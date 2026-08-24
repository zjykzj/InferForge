"""Smoke tests for /predict/agent/callback — no broker or worker needed."""
import base64

import cv2
import numpy as np
import pytest
import requests
from fastapi.testclient import TestClient

from apis.predict_agent_callback import predict_agent_callback_router
from tasks import agent
from tasks import agent_callback
from tasks import detection_callback

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

    monkeypatch.setattr(agent_callback.agent_callback_task, "delay", _delay)
    return calls


@pytest.fixture()
def fake_agent(monkeypatch):
    """Replace _build_agent — the seam inside run_hair_count (its imported
    name binding in agent_callback is resolved at import time, so patching
    run_hair_count directly would not reach the task)."""
    class _FakeRunResult:
        output = agent.HairCountResult(
            total_persons=2, with_hair=1, without_hair=1,
            per_person=[agent.PersonHair(index=0, bbox=[0.0, 0.0, 1.0, 1.0], has_hair=False),
                        agent.PersonHair(index=1, bbox=[2.0, 2.0, 3.0, 3.0], has_hair=True)],
        )
        usage = None

    class _FakeAgent:
        def run_sync(self, messages, deps=None, model_settings=None):
            return _FakeRunResult()

    monkeypatch.setattr(agent, "_build_agent", _FakeAgent)


@pytest.fixture()
def client(monkeypatch, app_factory, fake_delay):
    return TestClient(app_factory(predict_agent_callback_router))


def _tiny_image_b64():
    img = np.zeros((64, 64, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return base64.b64encode(buf.tobytes()).decode("utf-8")


def _fake_post_capture(monkeypatch):
    """Capture the callback POST. post_callback lives in detection_callback and
    resolves requests/time in THAT module's namespace — patch there, not here."""
    posted = {}

    def _fake_post(url, json=None, timeout=None):
        posted["url"] = url
        posted["json"] = json
        posted["timeout"] = timeout

    monkeypatch.setattr(detection_callback.requests, "post", _fake_post)
    return posted


# --- submit ---


def test_submit_returns_task_id(client, fake_delay):
    resp = client.post("/predict/agent/callback", json={
        "image": _tiny_image_b64(), "callback_url": "http://cb.local/result",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["task_id"] == "fake-task-id"
    # delay called with callback_url first, then the image kwargs + request_id
    assert fake_delay[0][0] == ("http://cb.local/result",)
    assert "image_b64" in fake_delay[0][1]
    assert len(fake_delay[0][1]["request_id"]) == 12
    assert isinstance(fake_delay[0][1]["submitted_at"], float)  # queue-wait transport metadata


def test_submit_requires_callback_url(client):
    resp = client.post("/predict/agent/callback", json={"image": _tiny_image_b64()})
    assert resp.status_code == 200
    assert resp.json()["code"] == 1


def test_submit_rejects_missing_input(client):
    resp = client.post("/predict/agent/callback", json={"callback_url": "http://cb.local/result"})
    assert resp.json()["code"] == 1


def test_submit_rejects_both_inputs(client):
    resp = client.post("/predict/agent/callback", json={
        "image": _tiny_image_b64(), "url": "http://x/y.jpg",
        "callback_url": "http://cb.local/result",
    })
    assert resp.json()["code"] == 1


# --- task body ---


def test_task_posts_success_envelope(monkeypatch, fake_agent):
    posted = _fake_post_capture(monkeypatch)

    result = agent_callback.agent_callback_task.run(
        "http://cb.local/result", image_b64=_tiny_image_b64()
    )
    assert result["code"] == 0
    assert posted["url"] == "http://cb.local/result"
    assert posted["json"]["code"] == 0
    assert posted["json"]["data"] == FAKE_RESULT


def test_task_posts_failure_envelope_on_bad_input(monkeypatch, fake_agent):
    posted = _fake_post_capture(monkeypatch)

    result = agent_callback.agent_callback_task.run(
        "http://cb.local/result", image_b64="!!not-base64!!"
    )
    assert result["code"] == 1
    assert posted["json"]["code"] == 1
    assert posted["json"]["data"] is None


def test_task_posts_code9_envelope_on_upstream_failure(monkeypatch):
    def _build_fails():
        raise agent.LLMUpstreamError("timeout")

    monkeypatch.setattr(agent, "_build_agent", _build_fails)
    posted = _fake_post_capture(monkeypatch)

    result = agent_callback.agent_callback_task.run(
        "http://cb.local/result", image_b64=_tiny_image_b64()
    )
    assert result["code"] == 9
    assert posted["json"]["code"] == 9
    assert posted["json"]["message"] == "upstream LLM call failed: timeout"
    assert posted["json"]["data"] is None


def test_task_posts_code3_envelope_on_missing_config(monkeypatch):
    def _build_fails():
        raise agent.LLMConfigError("missing INFERFORGE_LLM_MODEL: set it to the remote model name")

    monkeypatch.setattr(agent, "_build_agent", _build_fails)
    posted = _fake_post_capture(monkeypatch)

    result = agent_callback.agent_callback_task.run(
        "http://cb.local/result", image_b64=_tiny_image_b64()
    )
    assert result["code"] == 3
    assert "INFERFORGE_LLM_MODEL" in posted["json"]["message"]


def test_task_retries_failed_callback_post(monkeypatch, fake_agent):
    monkeypatch.setattr(detection_callback.time, "sleep", lambda _: None)

    calls = []

    def _fake_post_always_fails(url, json=None, timeout=None):
        calls.append(url)
        raise requests.ConnectionError("boom")

    monkeypatch.setattr(detection_callback.requests, "post", _fake_post_always_fails)

    with pytest.raises(requests.RequestException):
        agent_callback.agent_callback_task.run(
            "http://cb.local/result", image_b64=_tiny_image_b64()
        )
    # CALLBACK_MAX_RETRIES total attempts, then the task raises
    assert len(calls) == detection_callback.CALLBACK_MAX_RETRIES


def test_code9_never_regenerated_while_post_retries(monkeypatch):
    upstream_calls = []

    def _build_fails():
        upstream_calls.append(1)
        raise agent.LLMUpstreamError("timeout")

    monkeypatch.setattr(agent, "_build_agent", _build_fails)
    monkeypatch.setattr(detection_callback.time, "sleep", lambda _: None)

    payloads = []

    def _fake_post_fails(url, json=None, timeout=None):
        payloads.append(json)
        raise requests.ConnectionError("boom")

    monkeypatch.setattr(detection_callback.requests, "post", _fake_post_fails)

    with pytest.raises(requests.RequestException):
        agent_callback.agent_callback_task.run(
            "http://cb.local/result", image_b64=_tiny_image_b64()
        )
    # the business call ran once; only the POST transport retried the same envelope
    assert len(upstream_calls) == 1
    assert len(payloads) == detection_callback.CALLBACK_MAX_RETRIES
    assert all(p["code"] == 9 for p in payloads)
