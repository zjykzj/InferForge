"""Envelope contract: success/error shapes and the 422-fold handler.

Ships with the envelope mechanism; standalone apps (no conftest dependency)
so the file passes on any assembly that selects the mechanism.
"""
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel

from utils import response

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _app() -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, response.validation_error_handler)

    class Body(BaseModel):
        image: str

    @app.post("/echo")
    def echo(body: Body):
        return response.success({"got": body.image})

    @app.get("/fail")
    def fail():
        return response.error("boom", code=3, http_status=503, headers={"X-Extra": "1"})

    return app


def test_success_envelope():
    resp = TestClient(_app()).post("/echo", json={"image": "abc"})
    assert resp.status_code == 200
    assert resp.json() == {"code": 0, "message": "success", "data": {"got": "abc"}}


def test_error_envelope():
    resp = TestClient(_app()).get("/fail")
    assert resp.status_code == 503
    assert resp.headers["X-Extra"] == "1"
    assert resp.json() == {"code": 3, "message": "boom", "data": None}


def test_validation_failure_folds_into_envelope():
    """FastAPI's default 422 must never leak: 200 + code=1."""
    resp = TestClient(_app()).post("/echo", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"code", "message", "data"}
    assert body["code"] == 1


def test_status_codes_double_registered():
    """utils/response.py docstring and docs/status-codes.md must list the same
    business codes (CLAUDE.md: new codes register in BOTH places). Moved here
    from test_architecture.py when the envelope became an opt-in mechanism —
    the doc half skips because docs/ ships with the template only."""
    response_doc = (PROJECT_ROOT / "utils" / "response.py").read_text(encoding="utf-8")
    # The docstring enumerates codes as indented "N    <name>" lines.
    doc_codes = set(int(m) for m in re.findall(r"^\s{4}(\d+)\s+\w+", response_doc, re.MULTILINE))

    status_path = PROJECT_ROOT / "docs" / "status-codes.md"
    if not status_path.exists():
        pytest.skip("docs/status-codes.md absent (template-only file)")
    status_doc = status_path.read_text(encoding="utf-8")
    # §2 table rows look like: | `0` | success | ...
    table_codes = set(int(m) for m in re.findall(r"^\|\s*`(\d+)`\s*\|", status_doc, re.MULTILINE))

    assert doc_codes, "no codes parsed from utils/response.py docstring — format drift?"
    assert table_codes, "no codes parsed from docs/status-codes.md §2 — format drift?"
    assert doc_codes == table_codes, (
        "double registration broken:\n"
        "  response.py docstring: %s\n"
        "  status-codes.md §2:    %s"
        % (sorted(doc_codes), sorted(table_codes))
    )
