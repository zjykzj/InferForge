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

## Quick Start

### Sync

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

Optional: enable the sync segment / classify capabilities (off by default; detection is unaffected):

```bash
# 1. Export and place the models (same as detection)
yolo export model=yolov8n-seg.pt format=onnx
yolo export model=yolov8n-cls.pt format=onnx
cp /path/to/yolov8n-seg.onnx models/
cp /path/to/yolov8n-cls.onnx models/

# 2. Start with the switches (either one works; start.sh only checks enabled models)
INFERFORGE_SEG=1 INFERFORGE_CLS=1 ./start.sh

# 3. Test
python3 scripts/test_sync_segment.py --image assets/bus.jpg --save result_seg.jpg   # segment
python3 scripts/test_sync_classify.py --image assets/bus.jpg                        # classify (top-5)
```

Optional: multi-model routing — copy the example registry and pick models per request (no registry file means single-model behavior, exactly as above):

```bash
cp models/registry.example.yaml models/registry.yaml     # edit it to list your models
./start.sh                                               # preflight checks every registered model

python3 scripts/test_sync_detect.py --image assets/bus.jpg --model yolov8n          # explicit model
python3 scripts/test_sync_detect.py --image assets/bus.jpg                            # default model (no field)
# details: docs/model-registry.md
```

Run the smoke tests:

```bash
pytest tests/ -v
```

### Async

One async deployment shape — Celery + RabbitMQ + Redis. `INFERFORGE_ASYNC=1` registers both apis; callback or query is a per-request choice:

```bash
pip install -r requirements-async.txt
INFERFORGE_ASYNC=1 ./start.sh                                                   # start web with the async apis
./start_celery.sh                                                               # start the worker
```

Push style — server POSTs the result to your `callback_url`:

```bash
python3 scripts/callback_receiver.py                                            # receiver (saves to outputs/callbacks/)
python3 scripts/test_async_detect_callback.py --image assets/bus.jpg \
  --callback-url http://localhost:9000/result                                   # result is POSTed back
```

Pull style — submit a task, poll until the result is ready (result cached in Redis):

```bash
redis-server &                                                                  # start redis (result store)
python3 scripts/test_async_detect_query.py --image assets/bus.jpg                    # submit + poll until done
```

VLM (image understanding via a remote LLM, async-only) — add `INFERFORGE_LLM=1` on top of async; the worker calls the remote model:

```bash
INFERFORGE_LLM=1 INFERFORGE_ASYNC=1 ./start.sh                                  # start web (registers /predict/vlm/*)
INFERFORGE_LLM_MODEL=your-model \
INFERFORGE_LLM_API_KEY=your-key \
INFERFORGE_LLM_BASE_URL=https://your-llm-endpoint/v1 \
./start_celery.sh                                                               # start worker (remote call happens here)
python3 scripts/test_async_vlm_query.py --image assets/bus.jpg                        # submit + poll until the answer arrives
```

The prompt is fixed server-side (`INFERFORGE_LLM_PROMPT` overrides it); clients submit an image only. See [api](docs/api.md) §10.

Config can also live in a `.env` file (`cp .env.example .env` and fill in — shell-exported variables take precedence).

Agent (Pydantic AI orchestration demo — detection tool + LLM attribute judgment, async-only) — add `INFERFORGE_AGENT=1` on top of async; the worker needs the same `INFERFORGE_LLM_*` config plus the local model:

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

### Docker

Full stack in containers — web + worker + RabbitMQ + Redis, no local installs:

```bash
cp /path/to/yolov8n.onnx models/    # bind-mounted into the containers, never baked into the image
docker compose up -d
curl http://localhost:8000/health   # liveness probe
```

RabbitMQ management UI at http://localhost:15672 (guest/guest). `docker compose down` stops the stack (`-v` also drops queue/redis data). See [quick-start](docs/quick-start.md) §4 for details.

Optional monitoring stack (Prometheus + Grafana): `docker compose -f docker-compose.yml -f deploy/docker-compose.monitoring.yml up -d` — see [metrics](docs/metrics.md).

## Documentation

- **Engineering** — concepts · quick-start · architecture · add-engine · api · deployment · benchmark
- **Tech stack** — stack · fastapi-migration
- **Standards** — status-codes · logging · metrics · testing · security · forking-contract

Full index with one-line descriptions: [docs/README.md](docs/README.md).

## Acknowledgments

- **Web & serving** — [FastAPI](https://fastapi.tiangolo.com/) · [Uvicorn](https://www.uvicorn.org/) · [Gunicorn](https://gunicorn.org/)
- **Inference** — [ONNX Runtime](https://onnxruntime.ai/) · [OpenCV](https://opencv.org/) · [NumPy](https://numpy.org/)
- **Async tasks** — [Celery](https://docs.celeryq.dev/) · [RabbitMQ](https://www.rabbitmq.com/) · [Redis](https://redis.io/)
- **LLM & agents** — [OpenAI SDK](https://github.com/openai/openai-python) · [Pydantic AI](https://ai.pydantic.dev/)
- **Demo model** — [Ultralytics YOLOv8n](https://docs.ultralytics.com/)

## License

[MIT License](LICENSE) © 2026 zjykzj
