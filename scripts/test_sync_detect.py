#!/usr/bin/env python3
"""Manual API testing client for POST /predict (sync).

Usage:
    python3 scripts/test_sync_detect.py --image assets/bus.jpg
    python3 scripts/test_sync_detect.py --image assets/bus.jpg --save result.jpg
    python3 scripts/test_sync_detect.py --url https://ultralytics.com/images/bus.jpg
    python3 scripts/test_sync_detect.py --image assets/bus.jpg --host http://localhost:8000
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
    parser = argparse.ArgumentParser(description="Test the InferForge POST /predict API.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="service base url")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--image", help="local image path (sent as base64)")
    source.add_argument("--url", help="remote image url (sent as url)")
    parser.add_argument("--model", default=None, help="registered model name (default: the detect default)")
    parser.add_argument("--save", default=None, help="save the drawn result image to this path")
    parser.add_argument("--timeout", type=float, default=30.0, help="request timeout in seconds")
    return parser.parse_args()


def main():
    args = parse_args()

    if args.image:
        with open(args.image, "rb") as f:
            payload = {"image": base64.b64encode(f.read()).decode("utf-8")}
        print("POST %s/predict  image=%s" % (args.host, args.image))
    else:
        payload = {"url": args.url}
        print("POST %s/predict  url=%s" % (args.host, args.url))
    if args.model:
        payload["model"] = args.model

    t0 = time.perf_counter()
    try:
        resp = requests.post(args.host.rstrip("/") + "/predict", json=payload, headers=_auth_headers(), timeout=args.timeout)
    except requests.ConnectionError:
        print("[ERROR] cannot reach %s — is the service running? (./start.sh)" % args.host)
        sys.exit(2)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    print("HTTP %d | X-Request-ID: %s | %.1fms" % (
        resp.status_code, resp.headers.get("X-Request-ID", "-"), elapsed_ms))

    body = resp.json()
    print("code: %d | message: %s" % (body["code"], body["message"]))
    if body["code"] != 0:
        sys.exit(1)

    detections = body["data"]["detections"]
    print("detections: %d" % len(detections))
    for det in detections:
        x1, y1, x2, y2 = det["bbox"]
        print("  %-15s id=%-2d conf=%.2f  bbox=(%.1f, %.1f, %.1f, %.1f)" % (
            det["class"], det["class_id"], det["confidence"], x1, y1, x2, y2))

    if args.save:
        with open(args.save, "wb") as f:
            f.write(base64.b64decode(body["data"]["image"]))
        print("saved drawn image -> %s" % args.save)


if __name__ == "__main__":
    main()
