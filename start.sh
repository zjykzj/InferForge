#!/usr/bin/env bash
# One-command startup for the InferForge service.
set -euo pipefail

cd "$(dirname "$0")"

mkdir -p logs models

if [ ! -f models/yolov8n.onnx ]; then
  echo "[ERROR] models/yolov8n.onnx not found." >&2
  echo "        Export the model (e.g. ultralytics yolov8n) to ONNX and put it into models/." >&2
  exit 1
fi

exec gunicorn -c gunicorn.conf.py app:app "$@"
