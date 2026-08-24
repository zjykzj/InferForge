#!/usr/bin/env python3
"""Direct task-layer inference example: run the hair-count Agent WITHOUT the web service.

Demonstrates that tasks.agent.run_hair_count is callable directly from any
process — the same orchestration the async query task uses. Needs the
worker-side LLM config in the environment (or a .env file) and the local
detection model (models/yolov8n.onnx):

    INFERFORGE_LLM_MODEL=your-model \
    INFERFORGE_LLM_API_KEY=your-key \
    [INFERFORGE_LLM_BASE_URL=https://your-endpoint/v1] \
    python3 scripts/run_agent.py --image assets/zidane.jpg
"""
import argparse
import base64
import json
import logging
import os
import sys
import time

# Project-root import (mirrors celery_app.py): scripts run from anywhere.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tasks.agent import run_hair_count
from tasks.vlm import LLMConfigError, LLMUpstreamError


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the hair-count agent directly (no web service involved)."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--image", help="local image path (sent as base64)")
    source.add_argument("--url", help="remote image url")
    parser.add_argument("--output", default=None, help="write the full result JSON to this path")
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

    try:
        t0 = time.perf_counter()
        result = run_hair_count(image_b64=image_b64, image_url=image_url)
    except LLMConfigError as exc:
        print("[ERROR] %s" % exc)
        sys.exit(2)
    except LLMUpstreamError as exc:
        print("[ERROR] upstream LLM call failed: %s" % exc)
        sys.exit(1)

    print("hair count (%.1fs): total=%d with_hair=%d without_hair=%d" % (
        time.perf_counter() - t0,
        result["total_persons"], result["with_hair"], result["without_hair"]))
    for person in result["per_person"]:
        x1, y1, x2, y2 = person["bbox"]
        print("  person #%d: has_hair=%s  bbox=(%.1f, %.1f, %.1f, %.1f)" % (
            person["index"], person["has_hair"], x1, y1, x2, y2))

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print("result JSON -> %s" % args.output)


if __name__ == "__main__":
    main()
