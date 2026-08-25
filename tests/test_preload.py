"""Tests for startup model warmup (INFERFORGE_PRELOAD=1) — no model needed.

The wiring lives in two places that tests must not import (celery_app — see
CLAUDE.md) or only exercise via the app factory: the worker signal handler
is a one-line delegate to tasks.warmup.preload_worker, which is what these
tests target.
"""
import pytest
from fastapi.testclient import TestClient

from tasks import classification, detection, segmentation, warmup


@pytest.fixture()
def no_switches(monkeypatch):
    """Capability switches off; a dev .env (loaded when `app` is imported)
    could otherwise leak into create_app()."""
    monkeypatch.delenv("INFERFORGE_PRELOAD", raising=False)
    monkeypatch.delenv("INFERFORGE_SEG", raising=False)
    monkeypatch.delenv("INFERFORGE_CLS", raising=False)
    monkeypatch.delenv("INFERFORGE_ASYNC", raising=False)
    monkeypatch.delenv("INFERFORGE_QUERY", raising=False)
    monkeypatch.delenv("INFERFORGE_LLM", raising=False)
    monkeypatch.delenv("INFERFORGE_AGENT", raising=False)
    monkeypatch.delenv("INFERFORGE_API_KEY", raising=False)
    monkeypatch.delenv("INFERFORGE_RATE_LIMIT", raising=False)


def _spies(monkeypatch):
    """Replace the three task preloads with recording no-ops."""
    calls = []

    def _spy(name):
        def _fn():
            calls.append(name)
        return _fn

    monkeypatch.setattr(detection, "preload", _spy("detect"))
    monkeypatch.setattr(segmentation, "preload", _spy("segment"))
    monkeypatch.setattr(classification, "preload", _spy("classify"))
    return calls


def test_switch_off_is_noop(no_switches, monkeypatch):
    calls = _spies(monkeypatch)
    warmup.preload_web()
    warmup.preload_worker()
    assert calls == []


def test_preload_web_loads_detect_always(no_switches, monkeypatch):
    monkeypatch.setenv("INFERFORGE_PRELOAD", "1")
    calls = _spies(monkeypatch)
    warmup.preload_web()
    assert calls == ["detect"]


def test_preload_web_respects_capability_switches(no_switches, monkeypatch):
    monkeypatch.setenv("INFERFORGE_PRELOAD", "1")
    monkeypatch.setenv("INFERFORGE_SEG", "1")
    calls = _spies(monkeypatch)
    warmup.preload_web()
    assert calls == ["detect", "segment"]  # classify switch off


def test_preload_worker_loads_only_detection(no_switches, monkeypatch):
    # segment/classify are sync-only apis: the async worker must not waste
    # memory preloading models it can never serve a request with.
    monkeypatch.setenv("INFERFORGE_PRELOAD", "1")
    monkeypatch.setenv("INFERFORGE_SEG", "1")
    calls = _spies(monkeypatch)
    warmup.preload_worker()
    assert calls == ["detect"]


def test_preload_failure_does_not_stop_other_capabilities(no_switches, monkeypatch):
    monkeypatch.setenv("INFERFORGE_PRELOAD", "1")
    monkeypatch.setenv("INFERFORGE_SEG", "1")
    calls = []

    def _fail():
        calls.append("detect-fail")
        raise RuntimeError("corrupt weights")

    monkeypatch.setattr(detection, "preload", _fail)
    monkeypatch.setattr(segmentation, "preload", lambda: calls.append("segment"))
    warmup.preload_web()  # must not raise: one broken model must not kill boot
    assert calls == ["detect-fail", "segment"]


def test_task_preload_loads_default(monkeypatch):
    seen = []

    def _fake_get_predictor(model=None):
        seen.append(model)

    monkeypatch.setattr(detection, "get_predictor", _fake_get_predictor)
    detection.preload()
    assert seen == [None]  # default model, resolved by the registry


def test_app_runs_preload_on_startup(no_switches, monkeypatch):
    from app import create_app

    monkeypatch.setenv("INFERFORGE_PRELOAD", "1")
    calls = []
    monkeypatch.setattr(warmup, "preload_web", lambda: calls.append(True))
    app = create_app()  # binds warmup.preload_web at registration time
    with TestClient(app):  # context manager runs the lifespan
        pass
    assert calls == [True]


def test_app_skips_preload_without_switch(no_switches, monkeypatch):
    from app import create_app

    calls = []
    monkeypatch.setattr(warmup, "preload_web", lambda: calls.append(True))
    app = create_app()
    with TestClient(app):
        pass
    assert calls == []
