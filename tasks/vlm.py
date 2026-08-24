"""VLM task: fixed server-side prompt + remote LLM call over an image.

input_to_image validation -> JPEG data URL -> OpenAI-compatible chat
completions -> (answer, model). The prompt is fixed server-side (clients
submit an image only); INFERFORGE_LLM_PROMPT overrides the default.

The openai SDK is worker-only and imported lazily inside function bodies
(same rule as onnxruntime): the web process and celery_app registration must
import this module without openai installed. The remote call is I/O-bound,
so vlm workers scale with `./start_celery.sh -c N` (worker_prefetch_multiplier
stays 1 — that knob is about one task at a time per child process).

Failure semantics: LLMUpstreamError -> code 9 (business error, never retried
by the callback), LLMConfigError -> code 3, image errors reuse code 1/2 via
utils.image. Remote-call latency/errors are recorded in
inferforge_vlm_remote_call_seconds / inferforge_vlm_remote_errors_total
(utils.metrics); token usage is logged per call.
"""
import logging
import os
import time
from typing import Optional, Tuple

from utils import image as image_utils
from utils import metrics

logger = logging.getLogger("tasks.vlm")

DEFAULT_LLM_PROMPT = "Please describe this image in detail."
LLM_PROMPT = os.environ.get("INFERFORGE_LLM_PROMPT", DEFAULT_LLM_PROMPT)

LLM_TIMEOUT = 60.0  # seconds per SDK request (celery soft limit is 240s)
LLM_MAX_RETRIES = 2  # SDK-level retries for transient infra failures (connection / 429 / 5xx)
LLM_MAX_TOKENS = 1024  # max_tokens passed to the remote call (v1 fixed)


class LLMUpstreamError(Exception):
    """Upstream LLM call failed after the SDK's retries (timeout / 5xx / rate limit / connection).

    Mapped to business code 9 by the task modules.
    """


class LLMConfigError(RuntimeError):
    """Missing required LLM env config. Mapped to code 3 with a clear message."""


_client = None


def _get_config() -> Tuple[str, str, Optional[str]]:
    """Read (model, api_key, base_url) from the env; raise LLMConfigError if a required var is missing.

    Read lazily (not at import time) so tests can monkeypatch.setenv and reset
    _client without reloading the module.
    """
    model = os.environ.get("INFERFORGE_LLM_MODEL")
    api_key = os.environ.get("INFERFORGE_LLM_API_KEY")
    base_url = os.environ.get("INFERFORGE_LLM_BASE_URL") or None
    if not model:
        raise LLMConfigError("missing INFERFORGE_LLM_MODEL: set it to the remote model name")
    if not api_key:
        raise LLMConfigError("missing INFERFORGE_LLM_API_KEY")
    return model, api_key, base_url


def _get_client():
    """Lazily create the openai client singleton (worker-only dep, imported in-function)."""
    global _client
    if _client is None:
        model, api_key, base_url = _get_config()  # validate before importing openai
        from openai import OpenAI

        _client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            max_retries=LLM_MAX_RETRIES,
            timeout=LLM_TIMEOUT,
        )
        logger.info("llm client created: model=%s base_url=%s", model, base_url or "default")
    return _client


def _build_messages(image_data_url: str, prompt: str) -> list:
    """Build the single-turn user message (pure dict construction, no openai import)."""
    return [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": image_data_url}},
    ]}]


def _call_remote_llm(image_data_url: str, prompt: str) -> Tuple[str, str]:
    """One remote chat completion; SDK errors become LLMUpstreamError. Returns (answer, model)."""
    model, _, _ = _get_config()  # validate config BEFORE importing openai (clear code 3 first)
    try:
        from openai import OpenAIError
    except ImportError:
        raise LLMConfigError(
            "openai SDK is not installed in the worker — install requirements-async.txt"
        ) from None
    started = time.perf_counter()
    try:
        resp = _get_client().chat.completions.create(
            model=model,
            messages=_build_messages(image_data_url, prompt),
            max_tokens=LLM_MAX_TOKENS,
        )
    except OpenAIError as exc:
        metrics.count_vlm_remote_error()
        logger.warning("upstream llm call failed after %.1fs: %s",
                       time.perf_counter() - started, exc)
        raise LLMUpstreamError(str(exc)) from exc
    metrics.observe_vlm_remote_call(time.perf_counter() - started)
    usage = getattr(resp, "usage", None)  # test fakes have no usage attribute
    if usage is not None:
        logger.info("llm usage: model=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s",
                    model,
                    getattr(usage, "prompt_tokens", None),
                    getattr(usage, "completion_tokens", None),
                    getattr(usage, "total_tokens", None))
    content = resp.choices[0].message.content
    if not isinstance(content, str) or not content:
        raise LLMUpstreamError("empty response content from upstream")
    return content, model


def run_vlm(image_b64=None, image_url=None):
    """Run the full VLM pipeline: validate the image, call the remote LLM, return (answer, model).

    The image is decoded/validated before the paid remote call (reusing the
    code 1/2 ladder from utils.image) and re-encoded as JPEG so any accepted
    input format reaches the upstream model in one normalized form.
    """
    image = image_utils.input_to_image(image_b64, image_url)
    data_url = "data:image/jpeg;base64," + image_utils.image_to_base64(image, ext=".jpg")
    answer, model = _call_remote_llm(data_url, LLM_PROMPT)
    logger.info("vlm task done: model=%s answer_len=%d", model, len(answer))
    return answer, model
