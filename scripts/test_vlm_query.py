#!/usr/bin/env python3
"""Manual API testing client for POST /predict/vlm/query + GET /predict/vlm/query/<task_id> (async VLM polling).

Usage:
    python3 scripts/test_vlm_query.py --image assets/bus.jpg
    python3 scripts/test_vlm_query.py --image assets/bus.jpg --save answer.txt
    python3 scripts/test_vlm_query.py --url https://ultralytics.com/images/bus.jpg \
        --max-attempts 120 --poll-interval 0.5
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
        description="Test the InferForge POST + GET /predict/vlm/query API."
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="service base url")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--image", help="local image path (sent as base64)")
    source.add_argument("--url", help="remote image url (sent as url)")
    parser.add_argument("--save", default=None, help="save the answer text to this path")
    parser.add_argument("--timeout", type=float, default=30.0, help="request timeout in seconds")
    parser.add_argument("--poll-interval", type=float, default=1.0,
                        help="seconds between polls")
    parser.add_argument("--max-attempts", type=int, default=60,
                        help="max poll attempts before giving up")
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

    print("POST %s/predict/vlm/query" % args.host)
    t0 = time.perf_counter()
    try:
        resp = requests.post(
            args.host.rstrip("/") + "/predict/vlm/query", json=payload,
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

    task_id = body["data"]["task_id"]
    print("task_id: %s" % task_id)

    poll_url = args.host.rstrip("/") + "/predict/vlm/query/" + task_id
    body = None
    for attempt in range(1, args.max_attempts + 1):
        time.sleep(args.poll_interval)
        resp = requests.get(poll_url, headers=_auth_headers(), timeout=args.timeout)
        body = resp.json()
        print("[attempt %d] code: %d | message: %s" % (attempt, body["code"], body["message"]))
        if body["code"] in (0, 1, 2, 3, 9):  # terminal states
            break
    else:
        print("still processing after %d attempts — is the worker running? (./start_celery.sh)"
              % args.max_attempts)
        sys.exit(1)

    if body["code"] != 0:
        sys.exit(1)

    answer = body["data"]["answer"]
    print("model: %s" % body["data"]["model"])
    print("answer:\n%s" % answer)

    if args.save:
        with open(args.save, "w", encoding="utf-8") as f:
            f.write(answer)
        print("saved answer -> %s" % args.save)


if __name__ == "__main__":
    main()
