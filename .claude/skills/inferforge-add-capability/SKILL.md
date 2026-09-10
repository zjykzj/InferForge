---
name: inferforge-add-capability
description: 在 InferForge 新工程中新增一个业务能力（接口/任务/算法）。当需要新增同步接口、异步任务（callback/query）、query-only 任务，或实现模板没有参照的新功能时使用。完整知识与形态取舍见 docs/workflow/add-capability.md。
---

# 新增业务能力

完整知识与形态取舍见 `docs/workflow/add-capability.md`——本技能只规定流程与验收，不重复解释。

## Step 0：选形态（必做，不要跳过）

按 `docs/workflow/add-capability.md` §2 决策表选：同步 / 异步 callback / 异步 query / query-only。模板没有同形态参照时走 §6 契约推导路径（从 `BasePredictor` + envelope + 分层公理组合，测试当契约）。

## 步骤

1. **引擎**（新算法时）：`engines/<name>.py` 按 `docs/workflow/add-engine.md`（canonical：`engines/yolo.py`；重型依赖 import 在函数体内）
2. **registry**：`models/registry.yaml` 加条目（capability + path + classes）+ `defaults`
3. **task**：`tasks/<name>.py`（canonical：`tasks/detection.py`——`get_predictor` 懒加载三件套 + 编排函数 + `default_model_loaded`）
4. **schemas + api**：结构校验进 `apis/schemas.py`；路由 `apis/sync_<name>.py`（canonical：`apis/sync_detect.py`；try/except 阶梯顺序固定：ModelNotFound → ValueError → RequestException → Exception）
5. **装配**：`app.py` 开关函数 + 门控 import + `include_router`；`scripts/preflight_models.py` 的 `CAPABILITY_SWITCH` 加条目
6. **异步变体**：`shared_task`（不 import celery_app）+ submit 时 `validate_model` 同步拒绝 code 10 + `submitted_at` 打点（canonical：`tasks/detection_callback.py`）；query-only 无 sync/callback、worker-only 依赖懒加载（canonical：`tasks/vlm.py`）
7. **测试**：`tests/test_<name>.py` FakePredictor seam（canonical：`tests/test_sync_detect.py`）
8. **脚本**：`scripts/run_<name>.py`（task 层直调）+ `scripts/test_<name>.py`（HTTP 调用）
9. **指标**：`observe_phase(task="<name>")`、`mark_predictor_loaded(task=..., model=...)`
10. **文档 + CHANGELOG**：`docs/api.md` 接口小节、`docs/README.md` 索引

## 完成标准（done 的定义，全部满足才算完成）

- `pytest tests/ -q` 全绿（无回归）
- `python3 scripts/check_capability.py` 通过（footprint 无遗漏）
- `python3 -m py_compile apis/*.py tasks/*.py engines/*.py utils/*.py` 干净
- 涉及启动路径：`./start.sh` preflight 通过（注册模型文件在盘）
