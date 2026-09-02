"""Batch near-duplicate detection: embed all -> pairwise cosine -> threshold
-> union-find groups.

Semantics: the batch is the universe — every image is compared against every
OTHER image in the same request (no gallery, no index, stateless). The task
only IDENTIFIES duplicate groups; deletion decisions stay with the caller
(see docs/embedding.md §2). Exact duplicates (byte-identical files) are not
this task's job — MD5 handles those without an embedding engine.

The near-duplicate threshold is the shared business knob
(tasks.embedding.dup_threshold, INFERFORGE_DUP_THRESHOLD default 0.95):
"how similar counts as the same image" is a business decision, so it lives
in the task layer, not the engine.
"""
import logging
import time

import numpy as np

from tasks import embedding
from utils import image as image_utils

logger = logging.getLogger("tasks.dedup")

MAX_IMAGES = 50  # batch ceiling: O(N^2) pairwise + N embeddings, sync API


def dedup_vectors(vectors: np.ndarray, threshold: float) -> list:
    """Group L2-normalized vectors into near-duplicate clusters.

    Pure-NumPy union-find over pairs with cosine similarity >= threshold:
    near-duplication is TRANSITIVE (A~B, B~C groups A/B/C even when A~C is
    below the threshold — greedy pairing would split the chain), so
    connected components, not pairs, are the right output shape.

    Returns groups as [{"ids": [..], "representative": int, "confidence":
    float}], size-descending; single-image groups are dropped. Confidence is
    the representative's mean cosine to the rest of its group.
    """
    n = len(vectors)
    if n < 2:
        return []

    sims = vectors @ vectors.T  # L2-normalized rows -> cosine similarities
    parent = list(range(n))
    rank = [0] * n

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]  # path halving
            i = parent[i]
        return i

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if rank[ra] < rank[rb]:
            ra, rb = rb, ra
        parent[rb] = ra
        if rank[ra] == rank[rb]:
            rank[ra] += 1

    for i in range(n):
        for j in range(i + 1, n):
            if sims[i, j] >= threshold:
                union(i, j)

    members = {}
    for i in range(n):
        members.setdefault(find(i), []).append(i)

    groups = []
    for group in members.values():
        if len(group) < 2:
            continue
        sub = sims[np.ix_(group, group)]
        # mean cosine to the OTHER members — zero the self-similarity
        # diagonal (always ~1.0) so it does not inflate the confidence
        np.fill_diagonal(sub, 0.0)
        means = sub.sum(axis=1) / (len(group) - 1)
        representative = group[int(np.argmax(means))]
        groups.append({
            "ids": sorted(group),
            "representative": representative,
            "confidence": round(float(means.max()), 4),
        })
    groups.sort(key=lambda g: (-len(g["ids"]), g["ids"][0]))
    return groups


def run_dedup(sources: list):
    """Run batch near-duplicate detection.

    `sources` is a list of dicts, each with exactly one of "image" (base64)
    or "url" (schema-validated; the task re-checks minimally). Returns
    {"groups": [...], "total": N, "duplicates": count}. Group ids are
    0-based positions in `sources`, stable for the caller to map back to
    its own storage.
    """
    t_start = time.perf_counter()

    if not isinstance(sources, list) or len(sources) < 2:
        raise ValueError("provide at least 2 images")
    if len(sources) > MAX_IMAGES:
        raise ValueError("at most %d images per request" % MAX_IMAGES)

    threshold = embedding.dup_threshold()
    vectors = np.stack([
        embedding.encode(image_utils.input_to_image(src.get("image"), src.get("url")))
        for src in sources
    ])
    groups = dedup_vectors(vectors, threshold)

    duplicates = sum(len(g["ids"]) for g in groups)
    logger.info("dedup task done: %d image(s), %d group(s), %d duplicate(s), total=%.1fms",
                len(sources), len(groups), duplicates, (time.perf_counter() - t_start) * 1000)
    return {"groups": groups, "total": len(sources), "duplicates": duplicates}
