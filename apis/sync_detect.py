"""POST /predict — validate input, forward to the task layer, format the response.

An API may combine one or more tasks; it never touches algorithms directly.
The endpoint is a plain `def` — FastAPI runs it in its threadpool, because
the detection pipeline (download + ONNX inference) is blocking and CPU-bound.
"""
import logging

import requests
from fastapi import APIRouter, Request

from apis.schemas import PredictRequest
from tasks import detection
from utils import errors, response

logger = logging.getLogger("apis.sync_detect")

sync_detect_router = APIRouter()


@sync_detect_router.post("/predict")
def predict(request: Request, payload: PredictRequest):
    image_b64 = payload.image
    image_url = payload.url
    remote = request.client.host if request.client else "-"

    logger.info("predict request: remote=%s has_image=%s has_url=%s",
                remote, bool(image_b64), bool(image_url))

    try:
        out_image, detections = detection.run_detection(
            image_b64=image_b64, image_url=image_url, model=payload.model
        )
    except errors.ModelNotFound as exc:  # before ValueError: not a ValueError subclass
        logger.warning("predict rejected (model): %s", exc)
        return response.error(str(exc), code=10)
    except ValueError as exc:  # invalid input (bad base64, missing params, ...)
        logger.warning("predict rejected: %s", exc)
        return response.error(str(exc), code=1)
    except requests.RequestException as exc:  # image download failure
        logger.warning("predict failed (download): %s", exc)
        return response.error("failed to download image: %s" % exc, code=2)
    except Exception:  # unexpected internal error
        logger.exception("predict failed (internal)")
        return response.error("internal server error", code=3)

    logger.info("predict succeeded: %d detections", len(detections))
    return response.success({"image": out_image, "detections": detections})
