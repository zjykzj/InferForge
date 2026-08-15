"""Unified JSON response format: {"code": 0, "message": "success", "data": {...}}.

HTTP status is always 200; business status is carried by `code`:
    0     success
    1     invalid request (bad params / bad image data)
    2     image download failure
    3     internal error
"""
from typing import Any

from flask import Response, jsonify


def success(data: Any = None) -> Response:
    return jsonify({"code": 0, "message": "success", "data": data})


def error(message: str, code: int = 1) -> Response:
    return jsonify({"code": code, "message": message, "data": None})
