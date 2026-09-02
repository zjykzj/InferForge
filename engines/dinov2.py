"""DINOv2-small image embedding: ONNXRuntime inference with self-written
pre/post processing.

ViT-S/14: resize to 224x224 -> ImageNet normalize -> CLS token -> L2-normalized
384-d vector. Implemented from public documentation — no code copied from
external repositories (this project stays MIT).

The preprocessing below must match the ONNX export. DINOv2 exports vary
(interpolation, resize vs resize+center-crop, normalize or not): if the
export expects something else, adjust INPUT_SIZE / MEAN / STD here and
rebuild the gallery index (docs/embedding.md §3.1).

Weights are user-supplied, like every model in this project: export with
torch.onnx or take a pre-exported dino2-small ONNX and put it into models/.
The official DINOv2 weights are CC-BY-NC-4.0 — template demo only; a
commercial deployment should substitute a permitted backbone (the engine
contract and the search/dedup tasks don't care which one).
"""
import logging
import time

import cv2
import numpy as np

from engines.base import BasePredictor, EmbeddingResult
from utils import metrics

logger = logging.getLogger("engines.dinov2")

INPUT_SIZE = (224, 224)
MEAN = (0.485, 0.456, 0.406)   # ImageNet channel means
STD = (0.229, 0.224, 0.225)    # ImageNet channel stds


class DinoV2Predictor(BasePredictor):
    """DINOv2-small ONNX embedding predictor (CPU)."""

    def __init__(self, input_size: tuple = INPUT_SIZE):
        self.input_size = input_size
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
                    (time.perf_counter() - t0) * 1000, self._input_name, self._output_name)

    def predict(self, image: np.ndarray) -> EmbeddingResult:
        t_total = time.perf_counter()

        resized = cv2.resize(image, self.input_size, interpolation=cv2.INTER_LINEAR)
        blob = resized[:, :, ::-1].transpose(2, 0, 1)[np.newaxis]  # BGR->RGB, CHW, batch
        blob = np.ascontiguousarray(blob, dtype=np.float32) / 255.0
        mean = np.array(MEAN, dtype=np.float32).reshape(1, 3, 1, 1)
        std = np.array(STD, dtype=np.float32).reshape(1, 3, 1, 1)
        blob = (blob - mean) / std
        t_pre = time.perf_counter()

        output = self._session.run([self._output_name], {self._input_name: blob})[0]
        t_infer = time.perf_counter()

        # (1, 1 + (224/14)^2, 384) token sequence -> CLS token -> L2 normalize
        vector = output[0, 0].astype(np.float32)
        norm = float(np.linalg.norm(vector))
        if norm > 0:
            vector = vector / norm
        t_post = time.perf_counter()

        metrics.observe_phase("pre", t_pre - t_total, task="embed")
        metrics.observe_phase("infer", t_infer - t_pre, task="embed")
        metrics.observe_phase("post", t_post - t_infer, task="embed")

        logger.info("embed predict done: dim=%d (pre=%.1fms, infer=%.1fms, post=%.1fms, total=%.1fms)",
                    vector.shape[0],
                    (t_pre - t_total) * 1000,
                    (t_infer - t_pre) * 1000,
                    (t_post - t_infer) * 1000,
                    (t_post - t_total) * 1000,
                    )
        return EmbeddingResult(vector=vector)
