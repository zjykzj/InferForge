# Root conftest: makes the project root importable for pytest.
import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from apis.metrics import metrics_router
from utils import auth, metrics, rate_limit, request_id, response


@pytest.fixture()
def app_factory():
    """Build a minimal app wired like create_app (request-id + auth +
    metrics middleware, validation envelope, /metrics router) without the
    app.py content-length guard.

    AuthMiddleware reads INFERFORGE_API_KEY at construction, so tests
    monkeypatch.setenv it BEFORE building the app. Registering the
    validation handler here mirrors app.py so test apps never leak
    FastAPI's default HTTP 422.
    """

    def _make(*routers):
        app = FastAPI()
        # Same order as create_app: LAST added = outermost.
        app.add_middleware(metrics.MetricsMiddleware)
        app.add_middleware(rate_limit.RateLimitMiddleware)
        app.add_middleware(auth.AuthMiddleware)
        app.add_middleware(request_id.RequestIdMiddleware)
        app.add_exception_handler(RequestValidationError, response.validation_error_handler)
        app.include_router(metrics_router)
        for router in routers:
            app.include_router(router)
        return app

    return _make
