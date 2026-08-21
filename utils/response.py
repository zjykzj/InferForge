"""Unified JSON response format: {"code": 0, "message": "success", "data": {...}}.

HTTP status is always 200; business status is carried by `code`:
    0     success
    1     invalid request (bad params / bad image data)
    2     image download failure
    3     internal error
    4     task not found (query api: never submitted or result expired)
    5     task pending (query api: submitted, not finished yet)
    6     service not ready (health/ready: predictor not loaded)

The single exception to "always 200" is infrastructure probes: /health/ready
returns HTTP 503 alongside code 6 so that orchestrator probes can read the
status code directly (see apis.health and docs/status-codes.md).

Pydantic validation failures (RequestValidationError) are also folded into
the envelope by validation_error_handler — code=1, HTTP 200. Register it in
every FastAPI app so the framework's default 422 never leaks.
"""
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def success(data: Any = None) -> JSONResponse:
    return JSONResponse({"code": 0, "message": "success", "data": data})


def error(message: str, code: int = 1, http_status: int = 200) -> JSONResponse:
    return JSONResponse({"code": code, "message": message, "data": None}, status_code=http_status)


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
