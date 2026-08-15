"""Logging configuration for InferForge.

Console: human-readable text (INFO+), for developers.
File:    one JSON object per line (DEBUG+), daily rotation with 7-day retention —
         machine-collectable by ELK/Loki; every line carries the request_id.
"""
import json
import logging
import os
from logging.handlers import TimedRotatingFileHandler

from flask import g, has_request_context

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
LOG_FILE = os.path.join(LOG_DIR, "app.log")
LOG_RETENTION_DAYS = 7

# Third-party libraries are too noisy at INFO; keep them at WARNING.
_QUIET_LIBRARIES = ("onnxruntime", "urllib3", "requests")

_CONSOLE_FMT = "%(asctime)s | %(levelname)-7s | %(name)s | %(request_id)s | %(message)s"
_TIME_FMT = "%Y-%m-%d %H:%M:%S"


class RequestIdFilter(logging.Filter):
    """Attach the current request_id (or "-" outside a request) to every record."""

    def filter(self, record):
        record.request_id = g.get("request_id", "-") if has_request_context() else "-"
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line, for machine collection."""

    def format(self, record):
        payload = {
            "time": self.formatTime(record, _TIME_FMT),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging() -> None:
    """Configure the root logger. Safe to call multiple times."""
    os.makedirs(LOG_DIR, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(_CONSOLE_FMT, datefmt=_TIME_FMT))
    console.addFilter(RequestIdFilter())

    file_handler = TimedRotatingFileHandler(
        LOG_FILE, when="midnight", backupCount=LOG_RETENTION_DAYS, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(JsonFormatter())
    file_handler.addFilter(RequestIdFilter())

    root.handlers = []  # avoid duplicates when setup is called more than once
    root.addHandler(console)
    root.addHandler(file_handler)

    for lib in _QUIET_LIBRARIES:
        logging.getLogger(lib).setLevel(logging.WARNING)
