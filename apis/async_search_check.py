"""POST /predict/search/check + GET /predict/search/check/<task_id> — async gallery duplicate check with client polling.

Same shape as the search query api (submit + poll, query-only, worker-run —
see apis/async_search_query for the rationale); the business difference is
the output: a yes/no duplicate decision against the shared threshold
instead of a ranked list (docs/embedding.md §1). Registered only when
INFERFORGE_ASYNC=1 and INFERFORGE_SEARCH=1 (see app.py).
"""
import json
import logging
import time

from fastapi import APIRouter, Request

from apis.schemas import CheckRequest
from tasks.search_check_query import search_check_query_task
from utils import redis_store, request_id, response

logger = logging.getLogger("apis.async_search_check")

async_search_check_router = APIRouter()


@async_search_check_router.post("/predict/search/check")
def submit_search_check(request: Request, payload: CheckRequest):
    image_b64 = payload.image
    image_url = payload.url

    logger.info("search check request: remote=%s has_image=%s has_url=%s",
                request.client.host if request.client else "-",
                bool(image_b64), bool(image_url))

    try:
        task = search_check_query_task.delay(
            image_b64=image_b64,
            image_url=image_url,
            request_id=request_id.get_request_id(),
            submitted_at=time.time(),  # wall clock: queue-wait metric (celery_app task_prerun)
        )
        redis_store.set_pending(task.id)  # NX: never clobbers an already-written result
    except Exception:  # broker unreachable, redis down, serialization failure, ...
        logger.exception("failed to submit search check task")
        return response.error("failed to submit task", code=3)

    logger.info("search check task submitted: task_id=%s", task.id)
    return response.success({"task_id": task.id})


@async_search_check_router.get("/predict/search/check/{task_id}")
def poll_search_check(task_id: str):
    logger.info("search check poll: task_id=%s", task_id)
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
