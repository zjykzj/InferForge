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

Config can live in a `.env` file (`cp .env.example .env` — shell-exported variables take precedence). Async (Celery + RabbitMQ + Redis, callback/query), the other capabilities, and the Docker full stack: [quick-start](docs/quick-start.md) (§2–3 async, §4 containers) + [api](docs/api.md). Tests are model-free and service-free by design (`pytest tests/` — see [testing](docs/testing.md)).

## Developing with Agents

Development is agent-driven: fork the repo, tell the agent what you want, and the workflow docs turn the request into a checked implementation. Start from the task→entry map in [docs/README.md](docs/README.md) — for example:

```
You:   add a sync API for segmentation
Agent: decomposes (shape=sync × capability=segment, engine layer untouched),
       checks the boundary table, proposes the per-layer placement plan
You:   confirmed
Agent: implements against the canonical references → pytest +
       check_capability.py green → commit
```

The architecture checks shipped with the fork keep every change inside the contract; the skills in `.claude/skills/` wrap the same workflows for Claude Code.

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
| Standards | [forking-contract](docs/workflow/forking-contract.md) · [bootstrap](docs/workflow/bootstrap.md) · [add-capability](docs/workflow/add-capability.md) · [add-engine](docs/workflow/add-engine.md) · [modify-service](docs/workflow/modify-service.md) · [status-codes](docs/status-codes.md) · [logging](docs/logging.md) · [metrics](docs/metrics.md) · [testing](docs/testing.md) · [security](docs/security.md) |
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
