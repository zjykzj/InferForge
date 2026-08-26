# 技术栈说明（Stack）

> 本项目所用第三方技术：选型理由、配置点与关键决策。零基础读者建议先读 [concepts.md](concepts.md)。最后更新：2026-08-24

## 1. FastAPI + Uvicorn + Gunicorn（Web 服务）

### 1.1 选型理由

- **FastAPI**：Pydantic 声明式参数校验（结构校验失败折叠进 `code=1` envelope，见 [status-codes.md](status-codes.md)）、自动 OpenAPI 文档（`/docs`、`/openapi.json`）、类型提示驱动
- **同步 `def` 端点 + 线程池**：FastAPI 把普通 `def` 端点放进 anyio 线程池执行——推理是 CPU 密集阻塞式，线程池模型天然适配（ONNX Runtime 在 C++ 侧释放 GIL，多请求可并行），协程异步在推理路径上无收益
- **Gunicorn（进程管理）+ Uvicorn（ASGI 实现）**：Gunicorn 负责多进程、优雅停机、HUP 平滑重启、access/error 日志落盘；`uvicorn.workers.UvicornWorker` 让每个 gunicorn worker 进程内跑一个 ASGI 事件循环
- 同步接口的完整链路在 web 进程内完成，无外部依赖

### 1.2 配置点（`gunicorn.conf.py`）

| 参数 | 值 | 说明 |
|------|-----|------|
| `bind` | `0.0.0.0:8000` | 监听地址 |
| `workers` | 2（可用 `INFERFORGE_WORKERS` 覆盖） | web worker 进程数 |
| `worker_class` | `uvicorn.workers.UvicornWorker` | ASGI worker；gunicorn 管进程，uvicorn 跑事件循环 |
| `timeout` / `graceful_timeout` | 60s / 10s | 事件循环存活 watchdog / 优雅退出（语义见 §1.3） |
| `preload_app` | `True` | fork 前加载 app 模块（imports、日志配置、router 注册），worker 启动快 |

### 1.3 关键决策

- **preload_app=True 但不预热模型**：fork 前创建的 onnxruntime session 跨 fork 使用存在线程池相关风险，因此模型由任务层懒加载（每个 worker 首次请求时加载一次、之后常驻）——放弃"多 worker 共享一份权重"，换取 fork 安全
- **只配 2 个 worker，并发靠线程池**：推理是 CPU 密集，worker 数超过核数无收益；容量扩展靠横向加副本，不靠堆 worker。每个 worker 内的 anyio 线程池（默认 40 线程）承载并发请求，ONNX 推理释放 GIL 时可真并行
- **timeout 语义变化**：UvicornWorker 下 `timeout=60` 是**事件循环存活 watchdog**而非单请求截止时间——长推理（如大模型）不会被 60s 误杀；任务级超时由 celery 的 `task_time_limit` 负责
- **日志分工**：access/error 日志归 gunicorn（`logs/gunicorn_*.log`，uvicorn 日志重定向到此处），业务日志归 `utils/logger.py`（`logs/app.log`）

### 1.4 Gunicorn vs 直接 Uvicorn：如何选择

两种组合都是生产级，区别在于**"谁在管进程"**：

| 维度 | Gunicorn + UvicornWorker | Uvicorn 直跑 |
|------|-------------------------|-------------|
| 进程管理 | 成熟：fork、HUP 平滑重启（滚动重载不掉请求）、优雅停机（在途请求跑完） | 基础：`--workers` 多进程可用，但无 HUP 平滑重载，worker 管理能力弱 |
| 日志 | access/error 落盘文件，接系统 logrotate | 默认打 stdout，落盘与轮转需自行处理 |
| 预加载 | `preload_app=True` fork 前加载 app | 无 |
| 超时守护 | 事件循环存活 watchdog（worker 假死可杀） | 无 |
| 部署拓扑 | 单机多 worker（VM/裸机，自管进程） | 一容器一进程，多副本靠编排器（K8s/Docker） |
| 开发调试 | — | `python3 app.py` 即起，hot reload |

选择标准不是 worker 数量，而是**进程归谁管**：

- **编排器管进程（K8s 多副本、一容器一进程）** → Uvicorn 直跑，进程管理交给编排器
- **本机/VM 自管多 worker** → Gunicorn + UvicornWorker（本项目默认：模型每 worker 一份驻留内存，单机 2 个固定 worker 是理性默认，且 logrotate 运维体系依赖 gunicorn 日志落盘）

本项目两种都覆盖：开发 `python3 app.py`（uvicorn 单进程），生产 `./start.sh`（gunicorn 多 worker）。

## 2. Celery + RabbitMQ（异步任务）

### 2.1 选型理由

- **RabbitMQ 当 broker**：完整 AMQP——消息确认、持久化队列，worker 中途崩溃任务不丢；Celery 官方首选
- **结果交付两种形态并存**：回调形态 worker 直推 callback_url、不落 Redis；轮询形态（`/predict/query`）worker 把 result envelope 写入 Redis（TTL 暂存），客户端轮询拉取（详见 §3）
- **Celery**：Python 生态事实标准的任务队列框架，与分层架构自然衔接

### 2.2 拓扑

```
web（INFERFORGE_ASYNC=1）──delay()──▶ RabbitMQ ──消费──▶ Celery worker
                                                            │ 完成
client ◀──POST result── callback_url ◀─────────────────────┘   （回调形态）

web ──set pending──▶ Redis ◀──set envelope── Celery worker     （轮询形态）
client ◀──GET result── Redis
```

### 2.3 配置点（`celery_app.py`）

| 参数 | 值 | 说明 |
|------|-----|------|
| `broker_url` | `amqp://...`（可用 `CELERY_BROKER_URL` 覆盖） | 消息队列地址 |
| `task_ignore_result` | `True` | 结果不走 result backend（回调直推） |
| `worker_prefetch_multiplier` | `1` | 推理 CPU 密集：每个 worker 一次只取一个任务 |
| `task_time_limit` / `task_soft_time_limit` | 300s / 240s | 任务硬/软超时 |
| `control_queue_durable` | `True` | 广播回复队列持久化（RabbitMQ ≥ 4.3 拒绝临时非排他队列，见 §2.4） |
| 序列化 | json | 任务参数必须可 JSON 序列化 |

### 2.4 关键决策

- **shared_task 显式注册**（弃 autodiscover）：任务模块用 `shared_task` 绑定，celery_app.py 末尾显式 import——避免循环导入，注册时机确定
- **celery_app.py 无条件 sys.path insert**：celery CLI 会临时把 cwd 加入 sys.path 又移除，去重守卫会被骗过——实测踩过的坑
- **单开关显式声明部署形态**：`INFERFORGE_ASYNC=1` 一次性启用全部异步接口（回调 + 轮询），而非"装了什么自动用什么"——异步是一种整体形态（celery + RabbitMQ + Redis），callback 与 query 是按请求的选择；开关开着但缺依赖时告警跳过
- **回调"恰好一次"语义**：检测业务错误（code=1/2/3）不重试、直接回调 failure envelope；只有回调 POST 本身的网络故障才指数退避重试 3 次
- **RabbitMQ 4.x 兼容策略**：4.3 起默认拒绝临时非排他队列（`transient_nonexcl_queues` 废弃特性），celery 两处用到——控制回复队列（mingle/inspect/revoke）用 `control_queue_durable=True` 改为持久化（官方推荐方向，kombu 后续版本将默认如此）；gossip 队列无配置可改，直接 `--without-gossip` 关闭（本项目不需要 worker 时钟同步与撤销传播）。若需 gossip 或 `-E` 事件（如 flower 监控），两个选择：RabbitMQ 侧放行（`deprecated_features.permit.transient_nonexcl_queues = true`，官方声明为临时方案），或使用 RabbitMQ 3.x
- **进程组日志分离**：worker 写 `logs/celery.log`，轮转交给系统 logrotate（copytruncate），多进程写同一文件无竞态（详见 [logging.md](logging.md)）

## 3. Redis（异步轮询结果暂存）

### 3.1 选型理由

- **手动 redis-py 存储而非 celery result backend**：结果由任务代码显式写入、接口代码显式读取，celery 配置零改动（`task_ignore_result=True` 保持）；result backend 方案会改变全局任务语义、序列化由 celery 接管，与"回调直推"形态混杂
- **TTL 回收**：result envelope + pending 占位统一带过期时间，无人工清理；key 前缀 `inferforge:result` 命名空间隔离
- **不要求高可用**：Redis 掉线时提交/轮询返回 code=3（可感知故障），结果丢失范围被 TTL 限界

### 3.2 配置点（`utils/redis_store.py`）

| 参数 | 值 | 说明 |
|------|-----|------|
| `INFERFORGE_REDIS_URL` | `redis://localhost:6379/0` | 结果存储地址 |
| `INFERFORGE_RESULT_TTL` | `3600` | 结果保存秒数（过期后轮询 code=4） |
| `decode_responses` | `True` | 读回字符串（pending 比较与 JSON 解析依赖） |
| 连接方式 | 懒连接（首次使用时创建） | fork 安全（`preload_app=True`） |
| socket 超时 | 3s | Redis 故障不拖死 web worker |

### 3.3 关键决策

- **pending 占位区分 code=4/5**：提交时写 `"pending"`（`SET NX`），轮询时"key 不存在 → code=4、值为 pending → code=5、值为 envelope → 原样返回"——三种状态无歧义
- **NX 防竞态**：worker 若抢先写完结果，web 侧的 pending 写入不得覆盖（`SET NX` 保证先写者胜）
- **故障语义**：提交/轮询时 Redis 不可用 → code=3；worker 写结果失败 → 任务报错不重试（日志可见，静默吞异常等于丢结果）

## 4. OpenAI SDK + Pydantic AI（LLM 与 Agent）

### 4.1 选型理由

- **OpenAI SDK 当 LLM 客户端**：chat completions 已是事实标准协议，主流服务商与自托管推理框架（vLLM/Ollama/…）都提供 OpenAI 兼容端点——换供应商只改 `INFERFORGE_LLM_BASE_URL` 与模型名，任务代码零改动；超时、基础设施级重试、用量字段由 SDK 提供
- **Pydantic AI 当 Agent 编排框架**：结构化输出（`output_type` + Pydantic 校验，校验失败自动让模型修正）、工具调用（`@agent.tool`）、依赖注入（`deps`/`RunContext`）开箱即用，与项目已有的 Pydantic 校验体系同源；手写 openai SDK 做同样的事要自行实现 JSON prompt 解析容错与 function-calling 协议（成本对比见 [agent.md](agent.md) §1.3）
- **装 slim 包而非完整 pydantic-ai**：`pydantic-ai-slim[openai,retries]` 只带 openai provider 与重试传输层；完整包会拉入 anthropic/google/mcp 等用不到的 provider SDK 与 logfire
- **两者都是 worker-only**：远程调用只发生在 celery worker，web 进程不需要这两个依赖——只进 `requirements-async.txt`，且在函数体内惰性导入（见 §4.3）

### 4.2 配置点（`tasks/vlm.py` / `tasks/agent.py`）

| 参数 | 值 | 说明 |
|------|-----|------|
| `LLM_TIMEOUT` / `AGENT_TIMEOUT` | 60s | 单次远程请求超时（在 celery 软超时 240s 之下） |
| `LLM_MAX_RETRIES` | `2` | openai SDK 级重试（连接失败 / 429 / 5xx） |
| Agent 传输层重试 | 3 次尝试 | `AsyncHTTPX2TenacityTransport`：429/502/503/504 与连接错误，尊重 Retry-After（V2 无内置 HTTP 重试，见 §4.3） |
| `LLM_MAX_TOKENS` / `AGENT_MAX_TOKENS` | `1024` | 单次返回 token 上限 |
| `INFERFORGE_LLM_PROMPT` / `INFERFORGE_AGENT_INSTRUCTIONS` | 见代码默认值 | 服务端固定提示词/指令，客户端只传图片 |
| client 生命周期 | VLM 进程内单例 / Agent 每任务新建 | `run_sync` 每次自建事件循环，httpx2 client 不可跨任务复用 |

模型与鉴权环境变量（`INFERFORGE_LLM_MODEL` / `INFERFORGE_LLM_API_KEY` / `INFERFORGE_LLM_BASE_URL`，VLM 与 Agent 共用）见 §5。

### 4.3 关键决策

- **惰性导入 + 缺失即 code 3**：两个 SDK 都在函数体内导入（与 onnxruntime 同规则），web 进程与测试在未安装时照常导入整条任务链；未安装时返回点名 SDK 的 code 3，配置缺失同样是 code 3（VLM 在 import openai 之前先调 `get_llm_config()`，保证给出的是"缺哪个变量"而不是一个 ImportError）
- **上游失败是业务错误，不重试**：SDK/传输层重试用尽后统一抛 `LLMUpstreamError` → code 9，任务层不再重试，轮询直接拿到失败 envelope。空返回内容视为质量异常而非远程故障——只观测延迟，不计入错误计数器；Agent 侧本地工具失败（`ToolFailed`）走 code 3，与远程失败语义分开
- **VLM/Agent 只做 query 形态**：不提供同步与回调变体——回调交付以检测任务为参照实现，而 LLM 类任务的调用方是主动业务系统，轮询是主路（见 [api.md](api.md) §10、§11）
- **I/O 密集靠并发扩容**：远程调用等待期不吃 CPU，用 `./start_celery.sh -c N` 提高并发；`worker_prefetch_multiplier=1` 保持不变（那是"每个子进程一次只处理一个任务"，与并发数无关）——与检测任务的 CPU 密集扩容方式相反
- **Agent 复用 VLM 的远程调用指标**：`inferforge_vlm_remote_call_seconds` / `inferforge_vlm_remote_errors_total` 同时覆盖两类调用，不新增指标名——语义都是"一次远程 LLM 调用"（见 [metrics.md](metrics.md)）
- **Agent 归 tasks 层**：Agent 是编排（工具 = 本地引擎 + 远程模型）而非推理内核，引擎层契约不变；换成别的属性任务只动 `tasks/agent.py` 的 schema/指令/工具三处（见 [agent.md](agent.md) §3）
- **V2 命名与 V1 教程不同**：`output_type` / `instructions` / `BinaryContent` / `OpenAIChatModel`——照抄网上 V1 示例会直接报错，版本陷阱清单见 [agent.md](agent.md) §2

## 5. 配置项总览（环境变量）

| 配置 | 默认值 | 说明 | 所在文件 |
|------|--------|------|---------|
| `INFERFORGE_REGISTRY_PATH` | `models/registry.yaml` | 模型注册表文件路径（显式指定但文件不存在 → 启动报错；无文件时用下面的 path 变量回退） | `engines/registry.py` |
| `INFERFORGE_MODEL_PATH` | `models/yolov8n.onnx` | 检测模型文件路径（仅注册表文件不存在时生效） | `engines/registry.py` |
| `INFERFORGE_SEG` | 未设置（禁用） | 同步分割接口开关（默认关，独立于异步栈） | `app.py` / `apis/health.py` |
| `INFERFORGE_SEG_MODEL_PATH` | `models/yolov8n-seg.onnx` | 分割模型文件路径（仅注册表文件不存在时生效） | `engines/registry.py` |
| `INFERFORGE_CLS` | 未设置（禁用） | 同步分类接口开关（默认关，独立于异步栈） | `app.py` / `apis/health.py` |
| `INFERFORGE_CLS_MODEL_PATH` | `models/yolov8n-cls.onnx` | 分类模型文件路径（仅注册表文件不存在时生效） | `engines/registry.py` |
| `INFERFORGE_WORKERS` | `2` | web worker 进程数 | `gunicorn.conf.py` |
| `INFERFORGE_PRELOAD` | 未设置（懒加载） | 启动预热：web 每个 worker 进程（startup 事件）与 celery worker 子进程（worker_process_init）启动时加载所服务能力的缺省模型；best-effort，失败只记日志 | `tasks/warmup.py` |
| `INFERFORGE_ASYNC` | 未设置（禁用） | 异步接口总开关（回调 + 轮询一起注册，`1`/`true`/`yes` 启用） | `app.py` |
| `INFERFORGE_QUERY` | 未设置 | 废弃别名（等同 `INFERFORGE_ASYNC=1`，启动时打印 deprecated 告警） | `app.py` |
| `INFERFORGE_LLM` | 未设置（禁用） | VLM 接口开关（需同时 `INFERFORGE_ASYNC=1`，否则告警跳过） | `app.py` |
| `INFERFORGE_AGENT` | 未设置（禁用） | Agent 接口开关（需同时 `INFERFORGE_ASYNC=1`，否则告警跳过） | `app.py` |
| `CELERY_BROKER_URL` | `amqp://guest:guest@localhost:5672//` | 消息队列地址 | `celery_app.py` |
| `INFERFORGE_REDIS_URL` | `redis://localhost:6379/0` | 轮询结果存储地址 | `utils/redis_store.py` |
| `INFERFORGE_RESULT_TTL` | `3600` | 结果保存秒数（过期后轮询 code=4） | `utils/redis_store.py` |
| `INFERFORGE_LLM_MODEL` | 未设置（VLM/Agent 必填） | 远程模型名，worker 侧读取（缺失 → code=3） | `tasks/vlm.py` |
| `INFERFORGE_LLM_API_KEY` | 未设置（VLM/Agent 必填） | 远程端点 API key（缺失 → code=3） | `tasks/vlm.py` |
| `INFERFORGE_LLM_BASE_URL` | 未设置（用 SDK 默认） | OpenAI 兼容端点地址（换供应商只改这里 + 模型名） | `tasks/vlm.py` |
| `INFERFORGE_LLM_PROMPT` | `Please describe this image in detail.` | VLM 服务端固定提示词 | `tasks/vlm.py` |
| `INFERFORGE_AGENT_INSTRUCTIONS` | 见 `DEFAULT_AGENT_INSTRUCTIONS` | Agent 服务端固定指令 | `tasks/agent.py` |
| `INFERFORGE_AGENT_TARGET_CLASS` | `person` | Agent 检测工具的目标类（须在所选检测模型类名表内，否则 code 3 点名报错） | `tasks/agent.py` |
| `INFERFORGE_API_KEY` | 未设置（关闭） | API key 鉴权：设置后非豁免路径要求 `X-API-Key` header（401 + code=7） | `utils/auth.py` |
| `INFERFORGE_RATE_LIMIT` | 未设置（关闭） | 固定窗口限流：每调用方每分钟请求上限（429 + code=8；多 worker 为近似值） | `utils/rate_limit.py` |
| `PROMETHEUS_MULTIPROC_DIR` | 未设置（单进程注册表） | 指标多进程聚合目录（web 与 worker 必须一致） | `utils/metrics.py` |
