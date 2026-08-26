"""Agent task: detect + judge per-person attributes via a Pydantic AI agent.

The demo business: count persons with and without hair. The local detection
engine (tasks.detection) locates every person; a remote LLM agent judges the
hair attribute per person from the full image + the tool-provided boxes.
This is the template's "CV kernel + LLM orchestration" showcase — swap the
output schema + instructions + tool for any other fine-grained attribute
task (glasses / red clothes / masks, ...).

pydantic-ai is worker-only and imported lazily inside function bodies (same
rule as onnxruntime/openai): the web process and celery_app registration
must import this module without it installed. Each task builds a fresh
agent and http client — run_sync spins its own event loop per call, so the
httpx2 client cannot be reused across runs.

Failure semantics mirror tasks.vlm: LLMUpstreamError -> code 9 (business
error, never retried by the callback), LLMConfigError -> code 3, image
errors reuse code 1/2 via utils.image, detection-tool failures -> code 3.
Remote-call latency/errors reuse the vlm metrics
(inferforge_vlm_remote_call_seconds / inferforge_vlm_remote_errors_total).
"""
import logging
import os
import time

import cv2
import numpy as np
from pydantic import BaseModel, Field

from engines import registry
from tasks.detection import get_predictor
from tasks.vlm import LLMConfigError, LLMUpstreamError, get_llm_config
from utils import image as image_utils
from utils import metrics

logger = logging.getLogger("tasks.agent")

DEFAULT_AGENT_INSTRUCTIONS = (
    "You analyze photos of people. Always call the detect_persons tool first to "
    "locate every person in the image. Then judge, for each detected person, "
    "whether they have visible hair (has_hair=true) or are bald / shaved / "
    "wearing head coverings (has_hair=false). Use the bounding boxes returned "
    "by the tool to attribute each judgment to the right person. Output one "
    "HairCountResult: total_persons, with_hair, without_hair and one "
    "per_person entry per detected person."
)
AGENT_INSTRUCTIONS = os.environ.get("INFERFORGE_AGENT_INSTRUCTIONS", DEFAULT_AGENT_INSTRUCTIONS)

AGENT_TIMEOUT = 60.0  # seconds per run (model settings; transport retries live below this)
AGENT_MAX_TOKENS = 1024

RUN_MESSAGE = "Count the persons with and without hair in this image."

TARGET_CLASS_ENV = "INFERFORGE_AGENT_TARGET_CLASS"
DEFAULT_TARGET_CLASS = "person"


class PersonHair(BaseModel):
    """Per-person judgment: engine-located box + LLM-decided hair attribute."""

    index: int = Field(description="Person index from the detect_persons tool (0-based)")
    bbox: list[float] = Field(description="Bounding box [x1, y1, x2, y2] in original pixels")
    has_hair: bool = Field(description="Whether this person has visible hair")


class HairCountResult(BaseModel):
    """The demo output schema: per-person hair judgments aggregated."""

    total_persons: int = Field(description="Total persons detected in the image")
    with_hair: int = Field(description="Persons with visible hair")
    without_hair: int = Field(description="Persons without hair (bald / shaved / covered)")
    per_person: list[PersonHair] = Field(description="One entry per detected person")


class DetectedPerson(BaseModel):
    """Detection-tool payload: one person's box."""

    index: int
    bbox: list[float]


class DetectedPersons(BaseModel):
    """Detection-tool return type."""

    persons: list[DetectedPerson]


def _target_class() -> str:
    """The class the detection tool keeps: INFERFORGE_AGENT_TARGET_CLASS or
    the demo default ("person"). Read at call time (tests monkeypatch env)."""
    return os.environ.get(TARGET_CLASS_ENV, DEFAULT_TARGET_CLASS)


def _validate_target_class(spec: "registry.ModelSpec") -> str:
    """The target class must exist in the selected detect model's class table
    (registry-resolved: a per-model `classes` file overrides the built-in
    table). A miss is a config error naming the env var — same convention as
    get_llm_config (-> code 3)."""
    target = _target_class()
    if target not in spec.class_names:
        raise LLMConfigError(
            "%s=%r is not a class of detect model %r — set it to a class in "
            "the model's registry entry (classes file) or fix the variable"
            % (TARGET_CLASS_ENV, target, spec.name)
        )
    if target != DEFAULT_TARGET_CLASS and "INFERFORGE_AGENT_INSTRUCTIONS" not in os.environ:
        logger.warning(
            "%s=%r but INFERFORGE_AGENT_INSTRUCTIONS is not set — the default "
            "hair-count instructions may not match this task",
            TARGET_CLASS_ENV, target,
        )
    return target


def _detect_persons(image, model=None) -> DetectedPersons:
    """Locate every target-class object with the local detection engine
    (module-level, testable).

    `model` picks a registered detect model (absent -> the detect default);
    the class table comes from that model's registry entry, so a fork with a
    custom `classes` file or a renamed person class works without code edits.
    Only the target class (INFERFORGE_AGENT_TARGET_CLASS, default "person")
    is kept — the engine's other classes are noise for the attribute
    judgment. Indexes are 0-based and stable, so the model can attribute
    each judgment to the right box.
    """
    spec = registry.resolve(model, "detect")
    target = _validate_target_class(spec)
    result = get_predictor(spec.name).predict(image)
    persons = [
        DetectedPerson(index=i, bbox=[round(float(v), 2) for v in box])
        for i, (box, class_id) in enumerate(zip(result.boxes, result.class_ids))
        if spec.label(int(class_id)) == target  # label() tolerates ids past the table
    ]
    logger.info("detect_persons tool: %d %s(s)", len(persons), target)
    return DetectedPersons(persons=persons)


def _build_agent(model):
    """Build the hair-count agent (worker-only deps imported in-function).

    `model` is the registered detect model name (registry-validated by
    run_hair_count); the detection tool closes over it so the ReAct loop
    runs the right predictor + class table.

    A fresh client per task: run_sync spins a new event loop each call, so
    the httpx2 AsyncClient cannot be reused across runs. Transport retries
    mirror the vlm task's SDK semantics (3 attempts on 429/5xx/connection,
    Retry-After aware) — pydantic-ai has NO built-in HTTP retries.
    """
    from httpx2 import AsyncClient, ConnectError, HTTPStatusError
    from pydantic_ai import Agent, RunContext
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider
    from pydantic_ai.retries import AsyncHTTPX2TenacityTransport, RetryConfig, wait_retry_after
    from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential

    model_name, api_key, base_url = get_llm_config()  # validate BEFORE importing pydantic-ai

    def should_retry_status(response):
        if response.status_code in (429, 502, 503, 504):
            response.raise_for_status()

    transport = AsyncHTTPX2TenacityTransport(
        config=RetryConfig(
            retry=retry_if_exception_type((HTTPStatusError, ConnectError)),
            wait=wait_retry_after(
                fallback_strategy=wait_exponential(multiplier=1, max=60),
                max_wait=300,
            ),
            stop=stop_after_attempt(3),  # mirrors the vlm task's SDK max_retries=2
            reraise=True,
        ),
        validate_response=should_retry_status,
    )
    client = AsyncClient(transport=transport)
    model = OpenAIChatModel(
        model_name,
        provider=OpenAIProvider(api_key=api_key, base_url=base_url, http_client=client),
    )
    agent = Agent(
        model,
        output_type=HairCountResult,
        instructions=AGENT_INSTRUCTIONS,
        deps_type=np.ndarray,  # the decoded BGR image, used by the tool
    )

    @agent.tool
    def detect_persons(ctx: RunContext[np.ndarray]) -> DetectedPersons:
        """Locate every person in the image with the local detection engine."""
        return _detect_persons(ctx.deps, model=model)

    return agent


def run_hair_count(image_b64=None, image_url=None, model=None):
    """Run the hair-count agent: validate the image, detect persons, judge hair.

    `model` picks a registered detect model (absent -> the detect default).
    Returns the HairCountResult serialized as a plain dict (the task modules
    wrap it in the result envelope).
    """
    image = image_utils.input_to_image(image_b64, image_url)  # ValueError -> code 1, download -> 2
    # Registry + target-class checks run BEFORE the paid call; inside the
    # tool this raise would be wrapped into a ToolFailed and lose the message.
    spec = registry.resolve(model, "detect")
    _validate_target_class(spec)  # LLMConfigError -> code 3, naming the env var
    ok, buf = cv2.imencode(".jpg", image)
    if not ok:
        raise ValueError("failed to encode image to jpeg")
    jpeg_bytes = buf.tobytes()

    try:
        from pydantic_ai import BinaryContent, ModelSettings
        from pydantic_ai.exceptions import AgentRunError, ToolFailed
    except ImportError:
        raise LLMConfigError(
            "pydantic-ai SDK is not installed in the worker — install requirements-async.txt"
        ) from None

    agent = _build_agent(spec.name)  # config validated here (LLMConfigError -> code 3)

    started = time.perf_counter()
    try:
        result = agent.run_sync(
            [RUN_MESSAGE, BinaryContent(data=jpeg_bytes, media_type="image/jpeg")],
            deps=image,
            model_settings=ModelSettings(timeout=AGENT_TIMEOUT, max_tokens=AGENT_MAX_TOKENS),
        )
    except ToolFailed as exc:
        logger.error("detection tool failed: %s", exc)
        raise RuntimeError("detection tool failed") from exc
    except AgentRunError as exc:
        metrics.count_vlm_remote_error()
        logger.warning("agent run failed after %.1fs: %s", time.perf_counter() - started, exc)
        raise LLMUpstreamError(str(exc)) from exc
    metrics.observe_vlm_remote_call(time.perf_counter() - started)

    usage = getattr(result, "usage", None)  # test fakes have no usage attribute
    if usage is not None:
        logger.info("agent usage: %s", usage)

    output = result.output
    logger.info("hair count done: total=%s with_hair=%s without_hair=%s",
                output.total_persons, output.with_hair, output.without_hair)
    return output.model_dump()
