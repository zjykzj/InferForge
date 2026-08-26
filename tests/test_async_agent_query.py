"""Smoke tests for /predict/agent/query — no broker, no redis, no model needed."""
import base64
import json

import cv2
import numpy as np
import pytest
import requests
from fastapi.testclient import TestClient

pytest.importorskip("redis")  # apis.async_agent_query -> utils.redis_store imports redis

from apis.async_agent_query import async_agent_query_router
from engines import registry
from tasks import agent
from tasks import agent_query
from utils import image as image_utils
from utils import redis_store

FAKE_RESULT = {
    "total_persons": 2,
    "with_hair": 1,
    "without_hair": 1,
    "per_person": [
        {"index": 0, "bbox": [0.0, 0.0, 1.0, 1.0], "has_hair": False},
        {"index": 1, "bbox": [2.0, 2.0, 3.0, 3.0], "has_hair": True},
    ],
}


@pytest.fixture()
def fake_delay(monkeypatch):
    """Replace task.delay so submissions never touch the broker."""
    calls = []

    class FakeAsyncResult:
        id = "fake-task-id"

    def _delay(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeAsyncResult()

    monkeypatch.setattr(agent_query.agent_query_task, "delay", _delay)
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


@pytest.fixture()
def fake_agent(monkeypatch):
    """Replace _build_agent — the seam inside run_hair_count (its imported
    name binding in agent_query is resolved at import time, so patching
    run_hair_count directly would not reach the task)."""
    class _FakeRunResult:
        output = agent.HairCountResult(
            total_persons=2, with_hair=1, without_hair=1,
            per_person=[agent.PersonHair(index=0, bbox=[0.0, 0.0, 1.0, 1.0], has_hair=False),
                        agent.PersonHair(index=1, bbox=[2.0, 2.0, 3.0, 3.0], has_hair=True)],
        )
        usage = None

    class _FakeAgent:
        def __init__(self, model):
            pass

        def run_sync(self, messages, deps=None, model_settings=None):
            return _FakeRunResult()

    monkeypatch.setattr(agent, "_build_agent", _FakeAgent)


@pytest.fixture()
def client(monkeypatch, app_factory, fake_delay, fake_redis):
    return TestClient(app_factory(async_agent_query_router))


def _tiny_image_b64():
    img = np.zeros((64, 64, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return base64.b64encode(buf.tobytes()).decode("utf-8")


def _store_envelope(fake_redis, task_id, envelope):
    fake_redis["values"][task_id] = json.dumps(envelope)


# --- submit ---


def test_submit_returns_task_id(client, fake_delay, fake_redis):
    resp = client.post("/predict/agent/query", json={"image": _tiny_image_b64()})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["task_id"] == "fake-task-id"
    # delay called with the image kwarg + request_id
    assert "image_b64" in fake_delay[0][1]
    assert len(fake_delay[0][1]["request_id"]) == 12
    assert isinstance(fake_delay[0][1]["submitted_at"], float)  # queue-wait transport metadata
    # pending marker written after submission
    assert fake_redis["values"]["fake-task-id"] == redis_store.PENDING_VALUE


def test_submit_rejects_missing_input(client):
    resp = client.post("/predict/agent/query", json={})
    assert resp.status_code == 200
    assert resp.json()["code"] == 1


def test_submit_rejects_both_inputs(client):
    resp = client.post("/predict/agent/query", json={
        "image": _tiny_image_b64(), "url": "http://x/y.jpg",
    })
    assert resp.json()["code"] == 1


def test_submit_passes_model_to_task(client, fake_delay):
    resp = client.post("/predict/agent/query", json={
        "image": _tiny_image_b64(), "model": "yolov8n",
    })
    assert resp.json()["code"] == 0
    assert fake_delay[0][1]["model"] == "yolov8n"


def test_submit_rejects_unknown_model_synchronously(client, fake_delay):
    resp = client.post("/predict/agent/query", json={
        "image": _tiny_image_b64(), "model": "ghost",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 10
    assert body["data"] is None
    assert fake_delay == []  # nothing queued: the caller knows immediately


def test_submit_delay_failure_returns_code3(monkeypatch, client):
    def _delay_fails(*args, **kwargs):
        raise RuntimeError("broker down")

    monkeypatch.setattr(agent_query.agent_query_task, "delay", _delay_fails)
    resp = client.post("/predict/agent/query", json={"image": _tiny_image_b64()})
    body = resp.json()
    assert body["code"] == 3
    assert body["data"] is None


def test_submit_redis_failure_returns_code3(client, fake_redis):
    fake_redis["fail_set_pending"] = True
    resp = client.post("/predict/agent/query", json={"image": _tiny_image_b64()})
    body = resp.json()
    assert body["code"] == 3
    assert body["data"] is None


# --- poll ---


def test_poll_pending(client, fake_redis):
    fake_redis["values"]["some-task-id"] = redis_store.PENDING_VALUE
    resp = client.get("/predict/agent/query/some-task-id")
    body = resp.json()
    assert body["code"] == 5
    assert body["data"] is None


def test_poll_not_found(client):
    resp = client.get("/predict/agent/query/unknown-task-id")
    body = resp.json()
    assert body["code"] == 4
    assert body["data"] is None


def test_poll_success_envelope_verbatim(client, fake_redis):
    envelope = {"code": 0, "message": "success", "data": FAKE_RESULT}
    _store_envelope(fake_redis, "done-task-id", envelope)
    resp = client.get("/predict/agent/query/done-task-id")
    assert resp.json() == envelope


def test_poll_code9_envelope_verbatim(client, fake_redis):
    envelope = {"code": 9, "message": "upstream LLM call failed: timeout", "data": None}
    _store_envelope(fake_redis, "failed-task-id", envelope)
    resp = client.get("/predict/agent/query/failed-task-id")
    assert resp.json() == envelope


def test_poll_corrupt_payload_returns_code3(client, fake_redis):
    fake_redis["values"]["corrupt-task-id"] = "{not json"
    resp = client.get("/predict/agent/query/corrupt-task-id")
    body = resp.json()
    assert body["code"] == 3
    assert body["data"] is None


def test_poll_non_envelope_payload_returns_code3(client, fake_redis):
    fake_redis["values"]["weird-task-id"] = "42"
    resp = client.get("/predict/agent/query/weird-task-id")
    body = resp.json()
    assert body["code"] == 3
    assert body["data"] is None


def test_poll_redis_failure_returns_code3(client, fake_redis):
    fake_redis["fail_get"] = True
    resp = client.get("/predict/agent/query/some-task-id")
    body = resp.json()
    assert body["code"] == 3
    assert body["data"] is None


# --- task body ---


def test_task_stores_success_envelope(monkeypatch, fake_redis, fake_agent):
    monkeypatch.setattr(agent_query.agent_query_task.request, "id", "task-under-test")

    result = agent_query.agent_query_task.run(image_b64=_tiny_image_b64())
    assert result["code"] == 0
    stored = json.loads(fake_redis["values"]["task-under-test"])
    assert stored["code"] == 0
    assert stored["data"] == FAKE_RESULT


def test_task_stores_failure_envelope_on_bad_input(monkeypatch, fake_redis, fake_agent):
    monkeypatch.setattr(agent_query.agent_query_task.request, "id", "task-under-test")

    result = agent_query.agent_query_task.run(image_b64="!!not-base64!!")
    assert result["code"] == 1
    stored = json.loads(fake_redis["values"]["task-under-test"])
    assert stored["code"] == 1
    assert stored["data"] is None


def test_task_stores_download_failure_envelope(monkeypatch, fake_redis, fake_agent):
    monkeypatch.setattr(agent_query.agent_query_task.request, "id", "task-under-test")

    def _url_fails(url):
        raise requests.RequestException("boom")

    monkeypatch.setattr(image_utils, "url_to_image", _url_fails)

    result = agent_query.agent_query_task.run(image_url="http://x/y.jpg")
    assert result["code"] == 2
    stored = json.loads(fake_redis["values"]["task-under-test"])
    assert stored["code"] == 2
    assert "failed to download image" in stored["message"]


def test_task_stores_code10_envelope_on_unknown_model(monkeypatch, fake_redis):
    # web/worker registry drift defense: a model name that passed submit-time
    # validation on the web must not crash the worker if its registry copy
    # lacks it — the worker reports code 10 instead of failing the task.
    monkeypatch.setattr(agent_query.agent_query_task.request, "id", "task-under-test")
    registry.reset_cache()  # task runs "on the worker": re-read the registry

    result = agent_query.agent_query_task.run(image_b64=_tiny_image_b64(), model="ghost")
    assert result["code"] == 10
    stored = json.loads(fake_redis["values"]["task-under-test"])
    assert stored["code"] == 10
    assert stored["data"] is None


def test_task_stores_code9_envelope_on_upstream_failure(monkeypatch, fake_redis):
    def _build_fails(model):
        raise agent.LLMUpstreamError("timeout")

    monkeypatch.setattr(agent, "_build_agent", _build_fails)
    monkeypatch.setattr(agent_query.agent_query_task.request, "id", "task-under-test")

    result = agent_query.agent_query_task.run(image_b64=_tiny_image_b64())
    assert result["code"] == 9
    stored = json.loads(fake_redis["values"]["task-under-test"])
    assert stored["code"] == 9
    assert stored["message"] == "upstream LLM call failed: timeout"


def test_task_stores_code3_envelope_on_missing_config(monkeypatch, fake_redis):
    def _build_fails(model):
        raise agent.LLMConfigError("missing INFERFORGE_LLM_MODEL: set it to the remote model name")

    monkeypatch.setattr(agent, "_build_agent", _build_fails)
    monkeypatch.setattr(agent_query.agent_query_task.request, "id", "task-under-test")

    result = agent_query.agent_query_task.run(image_b64=_tiny_image_b64())
    assert result["code"] == 3
    stored = json.loads(fake_redis["values"]["task-under-test"])
    assert "INFERFORGE_LLM_MODEL" in stored["message"]


def test_task_redis_failure_propagates(monkeypatch, fake_redis, fake_agent):
    monkeypatch.setattr(agent_query.agent_query_task.request, "id", "task-under-test")
    fake_redis["fail_set_result"] = True

    # a redis outage must surface as a task failure, never a silent result loss
    with pytest.raises(RuntimeError):
        agent_query.agent_query_task.run(image_b64=_tiny_image_b64())
