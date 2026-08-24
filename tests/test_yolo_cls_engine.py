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


def test_topk_sorts_probabilities_without_resoftmax():
    # the model head already emits softmax probabilities — topk must not
    # re-softmax them (that would flatten the distribution)
    out = np.zeros((1, 1000), dtype=np.float32)
    out[0, 5] = 0.5
    out[0, 7] = 0.3
    out[0, 0] = 0.2
    probs, idx = topk(out, k=3)
    assert idx.tolist() == [5, 7, 0]
    np.testing.assert_allclose(probs, [0.5, 0.3, 0.2])  # raw values, unchanged


def test_topk_default_k_is_five():
    probs = np.random.default_rng(0).dirichlet(np.ones(1000)).astype(np.float32)
    p, idx = topk(probs[np.newaxis])
    assert len(p) == 5 and len(idx) == 5
    assert p[0] >= p[1] >= p[2] >= p[3] >= p[4]  # sorted descending
