#!/usr/bin/env bash
# One-command startup for the InferForge service.
set -euo pipefail

cd "$(dirname "$0")"

mkdir -p logs models

# Prometheus multiprocess mode: set BEFORE gunicorn imports the app (the
# client reads this env at its own import). Web and worker share the same
# directory, so worker metrics are scraped through the web /metrics
# endpoint. Unset in dev (`python3 app.py`) -> default in-process registry.
export PROMETHEUS_MULTIPROC_DIR="${PROMETHEUS_MULTIPROC_DIR:-$PWD/logs/metrics}"

if [ ! -f models/yolov8n.onnx ]; then
  echo "[ERROR] models/yolov8n.onnx not found." >&2
  echo "        Export the model (e.g. ultralytics yolov8n) to ONNX and put it into models/." >&2
  exit 1
fi

exec gunicorn -c gunicorn.conf.py app:app "$@"
