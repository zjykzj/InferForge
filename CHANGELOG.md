# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added

- Model registry: declarative multi-model config (models/registry.yaml, PyYAML; models/registry.example.yaml shipped) + request-level model routing via the `model` field — sync /predict, /predict/segment, /predict/classify and async /predict/query, /predict/callback accept it; engines/registry.py is pure metadata (lazy parse + process cache, no predictor instances); without a registry file the service synthesizes a single-model registry from the historical INFERFORGE_[SEG_|CLS_]MODEL_PATH env vars (byte-identical behavior, zero-cost upgrade)
- Model registry: per-model class names (optional `classes:` txt per entry; omitted -> built-in COCO-80 / ImageNet-1k); out-of-range class ids degrade to a `class_N` label + warning instead of failing the request (engines.base.class_label, used by draw_detections and the task-layer JSON mapping)
- Model registry: business code 10 (model not found / capability mismatch) registered in utils/response.py + docs/status-codes.md; async submit apis reject unknown models synchronously (validate_model) and workers re-check for web/worker registry drift; defaults derivation fails loudly when a capability has multiple models and no declared default
- Model registry: task layer predictor caches keyed by registered model name (per-capability dict + double-checked locking); /health/ready probes each enabled capability's DEFAULT model; start.sh preflight replaced by scripts/preflight_models.py (enumerates registered models of enabled capabilities, validates YAML at boot; the bash truthy mirror is gone — utils/switches.py is now the single source)
- Metrics: inferforge_predictor_loaded gains a `model` label (predict_phase_seconds stays model-unlabeled — engines don't know their registry name; limitation documented in docs/metrics.md)
- Tooling: scripts gain --model (test_predict*, run_detection/segment/classify, benchmark detect mode); new docs/model-registry.md (format, routing semantics, default derivation, switch relationship, backward compatibility), indexed in docs/README.md
- Warmup: INFERFORGE_PRELOAD=1 startup preload — web startup event (runs per gunicorn worker, after fork) and celery worker_process_init each load the DEFAULT model of the capabilities they serve (web: detect + switch-gated seg/cls; worker: detect only — seg/cls are sync-only); best-effort per capability (a broken model logs and stays 503 via readiness; readiness stays the source of truth); never preloads non-default registered models

## [1.1.0] - 2026-08-24

### Added

- Agent: Pydantic AI orchestration demo (/predict/agent/query, async-only, query-only) — hair-count task: the local detection engine locates persons (detect_persons tool) and the remote LLM agent judges the hair attribute per person into a typed HairCountResult (output_type + Pydantic validation); tasks/agent.py keeps pydantic-ai lazy-imported (worker-only) with a fresh agent/client per task; transport retries configured via AsyncHTTPX2TenacityTransport (429/5xx/connection x3, Retry-After aware — V2 has no built-in HTTP retries); INFERFORGE_AGENT=1 switch (requires INFERFORGE_ASYNC=1); docs/agent.md with the generalization guide
- Agent: tasks/vlm._get_config renamed to get_llm_config (shared by vlm + agent); agent remote calls reuse the vlm remote-call metrics (documented in metrics.md)
- Deps: pydantic-ai-slim[openai,retries]>=2.33,<3.0 (slim package — the full pydantic-ai pulls unrelated provider SDKs); openai pin relaxed to >=3.0,<4.0 (pydantic-ai 2.x requires openai 3.x; vlm API surface verified on 3.3.x by the suite)
- VLM: async image-understanding tasks (/predict/vlm/query, query-only — no sync or callback variant; callback delivery stays with the detection task as the reference implementation) — fixed server-side prompt (INFERFORGE_LLM_PROMPT overrides), remote OpenAI-compatible chat completions via the openai SDK (requirements-async.txt, `>=3.0,<4.0`; worker-only lazy import; SDK-level infra retries max_retries=2); image validated before the paid call (reuses the code 1/2 ladder)
- VLM: business code 9 (upstream LLM failure after SDK retries) registered in utils/response.py + docs/status-codes.md; business errors never retried by the callback (exactly-once holds for code 9)
- VLM: INFERFORGE_LLM=1 switch (requires INFERFORGE_ASYNC=1, warns and skips otherwise); worker env INFERFORGE_LLM_MODEL / INFERFORGE_LLM_API_KEY (required) + INFERFORGE_LLM_BASE_URL (optional); vlm workers are I/O-bound (`-c N`, prefetch_multiplier stays 1)
- VLM: test script (scripts/test_vlm_query.py) and smoke tests (tests/test_vlm.py, test_predict_vlm_query.py); compose gains commented INFERFORGE_LLM_* env examples; docs updated (api.md §8, architecture.md, deployment.md, status-codes.md)
- Config: .env support — app.py and celery_app.py load the project-root .env at import time (python-dotenv, override=False so shell/compose env wins); .env.example template shipped (.env already gitignored)
- Metrics: VLM remote-call latency histogram + remote-error counter + per-task broker queue-wait histogram (submitted_at wall-clock transport kwarg from the 4 submit apis, observed in celery_app task_prerun via utils.metrics.record_queue_wait; same-host assumption, negatives clamped); VLM token usage logged per call; docs/metrics.md synced
- Tooling: scripts/benchmark.py (detect / vlm-direct / vlm-http fixed-concurrency load generator, P50/P95/P99, RPS, outcome distribution, JSON output) + scripts/mock_llm.py (stdlib OpenAI-compatible /v1/chat/completions fake)
- Tooling: scripts/run_detection.py / run_vlm.py / run_agent.py — direct task-layer inference examples (call tasks.* orchestration without the web service, demonstrating the layer's web-independence)
- Docs: benchmark.md — detection + VLM baselines (queue-wait pending a broker environment); indexed in docs/README.md and READMEs
- Docs: stack.md §4 — OpenAI SDK + Pydantic AI (LLM & agents): selection rationale (OpenAI-compatible endpoints, slim package, worker-only), config points (timeouts / SDK + transport retries / client lifetime) and key decisions (lazy import + code 3, code 9 never retried, query-only, I/O-bound `-c N` scaling, shared vlm remote-call metrics); the env-var overview (renumbered to §5) gains INFERFORGE_LLM / INFERFORGE_AGENT and the five INFERFORGE_LLM_* / INFERFORGE_AGENT_INSTRUCTIONS rows
- Docs: READMEs Acknowledgments list Pydantic AI (was OpenAI SDK only; the entry is now "LLM & agents")

### Changed

- Refactor: tasks/detection_callback._post_callback renamed to post_callback (reusable by future async callback tasks; retry constants stay single-sourced; behavior unchanged)

## [1.0.0] - 2026-08-22

### Added

- Metrics: GET /metrics (Prometheus text, not the envelope — documented format exception) — http requests/duration by route template, business-code distribution, inference phase timings, predictor gauge, celery task counters; multiprocess aggregation via PROMETHEUS_MULTIPROC_DIR (start.sh / start_celery.sh / compose)
- Deploy: deploy/docker-compose.monitoring.yml + prometheus.yml — optional Prometheus + Grafana stack (reference artifact, merged with the main compose)
- Docs: metrics.md — metric list, multiprocess mode, monitoring stack usage; api.md gains the /metrics endpoint section
- Auth: optional API-key auth (off unless INFERFORGE_API_KEY is set) — X-API-Key header, constant-time compare, 401 + code=7 envelope (documented protocol exception); probes/docs/metrics paths exempt; test scripts read the env automatically
- Rate limit: optional fixed window (off unless INFERFORGE_RATE_LIMIT=N is set) — 429 + code=8 + Retry-After; buckets keyed by X-API-Key when auth is on, client IP otherwise; per-process memory (multi-worker limits approximate by design, documented)
- CI: GitHub Actions workflow (.github/workflows/ci.yml) — smoke tests + compile check + docs link check on push/PR; READMEs gain a CI badge
- Docs: READMEs About section condensed to three sentences (same four points: what / why a template / layered replaceability / forking contract pointer)
- Docs: READMEs Acknowledgments condensed to name-only links (per-library responsibilities live in stack.md)
- Docs: READMEs gain a hero capability strip (replacing the stale component list) and a Project Layout tree

### Changed

- Docs: terminology sweep — 信封 replaced with envelope across all docs (response envelope / result envelope / envelope 契约); status-codes.md §1 defines the term on first mention
- Docs: terminology sweep II — contract / fallback / watchdog / double-checked locking / sticky / hot reload replace their Chinese renderings (契约 / 兜底 / 看门狗 / 双重检查锁 / 粘性 / 热重载); the forking-contract doc title keeps 分叉契约（Forking Contract）

## [0.5.0] - 2026-08-22

### Changed

- Web framework migrated from Flask to FastAPI (breaking): ASGI serving via gunicorn + uvicorn.workers.UvicornWorker (one-line change in gunicorn.conf.py — process management, logrotate and graceful shutdown unchanged); Pydantic request models with validation failures folded into the 200 + code=1 envelope (FastAPI's 422 never leaks); request_id moved from flask.g to a ContextVar + pure-ASGI middleware; endpoints are sync `def` (threadpool execution for CPU-bound inference)
- Python floor raised to 3.12 (Dockerfile python:3.12-slim; latest fastapi/uvicorn)
- RabbitMQ >= 4.3 compatibility: control_queue_durable=True (pidbox reply queue no longer transient) + --without-gossip in start_celery.sh and compose (gossip's transient queue has no durability knob and its features are unused)

### Added

- OpenAPI docs: GET /docs (Swagger UI) + GET /openapi.json, version read from VERSION
- Request-body guard: Content-Length 20MB ceiling in app.py middleware (200 + code=1 envelope, matches the image download limit)
- Docs: stack.md §1.4 documents the gunicorn-vs-uvicorn decision (differences + when to choose each)
- Docs: deployment.md — canary rollout (nginx traffic split, web grayscale + worker full rollout) and long-term test/prod coexistence (two fully isolated stacks)
- Docs: fastapi-migration.md (Flask → FastAPI comparison and migration impact); docs index reorganized into engineering / tech-stack / standards categories; concepts.md gains a Pydantic primer
- Docs: add-engine.md (mounting a new inference engine — BasePredictor walkthrough, TensorRT/Triton notes, verification checklist) and forking-contract.md (template usage, editable vs stable areas, upstream merge policy)
- Docs: READMEs gain an About section stating the template-not-framework positioning
- Docs: READMEs restructured — Features table dropped (OpenAPI pointer moved into Quick Start), Documentation grouped by category, Acknowledgments condensed to one line per category
- Docs: architecture.md §1 names the architecture style — unidirectional layering + dependency inversion at the engine boundary (composition root / shared kernel / clean-architecture mapping)
- Deploy: deploy/nginx-canary.conf — canary traffic split reference (weight ramp + `X-Canary: 1` header pin, proxy headers, 20MB body match, long-inference read timeout); deploy/README.md marks deploy/ as the reference-artifact area; deployment.md gains §0 (environments / canary / traffic split primer) and §2.3 snippet corrected (weights only split within one upstream group) and points to the file

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
