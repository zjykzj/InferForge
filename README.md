# InferForge

> 🔨 From kernel to service — InferForge forges vision models into production, agent-first.
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

InferForge is a production-grade serving template for **vision inference services**: a thin service shell above inference kernels that turns any vision model into a deployable HTTP service.

- **Agent-first development.** Designed with LLM/Agents as the primary developer: new or existing projects are built by agents working against this implementation.
- **Business-facing web service and task architecture.** An architecture template for public-facing web services and task implementations: the service infrastructure is ready out of the box, and business tasks and APIs are yours to define.
- **Independent of the inference engine.** onnxruntime, TensorRT, Triton — any inference backend is freely replaceable, without touching the service itself.

Beyond vision kernels, the template ships reference implementations for VLM and Agent orchestration — remote-LLM integration (async query-only) that demonstrates the path from vision inference to LLM orchestration.

## Quick Start

Development is agent-driven — three examples walk the full path from an empty shell to a working service (Claude Code shown; other coding agents follow the same dialogue — the workflow docs are tool-agnostic):

### 1. Initialize a web service

```bash
# Download the template (a read-only factory — never modify it)
git clone https://github.com/zjykzj/InferForge.git ~/InferForge
```

```text
# In the template directory, start Claude Code (no path given? the agent asks)
cd ~/InferForge && claude
> initialize a web service at /srv/my-service

Agent: asks which mechanisms you want (metrics / auth / rate-limit /
       logging — default: none) → assemble.py --target
       /srv/my-service → generate identity files (README / CLAUDE.md)
       → configure → baseline checks green → git init + first commit
       (the default assembly = contract kernel + health probes)
```

```bash
# Verify: the service runs, health probes answer
cd /srv/my-service && python3 app.py
curl http://localhost:8000/health       # → {"code":0,"message":"success","data":{"status":"ok"}}
```

### 2. Add a sync detection API

```text
cd /srv/my-service && claude
> add a sync detection API, model yolov8n

Agent: decompose (shape=sync × capability=detect — the canonical references
       live in the template) → placement proposal → implement →
       pytest + check_capability.py green → commit
```

```bash
python3 scripts/test_sync_detect.py --image assets/bus.jpg   # → {"code":0,"data":{...boxes...}}
```

### 3. Add an async classification API

```text
> also add an async classification API, query style

Agent: decompose (shape=async query × capability=classify), boundary check
       clear → placement proposal: engine untouched, task copies the
       detection_query canonical, switch gating needs your call (async also
       registers detection's async apis)
> confirmed

Agent: implement → pytest + check_capability.py green → commit
```

```bash
INFERFORGE_ASYNC=1 ./start.sh
./start_celery.sh
python3 scripts/test_async_cls_query.py --image assets/bus.jpg   # submit → poll → top-5
```

Later capabilities work the same way: the agent copies canonical references from `~/InferForge` (the template directory is the reference library). The task→entry map in [docs/README.md](docs/README.md) routes init / add-capability / modify / engine work; the architecture checks built into every new project keep each change inside the contract; the skills in `.claude/skills/` wrap the same workflows for Claude Code.

## Run the Demo

Run the template's built-in service (sync detection) to see it work before initializing your own:

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

Config can live in a `.env` file (`cp .env.example .env` — shell-exported variables take precedence). Async (Celery + RabbitMQ + Redis, callback/query), the other capabilities, and the Docker full stack: [quick-start](docs/quick-start.md) (§2–3 async, §4 containers) + [api](docs/api.md). Tests are model-free and service-free by design (`pytest tests/` — see [testing](docs/testing.md)).

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

Switches are opt-in environment variables (detection is always on); they gate which routes exist, not which models load — that's the registry's job ([model-registry](docs/model-registry.md)). All async capabilities share one Celery + RabbitMQ + Redis infrastructure; delivery is a per-request choice — callback or query. Search / VLM / Agent have no callback form.

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

## Documentation

| Category | Docs |
|---|---|
| Guides | [quick-start](docs/quick-start.md) · [architecture](docs/architecture.md) · [api](docs/api.md) · [model-registry](docs/model-registry.md) · [agent](docs/agent.md) · [embedding](docs/embedding.md) · [benchmark](docs/benchmark.md) · [deployment](docs/deployment.md) |
| Knowledge | [concepts](docs/concepts.md) · [release-strategies](docs/release-strategies.md) |
| Standards | [forking-contract](docs/workflow/forking-contract.md) · [bootstrap](docs/workflow/bootstrap.md) · [assembly](docs/assembly.md) · [add-capability](docs/workflow/add-capability.md) · [add-engine](docs/workflow/add-engine.md) · [modify-service](docs/workflow/modify-service.md) · [status-codes](docs/status-codes.md) · [logging](docs/logging.md) · [metrics](docs/metrics.md) · [testing](docs/testing.md) · [security](docs/security.md) |
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
