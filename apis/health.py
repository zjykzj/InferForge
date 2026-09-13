# @inferforge:base
"""GET /health (liveness) and GET /health/ready (readiness).

Infrastructure probes for orchestrators and load balancers (K8s, Docker,
ALB, ...). These are the one place where HTTP status codes carry meaning:
a readiness probe that always returned 200 would be useless, so /health/ready
returns 503 until the predictor is loaded (the envelope mechanism wraps the
failure in code 6 when assembled).

The api layer never touches the predictor itself — it asks the task layer
whether the predictor has been loaded.
"""
# @inferforge:end:base
# @inferforge:base
from fastapi import APIRouter
from fastapi.responses import JSONResponse
# @inferforge:end:base
# @inferforge:detect
from tasks import detection  # noqa: E402
# @inferforge:end:detect
# @inferforge:seg
from tasks import segmentation  # noqa: E402
# @inferforge:end:seg
# @inferforge:cls
from tasks import classification  # noqa: E402
# @inferforge:end:cls
# @inferforge:embed
from tasks import embedding  # noqa: E402
# @inferforge:end:embed
# @inferforge:envelope
from utils import response  # noqa: E402
# @inferforge:end:envelope

# @inferforge:base
health_router = APIRouter()
# @inferforge:end:base


# @inferforge:base
@health_router.get("/health")
def liveness():
    """The process is alive and serving — never does real work."""
    # @inferforge:envelope
    return response.success({"status": "ok"})
    # @inferforge:end:envelope
    return {"status": "ok"}
# @inferforge:end:base


# @inferforge:base
@health_router.get("/health/ready")
def readiness():
    """Ready to accept traffic: every enabled capability's default model has
    been loaded in this process.

    Only the DEFAULT model of each capability is probed: with a multi-model
    registry, requiring every registered model to be loaded would keep the
    service perpetually not-ready. A capability whose registry holds no
    model at all counts as not ready.
    """
    ready = True  # kernel-only assembly: no capability to probe
    # @inferforge:end:base
    # @inferforge:detect
    ready = detection.default_model_loaded()
    # @inferforge:end:detect
    # @inferforge:seg
    from utils import switches

    if switches.switch_on("INFERFORGE_SEG"):
        ready = ready and segmentation.default_model_loaded()
    # @inferforge:end:seg
    # @inferforge:cls
    from utils import switches

    if switches.switch_on("INFERFORGE_CLS") or switches.switch_on("INFERFORGE_PIPELINE"):
        ready = ready and classification.default_model_loaded()
    # @inferforge:end:cls
    # @inferforge:embed
    from utils import switches

    if switches.switch_on("INFERFORGE_DEDUP"):
        # Dedup is the only embed capability this process serves: search is
        # worker-only (the gallery db is single-process exclusive), so
        # probing embed on INFERFORGE_SEARCH alone would keep the web
        # perpetually 503 — it never loads the embed model.
        ready = ready and embedding.default_model_loaded()
    # @inferforge:end:embed
    # @inferforge:base
    # @inferforge:envelope
    if ready:
        return response.success({"status": "ready"})
    return response.error("model not loaded", code=6, http_status=503)
    # @inferforge:end:envelope
    if ready:
        return {"status": "ready"}
    return JSONResponse({"status": "not ready"}, status_code=503)
# @inferforge:end:base
