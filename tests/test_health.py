"""Tests for the /health (liveness) and /health/ready (readiness) probes."""
import pytest
from fastapi.testclient import TestClient

from apis.health import health_router
from engines import registry
# @inferforge:detect
from tasks import detection  # noqa: E402
# @inferforge:end:detect
# @inferforge:seg
from tasks import segmentation  # noqa: E402
# @inferforge:end:seg
# @inferforge:cls
from tasks import classification  # noqa: E402
# @inferforge:end:cls
# @inferforge:embed
from tasks import embedding  # noqa: E402
# @inferforge:end:embed


def _mark_loaded(monkeypatch, task_module, capability):
    """Populate the task module's predictor cache with its default model, as
    if a first prediction had warmed it up. The cache is a dict keyed by
    registered model name; readiness probes only the default."""
    monkeypatch.setattr(task_module, "_predictors", {registry.default_name(capability): object()})


@pytest.fixture()
def client(monkeypatch, app_factory):
    # The real predictor is never loaded in tests; pin the unloaded state so
    # the "not ready" path is deterministic regardless of test order. The
    # capability switches are cleared (readiness reads them at request time;
    # a dev .env could otherwise leak in).
    monkeypatch.delenv("INFERFORGE_SEG", raising=False)
    monkeypatch.delenv("INFERFORGE_CLS", raising=False)
    monkeypatch.delenv("INFERFORGE_PIPELINE", raising=False)
    monkeypatch.delenv("INFERFORGE_DEDUP", raising=False)
    monkeypatch.delenv("INFERFORGE_SEARCH", raising=False)
    monkeypatch.setattr(detection, "_predictors", {})
    # @inferforge:seg
    monkeypatch.setattr(segmentation, "_predictors", {})
    # @inferforge:end:seg
    # @inferforge:cls
    monkeypatch.setattr(classification, "_predictors", {})
    # @inferforge:end:cls
    # @inferforge:embed
    monkeypatch.setattr(embedding, "_predictors", {})
    # @inferforge:end:embed
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
    # Simulate a first prediction warming the task layer: the default model
    # present in the cache makes predictor_loaded() report ready.
    _mark_loaded(monkeypatch, detection, "detect")
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["status"] == "ready"


# @inferforge:seg
def test_readiness_requires_seg_model_when_enabled(client, monkeypatch):
    monkeypatch.setenv("INFERFORGE_SEG", "1")
    _mark_loaded(monkeypatch, detection, "detect")  # detection ready
    resp = client.get("/health/ready")
    assert resp.status_code == 503  # segment enabled but not loaded
    assert resp.json()["code"] == 6


def test_readiness_ready_when_seg_loaded(client, monkeypatch):
    monkeypatch.setenv("INFERFORGE_SEG", "1")
    _mark_loaded(monkeypatch, detection, "detect")
    _mark_loaded(monkeypatch, segmentation, "segment")
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json()["code"] == 0
# @inferforge:end:seg


# @inferforge:cls
def test_readiness_requires_cls_model_when_enabled(client, monkeypatch):
    monkeypatch.setenv("INFERFORGE_CLS", "1")
    _mark_loaded(monkeypatch, detection, "detect")
    resp = client.get("/health/ready")
    assert resp.status_code == 503  # classify enabled but not loaded
    assert resp.json()["code"] == 6


def test_readiness_requires_cls_model_when_pipeline_enabled(client, monkeypatch):
    # the pipeline composes the classify default: readiness probes classify
    # even though INFERFORGE_CLS is off
    monkeypatch.setenv("INFERFORGE_PIPELINE", "1")
    _mark_loaded(monkeypatch, detection, "detect")
    resp = client.get("/health/ready")
    assert resp.status_code == 503  # pipeline enabled but classify not loaded
    assert resp.json()["code"] == 6
# @inferforge:end:cls


# @inferforge:embed
def test_readiness_requires_embed_model_when_dedup_enabled(client, monkeypatch):
    monkeypatch.setenv("INFERFORGE_DEDUP", "1")
    _mark_loaded(monkeypatch, detection, "detect")
    resp = client.get("/health/ready")
    assert resp.status_code == 503  # dedup enabled but embed not loaded
    assert resp.json()["code"] == 6


def test_readiness_ignores_embed_when_only_search_enabled(client, monkeypatch):
    # search is worker-only: the web process never loads the embed model, so
    # probing embed here would keep readiness perpetually 503
    monkeypatch.setenv("INFERFORGE_SEARCH", "1")
    _mark_loaded(monkeypatch, detection, "detect")
    resp = client.get("/health/ready")
    assert resp.status_code == 200
# @inferforge:end:embed


def test_readiness_ignores_disabled_capabilities(client, monkeypatch):
    # switches off: only detection's predictor state matters
    _mark_loaded(monkeypatch, detection, "detect")
    resp = client.get("/health/ready")
    assert resp.status_code == 200


def test_readiness_registered_by_app_factory(monkeypatch):
    """End-to-end through create_app: readiness returns 503 without a model."""
    monkeypatch.delenv("INFERFORGE_ASYNC", raising=False)
    monkeypatch.delenv("INFERFORGE_QUERY", raising=False)
    monkeypatch.delenv("INFERFORGE_SEG", raising=False)
    monkeypatch.delenv("INFERFORGE_CLS", raising=False)
    monkeypatch.delenv("INFERFORGE_PIPELINE", raising=False)
    from app import create_app

    resp = TestClient(create_app()).get("/health/ready")
    assert resp.status_code == 503
    assert resp.json()["code"] == 6
