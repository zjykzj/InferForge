"""YOLOv8-cls image classification: ONNXRuntime inference with self-written
pre/post processing.

The preprocess (resize shorter edge to 256 -> center-crop 224 -> RGB -> /255)
mirrors the ultralytics classify transform, implemented from scratch. No code
is copied from the ultralytics repository (AGPL-3.0), so this project stays
MIT.
"""
import logging
import time
from typing import Tuple

import cv2
import numpy as np

from engines.base import BasePredictor, ClassificationResult
from utils import metrics

logger = logging.getLogger("engines.yolo_cls")

INPUT_SIZE = 224
RESIZE_SHORT = 256
TOP_K = 5


def preprocess(image: np.ndarray) -> np.ndarray:
    """BGR uint8 (H, W, 3) -> (1, 3, 224, 224) float32 RGB in [0, 1].

    Mirrors the ultralytics classify transform (self-written): resize the
    shorter edge to 256 (bilinear), center-crop 224x224, BGR->RGB, /255.
    """
    h, w = image.shape[:2]
    scale = RESIZE_SHORT / min(h, w)
    resized = cv2.resize(
        image, (int(round(w * scale)), int(round(h * scale))),
        interpolation=cv2.INTER_LINEAR,
    )
    y0 = (resized.shape[0] - INPUT_SIZE) // 2
    x0 = (resized.shape[1] - INPUT_SIZE) // 2
    crop = resized[y0:y0 + INPUT_SIZE, x0:x0 + INPUT_SIZE]
    blob = crop[:, :, ::-1].transpose(2, 0, 1)[np.newaxis]  # BGR->RGB, CHW, batch
    return np.ascontiguousarray(blob, dtype=np.float32) / 255.0


def topk(logits: np.ndarray, k: int = TOP_K) -> Tuple[np.ndarray, np.ndarray]:
    """(1, 1000) logits -> ((k,) probs sorted descending, (k,) class ids)."""
    exp = np.exp(logits[0] - logits[0].max())  # stable softmax
    probs = exp / exp.sum()
    idx = probs.argsort()[::-1][:k]
    return probs[idx], idx


class YoloClsPredictor(BasePredictor):
    """YOLOv8-cls ONNX predictor (CPU)."""

    def __init__(self):
        self._session = None
        self._input_name = None
        self._output_name = None

    def load(self, model_path: str) -> None:
        import onnxruntime  # deferred: keeps the module import light

        logger.info("loading model: %s", model_path)
        t0 = time.perf_counter()
        self._session = onnxruntime.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        self._input_name = self._session.get_inputs()[0].name
        self._output_name = self._session.get_outputs()[0].name
        logger.info("model loaded in %.1fms (input=%s, output=%s)",
                    (time.perf_counter() - t0) * 1000,
                    self._input_name, self._output_name)

    def predict(self, image: np.ndarray) -> ClassificationResult:
        t_total = time.perf_counter()

        blob = preprocess(image)
        t_pre = time.perf_counter()

        logits = self._session.run([self._output_name], {self._input_name: blob})[0]
        t_infer = time.perf_counter()

        scores, class_ids = topk(logits)
        t_post = time.perf_counter()

        metrics.observe_phase("pre", t_pre - t_total, task="classify")
        metrics.observe_phase("infer", t_infer - t_pre, task="classify")
        metrics.observe_phase("post", t_post - t_infer, task="classify")

        logger.info(
            "classify predict done: top-1=%d (pre=%.1fms, infer=%.1fms, post=%.1fms, total=%.1fms)",
            int(class_ids[0]),
            (t_pre - t_total) * 1000,
            (t_infer - t_pre) * 1000,
            (t_post - t_infer) * 1000,
            (t_post - t_total) * 1000,
        )
        return ClassificationResult(scores=scores, class_ids=class_ids.astype(int))
