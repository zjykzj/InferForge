"""Async detection with client polling: run detection, store the result in Redis.

The client polls GET /predict/query/<task_id> until the envelope appears; the
worker never contacts the client. Envelope ladder mirrors the callback task
(code 0 success / 1 invalid input / 2 download failure / 3 internal), but
delivery is a Redis write instead of a callback POST — no retry logic.
"""
import logging

import requests
from celery import shared_task

from tasks.detection import run_detection
from utils import redis_store

logger = logging.getLogger("tasks.detection_query")


@shared_task(name="tasks.detection_query", bind=True)
def detect_query_task(self, image_b64=None, image_url=None, request_id="-"):
    """Run detection and store the result envelope in Redis under the task id.

    request_id travels with the task so worker logs can be correlated with
    the submitting request (injected into log lines by utils.logger).
    """
    logger.info("query task started: has_image=%s has_url=%s",
                bool(image_b64), bool(image_url))
    try:
        out_image, detections = run_detection(image_b64=image_b64, image_url=image_url)
        payload = {"code": 0, "message": "success",
                   "data": {"image": out_image, "detections": detections}}
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
