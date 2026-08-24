# 文档说明（Docs）

> InferForge 的文档索引。最后更新：2026-08-24

* 工程文档
  * [concepts.md](concepts.md)：概念入门——Web 服务、任务队列、回调/轮询、Redis 的零基础科普
  * [quick-start.md](quick-start.md)：快速开始——同步/异步（回调 + 轮询）场景的完整启动与验证
  * [architecture.md](architecture.md)：分层架构——各层职责、实现逻辑、依赖规则、技术栈
  * [add-engine.md](add-engine.md)：新增推理引擎——BasePredictor contract 、接入步骤（含 TensorRT/Triton）与验证清单
  * [api.md](api.md)：接口调用——/predict、/predict/segment、/predict/classify、/predict/callback、/predict/query、/predict/vlm/* 参数与响应、curl 示例、参数设计规范
  * [benchmark.md](benchmark.md)：性能基准——压测工具、检测/VLM 基线数据与复现步骤
  * [agent.md](agent.md)：Agent 编排——Pydantic AI 示例（检测引擎 + LLM 判断人物属性）、V2 用法要点、泛化指南与编排形态选择（workflow / 单 / 多 Agent）
  * [deployment.md](deployment.md)：部署指南——线上灰度发布与测试/生产环境长期共存的完整方案
* 技术栈文档
  * [stack.md](stack.md)：技术栈说明——FastAPI/Uvicorn/Gunicorn、Celery/RabbitMQ、Redis 与 OpenAI SDK/Pydantic AI 的选型理由、配置点与关键决策（全景，含环境变量总览）
  * [fastapi-migration.md](fastapi-migration.md)：Flask → FastAPI——两个框架对比、迁移理由与影响面（专题）
* 规范文档
  * [status-codes.md](status-codes.md)：业务状态码——`{code, message, data}` envelope 规范、方案比较
  * [logging.md](logging.md)：日志模块——分级纪律、trace_id、生产实践指南
  * [metrics.md](metrics.md)：指标规范——Prometheus 指标清单、multiprocess 聚合、监控栈接入
  * [testing.md](testing.md)：测试策略——测试分层、冒烟测试详解、后续计划
  * [security.md](security.md)：安全边界——已知风险点、已有防护与部署建议
  * [forking-contract.md](forking-contract.md)：forking contract——模板使用方式、可改/慎改区域、合并上游更新的冲突取舍
