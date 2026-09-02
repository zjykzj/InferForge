"""POST /predict/dedup — validate input, forward to the task layer, format
the response. Registered behind INFERFORGE_DEDUP=1 (app.py).

Sync on purpose: batch near-duplicate detection is stateless, pure numpy
(N embeddings + pairwise cosine + union-find) and fast enough to answer
inline — no gallery, no index, no worker. The endpoint is a plain `def`
(FastAPI threadpool), same rule as the other inference endpoints.
"""
import logging

import requests
from fastapi import APIRouter, Request

from apis.schemas import DedupRequest
from tasks import dedup
from utils import errors, response

logger = logging.getLogger("apis.sync_dedup")

sync_dedup_router = APIRouter()


@sync_dedup_router.post("/predict/dedup")
def predict_dedup(request: Request, payload: DedupRequest):
    remote = request.client.host if request.client else "-"
    logger.info("dedup request: remote=%s images=%d", remote, len(payload.images))

    try:
        result = dedup.run_dedup([src.model_dump() for src in payload.images])
    except errors.ModelNotFound as exc:  # before ValueError: not a ValueError subclass
        logger.warning("dedup rejected (model): %s", exc)
        return response.error(str(exc), code=10)
    except ValueError as exc:  # invalid input (bad base64, batch size, ...)
        logger.warning("dedup rejected: %s", exc)
        return response.error(str(exc), code=1)
    except requests.RequestException as exc:  # image download failure
        logger.warning("dedup failed (download): %s", exc)
        return response.error("failed to download image: %s" % exc, code=2)
    except Exception:  # unexpected internal error
        logger.exception("dedup failed (internal)")
        return response.error("internal server error", code=3)

    logger.info("dedup succeeded: %d image(s), %d group(s)",
                result["total"], len(result["groups"]))
    return response.success(result)
