"""Async agent with server-side callback: run the hair-count agent, POST the result to callback_url.

The callback always fires exactly once — with a success envelope (code=0) or
a failure envelope (code=1/2/3/9). Only the callback POST itself is retried
(network failures), never business errors — including code 9 (agent run
failure after transport retries).
"""
import logging

import requests
from celery import shared_task

from tasks.agent import run_hair_count
from tasks.detection_callback import post_callback
from tasks.vlm import LLMConfigError, LLMUpstreamError

logger = logging.getLogger("tasks.agent_callback")


@shared_task(name="tasks.agent_callback", bind=True)
def agent_callback_task(self, callback_url, image_b64=None, image_url=None, request_id="-",
                        submitted_at=None):
    """Run the hair-count agent and POST the result (success or failure) to callback_url.

    request_id travels with the task so worker logs can be correlated with
    the submitting request (injected into log lines by utils.logger).
    submitted_at is transport metadata for the queue-wait metric
    (celery_app task_prerun) — never read by the task body.
    """
    logger.info("agent callback task started: callback=%s has_image=%s has_url=%s",
                callback_url, bool(image_b64), bool(image_url))
    try:
        payload = {"code": 0, "message": "success",
                   "data": run_hair_count(image_b64=image_b64, image_url=image_url)}
    except ValueError as exc:  # invalid input
        logger.warning("agent rejected: %s", exc)
        payload = {"code": 1, "message": str(exc), "data": None}
    except requests.RequestException as exc:  # image download failure
        logger.warning("agent failed (download): %s", exc)
        payload = {"code": 2, "message": "failed to download image: %s" % exc, "data": None}
    except LLMUpstreamError as exc:  # agent run failed after transport retries -> code 9
        logger.warning("agent failed (upstream): %s", exc)
        payload = {"code": 9, "message": "upstream LLM call failed: %s" % exc, "data": None}
    except LLMConfigError as exc:  # missing env config -> code 3, message names the var
        logger.warning("agent failed (config): %s", exc)
        payload = {"code": 3, "message": str(exc), "data": None}
    except Exception:  # unexpected internal error (incl. detection tool failures)
        logger.exception("agent failed (internal)")
        payload = {"code": 3, "message": "internal server error", "data": None}

    post_callback(callback_url, payload)
    logger.info("callback delivered: %s (code=%s)", callback_url, payload["code"])
    return {"callback_url": callback_url, "code": payload["code"]}
