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

## About

InferForge is a serving shell above inference backends: it provides everything a production service needs around the inference kernel — web APIs, logging, exception handling, unified response formats — so a model becomes a deployable service in days, not weeks. But the business layer above inference is too diverse to generalize (different models, tasks and interfaces), so this project is deliberately a **template, not a framework**: fork it, own the code, and define your own tasks and APIs; the layered architecture keeps each layer replaceable independently — swap an algorithm (ONNX Runtime, TensorRT, Triton, …) and only the engine layer changes. See [forking-contract](docs/forking-contract.md) for what to edit and what to keep.

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

# 5. Auto-generated API docs (Swagger UI): http://localhost:8000/docs
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

- **Engineering** — concepts · quick-start · architecture · add-engine · api · deployment
- **Tech stack** — stack · fastapi-migration
- **Standards** — status-codes · logging · metrics · testing · security · forking-contract

Full index with one-line descriptions: [docs/README.md](docs/README.md).

## Acknowledgments

- **Web & serving** — [FastAPI](https://fastapi.tiangolo.com/) (routing, Pydantic validation, OpenAPI docs) · [Uvicorn](https://www.uvicorn.org/) (ASGI server) · [Gunicorn](https://gunicorn.org/) (multi-process management)
- **Inference** — [ONNX Runtime](https://onnxruntime.ai/) (forward pass) · [OpenCV](https://opencv.org/) (image pre/post-processing) · [NumPy](https://numpy.org/) (vectorized decode and NMS)
- **Async tasks** — [Celery](https://docs.celeryq.dev/) (task submission and execution) · [RabbitMQ](https://www.rabbitmq.com/) (message brokering) · [Redis](https://redis.io/) (TTL-managed result storage)
- **Demo model** — [Ultralytics YOLOv8n](https://docs.ultralytics.com/) (exported to ONNX)

## License

[MIT License](LICENSE) © 2026 zjykzj
