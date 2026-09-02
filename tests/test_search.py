"""Task-layer tests for gallery search / dupcheck.

milvus-lite never runs in tests: search_gallery is the thin seam the tests
patch (the module itself imports without pymilvus installed — the lazy
import rule keeps web and tests dependency-free)."""
import base64

import cv2
import numpy as np
import pytest

from engines.base import BasePredictor, EmbeddingResult
from tasks import embedding, search


class FakeEmbedPredictor(BasePredictor):
    def load(self, model_path):
        pass

    def predict(self, image):
        v = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        return EmbeddingResult(vector=v)


@pytest.fixture(autouse=True)
def fake_embedder(monkeypatch):
    monkeypatch.setattr(embedding, "get_embedder", lambda model=None: FakeEmbedPredictor())


def _tiny_image_b64():
    img = np.zeros((64, 64, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return base64.b64encode(buf.tobytes()).decode("utf-8")


HITS = [
    {"id": "bus.jpg", "path": "gallery/bus.jpg", "score": 0.991},
    {"id": "zidane.jpg", "path": "gallery/zidane.jpg", "score": 0.873},
]


# --- search ---


def test_run_search_returns_matches(monkeypatch):
    monkeypatch.setattr(search, "search_gallery", lambda vector, top_k=5: HITS[:top_k])
    matches = search.run_search(image_b64=_tiny_image_b64(), top_k=2)
    assert matches == HITS[:2]


def test_run_search_passes_top_k(monkeypatch):
    seen = {}

    def _fake(vector, top_k=5):
        seen["top_k"] = top_k
        return []

    monkeypatch.setattr(search, "search_gallery", _fake)
    search.run_search(image_b64=_tiny_image_b64(), top_k=10)
    assert seen["top_k"] == 10


def test_run_search_rejects_bad_base64(monkeypatch):
    monkeypatch.setattr(search, "search_gallery", lambda vector, top_k=5: [])
    with pytest.raises(ValueError):
        search.run_search(image_b64="!!not-base64!!")


# --- dupcheck ---


def test_run_dupcheck_found(monkeypatch):
    monkeypatch.setattr(search, "search_gallery", lambda vector, top_k=1: HITS[:1])
    result = search.run_dupcheck(image_b64=_tiny_image_b64())
    assert result["found"] is True
    assert result["match"]["id"] == "bus.jpg"
    assert result["threshold"] == 0.95  # shared default


def test_run_dupcheck_below_threshold(monkeypatch):
    monkeypatch.setattr(search, "search_gallery",
                        lambda vector, top_k=1: [{"id": "x", "path": "p", "score": 0.5}])
    result = search.run_dupcheck(image_b64=_tiny_image_b64())
    assert result["found"] is False
    assert result["match"] is None


def test_run_dupcheck_no_hits(monkeypatch):
    monkeypatch.setattr(search, "search_gallery", lambda vector, top_k=1: [])
    result = search.run_dupcheck(image_b64=_tiny_image_b64())
    assert result["found"] is False


def test_run_dupcheck_threshold_from_env(monkeypatch):
    monkeypatch.setenv("INFERFORGE_DUP_THRESHOLD", "0.999")
    monkeypatch.setattr(search, "search_gallery", lambda vector, top_k=1: HITS[:1])
    result = search.run_dupcheck(image_b64=_tiny_image_b64())
    assert result["found"] is False  # 0.991 < 0.999
    assert result["threshold"] == 0.999


def test_dup_threshold_bad_env_falls_back(monkeypatch):
    monkeypatch.setenv("INFERFORGE_DUP_THRESHOLD", "not-a-float")
    assert embedding.dup_threshold() == 0.95
