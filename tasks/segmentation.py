"""Segmentation task: owns its predictor and orchestrates the full pipeline.

input parsing -> inference -> mask encoding + overlay drawing -> response
payload. The predictor is lazily loaded on first use and kept resident
afterwards; the API layer never sees it.
"""
import logging
import os
import threading
import time
from typing import Optional

import numpy as np

from engines.base import BasePredictor
from engines.yolo import COCO_CLASS_NAMES
from engines.yolo_seg import YoloSegPredictor, draw_segmentations
from utils import image as image_utils
from utils import metrics

logger = logging.getLogger("tasks.segmentation")

MODEL_PATH = os.environ.get(
    "INFERFORGE_SEG_MODEL_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models", "yolov8n-seg.onnx"),
)

_predictor: Optional[BasePredictor] = None
_predictor_lock = threading.Lock()


def get_predictor() -> BasePredictor:
    """Lazily load the segmenter on first use; kept resident afterwards."""
    global _predictor
    if _predictor is None:
        with _predictor_lock:
            if _predictor is None:
                predictor = YoloSegPredictor()
                predictor.load(MODEL_PATH)
                _predictor = predictor
                metrics.mark_predictor_loaded(task="segment")
    return _predictor


def predictor_loaded() -> bool:
    """Whether the predictor has been loaded (pure check, no side effects)."""
    return _predictor is not None


def run_segmentation(image_b64=None, image_url=None):
    """Run the full segmentation pipeline.

    Returns (overlay_image_base64, segments) where segments is a list of
    {"bbox": [x1, y1, x2, y2], "class_id": int, "class": str,
     "confidence": float, "mask": base64 PNG of the full-image binary mask}.
    """
    t_start = time.perf_counter()

    image = image_utils.input_to_image(image_b64, image_url)

    result = get_predictor().predict(image)

    segments = [
        {
            "bbox": [round(float(v), 2) for v in box],
            "class_id": int(class_id),
            "class": COCO_CLASS_NAMES[int(class_id)],
            "confidence": round(float(score), 4),
            "mask": image_utils.image_to_base64(
                (mask.astype(np.uint8) * 255), ext=".png"
            ),
        }
        for box, score, class_id, mask in zip(
            result.boxes, result.scores, result.class_ids, result.masks
        )
    ]

    canvas = draw_segmentations(image, result)
    out_b64 = image_utils.image_to_base64(canvas)

    logger.info("segmentation task done: %d segments, total=%.1fms",
                len(segments), (time.perf_counter() - t_start) * 1000)
    return out_b64, segments
