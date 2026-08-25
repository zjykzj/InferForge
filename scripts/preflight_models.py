"""Boot-time model preflight: fail fast if a registered model file is missing.

Enumerates the model registry (engines.registry) for the ENABLED capabilities
only — detection is always on, segment/classify behind their env switches
(utils.switches is the single source of truth for "on"). Every registered
model of an enabled capability must have its weights file on disk, because
any of them can be routed to at request time. A missing or unparseable
registry YAML also fails here, before gunicorn ever starts.

Called by start.sh; the error format mirrors its historical preflight.
"""
import os
import sys

# Celery-style sys.path insert: running `python3 scripts/...` does not put
# the project root on sys.path, but this script imports project modules.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# This script is a boot-time check, not a metrics producer. start.sh exports
# PROMETHEUS_MULTIPROC_DIR, and prometheus_client's multiprocess mode writes
# one file per process at utils.metrics import (reached via the
# engines.yolo import chain below) — unsetting the env keeps the shared
# metrics dir free of this short-lived process's files.
os.environ.pop("PROMETHEUS_MULTIPROC_DIR", None)

from engines import registry
from utils.errors import RegistryConfigError
from utils.switches import switch_on

CAPABILITY_SWITCH = {
    "detect": None,             # always enabled
    "segment": "INFERFORGE_SEG",
    "classify": "INFERFORGE_CLS",
}


def enabled_capabilities():
    return [
        capability
        for capability, switch in CAPABILITY_SWITCH.items()
        if switch is None or switch_on(switch)
    ]


def main():
    try:
        registry.load()
    except RegistryConfigError as exc:
        print("[ERROR] %s" % exc)
        return 1

    missing = [
        spec.path
        for capability in enabled_capabilities()
        for spec in registry.specs_for(capability)
        if not os.path.isfile(registry.abs_path(spec.path))
    ]
    if missing:
        for path in missing:
            print("[ERROR] %s not found." % path)
        print("        Export the model (e.g. ultralytics yolov8n) to ONNX and put it into models/,")
        print("        or update models/registry.yaml to match the models you do have.")
        return 1
    print("[OK] all registered model files present for enabled capabilities "
          "(%s)" % ", ".join(enabled_capabilities()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
