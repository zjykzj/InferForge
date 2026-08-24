#!/usr/bin/env python3
"""Manual API testing client for POST /predict/vlm/callback (async VLM).

Usage:
    python3 scripts/test_vlm_callback.py --image assets/bus.jpg \
        --callback-url http://localhost:9000/result
    python3 scripts/test_vlm_callback.py --url https://ultralytics.com/images/bus.jpg \
        --callback-url http://localhost:9000/result
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
    parser = argparse.ArgumentParser(
        description="Test the InferForge POST /predict/vlm/callback API."
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="service base url")
    parser.add_argument("--callback-url", required=True,
                        help="result will be POSTed here when the task finishes")
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
        print("image=%s" % args.image)
    else:
        payload = {"url": args.url}
        print("url=%s" % args.url)
    payload["callback_url"] = args.callback_url

    print("POST %s/predict/vlm/callback" % args.host)
    t0 = time.perf_counter()
    try:
        resp = requests.post(
            args.host.rstrip("/") + "/predict/vlm/callback", json=payload,
            headers=_auth_headers(), timeout=args.timeout
        )
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

    print("task_id: %s" % body["data"]["task_id"])
    print("result will be POSTed to %s when the task finishes" % args.callback_url)


if __name__ == "__main__":
    main()
