"""Tests for the /health (liveness) and /health/ready (readiness) probes."""
import pytest
from fastapi.testclient import TestClient

from apis.health import health_router
from tasks import classification, detection, segmentation


@pytest.fixture()
def client(monkeypatch, app_factory):
    # The real predictor is never loaded in tests; pin the unloaded state so
    # the "not ready" path is deterministic regardless of test order. The
    # capability switches are cleared (readiness reads them at request time;
    # a dev .env could otherwise leak in).
    monkeypatch.delenv("INFERFORGE_SEG", raising=False)
    monkeypatch.delenv("INFERFORGE_CLS", raising=False)
    monkeypatch.setattr(detection, "_predictor", None)
    monkeypatch.setattr(segmentation, "_predictor", None)
    monkeypatch.setattr(classification, "_predictor", None)
    return TestClient(app_factory(health_router))


def test_liveness_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["status"] == "ok"


def test_readiness_not_loaded(client):
    resp = client.get("/health/ready")
    assert resp.status_code == 503  # probes read HTTP status, not the body
    body = resp.json()
    assert body["code"] == 6
    assert body["message"] == "model not loaded"
    assert body["data"] is None


def test_readiness_flips_after_predictor_loads(client, monkeypatch):
    # Simulate a first prediction warming the task layer: any non-None
    # predictor makes the real predictor_loaded() report ready.
    monkeypatch.setattr(detection, "_predictor", object())
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["status"] == "ready"


def test_readiness_requires_seg_model_when_enabled(client, monkeypatch):
    monkeypatch.setenv("INFERFORGE_SEG", "1")
    monkeypatch.setattr(detection, "_predictor", object())  # detection ready
    resp = client.get("/health/ready")
    assert resp.status_code == 503  # segment enabled but not loaded
    assert resp.json()["code"] == 6


def test_readiness_ready_when_seg_loaded(client, monkeypatch):
    monkeypatch.setenv("INFERFORGE_SEG", "1")
    monkeypatch.setattr(detection, "_predictor", object())
    monkeypatch.setattr(segmentation, "_predictor", object())
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json()["code"] == 0


def test_readiness_requires_cls_model_when_enabled(client, monkeypatch):
    monkeypatch.setenv("INFERFORGE_CLS", "1")
    monkeypatch.setattr(detection, "_predictor", object())
    resp = client.get("/health/ready")
    assert resp.status_code == 503  # classify enabled but not loaded
    assert resp.json()["code"] == 6


def test_readiness_ignores_disabled_capabilities(client, monkeypatch):
    # switches off: only detection's predictor state matters
    monkeypatch.setattr(detection, "_predictor", object())
    resp = client.get("/health/ready")
    assert resp.status_code == 200


def test_readiness_registered_by_app_factory(monkeypatch):
    """End-to-end through create_app: readiness returns 503 without a model."""
    monkeypatch.delenv("INFERFORGE_ASYNC", raising=False)
    monkeypatch.delenv("INFERFORGE_QUERY", raising=False)
    monkeypatch.delenv("INFERFORGE_SEG", raising=False)
    monkeypatch.delenv("INFERFORGE_CLS", raising=False)
    from app import create_app

    resp = TestClient(create_app()).get("/health/ready")
    assert resp.status_code == 503
    assert resp.json()["code"] == 6
