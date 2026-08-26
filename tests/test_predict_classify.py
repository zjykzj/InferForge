"""Smoke tests for the /predict/classify endpoint using a fake predictor (no model needed)."""
import base64

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from engines.base import BasePredictor, ClassificationResult
from apis.sync_classify import sync_classify_router
from tasks import classification


class FakePredictor(BasePredictor):
    """Returns a fixed top-5 and asserts the input image shape."""

    def load(self, model_path):
        pass

    def predict(self, image):
        assert image.ndim == 3 and image.shape[2] == 3
        return ClassificationResult(
            scores=np.array([0.97, 0.95, 0.90, 0.85, 0.80]),
            class_ids=np.array([96, 95, 97, 94, 98]),  # toucan, jacamar, duck, ...
        )


@pytest.fixture()
def client(monkeypatch, app_factory):
    # The task owns its predictor; swap it out for the fake one.
    monkeypatch.setattr(classification, "get_predictor", lambda model=None: FakePredictor())
    return TestClient(app_factory(sync_classify_router))


def _tiny_image_b64():
    img = np.zeros((64, 64, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return base64.b64encode(buf.tobytes()).decode("utf-8")


def test_predict_classify_with_base64(client):
    resp = client.post("/predict/classify", json={"image": _tiny_image_b64()})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert len(body["data"]["classifications"]) == 5
    first = body["data"]["classifications"][0]
    # the ImageNet table is wired through the task layer
    assert first["class_id"] == 96
    assert first["class"] == "toucan"
    assert first["confidence"] == 0.97
    assert "image" not in body["data"]  # classification returns text only


def test_predict_classify_missing_input(client):
    # validation failures fold into the envelope (code=1), never HTTP 422
    resp = client.post("/predict/classify", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 1
    assert body["data"] is None


def test_predict_classify_both_inputs_rejected(client):
    resp = client.post("/predict/classify", json={"image": _tiny_image_b64(), "url": "http://x/y.jpg"})
    assert resp.status_code == 200
    assert resp.json()["code"] == 1


def test_predict_classify_invalid_base64(client):
    resp = client.post("/predict/classify", json={"image": "!!not-base64!!"})
    assert resp.status_code == 200
    assert resp.json()["code"] == 1


def test_response_has_request_id(client):
    resp = client.post("/predict/classify", json={"image": _tiny_image_b64()})
    rid = resp.headers.get("X-Request-ID")
    assert rid and len(rid) == 12


def test_request_ids_are_unique(client):
    r1 = client.post("/predict/classify", json={"image": _tiny_image_b64()}).headers["X-Request-ID"]
    r2 = client.post("/predict/classify", json={"image": _tiny_image_b64()}).headers["X-Request-ID"]
    assert r1 != r2
