"""Startup model warmup behind INFERFORGE_PRELOAD=1.

The web process and the celery worker both call in here at startup; each
loads the DEFAULT model of the capabilities IT serves:

- web: detect always, segment/classify behind their env switches (mirrors
  app.py's router registration and /health/ready)
- worker: detect only — segment/classify are sync-only apis and the async
  tasks never touch them, so preloading there would waste memory

Best-effort by design: a failed load is logged per capability and left for
/health/ready to reflect (that capability keeps reporting 503 until the
first successful request). Readiness, not the preload log, is the source of
truth. Only DEFAULT models load — rare registered models keep lazy loading
(docs/model-registry.md), so a warmup can never balloon into loading every
registered weight.
"""
import logging

from tasks import classification, detection, segmentation
from utils import switches

logger = logging.getLogger("tasks.warmup")


def _load(capability: str, fn) -> None:
    try:
        fn()
        logger.info("preloaded %s default model", capability)
    except Exception:
        # A corrupt weight file, a missing default, a bad registry — log it
        # and keep going: the capability stays not-ready, everything else
        # still serves. Startup must not die because one model is broken.
        logger.exception(
            "preload failed (%s) — readiness stays 503 until the first "
            "successful load", capability
        )


def preload_web() -> None:
    """Web startup: every capability this process can serve requests on."""
    if not switches.switch_on("INFERFORGE_PRELOAD"):
        return
    _load("detect", detection.preload)
    if switches.switch_on("INFERFORGE_SEG"):
        _load("segment", segmentation.preload)
    if switches.switch_on("INFERFORGE_CLS") or switches.switch_on("INFERFORGE_PIPELINE"):
        # Pipeline composes the classify default, so it needs the classify
        # model warmed up even when the classify api itself is off.
        _load("classify", classification.preload)


def preload_worker() -> None:
    """Celery worker startup: only the local-model capability the async
    tasks actually use (detection)."""
    if not switches.switch_on("INFERFORGE_PRELOAD"):
        return
    _load("detect", detection.preload)
