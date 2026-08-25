"""Gunicorn configuration for InferForge (ASGI).

worker_class = uvicorn.workers.UvicornWorker: gunicorn manages processes
(fork, graceful restarts, access/error log files) while uvicorn serves the
FastAPI ASGI app inside each worker. See docs/stack.md for the
gunicorn-vs-uvicorn decision and the timeout-semantics caveat.

preload_app=True: the app module (imports, logging config, router
registration) is loaded once in the master before forking, so workers start
fast and share Python imports. Model weights are loaded lazily by each task
on its first request and kept resident afterwards — this avoids holding an
onnxruntime session across fork(). INFERFORGE_PRELOAD=1 loads them at
startup instead, via the app's startup event: uvicorn runs the lifespan in
EACH worker process (after fork), so preloaded sessions are still created
post-fork, per worker.
"""
import os

bind = "0.0.0.0:8000"
workers = int(os.environ.get("INFERFORGE_WORKERS", "2"))
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 60
graceful_timeout = 10
preload_app = True

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
accesslog = os.path.join(_LOG_DIR, "gunicorn_access.log")
errorlog = os.path.join(_LOG_DIR, "gunicorn_error.log")
loglevel = "info"


def on_exit(server):
    """Gunicorn server hook — runs in the master during its own shutdown.

    The master imports the app (preload_app=True) and prometheus_client's
    multiprocess mode writes its counter/histogram files at utils.metrics
    import — the master never serves a request, so no lifespan hook ever
    runs there. This deletes the master's own files.

    What is deliberately NOT here: a worker_exit hook. uvicorn workers reset
    SIGTERM/SIGINT to SIG_DFL (uvicorn issue #894) and their teardown never
    reaches gunicorn's worker_exit finally (empirically verified). Each
    worker deletes its own runtime files via the app lifespan shutdown hook
    (app.py); start.sh's preflight un-sets PROMETHEUS_MULTIPROC_DIR before
    importing project modules so it creates none. SIGKILL/crash leftovers
    stay deploy hygiene (docs/metrics.md §3).
    """
    from utils import metrics

    metrics.mark_process_dead()
