"""POST /predict/classify — validate input, forward to the task layer, format
the response. Registered behind INFERFORGE_CLS=1 (app.py).

An API may combine one or more tasks; it never touches algorithms directly.
The endpoint is a plain `def` — FastAPI runs it in its threadpool, because
the classification pipeline (download + ONNX inference) is blocking and
CPU-bound.
"""
import logging

import requests
from fastapi import APIRouter, Request

from apis.schemas import PredictRequest
from tasks import classification
from utils import errors, response

logger = logging.getLogger("apis.predict_classify")

predict_classify_router = APIRouter()


@predict_classify_router.post("/predict/classify")
def predict_classify(request: Request, payload: PredictRequest):
    image_b64 = payload.image
    image_url = payload.url
    remote = request.client.host if request.client else "-"

    logger.info("classify request: remote=%s has_image=%s has_url=%s",
                remote, bool(image_b64), bool(image_url))

    try:
        classifications = classification.run_classification(
            image_b64=image_b64, image_url=image_url, model=payload.model
        )
    except errors.ModelNotFound as exc:  # before ValueError: not a ValueError subclass
        logger.warning("classify rejected (model): %s", exc)
        return response.error(str(exc), code=10)
    except ValueError as exc:  # invalid input (bad base64, missing params, ...)
        logger.warning("classify rejected: %s", exc)
        return response.error(str(exc), code=1)
    except requests.RequestException as exc:  # image download failure
        logger.warning("classify failed (download): %s", exc)
        return response.error("failed to download image: %s" % exc, code=2)
    except Exception:  # unexpected internal error
        logger.exception("classify failed (internal)")
        return response.error("internal server error", code=3)

    logger.info("classify succeeded: top-k=%d", len(classifications))
    return response.success({"classifications": classifications})
