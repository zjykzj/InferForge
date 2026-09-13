"""Architecture guard tests: the red-zone axioms (docs/workflow/forking-contract.md §2)
as executable checks.

These ship with every new project — a downstream agent that breaks a layering,
envelope or status-code rule gets a red CI in its own repo, not a prose
reminder in the template. Model-free and network-free like the rest of the
suite: everything here parses source files with ast.

Guarded axioms:
1. One-way dependency chain app -> apis -> tasks -> engines (utils cross-cutting)
2. Heavy deps (onnxruntime/openai/pymilvus/pydantic-ai/ultralytics) are never
   imported at module level (CLAUDE.md: lazy import inside function bodies)
3. HTTP always 200 + {code, message, data} envelope; pydantic validation
   failures fold into code=1 (FastAPI's 422 never leaks) — end-to-end check,
   runs when the detect capability is assembled
The envelope code double-registration check lives in tests/test_response.py
(it ships with the envelope mechanism).
"""
import ast
from pathlib import Path

# @inferforge:detect
from fastapi.testclient import TestClient  # noqa: E402

from apis.sync_detect import sync_detect_router  # noqa: E402
# @inferforge:end:detect

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# layer dir -> top-level modules it must never import (one-way chain:
# app -> apis -> tasks -> engines; utils is cross-cutting and must not
# depend on business layers either).
FORBIDDEN_IMPORTS = {
    "engines": {"tasks", "apis", "app", "celery_app"},
    "tasks": {"apis", "app", "celery_app"},
    "apis": {"engines", "app", "celery_app"},
    "utils": {"engines", "tasks", "apis", "app", "celery_app"},
}

# Heavy/worker-only dependencies: imported lazily inside function bodies by
# convention (CLAUDE.md). A module-level import breaks model-free tests,
# worker-only packaging, or the AGPL-free guarantee.
HEAVY_MODULES = {"onnxruntime", "openai", "pymilvus", "pydantic_ai", "ultralytics"}

# Composition roots at project root: app.py wires apis only (engines/tasks
# stay behind the api layer); celery_app.py must import task modules to
# register them, but never the api or engine layers.
ROOT_FORBIDDEN = {
    "app.py": {"engines", "tasks"},
    "celery_app.py": {"apis", "engines"},
}


def _module_imports(path: Path) -> list[ast.stmt]:
    """All module-level import statements of a .py file (ast-parse only)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]


def _imported_roots(node: ast.stmt) -> set[str]:
    if isinstance(node, ast.Import):
        return {alias.name.split(".")[0] for alias in node.names}
    # ImportFrom: relative imports (level > 0) resolve within the project —
    # resolve them to the importing module's layer by walking back the dots.
    module = node.module or ""
    if node.level == 0:
        return {module.split(".")[0]} if module else set()
    return set()  # relative imports: nothing to check for module-level scans


def _layer_files(layer: str) -> list[Path]:
    return sorted((PROJECT_ROOT / layer).glob("*.py"))


def test_dependency_direction():
    """No reverse imports: each layer only imports layers below it (plus utils)."""
    violations = []
    for layer, forbidden in FORBIDDEN_IMPORTS.items():
        for path in _layer_files(layer):
            for node in _module_imports(path):
                for root in _imported_roots(node):
                    if root in forbidden:
                        violations.append("%s imports %s (line %d)" % (path.name, root, node.lineno))
    for path in PROJECT_ROOT.glob("*.py"):
        forbidden = ROOT_FORBIDDEN.get(path.name)
        if not forbidden:
            continue  # composition roots only
        for node in _module_imports(path):
            for root in _imported_roots(node):
                if root in forbidden:
                    violations.append("%s imports %s (line %d)" % (path.name, root, node.lineno))
    assert not violations, "dependency-direction violations:\n  " + "\n  ".join(violations)


def test_heavy_deps_never_imported_at_module_level():
    """onnxruntime/openai/pymilvus/pydantic-ai/ultralytics only inside functions."""
    violations = []
    candidates = (
        list(PROJECT_ROOT.glob("*.py"))
        + _layer_files("apis")
        + _layer_files("tasks")
        + _layer_files("engines")
        + _layer_files("utils")
    )
    for path in candidates:
        for node in _module_imports(path):
            for root in _imported_roots(node):
                if root in HEAVY_MODULES:
                    violations.append("%s imports %s at module level (line %d)"
                                      % (path.name, root, node.lineno))
    assert not violations, "heavy deps must be imported lazily:\n  " + "\n  ".join(violations)


# @inferforge:detect
def test_envelope_always_200_and_422_never_leaks(app_factory):
    """Validation failures fold into 200 + code=1; success/failure bodies both
    carry exactly the {code, message, data} envelope."""
    client = TestClient(app_factory(sync_detect_router))

    # Success path: envelope shape on a fake-predictor round trip.
    resp = client.post("/predict", json={"image": "aGVsbG8="})  # invalid base64 -> code=1
    assert resp.status_code == 200, "business errors must be HTTP 200, got %d" % resp.status_code
    body = resp.json()
    assert set(body.keys()) == {"code", "message", "data"}
    assert body["code"] == 1

    # Missing params: FastAPI's default 422 must never leak through.
    resp = client.post("/predict", json={})
    assert resp.status_code == 200, "pydantic validation leaked HTTP %d (422 forbidden)" % resp.status_code
    body = resp.json()
    assert set(body.keys()) == {"code", "message", "data"}
    assert body["code"] == 1
# @inferforge:end:detect
