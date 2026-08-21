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
"""
from typing import Any

from flask import Response, jsonify


def success(data: Any = None) -> Response:
    return jsonify({"code": 0, "message": "success", "data": data})


def error(message: str, code: int = 1, http_status: int = 200) -> Response:
    resp = jsonify({"code": code, "message": message, "data": None})
    resp.status_code = http_status
    return resp
