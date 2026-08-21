# Root conftest: makes the project root importable for pytest.
import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from utils import request_id, response


@pytest.fixture()
def app_factory():
    """Build a minimal app wired like create_app (request-id middleware +
    validation envelope) without the app.py content-length guard.

    Registering the validation handler here mirrors app.py so test apps
    never leak FastAPI's default HTTP 422.
    """

    def _make(*routers):
        app = FastAPI()
        app.add_middleware(request_id.RequestIdMiddleware)
        app.add_exception_handler(RequestValidationError, response.validation_error_handler)
        for router in routers:
            app.include_router(router)
        return app

    return _make
