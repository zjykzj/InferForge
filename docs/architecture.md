# 架构说明（Architecture）

> InferForge 的分层架构：各层职责、实现逻辑与技术栈。零基础读者建议先读 [concepts.md](concepts.md)。最后更新：2026-08-24

## 1. 分层总览

这套结构可以概括为:**unidirectional layered architecture + 引擎边界的 dependency inversion**。`app.py` 是 composition root（只做装配、不碰业务）；`apis → tasks → engines` 单向依赖，上层只依赖引擎层暴露的 `BasePredictor` 抽象，从不依赖具体算法；`utils/` 是 shared kernel，服务各层但不得反向依赖业务层。对照业界术语：精简版 clean architecture（接口层 ≈ controllers、任务层 ≈ use cases、引擎层 ≈ domain core），刻意不引入 repository、DI container 等重概念。

| 层 | 目录 | 技术 | 一句话职责 |
|----|------|------|-----------|
| 接口层 | `apis/` + `app.py` | FastAPI、Pydantic、requests | 校验参数 → 转发任务层 → 包装响应（业务状态码） |
| 任务层 | `tasks/` + `celery_app.py` | threading、celery、openai（VLM） | 任务编排；每个任务持有自己的预测器；异步任务经 RabbitMQ 执行；VLM 任务远程调用 LLM |
| 引擎层 | `engines/` | onnxruntime、OpenCV、NumPy | 推理引擎 contract + YOLOv8n 检测/分割/分类实现 |
| 横切层 | `utils/` | logging、cv2、requests、base64、uuid、contextvars | 日志、图片转换、响应格式、request_id（各层共用） |

## 2. 各层职责与实现

### 2.1 接口层（`apis/` + `app.py`）

**职责**：接收 HTTP 请求、校验参数、转发任务层、统一包装响应。`app.py` 只做装配：日志初始化、中间件、异常处理器、router 注册——不认识任何任务或算法。

**逻辑**：

- 一个接口一个 router 文件，接口可组合调用多个任务；端点一律写同步 `def`——FastAPI 将其放入 anyio 线程池执行（推理 CPU 密集阻塞式，推理路径禁止 async/await）
- **Pydantic 结构校验**：请求体模型（`apis/schemas.py`）声明字段与"image/url 二选一"规则；校验失败经 `RequestValidationError` 异常处理器折叠为 `200 + code=1` envelope——FastAPI 默认的 422 永不泄漏
- 语义校验与异常分层捕获：`ValueError` → code=1（图片内容非法）、`requests.RequestException` → code=2（下载失败）、其余 → code=3（内部错误）
- HTTP 永远返回 200，业务成败由 `code` 表达（见 [status-codes.md](status-codes.md)）；唯一例外是健康探针（见下）

| 库 | 用途 |
|----|------|
| FastAPI | router 路由、线程池执行同步端点、OpenAPI 文档（/docs） |
| Pydantic | 请求体结构校验（schemas.py） |
| requests | URL 下载图片、下载异常类型判断 |

**文件**：`app.py`、`apis/schemas.py`（请求体模型）、`apis/sync_detect.py`（同步检测）、`apis/sync_segment.py`（同步分割；由 `INFERFORGE_SEG=1` 启用）、`apis/sync_classify.py`（同步分类；由 `INFERFORGE_CLS=1` 启用）、`apis/health.py`（健康探针）、`apis/async_detect_callback.py`（异步回调）、`apis/async_detect_query.py`（异步轮询；由 `INFERFORGE_ASYNC=1` 开关启用）、`apis/async_vlm_query.py`（VLM 异步轮询，由 `INFERFORGE_ASYNC=1` + `INFERFORGE_LLM=1` 同时启用）、`apis/async_agent_query.py`（Agent 异步轮询，由 `INFERFORGE_ASYNC=1` + `INFERFORGE_AGENT=1` 同时启用）

**健康探针**：`GET /health`（存活）与 `GET /health/ready`（就绪）供 K8s / 负载均衡探活，始终注册。就绪检查向任务层询问**已启用能力**的 predictor 是否已加载（检测恒启用；分割/分类在对应开关开启时纳入检查——分类在 `INFERFORGE_CLS` 或 `INFERFORGE_PIPELINE` 任一开启时纳入，因为 pipeline 组合使用分类缺省模型；接口层不接触 predictor 本身），未加载时返回 503 + code=6——这是唯一使用非 200 HTTP 状态码的地方（探针只读状态码，见 [api.md](api.md) §7）。

### 2.2 任务层（`tasks/`）

**职责**：任务编排——不写算法细节，只组织步骤、组装数据、记录日志。

**逻辑**：

- 一个任务一个文件；每个任务**持有自己的预测器**（懒加载 + double-checked locking，按注册模型名缓存为 dict），API 层看不到预测器
- 组合任务例外：`tasks/pipeline.py` 与 `tasks/agent.py` 不持有 predictor，而是复用其他任务的缓存（pipeline 组合检测 + 分类两个引擎，agent 组合检测 + 远程 LLM）——一个引擎可被多个业务场景消费
- 模型清单来自**模型注册表** `engines/registry.py`（见 [model-registry.md](model-registry.md)）：请求的 `model` 字段在 task 层解析为具体 predictor；没有 `models/registry.yaml` 时，从 `INFERFORGE_MODEL_PATH` / `INFERFORGE_SEG_MODEL_PATH` / `INFERFORGE_CLS_MODEL_PATH` 合成单模型注册表（惰性读取，向后兼容）
- 编排步骤：解析输入图 → 调用预测器 → 组装结果列表（detections / segments / classifications）→ 绘图（检测/分割）→ 编码输出
- `tasks/warmup.py`：`INFERFORGE_PRELOAD=1` 的启动预热编排——web 与 worker 各自调用，只预热各自服务的能力的**缺省模型**（web：detect + 开关内的 seg/cls/pipeline——pipeline 开启时预热分类缺省模型；worker：仅 detect）；逐能力 try/except，单个模型加载失败只记日志、该能力维持 not-ready（readiness 才是真相来源）

| 库 | 用途 |
|----|------|
| threading | 预测器懒加载的 double-checked locking |
| celery | 异步任务：经 RabbitMQ 投递、worker 执行 |

**文件**：`tasks/detection.py`（同步检测编排）、`tasks/segmentation.py`（同步分割编排：mask 编码为每实例整图二值 PNG）、`tasks/classification.py`（同步分类编排：top-5 文本结果）、`tasks/pipeline.py`（组合管线编排：detect → 目标类过滤 → crop → classify，复用检测/分类 predictor 缓存，目标类由 `INFERFORGE_PIPELINE_TARGETS` 配置）、`tasks/detection_callback.py`（异步回调任务：复用 run_detection，结果 POST 到 callback_url，网络失败指数退避重试——callback 交付模式的参照实现）、`tasks/detection_query.py`（异步轮询任务：复用 run_detection，result envelope 写入 Redis，无重试）、`tasks/vlm.py`（VLM 编排：图片校验 → JPEG data URL → 远程 LLM chat completions；openai 惰性导入 + 懒加载 client 单例；LLMUpstreamError → code 9 语义）、`tasks/vlm_query.py`、`tasks/agent.py`（Agent 编排：Pydantic AI Agent + 检测引擎工具——detect_persons 定位个体、LLM 逐人判断属性；惰性导入 + 每次任务新建 client）、`tasks/agent_query.py`

VLM/Agent 为 **query-only** 形态：callback 推送以检测任务为参照实现，按任务性质选择性启用——LLM/Agent 类任务的调用方是主动业务系统（提交后轮询拿结果、需要幂等重查），query 是主路。

### 2.3 引擎层（`engines/`）

**职责**：算法无关的推理引擎 contract 与实现——全工程唯一稳定的抽象所在。

**逻辑**：

- `BasePredictor` 定义 contract：`load(model_path)` / `predict(image) -> PredictResult`（`DetectionResult` / `SegmentationResult` / `ClassificationResult` 三选一，结果类型按能力而定）；接口层和任务层只认识它
- `YoloPredictor` 实现（检测）：letterbox 预处理 → ONNX 推理 → decode `(1,84,8400)` → NumPy NMS → OpenCV 绘图
- `YoloSegPredictor` 实现（分割）：同检测链路 + 双输出头按形状识别（`(1,116,8400)` 分割头 + `(1,32,160,160)` prototype 头）→ 系数矩阵乘 + sigmoid + 阈值 → 整图二值 mask → 半透明叠加绘图
- `YoloClsPredictor` 实现（分类）：短边缩放 224（PIL bilinear，与模型训练 transform 对齐——cv2 插值核与之差异可测，会拉平置信度）→ 中心裁 224 → ONNX 推理（输出已是 softmax 概率，引擎不再二次 softmax）→ top-5 取值（ImageNet-1k 类名表见 `engines/imagenet_classes.py`，1000 条标准顺序）
- 三个引擎均为**注册表就绪**形态：构造函数不带模型路径，`load(path)` 注入——多模型注册表（`engines/registry.py`）据此按需加载任意数量的引擎实例；注册表本身是**纯元数据**（不持有 predictor、不加载权重），predictor 缓存仍在 task 层
- `engines/base.py` 的 `class_label()`：类别表与权重不匹配时降级为 `class_N` 标签 + warning，不让单个越界 class id 打挂整个请求（注册表可配每模型类别表后，这类错配更常见）
- onnxruntime **延迟导入**（仅 `load()` 内 import），测试无需真实模型
- 前后处理为**自研实现**（参考公开论文/文档），不依赖 ultralytics 库——ultralytics 为 AGPL-3.0 协议，直接使用会传染本项目协议

| 库 | 用途 |
|----|------|
| onnxruntime | ONNX 模型推理 |
| OpenCV | 缩放/padding、绘制检测框、图像编解码 |
| NumPy | decode 与 NMS 的向量化计算 |

**文件**：`engines/base.py`（contract + 三个结果类型 + `class_label` 安全查表）、`engines/yolo.py`（检测）、`engines/yolo_seg.py`（分割）、`engines/yolo_cls.py`（分类）、`engines/imagenet_classes.py`（ImageNet-1k 类名表）、`engines/registry.py`（模型注册表：YAML 解析 + env 回退 + 缺省推导）

### 2.4 横切层（`utils/`）

**职责**：各层共用的基础设施，不依赖任何业务层。

**逻辑**：

- **日志**（logger.py）：console 文本（INFO+）+ 文件 JSON（DEBUG+）；每行携带 request_id/task_id；web 写 `app.log`、worker 写 `celery.log`，轮转交给系统 logrotate（详见 [logging.md](logging.md)）
- **图片转换**（image.py）：base64 / URL ↔ BGR numpy；下载超时 10s、大小上限 20MB
- **响应格式**（response.py）：统一 `{code, message, data}` 封装
- **request_id**（request_id.py）：ASGI 中间件 + ContextVar——请求入口生成 12 位 hex，贯穿日志 + `X-Request-ID` 响应头（覆盖一切响应，含 503 与 validation envelope）
- **结果存储**（redis_store.py）：异步轮询结果暂存——pending 占位符 + result envelope，TTL 过期回收，客户端懒连接（详见 [stack.md](stack.md) §3）

| 库 | 用途 |
|----|------|
| logging | 双通道日志、自定义 Formatter/Filter（轮转交给系统 logrotate） |
| base64 | 图片编解码 |
| uuid | request_id 生成 |
| cv2 / NumPy | 图像解码与编码 |
| redis | result envelope 暂存（TTL 过期、NX 占位） |

**文件**：`utils/logger.py`、`utils/image.py`、`utils/response.py`、`utils/request_id.py`、`utils/redis_store.py`

## 3. 依赖规则

```
app -> apis -> tasks -> engines
```

- **单向依赖**：每层只 import 下一层，禁止反向引用
- **utils 横切**：各层均可使用；utils 不依赖任何业务层
- **engines 零业务依赖**：不 import FastAPI / apis / tasks，可独立测试与复用
- **替换原则**：换 Web 框架只动 `app.py` + `apis/`；换算法只动 `engines/`（+ 对应 task 的持有关系）；换任务编排只动 `tasks/`。本次 Flask → FastAPI 迁移即为实证：tasks/engines 零改动，utils 仅动响应/日志/request_id 三个横切机制
- **测试同向**：冒烟测试从 apis 层用 `FakePredictor` 替换 engines，验证外壳接线（见 [testing.md](testing.md)）

### 按需启用与裁剪

异步能力是可选的——"装什么用什么"，不需要删文件：

| 场景 | 额外安装 | 额外服务 | 环境变量 | 可用接口 |
|------|---------|---------|---------|---------|
| 纯同步 | 无 | 无 | 无 | `/predict` |
| 同步 + 分割 | 无 | 无 | `INFERFORGE_SEG=1`（+ `models/yolov8n-seg.onnx`） | `/predict` + `/predict/segment` |
| 同步 + 分类 | 无 | 无 | `INFERFORGE_CLS=1`（+ `models/yolov8n-cls.onnx`） | `/predict` + `/predict/classify` |
| 同步 + 异步（全量） | `requirements-async.txt` | RabbitMQ + Redis | `INFERFORGE_ASYNC=1` | `/predict` + `/predict/callback` + `/predict/query` |
| 同步 + 异步 + VLM | `requirements-async.txt`（含 openai） | RabbitMQ + Redis + 远程 LLM 端点 | `INFERFORGE_ASYNC=1` + `INFERFORGE_LLM=1` | 前述接口 + `/predict/vlm/query` |
| 同步 + 异步 + Agent | `requirements-async.txt`（含 pydantic-ai） | RabbitMQ + Redis + 远程 LLM 端点 + 本地模型 | `INFERFORGE_ASYNC=1` + `INFERFORGE_AGENT=1` | 前述接口 + `/predict/agent/query` |

实现机制：

- 分割/分类是**同步形态上的可选能力**（默认关，独立于异步栈）：`INFERFORGE_SEG=1` / `INFERFORGE_CLS=1` 时 app.py 惰性 import 并注册对应 router；开关真值集合单源于 `utils/switches.py`（app.py 与 health 探针共用）；start.sh 只检查已启用能力的模型文件
- `app.py` 按 `INFERFORGE_ASYNC=1` 一次性注册全部异步 router——异步是一种整体部署形态（celery + RabbitMQ + Redis），callback 与 query 是按请求的选择而非部署选择；`INFERFORGE_QUERY=1` 作为废弃别名保留（打印 deprecated 告警）。开了开关但缺依赖时打印告警并整体跳过异步模式，同步接口照常
- VLM 是异步形态上的可选能力：`INFERFORGE_LLM=1` 需与 `INFERFORGE_ASYNC=1` 同时开启才注册 vlm router；仅 LLM=1 时打印告警并跳过。VLM 没有同步版本——远程调用秒级到几十秒，同步长连接易超时且客户端重试会重复计费
- Agent 同理：`INFERFORGE_AGENT=1` 需与 `INFERFORGE_ASYNC=1` 同时开启；Agent 任务额外依赖本地检测模型（工具用）
- 任务模块用 `shared_task` 注册，避免与 celery_app 循环导入
- `celery_app.py` 显式导入任务模块（不用惰性 autodiscover），并保证项目根目录在 sys.path 中（celery CLI 会临时移除 cwd）

## 4. 请求生命周期

一次 `POST /predict`（base64 方式）的完整流程：

```
 1. app.py  RequestIdMiddleware  生成 request_id（12 位 hex，ContextVar 注入请求上下文）
 2. apis/schemas.py              Pydantic 结构校验（image/url 二选一；失败 → 200 + code=1 envelope）
 3. apis/sync_detect.py          记录请求日志（来源、输入类型）
 4. tasks/detection.py           开始计时，解析输入
 5. utils/image.py               base64 → BGR numpy（记录 shape）
 6. engines/yolo.py              letterbox 预处理
 7. engines/yolo.py              ONNX 推理（pre/infer/post 分段计时）
 8. engines/yolo.py              decode + NMS + 坐标还原到原图
 9. engines/yolo.py              draw_detections 绘图
10. utils/image.py               BGR → JPEG base64
11. tasks/detection.py           组装 detections 列表（记录总数与总耗时）
12. apis/sync_detect.py          成功 → code=0；异常 → 对应业务码
13. app.py  中间件出口            响应头回传 X-Request-ID（覆盖一切响应）
```

每一步的日志都携带 request_id，以 JSON 落盘 `logs/app.log`——用户报障时携带 `X-Request-ID`，即可过滤出该请求的完整链路。

`POST /predict/segment` 与 `POST /predict/classify` 走同一条生命周期：步骤 6-9 换成各自引擎的预处理 / 双输出推理 + mask 解码 / softmax top-k（分割在步骤 9 为半透明 mask 叠加 + 框标绘图，分类无绘图），其余步骤（校验、图片编解码、envelope、request_id）完全一致。

### 异步回调流程（POST /predict/callback）

```
 1. apis/async_detect_callback.py 校验参数（callback_url 必填）→ delay() 提交任务
 2. RabbitMQ                    任务排队
 3. Celery worker               消费任务：懒加载模型 → run_detection（复用同步编排）
 4. worker                      成功 → code=0 envelope；业务失败 → code=1/2/3 envelope
 5. worker                      POST 结果到 callback_url（网络失败指数退避重试，最多 3 次）
```

回调**恰好触发一次**：检测业务错误不重试（直接回调 failure envelope），只有回调 POST 本身的网络故障才重试。

### 异步查询流程（POST /predict/query + GET /predict/query/<task_id>）

```
 1. apis/async_detect_query.py 校验参数（image/url 二选一）→ delay() 提交任务
 2. apis/async_detect_query.py Redis 写 pending 占位（SET NX，防 worker 抢先完成的竞态）
 3. RabbitMQ                  任务排队
 4. Celery worker             消费任务：懒加载模型 → run_detection（复用同步编排）
 5. worker                    成功 → code=0 envelope；业务失败 → code=1/2/3 envelope
 6. worker                    envelope 写入 Redis（覆写 pending，TTL 刷新；写失败任务报错）
 7. client 轮询               pending → code=5；key 不存在 → code=4；envelope → 原样返回
```

轮询**幂等**：结果落 Redis 后原样返回，多次轮询无副作用；结果带 TTL（默认 3600s），过期后轮询返回 code=4。

### 异步 VLM 流程（POST /predict/vlm/query，query-only）

与检测异步轮询链路同构，差异在 worker 的第 4 步：

```
 1. apis/async_vlm_query.py 校验参数 → delay() 提交任务（与检测 query 完全一致）
 2. RabbitMQ                  任务排队
 3. Celery worker             消费任务 → run_vlm（tasks/vlm.py）
 4. worker                    图片解码校验（code 1/2 阶梯，付费前校验）→ JPEG data URL
 5. worker                    组装固定提示词 + 图片消息 → openai client 远程调用
                              （SDK 内置重试：连接/429/5xx，max_retries=2）
 6. worker                    成功 → code=0 envelope（data: {answer, model}）
                              远程失败 → code=9（SDK 重试耗尽）；配置缺失 → code=3（点名变量）
 7. worker                    envelope 写入 Redis，客户端轮询原样返回
```

- VLM worker 为 **I/O 密集**：`worker_prefetch_multiplier` 保持 1（那是"每个子进程一次一个任务"的约定，对远程调用同样成立），并发用 `./start_celery.sh -c N` 增加子进程数
- 远程调用的基础设施重试在 SDK 层（`max_retries=2`），worker 内不手写重试循环——与"检测业务错误不重试"的边界一致
- callback 推送模式以检测任务（§4 异步回调流程）为参照实现；LLM/Agent 类任务为 query-only——调用方是主动业务系统，query 是主路

### 异步 Agent 流程（POST /predict/agent/query，query-only）

与 VLM 链路同构，差异在 worker 内的编排（见 [agent.md](agent.md)）：

```
 1. apis/async_agent_query.py 校验参数 → delay() 提交任务（与检测 query 完全一致）
 2. RabbitMQ                  任务排队
 3. Celery worker             消费任务 → run_hair_count（tasks/agent.py）
 4. worker                    图片解码校验（code 1/2 阶梯，付费前）→ JPEG bytes
 5. worker                    _build_agent()：OpenAIChatModel + 传输重试 transport（429/5xx/连接 ×3）
 6. worker                    agent.run_sync([指令, BinaryContent(jpeg)], deps=解码图)
 7. LLM → 工具 detect_persons  本地检测引擎定位每个 person（过滤类别 → index + bbox）
 8. LLM                       依据全图 + bbox 逐人判断 has_hair → HairCountResult（Pydantic 校验）
 9. worker                    成功 → code=0 envelope（data = 结构化结果 dict）
                              AgentRunError → code=9；ToolFailed → code=3
10. worker                    envelope 写入 Redis，客户端轮询原样返回
```

- pydantic-ai 每次任务新建 agent/client（`run_sync` 自建事件循环，client 不可跨任务复用）；缺 SDK 时返回点名变量的 code 3（与 openai 规则一致）
- 传输重试在 Pydantic AI transport 层配置（V2 无内置 HTTP 重试），语义对齐 VLM 的 SDK `max_retries=2`

## 5. 技术栈总览

| 库 | 所属层 | 用途 |
|----|--------|------|
| FastAPI | 接口层 | router 路由、同步端点线程池、OpenAPI 文档 |
| Pydantic | 接口层 | 请求体结构校验（校验失败折叠为 code=1 envelope） |
| requests | 接口层 / 横切层 | URL 下载图片、下载异常类型 |
| threading | 任务层 | 预测器懒加载 double-checked locking |
| celery | 任务层 | 异步任务投递与执行 |
| openai | 任务层（VLM） | 远程 LLM 调用（OpenAI-compatible chat completions；函数体内惰性导入） |
| pydantic-ai | 任务层（Agent） | LLM Agent 编排（OpenAIChatModel + 工具 + 结构化输出；函数体内惰性导入） |
| onnxruntime | 引擎层 | ONNX 模型推理（延迟导入） |
| OpenCV | 引擎层 / 横切层 | 图像处理：缩放、绘图、编解码 |
| NumPy | 引擎层 / 横切层 | 向量化计算、数组处理 |
| logging | 横切层 | 双通道日志、轮转交给系统 logrotate |
| uuid | 横切层 | request_id 生成 |
| gunicorn + uvicorn | 部署 | 进程管理 + ASGI 服务（UvicornWorker，见 stack.md §1.4） |
| RabbitMQ | 部署 | 异步任务消息队列（可选） |
| Redis | 部署 | 异步轮询结果暂存（可选） |
| pytest | 测试 | 冒烟测试 |
