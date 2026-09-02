"""Smoke tests for the /predict/pipeline endpoint using fake predictors (no model needed)."""
import base64

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from apis.sync_pipeline import sync_pipeline_router
from engines.base import BasePredictor, ClassificationResult, DetectionResult
from tasks import classification, detection


class FakeDetectPredictor(BasePredictor):
    """Two fixed boxes: a car (kept by the default targets) and a person
    (filtered out by the target-class check)."""

    def load(self, model_path):
        pass

    def predict(self, image):
        assert image.ndim == 3 and image.shape[2] == 3
        return DetectionResult(
            boxes=np.array([[8.0, 8.0, 56.0, 56.0], [4.0, 4.0, 12.0, 12.0]]),
            scores=np.array([0.9, 0.8]),
            class_ids=np.array([2, 0]),  # car, person (COCO)
        )


class FakeClsPredictor(BasePredictor):
    """Fixed top-5; asserts the crop is a BGR sub-image (smaller than the
    original)."""

    def load(self, model_path):
        pass

    def predict(self, image):
        assert image.ndim == 3 and image.shape[2] == 3
        assert image.shape[0] <= 64 and image.shape[1] <= 64
        return ClassificationResult(
            scores=np.array([0.97, 0.95, 0.90, 0.85, 0.80]),
            class_ids=np.array([96, 95, 97, 94, 98]),  # toucan, jacamar, duck, ...
        )


@pytest.fixture()
def client(monkeypatch, app_factory):
    # The pipeline owns no predictors — it reuses the two tasks' seams.
    monkeypatch.setattr(detection, "get_predictor", lambda model=None: FakeDetectPredictor())
    monkeypatch.setattr(classification, "get_predictor", lambda model=None: FakeClsPredictor())
    return TestClient(app_factory(sync_pipeline_router))


def _tiny_image_b64():
    img = np.zeros((64, 64, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return base64.b64encode(buf.tobytes()).decode("utf-8")


def test_predict_pipeline_with_base64(client):
    resp = client.post("/predict/pipeline", json={"image": _tiny_image_b64()})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert len(body["data"]["items"]) == 1  # person filtered out by the default targets
    item = body["data"]["items"][0]
    assert item["detect_class"] == "car"
    assert item["fine_class"] == "toucan"
    assert item["fine_confidence"] == 0.97
    assert len(item["fine_top5"]) == 5
    assert item["fine_top5"][0]["class"] == "toucan"
    assert item["bbox"] == [8.0, 8.0, 56.0, 56.0]
    assert "image" in body["data"]


def test_predict_pipeline_targets_from_env(client, monkeypatch):
    monkeypatch.setenv("INFERFORGE_PIPELINE_TARGETS", "person")
    resp = client.post("/predict/pipeline", json={"image": _tiny_image_b64()})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert len(body["data"]["items"]) == 1  # car filtered out now
    assert body["data"]["items"][0]["detect_class"] == "person"


def test_predict_pipeline_unknown_target(client, monkeypatch):
    # a target the detect model does not know is a config error (code 3), not
    # an empty result
    monkeypatch.setenv("INFERFORGE_PIPELINE_TARGETS", "unicorn")
    resp = client.post("/predict/pipeline", json={"image": _tiny_image_b64()})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 3
    assert "INFERFORGE_PIPELINE_TARGETS" in body["message"]


def test_predict_pipeline_no_matching_boxes_skips_classifier(monkeypatch, app_factory):
    # no crop -> the classify predictor must never load
    monkeypatch.setattr(detection, "get_predictor", lambda model=None: FakeDetectPredictor())

    def _fail(model=None):
        raise AssertionError("classifier must not load when no box is kept")

    monkeypatch.setattr(classification, "get_predictor", _fail)
    monkeypatch.setenv("INFERFORGE_PIPELINE_TARGETS", "bicycle")
    client = TestClient(app_factory(sync_pipeline_router))
    resp = client.post("/predict/pipeline", json={"image": _tiny_image_b64()})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["items"] == []
    assert "image" in body["data"]  # still returns the (unannotated) image


def test_predict_pipeline_missing_input(client):
    # validation failures fold into the envelope (code=1), never HTTP 422
    resp = client.post("/predict/pipeline", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 1
    assert body["data"] is None


def test_predict_pipeline_both_inputs_rejected(client):
    resp = client.post("/predict/pipeline", json={"image": _tiny_image_b64(), "url": "http://x/y.jpg"})
    assert resp.status_code == 200
    assert resp.json()["code"] == 1


def test_predict_pipeline_invalid_base64(client):
    resp = client.post("/predict/pipeline", json={"image": "!!not-base64!!"})
    assert resp.status_code == 200
    assert resp.json()["code"] == 1


def test_response_has_request_id(client):
    resp = client.post("/predict/pipeline", json={"image": _tiny_image_b64()})
    rid = resp.headers.get("X-Request-ID")
    assert rid and len(rid) == 12


def test_request_ids_are_unique(client):
    r1 = client.post("/predict/pipeline", json={"image": _tiny_image_b64()}).headers["X-Request-ID"]
    r2 = client.post("/predict/pipeline", json={"image": _tiny_image_b64()}).headers["X-Request-ID"]
    assert r1 != r2
