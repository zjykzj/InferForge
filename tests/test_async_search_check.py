"""Smoke tests for /predict/search/check — same shape as the search query api
(see test_async_search_query.py for the full submit/poll coverage); this file
focuses on the check-specific task payload."""
import base64
import json

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

pytest.importorskip("redis")  # apis.async_search_check -> utils.redis_store imports redis

from apis.async_search_check import async_search_check_router
from engines.base import BasePredictor, EmbeddingResult
from tasks import embedding, search
from tasks import search_check_query
from utils import redis_store


class FakeEmbedPredictor(BasePredictor):
    def load(self, model_path):
        pass

    def predict(self, image):
        v = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        return EmbeddingResult(vector=v)


@pytest.fixture()
def fake_delay(monkeypatch):
    calls = []

    class FakeAsyncResult:
        id = "fake-task-id"

    def _delay(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeAsyncResult()

    monkeypatch.setattr(search_check_query.search_check_query_task, "delay", _delay)
    return calls


@pytest.fixture()
def fake_redis(monkeypatch):
    store = {"values": {}, "fail_set_pending": False}

    def _set_pending(task_id):
        if store["fail_set_pending"]:
            raise RuntimeError("redis down")
        store["values"].setdefault(task_id, redis_store.PENDING_VALUE)

    def _set_result(task_id, envelope):
        store["values"][task_id] = json.dumps(envelope)

    def _get_result(task_id):
        return store["values"].get(task_id)

    monkeypatch.setattr(redis_store, "set_pending", _set_pending)
    monkeypatch.setattr(redis_store, "set_result", _set_result)
    monkeypatch.setattr(redis_store, "get_result", _get_result)
    return store


@pytest.fixture(autouse=True)
def fake_search(monkeypatch):
    monkeypatch.setattr(embedding, "get_embedder", lambda model=None: FakeEmbedPredictor())
    monkeypatch.setattr(
        search, "search_gallery",
        lambda vector, top_k=1: [{"id": "bus.jpg", "path": "gallery/bus.jpg", "score": 0.991}],
    )


@pytest.fixture()
def client(monkeypatch, app_factory, fake_delay, fake_redis):
    return TestClient(app_factory(async_search_check_router))


def _tiny_image_b64():
    img = np.zeros((64, 64, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return base64.b64encode(buf.tobytes()).decode("utf-8")


def test_submit_returns_task_id(client, fake_delay, fake_redis):
    resp = client.post("/predict/search/check", json={"image": _tiny_image_b64()})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["task_id"] == "fake-task-id"
    assert fake_redis["values"]["fake-task-id"] == redis_store.PENDING_VALUE


def test_submit_rejects_missing_input(client):
    resp = client.post("/predict/search/check", json={})
    assert resp.status_code == 200
    assert resp.json()["code"] == 1


def test_poll_returns_stored_envelope_verbatim(client, fake_redis):
    envelope = {"code": 0, "message": "success",
                "data": {"found": True,
                         "match": {"id": "bus.jpg", "path": "gallery/bus.jpg", "score": 0.991},
                         "threshold": 0.95}}
    fake_redis["values"]["done-task-id"] = json.dumps(envelope)
    resp = client.get("/predict/search/check/done-task-id")
    assert resp.json() == envelope


def test_task_stores_found_envelope(monkeypatch, fake_redis):
    monkeypatch.setattr(search_check_query.search_check_query_task.request, "id", "task-under-test")

    result = search_check_query.search_check_query_task.run(image_b64=_tiny_image_b64())
    assert result["code"] == 0
    stored = json.loads(fake_redis["values"]["task-under-test"])
    assert stored["code"] == 0
    assert stored["data"]["found"] is True
    assert stored["data"]["match"]["id"] == "bus.jpg"


def test_task_stores_not_found_envelope(monkeypatch, fake_redis):
    monkeypatch.setattr(search, "search_gallery", lambda vector, top_k=1: [])
    monkeypatch.setattr(search_check_query.search_check_query_task.request, "id", "task-under-test")

    result = search_check_query.search_check_query_task.run(image_b64=_tiny_image_b64())
    assert result["code"] == 0
    stored = json.loads(fake_redis["values"]["task-under-test"])
    assert stored["data"]["found"] is False
    assert stored["data"]["match"] is None


def test_task_stores_failure_envelope_on_bad_input(monkeypatch, fake_redis):
    monkeypatch.setattr(search_check_query.search_check_query_task.request, "id", "task-under-test")

    result = search_check_query.search_check_query_task.run(image_b64="!!not-base64!!")
    assert result["code"] == 1
    stored = json.loads(fake_redis["values"]["task-under-test"])
    assert stored["code"] == 1
    assert stored["data"] is None
