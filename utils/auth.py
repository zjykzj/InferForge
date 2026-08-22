"""API-key auth middleware (stdlib only, off by default).

When INFERFORGE_API_KEY is unset, every request passes through untouched —
zero dependencies, zero configuration. When set, all non-exempt paths must
send `X-API-Key: <key>`; failures get HTTP 401 + code=7 envelope (the 401
carries the semantics for gateways, the body keeps the envelope shape —
same pattern as the readiness probe's 503 + code=6, docs/status-codes.md).

Comparison is constant-time (hmac.compare_digest) to avoid timing side
channels. This is the minimal single-key model — no users, no scopes;
multi-user / SSO scenarios belong to a gateway layer (docs/security.md).
"""
import hmac
import os

from utils import response

API_KEY_HEADER = "X-API-Key"

# Probe / doc / metrics paths stay anonymous: orchestrators and scrapers do
# not speak application auth. Public deployments should shield /docs and
# /metrics at the gateway instead (docs/security.md).
EXEMPT_PATHS = ("/health", "/health/ready", "/metrics", "/docs", "/openapi.json")


class AuthMiddleware:
    """Enforce X-API-Key on non-exempt paths when INFERFORGE_API_KEY is set."""

    def __init__(self, app):
        self.app = app
        self.api_key = os.environ.get("INFERFORGE_API_KEY")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not self.api_key:
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if any(path == p or path.startswith(p + "/") for p in EXEMPT_PATHS):
            await self.app(scope, receive, send)
            return

        provided = None
        for name, value in scope.get("headers", []):
            if name == b"x-api-key":
                provided = value.decode("latin-1")
                break
        # compare as bytes: compare_digest on str only supports ASCII keys
        if provided is not None and hmac.compare_digest(
            provided.encode("utf-8"), self.api_key.encode("utf-8")
        ):
            await self.app(scope, receive, send)
            return

        resp = response.error("unauthorized", code=7, http_status=401)
        await resp(scope, receive, send)
