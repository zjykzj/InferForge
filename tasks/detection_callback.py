"""Async detection with server-side callback: run detection, POST the result to callback_url.

The callback always fires exactly once — with a success envelope (code=0) or a
failure envelope (code=1/2/3). Only the callback POST itself is retried
(network failures), never the detection business errors.
"""
import logging
import time

import requests
from celery import shared_task

from tasks.detection import run_detection

logger = logging.getLogger("tasks.detection_callback")

CALLBACK_TIMEOUT = 10  # seconds
CALLBACK_MAX_RETRIES = 3
CALLBACK_RETRY_BASE_DELAY = 2  # seconds, exponential: 2, 4, 8


def _post_callback(callback_url, payload):
    """POST the payload, retrying transient network failures with backoff."""
    for attempt in range(CALLBACK_MAX_RETRIES):
        try:
            requests.post(callback_url, json=payload, timeout=CALLBACK_TIMEOUT)
            return
        except requests.RequestException:
            if attempt == CALLBACK_MAX_RETRIES - 1:
                raise
            delay = CALLBACK_RETRY_BASE_DELAY ** attempt
            logger.warning("callback post failed (attempt %d/%d), retrying in %ds: %s",
                           attempt + 1, CALLBACK_MAX_RETRIES, delay, callback_url)
            time.sleep(delay)


@shared_task(name="tasks.detection_callback", bind=True)
def detect_callback_task(self, callback_url, image_b64=None, image_url=None):
    """Run detection and POST the result (success or failure) to callback_url."""
    logger.info("callback task started: callback=%s has_image=%s has_url=%s",
                callback_url, bool(image_b64), bool(image_url))
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

    _post_callback(callback_url, payload)
    logger.info("callback delivered: %s (code=%s)", callback_url, payload["code"])
    return {"callback_url": callback_url, "code": payload["code"]}
