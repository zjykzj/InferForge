# 文档说明（Docs）

> InferForge 的文档索引。最后更新：2026-09-05
>
> 文档分四类：**使用指南**（本工程实现，只描述现状）· **领域知识**（业界通用，不绑定本工程实现）· **开发规范**（本工程约束）· **技术栈与原理**（选型理由与历史）。
>
> 撰写约定：使用指南/规范文档中出现的**领域知识小节必须带边界标注**（`> 本节为领域知识，不描述本工程实现…`）并注明本工程的实现状态——范例见 [security.md](security.md) §2。

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
- **开发规范**
  - [forking-contract.md](forking-contract.md)：forking contract——模板使用方式、可改/慎改区域、合并上游更新的冲突取舍
  - [add-engine.md](add-engine.md)：新增推理引擎——BasePredictor contract、接入步骤（含 TensorRT/Triton）与验证清单
  - [status-codes.md](status-codes.md)：业务状态码——`{code, message, data}` envelope 规范、方案比较
  - [logging.md](logging.md)：日志模块——分级纪律、trace_id、生产实践指南
  - [metrics.md](metrics.md)：指标规范——Prometheus 指标清单、multiprocess 聚合、监控栈接入
  - [testing.md](testing.md)：测试策略——测试分层、冒烟测试详解、覆盖率策略与后续计划
  - [security.md](security.md)：安全边界——已知风险点、已有防护与部署建议（§2 SSRF 专述为领域知识）
- **技术栈与原理**
  - [stack.md](stack.md)：技术栈说明——FastAPI/Uvicorn/Gunicorn、Celery/RabbitMQ、Redis 与 OpenAI SDK/Pydantic AI 的选型理由、配置点与关键决策（全景，含环境变量总览）
  - [fastapi-migration.md](fastapi-migration.md)：Flask → FastAPI——两个框架对比、迁移理由与影响面（历史专题）
