"""Detection task: owns its predictor and orchestrates the full pipeline.

input parsing -> inference -> drawing -> response payload.
A task may hold one or more predictors (each lazily loaded on first use,
kept resident afterwards); the API layer never sees any of them.
"""
import logging
import os
import threading
import time
from typing import Optional

from engines.base import BasePredictor
from engines.yolo import COCO_CLASS_NAMES, YoloPredictor, draw_detections
from utils import image as image_utils

logger = logging.getLogger("tasks.detection")

MODEL_PATH = os.environ.get(
    "INFERFORGE_MODEL_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models", "yolov8n.onnx"),
)

_predictor: Optional[BasePredictor] = None
_predictor_lock = threading.Lock()


def get_predictor() -> BasePredictor:
    """Lazily load the detector on first use; kept resident afterwards."""
    global _predictor
    if _predictor is None:
        with _predictor_lock:
            if _predictor is None:
                predictor = YoloPredictor()
                predictor.load(MODEL_PATH)
                _predictor = predictor
    return _predictor


def run_detection(image_b64=None, image_url=None):
    """Run the full detection pipeline.

    Returns (drawn_image_base64, detections) where detections is a list of
    {"bbox": [x1, y1, x2, y2], "class_id": int, "class": str, "confidence": float}.
    """
    t_start = time.perf_counter()

    image = image_utils.input_to_image(image_b64, image_url)

    result = get_predictor().predict(image)

    detections = [
        {
            "bbox": [round(float(v), 2) for v in box],
            "class_id": int(class_id),
            "class": COCO_CLASS_NAMES[int(class_id)],
            "confidence": round(float(score), 4),
        }
        for box, score, class_id in zip(result.boxes, result.scores, result.class_ids)
    ]

    canvas = draw_detections(image, result)
    out_b64 = image_utils.image_to_base64(canvas)

    logger.info("detection task done: %d objects, total=%.1fms",
                len(detections), (time.perf_counter() - t_start) * 1000)
    return out_b64, detections
