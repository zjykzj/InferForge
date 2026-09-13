---
name: inferforge-bootstrap
description: 从 InferForge 模板初始化一个新业务工程——按需装配（scripts/assemble.py 正向清单 + profile 分档）到目标路径后的改名、配置初始化与底座验收。当需要基于 InferForge 模板新建服务、初始化工程、或选择能力/特性时使用。完整知识与取舍说明见 docs/workflow/bootstrap.md。
---

# 从模板初始化新工程

完整知识与取舍说明见 `docs/workflow/bootstrap.md`——本技能只规定流程与验收，不重复解释。**步骤是确定性脚本，不是自由发挥：每条命令原样执行，失败即停下报告，不得跳过或临场改写装配方式。**

## 步骤（严格按序，每步完成后再进入下一步）

1. **问目标路径、profile 与能力**：用户未给新工程路径时先追问；确认 profile——`bare`（最小内核：FastAPI + 健康探针，无 envelope/request_id/dotenv）/ `kernel`（契约内核，默认）/ `production`（kernel + metrics/auth/限流/日志）——与能力清单（未说的默认不要）。**机制不逐个确认**：机制集合由 profile 决定，个别机制用 `--with` 叠加
2. **装配（守卫由脚本执行，不是 Agent 判断）**：`python3 <模板目录>/scripts/assemble.py --target <路径> --profile <profile> --with <能力> --features <特性>`——目标目录不存在会自动创建；**已存在且非空时脚本直接拒绝**（报"已有工程"提示）。脚本拒绝时停下来问用户换路径或清空目录，**禁止绕过脚本手工复制文件**
3. **身份生成**：按 `docs/workflow/bootstrap.md` §3 为新工程**生成**身份文件（不是复制模板的）——README（服务名 + 启动/测试命令）、CLAUDE.md（硬规则精简 + 模板 docs 指针）；CHANGELOG/VERSION 首次发布时再生成；LICENSE 问用户；改 base 内残留（`app.py` 的 `title`；kernel 及以上还有 `description`）
4. **配置**：装配含 dotenv 机制（kernel/production/任何能力装配，见 capability_contract）时 `.env.example` → `.env`；模型文件放 `models/`（`docs/workflow/bootstrap.md` §5——registry.yaml 装配时已按所选能力生成）；bare 装配没有 `.env.example`，跳过本步的 .env 部分
5. **初始化仓库**：目标路径 `git init` + 首次提交
6. **验收**：完成标准逐项过——bare 装配的 `/health` 返回 `{"status":"ok"}`；kernel 及以上返回 `{"code":0,...}` envelope
7. **知识层**：业务规则从此持续写进新工程的 CLAUDE.md/README（活文档随业务生长，`docs/workflow/bootstrap.md` §7）

## 完成标准（done 的定义，全部满足才算完成）

- `pytest tests/ -q` 全绿
- `python3 -m py_compile app.py apis/*.py tasks/*.py engines/*.py utils/*.py tests/*.py scripts/*.py` 干净
- `python3 scripts/check_capability.py` 通过（无模型能力的装配无 registry，输出跳过提示即正常）
- `python3 app.py` 起服务，`GET /health` 返回 200
- 装配过程走的是 `assemble.py` 脚本——目标守卫、profile 展开、依赖闭包全部由脚本执行

## 后续

- 提示用户在**目标路径**启动后续会话（CLAUDE.md/docs/tests 上下文来自新工程）
- 新增业务能力 → 使用 `inferforge-add-capability` 技能
- 修改已有服务 → 使用 `inferforge-modify-service` 技能
