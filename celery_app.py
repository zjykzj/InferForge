"""Celery application for async tasks.

Two entry points, two processes:
- web:    imports this module to submit tasks (via delay)
- worker: celery -A celery_app worker
"""
import os
import sys
import time

# Make the project root importable regardless of the worker's working directory.
# Unconditional insert: the celery CLI temporarily adds and then removes cwd from
# sys.path while importing this module, so a dedup guard would lose the entry.
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _PROJECT_ROOT)

# Load .env BEFORE task modules import — tasks read env at import time
# (INFERFORGE_MODEL_PATH, INFERFORGE_LLM_PROMPT). override=False: shell env wins.
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))

from celery import Celery  # noqa: E402
from celery.signals import (  # noqa: E402
    setup_logging,
    task_failure,
    task_postrun,
    task_prerun,
    worker_process_init,
)
from utils import metrics  # noqa: E402

celery_app = Celery("inferforge")

celery_app.conf.update(
    broker_url=os.environ.get("CELERY_BROKER_URL", "amqp://guest:guest@localhost:5672//"),
    task_ignore_result=True,  # callback mode: results are pushed, not stored
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    enable_utc=True,
    timezone="Asia/Shanghai",
    task_time_limit=300,
    task_soft_time_limit=240,
    worker_prefetch_multiplier=1,  # CPU-bound inference: one task at a time per worker
    # RabbitMQ >= 4.3 rejects transient non-exclusive queues by default; the
    # pidbox broadcast reply queue (mingle / inspect / revoke) must be durable.
    control_queue_durable=True,
)

# Explicit task registration instead of lazy autodiscovery: task modules use
# shared_task, which binds to this app without a circular import.
from tasks import detection_callback  # noqa: E402,F401
from tasks import detection_query  # noqa: E402,F401
from tasks import vlm_query  # noqa: E402,F401
from tasks import agent_query  # noqa: E402,F401


@setup_logging.connect
def _configure_logging(**kwargs):
    """Reuse the project logging config in workers (separate file: celery.log)."""
    from utils.logger import setup_logging

    setup_logging(log_file="celery.log")


# Worker-side metrics: counted in the worker process and scraped through the
# web /metrics endpoint via the shared PROMETHEUS_MULTIPROC_DIR.
def _task_elapsed(task) -> float | None:
    started = getattr(task.request, "metrics_started", None)
    return time.perf_counter() - started if started else None


@worker_process_init.connect
def _on_worker_process_init(**kwargs):
    """Model warmup in each prefork child (after fork, before the first task).

    INFERFORGE_PRELOAD gating and best-effort semantics live in tasks.warmup;
    this handler only wires the signal. Not covered by unit tests — importing
    celery_app in tests would split celery's thread-local current_app across
    TestClient threads (CLAUDE.md); tasks.warmup.preload_worker is tested
    directly instead.
    """
    from tasks import warmup

    warmup.preload_worker()


@task_prerun.connect
def _on_task_prerun(task_id, task, **kwargs):
    task.request.metrics_started = time.perf_counter()
    # Queue wait = now - the api layer's submission timestamp (wall clock,
    # crosses the web->worker process boundary via the task message).
    # task_received is NOT used: it fires when the worker FETCHES the task
    # (after the broker queue time), so it cannot measure queue wait.
    # task.request is a celery Context, not a dict — .kwargs.get, not .get.
    metrics.record_queue_wait(task.name, getattr(task.request, "kwargs", None))


@task_postrun.connect
def _on_task_postrun(task_id, task, **kwargs):
    metrics.record_celery_task(task.name, "success", _task_elapsed(task))


@task_failure.connect
def _on_task_failure(task_id, task, **kwargs):
    metrics.record_celery_task(task.name, "failure", _task_elapsed(task))
