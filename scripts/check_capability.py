#!/usr/bin/env python3
"""Template footprint checker: verify each registered capability matches the
add-capability.md file-set convention (docs/workflow/add-capability.md §3).

Static checks only — no model loads, no network, no services:
  A. the registry parses (load() enforces defaults/top-level rules)
  B. every registered capability appears in scripts/preflight_models.py
     CAPABILITY_SWITCH (otherwise the boot-time model check misses it)
  C. every capability has its core file set — task + api + test + script —
     via the template-known mapping, with a name-match fallback for
     fork-added capabilities
  D. every preflight switch var is actually read in app.py (an enabled
     capability with no route registration)

Ships with the template: forks get the same lint for their own capabilities,
so a capability that misses a file fails CI instead of failing at runtime.
"""
import ast
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

# Boot-time check, not a metrics producer — same hygiene as
# scripts/preflight_models.py.
os.environ.pop("PROMETHEUS_MULTIPROC_DIR", None)

from engines import registry
from utils.errors import RegistryConfigError

# capability -> minimal core file set (stem per layer). The template's own
# capabilities; fork-added capabilities fall back to name matching.
KNOWN_FILES = {
    "detect": {
        "tasks": ["detection"],
        "apis": ["sync_detect"],
        "tests": ["test_sync_detect"],
        "scripts": ["run_detection", "test_sync_detect"],
    },
    "segment": {
        "tasks": ["segmentation"],
        "apis": ["sync_segment"],
        "tests": ["test_sync_segment"],
        "scripts": ["run_segment", "test_sync_segment"],
    },
    "classify": {
        "tasks": ["classification"],
        "apis": ["sync_classify"],
        "tests": ["test_sync_classify"],
        "scripts": ["run_classify", "test_sync_classify"],
    },
    "embed": {
        "tasks": ["embedding"],
        "apis": ["sync_dedup"],
        "tests": ["test_dedup"],
        "scripts": ["run_dedup", "test_sync_dedup"],
    },
}


def _preflight_switches():
    """{capability: switch-var(s)} parsed from preflight_models.py's
    CAPABILITY_SWITCH dict (single source of the enabled set)."""
    path = os.path.join(_PROJECT_ROOT, "scripts", "preflight_models.py")
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "CAPABILITY_SWITCH" for t in node.targets
        ):
            return ast.literal_eval(node.value)
    return None


def check():
    errors = []
    try:
        reg = registry.load()
    except RegistryConfigError as exc:
        print("[ERROR] registry: %s" % exc)
        return 1
    capabilities = sorted({spec.capability for spec in reg.models.values()})
    print("[OK] registry: %d model(s) across %s"
          % (len(reg.models), ", ".join(capabilities) or "(none)"))

    # B. preflight coverage
    switches = _preflight_switches()
    if switches is None:
        errors.append("scripts/preflight_models.py: CAPABILITY_SWITCH not found")
    else:
        uncovered = [c for c in capabilities if c not in switches]
        if uncovered:
            errors.append("add to scripts/preflight_models.py CAPABILITY_SWITCH: %s"
                          % ", ".join(uncovered))

    # C. core file set per capability
    for capability in capabilities:
        stems = KNOWN_FILES.get(capability)
        if stems:
            for layer, names in stems.items():
                for name in names:
                    path = os.path.join(_PROJECT_ROOT, layer, name + ".py")
                    if not os.path.isfile(path):
                        errors.append("capability %r: missing %s/%s.py"
                                      % (capability, layer, name))
        else:
            # Fork-added capability: name-match convention (add-capability.md §3).
            for layer in ("tasks", "apis", "tests", "scripts"):
                files = [
                    f for f in os.listdir(os.path.join(_PROJECT_ROOT, layer))
                    if f.endswith(".py")
                ]
                if not any(capability in f for f in files):
                    errors.append(
                        "capability %r: no %s/ file matching its name "
                        "(docs/workflow/add-capability.md §3)" % (capability, layer)
                    )

    # D. every preflight switch is read somewhere in app.py
    if switches:
        with open(os.path.join(_PROJECT_ROOT, "app.py"), encoding="utf-8") as fh:
            app_src = fh.read()
        for capability, switch in switches.items():
            # None = always-on capability (detect); str/tuple = switch var(s).
            vars_ = [switch] if isinstance(switch, str) else (switch or [])
            for var in vars_:
                if var and var not in app_src:
                    errors.append(
                        "preflight switch %s (capability %r) is never read in app.py"
                        % (var, capability)
                    )

    if errors:
        for err in errors:
            print("[ERROR] %s" % err)
        return 1
    print("[OK] footprint convention intact (%d capability/capabilities)"
          % len(capabilities))
    return 0


if __name__ == "__main__":
    sys.exit(check())
