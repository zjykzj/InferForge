"""POST /predict/segment — validate input, forward to the task layer, format
the response. Registered behind INFERFORGE_SEG=1 (app.py).

An API may combine one or more tasks; it never touches algorithms directly.
The endpoint is a plain `def` — FastAPI runs it in its threadpool, because
the segmentation pipeline (download + ONNX inference) is blocking and
CPU-bound.
"""
import logging

import requests
from fastapi import APIRouter, Request

from apis.schemas import PredictRequest
from tasks import segmentation
from utils import response

logger = logging.getLogger("apis.predict_segment")

predict_segment_router = APIRouter()


@predict_segment_router.post("/predict/segment")
def predict_segment(request: Request, payload: PredictRequest):
    image_b64 = payload.image
    image_url = payload.url
    remote = request.client.host if request.client else "-"

    logger.info("segment request: remote=%s has_image=%s has_url=%s",
                remote, bool(image_b64), bool(image_url))

    try:
        out_image, segments = segmentation.run_segmentation(
            image_b64=image_b64, image_url=image_url
        )
    except ValueError as exc:  # invalid input (bad base64, missing params, ...)
        logger.warning("segment rejected: %s", exc)
        return response.error(str(exc), code=1)
    except requests.RequestException as exc:  # image download failure
        logger.warning("segment failed (download): %s", exc)
        return response.error("failed to download image: %s" % exc, code=2)
    except Exception:  # unexpected internal error
        logger.exception("segment failed (internal)")
        return response.error("internal server error", code=3)

    logger.info("segment succeeded: %d segments", len(segments))
    return response.success({"image": out_image, "segments": segments})
