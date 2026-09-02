"""Tests for batch near-duplicate detection: the union-find grouping
(pure function), the task orchestration and the /predict/dedup api."""
import base64

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from apis.sync_dedup import sync_dedup_router
from engines.base import BasePredictor, EmbeddingResult
from tasks import dedup, embedding


class FakeEmbedPredictor(BasePredictor):
    """Deterministic 4-d vector from the image content: identical images
    embed identically, different images embed far apart (cos ~0.7)."""

    def load(self, model_path):
        pass

    def predict(self, image):
        mean = float(image[:, :, 0].mean()) / 255.0
        v = np.array([mean, 1.0, 0.0, 0.0], dtype=np.float32)
        return EmbeddingResult(vector=v / np.linalg.norm(v))


@pytest.fixture()
def client(monkeypatch, app_factory):
    monkeypatch.setattr(embedding, "get_embedder", lambda model=None: FakeEmbedPredictor())
    return TestClient(app_factory(sync_dedup_router))


def _img_b64(value):
    img = np.full((64, 64, 3), value, dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return base64.b64encode(buf.tobytes()).decode("utf-8")


# --- pure union-find grouping ---


def test_dedup_vectors_transitive_grouping():
    # A~B and B~C are above the threshold but A~C is NOT: near-duplication is
    # transitive, so the connected component {A, B, C} is one group — greedy
    # pairing would split the chain. D is orthogonal to everyone.
    a = np.array([1.0, 0.0])
    b = np.array([0.96, 0.28])          # cos(a,b) = 0.96
    c = np.array([0.843, 0.538])        # cos(b,c) ~ 0.96, cos(a,c) ~ 0.843
    d = np.array([0.0, 1.0])
    groups = dedup.dedup_vectors(np.stack([a, b, c, d]), threshold=0.95)
    assert len(groups) == 1
    assert groups[0]["ids"] == [0, 1, 2]
    assert groups[0]["representative"] == 1  # B: highest mean sim to the group
    assert groups[0]["confidence"] == 0.96


def test_dedup_vectors_high_threshold_breaks_groups():
    a = np.array([1.0, 0.0])
    b = np.array([0.96, 0.28])
    groups = dedup.dedup_vectors(np.stack([a, b]), threshold=0.99)
    assert groups == []


def test_dedup_vectors_singleton_input():
    assert dedup.dedup_vectors(np.array([[1.0, 0.0]]), threshold=0.95) == []


# --- task + api ---


def test_dedup_api_groups_identical_images(client):
    dup = _img_b64(0)   # zeros
    diff = _img_b64(255)  # ones
    resp = client.post("/predict/dedup", json={"images": [
        {"image": dup}, {"image": dup}, {"image": diff},
    ]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["total"] == 3
    assert body["data"]["duplicates"] == 2
    assert body["data"]["groups"] == [{
        "ids": [0, 1],
        "representative": 0,
        "confidence": 1.0,
    }]


def test_dedup_api_all_distinct(client):
    resp = client.post("/predict/dedup", json={"images": [
        {"image": _img_b64(0)}, {"image": _img_b64(255)},
    ]})
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["groups"] == []
    assert body["data"]["duplicates"] == 0


def test_dedup_rejects_single_image(client):
    resp = client.post("/predict/dedup", json={"images": [{"image": _img_b64(0)}]})
    assert resp.status_code == 200
    assert resp.json()["code"] == 1  # schema min_length -> envelope, never 422


def test_dedup_rejects_oversized_batch(client):
    resp = client.post("/predict/dedup", json={"images": [
        {"image": _img_b64(0)} for _ in range(51)
    ]})
    assert resp.status_code == 200
    assert resp.json()["code"] == 1


def test_dedup_rejects_both_inputs_in_one_source(client):
    resp = client.post("/predict/dedup", json={"images": [
        {"image": _img_b64(0), "url": "http://x/y.jpg"},
        {"image": _img_b64(0)},
    ]})
    assert resp.status_code == 200
    assert resp.json()["code"] == 1


def test_dedup_rejects_empty_source(client):
    resp = client.post("/predict/dedup", json={"images": [{}, {"image": _img_b64(0)}]})
    assert resp.status_code == 200
    assert resp.json()["code"] == 1


def test_response_has_request_id(client):
    resp = client.post("/predict/dedup", json={"images": [
        {"image": _img_b64(0)}, {"image": _img_b64(0)},
    ]})
    rid = resp.headers.get("X-Request-ID")
    assert rid and len(rid) == 12
