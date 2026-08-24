#!/usr/bin/env python3
"""Stdlib OpenAI-compatible /v1/chat/completions fake for local VLM benchmarking.

    python3 scripts/mock_llm.py --port 8001 --delay 1.0

Then point the service at it (e.g. via .env):
    INFERFORGE_LLM_BASE_URL=http://127.0.0.1:8001/v1

Routes ANY path ending in /chat/completions (the openai SDK with
base_url=http://127.0.0.1:8001/v1 POSTs to /v1/chat/completions). The
response body is the full ChatCompletion shape the SDK validates — the
`created` field is REQUIRED (missing fields raise a validation error that
would masquerade as a code-9 upstream failure).
"""
import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RESPONSE_BODY = {
    "id": "mock-1",
    "object": "chat.completion",
    "created": 1750000000,  # REQUIRED by openai's ChatCompletion model
    "model": "mock-model",
    "choices": [{
        "index": 0,
        "message": {"role": "assistant", "content": "mock answer"},
        "finish_reason": "stop",  # REQUIRED Literal
    }],
    "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
}


class _Handler(BaseHTTPRequestHandler):
    delay = 1.0  # class attr: set once from argparse before serve_forever()

    def do_POST(self):
        if not self.path.endswith("/chat/completions"):
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        json.loads(self.rfile.read(length) or b"{}")  # validate, ignore
        time.sleep(self.delay)
        body = json.dumps(RESPONSE_BODY).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence per-request logs under load
        pass


class _Server(ThreadingHTTPServer):
    daemon_threads = True  # clean Ctrl-C


def parse_args():
    parser = argparse.ArgumentParser(
        description="Local OpenAI-compatible chat completions fake for VLM benchmarking."
    )
    parser.add_argument("--port", type=int, default=8001, help="listen port")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="fixed seconds of latency per request (simulates the remote LLM)")
    return parser.parse_args()


def main():
    args = parse_args()
    _Handler.delay = args.delay
    server = _Server(("127.0.0.1", args.port), _Handler)
    print("mock llm listening on http://127.0.0.1:%d/v1/chat/completions (delay=%.2fs)"
          % (args.port, args.delay))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
