# 文档说明（Docs）

> InferForge 的文档索引。最后更新：2026-09-13
>
> 文档分四类：**使用指南**（本工程实现，只描述现状）· **领域知识**（业界通用，不绑定本工程实现）· **开发规范**（本工程约束）· **技术栈与原理**（选型理由与历史）。
>
> 撰写约定：使用指南/规范文档中出现的**领域知识小节必须带边界标注**（`> 本节为领域知识，不描述本工程实现…`）并注明本工程的实现状态——范例见 [security.md](security.md) §2。

## 文档分类

- **使用指南**
  - [quick-start.md](quick-start.md)：快速开始——同步/异步（回调 + 轮询）场景的完整启动与验证
  - [architecture.md](architecture.md)：分层架构——各层职责、实现逻辑、依赖规则、技术栈
  - [api.md](api.md)：接口调用——检测/分割/分类/管线/去重、回调/轮询、VLM/Agent/检索/查重全部端点的参数与响应、curl 示例，以及健康检查、指标、鉴权限流、参数设计规范
  - [model-registry.md](model-registry.md)：多模型注册表——YAML 格式、请求级 `model` 路由、缺省推导、每模型类别表与向后兼容
  - [agent.md](agent.md)：Agent 编排——Pydantic AI 示例（检测引擎 + LLM 判断人物属性）、V2 用法要点、泛化指南与编排形态选择（§4 为领域知识）
  - [embedding.md](embedding.md)：Embedding 检索与去重——检索/去重两场景的差异、DINOv2 引擎 + milvus-lite 索引 + union-find 去重算法、选型约束与泛化
  - [benchmark.md](benchmark.md)：性能基准——压测工具、检测/VLM 基线数据与复现步骤
  - [deployment.md](deployment.md)：部署指南——线上灰度发布与测试/生产环境长期共存的完整方案
- **领域知识**
  - [concepts.md](concepts.md)：概念入门——Web 服务、任务队列、回调/轮询、Redis 的零基础科普
  - [release-strategies.md](release-strategies.md)：发布策略——环境模型、五种发布策略谱系（停服/滚动/蓝绿/canary/feature flag）、分流机制（canary vs A/B）、观测回滚、与模型版本管理的关系，附本工程实现状态标注
  - [scaffolding.md](scaffolding.md)：Scaffolding 工具调研——Copier/Yeoman/Spring Initializr/Backstage/schematics/create-* 的机制对照、"确定性生成器 + Agent 做胶水"共识、InferForge 的采纳与未采纳映射，附本工程实现状态标注
  - [generator-packaging.md](generator-packaging.md)：生成器包装轴——CLI / HTTP / MCP 三种包装形态与 Agent 集成取舍、"Agent + MCP 模板服务化"方案评估、HTTP vs MCP 选择矩阵与触发条件，附本工程实现状态标注
  - [agent-tooling.md](agent-tooling.md)：Agent 开发工具形态——业界三种落地形态（Agent 原生脚手架 / 自研 agent 平台 / 混合 MCP）、各自适用场景与代表实践、AGENTS.md 跨工具指令标准，附本工程实现状态标注
- **开发规范**
  - [forking-contract.md](workflow/forking-contract.md)：forking contract——模板使用方式、可改/慎改区域、合并上游更新的冲突取舍
  - [bootstrap.md](workflow/bootstrap.md)：从模板创建新工程——下载与按需装配、改名清单、配置初始化、底座验收与知识层继承
  - [assembly.md](assembly.md)：按需装配机制——manifest 正向清单、assemble.py、标记块约定与扩展纪律
  - [add-capability.md](workflow/add-capability.md)：新增业务能力——需求分解与形态决策（轴 × 组合规则、边界清单）、架构提案确认、能力文件集、无参照时的契约推导
  - [add-engine.md](workflow/add-engine.md)：新增推理引擎——BasePredictor contract、接入步骤（含 TensorRT/Triton）与验证清单
  - [modify-service.md](workflow/modify-service.md)：修改已有服务——层级定位、绿黄红区、换算法与回归验收
  - [status-codes.md](status-codes.md)：业务状态码——`{code, message, data}` envelope 规范、方案比较
  - [logging.md](logging.md)：日志模块——分级纪律、trace_id、生产实践指南
  - [metrics.md](metrics.md)：指标规范——Prometheus 指标清单、multiprocess 聚合、监控栈接入
  - [testing.md](testing.md)：测试策略——测试分层、冒烟测试详解、覆盖率策略与后续计划
  - [security.md](security.md)：安全边界——已知风险点、已有防护与部署建议（§2 SSRF 专述为领域知识）
- **技术栈与原理**
  - [stack.md](stack.md)：技术栈说明——FastAPI/Uvicorn/Gunicorn、Celery/RabbitMQ、Redis 与 OpenAI SDK/Pydantic AI 的选型理由、配置点与关键决策（全景，含环境变量总览）
  - [design-principles.md](design-principles.md)：模板设计原则——八条取舍（参考库而非拷贝源、正向清单、契约内核最小化等）与各自的反例
  - [fastapi-migration.md](fastapi-migration.md)：Flask → FastAPI——两个框架对比、迁移理由与影响面（历史专题）

## 给开发 Agent 的入口（任务 → 入口映射）

在新工程上开发时按"要做什么"直接进对应入口，不用通读全部文档：

- 从模板初始化新工程 → [bootstrap.md](workflow/bootstrap.md)
- 新增一个业务能力 → [add-capability.md](workflow/add-capability.md)（§2 先分解需求/查边界/确认架构提案）
- 换算法 / 接新推理后端 → [add-engine.md](workflow/add-engine.md)
- 修改已有服务（业务/参数/算法） → [modify-service.md](workflow/modify-service.md)（§1 定位）
- 合并模板上游更新 → [forking-contract.md](workflow/forking-contract.md) §4
- 理解"为什么这么设计" → [concepts.md](concepts.md) → [architecture.md](architecture.md)

每个入口的开发闭环一致：按文档实现 → `python3 scripts/check_capability.py` + `pytest tests/` 验收 → 提交。守门检查随新工程一起发布，本地与 CI 均可执行；`.claude/skills/` 的同名薄壳为 Claude Code 提供同一流程。
