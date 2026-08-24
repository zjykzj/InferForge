#!/usr/bin/env python3
"""Fixed-concurrency load generator for InferForge performance baselines.

Modes:
  detect     HTTP POST /predict (sync detection, CPU-bound) — needs ./start.sh
  vlm-direct In-process tasks.vlm.run_vlm against INFERFORGE_LLM_BASE_URL —
             measures the image pipeline + remote call latency without
             web/celery (pair with scripts/mock_llm.py)
  vlm-http   Full submit + poll flow on /predict/vlm/query — needs the async
             stack (RabbitMQ + Redis + a worker with INFERFORGE_LLM_* env)

Statistics: latency percentiles use numpy's 'linear' interpolation on sorted
samples; RPS = completed / wall seconds (closed system at fixed concurrency);
outcomes are envelope business codes (HTTP modes) or outcome tags (direct).

Usage:
    python3 scripts/benchmark.py --mode detect --image assets/bus.jpg \
        --concurrency 4 --requests 100
    INFERFORGE_LLM_MODEL=m INFERFORGE_LLM_API_KEY=k \
    INFERFORGE_LLM_BASE_URL=http://127.0.0.1:8001/v1 \
    python3 scripts/benchmark.py --mode vlm-direct --image assets/bus.jpg \
        --concurrency 4 --requests 30
"""
import argparse
import base64
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

# vlm-direct imports tasks.vlm (project-root import, mirrors celery_app.py).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_HOST = "http://localhost:8000"

TERMINAL_CODES = (0, 1, 2, 3, 9)  # vlm query terminal states (4=not found, 5=pending)


def _auth_headers():
    """Attach X-API-Key when INFERFORGE_API_KEY is set (see utils/auth.py)."""
    key = os.environ.get("INFERFORGE_API_KEY")
    return {"X-API-Key": key} if key else None


def percentile(sorted_values, p):
    """numpy 'linear' method on pre-sorted samples: index=(n-1)*p/100, interpolate."""
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    idx = (n - 1) * p / 100.0
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac


def _run(once, count, concurrency):
    """Run once() count times at fixed concurrency; (latencies, outcomes, wall_seconds).

    All futures are submitted up-front (closed system); wall time is dispatch
    start -> last completion.
    """
    latencies, codes = [], {}
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(once) for _ in range(count)]
        for fut in as_completed(futures):
            latency, outcome = fut.result()
            latencies.append(latency)
            codes[outcome] = codes.get(outcome, 0) + 1
    return latencies, codes, time.perf_counter() - started


def summarize(mode, concurrency, requests, latencies, codes, wall_seconds):
    """Build the stats dict shared by all modes."""
    completed = len(latencies)
    sorted_lat = sorted(latencies)
    return {
        "mode": mode,
        "concurrency": concurrency,
        "requests": requests,
        "completed": completed,
        "errors": requests - completed,
        "wall_seconds": round(wall_seconds, 3),
        "rps": round(completed / wall_seconds, 2) if wall_seconds > 0 else 0.0,
        "latency": {
            "mean": round(sum(sorted_lat) / completed, 4) if completed else None,
            "min": round(sorted_lat[0], 4) if completed else None,
            "max": round(sorted_lat[-1], 4) if completed else None,
            "p50": round(percentile(sorted_lat, 50), 4) if completed else None,
            "p95": round(percentile(sorted_lat, 95), 4) if completed else None,
            "p99": round(percentile(sorted_lat, 99), 4) if completed else None,
        },
        "codes": codes,
    }


def _print_stats(stats):
    lat = stats["latency"]
    print("\n===== benchmark: %s (concurrency=%d, requests=%d) =====" % (
        stats["mode"], stats["concurrency"], stats["requests"]))
    print("completed: %d | errors: %d | wall: %.2fs | rps: %.2f" % (
        stats["completed"], stats["errors"], stats["wall_seconds"], stats["rps"]))
    print("latency(s): mean=%s min=%s max=%s p50=%s p95=%s p99=%s" % (
        lat["mean"], lat["min"], lat["max"], lat["p50"], lat["p95"], lat["p99"]))
    print("outcomes: %s" % json.dumps(stats["codes"], sort_keys=True))


def _benchmark_detect(args, payload_b64):
    payload = {"image": payload_b64}
    url = args.host.rstrip("/") + "/predict"

    def once():
        t0 = time.perf_counter()
        try:
            resp = requests.post(url, json=payload, headers=_auth_headers(),
                                 timeout=args.timeout)
        except requests.RequestException:
            return time.perf_counter() - t0, "connection_error"
        latency = time.perf_counter() - t0
        if resp.status_code != 200:
            return latency, "http_error_%d" % resp.status_code
        try:
            body = resp.json()
        except ValueError:
            return latency, "bad_json"
        return latency, str(body.get("code", "?"))

    for _ in range(args.warmup):  # discarded: lazy model load per worker
        once()
    return _run(once, args.requests, args.concurrency)


def _benchmark_vlm_direct(args, payload_b64):
    from tasks.vlm import LLMConfigError, LLMUpstreamError, run_vlm

    missing = [v for v in ("INFERFORGE_LLM_MODEL", "INFERFORGE_LLM_API_KEY")
               if not os.environ.get(v)]
    if missing:
        print("[ERROR] vlm-direct needs: %s (and optionally INFERFORGE_LLM_BASE_URL)"
              % ", ".join(missing))
        sys.exit(2)

    def once():
        t0 = time.perf_counter()
        try:
            run_vlm(image_b64=payload_b64)
            outcome = "ok"
        except LLMUpstreamError:
            outcome = "llm_error"
        except LLMConfigError:
            outcome = "config_error"
        except Exception:
            outcome = "error"
        return time.perf_counter() - t0, outcome

    for _ in range(args.warmup):
        once()
    return _run(once, args.requests, args.concurrency)


def _benchmark_vlm_http(args, payload_b64):
    payload = {"image": payload_b64}
    base = args.host.rstrip("/")
    submit_url = base + "/predict/vlm/query"

    def once():
        t0 = time.perf_counter()
        try:
            resp = requests.post(submit_url, json=payload, headers=_auth_headers(),
                                 timeout=args.timeout)
        except requests.RequestException:
            return time.perf_counter() - t0, "submit_connection_error"
        if resp.status_code != 200:
            return time.perf_counter() - t0, "http_error_%d" % resp.status_code
        try:
            task_id = resp.json()["data"]["task_id"]
        except (ValueError, KeyError, TypeError):
            return time.perf_counter() - t0, "bad_submit_response"
        poll_url = base + "/predict/vlm/query/" + task_id
        for _ in range(args.max_attempts):
            time.sleep(args.poll_interval)
            try:
                body = requests.get(poll_url, headers=_auth_headers(),
                                    timeout=args.timeout).json()
            except (requests.RequestException, ValueError):
                continue
            code = body.get("code")
            if code in TERMINAL_CODES:
                return time.perf_counter() - t0, str(code)
        return time.perf_counter() - t0, "poll_timeout"

    for _ in range(args.warmup):
        once()
    return _run(once, args.requests, args.concurrency)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Fixed-concurrency load generator for InferForge baselines."
    )
    parser.add_argument("--mode", required=True,
                        choices=("detect", "vlm-direct", "vlm-http"))
    parser.add_argument("--image", required=True, help="local image path (sent as base64)")
    parser.add_argument("--host", default=DEFAULT_HOST,
                        help="service base url [detect, vlm-http]")
    parser.add_argument("--concurrency", type=int, default=4, help="parallel workers")
    parser.add_argument("--requests", type=int, default=100, help="measured requests")
    parser.add_argument("--warmup", type=int, default=2,
                        help="discarded warmup calls (one per web worker: lazy model load)")
    parser.add_argument("--timeout", type=float, default=30.0,
                        help="per-request timeout in seconds")
    parser.add_argument("--poll-interval", type=float, default=0.5,
                        help="seconds between polls [vlm-http]")
    parser.add_argument("--max-attempts", type=int, default=600,
                        help="max poll attempts before giving up [vlm-http]")
    parser.add_argument("--output", default=None, help="write stats JSON to this path")
    return parser.parse_args()


def main():
    args = parse_args()
    with open(args.image, "rb") as f:
        payload_b64 = base64.b64encode(f.read()).decode("utf-8")

    if args.mode == "detect":
        latencies, codes, wall = _benchmark_detect(args, payload_b64)
    elif args.mode == "vlm-direct":
        latencies, codes, wall = _benchmark_vlm_direct(args, payload_b64)
    else:
        latencies, codes, wall = _benchmark_vlm_http(args, payload_b64)

    stats = summarize(args.mode, args.concurrency, args.requests, latencies, codes, wall)
    _print_stats(stats)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)
        print("stats written -> %s" % args.output)


if __name__ == "__main__":
    main()
