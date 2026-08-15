"""Tests for the async feature switch in create_app."""
import pytest

from app import create_app


def test_async_disabled_by_default(monkeypatch):
    monkeypatch.delenv("INFERFORGE_ASYNC", raising=False)
    app = create_app()
    routes = str(app.url_map)
    assert "/predict" in routes
    assert "/predict/callback" not in routes


def test_async_enabled(monkeypatch):
    monkeypatch.setenv("INFERFORGE_ASYNC", "1")
    app = create_app()
    assert "/predict/callback" in str(app.url_map)
