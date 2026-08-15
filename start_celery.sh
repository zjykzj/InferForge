#!/usr/bin/env bash
# Start the Celery worker for async tasks.
set -euo pipefail

cd "$(dirname "$0")"

exec celery -A celery_app worker --loglevel=info "$@"
