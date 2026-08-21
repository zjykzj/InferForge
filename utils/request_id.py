"""Per-request trace id (ASGI middleware + contextvars).

Generated at request entry by RequestIdMiddleware, attached to every log line
(see utils.logger) and echoed back in the X-Request-ID response header so
callers can report issues with a searchable id.

ContextVars replace Flask's request-scoped g: set before the app runs, reset
after, so ids never leak across requests. Celery workers have no HTTP context
— they fall back to the request_id carried in task kwargs (utils.logger).
"""
import contextvars
import uuid

from starlette.datastructures import MutableHeaders

REQUEST_ID_HEADER = "X-Request-ID"

# 12 hex chars (48 bits): collision-safe at service scale, short enough for logs.
_LENGTH = 12

_request_id_var = contextvars.ContextVar("request_id", default="-")


def generate_request_id() -> str:
    return uuid.uuid4().hex[:_LENGTH]


def get_request_id() -> str:
    return _request_id_var.get()


class RequestIdMiddleware:
    """Set/reset the request_id ContextVar; echo it in every response header.

    Pure ASGI middleware (no BaseHTTPMiddleware task spawning): the ContextVar
    is set in the request task before the app runs, and anyio's threadpool
    copies caller context into worker threads — so sync `def` endpoints see
    the same id. Adding the header at http.response.start covers success
    responses, the 503 readiness envelope, validation envelopes and 404s.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        token = _request_id_var.set(generate_request_id())

        async def send_with_request_id(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.append(REQUEST_ID_HEADER, get_request_id())
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            _request_id_var.reset(token)
