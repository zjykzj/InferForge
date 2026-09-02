"""Pipeline task: detect -> crop -> fine-grained classify, composing two
existing capabilities.

Business demo: the generic-object detector (COCO classes) locates objects of
interest, each box is cropped and re-classified by the ImageNet-1k model for
the fine-grained label (e.g. detect "bus" -> classify "school bus"). The
task owns NO predictors — it reuses tasks.detection and tasks.classification
through their get_predictor seams, the same composition style as tasks.agent
(which pairs detection with a remote LLM), only fully local.

Model routing: the registry DEFAULTS of the detect and classify capabilities
(no `model` request field — the pair is chosen by models/registry.yaml's
defaults, see docs/api.md). Target classes: INFERFORGE_PIPELINE_TARGETS
(default "car,truck,bus"), validated against the detect model's class table
— a class the detect model does not know is a config error (code 3 via
PipelineConfigError), not an empty result. The classifier is only loaded
once at least one crop needs it: a request matching no target class never
pays the classify-model load.

Metrics: no pipeline-specific labels — the two inner engines observe their
own phases under their own task labels (detect/classify).
"""
import logging
import os
import time

import cv2
import numpy as np

from engines import registry
from engines.yolo import CLASS_COLORS
from tasks import classification, detection
from utils import image as image_utils

logger = logging.getLogger("tasks.pipeline")

TARGETS_ENV = "INFERFORGE_PIPELINE_TARGETS"
DEFAULT_TARGETS = "car,truck,bus"

# Crop margin: fraction of the box width/height added on each side before
# classifying, clipped to the image bounds. Business knob, not an engine one.
CROP_MARGIN = 0.1


class PipelineConfigError(Exception):
    """The pipeline task is misconfigured (bad INFERFORGE_PIPELINE_TARGETS).

    Task-local (see utils.errors for the cross-layer classes): the pipeline
    router imports it and maps it to code 3, same convention as
    tasks.vlm.LLMConfigError.
    """


def _target_classes(spec: "registry.ModelSpec") -> list:
    """The detect classes the pipeline keeps, from INFERFORGE_PIPELINE_TARGETS
    (comma-separated, default car,truck,bus). Read at call time (tests
    monkeypatch env). Every target must exist in the detect model's class
    table — a miss names the env var, same convention as
    tasks.agent._validate_target_class."""
    raw = os.environ.get(TARGETS_ENV, DEFAULT_TARGETS)
    targets = list(dict.fromkeys(t.strip() for t in raw.split(",") if t.strip()))
    if not targets:
        raise PipelineConfigError("%s must name at least one class" % TARGETS_ENV)
    unknown = sorted(t for t in targets if t not in spec.class_names)
    if unknown:
        raise PipelineConfigError(
            "%s names %s — not a class of detect model %r; pick classes from "
            "the model's registry entry (classes file) or fix the variable"
            % (TARGETS_ENV, ", ".join(unknown), spec.name)
        )
    return targets


def _crop(image: np.ndarray, box: np.ndarray, margin: float = CROP_MARGIN) -> "np.ndarray | None":
    """Crop a box out of the image, padded by `margin` of the box size and
    clipped to the image bounds. None for a degenerate (sub-pixel) box."""
    h, w = image.shape[:2]
    x1, y1, x2, y2 = (float(v) for v in box)
    bw, bh = x2 - x1, y2 - y1
    if bw < 1.0 or bh < 1.0:
        return None
    x1 = max(0.0, x1 - margin * bw)
    y1 = max(0.0, y1 - margin * bh)
    x2 = min(float(w), x2 + margin * bw)
    y2 = min(float(h), y2 + margin * bh)
    x1i, y1i, x2i, y2i = int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2))
    if x2i <= x1i or y2i <= y1i:
        return None
    return image[y1i:y2i, x1i:x2i]


def draw_pipeline_items(image: np.ndarray, items: list) -> np.ndarray:
    """Draw each recognized object: detect-class box + fine-grained label.

    Task-layer presentation of the COMPOSED result — unlike
    engines.yolo.draw_detections, which renders a single engine's output.
    """
    canvas = image.copy()
    for i, item in enumerate(items):
        x1, y1, x2, y2 = (int(round(v)) for v in item["bbox"])
        color = CLASS_COLORS[i % len(CLASS_COLORS)]
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
        label = "%s: %s %.2f" % (item["detect_class"], item["fine_class"], item["fine_confidence"])
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(canvas, (x1, y1 - th - 4), (x1 + tw, y1), color, -1)
        cv2.putText(canvas, label, (x1, y1 - 3), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return canvas


def run_pipeline(image_b64=None, image_url=None):
    """Run the full detect -> crop -> classify pipeline.

    Returns (annotated_image_base64, items) where items is a list of
    {"bbox": [x1, y1, x2, y2], "detect_class": str, "fine_class": str,
    "fine_confidence": float, "fine_top5": [{class_id, class, confidence}]}.
    """
    t_start = time.perf_counter()

    image = image_utils.input_to_image(image_b64, image_url)

    detect_spec = registry.resolve(None, "detect")
    targets = _target_classes(detect_spec)
    detect_result = detection.get_predictor(detect_spec.name).predict(image)
    kept = [
        (box, int(class_id))
        for box, class_id in zip(detect_result.boxes, detect_result.class_ids)
        if detect_spec.label(int(class_id)) in targets
    ]

    # Resolved up front so a registry without a classify model fails loudly
    # (code 10) even when no crop needs classifying; the predictor itself
    # loads lazily on the first crop.
    cls_spec = registry.resolve(None, "classify")
    cls_predictor = None

    items = []
    for box, class_id in kept:
        crop = _crop(image, box)
        if crop is None:
            continue
        if cls_predictor is None:
            cls_predictor = classification.get_predictor(cls_spec.name)
        cls_result = cls_predictor.predict(crop)
        fine_top5 = [
            {
                "class_id": int(cid),
                "class": cls_spec.label(cid),
                "confidence": round(float(score), 4),
            }
            for cid, score in zip(cls_result.class_ids, cls_result.scores)
        ]
        items.append({
            "bbox": [round(float(v), 2) for v in box],
            "detect_class": detect_spec.label(class_id),
            "fine_class": fine_top5[0]["class"],
            "fine_confidence": fine_top5[0]["confidence"],
            "fine_top5": fine_top5,
        })

    canvas = draw_pipeline_items(image, items)

    logger.info(
        "pipeline task done: detect=%s, classify=%s, %d item(s) of %d target box(es), total=%.1fms",
        detect_spec.name, cls_spec.name, len(items), len(kept),
        (time.perf_counter() - t_start) * 1000,
    )
    return image_utils.image_to_base64(canvas), items
