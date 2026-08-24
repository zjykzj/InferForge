"""POST /predict/vlm/callback — async VLM with server-side callback.

Submit a VLM task (image + fixed server-side prompt + remote LLM call); when
it finishes the server POSTs the result (success or failure envelope) to the
provided callback_url. Registered only when INFERFORGE_ASYNC=1 and
INFERFORGE_LLM=1 (see app.py).
"""
import logging

from fastapi import APIRouter, Request

from apis.schemas import CallbackRequest
from tasks.vlm_callback import vlm_callback_task
from utils import request_id, response

logger = logging.getLogger("apis.predict_vlm_callback")

predict_vlm_callback_router = APIRouter()


@predict_vlm_callback_router.post("/predict/vlm/callback")
def predict_vlm_callback(request: Request, payload: CallbackRequest):
    image_b64 = payload.image
    image_url = payload.url
    callback_url = payload.callback_url

    logger.info("vlm callback request: remote=%s has_image=%s has_url=%s",
                request.client.host if request.client else "-",
                bool(image_b64), bool(image_url))

    try:
        task = vlm_callback_task.delay(
            callback_url,
            image_b64=image_b64,
            image_url=image_url,
            request_id=request_id.get_request_id(),
        )
    except Exception:  # broker unreachable, serialization failure, ...
        logger.exception("failed to submit vlm callback task")
        return response.error("failed to submit task", code=3)

    logger.info("vlm callback task submitted: task_id=%s callback=%s", task.id, callback_url)
    return response.success({"task_id": task.id})
