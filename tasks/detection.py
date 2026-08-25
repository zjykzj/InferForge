"""Detection task: owns its predictors and orchestrates the full pipeline.

input parsing -> inference -> drawing -> response payload.
A task may hold one or more predictors (each lazily loaded on first use,
kept resident afterwards); the API layer never sees any of them. Which
predictor a request gets is decided by the model registry
(engines.registry) — the `model` field or, when absent, the detect default.
"""
import logging
import threading
import time
from typing import Optional

from engines import registry
from engines.base import BasePredictor
from engines.yolo import YoloPredictor, draw_detections
from utils import image as image_utils
from utils import metrics

logger = logging.getLogger("tasks.detection")

# Per-model predictors, keyed by registered model name. A single lock covers
# all models: loads are one-off seconds-scale events, and the template-scale
# registry holds a handful of entries, so lock contention is not a concern.
_predictors: dict[str, BasePredictor] = {}
_predictors_lock = threading.Lock()


def get_predictor(model: Optional[str] = None) -> BasePredictor:
    """Lazily load the predictor for `model` (or the detect default) on first
    use; kept resident afterwards."""
    spec = registry.resolve(model, "detect")
    if spec.name not in _predictors:
        with _predictors_lock:
            if spec.name not in _predictors:
                predictor = YoloPredictor()
                predictor.load(spec.path)
                _predictors[spec.name] = predictor
                metrics.mark_predictor_loaded(model=spec.name)
    return _predictors[spec.name]


def predictor_loaded(model: Optional[str] = None) -> bool:
    """Whether the predictor for `model` (or the detect default) has been
    loaded (pure check, no side effects)."""
    name = registry.resolve(model, "detect").name
    return name in _predictors


def default_model_loaded() -> bool:
    """Readiness probe: is the detect DEFAULT model loaded? False (not an
    exception) when no detect model is registered at all — the api layer
    asks the task layer and never sees the registry."""
    try:
        return predictor_loaded()
    except registry.ModelNotFound:
        return False


def validate_model(model: Optional[str] = None) -> None:
    """Cheap registry check a submit API can run before queueing, so an
    unknown model name is rejected synchronously instead of surfacing as a
    poll-time error on the worker. Raises utils.errors.ModelNotFound."""
    registry.resolve(model, "detect")


def run_detection(image_b64=None, image_url=None, model=None):
    """Run the full detection pipeline.

    Returns (drawn_image_base64, detections) where detections is a list of
    {"bbox": [x1, y1, x2, y2], "class_id": int, "class": str, "confidence": float}.
    """
    t_start = time.perf_counter()

    image = image_utils.input_to_image(image_b64, image_url)

    spec = registry.resolve(model, "detect")
    result = get_predictor(spec.name).predict(image)

    detections = [
        {
            "bbox": [round(float(v), 2) for v in box],
            "class_id": int(class_id),
            "class": spec.label(class_id),
            "confidence": round(float(score), 4),
        }
        for box, score, class_id in zip(result.boxes, result.scores, result.class_ids)
    ]

    canvas = draw_detections(image, result, class_names=spec.class_names)
    out_b64 = image_utils.image_to_base64(canvas)

    logger.info("detection task done: model=%s, %d objects, total=%.1fms",
                spec.name, len(detections), (time.perf_counter() - t_start) * 1000)
    return out_b64, detections
