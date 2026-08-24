"""Tests for the async feature switch in create_app.

Async is one deployment shape: INFERFORGE_ASYNC=1 registers the callback AND
query apis together (requires celery + rabbitmq + redis); INFERFORGE_QUERY=1
is accepted as a deprecated alias. Missing deps skip the whole async mode.
"""
import importlib.util

import pytest
from fastapi.testclient import TestClient

from app import create_app


def _route_paths(app):
    # The OpenAPI schema is the public, version-stable view of registered
    # paths (app.routes internals changed across starlette versions).
    return list(app.openapi()["paths"].keys())


@pytest.fixture()
def no_async_switch(monkeypatch):
    monkeypatch.delenv("INFERFORGE_ASYNC", raising=False)
    monkeypatch.delenv("INFERFORGE_QUERY", raising=False)
    monkeypatch.delenv("INFERFORGE_LLM", raising=False)
    monkeypatch.delenv("INFERFORGE_AGENT", raising=False)
    # create_app() reads these at construction; a dev .env (loaded by app.py)
    # could otherwise leak into test apps built via create_app()
    monkeypatch.delenv("INFERFORGE_API_KEY", raising=False)
    monkeypatch.delenv("INFERFORGE_RATE_LIMIT", raising=False)


def test_async_disabled_by_default(no_async_switch):
    routes = _route_paths(create_app())
    assert "/predict" in routes
    assert "/health" in routes
    assert "/health/ready" in routes
    assert "/predict/callback" not in routes
    assert "/predict/query" not in routes


def test_async_enabled_registers_both_apis(no_async_switch, monkeypatch):
    pytest.importorskip("redis")  # full async mode needs redis installed
    monkeypatch.setenv("INFERFORGE_ASYNC", "1")
    routes = _route_paths(create_app())
    assert "/predict/callback" in routes
    assert "/predict/query" in routes  # one switch, both async apis


def test_query_switch_is_deprecated_alias(no_async_switch, monkeypatch):
    pytest.importorskip("redis")
    monkeypatch.setenv("INFERFORGE_QUERY", "1")
    routes = _route_paths(create_app())
    assert "/predict/callback" in routes
    assert "/predict/query" in routes


@pytest.mark.skipif(
    importlib.util.find_spec("redis") is not None,
    reason="redis is installed — the missing-redis path is not exercisable here",
)
def test_async_skipped_without_redis(no_async_switch, monkeypatch):
    """Without redis the whole async mode is skipped, not just the query api."""
    monkeypatch.setenv("INFERFORGE_ASYNC", "1")
    routes = _route_paths(create_app())
    assert "/predict/callback" not in routes
    assert "/predict/query" not in routes


# --- vlm switch (INFERFORGE_LLM=1, needs INFERFORGE_ASYNC=1 too) ---


def test_vlm_disabled_without_async(no_async_switch, monkeypatch):
    monkeypatch.setenv("INFERFORGE_LLM", "1")
    routes = _route_paths(create_app())
    assert "/predict/vlm/callback" not in routes
    assert "/predict/vlm/query" not in routes


def test_vlm_enabled_registers_both_apis(no_async_switch, monkeypatch):
    pytest.importorskip("redis")  # full async mode needs redis installed
    monkeypatch.setenv("INFERFORGE_ASYNC", "1")
    monkeypatch.setenv("INFERFORGE_LLM", "1")
    routes = _route_paths(create_app())
    assert "/predict/callback" in routes
    assert "/predict/query" in routes
    assert "/predict/vlm/callback" in routes
    assert "/predict/vlm/query" in routes


def test_async_alone_leaves_vlm_out(no_async_switch, monkeypatch):
    pytest.importorskip("redis")
    monkeypatch.setenv("INFERFORGE_ASYNC", "1")
    routes = _route_paths(create_app())
    assert "/predict/callback" in routes
    assert "/predict/vlm/callback" not in routes
    assert "/predict/vlm/query" not in routes


# --- agent switch (INFERFORGE_AGENT=1, needs INFERFORGE_ASYNC=1 too) ---


def test_agent_disabled_without_async(no_async_switch, monkeypatch):
    monkeypatch.setenv("INFERFORGE_AGENT", "1")
    routes = _route_paths(create_app())
    assert "/predict/agent/callback" not in routes
    assert "/predict/agent/query" not in routes


def test_agent_enabled_registers_both_apis(no_async_switch, monkeypatch):
    pytest.importorskip("redis")  # full async mode needs redis installed
    monkeypatch.setenv("INFERFORGE_ASYNC", "1")
    monkeypatch.setenv("INFERFORGE_AGENT", "1")
    routes = _route_paths(create_app())
    assert "/predict/callback" in routes
    assert "/predict/agent/callback" in routes
    assert "/predict/agent/query" in routes


def test_async_alone_leaves_agent_out(no_async_switch, monkeypatch):
    pytest.importorskip("redis")
    monkeypatch.setenv("INFERFORGE_ASYNC", "1")
    routes = _route_paths(create_app())
    assert "/predict/callback" in routes
    assert "/predict/agent/callback" not in routes
    assert "/predict/agent/query" not in routes


# --- request-body ceiling ---


def test_body_size_limit_enforced(no_async_switch, monkeypatch):
    monkeypatch.setattr("app.MAX_BODY_SIZE", 64)
    resp = TestClient(create_app()).post("/predict", json={"image": "x" * 200})
    assert resp.status_code == 200  # the guard folds into the envelope, never 413
    body = resp.json()
    assert body["code"] == 1
    assert "too large" in body["message"]
    assert len(resp.headers["X-Request-ID"]) == 12  # guard envelope still traced


def test_small_body_passes_guard(no_async_switch, monkeypatch):
    monkeypatch.setattr("app.MAX_BODY_SIZE", 10 ** 6)
    resp = TestClient(create_app()).post("/predict", json={"image": "!!not-base64!!"})
    body = resp.json()
    assert body["code"] == 1
    assert "too large" not in body["message"]  # reached semantic validation instead
