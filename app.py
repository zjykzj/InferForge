"""FastAPI application factory: logging setup, middleware and router registration only.

Dependency chain: app -> apis -> tasks -> engines. app.py knows nothing about
tasks or algorithms — tasks own their predictors, apis own their tasks.

Health probe endpoints (/health, /health/ready) and the sync predict api are
always registered. The sync segment and classify apis are registered behind
their own env switches (INFERFORGE_SEG=1 / INFERFORGE_CLS=1, off by default,
no extra services — see tasks/segmentation.py + tasks/classification.py).
Async APIs are registered behind an explicit env switch:
INFERFORGE_ASYNC=1 registers both the callback and query apis (requires
celery + rabbitmq + redis — one deployment shape, callback vs query is a
per-request choice). INFERFORGE_QUERY=1 is accepted as a deprecated alias.
The VLM api (remote LLM call, query-only — no sync or callback variant)
additionally requires INFERFORGE_LLM=1 AND INFERFORGE_ASYNC=1 — LLM without
async logs a warning. The agent api (detection tool + Pydantic AI
orchestration, query-only) requires INFERFORGE_AGENT=1 AND
INFERFORGE_ASYNC=1 — agent without async logs a warning. A missing
dependency logs a warning and skips the whole async mode.

Serving: gunicorn with the uvicorn ASGI worker (gunicorn.conf.py). Endpoints
are plain `def` (sync) — FastAPI runs them in its threadpool, because ONNX
inference is CPU-bound blocking. Never add async/await to the inference path.
"""
import os

# Load .env BEFORE any project import reads configuration: INFERFORGE_MODEL_PATH
# is read at tasks.detection import and INFERFORGE_LLM_PROMPT at tasks.vlm
# import (both happen below via the apis imports). Explicit path — the default
# cwd-relative search breaks when gunicorn runs from another directory.
# override=False: shell-exported vars (start.sh / compose) beat the file.
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import logging  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402

from apis.health import health_router  # noqa: E402
from apis.metrics import metrics_router  # noqa: E402
from apis.predict import predict_router  # noqa: E402
from utils import auth, metrics, rate_limit, request_id, response, switches  # noqa: E402
from utils.logger import setup_logging  # noqa: E402

logger = logging.getLogger("app")

# Request-body ceiling: matches the image download limit (utils/image.py
# MAX_DOWNLOAD_SIZE). Best-effort: only reads the Content-Length header
# (chunked bodies without it bypass — see docs/security.md).
MAX_BODY_SIZE = 20 * 1024 * 1024


def _switch_on(name: str) -> bool:
    return switches.switch_on(name)


def _async_enabled() -> bool:
    # INFERFORGE_QUERY is a deprecated alias: async mode always includes the
    # query api, so either switch enables the full async mode.
    return _switch_on("INFERFORGE_ASYNC") or _switch_on("INFERFORGE_QUERY")


def _llm_enabled() -> bool:
    # VLM apis are async-shaped (they need celery), so this switch only takes
    # effect together with async mode — see create_app().
    return _switch_on("INFERFORGE_LLM")


def _agent_enabled() -> bool:
    # Agent apis are async-shaped (they need celery), so this switch only
    # takes effect together with async mode — see create_app().
    return _switch_on("INFERFORGE_AGENT")


def _seg_enabled() -> bool:
    # Sync segment api; independent of the async stack (see create_app()).
    return _switch_on("INFERFORGE_SEG")


def _cls_enabled() -> bool:
    # Sync classify api; independent of the async stack (see create_app()).
    return _switch_on("INFERFORGE_CLS")


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
    # rejection, 429 rate limit, validation envelope, 503 readiness, 404s —
    # carries X-Request-ID. Metrics innermost: only routed requests are
    # counted, short-circuits above it surface in responses_total{code}
    # instead. Auth off unless INFERFORGE_API_KEY is set (401 + code=7);
    # rate limit off unless INFERFORGE_RATE_LIMIT is set (429 + code=8).
    app.add_middleware(metrics.MetricsMiddleware)
    app.add_middleware(rate_limit.RateLimitMiddleware)
    app.add_middleware(auth.AuthMiddleware)
    app.add_middleware(ContentLengthLimitMiddleware)
    app.add_middleware(request_id.RequestIdMiddleware)
    # Replace FastAPI's default 422 handler: validation failures become
    # 200 + code=1 envelopes (the always-200 contract, docs/status-codes.md).
    app.add_exception_handler(RequestValidationError, response.validation_error_handler)

    app.include_router(health_router)
    app.include_router(metrics_router)
    app.include_router(predict_router)

    if _seg_enabled():
        from apis.predict_segment import predict_segment_router

        app.include_router(predict_segment_router)
        logger.info("segment api enabled")
    if _cls_enabled():
        from apis.predict_classify import predict_classify_router

        app.include_router(predict_classify_router)
        logger.info("classify api enabled")

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
            if _llm_enabled():
                from apis.predict_vlm_query import predict_vlm_query_router

                app.include_router(predict_vlm_query_router)
                logger.info("vlm query api enabled")
            if _agent_enabled():
                from apis.predict_agent_query import predict_agent_query_router

                app.include_router(predict_agent_query_router)
                logger.info("agent query api enabled")
        except ImportError:
            logger.warning(
                "INFERFORGE_ASYNC=1 but celery or redis is not installed — "
                "async apis disabled"
            )
    else:
        if _llm_enabled():
            logger.warning(
                "INFERFORGE_LLM=1 but INFERFORGE_ASYNC is off — vlm api "
                "disabled (it needs the async stack)"
            )
        if _agent_enabled():
            logger.warning(
                "INFERFORGE_AGENT=1 but INFERFORGE_ASYNC is off — agent api "
                "disabled (it needs the async stack)"
            )
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
