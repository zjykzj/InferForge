"""Logging configuration for InferForge.

Console: human-readable text (INFO+), for developers.
File:    one JSON object per line (DEBUG+), one file per process group:
         web -> app.log, worker -> celery.log.

Rotation is delegated to the system logrotate (copytruncate — same inode,
no multi-process rotation races) — see deploy/logrotate.conf. Every line
carries request_id (ContextVar or Celery task kwargs) and task_id (Celery).
"""
import json
import logging
import os

from utils import request_id

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")

# Third-party libraries are too noisy at INFO; keep them at WARNING.
_QUIET_LIBRARIES = ("onnxruntime", "urllib3", "requests", "amqp", "kombu")

_CONSOLE_FMT = ("%(asctime)s | %(levelname)-7s | %(name)s | "
                "%(request_id)s | %(task_id)s | %(message)s")
_TIME_FMT = "%Y-%m-%d %H:%M:%S"


def _celery_task():
    """Return the current celery task, or None (no celery / no task context)."""
    try:
        from celery._state import get_current_task
    except ImportError:
        return None
    try:
        return get_current_task()
    except Exception:
        return None


def _current_request_id() -> str:
    # HTTP context: set by utils.request_id.RequestIdMiddleware (ContextVar).
    # Workers have no HTTP context, so they fall back to the request_id
    # carried in the celery task kwargs.
    rid = request_id.get_request_id()
    if rid != "-":
        return rid
    task = _celery_task()
    if task is not None and task.request is not None:
        kwargs = getattr(task.request, "kwargs", None) or {}
        return str(kwargs.get("request_id", "-"))
    return "-"


def _current_task_id() -> str:
    task = _celery_task()
    if task is not None and task.request is not None:
        return str(getattr(task.request, "id", "-"))
    return "-"


class ContextFilter(logging.Filter):
    """Attach request_id / task_id to every record (HTTP or Celery context)."""

    def filter(self, record):
        record.request_id = _current_request_id()
        record.task_id = _current_task_id()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line, for machine collection."""

    def format(self, record):
        payload = {
            "time": self.formatTime(record, _TIME_FMT),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "task_id": getattr(record, "task_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(log_file: str = "app.log") -> None:
    """Configure the root logger. Safe to call multiple times.

    log_file: which file to write — web uses app.log, celery workers celery.log.
    """
    os.makedirs(LOG_DIR, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(_CONSOLE_FMT, datefmt=_TIME_FMT))
    console.addFilter(ContextFilter())

    # Plain FileHandler: rotation belongs to system logrotate (copytruncate),
    # which is safe for any number of concurrent writer processes.
    file_handler = logging.FileHandler(os.path.join(LOG_DIR, log_file), encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(JsonFormatter())
    file_handler.addFilter(ContextFilter())

    root.handlers = []  # avoid duplicates when setup is called more than once
    root.addHandler(console)
    root.addHandler(file_handler)

    for lib in _QUIET_LIBRARIES:
        logging.getLogger(lib).setLevel(logging.WARNING)
    # Celery lifecycle logs (task received/succeeded) are useful at INFO;
    # its DEBUG chatter (heartbeats, pool internals) is pure noise.
    logging.getLogger("celery").setLevel(logging.INFO)
