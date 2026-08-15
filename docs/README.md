# 文档说明（Docs）

> InferForge 的文档索引。最后更新：2026-08-15

* 工程文档
  * [concepts.md](concepts.md)：概念入门——Web 服务、任务队列、回调/轮询、Redis 的零基础科普
  * [quick-start.md](quick-start.md)：快速开始——同步/异步（回调 + 轮询）场景的完整启动与验证
  * [architecture.md](architecture.md)：分层架构——各层职责、实现逻辑、依赖规则、技术栈
  * [api.md](api.md)：接口调用——/predict、/predict/callback、/predict/query 参数与响应、curl 示例、参数设计规范
  * [stack.md](stack.md)：技术栈说明——Flask/Gunicorn、Celery/RabbitMQ 与 Redis 的选型理由、配置点与关键决策
* 规范文档
  * [status-codes.md](status-codes.md)：业务状态码——`{code, message, data}` 规范、方案比较
  * [logging.md](logging.md)：日志模块——分级纪律、trace_id、生产实践指南
  * [testing.md](testing.md)：测试策略——测试分层、冒烟测试详解、后续计划
  * [security.md](security.md)：安全边界——已知风险点、已有防护与部署建议
