# InferForge

> 🔨 Everything above model inference — InferForge forges any model (CV → LLM → Agent) into production.
>
> Web API · task orchestration · engine abstraction · logging & tracing · tests. A template, not a framework: download, adapt, deploy.

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="License"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.9+-blue.svg" alt="Python 3.9+"></a>
  <a href="https://github.com/zjykzj/InferForge/releases"><img src="https://img.shields.io/github/v/release/zjykzj/InferForge" alt="Release"></a>
  <a href="https://conventionalcommits.org"><img src="https://img.shields.io/badge/Conventional%20Commits-1.0.0-yellow.svg" alt="Conventional Commits"></a>
</p>

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

### Async (optional)

Server-side callback via Celery + RabbitMQ — no Redis needed:

```bash
pip install -r requirements-async.txt
INFERFORGE_ASYNC=1 ./start.sh                                                   # start web with the async api
./start_celery.sh                                                               # start the worker
python3 scripts/callback_receiver.py                                            # start the callback receiver (saves to outputs/callbacks/)
python3 scripts/test_predict_callback.py --image assets/bus.jpg \
  --callback-url http://localhost:9000/result                                   # result is POSTed back
```

Detailed guide (RabbitMQ setup, troubleshooting): [docs/quick-start.md](docs/quick-start.md). API reference: [docs/api.md](docs/api.md).

## License

[MIT License](LICENSE) © 2026 zjykzj
