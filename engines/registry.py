"""Model registry: name -> (capability, weights path, class names).

Pure metadata. The registry never constructs a predictor and never opens a
weights file — it only answers "which model does this request mean, and
where does it live". Loading and caching predictors stays in the task layer,
which owns them (see docs/architecture.md §2.2).

Config source, in order:

1. `models/registry.yaml` (override the location with INFERFORGE_REGISTRY_PATH)
2. no such file -> a three-entry registry synthesised from the historical
   INFERFORGE_MODEL_PATH / INFERFORGE_SEG_MODEL_PATH / INFERFORGE_CLS_MODEL_PATH
   env vars, with the same defaults they have always had

(2) is what keeps this feature backward compatible: a deployment that never
writes a registry file behaves exactly as it did before the registry existed.

Parsed lazily on first use and cached, not at import time — same reason as
tasks.vlm.get_llm_config: tests need to monkeypatch.setenv before the first
read. Call reset_cache() to drop the cache.
"""
import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Optional

from engines.base import class_label
from engines.imagenet_classes import IMAGENET_CLASS_NAMES
from engines.yolo import COCO_CLASS_NAMES
from utils.errors import ModelNotFound, RegistryConfigError

logger = logging.getLogger("engines.registry")

CAPABILITIES = ("detect", "segment", "classify", "embed")

DEFAULT_REGISTRY_FILE = os.path.join("models", "registry.yaml")

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The historical single-model env vars, kept alive as the no-registry-file
# fallback. Order matters only for readability.
_ENV_FALLBACK = (
    ("yolov8n", "detect", "INFERFORGE_MODEL_PATH", "yolov8n.onnx"),
    ("yolov8n-seg", "segment", "INFERFORGE_SEG_MODEL_PATH", "yolov8n-seg.onnx"),
    ("yolov8n-cls", "classify", "INFERFORGE_CLS_MODEL_PATH", "yolov8n-cls.onnx"),
    ("dino2-small", "embed", "INFERFORGE_EMBED_MODEL_PATH", "dino2-small.onnx"),
)

_BUILTIN_CLASS_NAMES = {
    "detect": COCO_CLASS_NAMES,
    "segment": COCO_CLASS_NAMES,
    "classify": IMAGENET_CLASS_NAMES,
    # Embed models have no class table (they output vectors, not labels);
    # the class_names property is never accessed by embed call sites.
    "embed": (),
}


def abs_path(path: str) -> str:
    """Resolve a registry-relative path against the project root.

    Registry files are written with repo-relative paths (models/foo.onnx) so
    the same file works on the host and inside the container, where the cwd
    differs. Public: scripts/preflight_models.py resolves the same paths to
    check the files exist.
    """
    return path if os.path.isabs(path) else os.path.join(_PROJECT_ROOT, path)


@dataclass
class ModelSpec:
    """One registered model. `class_names` is resolved on first access."""

    name: str
    capability: str
    path: str
    classes_path: Optional[str] = None
    _class_names: Optional[list] = field(default=None, repr=False, compare=False)

    @property
    def class_names(self) -> list:
        """Class-id -> label table for this model.

        Falls back to the built-in table for the capability (COCO-80 for
        detect/segment, ImageNet-1k for classify) when the entry declares no
        `classes` file.
        """
        if self._class_names is None:
            if self.classes_path is None:
                self._class_names = _BUILTIN_CLASS_NAMES[self.capability]
            else:
                self._class_names = _read_class_names(self.classes_path, self.name)
        return self._class_names

    def label(self, class_id: int) -> str:
        """class_id -> label, tolerating a table shorter than the model's
        class count (see engines.base.class_label)."""
        return class_label(self.class_names, class_id)


@dataclass
class Registry:
    models: dict          # name -> ModelSpec
    defaults: dict        # capability -> name
    source: str           # the registry file path, or "env" for the fallback


_registry: Optional[Registry] = None
_registry_lock = threading.Lock()


def _read_class_names(path: str, model_name: str) -> list:
    resolved = abs_path(path)
    try:
        with open(resolved, "r", encoding="utf-8") as fh:
            names = [line.strip() for line in fh if line.strip()]
    except OSError as exc:
        raise RegistryConfigError(
            "model %r: cannot read classes file %s: %s" % (model_name, resolved, exc)
        ) from exc
    if not names:
        raise RegistryConfigError(
            "model %r: classes file %s is empty" % (model_name, resolved)
        )
    return names


def registry_path() -> str:
    """Where the registry file is expected. Read at call time, not import."""
    return abs_path(os.environ.get("INFERFORGE_REGISTRY_PATH") or DEFAULT_REGISTRY_FILE)


def _env_fallback() -> Registry:
    models = {}
    defaults = {}
    for name, capability, env_var, filename in _ENV_FALLBACK:
        path = os.environ.get(env_var) or os.path.join("models", filename)
        models[name] = ModelSpec(name=name, capability=capability, path=path)
        defaults[capability] = name
    return Registry(models=models, defaults=defaults, source="env")


def _parse(raw: dict, source: str) -> Registry:
    if not isinstance(raw, dict):
        raise RegistryConfigError("%s: top level must be a mapping" % source)

    unknown = set(raw) - {"models", "defaults"}
    if unknown:
        # Loud on typos: `default:` instead of `defaults:` would otherwise
        # silently leave every capability guessing its default.
        raise RegistryConfigError(
            "%s: unknown top-level key(s) %s (expected 'models' and 'defaults')"
            % (source, ", ".join(sorted(unknown)))
        )

    entries = raw.get("models")
    if not isinstance(entries, dict) or not entries:
        raise RegistryConfigError("%s: 'models' must be a non-empty mapping" % source)

    models = {}
    for name, entry in entries.items():
        if not isinstance(entry, dict):
            raise RegistryConfigError("%s: model %r must be a mapping" % (source, name))
        capability = entry.get("capability")
        if capability not in CAPABILITIES:
            raise RegistryConfigError(
                "%s: model %r has capability %r, expected one of %s"
                % (source, name, capability, ", ".join(CAPABILITIES))
            )
        path = entry.get("path")
        if not isinstance(path, str) or not path:
            raise RegistryConfigError("%s: model %r needs a non-empty 'path'" % (source, name))
        classes_path = entry.get("classes")
        if classes_path is not None and (not isinstance(classes_path, str) or not classes_path):
            raise RegistryConfigError(
                "%s: model %r has an empty 'classes' path" % (source, name)
            )
        models[str(name)] = ModelSpec(
            name=str(name), capability=capability, path=path, classes_path=classes_path
        )

    declared = raw.get("defaults") or {}
    if not isinstance(declared, dict):
        raise RegistryConfigError("%s: 'defaults' must be a mapping" % source)
    for capability, name in declared.items():
        if capability not in CAPABILITIES:
            raise RegistryConfigError(
                "%s: defaults has unknown capability %r" % (source, capability)
            )
        if name not in models:
            raise RegistryConfigError(
                "%s: defaults.%s points at unregistered model %r" % (source, capability, name)
            )
        if models[name].capability != capability:
            raise RegistryConfigError(
                "%s: defaults.%s points at %r, which is a %s model"
                % (source, capability, name, models[name].capability)
            )

    defaults = dict(declared)
    for capability in CAPABILITIES:
        if capability in defaults:
            continue
        candidates = [s.name for s in models.values() if s.capability == capability]
        if len(candidates) == 1:
            defaults[capability] = candidates[0]
        elif len(candidates) > 1:
            # Never let dict ordering decide which model is the default.
            raise RegistryConfigError(
                "%s: %d %s models registered (%s) but defaults.%s is not set"
                % (source, len(candidates), capability, ", ".join(sorted(candidates)), capability)
            )

    return Registry(models=models, defaults=defaults, source=source)


def _load_file(path: str) -> Registry:
    try:
        import yaml  # deferred: the env fallback must work without PyYAML installed
    except ImportError as exc:
        raise RegistryConfigError(
            "PyYAML is required to read %s (pip install -r requirements.txt)" % path
        ) from exc

    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
    except OSError as exc:
        raise RegistryConfigError("cannot read %s: %s" % (path, exc)) from exc
    except yaml.YAMLError as exc:
        raise RegistryConfigError("cannot parse %s: %s" % (path, exc)) from exc

    return _parse(raw or {}, path)


def load() -> Registry:
    """The parsed registry, cached for the life of the process."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                path = registry_path()
                explicit = bool(os.environ.get("INFERFORGE_REGISTRY_PATH"))
                if os.path.isfile(path):
                    registry = _load_file(path)
                    stale = [v for _, _, v, _ in _ENV_FALLBACK if os.environ.get(v)]
                    if stale:
                        logger.warning(
                            "registry %s is in use; ignoring %s", path, ", ".join(stale)
                        )
                    logger.info(
                        "model registry loaded from %s: %d model(s)", path, len(registry.models)
                    )
                elif explicit:
                    # An explicitly configured path that does not exist is a
                    # typo, not a request for the fallback.
                    raise RegistryConfigError(
                        "INFERFORGE_REGISTRY_PATH points at %s, which does not exist" % path
                    )
                else:
                    registry = _env_fallback()
                    logger.info("no registry file at %s; using env-var model paths", path)
                _registry = registry
    return _registry


def reset_cache() -> None:
    """Drop the cached registry (tests; nothing reloads it at runtime)."""
    global _registry
    with _registry_lock:
        _registry = None


def default_name(capability: str) -> str:
    """The model a request gets when it names none. Raises ModelNotFound if
    the capability has no registered model at all."""
    name = load().defaults.get(capability)
    if name is None:
        raise ModelNotFound("no %s model is registered" % capability)
    return name


def resolve(model: Optional[str], capability: str) -> ModelSpec:
    """Look up the spec a request means. `model=None` -> the capability default."""
    registry = load()
    name = model if model else default_name(capability)
    spec = registry.models.get(name)
    if spec is None:
        known = sorted(s.name for s in registry.models.values() if s.capability == capability)
        raise ModelNotFound(
            "unknown model '%s'; registered %s models: %s"
            % (name, capability, ", ".join(known) if known else "(none)")
        )
    if spec.capability != capability:
        raise ModelNotFound(
            "model '%s' is a %s model and cannot serve a %s request"
            % (name, spec.capability, capability)
        )
    return spec


def specs_for(capability: str) -> list:
    """Every registered model of one capability (preflight, diagnostics)."""
    return [s for s in load().models.values() if s.capability == capability]


def all_specs() -> list:
    """Every registered model, in registry order."""
    return list(load().models.values())
