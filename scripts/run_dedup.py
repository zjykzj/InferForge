#!/usr/bin/env python3
"""Direct task-layer inference example: run batch near-duplicate detection
WITHOUT the web service.

Requires the embed model (models/dino2-small.onnx). The threshold is the
shared business knob INFERFORGE_DUP_THRESHOLD (default 0.95). Group ids are
0-based positions in the source list: --image entries first (in the order
given), then --url entries.

Usage:
    python3 scripts/run_dedup.py --image assets/bus.jpg --image assets/bus.jpg --image assets/zidane.jpg
    INFERFORGE_DUP_THRESHOLD=0.9 python3 scripts/run_dedup.py --image a.jpg --url https://x/b.jpg
"""
import argparse
import base64
import logging
import os
import sys
import time

# Project-root import (mirrors celery_app.py): scripts run from anywhere.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tasks import embedding
from tasks.dedup import run_dedup


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run batch near-duplicate detection directly (no web service involved)."
    )
    parser.add_argument("--image", action="append", default=[],
                        help="local image path (repeatable; sent as base64)")
    parser.add_argument("--url", action="append", default=[],
                        help="remote image url (repeatable)")
    return parser.parse_args()


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
    args = parse_args()
    if len(args.image) + len(args.url) < 2:
        print("[ERROR] provide at least 2 sources via --image/--url")
        return 1

    sources = []
    for path in args.image:
        with open(path, "rb") as f:
            sources.append({"image": base64.b64encode(f.read()).decode("utf-8")})
        print("image=%s" % path)
    for url in args.url:
        sources.append({"url": url})
        print("url=%s" % url)

    t0 = time.perf_counter()
    result = run_dedup(sources)
    print("threshold=%.2f  total=%d  groups=%d  duplicates=%d (%.1fms)" % (
        embedding.dup_threshold(), result["total"], len(result["groups"]),
        result["duplicates"], (time.perf_counter() - t0) * 1000))
    for group in result["groups"]:
        print("  group: ids=%s representative=%d confidence=%.4f" % (
            group["ids"], group["representative"], group["confidence"]))


if __name__ == "__main__":
    main()
