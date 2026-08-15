"""Flask application factory: logging setup and blueprint registration only.

Dependency chain: app -> apis -> tasks -> engines. app.py knows nothing about
tasks or algorithms — tasks own their predictors, apis own their tasks.
"""
import logging

from flask import Flask

from apis.predict import predict_bp
from utils import request_id
from utils.logger import setup_logging

logger = logging.getLogger("app")


def create_app() -> Flask:
    setup_logging()
    app = Flask(__name__)
    app.before_request(request_id.before_request)
    app.after_request(request_id.after_request)
    app.register_blueprint(predict_bp)
    logger.info("app created")
    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
