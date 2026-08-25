"""Tests for engines.registry — pure metadata, no model files needed.

The autouse conftest fixture points INFERFORGE_REGISTRY_PATH at a per-test
tmp file; these tests overwrite it with their own fixtures and drop the
cache via registry.reset_cache(). The env-var fallback test deletes the
override entirely and repoints the DEFAULT registry file location, so it is
immune to a dev machine having a real models/registry.yaml.
"""
import pytest

from engines import registry
from tasks import segmentation
from utils.errors import ModelNotFound, RegistryConfigError


def _use_registry(monkeypatch, tmp_path, text):
    path = tmp_path / "registry.yaml"
    path.write_text(text)
    monkeypatch.setenv("INFERFORGE_REGISTRY_PATH", str(path))
    registry.reset_cache()
    return path


# --- parsing ---


def test_parse_and_resolve(tmp_path, monkeypatch):
    _use_registry(monkeypatch, tmp_path, """
defaults:
  detect: yolov8n
models:
  yolov8n:
    capability: detect
    path: models/yolov8n.onnx
""")
    spec = registry.resolve(None, "detect")
    assert spec.name == "yolov8n"
    assert spec.capability == "detect"
    assert spec.path == "models/yolov8n.onnx"
    assert spec.class_names[0] == "person"  # built-in COCO fallback
    assert registry.default_name("detect") == "yolov8n"


def test_single_model_implies_default(tmp_path, monkeypatch):
    _use_registry(monkeypatch, tmp_path, """
models:
  only:
    capability: classify
    path: models/only.onnx
""")
    assert registry.default_name("classify") == "only"
    assert registry.resolve("only", "classify").name == "only"


def test_multiple_models_need_defaults(tmp_path, monkeypatch):
    _use_registry(monkeypatch, tmp_path, """
models:
  a:
    capability: detect
    path: models/a.onnx
  b:
    capability: detect
    path: models/b.onnx
""")
    with pytest.raises(RegistryConfigError):
        registry.load()


def test_unknown_model_raises(tmp_path, monkeypatch):
    _use_registry(monkeypatch, tmp_path, """
models:
  yolov8n:
    capability: detect
    path: models/yolov8n.onnx
""")
    with pytest.raises(ModelNotFound):
        registry.resolve("nope", "detect")


def test_capability_mismatch_raises(tmp_path, monkeypatch):
    _use_registry(monkeypatch, tmp_path, """
models:
  yolov8n:
    capability: detect
    path: models/yolov8n.onnx
""")
    with pytest.raises(ModelNotFound):
        registry.resolve("yolov8n", "classify")


def test_capability_without_models_raises(tmp_path, monkeypatch):
    _use_registry(monkeypatch, tmp_path, """
models:
  yolov8n:
    capability: detect
    path: models/yolov8n.onnx
""")
    with pytest.raises(ModelNotFound):
        registry.default_name("classify")


def test_readiness_probe_false_when_no_models_registered(tmp_path, monkeypatch):
    # /health/ready asks the task layer; a capability with no registered
    # model reports not-loaded instead of raising (probes must not crash).
    _use_registry(monkeypatch, tmp_path, """
models:
  yolov8n:
    capability: detect
    path: models/yolov8n.onnx
""")
    assert segmentation.default_model_loaded() is False


def test_defaults_must_point_at_matching_capability(tmp_path, monkeypatch):
    _use_registry(monkeypatch, tmp_path, """
defaults:
  classify: yolov8n
models:
  yolov8n:
    capability: detect
    path: models/yolov8n.onnx
""")
    with pytest.raises(RegistryConfigError):
        registry.load()


def test_unknown_top_level_key_rejected(tmp_path, monkeypatch):
    # a `default:` typo must not silently drop the default configuration
    _use_registry(monkeypatch, tmp_path, """
default: yolov8n
models:
  yolov8n:
    capability: detect
    path: models/yolov8n.onnx
""")
    with pytest.raises(RegistryConfigError):
        registry.load()


def test_bad_yaml_raises(tmp_path, monkeypatch):
    _use_registry(monkeypatch, tmp_path, "models: [unclosed")
    with pytest.raises(RegistryConfigError):
        registry.load()


# --- per-model class names ---


def test_classes_file_overrides_builtin(tmp_path, monkeypatch):
    classes = tmp_path / "classes.txt"
    classes.write_text("scratch\ndent\ncrack\n")
    _use_registry(monkeypatch, tmp_path, """
models:
  defect:
    capability: detect
    path: models/defect.onnx
    classes: %s
""" % classes)
    spec = registry.resolve("defect", "detect")
    assert spec.class_names == ["scratch", "dent", "crack"]
    assert spec.label(1) == "dent"


def test_missing_classes_file_raises(tmp_path, monkeypatch):
    _use_registry(monkeypatch, tmp_path, """
models:
  defect:
    capability: detect
    path: models/defect.onnx
    classes: models/nope.txt
""")
    spec = registry.resolve("defect", "detect")
    with pytest.raises(RegistryConfigError):
        spec.class_names  # resolved lazily on first access


# --- env-var fallback (no registry file -> historical single-model behavior) ---


def test_env_fallback_synthesizes_historical_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("INFERFORGE_MODEL_PATH", "models/custom.onnx")
    monkeypatch.delenv("INFERFORGE_REGISTRY_PATH", raising=False)
    # The autouse fixture already deleted nothing but set the env; point the
    # DEFAULT file location at a nonexistent path so the fallback triggers
    # regardless of any real models/registry.yaml on the dev machine.
    monkeypatch.setattr(registry, "DEFAULT_REGISTRY_FILE", str(tmp_path / "absent.yaml"))
    registry.reset_cache()

    assert registry.load().source == "env"
    assert registry.default_name("detect") == "yolov8n"
    assert registry.resolve(None, "detect").path == "models/custom.onnx"
    assert registry.default_name("segment") == "yolov8n-seg"
    assert registry.default_name("classify") == "yolov8n-cls"


def test_env_fallback_uses_historical_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("INFERFORGE_REGISTRY_PATH", raising=False)
    monkeypatch.setattr(registry, "DEFAULT_REGISTRY_FILE", str(tmp_path / "absent.yaml"))
    registry.reset_cache()

    assert registry.resolve("yolov8n", "detect").path.endswith("models/yolov8n.onnx")
    assert registry.resolve("yolov8n-cls", "classify").path.endswith("models/yolov8n-cls.onnx")


def test_explicit_registry_path_missing_hard_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("INFERFORGE_REGISTRY_PATH", str(tmp_path / "absent.yaml"))
    registry.reset_cache()
    with pytest.raises(RegistryConfigError):
        registry.load()


def test_yaml_source_ignores_env_path_vars(tmp_path, monkeypatch):
    monkeypatch.setenv("INFERFORGE_MODEL_PATH", "models/should-not-win.onnx")
    _use_registry(monkeypatch, tmp_path, """
models:
  yolov8n:
    capability: detect
    path: models/from-yaml.onnx
""")
    assert registry.resolve(None, "detect").path == "models/from-yaml.onnx"


# --- out-of-range class ids degrade, not crash ---


def test_label_out_of_range_falls_back(tmp_path, monkeypatch):
    classes = tmp_path / "classes.txt"
    classes.write_text("only-one\n")
    _use_registry(monkeypatch, tmp_path, """
models:
  small:
    capability: detect
    path: models/small.onnx
    classes: %s
""" % classes)
    spec = registry.resolve("small", "detect")
    assert spec.label(0) == "only-one"
    assert spec.label(7) == "class_7"  # mismatch degrades the label, not the request
