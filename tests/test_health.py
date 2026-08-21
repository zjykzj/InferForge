"""Tests for the /health (liveness) and /health/ready (readiness) probes."""
import pytest
from flask import Flask

from apis.health import health_bp
from tasks import detection


@pytest.fixture()
def client(monkeypatch):
    # The real predictor is never loaded in tests; pin the unloaded state so
    # the "not ready" path is deterministic regardless of test order.
    monkeypatch.setattr(detection, "_predictor", None)
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(health_bp)
    return app.test_client()


def test_liveness_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["code"] == 0
    assert body["data"]["status"] == "ok"


def test_readiness_not_loaded(client):
    resp = client.get("/health/ready")
    assert resp.status_code == 503  # probes read HTTP status, not the body
    body = resp.get_json()
    assert body["code"] == 6
    assert body["message"] == "model not loaded"
    assert body["data"] is None


def test_readiness_flips_after_predictor_loads(client, monkeypatch):
    # Simulate a first prediction warming the task layer: any non-None
    # predictor makes the real predictor_loaded() report ready.
    monkeypatch.setattr(detection, "_predictor", object())
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["code"] == 0
    assert body["data"]["status"] == "ready"


def test_readiness_registered_by_app_factory(monkeypatch):
    """End-to-end through create_app: readiness returns 503 without a model."""
    monkeypatch.delenv("INFERFORGE_ASYNC", raising=False)
    monkeypatch.delenv("INFERFORGE_QUERY", raising=False)
    from app import create_app

    app = create_app()
    app.config["TESTING"] = True
    resp = app.test_client().get("/health/ready")
    assert resp.status_code == 503
    assert resp.get_json()["code"] == 6
