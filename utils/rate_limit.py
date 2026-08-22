"""Fixed-window rate limiting (stdlib only, off by default).

INFERFORGE_RATE_LIMIT=N limits each client to N requests per minute
(window keyed by X-API-Key when auth is enabled, client IP otherwise).
Failures get HTTP 429 + code=8 + Retry-After — same protocol-exception
pattern as auth's 401 (docs/status-codes.md).

Known limitation (documented in docs/security.md): buckets live in process
memory, and gunicorn workers do not share it — with W workers the effective
limit is roughly W * N per client. That is an accepted approximation for
single-host deployments; strict limiting needs a shared store (Redis is
already available in async deployments).
"""
import os
import threading
import time

from utils import response
from utils.auth import EXEMPT_PATHS

WINDOW_SECONDS = 60.0
MAX_BUCKETS = 10_000  # opportunistic sweep threshold (unbounded IP memory)


def _parse_limit(raw: str | None):
    try:
        value = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


class RateLimitMiddleware:
    """Enforce a per-client fixed window when INFERFORGE_RATE_LIMIT is set."""

    def __init__(self, app):
        self.app = app
        self.limit = _parse_limit(os.environ.get("INFERFORGE_RATE_LIMIT"))
        # Per-key buckets only make sense when auth validates keys first;
        # with auth off, bucketing by a client-supplied header would let
        # callers rotate arbitrary keys to bypass the limit.
        self.use_api_key = bool(os.environ.get("INFERFORGE_API_KEY"))
        self._buckets: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or self.limit is None:
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if any(path == p or path.startswith(p + "/") for p in EXEMPT_PATHS):
            await self.app(scope, receive, send)
            return

        retry_after = self._check(self._client_key(scope))
        if retry_after is not None:
            resp = response.error(
                "rate limit exceeded",
                code=8,
                http_status=429,
                headers={"Retry-After": str(retry_after)},
            )
            await resp(scope, receive, send)
            return
        await self.app(scope, receive, send)

    def _client_key(self, scope) -> str:
        if self.use_api_key:
            for name, value in scope.get("headers", []):
                if name == b"x-api-key":
                    return "key:" + value.decode("latin-1")
        client = scope.get("client")
        return "ip:" + (client[0] if client else "-")

    def _check(self, key: str):
        """Count one request; return Retry-After seconds when over the limit."""
        now = time.monotonic()
        with self._lock:
            if len(self._buckets) > MAX_BUCKETS:
                expired = [k for k, (start, _) in self._buckets.items()
                           if now - start >= WINDOW_SECONDS]
                for k in expired:
                    del self._buckets[k]
            start, count = self._buckets.get(key, (now, 0))
            if now - start >= WINDOW_SECONDS:
                start, count = now, 0
            count += 1
            self._buckets[key] = (start, count)
            if count > self.limit:
                return max(1, int(WINDOW_SECONDS - (now - start)) + 1)
        return None
