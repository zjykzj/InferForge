"""Async VLM with client polling: run the remote LLM call, store the result in Redis.

The client polls GET /predict/vlm/query/<task_id> until the envelope appears;
the worker never contacts the client. Envelope ladder mirrors the vlm callback
task (code 0 success / 1 invalid input / 2 download failure / 9 upstream LLM
failure / 3 internal), but delivery is a Redis write instead of a callback
POST — no retry logic.
"""
import logging

import requests
from celery import shared_task

from tasks.vlm import LLMConfigError, LLMUpstreamError, run_vlm
from utils import redis_store

logger = logging.getLogger("tasks.vlm_query")


@shared_task(name="tasks.vlm_query", bind=True)
def vlm_query_task(self, image_b64=None, image_url=None, request_id="-"):
    """Run the remote VLM call and store the result envelope in Redis under the task id.

    request_id travels with the task so worker logs can be correlated with
    the submitting request (injected into log lines by utils.logger).
    """
    logger.info("vlm query task started: has_image=%s has_url=%s",
                bool(image_b64), bool(image_url))
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

    task_id = self.request.id  # always set in a worker; None only in direct .run() tests
    redis_store.set_result(task_id, payload)  # redis down -> raises -> task FAILURE (no retry)
    logger.info("vlm query result stored: task_id=%s code=%s", task_id, payload["code"])
    return {"task_id": task_id, "code": payload["code"]}
