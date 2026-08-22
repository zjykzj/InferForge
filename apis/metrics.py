"""GET /metrics — Prometheus exposition endpoint (raw text, no envelope).

Protocol endpoints like /health serve orchestrators; this one serves
monitoring scrapers. Prometheus expects its own text format, so the
{code, message, data} envelope does not apply here (documented as the
format exception in docs/status-codes.md). Metrics collection is always
on — counters are near-free and need no switch (docs/metrics.md).
"""
from fastapi import APIRouter
from fastapi.responses import Response

from utils import metrics

metrics_router = APIRouter()


@metrics_router.get("/metrics")
def metrics_endpoint() -> Response:
    return Response(content=metrics.generate(), media_type=metrics.CONTENT_TYPE)
