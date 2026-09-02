"""Smoke tests for /predict/search/query — no broker, no redis, no milvus, no model needed."""
import base64
import json

import cv2
import numpy as np
import pytest
import requests
from fastapi.testclient import TestClient

pytest.importorskip("redis")  # apis.async_search_query -> utils.redis_store imports redis

from apis.async_search_query import async_search_query_router
from engines.base import BasePredictor, EmbeddingResult
from tasks import embedding, search
from tasks import search_query
from utils import errors, image as image_utils
from utils import redis_store


class FakeEmbedPredictor(BasePredictor):
    def load(self, model_path):
        pass

    def predict(self, image):
        v = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        return EmbeddingResult(vector=v)


@pytest.fixture()
def fake_delay(monkeypatch):
    """Replace task.delay so submissions never touch the broker."""
    calls = []

    class FakeAsyncResult:
        id = "fake-task-id"

    def _delay(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeAsyncResult()

    monkeypatch.setattr(search_query.search_query_task, "delay", _delay)
    return calls


@pytest.fixture()
def fake_redis(monkeypatch):
    """In-memory stand-in for utils.redis_store (no real redis, no network)."""
    store = {"values": {}, "fail_set_pending": False, "fail_set_result": False,
             "fail_get": False}

    def _set_pending(task_id):
        if store["fail_set_pending"]:
            raise RuntimeError("redis down")
        store["values"].setdefault(task_id, redis_store.PENDING_VALUE)  # NX semantics

    def _set_result(task_id, envelope):
        if store["fail_set_result"]:
            raise RuntimeError("redis down")
        store["values"][task_id] = json.dumps(envelope)

    def _get_result(task_id):
        if store["fail_get"]:
            raise RuntimeError("redis down")
        return store["values"].get(task_id)

    monkeypatch.setattr(redis_store, "set_pending", _set_pending)
    monkeypatch.setattr(redis_store, "set_result", _set_result)
    monkeypatch.setattr(redis_store, "get_result", _get_result)
    return store


@pytest.fixture(autouse=True)
def fake_search(monkeypatch):
    """Fixed gallery hits + fake embedder (no model, no milvus, no network)."""
    monkeypatch.setattr(embedding, "get_embedder", lambda model=None: FakeEmbedPredictor())
    monkeypatch.setattr(
        search, "search_gallery",
        lambda vector, top_k=5: [{"id": "bus.jpg", "path": "gallery/bus.jpg", "score": 0.991}][:top_k],
    )


@pytest.fixture()
def client(monkeypatch, app_factory, fake_delay, fake_redis):
    return TestClient(app_factory(async_search_query_router))


def _tiny_image_b64():
    img = np.zeros((64, 64, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return base64.b64encode(buf.tobytes()).decode("utf-8")


def _store_envelope(fake_redis, task_id, envelope):
    fake_redis["values"][task_id] = json.dumps(envelope)


# --- submit ---


def test_submit_returns_task_id(client, fake_delay, fake_redis):
    resp = client.post("/predict/search/query", json={"image": _tiny_image_b64(), "top_k": 3})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["task_id"] == "fake-task-id"
    assert fake_delay[0][1]["top_k"] == 3  # request top_k travels with the task
    assert len(fake_delay[0][1]["request_id"]) == 12
    assert isinstance(fake_delay[0][1]["submitted_at"], float)  # queue-wait transport metadata
    assert fake_redis["values"]["fake-task-id"] == redis_store.PENDING_VALUE


def test_submit_rejects_missing_input(client):
    resp = client.post("/predict/search/query", json={})
    assert resp.status_code == 200
    assert resp.json()["code"] == 1


def test_submit_delay_failure_returns_code3(monkeypatch, client):
    def _delay_fails(*args, **kwargs):
        raise RuntimeError("broker down")

    monkeypatch.setattr(search_query.search_query_task, "delay", _delay_fails)
    resp = client.post("/predict/search/query", json={"image": _tiny_image_b64()})
    body = resp.json()
    assert body["code"] == 3
    assert body["data"] is None


def test_submit_redis_failure_returns_code3(client, fake_redis):
    fake_redis["fail_set_pending"] = True
    resp = client.post("/predict/search/query", json={"image": _tiny_image_b64()})
    body = resp.json()
    assert body["code"] == 3
    assert body["data"] is None


# --- poll ---


def test_poll_pending(client, fake_redis):
    fake_redis["values"]["some-task-id"] = redis_store.PENDING_VALUE
    resp = client.get("/predict/search/query/some-task-id")
    body = resp.json()
    assert body["code"] == 5
    assert body["data"] is None


def test_poll_not_found(client):
    resp = client.get("/predict/search/query/unknown-task-id")
    body = resp.json()
    assert body["code"] == 4
    assert body["data"] is None


def test_poll_success_envelope_verbatim(client, fake_redis):
    envelope = {"code": 0, "message": "success",
                "data": {"matches": [{"id": "bus.jpg", "path": "gallery/bus.jpg", "score": 0.991}],
                         "count": 1}}
    _store_envelope(fake_redis, "done-task-id", envelope)
    resp = client.get("/predict/search/query/done-task-id")
    assert resp.json() == envelope


def test_poll_corrupt_payload_returns_code3(client, fake_redis):
    fake_redis["values"]["corrupt-task-id"] = "{not json"
    resp = client.get("/predict/search/query/corrupt-task-id")
    body = resp.json()
    assert body["code"] == 3
    assert body["data"] is None


def test_poll_redis_failure_returns_code3(client, fake_redis):
    fake_redis["fail_get"] = True
    resp = client.get("/predict/search/query/some-task-id")
    body = resp.json()
    assert body["code"] == 3
    assert body["data"] is None


# --- task body ---


def test_task_stores_success_envelope(monkeypatch, fake_redis):
    monkeypatch.setattr(search_query.search_query_task.request, "id", "task-under-test")

    result = search_query.search_query_task.run(image_b64=_tiny_image_b64(), top_k=1)
    assert result["code"] == 0
    stored = json.loads(fake_redis["values"]["task-under-test"])
    assert stored["code"] == 0
    assert stored["data"]["count"] == 1
    assert stored["data"]["matches"][0]["id"] == "bus.jpg"


def test_task_stores_failure_envelope_on_bad_input(monkeypatch, fake_redis):
    monkeypatch.setattr(search_query.search_query_task.request, "id", "task-under-test")

    result = search_query.search_query_task.run(image_b64="!!not-base64!!")
    assert result["code"] == 1
    stored = json.loads(fake_redis["values"]["task-under-test"])
    assert stored["code"] == 1
    assert stored["data"] is None


def test_task_stores_download_failure_envelope(monkeypatch, fake_redis):
    monkeypatch.setattr(search_query.search_query_task.request, "id", "task-under-test")

    def _url_fails(url):
        raise requests.RequestException("boom")

    monkeypatch.setattr(image_utils, "url_to_image", _url_fails)

    result = search_query.search_query_task.run(image_url="http://x/y.jpg")
    assert result["code"] == 2
    stored = json.loads(fake_redis["values"]["task-under-test"])
    assert stored["code"] == 2
    assert "failed to download image" in stored["message"]


def test_task_stores_code10_envelope_on_missing_embed_model(monkeypatch, fake_redis):
    def _no_model(image, model=None):
        raise errors.ModelNotFound("no embed model is registered")

    monkeypatch.setattr(embedding, "encode", _no_model)
    monkeypatch.setattr(search_query.search_query_task.request, "id", "task-under-test")

    result = search_query.search_query_task.run(image_b64=_tiny_image_b64())
    assert result["code"] == 10
    stored = json.loads(fake_redis["values"]["task-under-test"])
    assert stored["code"] == 10


def test_task_redis_failure_propagates(monkeypatch, fake_redis):
    monkeypatch.setattr(search_query.search_query_task.request, "id", "task-under-test")
    fake_redis["fail_set_result"] = True

    # a redis outage must surface as a task failure, never a silent result loss
    with pytest.raises(RuntimeError):
        search_query.search_query_task.run(image_b64=_tiny_image_b64())
