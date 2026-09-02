"""Gallery retrieval + duplicate check: query the milvus-lite index built by
scripts/build_gallery.py.

Both business tasks share the same machinery: encode the image (tasks.embedding)
and query the gallery index. Retrieval returns the top-k ranked list — the
caller decides what "similar enough" means; dupcheck takes top-1 and applies
the near-duplicate threshold server-side (INFERFORGE_DUP_THRESHOLD, shared
with tasks.dedup) — a yes/no decision.

milvus-lite is worker-only: pymilvus is imported lazily inside function
bodies (same rule as openai/onnxruntime) so the web process and tests can
import this module without it installed. The gallery db file is
single-process exclusive (docs/embedding.md §5): only the celery worker
opens it — search/dupcheck are query-only worker tasks, and
scripts/build_gallery.py must run with the worker stopped.
"""
import logging
import os
import threading
import time

from tasks import embedding
from utils import image as image_utils

logger = logging.getLogger("tasks.search")

GALLERY_DB_ENV = "INFERFORGE_GALLERY_DB"
DEFAULT_GALLERY_DB = os.path.join("data", "gallery.db")
COLLECTION_NAME = "gallery"

_client = None
_client_lock = threading.Lock()


def gallery_db_path() -> str:
    """Where the milvus-lite db file is expected (INFERFORGE_GALLERY_DB or
    data/gallery.db, project-root relative — scripts/build_gallery.py writes
    the same path). Read at call time (tests monkeypatch env)."""
    return os.environ.get(GALLERY_DB_ENV, DEFAULT_GALLERY_DB)


def _gallery_client():
    """Lazily open the milvus-lite client. One process owns the db file; the
    client stays open for the process lifetime (worker only — the web process
    never calls this)."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                from pymilvus import MilvusClient  # deferred: worker-only dep

                path = gallery_db_path()
                _client = MilvusClient(path)
                # A freshly opened db has the collection in 'released'
                # state — search/get/query require a loaded collection
                # (idempotent: loading an already-loaded one is a no-op).
                _client.load_collection(COLLECTION_NAME)
                logger.info("gallery index opened: %s", path)
    return _client


def search_gallery(vector, top_k: int = 5) -> list:
    """Raw top-k query against the gallery index. Returns a list of
    {"id": str, "path": str, "score": float} sorted by score descending.

    The thin seam tests patch (milvus never runs in tests)."""
    hits = _gallery_client().search(
        collection_name=COLLECTION_NAME,
        data=[vector.tolist()],
        limit=top_k,
        output_fields=["path"],
        search_params={"metric_type": "COSINE"},  # L2-normalized vectors -> cosine
    )
    return [
        {"id": hit["id"], "path": hit["entity"]["path"], "score": round(float(hit["distance"]), 4)}
        for hit in (hits[0] if hits else [])
    ]


def run_search(image_b64=None, image_url=None, top_k: int = 5):
    """Retrieval: image -> vector -> top-k similar images from the gallery.

    Returns a list of {"id": str, "path": str, "score": float}."""
    t_start = time.perf_counter()

    image = image_utils.input_to_image(image_b64, image_url)
    vector = embedding.encode(image)
    matches = search_gallery(vector, top_k=top_k)

    logger.info("search task done: top-k=%d of %d hit(s), total=%.1fms",
                top_k, len(matches), (time.perf_counter() - t_start) * 1000)
    return matches


def run_dupcheck(image_b64=None, image_url=None):
    """Duplicate check: image -> vector -> top-1 -> threshold decision.

    Returns {"found": bool, "match": {id, path, score} | None,
    "threshold": float}. The threshold is the shared near-duplicate knob
    (tasks.embedding.dup_threshold) — "is there an image with the same
    content in the gallery" is the business question this answers."""
    t_start = time.perf_counter()

    threshold = embedding.dup_threshold()
    image = image_utils.input_to_image(image_b64, image_url)
    vector = embedding.encode(image)
    hits = search_gallery(vector, top_k=1)

    if hits and hits[0]["score"] >= threshold:
        result = {"found": True, "match": hits[0], "threshold": threshold}
    else:
        result = {"found": False, "match": None, "threshold": threshold}

    logger.info("dupcheck task done: found=%s score=%s total=%.1fms",
                result["found"],
                result["match"]["score"] if result["match"] else "-",
                (time.perf_counter() - t_start) * 1000)
    return result
