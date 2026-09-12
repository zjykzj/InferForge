---
name: inferforge-bootstrap
description: 从 InferForge 模板初始化一个新业务工程——按需装配（scripts/assemble.py 正向清单）到目标路径后的改名、配置初始化与底座验收。当需要基于 InferForge 模板新建服务、初始化工程、或选择能力/特性时使用。完整知识与取舍说明见 docs/workflow/bootstrap.md。
---

# 从模板初始化新工程

完整知识与取舍说明见 `docs/workflow/bootstrap.md`——本技能只规定流程与验收，不重复解释。

## 步骤（严格按序，每步完成后再进入下一步）

1. **问目标路径与能力**：用户未给新工程路径时先追问；未说能力时确认选择清单（默认仅 base = 服务外壳 + 健康探针，无业务能力；常用组合如 `detect`、`detect,async`）
2. **按需装配**：`python3 <模板目录>/scripts/assemble.py --target <路径> --with <能力> --features <特性>`（`docs/workflow/bootstrap.md` §2/§4——正向清单，未选的文件根本不存在；依赖自动展开）
3. **改名**：按 `docs/workflow/bootstrap.md` §3 清单逐项执行（`app.py` title、compose image、README badge、CLAUDE.md `{{REPO_URL}}`、VERSION/CHANGELOG）
4. **配置**：`.env.example` → `.env`、模型文件放 `models/`（`docs/workflow/bootstrap.md` §5——registry.yaml 装配时已按所选能力生成）
5. **初始化仓库**：目标路径 `git init` + 首次提交
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
