# InferForge

> 🔨 模型推理之上的一切——InferForge 把任何模型（CV → LLM → Agent）锻造成生产服务。
>
> Web 接口 · 任务编排 · 引擎抽象 · 日志与链路追踪 · 测试。模板而非框架：下载、改造、部署。

## 工程架构

```
InferForge/
├── app.py              # Flask 装配入口：日志初始化 + blueprint 注册
├── celery_app.py       # Celery 异步任务入口（可选）
├── apis/               # 接口层：一个接口一个 blueprint 文件
├── tasks/              # 任务层：任务编排，各任务持有自己的预测器
├── engines/            # 引擎层：BasePredictor 契约 + YOLO 实现
├── utils/              # 公共工具：日志 / 图片 / 响应格式 / request_id
├── tests/              # 冒烟测试
├── scripts/            # 辅助脚本（API 测试客户端）
├── assets/             # 测试图片
├── models/             # 模型文件（gitignore，yolov8n.onnx 放这里）
├── docs/               # 规范文档（接口 / 状态码 / 日志 / 测试）
├── start.sh            # 一键启动（web）
├── start_celery.sh     # Celery worker 启动（异步，可选）
├── gunicorn.conf.py    # Gunicorn 配置
├── requirements.txt    # 核心依赖
└── requirements-async.txt  # 可选异步依赖（celery）
```

分层职责与依赖规则：[docs/architecture.md](docs/architecture.md)。

## 快速开始

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

异步回调接口（可选——需要 RabbitMQ 服务）：

```bash
pip install -r requirements-async.txt
./start_celery.sh                                                               # 启动 worker
python3 scripts/callback_receiver.py                                            # 启动回调接收器（结果保存到 outputs/callbacks/）
python3 scripts/test_predict_callback.py --image assets/bus.jpg \
  --callback-url http://localhost:9000/result                                   # 结果完成后 POST 回调
```

运行冒烟测试：

```bash
pytest tests/ -v
```

日志：`logs/app.log`（JSON 格式，request_id 全链路）——详见 [docs/logging.md](docs/logging.md)。接口文档与 curl 示例：[docs/api.md](docs/api.md)。

## 开源协议

[MIT License](LICENSE) © 2026 zjykzj
