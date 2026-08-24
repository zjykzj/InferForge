"""Unit tests for the classification engine's pure functions (no model needed)."""
import numpy as np

from engines.imagenet_classes import IMAGENET_CLASS_NAMES
from engines.yolo_cls import INPUT_SIZE, preprocess, topk


# --- imagenet class table ---


def test_imagenet_table_has_1000_entries_in_standard_order():
    assert len(IMAGENET_CLASS_NAMES) == 1000
    assert IMAGENET_CLASS_NAMES[0] == "tench"
    assert IMAGENET_CLASS_NAMES[96] == "toucan"
    assert IMAGENET_CLASS_NAMES[151] == "Chihuahua"
    assert IMAGENET_CLASS_NAMES[999] == "toilet tissue"


# --- preprocess ---


def test_preprocess_output_shape_dtype_and_range():
    image = np.zeros((300, 400, 3), dtype=np.uint8)
    blob = preprocess(image)
    assert blob.shape == (1, 3, INPUT_SIZE, INPUT_SIZE)
    assert blob.dtype == np.float32
    assert blob.min() >= 0.0 and blob.max() <= 1.0


def test_preprocess_handles_non_square_images():
    image = np.full((100, 500, 3), 128, dtype=np.uint8)
    blob = preprocess(image)
    assert blob.shape == (1, 3, INPUT_SIZE, INPUT_SIZE)
    # 128/255 in the center crop (both channels and spatial dims)
    assert np.allclose(blob, 128 / 255.0)


# --- topk ---


def test_topk_sorts_descending_and_normalizes():
    # all logits far below the three interesting ones, so the top-3 order
    # is fully determined
    logits = np.full((1, 1000), -100.0, dtype=np.float32)
    logits[0, 5] = 3.0
    logits[0, 7] = 1.0
    logits[0, 0] = -1.0
    probs, idx = topk(logits, k=3)
    assert idx.tolist() == [5, 7, 0]
    assert probs[0] > probs[1] > probs[2]
    assert abs(probs.sum() - 1.0) < 1e-6


def test_topk_default_k_is_five():
    logits = np.random.default_rng(0).standard_normal((1, 1000)).astype(np.float32)
    probs, idx = topk(logits)
    assert len(probs) == 5 and len(idx) == 5
