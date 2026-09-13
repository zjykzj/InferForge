# @inferforge:base
# Root conftest: makes the project root importable for pytest.
import pytest
from fastapi import FastAPI
# @inferforge:end:base
# @inferforge:envelope
from fastapi.exceptions import RequestValidationError  # noqa: E402
# @inferforge:end:envelope
# @inferforge:metrics
from apis.metrics import metrics_router  # noqa: E402
# @inferforge:end:metrics
# @inferforge:base
# engines/registry ships with the serving-stack shared set — a kernel-only
# assembly (no capabilities) has no registry to isolate.
try:
    from engines import registry
except ImportError:  # pragma: no cover — depends on assembly selection
    registry = None
# @inferforge:end:base
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

# @inferforge:base
_DEFAULT_REGISTRY = """\
defaults:
  # @inferforge:detect
  detect: yolov8n
  # @inferforge:end:detect
  # @inferforge:seg
  segment: yolov8n-seg
  # @inferforge:end:seg
  # @inferforge:cls
  classify: yolov8n-cls
  # @inferforge:end:cls
  # @inferforge:embed
  embed: dino2-small
  # @inferforge:end:embed

models:
  # @inferforge:detect
  yolov8n:
    capability: detect
    path: models/yolov8n.onnx
  # @inferforge:end:detect
  # @inferforge:seg
  yolov8n-seg:
    capability: segment
    path: models/yolov8n-seg.onnx
  # @inferforge:end:seg
  # @inferforge:cls
  yolov8n-cls:
    capability: classify
    path: models/yolov8n-cls.onnx
  # @inferforge:end:cls
  # @inferforge:embed
  dino2-small:
    capability: embed
    path: models/dino2-small.onnx
  # @inferforge:end:embed
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
    if registry is None:
        return
    registry_file = tmp_path / "registry.yaml"
    registry_file.write_text(_DEFAULT_REGISTRY)
    monkeypatch.setenv("INFERFORGE_REGISTRY_PATH", str(registry_file))
    registry.reset_cache()


@pytest.fixture()
def app_factory():
    """Build a minimal app wired like create_app: each mechanism's middleware
    (metrics/rate-limit/auth/request-id) and the validation envelope handler
    are wired only when the mechanism is assembled, in create_app's order
    (LAST added = outermost). AuthMiddleware reads INFERFORGE_API_KEY at
    construction, so tests monkeypatch.setenv it BEFORE building the app.
    """

    def _make(*routers):
        app = FastAPI()
        # @inferforge:metrics
        app.add_middleware(metrics.MetricsMiddleware)
        # @inferforge:end:metrics
        # @inferforge:rate_limit
        app.add_middleware(rate_limit.RateLimitMiddleware)
        # @inferforge:end:rate_limit
        # @inferforge:auth
        app.add_middleware(auth.AuthMiddleware)
        # @inferforge:end:auth
        # @inferforge:request_id
        app.add_middleware(request_id.RequestIdMiddleware)
        # @inferforge:end:request_id
        # @inferforge:envelope
        app.add_exception_handler(RequestValidationError, response.validation_error_handler)
        # @inferforge:end:envelope
        # @inferforge:metrics
        app.include_router(metrics_router)
        # @inferforge:end:metrics
        for router in routers:
            app.include_router(router)
        return app

    return _make
# @inferforge:end:base
