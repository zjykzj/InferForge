"""POST /predict/callback — async detection with server-side callback.

Submit a detection task; when it finishes the server POSTs the result
(success or failure envelope) to the provided callback_url.
"""
import logging

from flask import Blueprint, request

from tasks.detection_callback import detect_callback_task
from utils import response

logger = logging.getLogger("apis.predict_callback")

predict_callback_bp = Blueprint("predict_callback", __name__)


@predict_callback_bp.route("/predict/callback", methods=["POST"])
def predict_callback():
    data = request.get_json(silent=True) or {}
    image_b64 = data.get("image")
    image_url = data.get("url")
    callback_url = data.get("callback_url")

    logger.info("predict callback request: remote=%s has_image=%s has_url=%s",
                request.remote_addr, bool(image_b64), bool(image_url))

    if not callback_url:
        return response.error("provide 'callback_url'", code=1)
    if image_b64 and image_url:
        return response.error("provide either 'image' or 'url', not both", code=1)
    if not image_b64 and not image_url:
        return response.error("provide either 'image' or 'url'", code=1)

    try:
        task = detect_callback_task.delay(
            callback_url, image_b64=image_b64, image_url=image_url
        )
    except Exception:  # broker unreachable, serialization failure, ...
        logger.exception("failed to submit callback task")
        return response.error("failed to submit task", code=3)

    logger.info("callback task submitted: task_id=%s callback=%s", task.id, callback_url)
    return response.success({"task_id": task.id})
