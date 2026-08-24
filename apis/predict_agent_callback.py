"""POST /predict/agent/callback — async agent with server-side callback.

Submit a hair-count agent task (image + fixed server-side instructions +
detection tool + remote LLM agent); when it finishes the server POSTs the
result (success or failure envelope) to the provided callback_url.
Registered only when INFERFORGE_ASYNC=1 and INFERFORGE_AGENT=1 (see app.py).
"""
import logging
import time

from fastapi import APIRouter, Request

from apis.schemas import CallbackRequest
from tasks.agent_callback import agent_callback_task
from utils import request_id, response

logger = logging.getLogger("apis.predict_agent_callback")

predict_agent_callback_router = APIRouter()


@predict_agent_callback_router.post("/predict/agent/callback")
def predict_agent_callback(request: Request, payload: CallbackRequest):
    image_b64 = payload.image
    image_url = payload.url
    callback_url = payload.callback_url

    logger.info("agent callback request: remote=%s has_image=%s has_url=%s",
                request.client.host if request.client else "-",
                bool(image_b64), bool(image_url))

    try:
        task = agent_callback_task.delay(
            callback_url,
            image_b64=image_b64,
            image_url=image_url,
            request_id=request_id.get_request_id(),
            submitted_at=time.time(),  # wall clock: queue-wait metric (celery_app task_prerun)
        )
    except Exception:  # broker unreachable, serialization failure, ...
        logger.exception("failed to submit agent callback task")
        return response.error("failed to submit task", code=3)

    logger.info("agent callback task submitted: task_id=%s callback=%s", task.id, callback_url)
    return response.success({"task_id": task.id})
