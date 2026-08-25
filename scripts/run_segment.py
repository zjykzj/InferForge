#!/usr/bin/env python3
"""Direct task-layer inference example: run segmentation WITHOUT the web service.

Demonstrates that tasks.segmentation.run_segmentation is callable directly
from any process — the same orchestration the sync /predict/segment api
uses. Requires models/yolov8n-seg.onnx (lazy-loaded on first call).

Usage:
    python3 scripts/run_segment.py --image assets/bus.jpg
    python3 scripts/run_segment.py --url https://ultralytics.com/images/bus.jpg --save result_seg.jpg
"""
import argparse
import base64
import logging
import os
import sys
import time

# Project-root import (mirrors celery_app.py): scripts run from anywhere.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tasks.segmentation import run_segmentation


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the segmentation task directly (no web service involved)."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--image", help="local image path (sent as base64)")
    source.add_argument("--url", help="remote image url")
    parser.add_argument("--model", default=None, help="registered model name (default: the segment default)")
    parser.add_argument("--save", default=None, help="save the overlay result image to this path")
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
    out_b64, segments = run_segmentation(image_b64=image_b64, image_url=image_url, model=args.model)
    print("segments: %d (%.1fms total)" % (len(segments), (time.perf_counter() - t0) * 1000))
    for seg in segments:
        x1, y1, x2, y2 = seg["bbox"]
        print("  %-15s id=%-2d conf=%.2f  bbox=(%.1f, %.1f, %.1f, %.1f)  mask=%d bytes" % (
            seg["class"], seg["class_id"], seg["confidence"], x1, y1, x2, y2,
            len(seg["mask"])))

    if args.save:
        with open(args.save, "wb") as f:
            f.write(base64.b64decode(out_b64))
        print("saved overlay image -> %s" % args.save)


if __name__ == "__main__":
    main()
