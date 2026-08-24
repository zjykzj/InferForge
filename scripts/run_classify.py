#!/usr/bin/env python3
"""Direct task-layer inference example: run classification WITHOUT the web service.

Demonstrates that tasks.classification.run_classification is callable
directly from any process — the same orchestration the sync
/predict/classify api uses. Requires models/yolov8n-cls.onnx (lazy-loaded
on first call).

Usage:
    python3 scripts/run_classify.py --image assets/bus.jpg
    python3 scripts/run_classify.py --url https://ultralytics.com/images/bus.jpg
"""
import argparse
import base64
import logging
import os
import sys
import time

# Project-root import (mirrors celery_app.py): scripts run from anywhere.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tasks.classification import run_classification


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the classification task directly (no web service involved)."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--image", help="local image path (sent as base64)")
    source.add_argument("--url", help="remote image url")
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
    classifications = run_classification(image_b64=image_b64, image_url=image_url)
    print("top-%d (%.1fms total):" % (len(classifications), (time.perf_counter() - t0) * 1000))
    for i, cls in enumerate(classifications, start=1):
        print("  %d. %-25s id=%-4d conf=%.4f" % (
            i, cls["class"], cls["class_id"], cls["confidence"]))


if __name__ == "__main__":
    main()
