# Changelog

All notable changes to this project will be documented in this file.

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
