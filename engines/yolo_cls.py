"""YOLOv8-cls image classification: ONNXRuntime inference with self-written
pre/post processing.

The preprocess mirrors the ultralytics classify transform (BGR->RGB,
PIL-bilinear resize with the shorter edge at 224, center-crop 224x224, /255)
— implemented from scratch; the resize deliberately uses Pillow because the
cv2 bilinear kernel differs measurably from PIL's (up to ~0.5 normalized
values), and the model was trained with the PIL pipeline. No code is copied
from the ultralytics repository (AGPL-3.0), so this project stays MIT.
"""
import logging
import time
from typing import Tuple

import cv2
import numpy as np
from PIL import Image

from engines.base import BasePredictor, ClassificationResult
from utils import metrics

logger = logging.getLogger("engines.yolo_cls")

INPUT_SIZE = 224
TOP_K = 5


def preprocess(image: np.ndarray) -> np.ndarray:
    """BGR uint8 (H, W, 3) -> (1, 3, 224, 224) float32 RGB in [0, 1].

    Mirrors the ultralytics classify transform (self-written): BGR->RGB,
    PIL-bilinear resize with the shorter edge at 224 (torchvision Resize(224)
    semantics — the longer edge is int(224 * h / w), truncated), center-crop
    224x224, /255, CHW. cv2.INTER_LINEAR is NOT equivalent to PIL bilinear —
    the resample phase would visibly degrade the probabilities.
    """
    h, w = image.shape[:2]
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    if w < h:
        ow, oh = INPUT_SIZE, int(INPUT_SIZE * h / w)
    else:
        ow, oh = int(INPUT_SIZE * w / h), INPUT_SIZE
    resized = Image.fromarray(rgb).resize((ow, oh), Image.BILINEAR)
    y0, x0 = (oh - INPUT_SIZE) // 2, (ow - INPUT_SIZE) // 2
    crop = np.asarray(
        resized.crop((x0, y0, x0 + INPUT_SIZE, y0 + INPUT_SIZE)), dtype=np.float32
    )
    blob = crop.transpose(2, 0, 1)[np.newaxis] / 255.0
    return np.ascontiguousarray(blob, dtype=np.float32)


def topk(probs: np.ndarray, k: int = TOP_K) -> Tuple[np.ndarray, np.ndarray]:
    """(1, 1000) probabilities -> ((k,) probs sorted descending, (k,) ids).

    The exported yolov8n-cls head already applies softmax (the ultralytics
    ClassificationModel emits probabilities, not logits) — softmaxing again
    would flatten the distribution, so topk only sorts and truncates.
    """
    probs = probs[0]
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
