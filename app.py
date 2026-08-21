"""Flask application factory: logging setup and blueprint registration only.

Dependency chain: app -> apis -> tasks -> engines. app.py knows nothing about
tasks or algorithms — tasks own their predictors, apis own their tasks.

Health probe endpoints (/health, /health/ready) and the sync predict api are
always registered. Async APIs are registered behind an explicit env switch:
INFERFORGE_ASYNC=1 registers both the callback and query apis (requires
celery + rabbitmq + redis — one deployment shape, callback vs query is a
per-request choice). INFERFORGE_QUERY=1 is accepted as a deprecated alias.
A missing dependency logs a warning and skips the whole async mode.
"""
import logging
import os

from flask import Flask

from apis.health import health_bp
from apis.predict import predict_bp
from utils import request_id
from utils.logger import setup_logging

logger = logging.getLogger("app")

_TRUTHY = ("1", "true", "yes")


def _switch_on(name: str) -> bool:
    return os.environ.get(name, "").lower() in _TRUTHY


def _async_enabled() -> bool:
    # INFERFORGE_QUERY is a deprecated alias: async mode always includes the
    # query api, so either switch enables the full async mode.
    return _switch_on("INFERFORGE_ASYNC") or _switch_on("INFERFORGE_QUERY")


def create_app() -> Flask:
    setup_logging()
    app = Flask(__name__)
    app.before_request(request_id.before_request)
    app.after_request(request_id.after_request)
    app.register_blueprint(health_bp)
    app.register_blueprint(predict_bp)

    if _async_enabled():
        if _switch_on("INFERFORGE_QUERY") and not _switch_on("INFERFORGE_ASYNC"):
            logger.warning(
                "INFERFORGE_QUERY is deprecated — async mode includes the query "
                "api by default, use INFERFORGE_ASYNC=1 instead"
            )
        try:
            from apis.predict_callback import predict_callback_bp
            from apis.predict_query import predict_query_bp

            app.register_blueprint(predict_callback_bp)
            app.register_blueprint(predict_query_bp)
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


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
