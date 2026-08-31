# CLAUDE.md

## Project Overview

InferForge is an algorithm-agnostic inference-serving project template — a serving shell above inference kernels, forging any model (CV → LLM → Agent) into production.

Layers:

- `apis/` + `app.py` — interface layer: FastAPI routers (sync + optional async), Pydantic input validation, unified responses
- `tasks/` + `celery_app.py` — task layer: orchestration; each task owns its predictors (lazy loading); celery tasks run via RabbitMQ; VLM tasks own a remote LLM client instead of a local predictor
- `engines/` — engine layer: `BasePredictor` contract + YOLOv8n implementation
- `utils/` — cross-cutting: logging, image conversion, response format, request_id, metrics, auth, rate limit

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
INFERFORGE_ASYNC=1 INFERFORGE_LLM=1 ./start.sh      # + vlm apis (worker needs INFERFORGE_LLM_MODEL/API_KEY)
./start_celery.sh                                   # run async worker (requires RabbitMQ + celery)
docker compose up -d                                # full stack in containers (needs models/yolov8n.onnx)
python3 scripts/test_sync_detect.py --image assets/bus.jpg          # test the sync API
python3 scripts/test_async_detect_callback.py --image assets/bus.jpg \  # test the async callback API
  --callback-url http://localhost:9000/result
python3 scripts/test_async_detect_query.py --image assets/bus.jpg     # test the async query API
python3 scripts/test_async_vlm_query.py --image assets/bus.jpg         # test the vlm query API (vlm/agent are query-only)
python3 scripts/callback_receiver.py                # receive async results (saves to outputs/callbacks/)
python3 scripts/run_detection.py --image assets/bus.jpg          # task layer directly, no web (sync detection)
INFERFORGE_LLM_MODEL=m INFERFORGE_LLM_API_KEY=k \
python3 scripts/run_vlm.py --image assets/bus.jpg                # task layer directly, no web (vlm)
INFERFORGE_LLM_MODEL=m INFERFORGE_LLM_API_KEY=k \
python3 scripts/run_agent.py --image assets/zidane.jpg           # task layer directly, no web (agent)
python3 scripts/benchmark.py --mode detect --image assets/bus.jpg --concurrency 4 --requests 100   # load test /predict
python3 scripts/mock_llm.py --delay 0.1             # local OpenAI-compatible fake for vlm benchmarking
INFERFORGE_ASYNC=1 INFERFORGE_AGENT=1 ./start.sh    # + agent apis (hair-count demo; worker needs INFERFORGE_LLM_* + the model)
python3 scripts/test_async_detect_query.py --image assets/zidane.jpg   # submit + poll the hair-count result
INFERFORGE_SEG=1 ./start.sh                        # + sync segment api (needs models/yolov8n-seg.onnx)
INFERFORGE_CLS=1 ./start.sh                        # + sync classify api (needs models/yolov8n-cls.onnx)
python3 scripts/test_sync_segment.py --image assets/bus.jpg    # test the sync segment API
python3 scripts/test_sync_classify.py --image assets/bus.jpg   # test the sync classify API
python3 scripts/run_segment.py --image assets/bus.jpg             # task layer directly, no web (segment)
python3 scripts/run_classify.py --image assets/bus.jpg            # task layer directly, no web (classify)
python3 -m py_compile app.py apis/*.py tasks/*.py engines/*.py utils/*.py tests/*.py scripts/*.py
```

## Critical Details

- onnxruntime is imported **inside** `YoloPredictor.load()` on purpose — tests must stay model-free. Do not move it to module level.
- Sync segment/classify are opt-in capabilities (`INFERFORGE_SEG=1` / `INFERFORGE_CLS=1`, off by default, independent of the async stack; detection is always on). Switches gate which HTTP routes exist — they do NOT pick models (that's the registry's job, see the registry bullet). Segment returns the overlay JPEG + one full-image binary-mask PNG per instance (large JSON on dense scenes — documented caveat); classify returns top-5 text, no image. The segment engine decodes the two-output head `(1,116,8400)` + `(1,32,160,160)` with shape-based output discovery (`find_seg_outputs` — docstring flags dynamic-axis fallback); all pre/post self-written, no ultralytics import. The ImageNet-1k table in `engines/imagenet_classes.py` must stay 1000 entries in standard order (matches the exported yolov8n-cls training set). Metrics `predict_phase_seconds` carries a `task` label (detect/segment/classify); `predictor_loaded` carries `task` + `model` (registered model name; empty string for non-registry callers). `observe_phase` / `mark_predictor_loaded` default to `task="detect"` so detection call sites are unchanged. `predict_phase_seconds` deliberately has NO model label — engines report phases and don't know their registry name (documented limitation). New engines are registry-ready (no model path in constructors; `load(path)` injects it).
- Model registry (`engines/registry.py` + `models/registry.yaml`, see docs/model-registry.md): pure METADATA — never holds predictors or loads weights; predictor caches stay in the task layer (`_predictors` dict keyed by registered model name, one lock per capability). Parsed lazily on first use and cached per process (NOT at import time — same reason as `get_llm_config`; `reset_cache()` is the test seam, and `conftest.py` has an autouse fixture pointing `INFERFORGE_REGISTRY_PATH` at a per-test tmp registry so dev-machine `models/registry.yaml` can't leak in). No registry file → synthesizes a single-model registry from `INFERFORGE_[SEG_|CLS_]MODEL_PATH` (historical defaults) — byte-identical behavior, zero-cost upgrade. Explicit `INFERFORGE_REGISTRY_PATH` pointing at a missing file → hard `RegistryConfigError` at load. A capability with multiple models and no `defaults` entry → parse-time error (dict order never picks the default). Request routing: `model` field (absent → capability default), unknown name or wrong capability → code 10. Errors live in `utils/errors.py` (`ModelNotFound` — NOT a ValueError subclass, or the routers' `except ValueError` would swallow it into code 1; `RegistryConfigError` → code 3). Async submit apis call `detection.validate_model` so code 10 is returned synchronously; workers re-check for web/worker registry drift. `/health/ready` probes each enabled capability's DEFAULT model only (all-models-ready would keep the service perpetually 503). start.sh preflight is `scripts/preflight_models.py` (registered models of enabled capabilities must exist on disk; utils.switches.py is the single truthy source — no bash mirror).
- Tests inject `FakePredictor` by monkeypatching `tasks.detection.get_predictor` (now `lambda model=None: FakePredictor()` — the seam takes the resolved model name); never load a real model or hit the network in tests. Registry paths in test registries never need to exist on disk (only `load()` opens them).
- Test apps are built via the `conftest.app_factory` fixture (request-id + auth + rate-limit + metrics middleware, validation handler, metrics router — mirrors `create_app()`'s wiring, one router per test) or `create_app()` — never register the validation handler twice.
- Python floor is 3.12 (conda env `py312`); `X | None` syntax is allowed.
- API endpoints are plain `def` (FastAPI threadpool) — the inference path is CPU-bound blocking; never async/await around predictor calls. Don't spawn raw `threading.Thread` in endpoints (request_id ContextVar propagates via anyio's threadpool only).
- request_id flows via `utils.request_id.RequestIdMiddleware` (ContextVar + X-Request-ID header on every response); workers fall back to the request_id in task kwargs.
- Metrics live in `utils/metrics.py` (cross-cutting). `/metrics` returns raw Prometheus text — NOT the envelope (format exception, see docs/status-codes.md). `MetricsMiddleware` reads `scope['route']` lazily in the response phase (routing fills it after middleware entry).
- `PROMETHEUS_MULTIPROC_DIR` must be set before the app imports (start.sh / start_celery.sh / compose do this); web and worker must point at the **same** directory — worker metrics are scraped through web's `/metrics`. Unset (dev `python3 app.py`) → default in-process registry. prometheus_client never deletes dead processes' metric files: `utils.metrics.mark_process_dead()` (no-op without the env) deletes `*_{pid}.db` by glob — do NOT use prometheus_client's own `mark_process_dead` (<=0.26 only removes live-mode gauges, misses gauge_all/counter/histogram). Wired (all empirically verified) in: app.py lifespan shutdown (each gunicorn/uvicorn worker's runtime files), gunicorn.conf.py `on_exit` (master's import-time files — preload_app makes the master import metrics without ever serving), celery_app `worker_shutdown` (main process) + `worker_process_shutdown` (prefork children), and scripts/preflight_models.py un-sets the env before project imports (creates no files). NEVER use gunicorn's `worker_exit` hook: uvicorn workers reset SIGTERM/SIGINT to SIG_DFL (uvicorn #894) and never reach gunicorn's worker_exit finally (verified 3×). SIGKILL/crash of the master leaves stale files (old-schema labels included) — deploy hygiene: clean the dir on full-stack redeploy (both sides down; docs/metrics.md §3).
- Auth is off unless `INFERFORGE_API_KEY` is set (read at middleware construction). Enforced paths get HTTP 401 + code=7 envelope; exempt paths: `/health`, `/health/ready`, `/metrics`, `/docs`, `/openapi.json`. Middleware order in `app.py`/conftest: **last added = outermost** — RequestId must stay outermost.
- Rate limit is off unless `INFERFORGE_RATE_LIMIT=N` is set (fixed window, 429 + code=8 + Retry-After; buckets keyed by X-API-Key when auth is on, else client IP). Buckets are per-process memory — multi-worker limits are approximate by design (documented); strict limits need shared storage (Redis).
- CI (`.github/workflows/ci.yml`) runs pytest + py_compile + docs link check on push/PR — tests stay model-free and network-free so CI needs no artifacts or services.
- New business codes must be registered in **both** `utils/response.py` docstring and `docs/status-codes.md`.
- `.env` at the project root is loaded at import time by `app.py` and `celery_app.py` (python-dotenv, `override=False` — shell/compose env wins; explicit file path, not cwd-relative). It must run BEFORE project imports because `INFERFORGE_LLM_PROMPT` is read at module import (model paths are now read lazily via the registry's env fallback). Tests don't load dotenv (conftest bypasses app.py); `test_app.py`'s `no_async_switch` fixture deletes the capability vars so a dev `.env` can't leak into `create_app()` tests.
- Queue-wait metric: the 4 async submit apis stamp `.delay()` kwargs with `submitted_at=time.time()` (wall clock — crosses the web→worker process boundary; perf_counter doesn't). `celery_app.task_prerun` calls `utils.metrics.record_queue_wait(task.name, task.request.kwargs)`; NOT `task_received` (fires at fetch, after broker queue time). `task.request` is a celery `Context`, not a dict — `task.request.kwargs.get`, never `task.request.get`. NEVER import celery_app in tests: celery's `current_app` is thread-local, so the import splits task-proxy resolution across TestClient threads and silently breaks task monkeypatching (keep queue-wait logic in utils/metrics.py, which is what tests target).
- VLM remote metrics live in `tasks/vlm.py` `_call_remote_llm`: latency observed on success, error counter only on `OpenAIError` (empty content is a quality anomaly, not a remote failure); token usage logged via getattr-guarded `resp.usage` (test fakes lack it). Histogram buckets are explicit (defaults cap at 10s). Benchmark scripts are not unit-tested (CI py_compiles them); baseline data lives in docs/benchmark.md.
- Agent (`INFERFORGE_AGENT=1`, requires `INFERFORGE_ASYNC=1`): pydantic-ai is worker-only, imported lazily inside `tasks/agent.py` function bodies (missing SDK → code 3 naming pydantic-ai, same rule as openai/onnxruntime). **Pydantic AI V2 naming differs from V1 tutorials**: `output_type` (not result_type), `instructions` (not system_prompt), `BinaryContent`/`ImageUrl` (not ImagePart), `OpenAIChatModel` (not OpenAIModel) for OpenAI-compatible endpoints. V2 has NO built-in HTTP retries — `_build_agent()` configures the tenacity/httpx2 transport (429/5xx/connection ×3, Retry-After aware). `run_sync` spins its own event loop per call, so build a FRESH agent/client per task (never cache the client). Agent reuses `INFERFORGE_LLM_*` config via `tasks.vlm.get_llm_config` and the vlm remote-call metrics. The detection tool is registry-driven: the `model` request field picks a registered detect model (submit-time `validate_model` → code 10; the worker re-checks for registry drift → code 10), class names come from that model's `classes` table (the hardcoded COCO lookup is gone), and `INFERFORGE_AGENT_TARGET_CLASS` (default `person`) picks the target class — not in the table → code 3 naming the var, checked before the paid call. Tests patch the `agent._build_agent(model)` seam (the seam takes the resolved registered model name; task modules bind `run_hair_count` at import time — patching `agent.run_hair_count` does NOT reach them).
- Gitignored: everything under `models/` except `.gitkeep` and `registry.example.yaml`, plus `logs/`, `outputs/`, `result*.jpg`/`result*.json`, `archive/` (old design docs — leave untouched).
- Celery/redis are optional: async is one deployment shape behind `INFERFORGE_ASYNC=1` — it registers both async apis (callback + query; requires celery + rabbitmq + redis). `INFERFORGE_QUERY=1` is a deprecated alias (logs a warning). Missing deps log a warning and skip the whole async mode. Async task modules use `shared_task` (never import celery_app from tasks — circular import). `celery_app.py` must keep its unconditional sys.path insert — the celery CLI temporarily removes cwd from sys.path.
- Callback fires exactly once: detection business errors (code 1/2/3/10) are NOT retried — only network failures on the callback POST retry (3 attempts, exponential backoff). Keep it that way. `tasks.detection_callback.post_callback` is the reusable helper for any future async callback task — retry constants stay single-sourced there.
- VLM/Agent are **query-only** async tasks (`INFERFORGE_LLM=1` / `INFERFORGE_AGENT=1`, both require `INFERFORGE_ASYNC=1`) — no sync or callback variants; callback delivery is the detection task's reference implementation, and LLM/Agent callers are active business systems that poll (query is the main path). Worker builds a fixed server-side prompt (`INFERFORGE_LLM_PROMPT` / `INFERFORGE_AGENT_INSTRUCTIONS` override) and calls a remote OpenAI-compatible endpoint; config via `INFERFORGE_LLM_MODEL`/`INFERFORGE_LLM_API_KEY` (required) + `INFERFORGE_LLM_BASE_URL` (optional), read lazily by `tasks.vlm.get_llm_config` (tests reset `tasks.vlm._client`). The openai SDK is worker-only, imported lazily inside `tasks/vlm.py` function bodies — the web process and tests must import the vlm chain without openai installed. Code 9 (upstream LLM failure after SDK retries) is a business error. VLM workers are I/O-bound — scale with `./start_celery.sh -c N`; `worker_prefetch_multiplier` stays 1.
- `INFERFORGE_PRELOAD=1` is a best-effort startup warmup: each enabled capability's DEFAULT model loads at boot (never every registered model — rare models keep lazy loading). Web wiring = `app.router.on_startup` in `app.py` (gunicorn `preload_app=True` builds the app in the master, but uvicorn runs the lifespan per worker, so sessions are created post-fork per worker); worker wiring = `worker_process_init` signal in `celery_app.py` delegating to `tasks.warmup.preload_worker` (detection only — seg/cls are sync-only). All gating + per-capability try/except lives in `tasks/warmup.py` (testable without importing celery_app — never import celery_app in tests); a failed preload is logged and the capability stays 503 via readiness — readiness is the source of truth, not the preload log.
- Log rotation belongs to system logrotate (copytruncate, `deploy/logrotate.conf`) — do not reintroduce in-app rotation handlers (multi-process rotation races).
- The compose stack bind-mounts `./models` and `./logs` — put yolov8n.onnx in `models/` first; the Docker image never bakes the model. In-container broker/redis urls are overridden in `docker-compose.yml` (the localhost defaults won't work).
- Docs language: `docs/` in Chinese, READMEs bilingual. Docs describe current implementation only — no version planning. Professional terms stay in English (envelope, contract, composition root, …) — don't coin Chinese translations; established terms (线程池、灰度、幂等) stay Chinese.

## Maestro Configuration

{{AI_MODEL_NAME}} = DeepSeek-V4-Pro
{{AI_MODEL_EMAIL}} = noreply@deepseek.com
{{REPO_URL}} = https://github.com/zjykzj/InferForge
{{PACKAGE_NAME}} = none

### Version Bump Locations

| # | File | Field |
|---|------|-------|
| 1 | `VERSION` | `X.Y.Z` single line |
| 2 | `CHANGELOG.md` | `## [X.Y.Z] - YYYY-MM-DD` section header |
