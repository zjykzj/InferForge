#!/usr/bin/env python3
"""Manual API testing client for POST /predict/classify (sync).

Requires the service running with INFERFORGE_CLS=1 ./start.sh and
models/yolov8n-cls.onnx in place.

Usage:
    python3 scripts/test_predict_classify.py --image assets/bus.jpg
    python3 scripts/test_predict_classify.py --url https://ultralytics.com/images/bus.jpg
"""
import argparse
import base64
import os
import sys
import time

import requests

DEFAULT_HOST = "http://localhost:8000"


def _auth_headers():
    """Attach X-API-Key when INFERFORGE_API_KEY is set (see utils/auth.py)."""
    key = os.environ.get("INFERFORGE_API_KEY")
    return {"X-API-Key": key} if key else None


def parse_args():
    parser = argparse.ArgumentParser(description="Test the InferForge POST /predict/classify API.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="service base url")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--image", help="local image path (sent as base64)")
    source.add_argument("--url", help="remote image url (sent as url)")
    parser.add_argument("--timeout", type=float, default=30.0, help="request timeout in seconds")
    return parser.parse_args()


def main():
    args = parse_args()

    if args.image:
        with open(args.image, "rb") as f:
            payload = {"image": base64.b64encode(f.read()).decode("utf-8")}
        print("POST %s/predict/classify  image=%s" % (args.host, args.image))
    else:
        payload = {"url": args.url}
        print("POST %s/predict/classify  url=%s" % (args.host, args.url))

    t0 = time.perf_counter()
    try:
        resp = requests.post(args.host.rstrip("/") + "/predict/classify",
                             json=payload, headers=_auth_headers(), timeout=args.timeout)
    except requests.ConnectionError:
        print("[ERROR] cannot reach %s — is the service running? (INFERFORGE_CLS=1 ./start.sh)" % args.host)
        sys.exit(2)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    print("HTTP %d | X-Request-ID: %s | %.1fms" % (
        resp.status_code, resp.headers.get("X-Request-ID", "-"), elapsed_ms))

    body = resp.json()
    print("code: %d | message: %s" % (body["code"], body["message"]))
    if body["code"] != 0:
        sys.exit(1)

    classifications = body["data"]["classifications"]
    print("top-%d:" % len(classifications))
    for i, cls in enumerate(classifications, start=1):
        print("  %d. %-25s id=%-4d conf=%.4f" % (
            i, cls["class"], cls["class_id"], cls["confidence"]))


if __name__ == "__main__":
    main()
