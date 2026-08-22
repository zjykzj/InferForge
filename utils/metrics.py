"""Prometheus metrics: definitions, ASGI middleware and scrape support.

All metric objects live here; layers import the helpers (utils/ is
cross-cutting, usable by any layer). Design notes:

- /metrics returns raw Prometheus text, NOT the {code, message, data}
  envelope — it is a protocol endpoint for scrapers, like /health is for
  orchestrators (docs/status-codes.md).
- Multiprocess: each gunicorn worker keeps its own counters. When
  PROMETHEUS_MULTIPROC_DIR is set at import time (start.sh / start_celery.sh
  / docker-compose.yml do this before the app imports), prometheus_client
  redirects metrics to per-process files and MultiProcessCollector
  aggregates them at scrape time. Web and worker share the same directory,
  so worker metrics are scraped through the web /metrics endpoint too.
  Without the env (dev `python3 app.py`), the default in-process registry
  is used.
- The route label comes from scope["route"], which routing fills in only
  after this middleware's entry phase — so it is read lazily in the
  response wrapper (mirrors RequestIdMiddleware's structure).
"""
import os
import time

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    multiprocess,
)

# prometheus_client switches to multiprocess mode when this env is present
# at ITS import time (the import above). Metric constructors open mmap files
# in that directory immediately, so it must exist BEFORE the definitions
# below — create it first (works for start.sh preload and the compose
# worker alike).
_multiproc_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
if _multiproc_dir:
    os.makedirs(_multiproc_dir, exist_ok=True)

http_requests_total = Counter(
    "inferforge_http_requests_total",
    "HTTP requests served, by method and route template.",
    ("method", "route"),
)
http_request_duration_seconds = Histogram(
    "inferforge_http_request_duration_seconds",
    "End-to-end request duration in seconds, by method and route template.",
    ("method", "route"),
)
responses_total = Counter(
    "inferforge_responses_total",
    "Envelope responses created, by business code (0..6).",
    ("code",),
)
predict_phase_seconds = Histogram(
    "inferforge_predict_phase_seconds",
    "Inference phase durations in seconds (pre / infer / post).",
    ("phase",),
)
predictor_loaded = Gauge(
    "inferforge_predictor_loaded",
    "Whether the task-layer predictor is loaded in this process (1) or not (0).",
)
celery_tasks_total = Counter(
    "inferforge_celery_tasks_total",
    "Celery task executions, by task name and final state.",
    ("task", "state"),
)
celery_task_duration_seconds = Histogram(
    "inferforge_celery_task_duration_seconds",
    "Celery task run duration in seconds, by task name.",
    ("task",),
)

CONTENT_TYPE = CONTENT_TYPE_LATEST  # re-export: the /metrics endpoint's media_type

_scrape_registry = None


def generate() -> bytes:
    """Render current metrics in the Prometheus text format.

    Lazily picks the registry: MultiProcessCollector when multiprocess mode
    is active, the default in-process registry otherwise.
    """
    global _scrape_registry
    if _scrape_registry is None:
        if _multiproc_dir:
            registry = CollectorRegistry()
            multiprocess.MultiProcessCollector(registry)
        else:
            registry = REGISTRY
        _scrape_registry = registry
    return generate_latest(_scrape_registry)


def record_response(code: int) -> None:
    """Count one envelope response (called by utils.response)."""
    responses_total.labels(str(code)).inc()


def observe_phase(phase: str, seconds: float) -> None:
    """Record one inference phase duration (called by engines)."""
    predict_phase_seconds.labels(phase).observe(seconds)


def mark_predictor_loaded() -> None:
    """Flag the task-layer predictor as loaded in this process."""
    predictor_loaded.set(1)


def record_celery_task(name: str, state: str, seconds=None) -> None:
    """Count one celery task run; optionally record its duration."""
    celery_tasks_total.labels(name, state).inc()
    if seconds is not None:
        celery_task_duration_seconds.labels(name).observe(seconds)


class MetricsMiddleware:
    """Count and time every HTTP request; labels come from the route template.

    Pure ASGI (no BaseHTTPMiddleware task spawning). The route template is
    only available in the response phase: this middleware wraps the router,
    and routing fills scope["route"] after our entry — so it is read lazily
    inside the send wrapper. Requests short-circuited by an outer middleware
    (e.g. the content-length guard) bypass this counter; their envelopes are
    still counted via utils.response.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "-")
        started = time.perf_counter()

        async def send_with_metrics(message):
            if message["type"] == "http.response.start":
                route = scope.get("route")
                path = getattr(route, "path_format", None) or scope.get("path", "-")
                http_requests_total.labels(method, path).inc()
                http_request_duration_seconds.labels(method, path).observe(
                    time.perf_counter() - started
                )
            await send(message)

        await self.app(scope, receive, send_with_metrics)
