"""Segmentation task: owns its predictors and orchestrates the full pipeline.

input parsing -> inference -> mask encoding + overlay drawing -> response
payload. Predictors are lazily loaded on first use and kept resident
afterwards; the API layer never sees them. Which predictor a request gets
is decided by the model registry (engines.registry) — the `model` field or,
when absent, the segment default.
"""
import logging
import threading
import time
from typing import Optional

import numpy as np

from engines import registry
from engines.base import BasePredictor
from engines.yolo_seg import YoloSegPredictor, draw_segmentations
from utils import image as image_utils
from utils import metrics

logger = logging.getLogger("tasks.segmentation")

# Per-model predictors, keyed by registered model name. A single lock covers
# all models (see tasks.detection for the rationale).
_predictors: dict[str, BasePredictor] = {}
_predictors_lock = threading.Lock()


def get_predictor(model: Optional[str] = None) -> BasePredictor:
    """Lazily load the predictor for `model` (or the segment default) on
    first use; kept resident afterwards."""
    spec = registry.resolve(model, "segment")
    if spec.name not in _predictors:
        with _predictors_lock:
            if spec.name not in _predictors:
                predictor = YoloSegPredictor()
                predictor.load(spec.path)
                _predictors[spec.name] = predictor
                metrics.mark_predictor_loaded(task="segment", model=spec.name)
    return _predictors[spec.name]


def preload() -> None:
    """Warmup: load the segment default model now instead of on first
    request (see tasks.detection.preload for the semantics)."""
    get_predictor()


def predictor_loaded(model: Optional[str] = None) -> bool:
    """Whether the predictor for `model` (or the segment default) has been
    loaded (pure check, no side effects)."""
    name = registry.resolve(model, "segment").name
    return name in _predictors


def default_model_loaded() -> bool:
    """Readiness probe: is the segment DEFAULT model loaded? False (not an
    exception) when no segment model is registered at all."""
    try:
        return predictor_loaded()
    except registry.ModelNotFound:
        return False


def run_segmentation(image_b64=None, image_url=None, model=None):
    """Run the full segmentation pipeline.

    Returns (overlay_image_base64, segments) where segments is a list of
    {"bbox": [x1, y1, x2, y2], "class_id": int, "class": str,
     "confidence": float, "mask": base64 PNG of the full-image binary mask}.
    """
    t_start = time.perf_counter()

    image = image_utils.input_to_image(image_b64, image_url)

    spec = registry.resolve(model, "segment")
    result = get_predictor(spec.name).predict(image)

    segments = [
        {
            "bbox": [round(float(v), 2) for v in box],
            "class_id": int(class_id),
            "class": spec.label(class_id),
            "confidence": round(float(score), 4),
            "mask": image_utils.image_to_base64(
                (mask.astype(np.uint8) * 255), ext=".png"
            ),
        }
        for box, score, class_id, mask in zip(
            result.boxes, result.scores, result.class_ids, result.masks
        )
    ]

    canvas = draw_segmentations(image, result, class_names=spec.class_names)
    out_b64 = image_utils.image_to_base64(canvas)

    logger.info("segmentation task done: model=%s, %d segments, total=%.1fms",
                spec.name, len(segments), (time.perf_counter() - t_start) * 1000)
    return out_b64, segments
