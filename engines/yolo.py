"""YOLOv8n detection: ONNXRuntime inference with self-written pre/post processing.

The letterbox / decode / NMS logic is implemented from scratch based on public
documentation. No code is copied from the ultralytics repository (AGPL-3.0),
so this project stays MIT.
"""
import logging
import time
from typing import Tuple

import cv2
import numpy as np

from engines.base import BasePredictor, DetectionResult

logger = logging.getLogger("engines.yolo")

INPUT_SIZE = (640, 640)
CONF_THRES = 0.25
IOU_THRES = 0.45

COCO_CLASS_NAMES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat",
    "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack",
    "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball",
    "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket",
    "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator",
    "book", "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush",
]

CLASS_COLORS = [
    (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255),
    (0, 255, 255), (128, 0, 0), (0, 128, 0), (0, 0, 128), (128, 128, 0),
    (128, 0, 128), (0, 128, 128), (64, 64, 64), (192, 192, 192), (64, 0, 0),
    (0, 64, 0), (0, 0, 64), (64, 64, 0), (64, 0, 64), (0, 64, 64),
]


def letterbox(image: np.ndarray, new_shape: Tuple[int, int] = INPUT_SIZE,
              color: Tuple[int, int, int] = (114, 114, 114)):
    """Resize keeping aspect ratio, then pad to new_shape.

    Returns (padded, ratio, (pad_left, pad_top)).
    """
    h, w = image.shape[:2]
    ratio = min(new_shape[0] / h, new_shape[1] / w)
    new_w, new_h = int(round(w * ratio)), int(round(h * ratio))
    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    pad_w, pad_h = new_shape[1] - new_w, new_shape[0] - new_h
    pad_left, pad_top = pad_w // 2, pad_h // 2
    padded = cv2.copyMakeBorder(
        resized, pad_top, pad_h - pad_top, pad_left, pad_w - pad_left,
        cv2.BORDER_CONSTANT, value=color,
    )
    return padded, ratio, (pad_left, pad_top)


def decode(output: np.ndarray, conf_thres: float = CONF_THRES):
    """Decode raw (1, 84, 8400) output into (xyxy boxes, scores, class_ids).

    Boxes are in letterboxed 640x640 space.
    """
    preds = output[0].T  # (8400, 84): cx, cy, w, h + 80 class scores
    boxes = preds[:, :4]
    class_scores = preds[:, 4:]
    scores = class_scores.max(axis=1)
    class_ids = class_scores.argmax(axis=1)

    keep = scores >= conf_thres
    boxes, scores, class_ids = boxes[keep], scores[keep], class_ids[keep]

    xyxy = np.empty_like(boxes)
    xyxy[:, 0] = boxes[:, 0] - boxes[:, 2] / 2.0
    xyxy[:, 1] = boxes[:, 1] - boxes[:, 3] / 2.0
    xyxy[:, 2] = boxes[:, 0] + boxes[:, 2] / 2.0
    xyxy[:, 3] = boxes[:, 1] + boxes[:, 3] / 2.0
    return xyxy, scores, class_ids


def nms(boxes: np.ndarray, scores: np.ndarray, iou_thres: float = IOU_THRES) -> np.ndarray:
    """Pure-NumPy greedy NMS; returns indices to keep."""
    if len(boxes) == 0:
        return np.array([], dtype=int)
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        if order.size == 1:
            break
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        iou = inter / (areas[i] + areas[order[1:]] - inter)
        order = order[1:][iou <= iou_thres]
    return np.array(keep, dtype=int)


def draw_detections(image: np.ndarray, result: DetectionResult,
                    class_names=COCO_CLASS_NAMES) -> np.ndarray:
    """Draw bounding boxes and labels onto a copy of the image."""
    canvas = image.copy()
    for box, score, class_id in zip(result.boxes, result.scores, result.class_ids):
        x1, y1, x2, y2 = box.astype(int)
        color = CLASS_COLORS[int(class_id) % len(CLASS_COLORS)]
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
        label = "%s %.2f" % (class_names[int(class_id)], score)
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(canvas, (x1, y1 - th - 4), (x1 + tw, y1), color, -1)
        cv2.putText(canvas, label, (x1, y1 - 3), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return canvas


class YoloPredictor(BasePredictor):
    """YOLOv8n ONNX predictor (CPU)."""

    def __init__(self, input_size: Tuple[int, int] = INPUT_SIZE,
                 conf_thres: float = CONF_THRES, iou_thres: float = IOU_THRES):
        self.input_size = input_size
        self.conf_thres = conf_thres
        self.iou_thres = iou_thres
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

    def predict(self, image: np.ndarray) -> DetectionResult:
        t_total = time.perf_counter()

        padded, ratio, pad = letterbox(image, self.input_size)
        blob = padded[:, :, ::-1].transpose(2, 0, 1)[np.newaxis]  # BGR->RGB, CHW, batch
        blob = np.ascontiguousarray(blob, dtype=np.float32) / 255.0
        t_pre = time.perf_counter()

        output = self._session.run([self._output_name], {self._input_name: blob})[0]
        t_infer = time.perf_counter()

        boxes, scores, class_ids = decode(output, self.conf_thres)
        keep = nms(boxes, scores, self.iou_thres)
        boxes, scores, class_ids = boxes[keep], scores[keep], class_ids[keep]

        # back from letterboxed space to original image coordinates
        h, w = image.shape[:2]
        boxes[:, [0, 2]] = np.clip((boxes[:, [0, 2]] - pad[0]) / ratio, 0, w)
        boxes[:, [1, 3]] = np.clip((boxes[:, [1, 3]] - pad[1]) / ratio, 0, h)
        t_post = time.perf_counter()

        logger.info(
            "predict done: %d detections (pre=%.1fms, infer=%.1fms, post=%.1fms, total=%.1fms)",
            len(scores),
            (t_pre - t_total) * 1000,
            (t_infer - t_pre) * 1000,
            (t_post - t_infer) * 1000,
            (t_post - t_total) * 1000,
        )
        return DetectionResult(boxes=boxes, scores=scores, class_ids=class_ids.astype(int))
