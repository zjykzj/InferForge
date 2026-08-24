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

# Check the model files for the enabled capabilities only (detection is
# always on; segment/classify behind their env switches). The truthy set
# mirrors utils/switches.py (lowercased).
_on() { case "${1,,}" in 1|true|yes) return 0 ;; *) return 1 ;; esac; }

MODEL_FILES="models/yolov8n.onnx"
if _on "$INFERFORGE_SEG"; then MODEL_FILES="$MODEL_FILES models/yolov8n-seg.onnx"; fi
if _on "$INFERFORGE_CLS"; then MODEL_FILES="$MODEL_FILES models/yolov8n-cls.onnx"; fi

for f in $MODEL_FILES; do
  if [ ! -f "$f" ]; then
    echo "[ERROR] $f not found." >&2
    echo "        Export the model (e.g. ultralytics yolov8n) to ONNX and put it into models/." >&2
    exit 1
  fi
done

exec gunicorn -c gunicorn.conf.py app:app "$@"
