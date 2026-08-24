"""Smoke tests for the /metrics endpoint using a fake predictor (no model needed)."""
import base64
import time
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from apis.predict import predict_router
from engines.base import BasePredictor, DetectionResult
from tasks import detection
from tasks import vlm
from utils import metrics


class FakePredictor(BasePredictor):
    """Returns one fixed detection; load/predict are no-ops."""

    def load(self, model_path):
        pass

    def predict(self, image):
        return DetectionResult(
            boxes=np.array([[4.0, 8.0, 20.0, 32.0]]),
            scores=np.array([0.87]),
            class_ids=np.array([0]),
        )


def _tiny_image_b64():
    img = np.zeros((64, 64, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return base64.b64encode(buf.tobytes()).decode("utf-8")


@pytest.fixture()
def client(monkeypatch, app_factory):
    monkeypatch.setattr(detection, "get_predictor", lambda: FakePredictor())
    return TestClient(app_factory(predict_router))


def test_metrics_endpoint(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert "inferforge_http_requests_total" in resp.text


def test_predict_counts_and_code(client):
    client.post("/predict", json={"image": _tiny_image_b64()})
    body = client.get("/metrics").text
    assert 'inferforge_http_requests_total{method="POST",route="/predict"}' in body
    assert 'inferforge_responses_total{code="0"}' in body


def test_validation_failure_code(client):
    client.post("/predict", json={})
    body = client.get("/metrics").text
    assert 'inferforge_responses_total{code="1"}' in body


def test_route_template_label(monkeypatch, app_factory):
    """The route label comes from the path template, not the raw request path."""
    router = APIRouter()

    @router.get("/items/{item_id}")
    def item(item_id: str):
        return {"code": 0, "message": "ok", "data": None}

    client = TestClient(app_factory(router))
    client.get("/items/42")
    body = client.get("/metrics").text
    assert 'route="/items/{item_id}"' in body


# --- vlm remote-call metrics (snapshot deltas: counters are process-global) ---


class _FakeChatCompletions:
    """Records create() kwargs; returns a fixed response or raises."""

    def __init__(self, raise_exc=None, content="ok"):
        self._raise_exc = raise_exc
        self._content = content
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self._raise_exc is not None:
            raise self._raise_exc

        class _Message:
            content = self._content

        class _Choice:
            message = _Message()

        class _Response:
            choices = [_Choice()]

        return _Response()


class _FakeClient:
    """Mimics client.chat.completions.create(...)."""

    def __init__(self, completions):
        class _FakeChat:
            pass

        _FakeChat.completions = completions
        self.chat = _FakeChat()


def test_vlm_remote_call_metric_on_success(monkeypatch):
    pytest.importorskip("openai")
    monkeypatch.setenv("INFERFORGE_LLM_MODEL", "m")
    monkeypatch.setenv("INFERFORGE_LLM_API_KEY", "k")
    monkeypatch.setattr(vlm, "_get_client", lambda: _FakeClient(_FakeChatCompletions()))
    before = REGISTRY.get_sample_value("inferforge_vlm_remote_call_seconds_count") or 0.0
    errors_before = REGISTRY.get_sample_value("inferforge_vlm_remote_errors_total") or 0.0

    vlm._call_remote_llm("data:image/jpeg;base64,AAAA", "prompt")

    assert REGISTRY.get_sample_value("inferforge_vlm_remote_call_seconds_count") == before + 1.0
    assert REGISTRY.get_sample_value("inferforge_vlm_remote_errors_total") == errors_before


def test_vlm_remote_error_metric(monkeypatch):
    openai = pytest.importorskip("openai")
    monkeypatch.setenv("INFERFORGE_LLM_MODEL", "m")
    monkeypatch.setenv("INFERFORGE_LLM_API_KEY", "k")
    completions = _FakeChatCompletions(raise_exc=openai.OpenAIError("boom"))
    monkeypatch.setattr(vlm, "_get_client", lambda: _FakeClient(completions))
    before = REGISTRY.get_sample_value("inferforge_vlm_remote_errors_total") or 0.0

    with pytest.raises(vlm.LLMUpstreamError):
        vlm._call_remote_llm("data:image/jpeg;base64,AAAA", "prompt")

    assert REGISTRY.get_sample_value("inferforge_vlm_remote_errors_total") == before + 1.0


# --- task-labeled phase / predictor metrics ---


def _phase_count(phase, task):
    return (REGISTRY.get_sample_value("inferforge_predict_phase_seconds_count",
                                      {"phase": phase, "task": task}) or 0.0)


def test_observe_phase_records_task_label():
    before = _phase_count("infer", "segment")
    metrics.observe_phase("infer", 0.01, task="segment")
    assert _phase_count("infer", "segment") == before + 1.0


def test_observe_phase_defaults_to_detect():
    before = _phase_count("post", "detect")
    metrics.observe_phase("post", 0.01)  # task omitted -> "detect"
    assert _phase_count("post", "detect") == before + 1.0


def test_mark_predictor_loaded_task_label():
    metrics.mark_predictor_loaded(task="classify")
    value = REGISTRY.get_sample_value("inferforge_predictor_loaded", {"task": "classify"})
    assert value == 1.0


# --- celery queue-wait metric (computation lives in utils.metrics.record_queue_wait;
#     never import celery_app in tests — its thread-local current_app would split
#     task-proxy resolution across TestClient threads and break task monkeypatching) ---


def _queue_wait_count(task):
    return (REGISTRY.get_sample_value("inferforge_celery_queue_wait_seconds_count",
                                      {"task": task}) or 0.0)


def test_queue_wait_metric_from_submitted_at():
    before = _queue_wait_count("tasks.detection_query")
    metrics.record_queue_wait("tasks.detection_query",
                              {"submitted_at": time.time() - 2.0})
    assert _queue_wait_count("tasks.detection_query") == before + 1.0


def test_queue_wait_metric_clamps_clock_skew():
    task = "tasks.detection_query"
    before = _queue_wait_count(task)
    sum_before = (REGISTRY.get_sample_value("inferforge_celery_queue_wait_seconds_sum",
                                            {"task": task}) or 0.0)
    metrics.record_queue_wait(task, {"submitted_at": time.time() + 5.0})
    assert _queue_wait_count(task) == before + 1.0
    # negative delta clamped to 0: the bucket sum is unchanged
    assert (REGISTRY.get_sample_value("inferforge_celery_queue_wait_seconds_sum",
                                      {"task": task}) or 0.0) == sum_before


def test_queue_wait_skips_missing_submitted_at():
    before = _queue_wait_count("tasks.detection_query")
    metrics.record_queue_wait("tasks.detection_query", {})
    assert _queue_wait_count("tasks.detection_query") == before
