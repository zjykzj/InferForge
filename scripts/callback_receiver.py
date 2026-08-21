#!/usr/bin/env python3
"""Callback receiver for testing POST /predict/callback.

Runs a small HTTP server that accepts result callbacks: prints a detection
summary and saves the full payload plus the drawn image.

Usage:
    python3 scripts/callback_receiver.py                          # listen on :9000
    python3 scripts/callback_receiver.py --port 9100 --save-dir /tmp/cb
"""
import argparse
import base64
import json
import logging
import os
import time
from typing import Any, Dict, Optional

from fastapi import Body, FastAPI
from fastapi.responses import PlainTextResponse

logger = logging.getLogger("callback_receiver")

SAVE_DIR = None


def _handle(payload: Dict[str, Any]) -> str:
    ts = time.strftime("%Y%m%d_%H%M%S")
    code = payload.get("code", -1)
    message = payload.get("message", "")
    data = payload.get("data") or {}

    logger.info("callback received: code=%s message=%s", code, message)
    if code != 0:
        logger.warning("task failed with code=%s — nothing to save", code)
        return "ok"

    detections = data.get("detections", [])
    logger.info("detections: %d", len(detections))
    for det in detections:
        logger.info("  %-15s conf=%.2f bbox=%s",
                    det["class"], det["confidence"], det["bbox"])

    json_path = os.path.join(SAVE_DIR, "callback_%s.json" % ts)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    img_b64 = data.get("image")
    if img_b64:
        img_path = os.path.join(SAVE_DIR, "callback_%s.jpg" % ts)
        with open(img_path, "wb") as f:
            f.write(base64.b64decode(img_b64))

    logger.info("saved -> %s", json_path)
    return "ok"


app = FastAPI()


@app.post("/result")
@app.post("/{path:path}")
def receive(path: str = "", payload: Optional[Dict[str, Any]] = Body(default=None)):
    return PlainTextResponse(_handle(payload or {}))


def main():
    global SAVE_DIR
    parser = argparse.ArgumentParser(description="Receive InferForge /predict/callback results.")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--save-dir", default="outputs/callbacks")
    args = parser.parse_args()

    SAVE_DIR = os.path.abspath(args.save_dir)
    os.makedirs(SAVE_DIR, exist_ok=True)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
    logger.info("callback receiver listening on :%d, saving to %s", args.port, SAVE_DIR)

    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=args.port, log_config=None)


if __name__ == "__main__":
    main()
