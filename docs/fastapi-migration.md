# Flask → FastAPI 迁移说明（Migration）

> 本项目 0.3.0 及以前基于 Flask 构建，0.4.0 起迁移到 FastAPI。本文说明：两个框架各自是什么、为什么迁移、迁移动了什么、没动什么。零基础读者建议先读 [concepts.md](concepts.md)。最后更新：2026-08-22

## 1. 两个框架各自是什么

| 维度 | Flask | FastAPI |
|------|-------|---------|
| 定位 | 轻量 Web 微框架（2010 年诞生，WSGI 时代） | 现代 Web 框架（2018 年诞生，ASGI 原生） |
| 请求校验 | 手写：端点里 if-else 逐字段检查 | Pydantic 声明式：定义请求模型，框架自动校验 |
| 接口文档 | 无内置，靠第三方扩展（flasgger 等） | 内置：从模型自动生成 `/docs`（Swagger UI）与 `/openapi.json` |
| 异步 | 需扩展（async 支持不完整） | 原生 ASGI，async 与 sync 端点通吃 |
| 类型体系 | 无类型驱动，参数是裸 dict/str | 类型提示驱动：校验、文档、编辑器提示同一来源 |

一句话：Flask 把"参数长什么样"留给开发者手写；FastAPI 让开发者**声明一次，框架自动执行**。

## 2. 为什么迁移（本项目视角）

- **校验从手写变成声明**：Flask 时代"image/url 恰好提供一个、字段类型、长度上限"散在各端点的 if-else 里，容易漏、改一处要全查；FastAPI 一个 `PredictRequest` 模型声明全部规则（见 [concepts.md](concepts.md) §1.3），校验失败经 `validation_error_handler` 折叠进 200 + `code=1` 信封——客户端看到的信封格式与业务错误完全一致，422 永不泄漏
- **文档从手写变成自动生成**：Flask 时代接口文档靠手写维护，容易和实现脱节；FastAPI 从 Pydantic 模型自动生成 `/docs`，版本号读 `VERSION` 文件，文档和实现永远同步
- **请求上下文更明确**：`flask.g` 的"请求级全局变量"换成 ContextVar + 纯 ASGI 中间件（`utils/request_id.py`），设置/复位边界清晰，不依赖框架的请求上下文
- **为异步扩展留路**：未来形态（LLM / Agent）单次推理可能几十秒，ASGI 原生异步让接口层有演进空间（当前端点仍是 sync `def`，推理路径不加 async，见 §4）

## 3. 迁移影响面

**动了的**：

| 层 | 改动 |
|----|------|
| `app.py` + `apis/` | 接口层重写：router 装配、Pydantic 请求模型、异常处理器注册 |
| `gunicorn.conf.py` | 一行：`worker_class = uvicorn.workers.UvicornWorker`——进程管理、logrotate、优雅停机全部不变 |
| `utils/` | 三个横切机制：响应信封（`response.py`）、日志（`logger.py`）、request_id（`request_id.py`） |
| 运行环境 | Python floor 提到 3.12（`X \| None` 等新语法） |

**没动的**：

- `tasks/`、`engines/` **零改动**——这正是分层架构的回报：换 Web 框架只动接口层（见 [architecture.md](architecture.md) §3 替换原则，本次迁移即为实证）
- `{code, message, data}` 信封契约不变——存量客户端无感
- 部署形态不变：gunicorn 进程管理、系统 logrotate、Celery/RabbitMQ/Redis 异步形态原样

## 4. 迁移后确立的关键约定

- **端点一律 sync `def`**：推理是 CPU 密集阻塞操作，FastAPI 把普通 `def` 端点放进 anyio 线程池执行（ONNX Runtime 在 C++ 侧释放 GIL，多请求可并行）；永远不要在推理路径加 async/await
- **校验分层**：结构校验（形状、类型、恰好一个来源）在 `apis/schemas.py`；语义校验（base64 内容、图片下载）在任务层，统一以 `code=1/2` 呈现——api 层不下载图片、不做推理，任务层不解析 HTTP 参数
- **422 永不泄漏**：`RequestValidationError` 由 `app.py` 里的异常处理器转成 200 + `code=1`（见 [status-codes.md](status-codes.md)）
- **request_id 传播**：`RequestIdMiddleware` 设置/复位 ContextVar，anyio 线程池把调用方上下文复制进 worker 线程，所以 sync 端点能看到同一个 id；celery worker 没有 HTTP 上下文，回退到任务 kwargs 里的 request_id

## 5. 延伸阅读

- 技术选型全景（FastAPI/Uvicorn/Gunicorn 分工与选择）：[stack.md](stack.md)
- 零基础概念（FastAPI/ASGI/Gunicorn/Pydantic）：[concepts.md](concepts.md)
- 分层架构与替换原则：[architecture.md](architecture.md)
- `code=1` 信封语义：[status-codes.md](status-codes.md)
