"""Smoke tests for /predict/callback — no broker or worker needed."""
import base64

import cv2
import numpy as np
import pytest
import requests
from flask import Flask

from apis.predict_callback import predict_callback_bp
from engines.base import BasePredictor, DetectionResult
from tasks import detection
from tasks import detection_callback
from utils import request_id


class FakePredictor(BasePredictor):
    """Returns one fixed detection."""

    def load(self, model_path):
        pass

    def predict(self, image):
        assert image.ndim == 3 and image.shape[2] == 3
        return DetectionResult(
            boxes=np.array([[4.0, 8.0, 20.0, 32.0]]),
            scores=np.array([0.87]),
            class_ids=np.array([0]),
        )


@pytest.fixture()
def fake_delay(monkeypatch):
    """Replace task.delay so submissions never touch the broker."""
    calls = []

    class FakeAsyncResult:
        id = "fake-task-id"

    def _delay(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeAsyncResult()

    monkeypatch.setattr(detection_callback.detect_callback_task, "delay", _delay)
    return calls


@pytest.fixture()
def client(monkeypatch, fake_delay):
    monkeypatch.setattr(detection, "get_predictor", lambda: FakePredictor())
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.before_request(request_id.before_request)
    app.after_request(request_id.after_request)
    app.register_blueprint(predict_callback_bp)
    return app.test_client()


def _tiny_image_b64():
    img = np.zeros((64, 64, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return base64.b64encode(buf.tobytes()).decode("utf-8")


def test_submit_returns_task_id(client, fake_delay):
    resp = client.post("/predict/callback", json={
        "image": _tiny_image_b64(), "callback_url": "http://cb.local/result",
    })
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["code"] == 0
    assert body["data"]["task_id"] == "fake-task-id"
    # delay called with callback_url first, then the image kwargs
    assert fake_delay[0][0] == ("http://cb.local/result",)
    assert "image_b64" in fake_delay[0][1]


def test_submit_requires_callback_url(client):
    resp = client.post("/predict/callback", json={"image": _tiny_image_b64()})
    assert resp.status_code == 200
    assert resp.get_json()["code"] == 1


def test_submit_rejects_missing_input(client):
    resp = client.post("/predict/callback", json={"callback_url": "http://cb.local/result"})
    assert resp.get_json()["code"] == 1


def test_submit_rejects_both_inputs(client):
    resp = client.post("/predict/callback", json={
        "image": _tiny_image_b64(), "url": "http://x/y.jpg",
        "callback_url": "http://cb.local/result",
    })
    assert resp.get_json()["code"] == 1


def test_task_posts_success_envelope(monkeypatch):
    monkeypatch.setattr(detection, "get_predictor", lambda: FakePredictor())
    posted = {}

    def _fake_post(url, json=None, timeout=None):
        posted["url"] = url
        posted["json"] = json
        posted["timeout"] = timeout

    monkeypatch.setattr(detection_callback.requests, "post", _fake_post)

    result = detection_callback.detect_callback_task.run(
        "http://cb.local/result", image_b64=_tiny_image_b64()
    )
    assert result["code"] == 0
    assert posted["url"] == "http://cb.local/result"
    assert posted["json"]["code"] == 0
    assert len(posted["json"]["data"]["detections"]) == 1
    assert posted["json"]["data"]["detections"][0]["class"] == "person"


def test_task_posts_failure_envelope_on_bad_input(monkeypatch):
    monkeypatch.setattr(detection, "get_predictor", lambda: FakePredictor())
    posted = {}

    def _fake_post(url, json=None, timeout=None):
        posted["json"] = json

    monkeypatch.setattr(detection_callback.requests, "post", _fake_post)

    result = detection_callback.detect_callback_task.run(
        "http://cb.local/result", image_b64="!!not-base64!!"
    )
    assert result["code"] == 1
    assert posted["json"]["code"] == 1
    assert posted["json"]["data"] is None


def test_task_retries_failed_callback_post(monkeypatch):
    monkeypatch.setattr(detection, "get_predictor", lambda: FakePredictor())
    monkeypatch.setattr(detection_callback.time, "sleep", lambda _: None)

    calls = []

    def _fake_post_always_fails(url, json=None, timeout=None):
        calls.append(url)
        raise requests.ConnectionError("boom")

    monkeypatch.setattr(detection_callback.requests, "post", _fake_post_always_fails)

    with pytest.raises(requests.RequestException):
        detection_callback.detect_callback_task.run(
            "http://cb.local/result", image_b64=_tiny_image_b64()
        )
    # CALLBACK_MAX_RETRIES total attempts, then the task raises
    assert len(calls) == detection_callback.CALLBACK_MAX_RETRIES
