"""Embedding task: owns its embed predictors and encodes images to vectors.

The shared capability behind the search / dupcheck / dedup business tasks —
each of them consumes `encode()` and never touches a predictor directly
(same ownership rule as tasks.detection). Predictors are lazily loaded on
first use and kept resident afterwards; the registry picks which registered
model a request gets (absent -> the embed default).
"""
import logging
import os
import threading
from typing import Optional

from engines import registry
from engines.base import BasePredictor
from engines.dinov2 import DinoV2Predictor
from utils import metrics

logger = logging.getLogger("tasks.embedding")

DUP_THRESHOLD_ENV = "INFERFORGE_DUP_THRESHOLD"
DEFAULT_DUP_THRESHOLD = 0.95

# Per-model predictors, keyed by registered model name. A single lock covers
# all models (see tasks.detection for the rationale).
_predictors: dict[str, BasePredictor] = {}
_predictors_lock = threading.Lock()


def get_embedder(model: Optional[str] = None) -> BasePredictor:
    """Lazily load the embedder for `model` (or the embed default) on first
    use; kept resident afterwards."""
    spec = registry.resolve(model, "embed")
    if spec.name not in _predictors:
        with _predictors_lock:
            if spec.name not in _predictors:
                predictor = DinoV2Predictor()
                predictor.load(spec.path)
                _predictors[spec.name] = predictor
                metrics.mark_predictor_loaded(task="embed", model=spec.name)
    return _predictors[spec.name]


def preload() -> None:
    """Warmup: load the embed default model now instead of on first request
    (see tasks.detection.preload for the semantics)."""
    get_embedder()


def predictor_loaded(model: Optional[str] = None) -> bool:
    """Whether the embedder for `model` (or the embed default) has been
    loaded (pure check, no side effects)."""
    name = registry.resolve(model, "embed").name
    return name in _predictors


def default_model_loaded() -> bool:
    """Readiness probe: is the embed DEFAULT model loaded? False (not an
    exception) when no embed model is registered at all."""
    try:
        return predictor_loaded()
    except registry.ModelNotFound:
        return False


def dup_threshold() -> float:
    """The near-duplicate similarity threshold shared by the dupcheck and
    dedup tasks: INFERFORGE_DUP_THRESHOLD or 0.95. Read at call time (tests
    monkeypatch env). A misconfigured value falls back to the default."""
    try:
        return float(os.environ.get(DUP_THRESHOLD_ENV, DEFAULT_DUP_THRESHOLD))
    except ValueError:
        logger.warning("%s=%r is not a float; using %.2f",
                       DUP_THRESHOLD_ENV, os.environ.get(DUP_THRESHOLD_ENV), DEFAULT_DUP_THRESHOLD)
        return DEFAULT_DUP_THRESHOLD


def encode(image, model: Optional[str] = None):
    """Encode a BGR image into its L2-normalized embedding vector."""
    spec = registry.resolve(model, "embed")
    return get_embedder(spec.name).predict(image).vector
