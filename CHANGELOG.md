# Changelog

All notable changes to this project will be documented in this file.

## [0.4.0] - 2026-08-21

### Added

- Health probe endpoints: GET /health (liveness, always 200) and GET /health/ready (readiness, 503 + code 6 until the predictor is loaded) — the only endpoints that carry meaning in the HTTP status, for orchestrator probes
- Docker Compose full stack: Dockerfile + docker-compose.yml (web + worker + RabbitMQ + Redis) — one-command containerized startup; the model is bind-mounted from ./models, never baked into the image

### Changed

- Async is one deployment shape: INFERFORGE_ASYNC=1 registers both async apis (callback + query, requires celery + rabbitmq + redis) — callback vs query is now a per-request choice, not a deployment choice (breaking)
- INFERFORGE_QUERY=1 kept as a deprecated alias with a startup warning; requirements-query.txt removed, redis merged into requirements-async.txt (breaking)

## [0.3.0] - 2026-08-15

### Added

- Async query API: POST /predict/query + GET /predict/query/<task_id> via Celery + RabbitMQ + Redis — submit a task, poll for the result
- Redis result store (utils/redis_store.py): pending marker with SET NX, result envelope, TTL expiry (INFERFORGE_RESULT_TTL, default 3600s)
- INFERFORGE_QUERY=1 env switch to register the query api on top of INFERFORGE_ASYNC=1; requirements-query.txt (redis) split from requirements-async.txt
- Business codes 4 (task not found) and 5 (task pending), registered in utils/response.py and docs/status-codes.md
- API test client: scripts/test_predict_query.py (submit + poll, --save option)
- Docs: concepts guide (web serving, task queues, callback vs polling, Redis)

### Changed

- READMEs: features table reordered (sync first), acknowledgments rewritten as compact grouped lines, test count 30+; README_zh.md renamed to README.zh-CN.md
- Test suite: 33 smoke tests (16 new for the query api)

## [0.2.0] - 2026-08-15

### Added

- Async detection API: POST /predict/callback via Celery + RabbitMQ — submit a task, result POSTed to callback_url
- Callback exactly-once semantics: business errors are not retried; network failures retry with exponential backoff (3 attempts)
- Per-request tracing: request_id travels with the task, worker logs carry request_id + task_id
- Process-group log files: web -> app.log, worker -> celery.log; rotation via system logrotate (deploy/logrotate.conf)
- INFERFORGE_ASYNC=1 env switch to enable async blueprints explicitly
- API test clients: test_predict.py / test_predict_callback.py / callback_receiver.py
- Docs: quick-start, stack, security; README features table and badges

## [0.1.0] - 2026-08-15

### Added

- Flask/Gunicorn synchronous detection service: POST /predict (base64 / URL input)
- YOLOv8n ONNX engine with self-written letterbox / decode / NMS / drawing
- Layered architecture (apis / tasks / engines / utils) with one-way dependencies
- Business status codes {code, message, data} — HTTP always 200
- Per-request trace id in logs and X-Request-ID response header
- JSON file logging with daily rotation
- Smoke tests (FakePredictor, no model file required)
- API test client (scripts/test_api.py)
- Docs: architecture, api, status-codes, logging, testing
