# @inferforge:base
"""FastAPI application factory: router registration and middleware wiring only.

Dependency chain: app -> apis -> tasks -> engines. app.py knows nothing about
algorithms — tasks own their predictors, apis own their tasks. Which
middleware and routers exist depends on the assembly selection (marker
blocks); the bare kernel is a plain FastAPI app with the health probes.
"""
# @inferforge:end:base
# @inferforge:base
import os
# @inferforge:end:base
# @inferforge:dotenv
# Load .env BEFORE any project import reads configuration (INFERFORGE_MODEL_PATH
# at tasks.detection import, INFERFORGE_LLM_PROMPT at tasks.vlm import — both
# happen below via the apis imports). Explicit path — the default cwd-relative
# search breaks when gunicorn runs from another directory. override=False:
# shell-exported vars (start.sh / compose) beat the file.
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# @inferforge:end:dotenv
# @inferforge:base
import logging  # noqa: E402
from fastapi import FastAPI  # noqa: E402
# @inferforge:end:base
# @inferforge:envelope
from fastapi.exceptions import RequestValidationError  # noqa: E402
# @inferforge:end:envelope
# @inferforge:base
from apis.health import health_router  # noqa: E402
# @inferforge:end:base
# @inferforge:metrics
from apis.metrics import metrics_router  # noqa: E402
# @inferforge:end:metrics
# @inferforge:detect
from apis.sync_detect import sync_detect_router  # noqa: E402
# @inferforge:end:detect
# @inferforge:envelope
from utils import response  # noqa: E402
# @inferforge:end:envelope
# @inferforge:metrics
from utils import metrics  # noqa: E402
# @inferforge:end:metrics
# @inferforge:rate_limit
from utils import rate_limit  # noqa: E402
# @inferforge:end:rate_limit
# @inferforge:auth
from utils import auth  # noqa: E402
# @inferforge:end:auth
# @inferforge:request_id
from utils import request_id  # noqa: E402
# @inferforge:end:request_id
# @inferforge:logging
from utils.logger import setup_logging  # noqa: E402
# @inferforge:end:logging

# @inferforge:base
logger = logging.getLogger("app")
# @inferforge:end:base

# @inferforge:envelope
# Request-body ceiling: matches the image download limit (utils/image.py
# MAX_DOWNLOAD_SIZE). Best-effort: only reads the Content-Length header
# (chunked bodies without it bypass).
MAX_BODY_SIZE = 20 * 1024 * 1024


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
# @inferforge:end:envelope

# @inferforge:base
def _read_version() -> str:
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION")
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return "0.0.0"
# @inferforge:end:base


# @inferforge:base
def create_app() -> FastAPI:
# @inferforge:end:base
    # @inferforge:logging
    setup_logging()
    # @inferforge:end:logging
    # @inferforge:base
    app = FastAPI(
        title="InferForge",
        version=_read_version(),
        # @inferforge:envelope
        description="Inference serving template — {code, message, data} envelope, HTTP always 200.",
        # @inferforge:end:envelope
    )
    # Middleware order: the LAST added runs FIRST (outermost).
    # @inferforge:end:base
    # @inferforge:metrics
    app.add_middleware(metrics.MetricsMiddleware)
    # @inferforge:end:metrics
    # @inferforge:rate_limit
    app.add_middleware(rate_limit.RateLimitMiddleware)
    # @inferforge:end:rate_limit
    # @inferforge:auth
    app.add_middleware(auth.AuthMiddleware)
    # @inferforge:end:auth
    # @inferforge:envelope
    app.add_middleware(ContentLengthLimitMiddleware)
    # Replace FastAPI's default 422 handler: validation failures become
    # 200 + code=1 envelopes (the always-200 contract).
    app.add_exception_handler(RequestValidationError, response.validation_error_handler)
    # @inferforge:end:envelope
    # @inferforge:request_id
    app.add_middleware(request_id.RequestIdMiddleware)
    # @inferforge:end:request_id

    # @inferforge:base
    app.include_router(health_router)
    # @inferforge:end:base
    # @inferforge:metrics
    app.include_router(metrics_router)
    # @inferforge:end:metrics
    # @inferforge:detect
    app.include_router(sync_detect_router)
    # @inferforge:end:detect

    # @inferforge:seg
    from utils import switches

    if switches.switch_on("INFERFORGE_SEG"):
        from apis.sync_segment import sync_segment_router

        app.include_router(sync_segment_router)
        logger.info("segment api enabled")
    # @inferforge:end:seg
    # @inferforge:cls
    from utils import switches

    if switches.switch_on("INFERFORGE_CLS"):
        from apis.sync_classify import sync_classify_router

        app.include_router(sync_classify_router)
        logger.info("classify api enabled")
    # @inferforge:end:cls
    # @inferforge:pipeline
    from utils import switches

    if switches.switch_on("INFERFORGE_PIPELINE"):
        from apis.sync_pipeline import sync_pipeline_router

        app.include_router(sync_pipeline_router)
        logger.info("pipeline api enabled")
    # @inferforge:end:pipeline
    # @inferforge:dedup
    from utils import switches

    if switches.switch_on("INFERFORGE_DEDUP"):
        from apis.sync_dedup import sync_dedup_router

        app.include_router(sync_dedup_router)
        logger.info("dedup api enabled")
    # @inferforge:end:dedup

    # @inferforge:async
    from utils import switches

    if switches.switch_on("INFERFORGE_ASYNC") or switches.switch_on("INFERFORGE_QUERY"):
        if switches.switch_on("INFERFORGE_QUERY") and not switches.switch_on("INFERFORGE_ASYNC"):
            logger.warning(
                "INFERFORGE_QUERY is deprecated — async mode includes the query "
                "api by default, use INFERFORGE_ASYNC=1 instead"
            )
        try:
            from apis.async_detect_callback import async_detect_callback_router
            from apis.async_detect_query import async_detect_query_router

            app.include_router(async_detect_callback_router)
            app.include_router(async_detect_query_router)
            logger.info("async apis enabled (callback + query)")
            # @inferforge:vlm
            if switches.switch_on("INFERFORGE_LLM"):
                from apis.async_vlm_query import async_vlm_query_router

                app.include_router(async_vlm_query_router)
                logger.info("vlm query api enabled")
            # @inferforge:end:vlm
            # @inferforge:agent
            if switches.switch_on("INFERFORGE_AGENT"):
                from apis.async_agent_query import async_agent_query_router

                app.include_router(async_agent_query_router)
                logger.info("agent query api enabled")
            # @inferforge:end:agent
            # @inferforge:search
            if switches.switch_on("INFERFORGE_SEARCH"):
                from apis.async_search_query import async_search_query_router
                from apis.async_search_check import async_search_check_router

                app.include_router(async_search_query_router)
                app.include_router(async_search_check_router)
                logger.info("search apis enabled (query + check)")
            # @inferforge:end:search
        except ImportError:
            logger.warning(
                "INFERFORGE_ASYNC=1 but celery or redis is not installed — "
                "async apis disabled"
            )
    else:
        # @inferforge:vlm
        if switches.switch_on("INFERFORGE_LLM"):
            logger.warning(
                "INFERFORGE_LLM=1 but INFERFORGE_ASYNC is off — vlm api "
                "disabled (it needs the async stack)"
            )
        # @inferforge:end:vlm
        # @inferforge:agent
        if switches.switch_on("INFERFORGE_AGENT"):
            logger.warning(
                "INFERFORGE_AGENT=1 but INFERFORGE_ASYNC is off — agent api "
                "disabled (it needs the async stack)"
            )
        # @inferforge:end:agent
        # @inferforge:search
        if switches.switch_on("INFERFORGE_SEARCH"):
            logger.warning(
                "INFERFORGE_SEARCH=1 but INFERFORGE_ASYNC is off — search "
                "apis disabled (they need the worker: the gallery db is "
                "single-process exclusive)"
            )
        # @inferforge:end:search
        logger.info("async api disabled (set INFERFORGE_ASYNC=1 to enable)")
    # @inferforge:end:async

    # @inferforge:detect
    from utils import switches

    if switches.switch_on("INFERFORGE_PRELOAD"):
        # Startup event, not module import: gunicorn preload_app=True builds
        # this app in the master, but uvicorn runs the lifespan in EACH
        # worker process — so the models load per worker, after fork.
        from tasks import warmup

        app.router.on_startup.append(warmup.preload_web)
        logger.info("model preload enabled (INFERFORGE_PRELOAD=1)")
    # @inferforge:end:detect

    # @inferforge:metrics
    # Multiprocess hygiene: each process deletes its own metrics file on
    # graceful shutdown (no-op without PROMETHEUS_MULTIPROC_DIR).
    app.router.on_shutdown.append(metrics.mark_process_dead)
    # @inferforge:end:metrics

    # @inferforge:base
    logger.info("app created")
    return app
    # @inferforge:end:base


# @inferforge:base
app = create_app()  # import-time app for the uvicorn/gunicorn entrypoints


if __name__ == "__main__":
    import uvicorn

    # Dev server. log_config=None: keep uvicorn from dictConfig-resetting
    # the root logger (the logging mechanism configures it when selected).
    uvicorn.run(app, host="0.0.0.0", port=8000, log_config=None)
# @inferforge:end:base
