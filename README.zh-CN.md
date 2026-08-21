# InferForge

> 🔨 从推理内核到部署——InferForge 把任何模型（CV → LLM → Agent）锻造成生产服务。
>
> Web 接口 · 任务编排 · 引擎抽象 · 日志与链路追踪 · 测试。模板而非框架：下载、改造、部署。

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="License"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.9+-blue.svg" alt="Python 3.9+"></a>
  <a href="https://github.com/zjykzj/InferForge/releases"><img src="https://img.shields.io/github/v/release/zjykzj/InferForge" alt="Release"></a>
  <a href="https://conventionalcommits.org"><img src="https://img.shields.io/badge/Conventional%20Commits-1.0.0-yellow.svg" alt="Conventional Commits"></a>
</p>

## 特性

| | | |
|:---|:---|:---|
| 🔍 **同步检测** | `POST /predict` —— base64 / URL 输入，返回绘图 + JSON 结果 | `scripts/test_predict.py` |
| ⚡ **异步回调** | Celery + RabbitMQ —— 提交任务，结果 POST 到你的回调地址 | `INFERFORGE_ASYNC=1 ./start.sh` |
| 🔄 **异步查询** | Celery + RabbitMQ + Redis —— 提交任务，主动轮询拉取结果 | `INFERFORGE_ASYNC=1 INFERFORGE_QUERY=1 ./start.sh` |
| 🧱 **分层模板** | apis / tasks / engines / utils —— 换一层不动其余 | [architecture](docs/architecture.md) |
| 📦 **业务状态码** | `{code, message, data}` 信封 —— HTTP 永远 200 | [status-codes](docs/status-codes.md) |
| 🚦 **健康探针** | `GET /health` + `/health/ready` —— 供 K8s / 负载均衡存活与就绪检查 | [api](docs/api.md) |
| 🔗 **请求追踪** | request_id + task_id 贯穿 web 与 worker 日志 | [logging](docs/logging.md) |
| ✅ **冒烟测试** | 30+ 个测试，无需模型文件 | `pytest tests/ -v` |

## 快速开始

### 同步

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 放置 ONNX 模型
cp /path/to/yolov8n.onnx models/

# 3. 启动服务（默认 2 worker，端口 8000）
./start.sh

# 4. 测试接口
python3 scripts/test_predict.py --image assets/bus.jpg                              # 本地图片（base64）
python3 scripts/test_predict.py --url https://ultralytics.com/images/bus.jpg        # 在线 URL
```

运行冒烟测试：

```bash
pytest tests/ -v
```

### 异步

Celery + RabbitMQ 服务端回调：

```bash
pip install -r requirements-async.txt
INFERFORGE_ASYNC=1 ./start.sh                                                   # 启动 web（启用异步接口）
./start_celery.sh                                                               # 启动 worker
python3 scripts/callback_receiver.py                                            # 启动回调接收器（结果保存到 outputs/callbacks/）
python3 scripts/test_predict_callback.py --image assets/bus.jpg \
  --callback-url http://localhost:9000/result                                   # 结果完成后 POST 回调
```

Celery + RabbitMQ + Redis 客户端轮询（结果缓存到 Redis，轮询直至就绪）：

```bash
pip install -r requirements-async.txt -r requirements-query.txt
redis-server &                                                                  # 启动 redis（结果存储）
INFERFORGE_ASYNC=1 INFERFORGE_QUERY=1 ./start.sh                                # 启动 web（启用异步接口）
./start_celery.sh                                                               # 启动 worker
python3 scripts/test_predict_query.py --image assets/bus.jpg                    # 提交 + 轮询直到完成
```

## 文档

[docs/](docs/) —— concepts · quick-start · architecture · stack · api · status-codes · logging · testing · security

## 致谢

- **Web 与服务** — [Flask](https://flask.palletsprojects.com/) 路由与请求处理 · [Gunicorn](https://gunicorn.org/) 多进程 WSGI 服务
- **推理引擎** — [ONNX Runtime](https://onnxruntime.ai/) 前向推理 · [OpenCV](https://opencv.org/) 图像前后处理与绘图 · [NumPy](https://numpy.org/) decode 与 NMS 向量化计算
- **异步任务** — [Celery](https://docs.celeryq.dev/) 任务定义与投递 · [RabbitMQ](https://www.rabbitmq.com/) 消息中转 · [Redis](https://redis.io/) 结果暂存（TTL 自动回收）
- **演示模型** — [Ultralytics YOLOv8n](https://docs.ultralytics.com/) 导出为 ONNX

## 开源协议

[MIT License](LICENSE) © 2026 zjykzj
