# Root conftest: makes the project root importable for pytest.
import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from apis.metrics import metrics_router
from engines import registry
from utils import auth, metrics, rate_limit, request_id, response

_DEFAULT_REGISTRY = """\
defaults:
  detect: yolov8n
  segment: yolov8n-seg
  classify: yolov8n-cls
  embed: dino2-small

models:
  yolov8n:
    capability: detect
    path: models/yolov8n.onnx
  yolov8n-seg:
    capability: segment
    path: models/yolov8n-seg.onnx
  yolov8n-cls:
    capability: classify
    path: models/yolov8n-cls.onnx
  dino2-small:
    capability: embed
    path: models/dino2-small.onnx
"""


@pytest.fixture(autouse=True)
def registry_isolation(tmp_path, monkeypatch):
    """Point the registry at a per-test file so tests are deterministic even
    on a dev machine with a real models/registry.yaml present.

    The paths inside never need to exist on disk: tests swap the predictors
    out via get_predictor before any load() would happen. Tests that need a
    custom registry overwrite the env var (and the registry reloads via
    reset_cache) — see tests/test_registry.py.
    """
    registry_file = tmp_path / "registry.yaml"
    registry_file.write_text(_DEFAULT_REGISTRY)
    monkeypatch.setenv("INFERFORGE_REGISTRY_PATH", str(registry_file))
    registry.reset_cache()


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
