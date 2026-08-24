"""Smoke tests for /predict/vlm/callback — no broker or worker needed."""
import base64

import cv2
import numpy as np
import pytest
import requests
from fastapi.testclient import TestClient

from apis.predict_vlm_callback import predict_vlm_callback_router
from tasks import detection_callback
from tasks import vlm
from tasks import vlm_callback


@pytest.fixture()
def fake_delay(monkeypatch):
    """Replace task.delay so submissions never touch the broker."""
    calls = []

    class FakeAsyncResult:
        id = "fake-task-id"

    def _delay(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeAsyncResult()

    monkeypatch.setattr(vlm_callback.vlm_callback_task, "delay", _delay)
    return calls


@pytest.fixture()
def fake_remote_llm(monkeypatch):
    """Replace the remote call with a fixed answer (no openai, no network)."""
    monkeypatch.setattr(
        vlm, "_call_remote_llm",
        lambda data_url, prompt: ("a fixed answer", "test-model"),
    )


@pytest.fixture()
def client(monkeypatch, app_factory, fake_delay):
    return TestClient(app_factory(predict_vlm_callback_router))


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
    resp = client.post("/predict/vlm/callback", json={
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


def test_submit_requires_callback_url(client):
    resp = client.post("/predict/vlm/callback", json={"image": _tiny_image_b64()})
    assert resp.status_code == 200
    assert resp.json()["code"] == 1


def test_submit_rejects_missing_input(client):
    resp = client.post("/predict/vlm/callback", json={"callback_url": "http://cb.local/result"})
    assert resp.json()["code"] == 1


def test_submit_rejects_both_inputs(client):
    resp = client.post("/predict/vlm/callback", json={
        "image": _tiny_image_b64(), "url": "http://x/y.jpg",
        "callback_url": "http://cb.local/result",
    })
    assert resp.json()["code"] == 1


# --- task body ---


def test_task_posts_success_envelope(monkeypatch, fake_remote_llm):
    posted = _fake_post_capture(monkeypatch)

    result = vlm_callback.vlm_callback_task.run(
        "http://cb.local/result", image_b64=_tiny_image_b64()
    )
    assert result["code"] == 0
    assert posted["url"] == "http://cb.local/result"
    assert posted["json"]["code"] == 0
    assert posted["json"]["data"] == {"answer": "a fixed answer", "model": "test-model"}


def test_task_posts_failure_envelope_on_bad_input(monkeypatch, fake_remote_llm):
    posted = _fake_post_capture(monkeypatch)

    result = vlm_callback.vlm_callback_task.run(
        "http://cb.local/result", image_b64="!!not-base64!!"
    )
    assert result["code"] == 1
    assert posted["json"]["code"] == 1
    assert posted["json"]["data"] is None


def test_task_posts_code9_envelope_on_upstream_failure(monkeypatch):
    def _upstream_fails(data_url, prompt):
        raise vlm.LLMUpstreamError("timeout")

    monkeypatch.setattr(vlm, "_call_remote_llm", _upstream_fails)
    posted = _fake_post_capture(monkeypatch)

    result = vlm_callback.vlm_callback_task.run(
        "http://cb.local/result", image_b64=_tiny_image_b64()
    )
    assert result["code"] == 9
    assert posted["json"]["code"] == 9
    assert posted["json"]["message"] == "upstream LLM call failed: timeout"
    assert posted["json"]["data"] is None


def test_task_posts_code3_envelope_on_missing_config(monkeypatch):
    # no _call_remote_llm patch: real config validation fails BEFORE any openai
    # import (that order is deliberate in tasks.vlm)
    monkeypatch.delenv("INFERFORGE_LLM_MODEL", raising=False)
    monkeypatch.setattr(vlm, "_client", None)
    posted = _fake_post_capture(monkeypatch)

    result = vlm_callback.vlm_callback_task.run(
        "http://cb.local/result", image_b64=_tiny_image_b64()
    )
    assert result["code"] == 3
    assert "INFERFORGE_LLM_MODEL" in posted["json"]["message"]


def test_task_retries_failed_callback_post(monkeypatch, fake_remote_llm):
    monkeypatch.setattr(detection_callback.time, "sleep", lambda _: None)

    calls = []

    def _fake_post_always_fails(url, json=None, timeout=None):
        calls.append(url)
        raise requests.ConnectionError("boom")

    monkeypatch.setattr(detection_callback.requests, "post", _fake_post_always_fails)

    with pytest.raises(requests.RequestException):
        vlm_callback.vlm_callback_task.run(
            "http://cb.local/result", image_b64=_tiny_image_b64()
        )
    # CALLBACK_MAX_RETRIES total attempts, then the task raises
    assert len(calls) == detection_callback.CALLBACK_MAX_RETRIES


def test_code9_never_regenerated_while_post_retries(monkeypatch):
    upstream_calls = []

    def _upstream_fails(data_url, prompt):
        upstream_calls.append(1)
        raise vlm.LLMUpstreamError("timeout")

    monkeypatch.setattr(vlm, "_call_remote_llm", _upstream_fails)
    monkeypatch.setattr(detection_callback.time, "sleep", lambda _: None)

    payloads = []

    def _fake_post_fails(url, json=None, timeout=None):
        payloads.append(json)
        raise requests.ConnectionError("boom")

    monkeypatch.setattr(detection_callback.requests, "post", _fake_post_fails)

    with pytest.raises(requests.RequestException):
        vlm_callback.vlm_callback_task.run(
            "http://cb.local/result", image_b64=_tiny_image_b64()
        )
    # the business call ran once; only the POST transport retried the same envelope
    assert len(upstream_calls) == 1
    assert len(payloads) == detection_callback.CALLBACK_MAX_RETRIES
    assert all(p["code"] == 9 for p in payloads)
