"""Redis-backed result store for the async query api.

Cross-cutting utility: web and worker both use it (web writes the pending
marker and reads results; the worker overwrites the marker with the final
envelope). Key scheme:

    inferforge:result:<task_id>  ->  "pending" | <envelope JSON>

Values expire after RESULT_TTL seconds (set on every write; the worker's
overwrite refreshes the TTL). The client is created lazily on first use so
nothing connects at import time (safe with gunicorn preload_app fork).
"""
import json
import logging
import os
from typing import Any, Dict, Optional

import redis

logger = logging.getLogger("utils.redis_store")

REDIS_URL = os.environ.get("INFERFORGE_REDIS_URL", "redis://localhost:6379/0")
try:
    RESULT_TTL = int(os.environ.get("INFERFORGE_RESULT_TTL", "3600"))
except ValueError:
    RESULT_TTL = 3600  # misconfigured TTL falls back to the default

_KEY_PREFIX = "inferforge:result"
PENDING_VALUE = "pending"

_client: Optional[redis.Redis] = None


def _get_client() -> redis.Redis:
    """Lazily create the redis client (fork-safe with preload_app)."""
    global _client
    if _client is None:
        _client = redis.Redis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        logger.info("redis client created: %s (ttl=%ds)", REDIS_URL, RESULT_TTL)
    return _client


def _key(task_id: str) -> str:
    return "%s:%s" % (_KEY_PREFIX, task_id)


def set_pending(task_id: str) -> None:
    """Mark a task as submitted but not finished yet.

    NX: never overwrite an existing value — if the worker already finished
    (rare race where it beats this write), the final envelope survives.
    """
    _get_client().set(_key(task_id), PENDING_VALUE, ex=RESULT_TTL, nx=True)


def set_result(task_id: str, envelope: Dict[str, Any]) -> None:
    """Overwrite the pending marker with the final envelope (JSON; TTL refreshed)."""
    _get_client().set(_key(task_id), json.dumps(envelope), ex=RESULT_TTL)


def get_result(task_id: str) -> Optional[str]:
    """Return the raw stored value (pending marker or envelope JSON); None if missing."""
    return _get_client().get(_key(task_id))
