# 生成器包装轴：CLI / HTTP / MCP 与 Agent 集成取舍（Generator Packaging）

> 领域知识文档：LLM Agent 如何消费"确定性生成器"——包装形态谱系（CLI / HTTP / MCP）、"Agent + MCP 模板服务化"方案的评估、HTTP vs MCP 的选择矩阵，**不描述本工程的实现**——InferForge 当前形态与未采纳决策见 §5/§7（全景对照见 [scaffolding.md](scaffolding.md)，机制实现见 [assembly.md](assembly.md)）。最后更新：2026-09-13

## 1. 背景：一个需求，两种说法

同一个需求——"基于模板工程 + Agent 生成新工程，精确、不冗余、不复制粘贴"——业界讨论中有两种常见表述：

- **"确定性生成器 + Agent 做胶水"**：底层抽象——生成权归确定性引擎（模板/DSL/脚本），Agent 负责意图理解与编排
- **"Agent + MCP 模板服务化"**：落地主张——把模板库抽象为 MCP 工具集（如 `init-fastapi-service`、`add-onnx-classification-endpoint`），Agent 经 JSON-RPC 调用、参数注入、精确写入

两者是不是一回事？哪条路更有效？本文的结论：**同一理念的两种表述——但"服务化"只是包装选择，MCP 只是其中一种包装；对模板生成这种一次性无状态场景，MCP 通常是性价比较低的那种。** 本文逐层拆解这个结论。

## 2. 两个正交的轴

"谁写代码"与"怎么被调用"是两个互不相干的决策，被混为一谈是所有争论的来源：

| 轴 | 问题 | 选项 | 共识 |
|----|------|------|------|
| **生成权** | 核心脚手架由谁写 | LLM 自由发挥（概率）vs 确定性引擎（确定） | 业界共识明确：核心脚手架确定性生成——LLM 的本质是概率性的，自由发挥必然产生结构不可控与"同义异表"。这一条两边没有分歧 |
| **包装** | 生成器怎么被调用 | CLI / HTTP API / MCP | **与确定性无关**——同一个确定性引擎可以用任意包装 |

"Agent + MCP 模板服务化"的错误印象在于把包装轴的某一选项（MCP）当成架构升级：传输层改变不了生成器本身的确定性。**换包装不换确定性；换确定性才是架构问题。**

## 3. 业界事实：主流 scaffolders 用什么包装

| 工具 | 包装 | 形态 |
|------|------|------|
| Copier | CLI | Python 包，本地执行，`copier update` 回放 |
| Yeoman | CLI | Node 生成器框架 |
| Nx generators / Angular schematics | CLI | 本地 AST 变换 |
| create-\* 家族 | CLI | 固定 flag + 固定文件内容 |
| Spring Initializr | HTTP API | start.spring.io，被全球客户端（人/脚本/CI/Agent）消费 |
| Backstage Software Templates | HTTP 服务 | 企业内部 golden path 目录 |
| **MCP 分发** | — | **无主流先例** |

MCP 生态的强项是**有状态、长会话、流式**工具（浏览器、数据库、IDE、长任务）——工具发现协议的价值随"工具数量 × 会话深度"增长。一次性无状态的代码生成（请求 → 文件）不在此列，这就是为什么脚手架世界没有 MCP。

## 4. "Agent + MCP 模板服务化"方案评估

**说得对的部分：**

- **工具级拆解**：按场景拆分确定工具（init / add / modify）——方向正确，与"固定场景固定实现"一致
- **职责分离**：Agent 做意图理解，确定性层做数据处理——即 §2 生成权轴的共识
- **参数注入**：endpoint_name / model_path 等参数由确定模板渲染——正确做法

**不准确的部分：**

- "**MCP 是确定性生成器最标准的实现形态**"——事实错误（§3）：MCP 是给 LLM 客户端的工具发现协议，不是代码生成架构
- "**告别复制粘贴是 MCP 的功劳**"——因果倒置：精确 vs 复制粘贴由生成器设计决定（正向 include-list、marker 剥离、覆盖守护），与传输协议无关。CLI 可以精确生成，MCP 工具同样可以照抄
- "**100% 符合工程规范**"——规范由生成器 + 测试保证（生成物自证），协议层保证不了任何东西

**值得吸收的部分：**

- **Vision Agent 端到端验证**（生成接口后对运行结果做截图/语义验证）——有价值，但属于**新工程的业务开发环**（add-capability 的验收环节），不属于生成器本身；当前对应物是 `scripts/test_sync_*.py` 的 API 级验证。将来可在 add-capability 验收中吸收"视觉语义验证"这一步

## 5. 当前形态对照：InferForge = CLI + Agent

```
Agent（Claude Code）→ skill（确定性步骤指令）→ CLI（assemble.py / check_assembly.py）→ 文件系统
```

Agent 调用 CLI 的接口就是自身的 Bash 工具——"Agent 调用确定性工具"这一层已经存在，无需再包一层协议。网上的 MCP 工具清单与当前实现一一对应：

| 网上方案的 MCP 工具 | InferForge 已有实现 |
|-------------------|-------------------|
| `init-fastapi-service`（纯净 FastAPI，无业务冗余） | `--profile bare`——约 50 行 app.py + 健康探针，正是"单纯创建 FastAPI 服务，不要多余代码" |
| `add-onnx-classification-endpoint`（参数注入业务代码） | cls 能力装配 + `inferforge-add-capability` skill（canonical 参照、footprint 清单、逐层步骤） |
| "生成代码 100% 符合工程规范" | wiring 全覆盖守护 + 六装配自证（py_compile + pyflakes + pytest），CI 逐字节验证 |
| "要什么给什么，不要的绝对没有" | 正向 include-list：未选的文件根本不存在 |

## 6. HTTP vs MCP：Agent 消费视角

| 维度 | MCP | 纯 HTTP API |
|------|-----|------------|
| **Agent 集成成本** | 零——`claude mcp add` 即插即用，工具 schema 自动进模型上下文 | 需要一个 skill/文档描述端点与参数（skill 已是这个胶水） |
| **非 Agent 消费** | 要 MCP client 库，人/脚本/CI 用着别扭 | curl 就能调，所有客户端通用 |
| **运维成熟度** | 较新（spec 仍在演进，auth 2025 年才稳定） | 标准基建：API key / 限流 / 缓存 / 观测全有现成方案 |
| **适合形态** | 有状态、长会话、流式工具 | 一次性无状态请求——代码生成正是这种 |

关键事实：**MCP = HTTP + 协议壳**——MCP 的远程传输（streamable HTTP）就是 HTTP 端点加 JSON-RPC 帧。推论：

- **先建 HTTP、后挂 MCP adapter 是廉价增量**（约百行薄壳，每个 tool handler 指向 HTTP 端点），CLI/HTTP 核心不动
- **反向不成立**：先建 MCP，非 Agent 消费者要装 MCP client，且吃协议演进 churn
- MCP 收益 = f(工具数量 × 客户端种类)：生成器只有 3-5 个无状态操作、客户端少时，增量收益趋近于零

## 7. 选择矩阵与触发条件

| 场景 | 形态 | 理由 |
|------|------|------|
| 本地单用户（**InferForge 现状**） | CLI + skill | Agent 集成成本为零（Bash 就是接口），无服务运维负担 |
| 需要服务化（远程 Agent / 团队共享 golden path） | **HTTP API 优先** | 通用消费 + 标准鉴权/限流/观测设施；OpenAPI schema 供 skill 描述端点（Spring Initializr 先例） |
| 出现真实 Agent 摩擦（多个 agent runtime 都要用、不想每个客户端维护 skill 文档） | 加 **MCP adapter** | 薄壳增量，CLI/HTTP 核心不动 |

**实现状态**：CLI 形态已落地（assemble.py + skill + 生成物自证）；HTTP 服务化与 MCP 包装均为未采纳（有意推迟）——触发条件即上表后两行；届时在现有 manifest/assemble.py 上评估，核心不动。

## 8. 与其它文档的分工

- [scaffolding.md](scaffolding.md)：业界工具谱系与采纳/未采纳映射（全景）
- [assembly.md](assembly.md)：装配机制实现（怎么工作）
- [design-principles.md](design-principles.md)：以上设计的取舍理由（为什么）
- 本文：生成器怎么被 Agent 消费——包装轴与协议选择（接口在哪）
