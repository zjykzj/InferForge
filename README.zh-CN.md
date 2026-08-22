# InferForge

> 🔨 从推理内核到部署——InferForge 把任何模型（CV → LLM → Agent）锻造成生产服务。
>
> Web 接口 · 任务编排 · 引擎抽象 · 日志与链路追踪 · 测试。模板而非框架：下载、改造、部署。

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="License"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.12%2B-blue.svg" alt="Python 3.12+"></a>
  <a href="https://github.com/zjykzj/InferForge/actions/workflows/ci.yml"><img src="https://github.com/zjykzj/InferForge/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/zjykzj/InferForge/releases"><img src="https://img.shields.io/github/v/release/zjykzj/InferForge" alt="Release"></a>
  <a href="https://conventionalcommits.org"><img src="https://img.shields.io/badge/Conventional%20Commits-1.0.0-yellow.svg" alt="Conventional Commits"></a>
</p>

## 关于

InferForge 是推理后端之上的服务外壳：围绕推理内核提供生产服务所需的全部工程能力——Web 接口、日志处理、异常处理、统一响应格式——让一个模型在几天内变成可部署的服务，而不是几周。但推理之上的业务层千差万别（模型不同、任务不同、接口不同），无法一概而论，因此本项目刻意做成**模板而非框架**：fork 之后代码归你所有，任务与接口由你定义；分层架构保证每一层可独立替换——换一个算法（ONNX Runtime、TensorRT、Triton……）只动引擎层。哪些可以改、哪些别乱动，见 [forking-contract](docs/forking-contract.md)。

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

# 5. 自动生成的接口文档（Swagger UI）：http://localhost:8000/docs
```

运行冒烟测试：

```bash
pytest tests/ -v
```

### 异步

异步只有一种部署形态 —— Celery + RabbitMQ + Redis。`INFERFORGE_ASYNC=1` 一次注册全部异步接口，回调还是轮询按请求选择：

```bash
pip install -r requirements-async.txt
INFERFORGE_ASYNC=1 ./start.sh                                                   # 启动 web（启用异步接口）
./start_celery.sh                                                               # 启动 worker
```

推送式 —— 服务端把结果 POST 到你的 `callback_url`：

```bash
python3 scripts/callback_receiver.py                                            # 启动回调接收器（结果保存到 outputs/callbacks/）
python3 scripts/test_predict_callback.py --image assets/bus.jpg \
  --callback-url http://localhost:9000/result                                   # 结果完成后 POST 回调
```

拉取式 —— 提交任务，轮询直到结果就绪（结果缓存到 Redis）：

```bash
redis-server &                                                                  # 启动 redis（结果存储）
python3 scripts/test_predict_query.py --image assets/bus.jpg                    # 提交 + 轮询直到完成
```

### Docker

容器化一键起全栈 —— web + worker + RabbitMQ + Redis，本机零安装：

```bash
cp /path/to/yolov8n.onnx models/    # 模型 bind mount 进容器，不进镜像
docker compose up -d
curl http://localhost:8000/health   # 存活探针
```

RabbitMQ 管理界面：http://localhost:15672（guest/guest）。`docker compose down` 停止全部容器（加 `-v` 连数据卷一起删除）。详见 [quick-start](docs/quick-start.md) §4。

## 文档

- **工程文档** — concepts · quick-start · architecture · add-engine · api · deployment
- **技术栈文档** — stack · fastapi-migration
- **规范文档** — status-codes · logging · metrics · testing · security · forking-contract

带逐篇说明的完整索引：[docs/README.md](docs/README.md)。

## 致谢

- **Web 与服务** — [FastAPI](https://fastapi.tiangolo.com/)（路由、Pydantic 校验与 OpenAPI 文档）· [Uvicorn](https://www.uvicorn.org/)（ASGI 服务）· [Gunicorn](https://gunicorn.org/)（多进程管理）
- **推理引擎** — [ONNX Runtime](https://onnxruntime.ai/)（前向推理）· [OpenCV](https://opencv.org/)（图像前后处理与绘图）· [NumPy](https://numpy.org/)（decode 与 NMS 向量化计算）
- **异步任务** — [Celery](https://docs.celeryq.dev/)（任务定义与投递）· [RabbitMQ](https://www.rabbitmq.com/)（消息中转）· [Redis](https://redis.io/)（结果暂存，TTL 自动回收）
- **演示模型** — [Ultralytics YOLOv8n](https://docs.ultralytics.com/)（导出为 ONNX）

## 开源协议

[MIT License](LICENSE) © 2026 zjykzj
