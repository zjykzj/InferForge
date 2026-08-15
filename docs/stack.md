# 技术栈说明（Stack）

> 本项目所用第三方技术：选型理由、配置点与关键决策。最后更新：2026-08-15

## 1. Flask + Gunicorn（Web 服务）

### 1.1 选型理由

- **Flask**：blueprint 机制天然契合"一个接口一个文件"的分层注册；轻量、生态成熟
- **Gunicorn**：WSGI 生产级进程管理；`preload_app` 支持启动前预加载，worker 管理、优雅重启开箱即用
- 同步接口的完整链路在 web 进程内完成，无外部依赖

### 1.2 配置点（`gunicorn.conf.py`）

| 参数 | 值 | 说明 |
|------|-----|------|
| `bind` | `0.0.0.0:8000` | 监听地址 |
| `workers` | 2（可用 `INFERFORGE_WORKERS` 覆盖） | web worker 进程数 |
| `worker_class` | `sync` | 同步 worker；推理是 CPU 密集阻塞式，线程/协程模型无收益 |
| `timeout` / `graceful_timeout` | 60s / 10s | 请求超时 / 优雅退出 |
| `preload_app` | `True` | fork 前加载 app 模块（imports、日志配置、blueprint 注册），worker 启动快 |

### 1.3 关键决策

- **preload_app=True 但不预热模型**：fork 前创建的 onnxruntime session 跨 fork 使用存在线程池相关风险，因此模型由任务层懒加载（每个 worker 首次请求时加载一次、之后常驻）——放弃"多 worker 共享一份权重"，换取 fork 安全
- **只配 2 个 sync worker**：推理是 CPU 密集，worker 数超过核数无收益；容量扩展靠横向加副本，不靠堆 worker
- **日志分工**：access/error 日志归 gunicorn（`logs/gunicorn_*.log`），业务日志归 `utils/logger.py`（`logs/app.log`）

## 2. Celery + RabbitMQ（异步任务）

### 2.1 选型理由

- **RabbitMQ 当 broker**：完整 AMQP——消息确认、持久化队列，worker 中途崩溃任务不丢；Celery 官方首选
- **结果交付用回调、不落 Redis**：当前异步形态是"服务端主动推送"——worker 完成直接 POST 到 callback_url，无需结果存储中间件；轮询形态（需 Redis 暂存）按需再引入
- **Celery**：Python 生态事实标准的任务队列框架，与分层架构自然衔接

### 2.2 拓扑

```
web（INFERFORGE_ASYNC=1）──delay()──▶ RabbitMQ ──消费──▶ Celery worker
                                                            │ 完成
client ◀──POST result── callback_url ◀─────────────────────┘
```

### 2.3 配置点（`celery_app.py`）

| 参数 | 值 | 说明 |
|------|-----|------|
| `broker_url` | `amqp://...`（可用 `CELERY_BROKER_URL` 覆盖） | 消息队列地址 |
| `task_ignore_result` | `True` | 结果不走 result backend（回调直推） |
| `worker_prefetch_multiplier` | `1` | 推理 CPU 密集：每个 worker 一次只取一个任务 |
| `task_time_limit` / `task_soft_time_limit` | 300s / 240s | 任务硬/软超时 |
| 序列化 | json | 任务参数必须可 JSON 序列化 |

### 2.4 关键决策

- **shared_task 显式注册**（弃 autodiscover）：任务模块用 `shared_task` 绑定，celery_app.py 末尾显式 import——避免循环导入，注册时机确定
- **celery_app.py 无条件 sys.path insert**：celery CLI 会临时把 cwd 加入 sys.path 又移除，去重守卫会被骗过——实测踩过的坑
- **`INFERFORGE_ASYNC` 显式开关**：异步接口由环境变量声明启用，而非"装了什么自动用什么"——部署形态显式化；开关开着但缺 celery 时告警跳过
- **回调"恰好一次"语义**：检测业务错误（code=1/2/3）不重试、直接回调失败信封；只有回调 POST 本身的网络故障才指数退避重试 3 次
- **进程组日志分离**：worker 写 `logs/celery.log`，轮转交给系统 logrotate（copytruncate），多进程写同一文件无竞态（详见 [logging.md](logging.md)）

## 3. 配置项总览（环境变量）

| 配置 | 默认值 | 说明 | 所在文件 |
|------|--------|------|---------|
| `INFERFORGE_MODEL_PATH` | `models/yolov8n.onnx` | 模型文件路径 | `tasks/detection.py` |
| `INFERFORGE_WORKERS` | `2` | web worker 进程数 | `gunicorn.conf.py` |
| `INFERFORGE_ASYNC` | 未设置（禁用） | 异步接口开关（`1`/`true`/`yes` 启用） | `app.py` |
| `CELERY_BROKER_URL` | `amqp://guest:guest@localhost:5672//` | 消息队列地址 | `celery_app.py` |
