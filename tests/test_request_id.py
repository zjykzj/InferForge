"""RequestIdMiddleware: per-request trace id, echoed in every response.

Ships with the request_id mechanism; standalone app (no conftest dependency).
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from utils import request_id


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(request_id.RequestIdMiddleware)

    @app.get("/ping")
    def ping():
        return {"id": request_id.get_request_id()}

    return app


def test_response_carries_generated_request_id():
    resp = TestClient(_app()).get("/ping")
    rid = resp.headers["X-Request-ID"]
    assert len(rid) == 12
    assert all(c in "0123456789abcdef" for c in rid)
    # The endpoint sees the same id the response header echoes.
    assert resp.json()["id"] == rid


def test_request_id_defaults_to_dash_outside_requests():
    assert request_id.get_request_id() == "-"


def test_ids_do_not_leak_across_requests():
    client = TestClient(_app())
    first = client.get("/ping").headers["X-Request-ID"]
    second = client.get("/ping").headers["X-Request-ID"]
    assert first != second
