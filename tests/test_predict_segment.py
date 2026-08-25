"""Smoke tests for the /predict/segment endpoint using a fake predictor (no model needed)."""
import base64

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from engines.base import BasePredictor, SegmentationResult
from apis.predict_segment import predict_segment_router
from tasks import segmentation


class FakePredictor(BasePredictor):
    """Returns one fixed segment and asserts the input image shape."""

    def load(self, model_path):
        pass

    def predict(self, image):
        assert image.ndim == 3 and image.shape[2] == 3
        return SegmentationResult(
            boxes=np.array([[4.0, 8.0, 20.0, 32.0]]),
            scores=np.array([0.87]),
            class_ids=np.array([0]),
            masks=np.zeros((1, 64, 64), dtype=bool),  # matches the 64x64 test image
        )


@pytest.fixture()
def client(monkeypatch, app_factory):
    # The task owns its predictor; swap it out for the fake one.
    monkeypatch.setattr(segmentation, "get_predictor", lambda model=None: FakePredictor())
    return TestClient(app_factory(predict_segment_router))


def _tiny_image_b64():
    img = np.zeros((64, 64, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return base64.b64encode(buf.tobytes()).decode("utf-8")


def test_predict_segment_with_base64(client):
    resp = client.post("/predict/segment", json={"image": _tiny_image_b64()})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert isinstance(body["data"]["image"], str)
    assert len(body["data"]["segments"]) == 1
    seg = body["data"]["segments"][0]
    assert seg["class_id"] == 0
    assert seg["class"] == "person"
    assert seg["confidence"] == 0.87
    assert len(seg["bbox"]) == 4
    # the mask survives a base64 + PNG round-trip as a single-channel image
    mask = cv2.imdecode(
        np.frombuffer(base64.b64decode(seg["mask"]), dtype=np.uint8),
        cv2.IMREAD_UNCHANGED,
    )
    assert mask is not None
    assert mask.shape == (64, 64)
    assert mask.ndim == 2


def test_predict_segment_missing_input(client):
    # validation failures fold into the envelope (code=1), never HTTP 422
    resp = client.post("/predict/segment", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 1
    assert body["data"] is None


def test_predict_segment_both_inputs_rejected(client):
    resp = client.post("/predict/segment", json={"image": _tiny_image_b64(), "url": "http://x/y.jpg"})
    assert resp.status_code == 200
    assert resp.json()["code"] == 1


def test_predict_segment_invalid_base64(client):
    resp = client.post("/predict/segment", json={"image": "!!not-base64!!"})
    assert resp.status_code == 200
    assert resp.json()["code"] == 1


def test_response_has_request_id(client):
    resp = client.post("/predict/segment", json={"image": _tiny_image_b64()})
    rid = resp.headers.get("X-Request-ID")
    assert rid and len(rid) == 12


def test_request_ids_are_unique(client):
    r1 = client.post("/predict/segment", json={"image": _tiny_image_b64()}).headers["X-Request-ID"]
    r2 = client.post("/predict/segment", json={"image": _tiny_image_b64()}).headers["X-Request-ID"]
    assert r1 != r2
