#!/usr/bin/env python3
"""Direct task-layer inference example: run the gallery search or duplicate
check WITHOUT the web service.

Requires the embed model (models/dino2-small.onnx), a built gallery index
(scripts/build_gallery.py) and pymilvus installed (worker dep) — and no
celery worker currently holding the db file.

Usage:
    python3 scripts/run_search.py --image assets/bus.jpg              # gallery top-5
    python3 scripts/run_search.py --image assets/bus.jpg --top-k 10   # gallery top-10
    python3 scripts/run_search.py --image assets/bus.jpg --check      # duplicate check
    python3 scripts/run_search.py --url https://ultralytics.com/images/bus.jpg
"""
import argparse
import base64
import logging
import os
import sys
import time

# Project-root import (mirrors celery_app.py): scripts run from anywhere.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tasks.search import run_dupcheck, run_search


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the gallery search / duplicate check directly (no web service involved)."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--image", help="query image path (sent as base64)")
    source.add_argument("--url", help="query image url")
    parser.add_argument("--top-k", type=int, default=5, help="top-k for search mode (default 5)")
    parser.add_argument("--check", action="store_true",
                        help="duplicate check mode: top-1 + threshold decision instead of a ranked list")
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
    if args.check:
        result = run_dupcheck(image_b64=image_b64, image_url=image_url)
        print("found=%s threshold=%.2f (%.1fms total)" % (
            result["found"], result["threshold"], (time.perf_counter() - t0) * 1000))
        if result["match"]:
            m = result["match"]
            print("  match: %s  score=%.4f  path=%s" % (m["id"], m["score"], m["path"]))
    else:
        matches = run_search(image_b64=image_b64, image_url=image_url, top_k=args.top_k)
        print("matches: %d (%.1fms total)" % (len(matches), (time.perf_counter() - t0) * 1000))
        for i, m in enumerate(matches, start=1):
            print("  %d. %-20s score=%.4f  path=%s" % (i, m["id"], m["score"], m["path"]))


if __name__ == "__main__":
    main()
