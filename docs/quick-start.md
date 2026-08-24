# 快速开始（Quick Start）

> 从零跑起 InferForge 的操作手册，覆盖同步/异步（回调 + 轮询）/容器化部署场景。概念不熟？先读 [concepts.md](concepts.md)。最后更新：2026-08-21

## 1. 场景一：同步接口（FastAPI + Gunicorn/Uvicorn）

### 1.1 环境准备

- Python 3.9+

### 1.2 安装依赖

```bash
pip install -r requirements.txt
```

### 1.3 准备模型

```bash
# ONNX 导出方式之一（仅使用导出工具，不复制其代码，不影响本项目协议）：
yolo export model=yolov8n.pt format=onnx

cp /path/to/yolov8n.onnx models/
```

### 1.4 启动服务

```bash
python3 app.py    # 开发模式：uvicorn 单进程（不检查模型文件，接口调试用）
./start.sh        # 生产模式：gunicorn 多 worker（默认 2 worker，端口 8000）
```

启动失败说明：`start.sh` 在模型文件缺失时会直接提示；端口冲突改 `gunicorn.conf.py` 的 `bind`。开发模式自带交互式接口文档：浏览器打开 `http://localhost:8000/docs`。

### 1.5 验证

```bash
# 本地图片（base64 上传）
python3 scripts/test_predict.py --image assets/bus.jpg

# 在线图片（URL 下载）
python3 scripts/test_predict.py --url https://ultralytics.com/images/bus.jpg

# 冒烟测试（无需模型文件、无需服务）
pytest tests/ -v

# Prometheus 指标（见 docs/metrics.md；不接监控栈时此端点可忽略）
curl http://localhost:8000/metrics
```

### 1.6 可选：启用分割 / 分类（同步，默认关）

```bash
# 导出并放置模型（同检测：仅使用导出工具，不复制其代码）
yolo export model=yolov8n-seg.pt format=onnx
yolo export model=yolov8n-cls.pt format=onnx
cp /path/to/yolov8n-seg.onnx models/
cp /path/to/yolov8n-cls.onnx models/

# 带开关启动（可只开一个；start.sh 只检查已启用能力的模型文件）
INFERFORGE_SEG=1 INFERFORGE_CLS=1 ./start.sh

# 验证
python3 scripts/test_predict_segment.py --image assets/bus.jpg --save result_seg.jpg
python3 scripts/test_predict_classify.py --image assets/bus.jpg
```

预期：打印 `code: 0` 与检测列表；首次请求会触发模型懒加载（多几十毫秒属正常）。

### 1.6 日志

```bash
tail -f logs/app.log          # JSON 行，带 request_id 全链路
```

## 2. 场景二：异步接口（Celery + RabbitMQ 回调）

### 2.1 环境准备

- Python 3.9+
- RabbitMQ：

```bash
sudo apt-get install rabbitmq-server        # Ubuntu/WSL
sudo service rabbitmq-server start          # 启动
sudo rabbitmqctl status | head -3           # 验证运行中
```

### 2.2 安装依赖

```bash
pip install -r requirements-async.txt
```

### 2.3 启动（三个终端，各一个进程）

```bash
# 终端 1：web（必须带 INFERFORGE_ASYNC=1，否则回调接口不注册）
INFERFORGE_ASYNC=1 ./start.sh

# 终端 2：worker
./start_celery.sh

# 终端 3：回调接收器（结果保存到 outputs/callbacks/）
python3 scripts/callback_receiver.py
```

### 2.4 验证

```bash
python3 scripts/test_predict_callback.py --image assets/bus.jpg \
  --callback-url http://localhost:9000/result
```

预期：提交返回 `task_id`；几秒后接收器终端打印检测摘要，`outputs/callbacks/` 出现 `callback_*.json` + `callback_*.jpg`。

### 2.5 日志与排障

```bash
tail -f logs/celery.log        # 任务日志：request_id + task_id 贯穿
```

常见问题：

| 现象 | 原因 |
|------|------|
| `/predict/callback` 返回 404 | web 没带 `INFERFORGE_ASYNC=1` 启动 |
| 提交返回 code=3 "failed to submit task" | RabbitMQ 未启动 |
| 提交成功但回调迟迟不来 | 接收器未启动或 callback_url 不可达（worker 会重试 3 次后任务失败） |
| worker 日志 request_id 为 `-` | 旧版本 worker（重启 `./start_celery.sh` 拉新代码） |

## 3. 场景三：异步轮询接口（Celery + RabbitMQ + Redis）

### 3.1 环境准备

- Python 3.9+
- RabbitMQ（同场景二）
- Redis：

```bash
sudo apt-get install redis-server          # Ubuntu/WSL
sudo service redis-server start            # 启动
redis-cli ping                             # 返回 PONG 即正常
```

### 3.2 安装依赖

```bash
pip install -r requirements-async.txt
```

### 3.3 启动（两个终端，各一个进程）

```bash
# 终端 1：web（INFERFORGE_ASYNC=1 一次注册回调 + 轮询全部异步接口）
INFERFORGE_ASYNC=1 ./start.sh

# 终端 2：worker
./start_celery.sh
```

无需回调接收器——结果是调用方主动拉取的。

### 3.4 验证

```bash
python3 scripts/test_predict_query.py --image assets/bus.jpg
python3 scripts/test_predict_query.py --image assets/bus.jpg --save result.jpg   # 另存绘图结果到本地
```

预期：提交返回 `task_id` → 轮询打印若干次 `code: 5`（处理中）→ 最终 `code: 0` + 检测列表。结果暂存期间可直接查看：

```bash
redis-cli GET inferforge:result:<task_id>   # result envelope JSON
redis-cli TTL inferforge:result:<task_id>   # 剩余存活秒数（≤ 3600）
```

### 3.5 常见问题

| 现象 | 原因 |
|------|------|
| `/predict/query` 返回 404 | web 没带 `INFERFORGE_ASYNC=1` 启动 |
| 提交返回 code=3 "failed to submit task" | RabbitMQ 或 Redis 未启动 |
| 轮询返回 code=3 | Redis 掉线 |
| 轮询一直 code=5 | worker 未启动（`./start_celery.sh`） |
| 轮询返回 code=4 | task_id 错误，或结果已过期（默认 3600s，`INFERFORGE_RESULT_TTL` 可调） |

## 4. 场景四：Docker Compose 一键全栈

不想在本机装 Python / RabbitMQ / Redis？直接容器化起全栈（web + worker + RabbitMQ + Redis）：

### 4.1 准备模型

```bash
cp /path/to/yolov8n.onnx models/   # 模型通过 bind mount 挂进容器，不进镜像
```

### 4.2 一键启动

```bash
docker compose up -d
curl http://localhost:8000/health     # 存活探针（就绪探针 /health/ready 按进程各自报告）
```

四个容器：`web`（gunicorn，`INFERFORGE_ASYNC=1` 默认开启异步）、`worker`（celery）、`rabbitmq`、`redis`。容器间通过服务名互连，broker/redis 地址由 compose 自动改写为 `rabbitmq` / `redis`，无需手工配置。

### 4.3 使用

端口全部映射到宿主机，客户端脚本与本地部署完全一致：

```bash
python3 scripts/test_predict.py --image assets/bus.jpg                    # 同步
python3 scripts/test_predict_callback.py --image assets/bus.jpg \
  --callback-url http://localhost:9000/result                             # 回调
python3 scripts/test_predict_query.py --image assets/bus.jpg              # 轮询
```

RabbitMQ 管理界面：http://localhost:15672（guest/guest）。

### 4.4 管理

```bash
docker compose logs -f web       # 看容器日志（logs/ 同时 bind mount 到宿主机）
docker compose down              # 停止全部容器（保留队列与 Redis 数据）
docker compose down -v           # 连数据卷一起删除（清空队列与结果）
```

### 4.5 注意

- web 容器启动时检查 `models/yolov8n.onnx` 是否存在（与本地 `start.sh` 行为一致），缺失会直接退出并提示
- web 与 worker 共用同一个镜像（`inferforge:latest`），worker 同样挂载 `models/`——异步推理在 worker 进程里执行
- 容器内 web/worker 日志同时落 `logs/`（bind mount 到宿主机，系统 logrotate 照常轮转）
