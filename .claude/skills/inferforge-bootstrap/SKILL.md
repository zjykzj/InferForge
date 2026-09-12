---
name: inferforge-bootstrap
description: 从 InferForge 模板初始化一个新业务工程——按需装配（scripts/assemble.py 正向清单）到目标路径后的改名、配置初始化与底座验收。当需要基于 InferForge 模板新建服务、初始化工程、或选择能力/特性时使用。完整知识与取舍说明见 docs/workflow/bootstrap.md。
---

# 从模板初始化新工程

完整知识与取舍说明见 `docs/workflow/bootstrap.md`——本技能只规定流程与验收，不重复解释。

## 步骤（严格按序，每步完成后再进入下一步）

1. **问目标路径、能力与机制**：用户未给新工程路径时先追问；未说能力时确认选择清单；**横切机制逐个确认**（metrics / auth / 限流 / 日志，默认都不要——"先检查、再确认"）
2. **按需装配**：`python3 <模板目录>/scripts/assemble.py --target <路径> --with <能力,机制> --features <特性>`（`docs/workflow/bootstrap.md` §2/§4——正向清单，未选的文件根本不存在；依赖自动展开；requirements.txt 由所选条目的依赖声明合并生成）
3. **身份生成**：按 `docs/workflow/bootstrap.md` §3 为新工程**生成**身份文件（不是复制模板的）——README（服务名 + 启动/测试命令）、CLAUDE.md（硬规则精简 + 模板 docs 指针）；CHANGELOG/VERSION 首次发布时再生成；LICENSE 问用户；改 base 内残留（`app.py` title）
4. **配置**：`.env.example` → `.env`、模型文件放 `models/`（`docs/workflow/bootstrap.md` §5——registry.yaml 装配时已按所选能力生成）
5. **初始化仓库**：目标路径 `git init` + 首次提交
6. **验收**：完成标准逐项过（pytest / py_compile / GET /health；check_capability 仅在有模型能力时）
7. **知识层**：业务规则从此持续写进新工程的 CLAUDE.md/README（活文档随业务生长，`docs/workflow/bootstrap.md` §7）

## 完成标准（done 的定义，全部满足才算完成）

- `pytest tests/ -q` 全绿
- `python3 -m py_compile app.py apis/*.py tasks/*.py engines/*.py utils/*.py tests/*.py scripts/*.py` 干净
- `python3 scripts/check_capability.py` 通过（base-only 装配无 registry，输出跳过提示即正常）
- `python3 app.py` 起服务，`GET /health` 返回 200

## 后续

- 提示用户在**目标路径**启动后续会话（CLAUDE.md/docs/tests 上下文来自新工程）
- 新增业务能力 → 使用 `inferforge-add-capability` 技能
- 修改已有服务 → 使用 `inferforge-modify-service` 技能
