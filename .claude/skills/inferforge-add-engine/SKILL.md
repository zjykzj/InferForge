---
name: inferforge-add-engine
description: 在 InferForge 新工程中接入一个新的推理引擎（新算法或新推理后端，如 TensorRT/Triton）。当需要替换推理算法、接入新的 ONNX 模型或新推理后端时使用。完整知识与接入步骤见 docs/workflow/add-engine.md。
---

# 接入推理引擎

完整知识与接入步骤见 `docs/workflow/add-engine.md`——本技能只规定流程与验收，不重复解释。

## 步骤（严格按序）

1. **定位确认**：这是引擎层改动（换算法/新后端），上层零改动——先读 `docs/workflow/add-engine.md` §1；task 层拥有预测器，api 层永远不碰
2. **实现 contract**：一个引擎 = 一个 `BasePredictor` 实现，逐项对齐 §2 的结果类型（Detection/Segmentation/Classification）；上层只依赖抽象，从不 import 具体引擎
3. **前后处理自写**：不 import ultralytics（AGPL-3.0）；前后处理纯函数先落单测
4. **接入与注册**：按 §3 接入步骤（以 YOLOv8n 为参照）实现 load/predict；注册到 `models/registry.yaml` + `engines/registry.py` 对应 capability；TensorRT/Triton 注意 §4 的后端差异
5. **验证**：§5 验证清单逐项过

## 完成标准（done 的定义，全部满足才算完成）

- `pytest tests/ -q` 全绿（新引擎的 FakePredictor 冒烟 + 全量无回归）
- `python3 scripts/check_capability.py` 通过
- 模型文件就位后 `python3 scripts/run_<task>.py` 真实推理通过
- 接口或注册表变化时 `docs/api.md` / `docs/model-registry.md` 同步
