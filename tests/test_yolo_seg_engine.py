"""Unit tests for the segmentation engine's pure functions (no model needed).

The ONNX session is faked for find_seg_outputs; decode_seg / process_mask /
draw_segmentations are exercised on synthetic arrays.
"""
import numpy as np
import pytest

from engines.base import SegmentationResult
from engines.yolo import CLASS_COLORS
from engines.yolo_seg import (
    decode_seg,
    draw_segmentations,
    find_seg_outputs,
    process_mask,
)


class _FakeOutput:
    def __init__(self, name, shape):
        self.name = name
        self.shape = shape


class _FakeSession:
    def __init__(self, outputs):
        self._outputs = outputs

    def get_outputs(self):
        return self._outputs


def _session(outputs):
    return _FakeSession([_FakeOutput(name, shape) for name, shape in outputs])


# --- find_seg_outputs ---


def test_find_seg_outputs_by_shape_regardless_of_order():
    session = _session([
        ("output1", [1, 32, 160, 160]),  # prototype head first
        ("output0", [1, 116, 8400]),
    ])
    assert find_seg_outputs(session) == ("output0", "output1")


def test_find_seg_outputs_rejects_wrong_model():
    session = _session([
        ("output0", [1, 84, 8400]),  # plain detection head: no mask channels
        ("output1", [1, 32, 160, 160]),
    ])
    with pytest.raises(ValueError):
        find_seg_outputs(session)


# --- decode_seg ---


def _seg_output(anchor_cxcywh_scores, n_anchors=8400, conf_thres=0.25):
    """Build a (1, 116, 8400) segment head. Each entry is
    (cx, cy, w, h, class_id, score, coeff_seed); anchors without an entry
    carry all-zero scores (below the conf threshold) and are dropped."""
    out = np.zeros((1, 116, n_anchors), dtype=np.float32)
    for i, (cx, cy, w, h, class_id, score, seed) in enumerate(anchor_cxcywh_scores):
        out[0, 0, i] = cx
        out[0, 1, i] = cy
        out[0, 2, i] = w
        out[0, 3, i] = h
        out[0, 4 + class_id, i] = score
        out[0, 84:, i] = np.arange(32, dtype=np.float32) * seed + 1.0
    return out


def test_decode_seg_splits_columns_and_filters_by_confidence():
    out = _seg_output([
        (300.0, 300.0, 100.0, 100.0, 5, 0.9, 0.01),  # kept
        (100.0, 100.0, 50.0, 50.0, 3, 0.1, 0.02),   # below conf: dropped
    ])
    boxes, scores, class_ids, coeffs = decode_seg(out, conf_thres=0.25)
    assert len(boxes) == 1
    np.testing.assert_allclose(boxes[0], [250.0, 250.0, 350.0, 350.0])
    np.testing.assert_allclose(scores, [0.9])
    assert class_ids[0] == 5
    assert coeffs.shape == (1, 32)  # coefficients stay index-aligned with the box


def test_decode_seg_empty_result_when_nothing_passes():
    out = _seg_output([(300.0, 300.0, 100.0, 100.0, 5, 0.1, 0.01)])
    boxes, scores, class_ids, coeffs = decode_seg(out)
    assert len(boxes) == 0 and len(scores) == 0 and len(coeffs) == 0


# --- process_mask ---


def test_process_mask_maps_prototype_crop_back_to_original_coords():
    # Original image 400x200 letterboxed into 640x640: ratio=1.6, pad=(0, 160).
    prototypes = np.zeros((32, 160, 160), dtype=np.float32)
    prototypes[:, 80:100, 80:120] = 5.0  # a patch inside the box's proto crop
    coeffs = np.ones(32, dtype=np.float32) * 0.5

    mask = process_mask(coeffs, prototypes, np.array([100.0, 50.0, 300.0, 150.0]),
                        ratio=1.6, pad=(0, 160), orig_h=200, orig_w=400)
    assert mask.shape == (200, 400)
    assert mask.dtype == bool
    assert mask[120, 250]  # patch center, mapped through ratio+pad
    assert not mask[10, 10]  # outside the box entirely
    assert not mask[75, 175]  # inside the box but outside the prototype patch


def test_process_mask_degenerate_box_at_edge_returns_empty():
    prototypes = np.zeros((32, 160, 160), dtype=np.float32)
    coeffs = np.ones(32, dtype=np.float32)
    # box clipped to the image's right edge with zero width: no usable region
    mask = process_mask(coeffs, prototypes, np.array([400.0, 0.0, 400.0, 10.0]),
                        ratio=1.0, pad=(0, 0), orig_h=200, orig_w=400)
    assert not mask.any()


# --- draw_segmentations ---


def test_draw_segmentations_blends_masks_then_draws_boxes():
    image = np.zeros((64, 64, 3), dtype=np.uint8)
    masks = np.zeros((1, 64, 64), dtype=bool)
    masks[0, 10:20, 10:20] = True
    result = SegmentationResult(
        boxes=np.array([[10.0, 10.0, 20.0, 20.0]]),
        scores=np.array([0.9]),
        class_ids=np.array([0]),
        masks=masks,
    )
    canvas = draw_segmentations(image, result)
    assert canvas.shape == image.shape
    color = CLASS_COLORS[0]
    expected = [round(0.4 * c) for c in color]  # alpha blend onto black
    assert canvas[15, 15].tolist() == expected  # inside the mask, off the box border
    assert canvas[0, 0].tolist() == [0, 0, 0]  # untouched background
