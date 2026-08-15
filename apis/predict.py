"""POST /predict — validate input, forward to the task layer, format the response.

An API may combine one or more tasks; it never touches algorithms directly.
"""
import logging

import requests
from flask import Blueprint, request

from tasks import detection
from utils import response

logger = logging.getLogger("apis.predict")

predict_bp = Blueprint("predict", __name__)


@predict_bp.route("/predict", methods=["POST"])
def predict():
    data = request.get_json(silent=True) or {}
    image_b64 = data.get("image")
    image_url = data.get("url")

    logger.info("predict request: remote=%s has_image=%s has_url=%s",
                request.remote_addr, bool(image_b64), bool(image_url))

    try:
        out_image, detections = detection.run_detection(
            image_b64=image_b64, image_url=image_url
        )
    except ValueError as exc:  # invalid input (bad base64, missing params, ...)
        logger.warning("predict rejected: %s", exc)
        return response.error(str(exc), code=1, http_status=400)
    except requests.RequestException as exc:  # image download failure
        logger.warning("predict failed (download): %s", exc)
        return response.error("failed to download image: %s" % exc, code=2, http_status=502)
    except Exception:  # unexpected internal error
        logger.exception("predict failed (internal)")
        return response.error("internal server error", code=3, http_status=500)

    logger.info("predict succeeded: %d detections", len(detections))
    return response.success({"image": out_image, "detections": detections})
