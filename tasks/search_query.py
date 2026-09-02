"""Async gallery retrieval with client polling: run the search, store the result in Redis.

The client polls GET /predict/search/query/<task_id> until the envelope
appears; the worker never contacts the client. Envelope ladder mirrors the
vlm query task (code 0 success / 1 invalid input / 2 download failure / 10
model not registered / 3 internal), delivery is a Redis write — no retry.
Worker-only: this task is the one place the milvus-lite gallery db file is
opened (single-process exclusive, docs/embedding.md §5).
"""
import logging

import requests
from celery import shared_task

from tasks.search import run_search
from utils import errors, redis_store

logger = logging.getLogger("tasks.search_query")


@shared_task(name="tasks.search_query", bind=True)
def search_query_task(self, image_b64=None, image_url=None, top_k=5,
                      request_id="-", submitted_at=None):
    """Run the gallery search and store the result envelope in Redis under the task id.

    request_id travels with the task so worker logs can be correlated with
    the submitting request (injected into log lines by utils.logger).
    submitted_at is transport metadata for the queue-wait metric
    (celery_app task_prerun) — never read by the task body.
    """
    logger.info("search query task started: has_image=%s has_url=%s top_k=%s",
                bool(image_b64), bool(image_url), top_k)
    try:
        matches = run_search(image_b64=image_b64, image_url=image_url, top_k=top_k)
        payload = {"code": 0, "message": "success",
                   "data": {"matches": matches, "count": len(matches)}}
    except ValueError as exc:  # invalid input
        logger.warning("search rejected: %s", exc)
        payload = {"code": 1, "message": str(exc), "data": None}
    except requests.RequestException as exc:  # image download failure
        logger.warning("search failed (download): %s", exc)
        payload = {"code": 2, "message": "failed to download image: %s" % exc, "data": None}
    except errors.ModelNotFound as exc:  # no embed model registered -> code 10
        logger.warning("search rejected (model): %s", exc)
        payload = {"code": 10, "message": str(exc), "data": None}
    except Exception:  # unexpected internal error (incl. gallery index problems)
        logger.exception("search failed (internal)")
        payload = {"code": 3, "message": "internal server error", "data": None}

    task_id = self.request.id  # always set in a worker; None only in direct .run() tests
    redis_store.set_result(task_id, payload)  # redis down -> raises -> task FAILURE (no retry)
    logger.info("search query result stored: task_id=%s code=%s", task_id, payload["code"])
    return {"task_id": task_id, "code": payload["code"]}
