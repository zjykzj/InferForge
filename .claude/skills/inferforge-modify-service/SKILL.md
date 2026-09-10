---
name: inferforge-modify-service
description: 修改 InferForge 新工程中已存在的服务——改业务逻辑、改接口参数、或替换推理算法。当需要修改已有接口/任务/算法的实现时使用。完整知识与层级定位见 docs/workflow/modify-service.md。
---

# 修改已有服务

完整知识与层级定位见 `docs/workflow/modify-service.md`——本技能只规定流程与验收，不重复解释。

## 步骤（严格按序）

1. **定位层级**：按 `docs/workflow/modify-service.md` §1 表找到动手层（业务编排 → `tasks/`；参数/响应 → `apis/`；换算法 → `engines/` + task 持有）
2. **区检查**：核对绿黄红区（`docs/workflow/forking-contract.md` §2）——绿区直接做；黄区先读对应文档；红区（`BasePredictor` 签名 / envelope 格式 / 分层方向）停下重新评估
3. **改实现 + 同步改测试**：实现与测试同一次改动完成；冒烟测试沿用 FakePredictor seam
4. **契约类改动双注册**：新增状态码 → `utils/response.py` 文档串 **和** `docs/status-codes.md` 两处；接口变化 → 更新 `docs/api.md`
5. **换算法**：走 `docs/workflow/add-engine.md`（前后处理自写、无 ultralytics import；引擎纯函数先落单测）

## 完成标准（done 的定义，全部满足才算完成）

- `pytest tests/ -q` 全绿（受影响能力的测试 + 全量无回归）
- `python3 scripts/check_capability.py` 通过
- `python3 -m py_compile apis/*.py tasks/*.py engines/*.py utils/*.py scripts/*.py` 干净
- 涉及启动路径 / registry 改动：`./start.sh` 通过

## 红线必查（验收时逐条确认）

- HTTP 永远 200 + `{code, message, data}` envelope；Pydantic 校验失败折叠为 code 1（422 永不泄漏）
- 状态码双注册（`tests/test_architecture.py` 会替你盯着）
- 依赖方向不破坏（`app -> apis -> tasks -> engines`）
