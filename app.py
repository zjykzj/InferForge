"""FastAPI application factory: logging setup, middleware and router registration only.

Dependency chain: app -> apis -> tasks -> engines. app.py knows nothing about
tasks or algorithms — tasks own their predictors, apis own their tasks.

Health probe endpoints (/health, /health/ready) and the sync predict api are
always registered. Async APIs are registered behind an explicit env switch:
INFERFORGE_ASYNC=1 registers both the callback and query apis (requires
celery + rabbitmq + redis — one deployment shape, callback vs query is a
per-request choice). INFERFORGE_QUERY=1 is accepted as a deprecated alias.
A missing dependency logs a warning and skips the whole async mode.

Serving: gunicorn with the uvicorn ASGI worker (gunicorn.conf.py). Endpoints
are plain `def` (sync) — FastAPI runs them in its threadpool, because ONNX
inference is CPU-bound blocking. Never add async/await to the inference path.
"""
import logging
import os

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from apis.health import health_router
from apis.metrics import metrics_router
from apis.predict import predict_router
from utils import auth, metrics, request_id, response
from utils.logger import setup_logging

logger = logging.getLogger("app")

_TRUTHY = ("1", "true", "yes")

# Request-body ceiling: matches the image download limit (utils/image.py
# MAX_DOWNLOAD_SIZE). Best-effort: only reads the Content-Length header
# (chunked bodies without it bypass — see docs/security.md).
MAX_BODY_SIZE = 20 * 1024 * 1024


def _switch_on(name: str) -> bool:
    return os.environ.get(name, "").lower() in _TRUTHY


def _async_enabled() -> bool:
    # INFERFORGE_QUERY is a deprecated alias: async mode always includes the
    # query api, so either switch enables the full async mode.
    return _switch_on("INFERFORGE_ASYNC") or _switch_on("INFERFORGE_QUERY")


def _read_version() -> str:
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION")
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return "0.0.0"


class ContentLengthLimitMiddleware:
    """Reject declared-oversized bodies with the always-200 envelope (code=1)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    if int(value) > MAX_BODY_SIZE:
                        resp = response.error(
                            "request body too large (max %d bytes)" % MAX_BODY_SIZE,
                            code=1,
                        )
                        await resp(scope, receive, send)
                        return
                except ValueError:
                    pass
                break
        await self.app(scope, receive, send)


def create_app() -> FastAPI:
    setup_logging()
    app = FastAPI(
        title="InferForge",
        version=_read_version(),
        description="Inference serving template — {code, message, data} envelope, HTTP always 200.",
    )
    # Middleware order: the LAST added runs FIRST (outermost). RequestId
    # outermost so every response — content-length envelope, 401 auth
    # rejection, validation envelope, 503 readiness, 404s — carries
    # X-Request-ID. Metrics innermost: only routed requests are counted,
    # short-circuits above it surface in responses_total{code} instead.
    # Auth off unless INFERFORGE_API_KEY is set (401 + code=7, utils/auth.py).
    app.add_middleware(metrics.MetricsMiddleware)
    app.add_middleware(auth.AuthMiddleware)
    app.add_middleware(ContentLengthLimitMiddleware)
    app.add_middleware(request_id.RequestIdMiddleware)
    # Replace FastAPI's default 422 handler: validation failures become
    # 200 + code=1 envelopes (the always-200 contract, docs/status-codes.md).
    app.add_exception_handler(RequestValidationError, response.validation_error_handler)

    app.include_router(health_router)
    app.include_router(metrics_router)
    app.include_router(predict_router)

    if _async_enabled():
        if _switch_on("INFERFORGE_QUERY") and not _switch_on("INFERFORGE_ASYNC"):
            logger.warning(
                "INFERFORGE_QUERY is deprecated — async mode includes the query "
                "api by default, use INFERFORGE_ASYNC=1 instead"
            )
        try:
            from apis.predict_callback import predict_callback_router
            from apis.predict_query import predict_query_router

            app.include_router(predict_callback_router)
            app.include_router(predict_query_router)
            logger.info("async apis enabled (callback + query)")
        except ImportError:
            logger.warning(
                "INFERFORGE_ASYNC=1 but celery or redis is not installed — "
                "async apis disabled"
            )
    else:
        logger.info("async api disabled (set INFERFORGE_ASYNC=1 to enable)")

    logger.info("app created")
    return app


app = create_app()  # keeps `gunicorn -c gunicorn.conf.py app:app` and preload_app working


if __name__ == "__main__":
    import uvicorn

    # Dev server. log_config=None: keep the project's single logging pipeline
    # (utils.logger) — uvicorn loggers propagate to the root handlers instead
    # of dictConfig-resetting the root logger.
    uvicorn.run(app, host="0.0.0.0", port=8000, log_config=None)
