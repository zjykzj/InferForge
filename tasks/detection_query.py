"""Async detection with client polling: run detection, store the result in Redis.

The client polls GET /predict/query/<task_id> until the envelope appears; the
worker never contacts the client. Envelope ladder mirrors the callback task
(code 0 success / 1 invalid input / 2 download failure / 3 internal / 10
model not found), but delivery is a Redis write instead of a callback POST —
no retry logic. Code 10 normally gets rejected at submission; the worker
guards it again because web and worker each parse the registry and their
copies can drift (deploy skew).
"""
import logging

import requests
from celery import shared_task

from tasks.detection import run_detection
from utils import errors, redis_store

logger = logging.getLogger("tasks.detection_query")


@shared_task(name="tasks.detection_query", bind=True)
def detect_query_task(self, image_b64=None, image_url=None, model=None,
                      request_id="-", submitted_at=None):
    """Run detection and store the result envelope in Redis under the task id.

    request_id travels with the task so worker logs can be correlated with
    the submitting request (injected into log lines by utils.logger).
    submitted_at is transport metadata for the queue-wait metric
    (celery_app task_prerun) — never read by the task body.
    """
    logger.info("query task started: has_image=%s has_url=%s model=%s",
                bool(image_b64), bool(image_url), model)
    try:
        out_image, detections = run_detection(image_b64=image_b64, image_url=image_url,
                                              model=model)
        payload = {"code": 0, "message": "success",
                   "data": {"image": out_image, "detections": detections}}
    except errors.ModelNotFound as exc:  # registry drift between web and worker
        logger.warning("detection rejected (model): %s", exc)
        payload = {"code": 10, "message": str(exc), "data": None}
    except ValueError as exc:  # invalid input
        logger.warning("detection rejected: %s", exc)
        payload = {"code": 1, "message": str(exc), "data": None}
    except requests.RequestException as exc:  # image download failure
        logger.warning("detection failed (download): %s", exc)
        payload = {"code": 2, "message": "failed to download image: %s" % exc, "data": None}
    except Exception:  # unexpected internal error
        logger.exception("detection failed (internal)")
        payload = {"code": 3, "message": "internal server error", "data": None}

    task_id = self.request.id  # always set in a worker; None only in direct .run() tests
    redis_store.set_result(task_id, payload)  # redis down -> raises -> task FAILURE (no retry)
    logger.info("query result stored: task_id=%s code=%s", task_id, payload["code"])
    return {"task_id": task_id, "code": payload["code"]}
