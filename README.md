# InferForge

> 🔨 Everything above model inference — InferForge forges any model (CV → LLM → Agent) into production.
>
> Web API · task orchestration · engine abstraction · logging & tracing · tests. A template, not a framework: download, adapt, deploy.

## Architecture

```
InferForge/
├── app.py              # Flask entry: logging setup + blueprint registration
├── apis/               # Interface layer: one blueprint per endpoint
├── tasks/              # Task layer: orchestration; each task owns its predictors
├── engines/            # Engine layer: BasePredictor contract + YOLO implementation
├── utils/              # Common utilities: logging / image / response / request id
├── tests/              # Smoke tests
├── scripts/            # Helper scripts (API test client)
├── assets/             # Test images
├── models/             # Model files (gitignored — put yolov8n.onnx here)
├── docs/               # Specifications (api / status-codes / logging / testing)
├── start.sh            # One-command startup
├── gunicorn.conf.py    # Gunicorn configuration
└── requirements.txt    # Dependencies
```

Dependency chain — each layer only talks to the one below (`utils/` is cross-cutting):

```
app -> apis -> tasks -> engines
```

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Put the ONNX model in place
cp /path/to/yolov8n.onnx models/

# 3. Start the service (default: 2 workers on port 8000)
./start.sh

# 4. Test the API
python3 scripts/test_api.py --image assets/bus.jpg                              # local image (base64)
python3 scripts/test_api.py --url https://ultralytics.com/images/bus.jpg        # remote url
```

Run the smoke tests:

```bash
pytest tests/ -v
```

Logs land in `logs/app.log` (JSON, per-request trace ids) — see [docs/logging.md](docs/logging.md). API reference and curl recipes: [docs/api.md](docs/api.md).

## License

[MIT License](LICENSE) © 2026 zjykzj
