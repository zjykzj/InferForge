"""Flask application factory: logging setup and blueprint registration only.

Dependency chain: app -> apis -> tasks -> engines. app.py knows nothing about
tasks or algorithms — tasks own their predictors, apis own their tasks.

Health probe endpoints (/health, /health/ready) and the sync predict api are
always registered. Async APIs are registered behind explicit env switches:
INFERFORGE_ASYNC=1 registers the callback api (requires celery);
INFERFORGE_QUERY=1 additionally registers the query api (requires celery +
redis). A missing dependency logs a warning and skips only the affected api.
"""
import logging
import os

from flask import Flask

from apis.health import health_bp
from apis.predict import predict_bp
from utils import request_id
from utils.logger import setup_logging

logger = logging.getLogger("app")


def _async_enabled() -> bool:
    return os.environ.get("INFERFORGE_ASYNC", "").lower() in ("1", "true", "yes")


def _query_enabled() -> bool:
    return os.environ.get("INFERFORGE_QUERY", "").lower() in ("1", "true", "yes")


def create_app() -> Flask:
    setup_logging()
    app = Flask(__name__)
    app.before_request(request_id.before_request)
    app.after_request(request_id.after_request)
    app.register_blueprint(health_bp)
    app.register_blueprint(predict_bp)

    if _async_enabled():
        try:
            from apis.predict_callback import predict_callback_bp

            app.register_blueprint(predict_callback_bp)
            logger.info("async callback api enabled")
        except ImportError:
            logger.warning(
                "INFERFORGE_ASYNC=1 but celery is not installed — async api disabled"
            )
        if _query_enabled():
            try:
                from apis.predict_query import predict_query_bp

                app.register_blueprint(predict_query_bp)
                logger.info("async query api enabled")
            except ImportError:
                logger.warning(
                    "INFERFORGE_QUERY=1 but celery or redis is not installed — "
                    "async query api disabled"
                )
        else:
            logger.info("async query api disabled (set INFERFORGE_QUERY=1 to enable)")
    else:
        logger.info("async api disabled (set INFERFORGE_ASYNC=1 to enable)")

    logger.info("app created")
    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
