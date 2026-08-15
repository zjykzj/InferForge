# CLAUDE.md

## Project Overview

InferForge is an algorithm-agnostic inference-serving project template — a serving shell above inference kernels, forging any model (CV → LLM → Agent) into production.

Layers:

- `apis/` + `app.py` — interface layer: Flask blueprints, input validation, unified responses
- `tasks/` — task layer: orchestration; each task owns its predictors (lazy loading)
- `engines/` — engine layer: `BasePredictor` contract + YOLOv8n implementation
- `utils/` — cross-cutting: logging, image conversion, response format, request_id

## Architecture Constraints

Authoritative details live in [docs/architecture.md](docs/architecture.md); the hard rules that affect every edit:

- One-way dependency chain: `app -> apis -> tasks -> engines`. No reverse imports.
- `utils/` is cross-cutting — usable by any layer, must not depend on business layers.
- `BasePredictor` (`engines/base.py`) is the only stable contract. Swapping an algorithm touches `engines/` only.
- Tasks own their predictors; the API layer never touches them.
- HTTP always returns 200; business status in `{code, message, data}` (see docs/status-codes.md).
- Engine pre/post processing is self-written — never import ultralytics (AGPL-3.0).

## Development Commands

```bash
pytest tests/ -v                                    # smoke tests (no model file needed)
./start.sh                                          # run service (requires models/yolov8n.onnx)
python3 scripts/test_api.py --image assets/bus.jpg  # test the running API
python3 -m py_compile app.py apis/*.py tasks/*.py engines/*.py utils/*.py tests/*.py
```

## Critical Details

- onnxruntime is imported **inside** `YoloPredictor.load()` on purpose — tests must stay model-free. Do not move it to module level.
- Tests inject `FakePredictor` by monkeypatching `tasks.detection.get_predictor`; never load a real model or hit the network in tests.
- Python 3.9 compatibility: no `X | None` syntax; use `Optional` from typing.
- New business codes must be registered in **both** `utils/response.py` docstring and `docs/status-codes.md`.
- Gitignored: `models/*.onnx`, `logs/`, `result*.jpg`/`result*.json`, `archive/` (old design docs — leave untouched).
- Docs language: `docs/` in Chinese, READMEs bilingual. Docs describe current implementation only — no version planning.

## Git Operations

Git workflows are defined as project skills. Use the corresponding skill for each task:

- **`/commit`** — commit message format, `Co-Authored-By` line, and conventional commit types. Invoke for every `git commit`.
- **`/release`** — version bump checklist, version bump commit, annotated tag, push, and GitHub Release body template. Invoke when publishing a new release.

### AI Model Configuration

The AI model used in this project is **DeepSeek-V4-Pro**. Configured in skills as:

```
{{AI_MODEL_NAME}} = DeepSeek-V4-Pro
{{AI_MODEL_EMAIL}} = noreply@deepseek.com
```

### Release Configuration

Version bump locations for this project:

| # | File | Field |
|---|------|-------|
| 1 | `VERSION` | `0.1.0` single line |
| 2 | `CHANGELOG.md` | `## [0.1.0] - YYYY-MM-DD` section header |

Verify with: `grep -n "0.1.0" VERSION CHANGELOG.md`

Repository URL for the `/release` skill:

```
{{REPO_URL}} = https://github.com/zjykzj/InferForge
```
