"""Async gallery duplicate check with client polling: run the dupcheck, store
the result in Redis.

Same shape as tasks.search_query (query-only, Redis envelope, same error
ladder) — the business difference is the output: a yes/no decision against
the shared near-duplicate threshold instead of a ranked top-k list
(docs/embedding.md §1).
"""
import logging

import requests
from celery import shared_task

from tasks.search import run_dupcheck
from utils import errors, redis_store

logger = logging.getLogger("tasks.search_check_query")


@shared_task(name="tasks.search_check_query", bind=True)
def search_check_query_task(self, image_b64=None, image_url=None,
                            request_id="-", submitted_at=None):
    """Run the gallery duplicate check and store the result envelope in Redis
    under the task id (see tasks.search_query for the kwargs semantics)."""
    logger.info("search check task started: has_image=%s has_url=%s",
                bool(image_b64), bool(image_url))
    try:
        result = run_dupcheck(image_b64=image_b64, image_url=image_url)
        payload = {"code": 0, "message": "success", "data": result}
    except ValueError as exc:  # invalid input
        logger.warning("dupcheck rejected: %s", exc)
        payload = {"code": 1, "message": str(exc), "data": None}
    except requests.RequestException as exc:  # image download failure
        logger.warning("dupcheck failed (download): %s", exc)
        payload = {"code": 2, "message": "failed to download image: %s" % exc, "data": None}
    except errors.ModelNotFound as exc:  # no embed model registered -> code 10
        logger.warning("dupcheck rejected (model): %s", exc)
        payload = {"code": 10, "message": str(exc), "data": None}
    except Exception:  # unexpected internal error
        logger.exception("dupcheck failed (internal)")
        payload = {"code": 3, "message": "internal server error", "data": None}

    task_id = self.request.id
    redis_store.set_result(task_id, payload)
    logger.info("search check result stored: task_id=%s code=%s", task_id, payload["code"])
    return {"task_id": task_id, "code": payload["code"]}
