"""Unit tests for tasks.vlm — no network; openai only for the error-mapping tests."""
import base64
import importlib
import importlib.util
import os

import cv2
import numpy as np
import pytest

from tasks import vlm


def _tiny_image_b64():
    img = np.zeros((64, 64, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return base64.b64encode(buf.tobytes()).decode("utf-8")


# --- message construction ---


def test_build_messages_single_user_message():
    messages = vlm._build_messages("data:image/jpeg;base64,AAAA", "prompt text")
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    content = messages[0]["content"]
    assert isinstance(content, list) and len(content) == 2
    assert content[0] == {"type": "text", "text": "prompt text"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"] == {"url": "data:image/jpeg;base64,AAAA"}


# --- prompt env override (module-level constant, mirrors MODEL_PATH) ---


def test_llm_prompt_env_override():
    """INFERFORGE_LLM_PROMPT overrides the default (module-level snapshot; reload to re-read)."""
    prev = os.environ.get("INFERFORGE_LLM_PROMPT")
    os.environ["INFERFORGE_LLM_PROMPT"] = "custom prompt"
    try:
        assert importlib.reload(vlm).LLM_PROMPT == "custom prompt"
    finally:
        if prev is None:
            os.environ.pop("INFERFORGE_LLM_PROMPT", None)
        else:
            os.environ["INFERFORGE_LLM_PROMPT"] = prev
        importlib.reload(vlm)  # restore the default snapshot for the other tests


def test_llm_prompt_default():
    assert vlm.LLM_PROMPT == vlm.DEFAULT_LLM_PROMPT


# --- run_vlm orchestration (remote call faked) ---


@pytest.fixture()
def fake_remote_llm(monkeypatch):
    """Replace the remote call with a fixed answer; captures the call args."""
    calls = []

    def _fake(data_url, prompt):
        calls.append((data_url, prompt))
        return "a fixed answer", "test-model"

    monkeypatch.setattr(vlm, "_call_remote_llm", _fake)
    return calls


def test_run_vlm_returns_answer_and_model(fake_remote_llm):
    answer, model = vlm.run_vlm(image_b64=_tiny_image_b64())
    assert answer == "a fixed answer"
    assert model == "test-model"


def test_run_vlm_passes_jpeg_data_url_and_prompt(fake_remote_llm):
    vlm.run_vlm(image_b64=_tiny_image_b64())
    data_url, prompt = fake_remote_llm[0]
    assert data_url.startswith("data:image/jpeg;base64,")
    assert prompt == vlm.LLM_PROMPT
    # the data URL payload must decode back into a color image (JPEG round-trip)
    payload = base64.b64decode(data_url.split(",", 1)[1])
    img = cv2.imdecode(np.frombuffer(payload, np.uint8), cv2.IMREAD_COLOR)
    assert img is not None and img.ndim == 3 and img.shape[2] == 3


def test_run_vlm_rejects_bad_input_before_remote_call(fake_remote_llm):
    with pytest.raises(ValueError):
        vlm.run_vlm(image_b64="!!not-base64!!")
    assert fake_remote_llm == []  # validation happens before the paid call


# --- config (lazy env read; _client reset so tests never leak a cached client) ---


def test_config_error_names_missing_model(monkeypatch):
    monkeypatch.delenv("INFERFORGE_LLM_MODEL", raising=False)
    monkeypatch.setenv("INFERFORGE_LLM_API_KEY", "k")
    monkeypatch.setattr(vlm, "_client", None)
    with pytest.raises(vlm.LLMConfigError) as exc:
        vlm.get_llm_config()
    assert "INFERFORGE_LLM_MODEL" in str(exc.value)


def test_config_error_names_missing_api_key(monkeypatch):
    monkeypatch.setenv("INFERFORGE_LLM_MODEL", "m")
    monkeypatch.delenv("INFERFORGE_LLM_API_KEY", raising=False)
    monkeypatch.setattr(vlm, "_client", None)
    with pytest.raises(vlm.LLMConfigError) as exc:
        vlm.get_llm_config()
    assert "INFERFORGE_LLM_API_KEY" in str(exc.value)


def test_config_reads_all_vars(monkeypatch):
    monkeypatch.setenv("INFERFORGE_LLM_MODEL", "m")
    monkeypatch.setenv("INFERFORGE_LLM_API_KEY", "k")
    monkeypatch.setenv("INFERFORGE_LLM_BASE_URL", "https://x/v1")
    assert vlm.get_llm_config() == ("m", "k", "https://x/v1")


@pytest.mark.skipif(
    importlib.util.find_spec("openai") is not None,
    reason="openai is installed — the missing-SDK path is not exercisable here",
)
def test_call_remote_llm_reports_missing_sdk(monkeypatch):
    """Without the SDK, the worker reports a clear config error (code 3), not a generic one."""
    monkeypatch.setenv("INFERFORGE_LLM_MODEL", "m")
    monkeypatch.setenv("INFERFORGE_LLM_API_KEY", "k")
    monkeypatch.setattr(vlm, "_client", None)
    with pytest.raises(vlm.LLMConfigError) as exc:
        vlm._call_remote_llm("data:image/jpeg;base64,AAAA", "prompt")
    assert "openai" in str(exc.value).lower()


# --- openai error mapping (only where the SDK is installed) ---


class _FakeChatCompletions:
    """Records create() kwargs; returns a fixed response or raises."""

    def __init__(self, raise_exc=None, content="hello"):
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


def test_call_remote_llm_maps_sdk_errors(monkeypatch):
    openai = pytest.importorskip("openai")
    monkeypatch.setenv("INFERFORGE_LLM_MODEL", "m")
    monkeypatch.setenv("INFERFORGE_LLM_API_KEY", "k")
    completions = _FakeChatCompletions(raise_exc=openai.OpenAIError("boom"))
    monkeypatch.setattr(vlm, "_get_client", lambda: _FakeClient(completions))
    with pytest.raises(vlm.LLMUpstreamError) as exc:
        vlm._call_remote_llm("data:image/jpeg;base64,AAAA", "prompt")
    assert "boom" in str(exc.value)


def test_call_remote_llm_success_returns_answer_and_model(monkeypatch):
    pytest.importorskip("openai")
    monkeypatch.setenv("INFERFORGE_LLM_MODEL", "m")
    monkeypatch.setenv("INFERFORGE_LLM_API_KEY", "k")
    completions = _FakeChatCompletions(content="hello from the model")
    monkeypatch.setattr(vlm, "_get_client", lambda: _FakeClient(completions))
    answer, model = vlm._call_remote_llm("data:image/jpeg;base64,AAAA", "prompt")
    assert answer == "hello from the model"
    assert model == "m"
    assert completions.kwargs["model"] == "m"
    assert completions.kwargs["max_tokens"] == vlm.LLM_MAX_TOKENS
    assert completions.kwargs["messages"][0]["role"] == "user"


def test_call_remote_llm_rejects_empty_content(monkeypatch):
    pytest.importorskip("openai")
    monkeypatch.setenv("INFERFORGE_LLM_MODEL", "m")
    monkeypatch.setenv("INFERFORGE_LLM_API_KEY", "k")
    completions = _FakeChatCompletions(content="")
    monkeypatch.setattr(vlm, "_get_client", lambda: _FakeClient(completions))
    with pytest.raises(vlm.LLMUpstreamError):
        vlm._call_remote_llm("data:image/jpeg;base64,AAAA", "prompt")
