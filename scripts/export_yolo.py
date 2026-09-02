#!/usr/bin/env python3
"""Export the ultralytics YOLOv8n models (detect / segment / classify) to ONNX.

Subprocess wrapper around the `yolo export` CLI — the project NEVER imports
ultralytics (AGPL-3.0): this script shells out to the export tool exactly
like the documented manual command, so the project's license posture is
unchanged (see CLAUDE.md). Requires the ultralytics package installed
(one-off export dep, like torch for export_dinov2.py); the first run
downloads the .pt weights automatically.

After each export the script verifies the ONNX output shapes with
onnxruntime against what the engines expect (detect `(1,84,8400)`, segment
`(1,116,8400)` + `(1,32,160,160)` — order-insensitive, cls `(1,1000)`),
so a mislabeled or truncated model file fails loudly here instead of at
request time.

Usage:
    python3 scripts/export_yolo.py                # all three -> models/
    python3 scripts/export_yolo.py --task detect  # one of them
    python3 scripts/export_yolo.py --task detect --task segment
    python3 scripts/export_yolo.py --output-dir /tmp/models --skip-verify
"""
import argparse
import os
import subprocess
import sys

# Project-root import (mirrors celery_app.py): scripts run from anywhere.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TASKS = {
    "detect": {
        "model": "yolov8n.pt",
        "file": "yolov8n.onnx",
        "input": (1, 3, 640, 640),
        "outputs": [(1, 84, 8400)],
    },
    "segment": {
        "model": "yolov8n-seg.pt",
        "file": "yolov8n-seg.onnx",
        "input": (1, 3, 640, 640),
        "outputs": [(1, 116, 8400), (1, 32, 160, 160)],
    },
    "classify": {
        "model": "yolov8n-cls.pt",
        "file": "yolov8n-cls.onnx",
        "input": (1, 3, 224, 224),  # cls is a 224 model, not 640
        "outputs": [(1, 1000)],
    },
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Export the ultralytics YOLOv8n models to ONNX (subprocess wrapper, no ultralytics import)."
    )
    parser.add_argument("--task", action="append", choices=sorted(TASKS), default=None,
                        help="repeatable; default: export all three")
    parser.add_argument("--output-dir", default=os.path.join("models"),
                        help="output directory (default: models/)")
    parser.add_argument("--skip-verify", action="store_true",
                        help="skip the onnxruntime output-shape check")
    return parser.parse_args()


def export_one(task: str, info: dict, output_dir: str, skip_verify: bool) -> int:
    os.makedirs(output_dir, exist_ok=True)
    cmd = ["yolo", "export", "model=%s" % info["model"], "format=onnx"]
    print("running: %s (in %s)" % (" ".join(cmd), output_dir))
    try:
        subprocess.run(cmd, check=True, cwd=output_dir)
    except FileNotFoundError:
        print("[ERROR] `yolo` CLI not found — pip install ultralytics first")
        return 1
    except subprocess.CalledProcessError as exc:
        print("[ERROR] export failed: %s" % exc)
        return 1

    path = os.path.join(output_dir, info["file"])
    if not os.path.isfile(path):
        print("[ERROR] export did not produce %s" % path)
        return 1
    print("[OK] exported: %s" % path)

    if skip_verify:
        return 0

    import numpy as np
    import onnxruntime

    session = onnxruntime.InferenceSession(path, providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    outputs = session.run(None, {input_name: np.zeros(info["input"], dtype=np.float32)})
    actual = sorted(tuple(o.shape) for o in outputs)
    expected = sorted(info["outputs"])
    print("[OK] output shapes: %s (expect %s)" % (actual, expected))
    if actual != expected:
        print("[ERROR] output shapes do not match what the engine expects")
        return 1
    return 0


def main():
    args = parse_args()
    tasks = args.task if args.task else sorted(TASKS)
    for task in tasks:
        rc = export_one(task, TASKS[task], args.output_dir, args.skip_verify)
        if rc != 0:
            return rc
    print("[OK] all requested exports verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
