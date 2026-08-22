#!/usr/bin/env bash
# Start the Celery worker for async tasks.
set -euo pipefail

cd "$(dirname "$0")"

# Same multiprocess metrics dir as start.sh: worker metrics are aggregated
# and scraped through the web /metrics endpoint (utils/metrics.py).
export PROMETHEUS_MULTIPROC_DIR="${PROMETHEUS_MULTIPROC_DIR:-$PWD/logs/metrics}"

# --without-gossip: gossip declares a transient non-exclusive queue, which
# RabbitMQ >= 4.3 rejects by default (deprecated feature). The project uses
# none of gossip's features (worker clock sync / revocation propagation);
# control replies already use durable queues via control_queue_durable=True.
exec celery -A celery_app worker --loglevel=info --without-gossip "$@"
