# CLAUDE.md

## Project Overview

InferForge is an algorithm-agnostic inference-serving project template — a serving shell above inference kernels, forging any model (CV → LLM → Agent) into production.

Layers:

- `apis/` + `app.py` — interface layer: FastAPI routers (sync + optional async), Pydantic input validation, unified responses
- `tasks/` + `celery_app.py` — task layer: orchestration; each task owns its predictors (lazy loading); celery tasks run via RabbitMQ
- `engines/` — engine layer: `BasePredictor` contract + YOLOv8n implementation
- `utils/` — cross-cutting: logging, image conversion, response format, request_id

## Architecture Constraints

Authoritative details live in [docs/architecture.md](docs/architecture.md); the hard rules that affect every edit:

- One-way dependency chain: `app -> apis -> tasks -> engines`. No reverse imports.
- `utils/` is cross-cutting — usable by any layer, must not depend on business layers.
- `BasePredictor` (`engines/base.py`) is the only stable contract. Swapping an algorithm touches `engines/` only.
- Tasks own their predictors; the API layer never touches them.
- HTTP always returns 200; business status in `{code, message, data}` (see docs/status-codes.md). Pydantic validation failures must fold into the envelope via `utils.response.validation_error_handler` (code=1) — FastAPI's default 422 must never leak.
- Engine pre/post processing is self-written — never import ultralytics (AGPL-3.0).

## Development Commands

```bash
pytest tests/ -v                                    # smoke tests (no model file needed)
python3 app.py                                      # dev server (uvicorn single process, no model check)
./start.sh                                          # run service (requires models/yolov8n.onnx)
INFERFORGE_ASYNC=1 ./start.sh                       # run service with the async apis (callback + query)
./start_celery.sh                                   # run async worker (requires RabbitMQ + celery)
docker compose up -d                                # full stack in containers (needs models/yolov8n.onnx)
python3 scripts/test_predict.py --image assets/bus.jpg          # test the sync API
python3 scripts/test_predict_callback.py --image assets/bus.jpg \  # test the async callback API
  --callback-url http://localhost:9000/result
python3 scripts/test_predict_query.py --image assets/bus.jpg     # test the async query API
python3 scripts/callback_receiver.py                # receive async results (saves to outputs/callbacks/)
python3 -m py_compile app.py apis/*.py tasks/*.py engines/*.py utils/*.py tests/*.py scripts/*.py
```

## Critical Details

- onnxruntime is imported **inside** `YoloPredictor.load()` on purpose — tests must stay model-free. Do not move it to module level.
- Tests inject `FakePredictor` by monkeypatching `tasks.detection.get_predictor`; never load a real model or hit the network in tests.
- Test apps are built via the `conftest.app_factory` fixture (RequestIdMiddleware + MetricsMiddleware + validation handler + metrics router, one router per test) or `create_app()` — never register the validation handler twice.
- Python floor is 3.12 (conda env `py312`); `X | None` syntax is allowed.
- API endpoints are plain `def` (FastAPI threadpool) — the inference path is CPU-bound blocking; never async/await around predictor calls. Don't spawn raw `threading.Thread` in endpoints (request_id ContextVar propagates via anyio's threadpool only).
- request_id flows via `utils.request_id.RequestIdMiddleware` (ContextVar + X-Request-ID header on every response); workers fall back to the request_id in task kwargs.
- Metrics live in `utils/metrics.py` (cross-cutting). `/metrics` returns raw Prometheus text — NOT the envelope (format exception, see docs/status-codes.md). `MetricsMiddleware` reads `scope['route']` lazily in the response phase (routing fills it after middleware entry).
- `PROMETHEUS_MULTIPROC_DIR` must be set before the app imports (start.sh / start_celery.sh / compose do this); web and worker must point at the **same** directory — worker metrics are scraped through web's `/metrics`. Unset (dev `python3 app.py`) → default in-process registry.
- Auth is off unless `INFERFORGE_API_KEY` is set (read at middleware construction). Enforced paths get HTTP 401 + code=7 envelope; exempt paths: `/health`, `/health/ready`, `/metrics`, `/docs`, `/openapi.json`. Middleware order in `app.py`/conftest: **last added = outermost** — RequestId must stay outermost.
- Rate limit is off unless `INFERFORGE_RATE_LIMIT=N` is set (fixed window, 429 + code=8 + Retry-After; buckets keyed by X-API-Key when auth is on, else client IP). Buckets are per-process memory — multi-worker limits are approximate by design (documented); strict limits need shared storage (Redis).
- CI (`.github/workflows/ci.yml`) runs pytest + py_compile + docs link check on push/PR — tests stay model-free and network-free so CI needs no artifacts or services.
- New business codes must be registered in **both** `utils/response.py` docstring and `docs/status-codes.md`.
- Gitignored: `models/*.onnx`, `logs/`, `outputs/`, `result*.jpg`/`result*.json`, `archive/` (old design docs — leave untouched).
- Celery/redis are optional: async is one deployment shape behind `INFERFORGE_ASYNC=1` — it registers both async apis (callback + query; requires celery + rabbitmq + redis). `INFERFORGE_QUERY=1` is a deprecated alias (logs a warning). Missing deps log a warning and skip the whole async mode. Async task modules use `shared_task` (never import celery_app from tasks — circular import). `celery_app.py` must keep its unconditional sys.path insert — the celery CLI temporarily removes cwd from sys.path.
- Callback fires exactly once: detection business errors (code 1/2/3) are NOT retried — only network failures on the callback POST retry (3 attempts, exponential backoff). Keep it that way.
- Log rotation belongs to system logrotate (copytruncate, `deploy/logrotate.conf`) — do not reintroduce in-app rotation handlers (multi-process rotation races).
- The compose stack bind-mounts `./models` and `./logs` — put yolov8n.onnx in `models/` first; the Docker image never bakes the model. In-container broker/redis urls are overridden in `docker-compose.yml` (the localhost defaults won't work).
- Docs language: `docs/` in Chinese, READMEs bilingual. Docs describe current implementation only — no version planning.

## Git Operations

Git workflows are defined as project skills. Use the corresponding skill for each task:

- **`/commit`** — commit message format, `Co-Authored-By` line, and conventional commit types. Invoke for every `git commit`.
- **`/release`** — version bump checklist, version bump commit, annotated tag, push, and GitHub Release body template. Invoke when publishing a new release.

### AI Model Configuration

The AI model used in this project is **DeepSeek-V4-Pro**. Configured in skills as:

```
{{AI_MODEL_NAME}} = DeepSeek-V4-Pro
{{AI_MODEL_EMAIL}} = noreply@deepseek.com
```

### Release Configuration

Version bump locations for this project:

| # | File | Field |
|---|------|-------|
| 1 | `VERSION` | `0.3.0` single line |
| 2 | `CHANGELOG.md` | `## [0.3.0] - YYYY-MM-DD` section header |

Verify with: `grep -n "0.3.0" VERSION CHANGELOG.md`

Repository URL for the `/release` skill:

```
{{REPO_URL}} = https://github.com/zjykzj/InferForge
```
