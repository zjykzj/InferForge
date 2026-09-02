"""GET /health (liveness) and GET /health/ready (readiness).

Infrastructure probes for orchestrators and load balancers (K8s, Docker,
ALB, ...). These are the one place where HTTP status codes carry meaning:
a readiness probe that always returned 200 would be useless, so /health/ready
returns 503 until the predictor is loaded. Business APIs keep the always-200
convention (see docs/status-codes.md).

The api layer never touches the predictor itself — it asks the task layer
whether the predictor has been loaded.
"""
import logging

from fastapi import APIRouter

from tasks import classification, detection, embedding, segmentation
from utils import response, switches

logger = logging.getLogger("apis.health")

health_router = APIRouter()


@health_router.get("/health")
def liveness():
    """The process is alive and serving — never does real work."""
    return response.success({"status": "ok"})


@health_router.get("/health/ready")
def readiness():
    """Ready to accept traffic: every enabled capability's default model has
    been loaded in this process.

    Detection is always enabled; segment/classify are probed only when their
    env switch is on (read at request time, matching app.py's router
    registration). Classify is probed when EITHER the classify or the
    pipeline switch is on — the pipeline composes the classify default, so
    it needs that model loaded even without INFERFORGE_CLS. With lazy
    loading the predictors stay unloaded until the first prediction warms
    this worker up, so a fresh deployment reports not-ready (503) until
    then — the load balancer routes around it in the meantime.

    Only the DEFAULT model of each capability is probed: with a multi-model
    registry, requiring every registered model to be loaded would keep the
    service perpetually not-ready (rare models warm on their first use).
    A capability whose registry holds no model at all counts as not ready.
    """
    ready = detection.default_model_loaded()
    if switches.switch_on("INFERFORGE_SEG"):
        ready = ready and segmentation.default_model_loaded()
    if switches.switch_on("INFERFORGE_CLS") or switches.switch_on("INFERFORGE_PIPELINE"):
        ready = ready and classification.default_model_loaded()
    if switches.switch_on("INFERFORGE_DEDUP"):
        # Dedup is the only embed capability this process serves: search is
        # worker-only (the gallery db is single-process exclusive), so
        # probing embed on INFERFORGE_SEARCH alone would keep the web
        # perpetually 503 — it never loads the embed model.
        ready = ready and embedding.default_model_loaded()
    if ready:
        return response.success({"status": "ready"})
    return response.error("model not loaded", code=6, http_status=503)
