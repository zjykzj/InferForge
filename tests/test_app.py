"""Tests for the async feature switch in create_app.

Async is one deployment shape: INFERFORGE_ASYNC=1 registers the callback AND
query apis together (requires celery + rabbitmq + redis); INFERFORGE_QUERY=1
is accepted as a deprecated alias. Missing deps skip the whole async mode.
"""
import importlib.util

import pytest

from app import create_app


@pytest.fixture()
def no_async_switch(monkeypatch):
    monkeypatch.delenv("INFERFORGE_ASYNC", raising=False)
    monkeypatch.delenv("INFERFORGE_QUERY", raising=False)


def test_async_disabled_by_default(no_async_switch):
    app = create_app()
    routes = str(app.url_map)
    assert "/predict" in routes
    assert "/health" in routes
    assert "/health/ready" in routes
    assert "/predict/callback" not in routes
    assert "/predict/query" not in routes


def test_async_enabled_registers_both_apis(no_async_switch, monkeypatch):
    pytest.importorskip("redis")  # full async mode needs redis installed
    monkeypatch.setenv("INFERFORGE_ASYNC", "1")
    app = create_app()
    routes = str(app.url_map)
    assert "/predict/callback" in routes
    assert "/predict/query" in routes  # one switch, both async apis


def test_query_switch_is_deprecated_alias(no_async_switch, monkeypatch):
    pytest.importorskip("redis")
    monkeypatch.setenv("INFERFORGE_QUERY", "1")
    app = create_app()
    routes = str(app.url_map)
    assert "/predict/callback" in routes
    assert "/predict/query" in routes


@pytest.mark.skipif(
    importlib.util.find_spec("redis") is not None,
    reason="redis is installed — the missing-redis path is not exercisable here",
)
def test_async_skipped_without_redis(no_async_switch, monkeypatch):
    """Without redis the whole async mode is skipped, not just the query api."""
    monkeypatch.setenv("INFERFORGE_ASYNC", "1")
    app = create_app()
    routes = str(app.url_map)
    assert "/predict/callback" not in routes
    assert "/predict/query" not in routes
