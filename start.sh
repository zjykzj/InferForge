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

# Check the registered model files for the enabled capabilities only
# (detection is always on; segment/classify behind their env switches).
# The registry YAML is parsed here too, so config typos fail at boot.
python3 scripts/preflight_models.py

exec gunicorn -c gunicorn.conf.py app:app "$@"
