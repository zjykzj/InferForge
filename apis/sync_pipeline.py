"""POST /predict/pipeline — validate input, forward to the task layer, format
the response. Registered behind INFERFORGE_PIPELINE=1 (app.py).

The pipeline composes the detect + classify registry DEFAULTS (no `model`
field — the pair is chosen by models/registry.yaml, see docs/api.md). The
endpoint is a plain `def` — FastAPI runs it in its threadpool, because the
composed inference (download + two ONNX passes) is blocking and CPU-bound.
"""
import logging

import requests
from fastapi import APIRouter, Request

from apis.schemas import PipelineRequest
from tasks import pipeline
from utils import errors, response

logger = logging.getLogger("apis.sync_pipeline")

sync_pipeline_router = APIRouter()


@sync_pipeline_router.post("/predict/pipeline")
def predict_pipeline(request: Request, payload: PipelineRequest):
    image_b64 = payload.image
    image_url = payload.url
    remote = request.client.host if request.client else "-"

    logger.info("pipeline request: remote=%s has_image=%s has_url=%s",
                remote, bool(image_b64), bool(image_url))

    try:
        out_image, items = pipeline.run_pipeline(image_b64=image_b64, image_url=image_url)
    except errors.ModelNotFound as exc:  # before ValueError: not a ValueError subclass
        logger.warning("pipeline rejected (model): %s", exc)
        return response.error(str(exc), code=10)
    except pipeline.PipelineConfigError as exc:  # bad INFERFORGE_PIPELINE_TARGETS
        logger.warning("pipeline rejected (config): %s", exc)
        return response.error(str(exc), code=3)
    except ValueError as exc:  # invalid input (bad base64, missing params, ...)
        logger.warning("pipeline rejected: %s", exc)
        return response.error(str(exc), code=1)
    except requests.RequestException as exc:  # image download failure
        logger.warning("pipeline failed (download): %s", exc)
        return response.error("failed to download image: %s" % exc, code=2)
    except Exception:  # unexpected internal error
        logger.exception("pipeline failed (internal)")
        return response.error("internal server error", code=3)

    logger.info("pipeline succeeded: %d item(s)", len(items))
    return response.success({"image": out_image, "items": items})
