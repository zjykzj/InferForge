"""Smoke tests for the /predict endpoint using a fake predictor (no model needed)."""
import base64

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from engines.base import BasePredictor, DetectionResult
from apis.predict import predict_router
from tasks import detection


class FakePredictor(BasePredictor):
    """Returns one fixed detection and asserts the input image shape."""

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
def client(monkeypatch, app_factory):
    # The task owns its predictors; swap them out for the fake one.
    monkeypatch.setattr(detection, "get_predictor", lambda model=None: FakePredictor())
    return TestClient(app_factory(predict_router))


def _tiny_image_b64():
    img = np.zeros((64, 64, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return base64.b64encode(buf.tobytes()).decode("utf-8")


def test_predict_with_base64(client):
    resp = client.post("/predict", json={"image": _tiny_image_b64()})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert isinstance(body["data"]["image"], str)
    assert len(body["data"]["detections"]) == 1
    det = body["data"]["detections"][0]
    assert det["class_id"] == 0
    assert det["class"] == "person"
    assert det["confidence"] == 0.87
    assert len(det["bbox"]) == 4


def test_predict_missing_input(client):
    # validation failures fold into the envelope (code=1), never HTTP 422
    resp = client.post("/predict", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 1
    assert body["data"] is None


def test_predict_both_inputs_rejected(client):
    resp = client.post("/predict", json={"image": _tiny_image_b64(), "url": "http://x/y.jpg"})
    assert resp.status_code == 200
    assert resp.json()["code"] == 1


def test_predict_invalid_base64(client):
    resp = client.post("/predict", json={"image": "!!not-base64!!"})
    assert resp.status_code == 200
    assert resp.json()["code"] == 1


def test_predict_unknown_model_returns_code10(client):
    resp = client.post("/predict", json={"image": _tiny_image_b64(), "model": "nope"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 10
    assert body["data"] is None


def test_predict_model_reaches_task_layer(client, monkeypatch):
    """The api layer passes the model through; the task layer routes on it."""
    seen = []

    def _spy(model=None):
        seen.append(model)
        return FakePredictor()

    monkeypatch.setattr(detection, "get_predictor", _spy)
    resp = client.post("/predict", json={"image": _tiny_image_b64(), "model": "yolov8n"})
    assert resp.json()["code"] == 0
    assert seen == ["yolov8n"]


def test_response_has_request_id(client):
    resp = client.post("/predict", json={"image": _tiny_image_b64()})
    rid = resp.headers.get("X-Request-ID")
    assert rid and len(rid) == 12


def test_request_ids_are_unique(client):
    r1 = client.post("/predict", json={"image": _tiny_image_b64()}).headers["X-Request-ID"]
    r2 = client.post("/predict", json={"image": _tiny_image_b64()}).headers["X-Request-ID"]
    assert r1 != r2
