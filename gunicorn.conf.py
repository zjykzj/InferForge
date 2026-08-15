"""Gunicorn configuration for InferForge.

preload_app=True: the app module (imports, logging config, blueprints) is loaded
once in the master before forking, so workers start fast and share Python imports.
Model weights are loaded lazily by each task on its first request and kept
resident afterwards — this avoids holding an onnxruntime session across fork().
"""
import os

bind = "0.0.0.0:8000"
workers = int(os.environ.get("INFERFORGE_WORKERS", "2"))
worker_class = "sync"
timeout = 60
graceful_timeout = 10
preload_app = True

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
accesslog = os.path.join(_LOG_DIR, "gunicorn_access.log")
errorlog = os.path.join(_LOG_DIR, "gunicorn_error.log")
loglevel = "info"
