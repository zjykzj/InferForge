"""Classification task: owns its predictor and orchestrates the full pipeline.

input parsing -> inference -> top-k mapping -> response payload. The predictor
is lazily loaded on first use and kept resident afterwards; the API layer
never sees it. No drawing — classification returns text results only.
"""
import logging
import os
import threading
import time
from typing import Optional

from engines.base import BasePredictor
from engines.imagenet_classes import IMAGENET_CLASS_NAMES
from engines.yolo_cls import YoloClsPredictor
from utils import image as image_utils
from utils import metrics

logger = logging.getLogger("tasks.classification")

MODEL_PATH = os.environ.get(
    "INFERFORGE_CLS_MODEL_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models", "yolov8n-cls.onnx"),
)

_predictor: Optional[BasePredictor] = None
_predictor_lock = threading.Lock()


def get_predictor() -> BasePredictor:
    """Lazily load the classifier on first use; kept resident afterwards."""
    global _predictor
    if _predictor is None:
        with _predictor_lock:
            if _predictor is None:
                predictor = YoloClsPredictor()
                predictor.load(MODEL_PATH)
                _predictor = predictor
                metrics.mark_predictor_loaded(task="classify")
    return _predictor


def predictor_loaded() -> bool:
    """Whether the predictor has been loaded (pure check, no side effects)."""
    return _predictor is not None


def run_classification(image_b64=None, image_url=None):
    """Run the full classification pipeline.

    Returns the top-k classifications as a list of
    {"class_id": int, "class": str, "confidence": float}, sorted by
    confidence descending.
    """
    t_start = time.perf_counter()

    image = image_utils.input_to_image(image_b64, image_url)

    result = get_predictor().predict(image)

    classifications = [
        {
            "class_id": int(class_id),
            "class": IMAGENET_CLASS_NAMES[int(class_id)],
            "confidence": round(float(score), 4),
        }
        for class_id, score in zip(result.class_ids, result.scores)
    ]

    logger.info("classification task done: top-k=%d, total=%.1fms",
                len(classifications), (time.perf_counter() - t_start) * 1000)
    return classifications
