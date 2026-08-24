"""Async VLM with server-side callback: run the remote LLM call, POST the result to callback_url.

The callback always fires exactly once — with a success envelope (code=0) or
a failure envelope (code=1/2/3/9). Only the callback POST itself is retried
(network failures), never business errors — including code 9 (upstream LLM
failure after the SDK's built-in retries).
"""
import logging

import requests
from celery import shared_task

from tasks.detection_callback import post_callback
from tasks.vlm import LLMConfigError, LLMUpstreamError, run_vlm

logger = logging.getLogger("tasks.vlm_callback")


@shared_task(name="tasks.vlm_callback", bind=True)
def vlm_callback_task(self, callback_url, image_b64=None, image_url=None, request_id="-"):
    """Run the remote VLM call and POST the result (success or failure) to callback_url.

    request_id travels with the task so worker logs can be correlated with
    the submitting request (injected into log lines by utils.logger).
    """
    logger.info("vlm callback task started: callback=%s has_image=%s has_url=%s",
                callback_url, bool(image_b64), bool(image_url))
    try:
        answer, model = run_vlm(image_b64=image_b64, image_url=image_url)
        payload = {"code": 0, "message": "success",
                   "data": {"answer": answer, "model": model}}
    except ValueError as exc:  # invalid input
        logger.warning("vlm rejected: %s", exc)
        payload = {"code": 1, "message": str(exc), "data": None}
    except requests.RequestException as exc:  # image download failure
        logger.warning("vlm failed (download): %s", exc)
        payload = {"code": 2, "message": "failed to download image: %s" % exc, "data": None}
    except LLMUpstreamError as exc:  # remote call failed after SDK retries -> code 9
        logger.warning("vlm failed (upstream): %s", exc)
        payload = {"code": 9, "message": "upstream LLM call failed: %s" % exc, "data": None}
    except LLMConfigError as exc:  # missing env config -> code 3, message names the var
        logger.warning("vlm failed (config): %s", exc)
        payload = {"code": 3, "message": str(exc), "data": None}
    except Exception:  # unexpected internal error
        logger.exception("vlm failed (internal)")
        payload = {"code": 3, "message": "internal server error", "data": None}

    post_callback(callback_url, payload)
    logger.info("callback delivered: %s (code=%s)", callback_url, payload["code"])
    return {"callback_url": callback_url, "code": payload["code"]}
