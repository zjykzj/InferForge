#!/usr/bin/env python3
"""Manual API testing client for POST /predict/dedup (sync).

Requires the service running with INFERFORGE_DEDUP=1 ./start.sh and the
embed model in place (models/dino2-small.onnx).

Usage:
    python3 scripts/test_sync_dedup.py --image assets/bus.jpg --image assets/bus.jpg --image assets/zidane.jpg
    python3 scripts/test_sync_dedup.py --image assets/bus.jpg --url https://ultralytics.com/images/bus.jpg
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
    parser = argparse.ArgumentParser(description="Test the InferForge POST /predict/dedup API.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="service base url")
    parser.add_argument("--image", action="append", default=[],
                        help="local image path (repeatable; sent as base64)")
    parser.add_argument("--url", action="append", default=[],
                        help="remote image url (repeatable; sent as url)")
    parser.add_argument("--timeout", type=float, default=120.0, help="request timeout in seconds")
    return parser.parse_args()


def main():
    args = parse_args()
    if len(args.image) + len(args.url) < 2:
        print("[ERROR] provide at least 2 sources via --image/--url")
        sys.exit(2)

    sources = []
    for path in args.image:
        with open(path, "rb") as f:
            sources.append({"image": base64.b64encode(f.read()).decode("utf-8")})
        print("image=%s" % path)
    for url in args.url:
        sources.append({"url": url})
        print("url=%s" % url)
    payload = {"images": sources}

    t0 = time.perf_counter()
    try:
        resp = requests.post(args.host.rstrip("/") + "/predict/dedup",
                             json=payload, headers=_auth_headers(), timeout=args.timeout)
    except requests.ConnectionError:
        print("[ERROR] cannot reach %s — is the service running? (INFERFORGE_DEDUP=1 ./start.sh)" % args.host)
        sys.exit(2)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    print("HTTP %d | X-Request-ID: %s | %.1fms" % (
        resp.status_code, resp.headers.get("X-Request-ID", "-"), elapsed_ms))

    body = resp.json()
    print("code: %d | message: %s" % (body["code"], body["message"]))
    if body["code"] != 0:
        sys.exit(1)

    data = body["data"]
    print("total: %d | groups: %d | duplicates: %d" % (
        data["total"], len(data["groups"]), data["duplicates"]))
    for group in data["groups"]:
        print("  group: ids=%s representative=%d confidence=%.4f" % (
            group["ids"], group["representative"], group["confidence"]))


if __name__ == "__main__":
    main()
