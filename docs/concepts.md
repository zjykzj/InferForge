# 概念入门（Concepts）

> 给没接触过 Web 服务、消息队列、Redis 的读者：以「一次推理请求的旅程」为主线，建立心智模型。读完全文，你会理解 InferForge 为什么是现在这套架构。最后更新：2026-08-22

**建议阅读顺序**：本文（概念）→ [quick-start.md](quick-start.md)（跑起来）→ [architecture.md](architecture.md) / [api.md](api.md) / [stack.md](stack.md)（深入实现）。

## 1. Web 服务是怎么工作的

### 1.1 一次 HTTP 请求的旅程

```
客户端（浏览器/脚本/手机 App）
   │  ① 发起 HTTP 请求（"请帮我检测这张图"）
   ▼
你的服务器（监听 8000 端口）
   ├─ ② 收到请求的进程
   ├─ ③ 根据 URL 找到处理函数（路由）
   └─ ④ 返回 HTTP 响应（"这是检测结果"）
```

### 1.2 FastAPI、ASGI 与 Gunicorn 的分工

| 角色 | 是什么 | 负责 |
|------|--------|------|
| **FastAPI** | Python Web 应用框架 | 写"处理逻辑"：路由（哪个 URL 走哪个函数）、Pydantic 声明式参数校验、组装响应、自动生成接口文档（`/docs`）。自带开发服务器，仅适合调试 |
| **ASGI** | 服务器与应用之间的标准协议（WSGI 的现代继任者） | 约定"服务器怎么把请求交给应用、应用怎么把响应交回来"，原生支持异步 |
| **Uvicorn** | ASGI 服务器实现 | 每个 gunicorn worker 进程内的"引擎"：运行事件循环、收发 HTTP |
| **Gunicorn** | 进程管理器 | 生产环境进程管理：开 N 个 worker 进程并发收请求，一个进程卡住不影响其他进程；优雅停机、平滑重启 |

类比：FastAPI 是"菜单和做法"，Gunicorn 是"餐厅经理（管服务员）"，Uvicorn 是"每个服务员体内的传菜引擎"，ASGI 是服务员和后厨之间的"传菜口标准"。

本项目对应：`app.py`（装配 FastAPI router）、`gunicorn.conf.py`（2 个 worker、`uvicorn.workers.UvicornWorker`、8000 端口）、`start.sh`（启动 gunicorn）。开发调试可用 `python3 app.py`（uvicorn 单进程）。Gunicorn 与直接 uvicorn 的选择见 [stack.md](stack.md) §1.4。

补充：接口端点写的是**同步函数**（`def`），FastAPI 会把它们放进线程池执行——推理是 CPU 密集的阻塞操作，线程池正好适配；单进程也能同时服务多个请求。

### 1.3 Pydantic：参数的"安检员"

FastAPI 讲路由，gunicorn/uvicorn 讲收发，那"请求里的参数靠不靠谱"由谁管？——**Pydantic**。

- **是什么**：用 Python 类型声明描述"请求应该长什么样"。写一个继承 `BaseModel` 的类，声明字段和类型（`image: str | None`），再用 `@model_validator` 写规则（比如"image 和 url 必须恰好提供一个"）
- **怎么工作**：请求进来先"过安检"——合格，函数里拿到的是干净的对象，不用再写 if-else；不合格，请求根本进不了处理函数，直接变成 `code=1` envelope 返回（见 [status-codes.md](status-codes.md)）
- **为什么和 FastAPI 天生一对**：同一份类型声明同时驱动三件事——① 参数校验 ② 自动生成接口文档（`/docs`）③ 编辑器的类型提示。Flask 时代这三件事各自手写、互相脱节
- **本项目对应**：模型在 `apis/schemas.py`（`PredictRequest` / `CallbackRequest` / `QueryRequest`），校验失败经 `utils.response.validation_error_handler` 折叠进 200 + `code=1`。注意分层：**结构**校验（形状、类型、二选一）在 api 层，**语义**校验（base64 内容、图片下载）在任务层

一句话：校验从"手写 if-else"变成"声明一次、自动执行"。

### 1.4 多进程意味着什么（第 5 节的伏笔）

web 进程、celery worker 进程、Redis 服务是**互相独立的进程**（甚至不同机器），**内存不共享**。一个进程算出来的东西，另一个进程拿不到——这是第 5 节 Redis 登场的根本原因。

## 2. 同步请求的瓶颈

- 推理（ONNX 前向计算）是 **CPU 密集、阻塞**操作：单个请求要几百毫秒到几秒
- 同步模式下 web 只有 2 个 worker：2 个慢请求同时到达，第 3 个请求只能排队等待
- 更糟的是未来形态（LLM / Agent）单次推理可能几十秒——同步等待会彻底堵死服务
- 解决思路：**把"重活"从 web 进程搬出去**，交给专门的工人进程，web 只负责收发请求

这就是"异步化"。

## 3. 异步化：任务队列登场

### 3.1 三个角色

```
生产者（web 进程）──①投递任务描述──▶ 队列（RabbitMQ）──②消费──▶ 消费者（celery worker）
        │                                                               │
        └──── ③ 立刻返回 task_id 给客户端（不等结果）                    └─ ④ 执行推理
```

- **生产者**：收到请求后不干活，只把"任务描述"（图片、参数）放进队列，立刻返回 `task_id`
- **队列**：消息暂存区，先进先出，把任务安全地派发给消费者
- **消费者**：独立的 worker 进程，从队列取任务执行

### 3.2 Celery 与 RabbitMQ 的分工

| 角色 | 是什么 | 负责 |
|------|--------|------|
| **Celery** | Python 任务队列框架 | 任务怎么定义（`shared_task`）、怎么投递（`.delay()`）、怎么执行 |
| **RabbitMQ** | 消息队列中间件（独立服务） | 消息的暂存、派发、确认 |

关系：Celery 是"快递公司业务系统"，RabbitMQ 是"中转仓库"。Celery 本身不带仓库，必须对接一个 broker。

### 3.3 消息为什么不丢

- **确认机制（ack）**：worker 处理完才向队列"签收"；中途崩溃的任务会重新入队，交给别的 worker
- **持久化队列**：消息写入硬盘，RabbitMQ 重启也不丢

本项目对应：`celery_app.py`（broker 地址 `CELERY_BROKER_URL`）、`start_celery.sh`、`tasks/` 下的 `@shared_task` 任务。

## 4. 结果怎么交回：两种模式

任务做完了，结果怎么回到发起方？

### 4.1 推送（callback 回调）

worker 完成后**主动 POST** 到发起方提供的 `callback_url`。

- 发起方必须提供"接收地址"（一个常驻服务）
- 适用：发起方是常驻服务、想被"通知"而不是反复"询问"
- 代价：接收方临时挂了，回调 POST 需要重试（本项目：网络失败重试 3 次）

### 4.2 拉取（轮询 query）

worker 完成后把结果放进一个**共享的"快递柜"**（Redis），发起方拿着 `task_id` 反复来问："好了吗？"

- 发起方无需开任何接收端口，脚本/移动端都行
- 多个下游想取同一结果，各取各的
- 结果带保质期（TTL），到期自动清空

### 4.3 对比

| 维度 | callback（推送） | query（拉取） |
|------|-----------------|--------------|
| 结果走向 | 服务端推给指定地址 | 放快递柜，谁有 task_id 谁取 |
| 发起方要求 | 需提供常驻接收服务 | 无需 |
| 网络故障 | 回调 POST 重试 3 次 | 无此概念（结果一直在柜子里） |
| 结果保存 | 接收方自己决定 | TTL 过期自动清除 |

本项目两种都实现了：`POST /predict/callback` 与 `POST/GET /predict/query`，由 `INFERFORGE_ASYNC=1` 一个开关一起启用——callback 还是 query 是按请求的选择，不是部署形态的选择（见 [architecture.md](architecture.md) §3）。

## 5. Redis 登场

### 5.1 为什么轮询需要一个"快递柜"

回到 1.4 的伏笔：web 进程提交任务、celery worker 执行任务、发起方来查询——三者是**不同进程**，内存不共享。worker 算完的结果放哪？

- 放 web 进程内存？worker 是另一个进程，写不进去
- 放文件？多进程同时读写有竞态，性能差
- 答案：放进一个**大家都连得上的共享存储**——Redis

### 5.2 Redis 是什么

- **内存键值数据库**：像一个大字典，`key → value`，操作是微秒级
- **内存** → 极快，但重启即失 → 只适合放"可丢失的临时数据"（result envelope 丢了无非再算一次）
- **TTL**：每条数据可设过期时间，到期自动删除 → 天然适合"结果只保留 1 小时"

### 5.3 为什么不用 MySQL

- MySQL 数据在硬盘，慢一个数量级；且 result envelope 是临时数据，不需要永久保存
- Redis 的 TTL 自动回收，零清理成本

### 5.4 快递柜的工作流程

```
提交  web 写 "pending" 占位（SET NX 防覆盖）→ 返回 task_id
执行  worker 算完，把 result envelope 覆写进柜子（TTL 刷新）
查询  发起方 GET：
        "pending"          → code 5  还在做，继续等
        result envelope JSON       → code 0  拿走（envelope 原样返回）
        柜子里没有          → code 4  没这单或已过期
```

本项目对应：`utils/redis_store.py`，key 格式 `inferforge:result:<task_id>`，TTL 由 `INFERFORGE_RESULT_TTL` 控制（默认 3600s）。

## 6. 概念 → 实现对照表

| 概念 | 本项目对应 |
|------|-----------|
| Web 应用 | `app.py` + `apis/`（FastAPI router） |
| Web 服务器 | gunicorn + uvicorn worker（`gunicorn.conf.py`，`start.sh` 启动；开发用 `python3 app.py`） |
| 任务框架 | `celery_app.py` + `tasks/` 的 `@shared_task` |
| 消息队列 | RabbitMQ（`CELERY_BROKER_URL`） |
| 生产者 | `apis/predict_callback.py` / `apis/predict_query.py` 里的 `.delay()` |
| 消费者 | `tasks/detection_callback.py` / `tasks/detection_query.py` |
| 快递柜 | Redis + `utils/redis_store.py`（`INFERFORGE_REDIS_URL`） |
| result envelope | `{code, message, data}`（见 [status-codes.md](status-codes.md)） |
| 链路追踪 | `utils/request_id.py`（见 [logging.md](logging.md)） |

## 7. 延伸阅读

- 架构与依赖规则：[architecture.md](architecture.md)
- 技术选型理由：[stack.md](stack.md)
- 接口调用：[api.md](api.md)
- 部署启动：[quick-start.md](quick-start.md)
