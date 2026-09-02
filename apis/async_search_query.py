"""POST /predict/search/query + GET /predict/search/query/<task_id> — async gallery search with client polling.

Submit a gallery retrieval task; the worker stores the result envelope in
Redis; the client polls until the envelope appears. Poll semantics mirror
the vlm query api: missing key -> code 4, pending marker -> code 5, final
envelope returned verbatim (code 0/1/2/10/3 + data). Query-only by design:
the milvus-lite gallery db is single-process exclusive, so the search runs
only in the celery worker (docs/embedding.md §5). Registered only when
INFERFORGE_ASYNC=1 and INFERFORGE_SEARCH=1 (see app.py).
"""
import json
import logging
import time

from fastapi import APIRouter, Request

from apis.schemas import SearchRequest
from tasks.search_query import search_query_task
from utils import redis_store, request_id, response

logger = logging.getLogger("apis.async_search_query")

async_search_query_router = APIRouter()


@async_search_query_router.post("/predict/search/query")
def submit_search_query(request: Request, payload: SearchRequest):
    image_b64 = payload.image
    image_url = payload.url

    logger.info("search query request: remote=%s has_image=%s has_url=%s top_k=%s",
                request.client.host if request.client else "-",
                bool(image_b64), bool(image_url), payload.top_k)

    try:
        task = search_query_task.delay(
            image_b64=image_b64,
            image_url=image_url,
            top_k=payload.top_k,
            request_id=request_id.get_request_id(),
            submitted_at=time.time(),  # wall clock: queue-wait metric (celery_app task_prerun)
        )
        redis_store.set_pending(task.id)  # NX: never clobbers an already-written result
    except Exception:  # broker unreachable, redis down, serialization failure, ...
        logger.exception("failed to submit search query task")
        return response.error("failed to submit task", code=3)

    logger.info("search query task submitted: task_id=%s", task.id)
    return response.success({"task_id": task.id})


@async_search_query_router.get("/predict/search/query/{task_id}")
def poll_search_query(task_id: str):
    logger.info("search query poll: task_id=%s", task_id)
    try:
        raw = redis_store.get_result(task_id)
    except Exception:  # redis unreachable
        logger.exception("failed to read result from redis")
        return response.error("internal server error", code=3)
    if raw is None:
        return response.error("task not found", code=4)
    if raw == redis_store.PENDING_VALUE:
        return response.error("task is still processing", code=5)
    try:
        payload = json.loads(raw)
    except ValueError:
        logger.error("corrupt result payload: task_id=%s", task_id)
        return response.error("internal server error", code=3)
    if not isinstance(payload, dict):
        logger.error("result payload is not an envelope: task_id=%s", task_id)
        return response.error("internal server error", code=3)
    return response.JSONResponse(payload)  # worker-stored envelope verbatim (code 0/1/2/10/3 + data)
