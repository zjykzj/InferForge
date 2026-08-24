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
# Explicit buckets below: prometheus defaults cap at 10s, but remote calls
# run up to LLM_TIMEOUT=60s x 3 SDK retries (~180s) and queue wait is bounded
# by celery's task_time_limit=300s.
vlm_remote_call_seconds = Histogram(
    "inferforge_vlm_remote_call_seconds",
    "Remote LLM (OpenAI-compatible) call duration in seconds, incl. SDK retries.",
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 30.0, 60.0, 120.0, 180.0),
)
vlm_remote_errors_total = Counter(
    "inferforge_vlm_remote_errors_total",
    "Remote LLM calls that failed with an OpenAIError after SDK retries.",
)
celery_queue_wait_seconds = Histogram(
    "inferforge_celery_queue_wait_seconds",
    "Time a task waited in the broker queue before the worker picked it up, by task name.",
    ("task",),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
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


def observe_vlm_remote_call(seconds: float) -> None:
    """Record one remote LLM call duration (called by tasks.vlm)."""
    vlm_remote_call_seconds.observe(seconds)


def count_vlm_remote_error() -> None:
    """Count one failed remote LLM call (called by tasks.vlm on OpenAIError)."""
    vlm_remote_errors_total.inc()


def observe_queue_wait(task: str, seconds: float) -> None:
    """Record broker queue wait for one celery task (called by celery_app task_prerun)."""
    celery_queue_wait_seconds.labels(task).observe(seconds)


def record_queue_wait(task_name: str, task_kwargs: dict | None) -> None:
    """Extract submitted_at from task kwargs and observe the broker queue wait.

    submitted_at is a wall-clock timestamp stamped by the api layer at
    submission (crosses the web->worker process boundary via the task
    message). Same-host (or NTP-synced) clock assumption; negative deltas
    from clock skew are clamped to 0. Lives here (not in celery_app) so the
    computation is testable without importing celery_app — importing it in
    tests would split celery's thread-local current_app across TestClient
    threads and break task monkeypatching.
    """
    submitted_at = (task_kwargs or {}).get("submitted_at")
    if submitted_at is not None:
        observe_queue_wait(task_name, max(0.0, time.time() - submitted_at))


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
