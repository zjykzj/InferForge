"""Async agent with client polling: run the hair-count agent, store the result in Redis.

The client polls GET /predict/agent/query/<task_id> until the envelope
appears; the worker never contacts the client. Envelope ladder mirrors the
agent callback task (code 0 success / 1 invalid input / 2 download failure /
9 agent run failure / 10 unknown model / 3 internal), but delivery is a
Redis write instead of a callback POST — no retry logic.
"""
import logging

import requests
from celery import shared_task

from tasks.agent import run_hair_count
from tasks.vlm import LLMConfigError, LLMUpstreamError
from utils import redis_store
from utils.errors import ModelNotFound

logger = logging.getLogger("tasks.agent_query")


@shared_task(name="tasks.agent_query", bind=True)
def agent_query_task(self, image_b64=None, image_url=None, request_id="-", submitted_at=None,
                     model=None):
    """Run the hair-count agent and store the result envelope in Redis under the task id.

    request_id travels with the task so worker logs can be correlated with
    the submitting request (injected into log lines by utils.logger).
    submitted_at is transport metadata for the queue-wait metric
    (celery_app task_prerun) — never read by the task body. model is the
    registered detect model the agent's detection tool uses (absent -> the
    detect default; worker re-checks for web/worker registry drift).
    """
    logger.info("agent query task started: has_image=%s has_url=%s model=%s",
                bool(image_b64), bool(image_url), model)
    try:
        payload = {"code": 0, "message": "success",
                   "data": run_hair_count(image_b64=image_b64, image_url=image_url, model=model)}
    except ModelNotFound as exc:  # web/worker registry drift -> code 10, like detection
        logger.warning("agent rejected (model): %s", exc)
        payload = {"code": 10, "message": str(exc), "data": None}
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

    task_id = self.request.id  # always set in a worker; None only in direct .run() tests
    redis_store.set_result(task_id, payload)  # redis down -> raises -> task FAILURE (no retry)
    logger.info("agent query result stored: task_id=%s code=%s", task_id, payload["code"])
    return {"task_id": task_id, "code": payload["code"]}
