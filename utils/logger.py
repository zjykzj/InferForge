"""Logging configuration: console (INFO) + rotating file (DEBUG) under logs/."""
import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
LOG_FILE = os.path.join(LOG_DIR, "app.log")

# Third-party libraries are too noisy at INFO; keep them at WARNING.
_QUIET_LIBRARIES = ("onnxruntime", "urllib3", "requests")


def setup_logging() -> None:
    """Configure the root logger. Safe to call multiple times."""
    os.makedirs(LOG_DIR, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    root.handlers = []  # avoid duplicates when setup is called more than once
    root.addHandler(console)
    root.addHandler(file_handler)

    for lib in _QUIET_LIBRARIES:
        logging.getLogger(lib).setLevel(logging.WARNING)
