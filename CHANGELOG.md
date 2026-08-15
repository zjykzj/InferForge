# Changelog

All notable changes to this project will be documented in this file.

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
