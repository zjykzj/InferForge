# InferForge

> 🔨 From kernel to service — InferForge forges any model (CV → LLM → Agent) into production.
>
> Out of the box: sync + async APIs · health probes · OpenAPI docs · Prometheus metrics. Optional (off by default): API-key auth & rate limiting. A template, not a framework: download, adapt, deploy.

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="License"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.12%2B-blue.svg" alt="Python 3.12+"></a>
  <a href="https://github.com/zjykzj/InferForge/actions/workflows/ci.yml"><img src="https://github.com/zjykzj/InferForge/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/zjykzj/InferForge/releases"><img src="https://img.shields.io/github/v/release/zjykzj/InferForge" alt="Release"></a>
  <a href="https://deepwiki.com/zjykzj/InferForge"><img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki"></a>
</p>

## About

InferForge is a serving shell above inference backends: web APIs, logging, exception handling and unified response formats out of the box — a model becomes a deployable service in days. But the business layer above inference is too diverse to generalize, so this is deliberately a **template, not a framework**: fork it, own the code, and define your own tasks and APIs. The layered architecture keeps every layer replaceable independently — see [forking-contract](docs/forking-contract.md) for what to edit and what to keep.

## Project Layout

```
InferForge/
├── apis/          # FastAPI routers + Pydantic schemas — interface layer
├── tasks/         # task orchestration; each task owns its predictors
├── engines/       # BasePredictor contract + YOLOv8n detect/segment/classify reference implementations
├── utils/         # cross-cutting: envelope, logging, metrics, auth, rate limit
├── deploy/        # reference artifacts: logrotate, nginx canary, monitoring stack
├── docs/          # full documentation set (Chinese, indexed by category)
├── scripts/       # API test clients + callback receiver
└── tests/         # smoke tests — model-free, CI-run
```

## Capability Overview

| Capability | Form | Switch | Model |
|---|---|---|---|
| Detection | sync + async | always on; `INFERFORGE_ASYNC` adds the async apis | `yolov8n.onnx` |
| Segment | sync only | `INFERFORGE_SEG` | `yolov8n-seg.onnx` |
| Classify | sync only | `INFERFORGE_CLS` | `yolov8n-cls.onnx` |
| Pipeline | sync only | `INFERFORGE_PIPELINE` | reuses detect + classify |
| Dedup | sync only | `INFERFORGE_DEDUP` | `dino2-small.onnx` |
| Search / dupcheck | async only (query) | `INFERFORGE_SEARCH` | embed + `data/gallery.db` |
| VLM | async only (query) | `INFERFORGE_LLM` | remote LLM |
| Agent | async only (query) | `INFERFORGE_AGENT` | detect + remote LLM |

Switches are opt-in environment variables (detection is always on); they gate which routes exist, not which models load (that's the registry's job — see [model-registry](docs/model-registry.md)). Every async capability builds on the same §Async Infrastructure; search / VLM / Agent have no callback form.

## Quick Start

The minimal path: sync detection.

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Put the ONNX model in place
cp /path/to/yolov8n.onnx models/

# 3. Start the service (default: 2 workers on port 8000)
./start.sh                                  # models load lazily on first request
INFERFORGE_PRELOAD=1 ./start.sh             # ... or load them at startup (readiness ready immediately)

# 4. Test the API
python3 scripts/test_sync_detect.py --image assets/bus.jpg                              # local image (base64)
python3 scripts/test_sync_detect.py --url https://ultralytics.com/images/bus.jpg        # remote url

# 5. Auto-generated API docs (Swagger UI): http://localhost:8000/docs
# 6. Prometheus metrics: http://localhost:8000/metrics (optional — see docs/metrics.md)
```

Config can also live in a `.env` file (`cp .env.example .env` and fill in — shell-exported variables take precedence). Everything else: §Capabilities.

## Async Infrastructure

One async deployment shape — Celery + RabbitMQ + Redis — shared by every async capability (detect, search/dupcheck, VLM, Agent). Delivery is a per-request choice: callback (server POSTs the result to your `callback_url`) or query (submit, poll until the result is ready — cached in Redis). Set up once:

```bash
pip install -r requirements-async.txt
INFERFORGE_ASYNC=1 ./start.sh                                                   # start web (registers the async detect apis)
./start_celery.sh                                                               # start the worker
```

`INFERFORGE_ASYNC=1` registers the detection apis; search / VLM / Agent stack their own switches on top (see their sections). Usage of the two delivery styles: §Detection.

## Capabilities

### 1. Detection

Sync form — see Quick Start above. The async form needs no extra switch: the apis registered by §Async Infrastructure are detection's; callback or query per request:

```bash
# push style — server POSTs the result to your callback_url
python3 scripts/callback_receiver.py                                            # receiver (saves to outputs/callbacks/)
python3 scripts/test_async_detect_callback.py --image assets/bus.jpg \
  --callback-url http://localhost:9000/result                                   # result is POSTed back

# pull style — submit a task, poll until the result is ready (result cached in Redis)
redis-server &                                                                  # start redis (result store)
python3 scripts/test_async_detect_query.py --image assets/bus.jpg                    # submit + poll until done
```

### 2. Segment / Classify

Sync only (off by default; detection is unaffected):

```bash
# 1. Export and place the models (subprocess yolo CLI — never imports ultralytics; auto shape-verified)
python3 scripts/export_yolo.py --task segment --task classify

# 2. Start with the switches (either one works; start.sh only checks enabled models)
INFERFORGE_SEG=1 INFERFORGE_CLS=1 ./start.sh

# 3. Test
python3 scripts/test_sync_segment.py --image assets/bus.jpg --save result_seg.jpg   # segment
python3 scripts/test_sync_classify.py --image assets/bus.jpg                        # classify (top-5)
```

### 3. Pipeline

Sync only. Compose the two models above — detect → crop → fine-grained classify (e.g. detect `bus` → classify `school bus`); target classes via `INFERFORGE_PIPELINE_TARGETS` (default `car,truck,bus`):

```bash
INFERFORGE_PIPELINE=1 ./start.sh
python3 scripts/test_sync_pipeline.py --image assets/bus.jpg --save result_pipeline.jpg   # pipeline (detect → classify)
```

### 4. Embedding

One DINOv2-small engine powers three business tasks: dedup (sync) and gallery search / dupcheck (async query-only, worker-only — the milvus-lite index is single-process exclusive). Export the ONNX into models/ first:

```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu   # one-off export dep
python3 scripts/export_dinov2.py                                                # -> models/dino2-small.onnx
```

Sync batch dedup — near-duplicate groups within one batch (threshold via `INFERFORGE_DUP_THRESHOLD`, default 0.95):

```bash
INFERFORGE_DEDUP=1 ./start.sh
python3 scripts/test_sync_dedup.py --image assets/bus.jpg --image assets/bus.jpg --image assets/zidane.jpg   # dedup
```

Async gallery search / dupcheck (on top of §Async Infrastructure):

```bash
python3 scripts/build_gallery.py                # build the index first — worker must be STOPPED (gallery/ -> data/gallery.db)
INFERFORGE_ASYNC=1 INFERFORGE_SEARCH=1 ./start.sh
python3 scripts/run_search.py --image assets/bus.jpg --check    # task layer directly (search / dupcheck)
```

Details: [embedding](docs/embedding.md).

### 5. VLM

Image understanding via a remote LLM — async query-only. Add `INFERFORGE_LLM=1` on top of §Async Infrastructure; the worker calls the remote model:

```bash
INFERFORGE_LLM=1 INFERFORGE_ASYNC=1 ./start.sh                                  # start web (registers /predict/vlm/*)
INFERFORGE_LLM_MODEL=your-model \
INFERFORGE_LLM_API_KEY=your-key \
INFERFORGE_LLM_BASE_URL=https://your-llm-endpoint/v1 \
./start_celery.sh                                                               # start worker (remote call happens here)
python3 scripts/test_async_vlm_query.py --image assets/bus.jpg                        # submit + poll until the answer arrives
```

The prompt is fixed server-side (`INFERFORGE_LLM_PROMPT` overrides it); clients submit an image only. See [api](docs/api.md) §10.

### 6. Agent

Pydantic AI orchestration demo — detection tool + LLM attribute judgment, async query-only. Add `INFERFORGE_AGENT=1` on top of §Async Infrastructure; the worker reuses the same `INFERFORGE_LLM_*` config plus the local model:

```bash
INFERFORGE_AGENT=1 INFERFORGE_ASYNC=1 ./start.sh                                  # start web (registers /predict/agent/*)
INFERFORGE_LLM_MODEL=your-model \
INFERFORGE_LLM_API_KEY=your-key \
./start_celery.sh                                                               # start worker (agent runs here)
curl -s -X POST http://localhost:8000/predict/agent/query \                     # submit; then poll the returned task_id
  -H "Content-Type: application/json" \
  -d '{"image": "<base64 of assets/zidane.jpg>"}'
```

The demo counts persons with/without hair (zidane.jpg → 2 persons, 1:1); swap the schema + instructions + tool for any other attribute task. See [agent](docs/agent.md).

## Model Registry

Multi-model routing — copy the example registry and pick models per request (no registry file means single-model behavior, exactly as above):

```bash
cp models/registry.example.yaml models/registry.yaml     # edit it to list your models
./start.sh                                               # preflight checks every registered model

python3 scripts/test_sync_detect.py --image assets/bus.jpg --model yolov8n          # explicit model
python3 scripts/test_sync_detect.py --image assets/bus.jpg                            # default model (no field)
# details: docs/model-registry.md
```

## Docker

Full stack in containers — web + worker + RabbitMQ + Redis, no local installs:

```bash
cp /path/to/yolov8n.onnx models/    # bind-mounted into the containers, never baked into the image
docker compose up -d
curl http://localhost:8000/health   # liveness probe
```

RabbitMQ management UI at http://localhost:15672 (guest/guest). `docker compose down` stops the stack (`-v` also drops queue/redis data). See [quick-start](docs/quick-start.md) §4 for details.

Optional monitoring stack (Prometheus + Grafana): `docker compose -f docker-compose.yml -f deploy/docker-compose.monitoring.yml up -d` — see [metrics](docs/metrics.md).

## Testing

Model-free and service-free by design: tests inject FakePredictor seams and never load weights or hit the network — CI runs the same commands.

```bash
pytest tests/ -v                                  # full suite (no models, no RabbitMQ/Redis needed)
pip install pytest-cov
pytest tests/ -q --cov=app --cov=apis --cov=tasks --cov=engines --cov=utils
python3 -m py_compile app.py apis/*.py tasks/*.py engines/*.py utils/*.py tests/*.py scripts/*.py
```

Coverage (~81% baseline) is informational, not gated: scripts/ and defensive error branches are intentionally not unit-tested. Test strategy details (seams, async fakes, registry isolation): [docs/testing.md](docs/testing.md).

## Documentation

| Category | Docs |
|---|---|
| Guides | [quick-start](docs/quick-start.md) · [architecture](docs/architecture.md) · [api](docs/api.md) · [model-registry](docs/model-registry.md) · [agent](docs/agent.md) · [embedding](docs/embedding.md) · [benchmark](docs/benchmark.md) · [deployment](docs/deployment.md) |
| Knowledge | [concepts](docs/concepts.md) · [release-strategies](docs/release-strategies.md) |
| Standards | [forking-contract](docs/forking-contract.md) · [add-engine](docs/add-engine.md) · [status-codes](docs/status-codes.md) · [logging](docs/logging.md) · [metrics](docs/metrics.md) · [testing](docs/testing.md) · [security](docs/security.md) |
| Tech stack | [stack](docs/stack.md) · [fastapi-migration](docs/fastapi-migration.md) |

Full index with one-line descriptions: [docs/README.md](docs/README.md).

## Acknowledgments

| Category | Dependencies |
|---|---|
| 🌐 Web & serving | [FastAPI](https://fastapi.tiangolo.com/) · [Uvicorn](https://www.uvicorn.org/) · [Gunicorn](https://gunicorn.org/) · [prometheus_client](https://github.com/prometheus/client_python) |
| ⚡ Async tasks | [Celery](https://docs.celeryq.dev/) · [RabbitMQ](https://www.rabbitmq.com/) · [Redis](https://redis.io/) |
| 🧠 Inference, image processing & retrieval | [ONNX Runtime](https://onnxruntime.ai/) · [OpenCV](https://opencv.org/) · [Milvus Lite](https://milvus.io/) |
| 🤖 LLM & agents | [OpenAI SDK](https://github.com/openai/openai-python) · [Pydantic AI](https://ai.pydantic.dev/) |

## License

[MIT License](LICENSE) © 2026 zjykzj
