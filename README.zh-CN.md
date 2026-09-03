# InferForge

> 🔨 从推理内核到部署——InferForge 把任何模型（CV → LLM → Agent）锻造成生产服务。
>
> 开箱即用：同步/异步接口 · 健康探针 · OpenAPI 文档 · Prometheus 指标。可选（默认关闭）：API-key 鉴权与限流。模板而非框架：下载、改造、部署。

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="License"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.12%2B-blue.svg" alt="Python 3.12+"></a>
  <a href="https://github.com/zjykzj/InferForge/actions/workflows/ci.yml"><img src="https://github.com/zjykzj/InferForge/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/zjykzj/InferForge/releases"><img src="https://img.shields.io/github/v/release/zjykzj/InferForge" alt="Release"></a>
  <a href="https://deepwiki.com/zjykzj/InferForge"><img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki"></a>
</p>

## 关于

InferForge 是推理后端之上的服务外壳：开箱即得生产配套——Web 接口、日志处理、异常处理、统一响应格式——模型几天内就能变成可部署的服务。但推理之上的业务层千差万别、无法一概而论，因此本项目刻意做成**模板而非框架**：fork 之后代码归你所有，任务与接口由你定义。分层架构保证每一层可独立替换——哪些可以改、哪些别乱动，见 [forking-contract](docs/forking-contract.md)。

## 项目结构

```
InferForge/
├── apis/          # FastAPI 路由 + Pydantic 模型 —— 接口层
├── tasks/         # 任务编排；每个任务持有自己的预测器
├── engines/       # BasePredictor contract + YOLOv8n 检测/分割/分类参考实现
├── utils/         # 横切机制：envelope、日志、指标、鉴权、限流
├── deploy/        # 参考工件：logrotate、nginx 灰度、监控栈
├── docs/          # 完整文档集（中文，按分类索引）
├── scripts/       # 接口测试脚本 + 回调接收器
└── tests/         # 冒烟测试——无模型依赖，CI 自动执行
```

## 能力总览

| 能力 | 形态 | 开关 | 模型 |
|---|---|---|---|
| 检测 | 同步 + 异步 | 常开；`INFERFORGE_ASYNC` 增加异步接口 | `yolov8n.onnx` |
| 分割 | 仅同步 | `INFERFORGE_SEG` | `yolov8n-seg.onnx` |
| 分类 | 仅同步 | `INFERFORGE_CLS` | `yolov8n-cls.onnx` |
| 管线 | 仅同步 | `INFERFORGE_PIPELINE` | 复用检测 + 分类 |
| 去重 | 仅同步 | `INFERFORGE_DEDUP` | `dino2-small.onnx` |
| 检索 / 查重 | 仅异步（query） | `INFERFORGE_SEARCH` | embed + `data/gallery.db` |
| VLM | 仅异步（query） | `INFERFORGE_LLM` | 远程 LLM |
| Agent | 仅异步（query） | `INFERFORGE_AGENT` | 检测 + 远程 LLM |

开关均为可选环境变量（检测常开）；开关只决定路由是否存在，不决定加载哪个模型（那是注册表的职责，见 [model-registry](docs/model-registry.md)）。所有异步能力都建立在同一套 §异步基础设施 之上；检索 / VLM / Agent 无 callback 形态。

## 快速开始

最小编程路径：同步检测。

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 放置 ONNX 模型
cp /path/to/yolov8n.onnx models/

# 3. 启动服务（默认 2 worker，端口 8000）
./start.sh                                  # 模型在首个请求时懒加载
INFERFORGE_PRELOAD=1 ./start.sh             # ... 或启动即加载（就绪检查立即 ready）

# 4. 测试接口
python3 scripts/test_sync_detect.py --image assets/bus.jpg                              # 本地图片（base64）
python3 scripts/test_sync_detect.py --url https://ultralytics.com/images/bus.jpg        # 在线 URL

# 5. 自动生成的接口文档（Swagger UI）：http://localhost:8000/docs
# 6. Prometheus 指标：http://localhost:8000/metrics（可选，见 docs/metrics.md）
```

配置也可以写进 `.env` 文件（`cp .env.example .env` 后填写——shell 已导出的环境变量优先）。其余能力见 §能力。

## 异步基础设施

异步只有一种部署形态——Celery + RabbitMQ + Redis，所有异步能力（检测、检索/查重、VLM、Agent）都共享它。投递方式按请求选择：callback（服务端把结果 POST 到你的 `callback_url`）或 query（提交后轮询直到结果就绪——结果缓存到 Redis）。搭建一次即可：

```bash
pip install -r requirements-async.txt
INFERFORGE_ASYNC=1 ./start.sh                                                   # 启动 web（注册检测的异步接口）
./start_celery.sh                                                               # 启动 worker
```

`INFERFORGE_ASYNC=1` 注册的是检测接口；检索 / VLM / Agent 在此基础上叠加各自开关（见对应章节）。两种投递方式的用法见 §检测。

## 能力

### 1. 检测

同步形态见上方快速开始。异步形态无需额外开关——§异步基础设施 注册的即是检测接口，callback 还是 query 按请求选择：

```bash
# 推送式 —— 服务端把结果 POST 到你的 callback_url
python3 scripts/callback_receiver.py                                            # 启动回调接收器（结果保存到 outputs/callbacks/）
python3 scripts/test_async_detect_callback.py --image assets/bus.jpg \
  --callback-url http://localhost:9000/result                                   # 结果完成后 POST 回调

# 拉取式 —— 提交任务，轮询直到结果就绪（结果缓存到 Redis）
redis-server &                                                                  # 启动 redis（结果存储）
python3 scripts/test_async_detect_query.py --image assets/bus.jpg                    # 提交 + 轮询直到完成
```

### 2. 分割 / 分类

仅同步形态（默认关，检测不受影响）：

```bash
# 1. 导出并放置模型（subprocess 调 yolo CLI——不 import ultralytics；导出后自动形状校验）
python3 scripts/export_yolo.py --task segment --task classify

# 2. 带开关启动（可只开一个；start.sh 只检查已启用能力的模型文件）
INFERFORGE_SEG=1 INFERFORGE_CLS=1 ./start.sh

# 3. 测试
python3 scripts/test_sync_segment.py --image assets/bus.jpg --save result_seg.jpg   # 分割
python3 scripts/test_sync_classify.py --image assets/bus.jpg                        # 分类（top-5）
```

### 3. 管线

仅同步形态。组合上面两个模型——检测 → 裁剪 → 细粒度分类（如检测 `bus` → 识别 `school bus`）；目标类用 `INFERFORGE_PIPELINE_TARGETS` 配置（默认 `car,truck,bus`）：

```bash
INFERFORGE_PIPELINE=1 ./start.sh
python3 scripts/test_sync_pipeline.py --image assets/bus.jpg --save result_pipeline.jpg   # 管线（检测 → 分类）
```

### 4. Embedding

同一个 DINOv2-small 引擎支撑三个业务任务：去重（同步）与 gallery 检索 / 查重（异步 query-only、worker 专属——milvus-lite 索引单进程独占）。先将 DINOv2-small 导出 ONNX 放入 models/：

```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu   # 一次性导出依赖
python3 scripts/export_dinov2.py                                                # -> models/dino2-small.onnx
```

同步批内去重——一批图里找出互为近似重复的分组（阈值 `INFERFORGE_DUP_THRESHOLD`，默认 0.95）：

```bash
INFERFORGE_DEDUP=1 ./start.sh
python3 scripts/test_sync_dedup.py --image assets/bus.jpg --image assets/bus.jpg --image assets/zidane.jpg   # 去重
```

异步 gallery 检索 / 查重（建立在 §异步基础设施 之上）：

```bash
python3 scripts/build_gallery.py                # 先建索引——worker 必须已停止（gallery/ -> data/gallery.db）
INFERFORGE_ASYNC=1 INFERFORGE_SEARCH=1 ./start.sh
python3 scripts/run_search.py --image assets/bus.jpg --check    # task 层直测（检索 / 查重）
```

详见 [embedding](docs/embedding.md)。

### 5. VLM

图片理解——worker 调用远程 OpenAI 兼容 LLM，仅异步 query-only。在 §异步基础设施 之上再加 `INFERFORGE_LLM=1`：

```bash
INFERFORGE_LLM=1 INFERFORGE_ASYNC=1 ./start.sh                                  # 启动 web（注册 /predict/vlm/*）
INFERFORGE_LLM_MODEL=your-model \
INFERFORGE_LLM_API_KEY=your-key \
INFERFORGE_LLM_BASE_URL=https://your-llm-endpoint/v1 \
./start_celery.sh                                                               # 启动 worker（远程调用发生在 worker）
python3 scripts/test_async_vlm_query.py --image assets/bus.jpg                        # 提交 + 轮询直到文本答案返回
```

提示词由服务端固定（`INFERFORGE_LLM_PROMPT` 可覆盖），客户端只传图片。详见 [api](docs/api.md) §10。

### 6. Agent

Pydantic AI 编排示例——检测工具 + LLM 属性判断，仅异步 query-only。在 §异步基础设施 之上再加 `INFERFORGE_AGENT=1`，worker 复用 `INFERFORGE_LLM_*` 配置并需要本地模型：

```bash
INFERFORGE_AGENT=1 INFERFORGE_ASYNC=1 ./start.sh                                  # 启动 web（注册 /predict/agent/*）
INFERFORGE_LLM_MODEL=your-model \
INFERFORGE_LLM_API_KEY=your-key \
./start_celery.sh                                                               # 启动 worker（Agent 在这里运行）
curl -s -X POST http://localhost:8000/predict/agent/query \                     # 提交后用返回的 task_id 轮询
  -H "Content-Type: application/json" \
  -d '{"image": "<assets/zidane.jpg 的 base64>"}'
```

示例统计图中人物有头发/无头发的人数（zidane.jpg → 2 人 1:1）；换属性字段 + 指令 + 工具即可换成任意属性任务。详见 [agent](docs/agent.md)。

## 模型注册表

多模型路由——复制示例注册表后按请求选模型（没有注册表文件时保持单模型行为，与上文完全一致）：

```bash
cp models/registry.example.yaml models/registry.yaml     # 编辑它，列出你的模型
./start.sh                                               # preflight 检查每个注册模型

python3 scripts/test_sync_detect.py --image assets/bus.jpg --model yolov8n          # 显式指定模型
python3 scripts/test_sync_detect.py --image assets/bus.jpg                            # 不带 model 字段 → 缺省模型
# 详见 docs/model-registry.md
```

## Docker

容器化一键起全栈——web + worker + RabbitMQ + Redis，本机零安装：

```bash
cp /path/to/yolov8n.onnx models/    # 模型 bind mount 进容器，不进镜像
docker compose up -d
curl http://localhost:8000/health   # 存活探针
```

RabbitMQ 管理界面：http://localhost:15672（guest/guest）。`docker compose down` 停止全部容器（加 `-v` 连数据卷一起删除）。详见 [quick-start](docs/quick-start.md) §4。

可选监控栈（Prometheus + Grafana）：`docker compose -f docker-compose.yml -f deploy/docker-compose.monitoring.yml up -d`——见 [metrics](docs/metrics.md)。

## 测试

测试刻意**免模型、免服务**：通过 FakePredictor seam 注入假预测器，从不加载权重、不访问网络——CI 跑的是同一套命令。

```bash
pytest tests/ -v                                  # 全量测试（无需模型文件、无需 RabbitMQ/Redis）
pip install pytest-cov
pytest tests/ -q --cov=app --cov=apis --cov=tasks --cov=engines --cov=utils
python3 -m py_compile app.py apis/*.py tasks/*.py engines/*.py utils/*.py tests/*.py scripts/*.py
```

覆盖率（基线约 81%）只作参考、不作门禁：scripts/ 与防御性错误分支刻意不做单测。测试策略细节（seam、异步 fake、注册表隔离）见 [docs/testing.md](docs/testing.md)。

## 文档

| 分类 | 文档 |
|---|---|
| 工程 | [concepts](docs/concepts.md) · [quick-start](docs/quick-start.md) · [architecture](docs/architecture.md) · [forking-contract](docs/forking-contract.md) · [add-engine](docs/add-engine.md) · [model-registry](docs/model-registry.md) · [api](docs/api.md) · [agent](docs/agent.md) · [embedding](docs/embedding.md) · [benchmark](docs/benchmark.md) · [deployment](docs/deployment.md) |
| 技术栈 | [stack](docs/stack.md) · [fastapi-migration](docs/fastapi-migration.md) |
| 规范 | [status-codes](docs/status-codes.md) · [logging](docs/logging.md) · [metrics](docs/metrics.md) · [testing](docs/testing.md) · [security](docs/security.md) |

带逐篇说明的完整索引：[docs/README.md](docs/README.md)。

## 致谢

| 分类 | 依赖 |
|---|---|
| 🌐 Web 与服务 | [FastAPI](https://fastapi.tiangolo.com/) · [Uvicorn](https://www.uvicorn.org/) · [Gunicorn](https://gunicorn.org/) · [prometheus_client](https://github.com/prometheus/client_python) |
| ⚡ 异步任务 | [Celery](https://docs.celeryq.dev/) · [RabbitMQ](https://www.rabbitmq.com/) · [Redis](https://redis.io/) |
| 🧠 推理、图像与检索 | [ONNX Runtime](https://onnxruntime.ai/) · [OpenCV](https://opencv.org/) · [Milvus Lite](https://milvus.io/) |
| 🤖 LLM 与 Agent | [OpenAI SDK](https://github.com/openai/openai-python) · [Pydantic AI](https://ai.pydantic.dev/) |

## 开源协议

[MIT License](LICENSE) © 2026 zjykzj
