"""Unified JSON response format: {"code": 0, "message": "success", "data": {...}}.

HTTP status is always 200; business status is carried by `code`:
    0     success
    1     invalid request (bad params / bad image data)
    2     image download failure
    3     internal error
    4     task not found (query api: never submitted or result expired)
    5     task pending (query api: submitted, not finished yet)
    6     service not ready (health/ready: predictor not loaded)
    7     unauthorized (auth middleware: missing / wrong X-API-Key)
    8     rate limit exceeded (rate_limit middleware: over INFERFORGE_RATE_LIMIT)
    9     upstream LLM call failure (vlm tasks: remote LLM timeout / 5xx / rate limit / connection)
    10    model not found (predict apis: unknown model name or wrong capability)

The exceptions to "always 200" are infrastructure endpoints: /health/ready
returns HTTP 503 alongside code 6 so that orchestrator probes can read the
status code directly, the auth middleware returns HTTP 401 alongside code 7
so that gateways see the rejection, and the rate limiter returns HTTP 429
alongside code 8 (see apis.health, utils.auth, utils.rate_limit and
docs/status-codes.md).

Pydantic validation failures (RequestValidationError) are also folded into
the envelope by validation_error_handler — code=1, HTTP 200. Register it in
every FastAPI app so the framework's default 422 never leaks.
"""
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from utils import metrics


def success(data: Any = None) -> JSONResponse:
    metrics.record_response(0)
    return JSONResponse({"code": 0, "message": "success", "data": data})


def error(message: str, code: int = 1, http_status: int = 200,
          headers: dict | None = None) -> JSONResponse:
    metrics.record_response(code)
    return JSONResponse({"code": code, "message": message, "data": None},
                        status_code=http_status, headers=headers)


def _format_validation_errors(exc: RequestValidationError) -> str:
    """First error per field, in a caller-readable line.

    Pydantic v2 wraps model_validator ValueErrors with a "Value error, "
    prefix and locates every error at ("body", <field>) — strip both.
    """
    parts = []
    for err in exc.errors():
        msg = str(err["msg"])
        if msg.startswith("Value error, "):
            msg = msg[len("Value error, "):]
        loc = [str(p) for p in err["loc"] if p != "body"]
        parts.append("%s: %s" % (".".join(loc), msg) if loc else msg)
    return "; ".join(parts)


def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Translate pydantic validation failures into the always-200 envelope."""
    return error("invalid request: %s" % _format_validation_errors(exc), code=1)
