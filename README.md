# InferForge

> 🔨 From kernel to service — InferForge forges any model (CV → LLM → Agent) into production.
>
> Web API · task orchestration · engine abstraction · logging & tracing · tests. A template, not a framework: download, adapt, deploy.

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="License"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.12%2B-blue.svg" alt="Python 3.12+"></a>
  <a href="https://github.com/zjykzj/InferForge/releases"><img src="https://img.shields.io/github/v/release/zjykzj/InferForge" alt="Release"></a>
  <a href="https://conventionalcommits.org"><img src="https://img.shields.io/badge/Conventional%20Commits-1.0.0-yellow.svg" alt="Conventional Commits"></a>
</p>

## Features

| | | |
|:---|:---|:---|
| 🔍 **Sync Detection** | `POST /predict` — base64 / URL in, drawn image + JSON out | `scripts/test_predict.py` |
| ⚡ **Async Detection** | Celery + RabbitMQ + Redis — push (callback) or poll (query), per-request choice | `INFERFORGE_ASYNC=1 ./start.sh` |
| 🧱 **Layered Template** | apis / tasks / engines / utils — replace one layer, keep the rest | [architecture](docs/architecture.md) |
| 📦 **Business Codes** | `{code, message, data}` envelope — HTTP always 200 | [status-codes](docs/status-codes.md) |
| 🚦 **Health Probes** | `GET /health` + `/health/ready` — liveness/readiness for K8s & LBs | [api](docs/api.md) |
| 📚 **OpenAPI Docs** | auto-generated `/docs` (Swagger UI) + `/openapi.json` | `GET /docs` |
| 🐳 **Docker Compose** | one command full stack — web + worker + RabbitMQ + Redis | `docker compose up -d` |
| 🔗 **Request Tracing** | request_id + task_id across web and worker logs | [logging](docs/logging.md) |
| ✅ **Smoke Tests** | 30+ tests, no model file needed | `pytest tests/ -v` |

## Quick Start

### Sync

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Put the ONNX model in place
cp /path/to/yolov8n.onnx models/

# 3. Start the service (default: 2 workers on port 8000)
./start.sh

# 4. Test the API
python3 scripts/test_predict.py --image assets/bus.jpg                              # local image (base64)
python3 scripts/test_predict.py --url https://ultralytics.com/images/bus.jpg        # remote url
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
python3 scripts/test_predict_callback.py --image assets/bus.jpg \
  --callback-url http://localhost:9000/result                                   # result is POSTed back
```

Pull style — submit a task, poll until the result is ready (result cached in Redis):

```bash
redis-server &                                                                  # start redis (result store)
python3 scripts/test_predict_query.py --image assets/bus.jpg                    # submit + poll until done
```

### Docker

Full stack in containers — web + worker + RabbitMQ + Redis, no local installs:

```bash
cp /path/to/yolov8n.onnx models/    # bind-mounted into the containers, never baked into the image
docker compose up -d
curl http://localhost:8000/health   # liveness probe
```

RabbitMQ management UI at http://localhost:15672 (guest/guest). `docker compose down` stops the stack (`-v` also drops queue/redis data). See [quick-start](docs/quick-start.md) §4 for details.

## Documentation

[docs/](docs/) — concepts · quick-start · architecture · api · deployment · stack · fastapi-migration · status-codes · logging · testing · security

## Acknowledgments

- **Web & serving** — [FastAPI](https://fastapi.tiangolo.com/) for routing, Pydantic validation and OpenAPI docs · [Uvicorn](https://www.uvicorn.org/) for the ASGI server · [Gunicorn](https://gunicorn.org/) for multi-process management
- **Inference** — [ONNX Runtime](https://onnxruntime.ai/) for the forward pass · [OpenCV](https://opencv.org/) for image pre/post-processing · [NumPy](https://numpy.org/) for vectorized decode and NMS
- **Async tasks** — [Celery](https://docs.celeryq.dev/) for task submission and execution · [RabbitMQ](https://www.rabbitmq.com/) for message brokering · [Redis](https://redis.io/) for TTL-managed result storage
- **Demo model** — [Ultralytics YOLOv8n](https://docs.ultralytics.com/) exported to ONNX

## License

[MIT License](LICENSE) © 2026 zjykzj
