---
name: inferforge-bootstrap
description: 从 InferForge 模板初始化一个新业务工程——fork/clone 后的改名、demo 能力裁剪、配置初始化与底座验收。当需要基于 InferForge 模板新建服务、初始化工程、或裁剪模板自带能力时使用。完整知识与取舍说明见 docs/bootstrap.md。
---

# 从模板初始化新工程

完整知识与取舍说明见 `docs/bootstrap.md`——本技能只规定流程与验收，不重复解释。

## 步骤（严格按序，每步完成后再进入下一步）

1. **复制模板**：fork 或 clone 为新仓库（`docs/bootstrap.md` §2）
2. **改名**：按 `docs/bootstrap.md` §3 清单逐项执行（`app.py` title、compose image、README badge、CLAUDE.md `{{REPO_URL}}`、VERSION/CHANGELOG）
3. **裁剪**：决定 demo 能力去留（`docs/bootstrap.md` §4）——默认保留同形态参照能力直到自建第一个业务能力；确需删除按 8 项删除面清单逐项核对
4. **配置**：`.env.example` → `.env`、`models/registry.example.yaml` → `registry.yaml`、模型文件放 `models/`（`docs/bootstrap.md` §5）
5. **知识层**：新工程的 CLAUDE.md/docs 更新为工程自身身份，业务规则从此持续写进新工程（`docs/bootstrap.md` §7）

## 完成标准（done 的定义，全部满足才算完成）

- `pytest tests/ -q` 全绿
- `python3 -m py_compile app.py apis/*.py tasks/*.py engines/*.py utils/*.py tests/*.py scripts/*.py` 干净
- `python3 scripts/check_capability.py` 通过
- `python3 app.py` 起服务，`GET /health` 返回 200

## 后续

- 新增业务能力 → 使用 `inferforge-add-capability` 技能
- 修改已有服务 → 使用 `inferforge-modify-service` 技能
