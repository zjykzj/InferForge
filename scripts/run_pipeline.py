#!/usr/bin/env python3
"""Direct task-layer inference example: run the detect->crop->classify
pipeline WITHOUT the web service.

Demonstrates that tasks.pipeline.run_pipeline is callable directly from any
process — the same orchestration the sync /predict/pipeline api uses.
Requires the detect AND classify registry defaults on disk
(models/yolov8n.onnx + models/yolov8n-cls.onnx, lazy-loaded on first call).
Target classes come from INFERFORGE_PIPELINE_TARGETS (default car,truck,bus).

Usage:
    python3 scripts/run_pipeline.py --image assets/bus.jpg
    python3 scripts/run_pipeline.py --image assets/bus.jpg --save outputs/pipeline.jpg
    INFERFORGE_PIPELINE_TARGETS=dog,cat,bird python3 scripts/run_pipeline.py --url https://ultralytics.com/images/zidane.jpg
"""
import argparse
import base64
import logging
import os
import sys
import time

# Project-root import (mirrors celery_app.py): scripts run from anywhere.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tasks.pipeline import run_pipeline


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the detect->crop->classify pipeline directly (no web service involved)."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--image", help="local image path (sent as base64)")
    source.add_argument("--url", help="remote image url")
    parser.add_argument("--save", default=None, help="save the annotated result image to this path")
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
    out_b64, items = run_pipeline(image_b64=image_b64, image_url=image_url)
    print("items: %d (%.1fms total)" % (len(items), (time.perf_counter() - t0) * 1000))
    for item in items:
        x1, y1, x2, y2 = item["bbox"]
        print("  %-12s -> %-20s conf=%.4f  bbox=(%.1f, %.1f, %.1f, %.1f)" % (
            item["detect_class"], item["fine_class"], item["fine_confidence"],
            x1, y1, x2, y2))
        for i, top in enumerate(item["fine_top5"], start=1):
            print("      %d. %-25s conf=%.4f" % (i, top["class"], top["confidence"]))

    if args.save:
        with open(args.save, "wb") as f:
            f.write(base64.b64decode(out_b64))
        print("saved: %s" % args.save)


if __name__ == "__main__":
    main()
