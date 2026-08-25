"""Unit tests for tasks.agent — no network; pydantic-ai only for the error-mapping tests."""
import base64
import importlib.util

import cv2
import numpy as np
import pytest

from engines.base import BasePredictor, DetectionResult
from tasks import agent


class FakePredictor(BasePredictor):
    """Two persons + one non-person class (the tie is filtered by the tool)."""

    def load(self, model_path):
        pass

    def predict(self, image):
        assert image.ndim == 3 and image.shape[2] == 3
        return DetectionResult(
            boxes=np.array([[4.0, 8.0, 20.0, 32.0], [30.0, 40.0, 60.0, 90.0], [1.0, 1.0, 5.0, 5.0]]),
            scores=np.array([0.9, 0.8, 0.4]),
            class_ids=np.array([0, 0, 27]),  # person, person, tie
        )


def _tiny_image_b64():
    img = np.zeros((64, 64, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return base64.b64encode(buf.tobytes()).decode("utf-8")


# --- output models ---


def test_hair_count_result_model_dump():
    result = agent.HairCountResult(
        total_persons=2,
        with_hair=1,
        without_hair=1,
        per_person=[
            agent.PersonHair(index=0, bbox=[4.0, 8.0, 20.0, 32.0], has_hair=False),
            agent.PersonHair(index=1, bbox=[30.0, 40.0, 60.0, 90.0], has_hair=True),
        ],
    )
    dumped = result.model_dump()
    assert dumped["total_persons"] == 2
    assert dumped["per_person"][1]["has_hair"] is True


# --- detection tool ---


def test_detect_persons_filters_to_person_class(monkeypatch):
    monkeypatch.setattr(agent, "get_predictor", lambda model=None: FakePredictor())
    detections = agent._detect_persons(np.zeros((64, 64, 3), dtype=np.uint8))
    assert len(detections.persons) == 2  # the tie class is filtered out
    assert detections.persons[0].index == 0
    assert detections.persons[0].bbox == [4.0, 8.0, 20.0, 32.0]
    assert detections.persons[1].index == 1  # index stable: the second person


# --- run_hair_count orchestration (agent faked) ---


class _FakeRunResult:
    def __init__(self, output, usage=None):
        self.output = output
        self.usage = usage


@pytest.fixture()
def fake_agent(monkeypatch):
    """Replace _build_agent with a fake agent capturing run_sync args."""
    calls = []

    class _FakeAgent:
        def run_sync(self, messages, deps=None, model_settings=None):
            calls.append({"messages": messages, "deps": deps, "model_settings": model_settings})
            return _FakeRunResult(agent.HairCountResult(
                total_persons=2, with_hair=1, without_hair=1,
                per_person=[agent.PersonHair(index=0, bbox=[0, 0, 1, 1], has_hair=False),
                            agent.PersonHair(index=1, bbox=[2, 2, 3, 3], has_hair=True)],
            ))

    monkeypatch.setattr(agent, "_build_agent", _FakeAgent)
    return calls


def test_run_hair_count_returns_result_dict(fake_agent):
    result = agent.run_hair_count(image_b64=_tiny_image_b64())
    assert result["total_persons"] == 2
    assert result["with_hair"] == 1
    assert result["without_hair"] == 1
    assert len(result["per_person"]) == 2


def test_run_hair_count_passes_jpeg_content_and_image_deps(fake_agent):
    agent.run_hair_count(image_b64=_tiny_image_b64())
    call = fake_agent[0]
    messages = call["messages"]
    assert messages[0] == agent.RUN_MESSAGE
    # BinaryContent carries the re-encoded JPEG bytes
    assert messages[1].media_type == "image/jpeg"
    assert messages[1].data[:2] == b"\xff\xd8"  # JPEG magic
    # deps = decoded BGR image for the detection tool
    assert isinstance(call["deps"], np.ndarray)
    assert call["deps"].shape[2] == 3
    assert call["model_settings"] is not None


def test_run_hair_count_rejects_bad_input_before_agent(monkeypatch):
    built = []

    def _build():
        built.append(1)

    monkeypatch.setattr(agent, "_build_agent", _build)
    with pytest.raises(ValueError):
        agent.run_hair_count(image_b64="!!not-base64!!")
    assert built == []  # validation happens before the paid call


def test_run_hair_count_config_error_names_missing_model(monkeypatch):
    monkeypatch.delenv("INFERFORGE_LLM_MODEL", raising=False)
    monkeypatch.setenv("INFERFORGE_LLM_API_KEY", "k")
    with pytest.raises(agent.LLMConfigError) as exc:
        agent.run_hair_count(image_b64=_tiny_image_b64())
    assert "INFERFORGE_LLM_MODEL" in str(exc.value)


@pytest.mark.skipif(
    importlib.util.find_spec("pydantic_ai") is not None,
    reason="pydantic-ai is installed — the missing-SDK path is not exercisable here",
)
def test_run_hair_count_reports_missing_sdk(monkeypatch):
    """Without the SDK, the worker reports a clear config error (code 3), not a generic one."""
    monkeypatch.setenv("INFERFORGE_LLM_MODEL", "m")
    monkeypatch.setenv("INFERFORGE_LLM_API_KEY", "k")
    with pytest.raises(agent.LLMConfigError) as exc:
        agent.run_hair_count(image_b64=_tiny_image_b64())
    assert "pydantic-ai" in str(exc.value)


# --- pydantic-ai error mapping (only where the SDK is installed) ---


def test_run_hair_count_maps_agent_run_error(monkeypatch):
    pytest.importorskip("pydantic_ai")
    from pydantic_ai.exceptions import AgentRunError

    class _FailingAgent:
        def run_sync(self, *args, **kwargs):
            raise AgentRunError("upstream boom")

    monkeypatch.setattr(agent, "_build_agent", lambda: _FailingAgent())
    with pytest.raises(agent.LLMUpstreamError) as exc:
        agent.run_hair_count(image_b64=_tiny_image_b64())
    assert "upstream boom" in str(exc.value)


def test_run_hair_count_maps_tool_failed(monkeypatch):
    pytest.importorskip("pydantic_ai")
    from pydantic_ai.exceptions import ToolFailed

    class _FailingAgent:
        def run_sync(self, *args, **kwargs):
            raise ToolFailed("tool boom")

    monkeypatch.setattr(agent, "_build_agent", lambda: _FailingAgent())
    with pytest.raises(RuntimeError):
        agent.run_hair_count(image_b64=_tiny_image_b64())
