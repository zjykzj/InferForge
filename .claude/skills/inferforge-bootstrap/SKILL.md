---
name: inferforge-bootstrap
description: 从 InferForge 模板初始化一个新业务工程——复制模板到目标路径后的改名、demo 能力裁剪、配置初始化与底座验收。当需要基于 InferForge 模板新建服务、初始化工程、或裁剪模板自带能力时使用。完整知识与取舍说明见 docs/workflow/bootstrap.md。
---

# 从模板初始化新工程

完整知识与取舍说明见 `docs/workflow/bootstrap.md`——本技能只规定流程与验收，不重复解释。

## 步骤（严格按序，每步完成后再进入下一步）

1. **问目标路径**：用户未给新工程路径时先追问。模板目录只读——复制、初始化与后续开发全部发生在目标路径，模板本身永不修改
2. **复制模板**：`cp -r` 模板到目标路径，`rm -rf .git && git init` + 首次提交（`docs/workflow/bootstrap.md` §2）
3. **改名**：按 `docs/workflow/bootstrap.md` §3 清单逐项执行（`app.py` title、compose image、README badge、CLAUDE.md `{{REPO_URL}}`、VERSION/CHANGELOG）
4. **裁剪**：决定 demo 能力去留（`docs/workflow/bootstrap.md` §4）——默认保留同形态参照能力直到自建第一个业务能力；确需删除按 8 项删除面清单逐项核对
5. **配置**：`.env.example` → `.env`、`models/registry.example.yaml` → `registry.yaml`、模型文件放 `models/`（`docs/workflow/bootstrap.md` §5）
6. **验收**：完成标准逐项过（pytest / py_compile / check_capability / GET /health）
7. **知识层**：新工程的 CLAUDE.md/docs 更新为工程自身身份，业务规则从此持续写进新工程（`docs/workflow/bootstrap.md` §7）

## 完成标准（done 的定义，全部满足才算完成）

- `pytest tests/ -q` 全绿
- `python3 -m py_compile app.py apis/*.py tasks/*.py engines/*.py utils/*.py tests/*.py scripts/*.py` 干净
- `python3 scripts/check_capability.py` 通过
- `python3 app.py` 起服务，`GET /health` 返回 200

## 后续

- 提示用户在**目标路径**启动后续会话（CLAUDE.md/docs/tests 上下文来自新工程）
- 新增业务能力 → 使用 `inferforge-add-capability` 技能
- 修改已有服务 → 使用 `inferforge-modify-service` 技能
