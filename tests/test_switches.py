"""utils.switches.switch_on — the single source of the truthy-set truth.

app.py (router registration) and apis/health.py (readiness) must agree on
what "on" means; this test pins the behavior.
"""
from utils import switches


def test_switch_on_truthy(monkeypatch):
    for value in ("1", "true", "yes", "TRUE", "Yes"):
        monkeypatch.setenv("INFERFORGE_X", value)
        assert switches.switch_on("INFERFORGE_X")


def test_switch_on_falsy(monkeypatch):
    for value in ("0", "no", "off", "false", "on", ""):
        monkeypatch.setenv("INFERFORGE_X", value)
        assert not switches.switch_on("INFERFORGE_X")


def test_switch_on_unset(monkeypatch):
    monkeypatch.delenv("INFERFORGE_X", raising=False)
    assert not switches.switch_on("INFERFORGE_X")
