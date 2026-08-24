#!/usr/bin/env python3
"""Direct task-layer inference example: run detection WITHOUT the web service.

Demonstrates that tasks.detection.run_detection is callable directly from any
process — the same orchestration the sync /predict api and the async tasks
use. Requires models/yolov8n.onnx (lazy-loaded on first call).

Usage:
    python3 scripts/run_detection.py --image assets/bus.jpg
    python3 scripts/run_detection.py --url https://ultralytics.com/images/bus.jpg --save result.jpg
"""
import argparse
import base64
import logging
import os
import sys
import time

# Project-root import (mirrors celery_app.py): scripts run from anywhere.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tasks.detection import run_detection


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the detection task directly (no web service involved)."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--image", help="local image path (sent as base64)")
    source.add_argument("--url", help="remote image url")
    parser.add_argument("--save", default=None, help="save the drawn result image to this path")
    return parser.parse_args()


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
    args = parse_args()

    if args.image:
        with open(args.image, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")
        image_url = None
        print("image=%s" % args.image)
    else:
        image_b64 = None
        image_url = args.url
        print("url=%s" % args.url)

    t0 = time.perf_counter()
    out_b64, detections = run_detection(image_b64=image_b64, image_url=image_url)
    print("detections: %d (%.1fms total)" % (len(detections), (time.perf_counter() - t0) * 1000))
    for det in detections:
        x1, y1, x2, y2 = det["bbox"]
        print("  %-15s id=%-2d conf=%.2f  bbox=(%.1f, %.1f, %.1f, %.1f)" % (
            det["class"], det["class_id"], det["confidence"], x1, y1, x2, y2))

    if args.save:
        with open(args.save, "wb") as f:
            f.write(base64.b64decode(out_b64))
        print("saved drawn image -> %s" % args.save)


if __name__ == "__main__":
    main()
