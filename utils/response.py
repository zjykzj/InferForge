"""Unified JSON response format: {"code": 0, "message": "success", "data": {...}}."""
from typing import Any, Tuple

from flask import Response, jsonify


def success(data: Any = None) -> Response:
    return jsonify({"code": 0, "message": "success", "data": data})


def error(message: str, code: int = 1, http_status: int = 400) -> Tuple[Response, int]:
    return jsonify({"code": code, "message": message, "data": None}), http_status
