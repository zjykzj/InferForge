"""Classification task: owns its predictors and orchestrates the full pipeline.

input parsing -> inference -> top-k mapping -> response payload. Predictors
are lazily loaded on first use and kept resident afterwards; the API layer
never sees them. No drawing — classification returns text results only.
Which predictor a request gets is decided by the model registry
(engines.registry) — the `model` field or, when absent, the classify default.
"""
import logging
import threading
import time
from typing import Optional

from engines import registry
from engines.base import BasePredictor
from engines.yolo_cls import YoloClsPredictor
from utils import image as image_utils
from utils import metrics

logger = logging.getLogger("tasks.classification")

# Per-model predictors, keyed by registered model name. A single lock covers
# all models (see tasks.detection for the rationale).
_predictors: dict[str, BasePredictor] = {}
_predictors_lock = threading.Lock()


def get_predictor(model: Optional[str] = None) -> BasePredictor:
    """Lazily load the predictor for `model` (or the classify default) on
    first use; kept resident afterwards."""
    spec = registry.resolve(model, "classify")
    if spec.name not in _predictors:
        with _predictors_lock:
            if spec.name not in _predictors:
                predictor = YoloClsPredictor()
                predictor.load(spec.path)
                _predictors[spec.name] = predictor
                metrics.mark_predictor_loaded(task="classify", model=spec.name)
    return _predictors[spec.name]


def predictor_loaded(model: Optional[str] = None) -> bool:
    """Whether the predictor for `model` (or the classify default) has been
    loaded (pure check, no side effects)."""
    name = registry.resolve(model, "classify").name
    return name in _predictors


def default_model_loaded() -> bool:
    """Readiness probe: is the classify DEFAULT model loaded? False (not an
    exception) when no classify model is registered at all."""
    try:
        return predictor_loaded()
    except registry.ModelNotFound:
        return False


def run_classification(image_b64=None, image_url=None, model=None):
    """Run the full classification pipeline.

    Returns the top-k classifications as a list of
    {"class_id": int, "class": str, "confidence": float}, sorted by
    confidence descending.
    """
    t_start = time.perf_counter()

    image = image_utils.input_to_image(image_b64, image_url)

    spec = registry.resolve(model, "classify")
    result = get_predictor(spec.name).predict(image)

    classifications = [
        {
            "class_id": int(class_id),
            "class": spec.label(class_id),
            "confidence": round(float(score), 4),
        }
        for class_id, score in zip(result.class_ids, result.scores)
    ]

    logger.info("classification task done: model=%s, top-k=%d, total=%.1fms",
                spec.name, len(classifications), (time.perf_counter() - t_start) * 1000)
    return classifications
