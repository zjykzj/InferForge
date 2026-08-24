#!/usr/bin/env python3
"""Direct task-layer inference example: run the VLM task WITHOUT the web service.

Demonstrates that tasks.vlm.run_vlm is callable directly from any process —
the same orchestration the async query task uses. Needs the worker-side LLM
config in the environment (or a .env file):

    INFERFORGE_LLM_MODEL=your-model \
    INFERFORGE_LLM_API_KEY=your-key \
    [INFERFORGE_LLM_BASE_URL=https://your-endpoint/v1] \
    python3 scripts/run_vlm.py --image assets/bus.jpg
"""
import argparse
import base64
import logging
import os
import sys
import time

# Project-root import (mirrors celery_app.py): scripts run from anywhere.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tasks.vlm import LLMConfigError, LLMUpstreamError, run_vlm


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the VLM task directly (no web service involved)."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--image", help="local image path (sent as base64)")
    source.add_argument("--url", help="remote image url")
    parser.add_argument("--save", default=None, help="save the answer text to this path")
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
        answer, model = run_vlm(image_b64=image_b64, image_url=image_url)
    except LLMConfigError as exc:
        print("[ERROR] %s" % exc)
        sys.exit(2)
    except LLMUpstreamError as exc:
        print("[ERROR] upstream LLM call failed: %s" % exc)
        sys.exit(1)

    print("model: %s (%.1fs)" % (model, time.perf_counter() - t0))
    print("answer:\n%s" % answer)

    if args.save:
        with open(args.save, "w", encoding="utf-8") as f:
            f.write(answer)
        print("saved answer -> %s" % args.save)


if __name__ == "__main__":
    main()
