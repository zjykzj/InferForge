"""Tests for the async feature switch in create_app."""
import pytest

from app import create_app


def test_async_disabled_by_default(monkeypatch):
    monkeypatch.delenv("INFERFORGE_ASYNC", raising=False)
    monkeypatch.delenv("INFERFORGE_QUERY", raising=False)
    app = create_app()
    routes = str(app.url_map)
    assert "/predict" in routes
    assert "/predict/callback" not in routes
    assert "/predict/query" not in routes


def test_async_enabled(monkeypatch):
    monkeypatch.setenv("INFERFORGE_ASYNC", "1")
    monkeypatch.delenv("INFERFORGE_QUERY", raising=False)
    app = create_app()
    routes = str(app.url_map)
    assert "/predict/callback" in routes
    assert "/predict/query" not in routes  # query needs its own switch


def test_async_query_enabled(monkeypatch):
    pytest.importorskip("redis")
    monkeypatch.setenv("INFERFORGE_ASYNC", "1")
    monkeypatch.setenv("INFERFORGE_QUERY", "1")
    app = create_app()
    assert "/predict/callback" in str(app.url_map)
    assert "/predict/query" in str(app.url_map)
