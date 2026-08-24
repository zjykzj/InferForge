"""YOLOv8-seg instance segmentation: ONNXRuntime inference with self-written
decode / mask / overlay post-processing.

The segment head (1, 116, 8400) carries 4 box coords + 80 class scores + 32
mask coefficients; the prototype head (1, 32, 160, 160) holds the shared
prototype masks. The mask pipeline (crop -> matmul -> sigmoid -> threshold ->
paste) is implemented from scratch based on public documentation. No code is
copied from the ultralytics repository (AGPL-3.0), so this project stays MIT.

Reuses the detection module's letterbox / nms / colors (same-layer import).
"""
import logging
import time
from typing import Tuple

import cv2
import numpy as np

from engines.base import BasePredictor, SegmentationResult
from engines.yolo import (
    CLASS_COLORS,
    COCO_CLASS_NAMES,
    CONF_THRES,
    INPUT_SIZE,
    IOU_THRES,
    draw_detections,
    letterbox,
    nms,
)
from utils import metrics

logger = logging.getLogger("engines.yolo_seg")

PROTO_SIZE = (160, 160)
MASK_THRES = 0.5
OVERLAY_ALPHA = 0.4


def sigmoid(x: np.ndarray) -> np.ndarray:
    """Numerically stable sigmoid (overflow-safe for large logits)."""
    return 1.0 / (1.0 + np.exp(-x))


def find_seg_outputs(session) -> Tuple[str, str]:
    """Return (seg_head_name, proto_head_name), identified by output shape
    rather than order — exporters may emit outputs in either sequence.

    The segment head is (1, 116, 8400) and the prototype head (1, 32, 160,
    160). Raises ValueError if either is missing (wrong model file). Note:
    exports with dynamic axes (None in the shape) would need name-based
    matching — not handled here.
    """
    seg_name = proto_name = None
    for out in session.get_outputs():
        shape = out.shape
        if len(shape) == 3 and shape[0] == 1 and shape[1] == 116:
            seg_name = out.name
        elif len(shape) == 4 and shape[0] == 1 and shape[1] == 32:
            proto_name = out.name
    if seg_name is None or proto_name is None:
        raise ValueError(
            "cannot identify the (1,116,8400) / (1,32,160,160) outputs — is this a yolov8-seg model?"
        )
    return seg_name, proto_name


def decode_seg(output: np.ndarray, conf_thres: float = CONF_THRES):
    """Decode the (1, 116, 8400) segment head.

    Columns per anchor: 4 box (cx, cy, w, h) + 80 class scores + 32 mask
    coefficients. Returns (xyxy boxes in letterboxed space, scores, class_ids,
    mask_coeffs) — all four index-aligned so the NMS subset keeps them paired.
    """
    preds = output[0].T  # (8400, 116)
    boxes = preds[:, :4]
    class_scores = preds[:, 4:84]
    mask_coeffs = preds[:, 84:]
    scores = class_scores.max(axis=1)
    class_ids = class_scores.argmax(axis=1)

    keep = scores >= conf_thres
    boxes, scores, class_ids, mask_coeffs = (
        boxes[keep], scores[keep], class_ids[keep], mask_coeffs[keep],
    )

    xyxy = np.empty_like(boxes)
    xyxy[:, 0] = boxes[:, 0] - boxes[:, 2] / 2.0
    xyxy[:, 1] = boxes[:, 1] - boxes[:, 3] / 2.0
    xyxy[:, 2] = boxes[:, 0] + boxes[:, 2] / 2.0
    xyxy[:, 3] = boxes[:, 1] + boxes[:, 3] / 2.0
    return xyxy, scores, class_ids, mask_coeffs


def process_mask(coeffs: np.ndarray, prototypes: np.ndarray, box: np.ndarray,
                 ratio: float, pad: Tuple[int, int],
                 orig_h: int, orig_w: int) -> np.ndarray:
    """Build one full-image binary mask for a kept box.

    coeffs: (32,) mask coefficients. prototypes: (32, 160, 160) proto grid.
    box: [x1, y1, x2, y2] in original-image pixels (already clipped to the
    image bounds by the caller). ratio / pad come from letterbox().

    Pipeline: map the box back into letterboxed input space, crop the
    prototype grid to that region, matmul with the coefficients, sigmoid,
    threshold, resize to the box's pixel size and paste onto an
    (orig_h, orig_w) canvas.
    """
    x1, y1, x2, y2 = box
    # original -> letterboxed input space (inverse of the yolo.py transform)
    x1_lb, x2_lb = x1 * ratio + pad[0], x2 * ratio + pad[0]
    y1_lb, y2_lb = y1 * ratio + pad[1], y2 * ratio + pad[1]
    # letterboxed -> prototype grid space (computed, not hardcoded: a
    # different proto-grid export still works)
    s = PROTO_SIZE[0] / INPUT_SIZE[0]
    px1 = min(PROTO_SIZE[0] - 1, max(0, int(x1_lb * s)))
    px2 = max(px1 + 1, min(PROTO_SIZE[0], int(np.ceil(x2_lb * s))))
    py1 = min(PROTO_SIZE[0] - 1, max(0, int(y1_lb * s)))
    py2 = max(py1 + 1, min(PROTO_SIZE[0], int(np.ceil(y2_lb * s))))

    crop = prototypes[:, py1:py2, px1:px2]  # (32, ph, pw)
    mask_map = sigmoid(coeffs @ crop.reshape(32, -1)).reshape(py2 - py1, px2 - px1)
    binary = (mask_map > MASK_THRES).astype(np.uint8) * 255

    # resize the prototype-space crop to the box's original-image pixel size
    x1i, y1i = int(x1), int(y1)
    bw = min(max(1, int(x2) - x1i), orig_w - x1i)
    bh = min(max(1, int(y2) - y1i), orig_h - y1i)
    if bw < 1 or bh < 1:  # degenerate box at the image edge: empty mask
        return np.zeros((orig_h, orig_w), dtype=bool)
    resized = cv2.resize(binary, (bw, bh), interpolation=cv2.INTER_LINEAR) > 127

    canvas = np.zeros((orig_h, orig_w), dtype=bool)
    canvas[y1i:y1i + bh, x1i:x1i + bw] = resized
    return canvas


def draw_segmentations(image: np.ndarray, result: SegmentationResult,
                       class_names=COCO_CLASS_NAMES) -> np.ndarray:
    """Blend each instance mask (semi-transparent, per-class color) onto a
    copy of the image, then draw boxes/labels on top.

    Reuses draw_detections via duck typing — it only touches
    boxes/scores/class_ids, which SegmentationResult also carries.
    """
    canvas = image.copy()
    for mask, class_id in zip(result.masks, result.class_ids):
        color = CLASS_COLORS[int(class_id) % len(CLASS_COLORS)]
        region = canvas[mask]
        canvas[mask] = (OVERLAY_ALPHA * np.array(color)
                        + (1 - OVERLAY_ALPHA) * region).astype(np.uint8)
    return draw_detections(canvas, result, class_names=class_names)


class YoloSegPredictor(BasePredictor):
    """YOLOv8-seg ONNX predictor (CPU)."""

    def __init__(self, input_size: Tuple[int, int] = INPUT_SIZE,
                 conf_thres: float = CONF_THRES, iou_thres: float = IOU_THRES):
        self.input_size = input_size
        self.conf_thres = conf_thres
        self.iou_thres = iou_thres
        self._session = None
        self._input_name = None
        self._seg_name = None
        self._proto_name = None

    def load(self, model_path: str) -> None:
        import onnxruntime  # deferred: keeps the module import light

        logger.info("loading model: %s", model_path)
        t0 = time.perf_counter()
        self._session = onnxruntime.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        self._input_name = self._session.get_inputs()[0].name
        self._seg_name, self._proto_name = find_seg_outputs(self._session)
        logger.info("model loaded in %.1fms (input=%s, seg=%s, proto=%s)",
                    (time.perf_counter() - t0) * 1000,
                    self._input_name, self._seg_name, self._proto_name)

    def predict(self, image: np.ndarray) -> SegmentationResult:
        t_total = time.perf_counter()

        padded, ratio, pad = letterbox(image, self.input_size)
        blob = padded[:, :, ::-1].transpose(2, 0, 1)[np.newaxis]  # BGR->RGB, CHW, batch
        blob = np.ascontiguousarray(blob, dtype=np.float32) / 255.0
        t_pre = time.perf_counter()

        seg_out, proto_out = self._session.run(
            [self._seg_name, self._proto_name], {self._input_name: blob}
        )
        t_infer = time.perf_counter()

        boxes, scores, class_ids, coeffs = decode_seg(seg_out, self.conf_thres)
        keep = nms(boxes, scores, self.iou_thres)
        boxes, scores, class_ids, coeffs = (
            boxes[keep], scores[keep], class_ids[keep], coeffs[keep],
        )

        # back from letterboxed space to original image coordinates
        h, w = image.shape[:2]
        boxes[:, [0, 2]] = np.clip((boxes[:, [0, 2]] - pad[0]) / ratio, 0, w)
        boxes[:, [1, 3]] = np.clip((boxes[:, [1, 3]] - pad[1]) / ratio, 0, h)

        masks = np.zeros((len(boxes), h, w), dtype=bool)
        for i, box in enumerate(boxes):
            masks[i] = process_mask(coeffs[i], proto_out[0], box, ratio, pad, h, w)
        t_post = time.perf_counter()

        metrics.observe_phase("pre", t_pre - t_total, task="segment")
        metrics.observe_phase("infer", t_infer - t_pre, task="segment")
        metrics.observe_phase("post", t_post - t_infer, task="segment")

        logger.info(
            "segment predict done: %d segments (pre=%.1fms, infer=%.1fms, post=%.1fms, total=%.1fms)",
            len(scores),
            (t_pre - t_total) * 1000,
            (t_infer - t_pre) * 1000,
            (t_post - t_infer) * 1000,
            (t_post - t_total) * 1000,
        )
        return SegmentationResult(boxes=boxes, scores=scores,
                                  class_ids=class_ids.astype(int), masks=masks)
