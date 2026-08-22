"""Smoke tests for the API-key auth middleware (no model, no network).

AuthMiddleware reads INFERFORGE_API_KEY when the app is built, so tests set
the env before constructing the app. Counter states are global per process:
assert on presence, not exact counts.
"""
import pytest
from fastapi.testclient import TestClient

from apis.health import health_router
from apis.predict import predict_router

API_KEY = "test-secret-key"


@pytest.fixture()
def locked_app(monkeypatch, app_factory):
    monkeypatch.setenv("INFERFORGE_API_KEY", API_KEY)
    return app_factory(predict_router)


def test_auth_disabled_by_default(monkeypatch, app_factory):
    """No env -> every request passes through untouched (zero-cost mode)."""
    monkeypatch.delenv("INFERFORGE_API_KEY", raising=False)
    client = TestClient(app_factory(predict_router))
    resp = client.post("/predict", json={})
    assert resp.status_code == 200  # code=1 validation, NOT 401


def test_missing_key_returns_401_envelope(locked_app):
    client = TestClient(locked_app)
    resp = client.post("/predict", json={})
    assert resp.status_code == 401
    body = resp.json()
    assert body["code"] == 7
    assert body["data"] is None
    assert resp.headers.get("X-Request-ID")  # rejection still carries the id


def test_wrong_key_returns_401(locked_app):
    client = TestClient(locked_app)
    resp = client.post("/predict", json={}, headers={"X-API-Key": "wrong"})
    assert resp.status_code == 401
    assert resp.json()["code"] == 7


def test_correct_key_passes(locked_app):
    client = TestClient(locked_app)
    resp = client.post("/predict", json={}, headers={"X-API-Key": API_KEY})
    assert resp.status_code == 200
    assert resp.json()["code"] == 1  # validation error, auth passed


def test_probes_stay_anonymous(monkeypatch, app_factory):
    """Orchestrator probes are exempt even when auth is on."""
    monkeypatch.setenv("INFERFORGE_API_KEY", API_KEY)
    client = TestClient(app_factory(health_router))
    assert client.get("/health").status_code == 200
    assert client.get("/metrics").status_code == 200
