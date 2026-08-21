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

from tasks import detection
from utils import response

logger = logging.getLogger("apis.health")

health_router = APIRouter()


@health_router.get("/health")
def liveness():
    """The process is alive and serving — never does real work."""
    return response.success({"status": "ok"})


@health_router.get("/health/ready")
def readiness():
    """Ready to accept traffic: the predictor has been loaded in this process.

    With lazy loading the predictor stays unloaded until the first prediction
    warms this worker up, so a fresh deployment reports not-ready (503) until
    then — the load balancer routes around it in the meantime.
    """
    if detection.predictor_loaded():
        return response.success({"status": "ready"})
    return response.error("model not loaded", code=6, http_status=503)
