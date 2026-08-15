"""Per-request trace id.

Generated at request entry, attached to every log line (see utils.logger) and
echoed back in the X-Request-ID response header so callers can report issues
with a searchable id.
"""
import uuid

from flask import g

REQUEST_ID_HEADER = "X-Request-ID"

# 12 hex chars (48 bits): collision-safe at service scale, short enough for logs.
_LENGTH = 12


def before_request():
    g.request_id = uuid.uuid4().hex[:_LENGTH]


def after_request(response):
    response.headers[REQUEST_ID_HEADER] = get_request_id()
    return response


def get_request_id() -> str:
    return g.get("request_id", "-")
