"""Smoke tests for the fixed-window rate limiter (no model, no network).

RateLimitMiddleware reads INFERFORGE_RATE_LIMIT when the app is built, so
tests set the env before constructing the app; each app gets fresh buckets.
"""
import pytest
from fastapi.testclient import TestClient

from apis.health import health_router
from apis.predict import predict_router


def _limited_app(monkeypatch, app_factory, limit, api_key=None):
    monkeypatch.setenv("INFERFORGE_RATE_LIMIT", str(limit))
    if api_key:
        monkeypatch.setenv("INFERFORGE_API_KEY", api_key)
    else:
        monkeypatch.delenv("INFERFORGE_API_KEY", raising=False)
    return app_factory(predict_router)


def test_disabled_by_default(monkeypatch, app_factory):
    """No env -> no limiting, any number of requests pass."""
    monkeypatch.delenv("INFERFORGE_RATE_LIMIT", raising=False)
    client = TestClient(app_factory(predict_router))
    for _ in range(10):
        resp = client.post("/predict", json={})
        assert resp.status_code == 200  # code=1 validation, not 429


def test_over_limit_returns_429_envelope(monkeypatch, app_factory):
    client = TestClient(_limited_app(monkeypatch, app_factory, limit=3))
    for _ in range(3):
        assert client.post("/predict", json={}).status_code == 200
    resp = client.post("/predict", json={})
    assert resp.status_code == 429
    body = resp.json()
    assert body["code"] == 8
    assert body["data"] is None
    assert int(resp.headers["Retry-After"]) >= 1
    assert resp.headers.get("X-Request-ID")  # rejection still carries the id


def test_probes_exempt(monkeypatch, app_factory):
    monkeypatch.setenv("INFERFORGE_RATE_LIMIT", "1")
    client = TestClient(app_factory(health_router))
    for _ in range(5):
        assert client.get("/health").status_code == 200
        assert client.get("/metrics").status_code == 200


def test_per_key_buckets_when_auth_on(monkeypatch, app_factory):
    """With auth enabled, each valid key gets its own bucket."""
    client = TestClient(_limited_app(monkeypatch, app_factory, limit=1, api_key="secret"))
    h1 = {"X-API-Key": "secret"}
    h2 = {"X-API-Key": "other-key"}

    assert client.post("/predict", json={}, headers=h1).status_code == 200
    assert client.post("/predict", json={}, headers=h1).status_code == 429
    # wrong key is rejected by auth (401) before the limiter ever sees it
    assert client.post("/predict", json={}, headers=h2).status_code == 401
