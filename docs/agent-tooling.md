# Agent 开发工具形态调研（Agent Tooling Landscape）

> 领域知识文档：业界如何落地 Agent 驱动的开发工具——三种形态（Agent 原生脚手架 / 自研 agent 平台 / 混合 MCP）、各自适用场景与代表实践、AGENTS.md 跨工具指令标准，**不描述本工程的实现**——InferForge 的形态定位见 §5，实现状态在各节末尾标注（对照 [generator-packaging.md](generator-packaging.md) 与 [scaffolding.md](scaffolding.md)）。最后更新：2026-09-13

## 1. 背景：一个需求，三种落地形态

公司级需求："针对具体需求提供具体模板，不需要额外开发"——同一需求，业界有三条落地路径：

| 形态 | 组成 | 典型场景 |
|------|------|---------|
| ① Agent 原生脚手架 | 模板仓库 + 指令文件（CLAUDE.md / AGENTS.md）+ skills/commands + 确定性脚本 | 开发者的现成 coding agent 按公司 golden path 初始化/开发 |
| ② 自研 agent 平台 | Pydantic AI / LangGraph / CrewAI 等框架自建编排 | 内部开发平台（IDP）产品化"AI 软件工厂" |
| ③ 混合（MCP） | 现成 agent + 公司侧 MCP server（暴露模板、数据库、内部工具） | 大厂平台团队把内部能力开放给市面上的 agent |

## 2. 形态①：Agent 原生脚手架（模板生成的主流）

**组成**：模板仓库 + 指令文件 + 接入层 + 确定性脚本。公司不建 agent，而是建"任何 agent 都能执行的指令与脚本"。

- 指令文件：CLAUDE.md（Claude Code）、AGENTS.md（跨工具标准，Codex / Copilot 等支持）、.cursor/rules（Cursor）
- 接入层：skills / slash commands / custom agents——把流程固化为确定性步骤
- 确定性脚本：脚手架、守卫、自证——agent 只调用，不生成

**为什么模板生成走这条路**：模板生成的本质是**确定性脚手架 + 意图解析**。意图解析（"初始化服务、要哪些能力"）现成 coding agent 已经足够好；自研编排的价值在多步、有状态、需治理的工作流（规划-实现-审查循环），而不是一次性代码生成——与 [generator-packaging.md](generator-packaging.md) §3 的结论同源：框架的收益随"工具数量 × 会话深度"增长，脚手架场景都不高。

（实现状态：InferForge 即此形态——workflow 文档 + `.claude/skills/` + `assemble.py`，见 §5。）

## 3. 形态②：自研 agent 平台（重形态）

**组成**：用 agent 框架（Pydantic AI / LangGraph / CrewAI 等）编排 LLM，自建多步工作流——issue 解析 → 规划 → 多步实现 → 审查 → 部署，带审批门（human-in-the-loop）、审计日志、Jira/CI 集成、多 agent 协作。

**适用场景**：公司要把 **agent 本身产品化**——"AI 软件工厂"作为平台对外服务，工作流是产品的一部分，需要治理与可观测。Pydantic AI 这类框架的价值点（类型化结构输出、依赖注入、可测试性）在此才真正兑现。

**为什么模板生成不走这条路**：一次性无状态的代码生成不需要编排引擎；自研平台的成本（框架、运维、治理）与脚手架场景的价值不匹配。

（实现状态：InferForge 不自建 agent 平台——bootstrap 流程的编排就是 skill 里的确定性步骤序列，见 workflow/bootstrap.md。）

## 4. 形态③：混合（MCP）

**组成**：公司侧起 MCP server，把内部 golden path、模板服务、数据库、内部工具暴露为工具集；agent 侧用现成的 MCP 客户端（Claude Code / IDE 插件）消费。

**意义**：不建 agent、不绑定任何一家——把能力暴露给市面上的 agent。选择矩阵（何时 HTTP、何时 MCP）见 [generator-packaging.md](generator-packaging.md) §6/§7。

## 5. 本工程的形态定位

InferForge = **形态① + 工具无关分层**：

```
docs/workflow/*.md   # 中性知识（≈ AGENTS.md 承载的内容）——工具无关
.claude/skills/      # Claude Code 专属接入层（把流程固化为确定性步骤）
scripts/assemble.py  # 确定性核心——任何 agent 都只是调用它
```

工具无关性是最前瞻的一笔：**如果哪天要让 Codex / Copilot 也按本流程干活，只需把 workflow 文档的指针挂进 AGENTS.md，确定性脚本一行不动。**

（实现状态：已落地——workflow 文档、skills、CLAUDE.md 三层各就各位；未提供 AGENTS.md，触发条件见 §6。）

## 6. AGENTS.md 与指令文件标准

业界正在收敛一个跨工具的指令文件标准 **AGENTS.md**（Codex、Copilot 等多方支持，相当于通用版的 CLAUDE.md）：仓库根放一份 agent 开发指南，任何支持该标准的编码 agent 读它开局。

与本工程的关系：CLAUDE.md（Claude Code 指令）+ workflow 文档（中性知识）已经是分层正确的等价物；**新增一个 AGENTS.md 的成本只是一份指针文件**（指向 docs/README.md 入口表与 workflow 文档），不产生任何内容重复。

（实现状态：未提供 AGENTS.md——当前 canonical 载体是 Claude Code；需要支持其他编码 agent 时补一份指针文件即可。）

## 7. 与其它文档的分工

- [scaffolding.md](scaffolding.md)：确定性生成器侧的业界工具（Copier/Yeoman/Initializr…）——生成器怎么做
- [generator-packaging.md](generator-packaging.md)：生成器怎么被 Agent 调用（CLI/HTTP/MCP）——接口在哪
- 本文：业界公司怎么落地 Agent 驱动的开发工具（三种形态 + AGENTS.md）——生态怎么落地
