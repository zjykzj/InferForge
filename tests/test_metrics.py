"""Smoke tests for the /metrics endpoint using a fake predictor (no model needed)."""
import base64

import cv2
import numpy as np
import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from apis.predict import predict_router
from engines.base import BasePredictor, DetectionResult
from tasks import detection


class FakePredictor(BasePredictor):
    """Returns one fixed detection; load/predict are no-ops."""

    def load(self, model_path):
        pass

    def predict(self, image):
        return DetectionResult(
            boxes=np.array([[4.0, 8.0, 20.0, 32.0]]),
            scores=np.array([0.87]),
            class_ids=np.array([0]),
        )


def _tiny_image_b64():
    img = np.zeros((64, 64, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return base64.b64encode(buf.tobytes()).decode("utf-8")


@pytest.fixture()
def client(monkeypatch, app_factory):
    monkeypatch.setattr(detection, "get_predictor", lambda: FakePredictor())
    return TestClient(app_factory(predict_router))


def test_metrics_endpoint(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert "inferforge_http_requests_total" in resp.text


def test_predict_counts_and_code(client):
    client.post("/predict", json={"image": _tiny_image_b64()})
    body = client.get("/metrics").text
    assert 'inferforge_http_requests_total{method="POST",route="/predict"}' in body
    assert 'inferforge_responses_total{code="0"}' in body


def test_validation_failure_code(client):
    client.post("/predict", json={})
    body = client.get("/metrics").text
    assert 'inferforge_responses_total{code="1"}' in body


def test_route_template_label(monkeypatch, app_factory):
    """The route label comes from the path template, not the raw request path."""
    router = APIRouter()

    @router.get("/items/{item_id}")
    def item(item_id: str):
        return {"code": 0, "message": "ok", "data": None}

    client = TestClient(app_factory(router))
    client.get("/items/42")
    body = client.get("/metrics").text
    assert 'route="/items/{item_id}"' in body
