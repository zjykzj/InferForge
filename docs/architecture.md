# 架构说明（Architecture）

> InferForge 的分层架构：各层职责、实现逻辑与技术栈。最后更新：2026-08-15

## 1. 分层总览

| 层 | 目录 | 技术 | 一句话职责 |
|----|------|------|-----------|
| 接口层 | `apis/` + `app.py` | Flask、requests | 校验参数 → 转发任务层 → 包装响应（业务状态码） |
| 任务层 | `tasks/` + `celery_app.py` | threading、celery | 任务编排；每个任务持有自己的预测器；异步任务经 RabbitMQ 执行 |
| 引擎层 | `engines/` | onnxruntime、OpenCV、NumPy | 推理引擎契约 + YOLOv8n 实现 |
| 横切层 | `utils/` | logging、cv2、requests、base64、uuid | 日志、图片转换、响应格式、request_id（各层共用） |

## 2. 各层职责与实现

### 2.1 接口层（`apis/` + `app.py`）

**职责**：接收 HTTP 请求、校验参数、转发任务层、统一包装响应。`app.py` 只做装配：日志初始化、request_id 钩子、blueprint 注册——不认识任何任务或算法。

**逻辑**：

- 一个接口一个 blueprint 文件，接口可组合调用多个任务
- 异常分层捕获：`ValueError` → code=1（参数/图片非法）、`requests.RequestException` → code=2（下载失败）、其余 → code=3（内部错误）
- HTTP 永远返回 200，业务成败由 `code` 表达（见 [status-codes.md](status-codes.md)）

| 库 | 用途 |
|----|------|
| Flask | blueprint 路由、请求上下文、响应处理 |
| requests | URL 下载图片、下载异常类型判断 |

**文件**：`app.py`、`apis/predict.py`（同步）、`apis/predict_callback.py`（异步回调）、`apis/predict_query.py`（异步轮询；两者均由 `INFERFORGE_ASYNC=1` 开关启用）

### 2.2 任务层（`tasks/`）

**职责**：任务编排——不写算法细节，只组织步骤、组装数据、记录日志。

**逻辑**：

- 一个任务一个文件；每个任务**持有自己的预测器**（懒加载单例 + 双重检查锁），API 层看不到预测器
- 模型路径可用环境变量 `INFERFORGE_MODEL_PATH` 覆盖
- 编排步骤：解析输入图 → 调用预测器 → 组装 detections 列表 → 绘图 → 编码输出

| 库 | 用途 |
|----|------|
| threading | 预测器懒加载的双重检查锁 |
| celery | 异步任务：经 RabbitMQ 投递、worker 执行 |

**文件**：`tasks/detection.py`（同步编排）、`tasks/detection_callback.py`（异步回调任务：复用 run_detection，结果 POST 到 callback_url，网络失败指数退避重试）、`tasks/detection_query.py`（异步轮询任务：复用 run_detection，结果信封写入 Redis，无重试）

### 2.3 引擎层（`engines/`）

**职责**：算法无关的推理引擎契约与实现——全工程唯一稳定的抽象所在。

**逻辑**：

- `BasePredictor` 定义契约：`load(model_path)` / `predict(image) -> DetectionResult`；接口层和任务层只认识它
- `YoloPredictor` 实现：letterbox 预处理 → ONNX 推理 → decode `(1,84,8400)` → NumPy NMS → OpenCV 绘图
- onnxruntime **延迟导入**（仅 `load()` 内 import），测试无需真实模型
- 前后处理为**自研实现**（参考公开论文/文档），不依赖 ultralytics 库——ultralytics 为 AGPL-3.0 协议，直接使用会传染本项目协议

| 库 | 用途 |
|----|------|
| onnxruntime | ONNX 模型推理 |
| OpenCV | 缩放/padding、绘制检测框、图像编解码 |
| NumPy | decode 与 NMS 的向量化计算 |

**文件**：`engines/base.py`、`engines/yolo.py`

### 2.4 横切层（`utils/`）

**职责**：各层共用的基础设施，不依赖任何业务层。

**逻辑**：

- **日志**（logger.py）：console 文本（INFO+）+ 文件 JSON（DEBUG+）；每行携带 request_id/task_id；web 写 `app.log`、worker 写 `celery.log`，轮转交给系统 logrotate（详见 [logging.md](logging.md)）
- **图片转换**（image.py）：base64 / URL ↔ BGR numpy；下载超时 10s、大小上限 20MB
- **响应格式**（response.py）：统一 `{code, message, data}` 封装
- **request_id**（request_id.py）：请求入口生成 12 位 hex，贯穿日志 + `X-Request-ID` 响应头
- **结果存储**（redis_store.py）：异步轮询结果暂存——pending 占位符 + 结果信封，TTL 过期回收，客户端懒连接（详见 [stack.md](stack.md) §3）

| 库 | 用途 |
|----|------|
| logging | 双通道日志、自定义 Formatter/Filter（轮转交给系统 logrotate） |
| base64 | 图片编解码 |
| uuid | request_id 生成 |
| cv2 / NumPy | 图像解码与编码 |
| redis | 结果信封暂存（TTL 过期、NX 占位） |

**文件**：`utils/logger.py`、`utils/image.py`、`utils/response.py`、`utils/request_id.py`、`utils/redis_store.py`

## 3. 依赖规则

```
app -> apis -> tasks -> engines
```

- **单向依赖**：每层只 import 下一层，禁止反向引用
- **utils 横切**：各层均可使用；utils 不依赖任何业务层
- **engines 零业务依赖**：不 import Flask / apis / tasks，可独立测试与复用
- **替换原则**：换 Web 框架只动 `app.py` + `apis/`；换算法只动 `engines/`（+ 对应 task 的持有关系）；换任务编排只动 `tasks/`
- **测试同向**：冒烟测试从 apis 层用 `FakePredictor` 替换 engines，验证外壳接线（见 [testing.md](testing.md)）

### 按需启用与裁剪

异步能力是可选的——"装什么用什么"，不需要删文件：

| 场景 | 额外安装 | 额外服务 | 环境变量 | 可用接口 |
|------|---------|---------|---------|---------|
| 纯同步 | 无 | 无 | 无 | `/predict` |
| 同步 + 异步回调 | `requirements-async.txt` | RabbitMQ（无需 Redis） | `INFERFORGE_ASYNC=1` | `/predict` + `/predict/callback` |
| 同步 + 回调 + 查询 | `requirements-async.txt` + `requirements-query.txt` | RabbitMQ + Redis | `INFERFORGE_ASYNC=1 INFERFORGE_QUERY=1` | `/predict` + `/predict/callback` + `/predict/query` |

实现机制：

- `app.py` 按 `INFERFORGE_ASYNC=1`（回调）/ `INFERFORGE_QUERY=1`（查询，叠加在前者之上）注册异步 blueprint——两个开关正交，显式声明部署形态；开了开关但缺依赖时打印告警并跳过，同步接口照常
- 任务模块用 `shared_task` 注册，避免与 celery_app 循环导入
- `celery_app.py` 显式导入任务模块（不用惰性 autodiscover），并保证项目根目录在 sys.path 中（celery CLI 会临时移除 cwd）

## 4. 请求生命周期

一次 `POST /predict`（base64 方式）的完整流程：

```
 1. app.py  before_request     生成 request_id（12 位 hex）
 2. apis/predict.py            记录请求日志（来源、输入类型）
 3. tasks/detection.py         开始计时，解析输入
 4. utils/image.py             base64 → BGR numpy（记录 shape）
 5. engines/yolo.py            letterbox 预处理
 6. engines/yolo.py            ONNX 推理（pre/infer/post 分段计时）
 7. engines/yolo.py            decode + NMS + 坐标还原到原图
 8. engines/yolo.py            draw_detections 绘图
 9. utils/image.py             BGR → JPEG base64
10. tasks/detection.py         组装 detections 列表（记录总数与总耗时）
11. apis/predict.py            成功 → code=0；异常 → 对应业务码
12. app.py  after_request      响应头回传 X-Request-ID
```

每一步的日志都携带 request_id，以 JSON 落盘 `logs/app.log`——用户报障时携带 `X-Request-ID`，即可过滤出该请求的完整链路。

### 异步回调流程（POST /predict/callback）

```
 1. apis/predict_callback.py    校验参数（callback_url 必填）→ delay() 提交任务
 2. RabbitMQ                    任务排队
 3. Celery worker               消费任务：懒加载模型 → run_detection（复用同步编排）
 4. worker                      成功 → code=0 信封；业务失败 → code=1/2/3 信封
 5. worker                      POST 结果到 callback_url（网络失败指数退避重试，最多 3 次）
```

回调**恰好触发一次**：检测业务错误不重试（直接回调失败信封），只有回调 POST 本身的网络故障才重试。

### 异步查询流程（POST /predict/query + GET /predict/query/<task_id>）

```
 1. apis/predict_query.py    校验参数（image/url 二选一）→ delay() 提交任务
 2. apis/predict_query.py    Redis 写 pending 占位（SET NX，防 worker 抢先完成的竞态）
 3. RabbitMQ                  任务排队
 4. Celery worker             消费任务：懒加载模型 → run_detection（复用同步编排）
 5. worker                    成功 → code=0 信封；业务失败 → code=1/2/3 信封
 6. worker                    信封写入 Redis（覆写 pending，TTL 刷新；写失败任务报错）
 7. client 轮询               pending → code=5；key 不存在 → code=4；信封 → 原样返回
```

轮询**幂等**：结果落 Redis 后原样返回，多次轮询无副作用；结果带 TTL（默认 3600s），过期后轮询返回 code=4。

## 5. 技术栈总览

| 库 | 所属层 | 用途 |
|----|--------|------|
| Flask | 接口层 | blueprint 路由、请求/响应处理 |
| requests | 接口层 / 横切层 | URL 下载图片、下载异常类型 |
| threading | 任务层 | 预测器懒加载双重检查锁 |
| celery | 任务层 | 异步任务投递与执行 |
| onnxruntime | 引擎层 | ONNX 模型推理（延迟导入） |
| OpenCV | 引擎层 / 横切层 | 图像处理：缩放、绘图、编解码 |
| NumPy | 引擎层 / 横切层 | 向量化计算、数组处理 |
| logging | 横切层 | 双通道日志、轮转交给系统 logrotate |
| uuid | 横切层 | request_id 生成 |
| gunicorn | 部署 | 进程管理（preload_app、worker） |
| RabbitMQ | 部署 | 异步任务消息队列（可选） |
| Redis | 部署 | 异步轮询结果暂存（可选） |
| pytest | 测试 | 冒烟测试 |
