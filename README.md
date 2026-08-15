# InferForge

> 🔨 From kernel to service — InferForge forges any model (CV → LLM → Agent) into production.
>
> Web API · task orchestration · engine abstraction · logging & tracing · tests. A template, not a framework: download, adapt, deploy.

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="License"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.9+-blue.svg" alt="Python 3.9+"></a>
  <a href="https://github.com/zjykzj/InferForge/releases"><img src="https://img.shields.io/github/v/release/zjykzj/InferForge" alt="Release"></a>
  <a href="https://conventionalcommits.org"><img src="https://img.shields.io/badge/Conventional%20Commits-1.0.0-yellow.svg" alt="Conventional Commits"></a>
</p>

## Features

| | | |
|:---|:---|:---|
| ⚡ **Async Callback** | Celery + RabbitMQ — submit a task, result POSTed to your URL | `INFERFORGE_ASYNC=1 ./start.sh` |
| 🔍 **Sync Detection** | `POST /predict` — base64 / URL in, drawn image + JSON out | `scripts/test_predict.py` |
| 🧱 **Layered Template** | apis / tasks / engines / utils — replace one layer, keep the rest | [architecture](docs/architecture.md) |
| 📦 **Business Codes** | `{code, message, data}` envelope — HTTP always 200 | [status-codes](docs/status-codes.md) |
| 🔗 **Request Tracing** | request_id + task_id across web and worker logs | [logging](docs/logging.md) |
| ✅ **Smoke Tests** | 16 tests, no model file needed | `pytest tests/ -v` |

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

Server-side callback via Celery + RabbitMQ:

```bash
pip install -r requirements-async.txt
INFERFORGE_ASYNC=1 ./start.sh                                                   # start web with the async api
./start_celery.sh                                                               # start the worker
python3 scripts/callback_receiver.py                                            # start the callback receiver (saves to outputs/callbacks/)
python3 scripts/test_predict_callback.py --image assets/bus.jpg \
  --callback-url http://localhost:9000/result                                   # result is POSTed back
```

## Documentation

[docs/](docs/) — quick-start · architecture · stack · api · status-codes · logging · testing · security

## Acknowledgments

- Built with [Flask](https://flask.palletsprojects.com/), [Gunicorn](https://gunicorn.org/), [ONNX Runtime](https://onnxruntime.ai/), [OpenCV](https://opencv.org/), [NumPy](https://numpy.org/), and [Celery](https://docs.celeryq.dev/)
- Demo model: [Ultralytics YOLOv8n](https://docs.ultralytics.com/) (exported to ONNX)

## License

[MIT License](LICENSE) © 2026 zjykzj
