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

## 快速开始

### 同步

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

可选：启用同步分割 / 分类能力（默认关，检测不受影响）：

```bash
# 1. 导出并放置模型（subprocess 调 yolo CLI——不 import ultralytics；导出后自动形状校验）
python3 scripts/export_yolo.py --task segment --task classify

# 2. 带开关启动（可只开一个；start.sh 只检查已启用能力的模型文件）
INFERFORGE_SEG=1 INFERFORGE_CLS=1 ./start.sh

# 3. 测试
python3 scripts/test_sync_segment.py --image assets/bus.jpg --save result_seg.jpg   # 分割
python3 scripts/test_sync_classify.py --image assets/bus.jpg                        # 分类（top-5）
```

可选：组合它们——同步管线接口（检测 → 裁剪 → 细粒度分类，如检测 `bus` → 识别 `school bus`）。复用上面两个模型；目标类用 `INFERFORGE_PIPELINE_TARGETS` 配置（默认 `car,truck,bus`）：

```bash
INFERFORGE_PIPELINE=1 ./start.sh
python3 scripts/test_sync_pipeline.py --image assets/bus.jpg --save result_pipeline.jpg   # 管线（检测 → 分类）
```

可选：图像 embedding——批量近重复检测（同步）+ gallery 检索 / 查重（异步 query-only，需 worker 与预建索引，见 docs/embedding.md）。先将 DINOv2-small 导出 ONNX 放入 models/：

```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu   # 一次性导出依赖
python3 scripts/export_dinov2.py                                                # -> models/dino2-small.onnx
```

```bash
# 同步批内去重：一批图里找出互为近似重复的分组（阈值 INFERFORGE_DUP_THRESHOLD，默认 0.95）
INFERFORGE_DEDUP=1 ./start.sh
python3 scripts/test_sync_dedup.py --image assets/bus.jpg --image assets/bus.jpg --image assets/zidane.jpg   # 去重

# 异步 gallery 检索 / 查重（worker-only：milvus-lite 索引单进程独占）
python3 scripts/build_gallery.py                # 先建索引——worker 必须已停止（gallery/ -> data/gallery.db）
INFERFORGE_ASYNC=1 INFERFORGE_SEARCH=1 ./start.sh
python3 scripts/run_search.py --image assets/bus.jpg --check    # task 层直测（检索 / 查重）
```

可选：多模型路由——复制示例注册表后按请求选模型（没有注册表文件时保持单模型行为，与上文完全一致）：

```bash
cp models/registry.example.yaml models/registry.yaml     # 编辑它，列出你的模型
./start.sh                                               # preflight 检查每个注册模型

python3 scripts/test_sync_detect.py --image assets/bus.jpg --model yolov8n          # 显式指定模型
python3 scripts/test_sync_detect.py --image assets/bus.jpg                            # 不带 model 字段 → 缺省模型
# 详见 docs/model-registry.md
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
python3 scripts/test_async_detect_callback.py --image assets/bus.jpg \
  --callback-url http://localhost:9000/result                                   # 结果完成后 POST 回调
```

拉取式 —— 提交任务，轮询直到结果就绪（结果缓存到 Redis）：

```bash
redis-server &                                                                  # 启动 redis（结果存储）
python3 scripts/test_async_detect_query.py --image assets/bus.jpg                    # 提交 + 轮询直到完成
```

VLM（图片理解，远程调用 LLM，仅异步形态）—— 在异步基础上再加 `INFERFORGE_LLM=1`，worker 侧配置远程模型：

```bash
INFERFORGE_LLM=1 INFERFORGE_ASYNC=1 ./start.sh                                  # 启动 web（注册 /predict/vlm/*）
INFERFORGE_LLM_MODEL=your-model \
INFERFORGE_LLM_API_KEY=your-key \
INFERFORGE_LLM_BASE_URL=https://your-llm-endpoint/v1 \
./start_celery.sh                                                               # 启动 worker（远程调用发生在 worker）
python3 scripts/test_async_vlm_query.py --image assets/bus.jpg                        # 提交 + 轮询直到文本答案返回
```

提示词由服务端固定（`INFERFORGE_LLM_PROMPT` 可覆盖），客户端只传图片。详见 [api](docs/api.md) §10。

配置也可以写进 `.env` 文件（`cp .env.example .env` 后填写——shell 已导出的环境变量优先）。

Agent（Pydantic AI 编排示例——检测工具 + LLM 属性判断，仅异步形态）—— 在异步基础上再加 `INFERFORGE_AGENT=1`，worker 侧复用 `INFERFORGE_LLM_*` 配置并需要本地模型：

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

### Docker

容器化一键起全栈 —— web + worker + RabbitMQ + Redis，本机零安装：

```bash
cp /path/to/yolov8n.onnx models/    # 模型 bind mount 进容器，不进镜像
docker compose up -d
curl http://localhost:8000/health   # 存活探针
```

RabbitMQ 管理界面：http://localhost:15672（guest/guest）。`docker compose down` 停止全部容器（加 `-v` 连数据卷一起删除）。详见 [quick-start](docs/quick-start.md) §4。

可选监控栈（Prometheus + Grafana）：`docker compose -f docker-compose.yml -f deploy/docker-compose.monitoring.yml up -d` —— 见 [metrics](docs/metrics.md)。

## 文档

- **工程文档** — concepts · quick-start · architecture · add-engine · api · deployment · benchmark
- **技术栈文档** — stack · fastapi-migration
- **规范文档** — status-codes · logging · metrics · testing · security · forking-contract

带逐篇说明的完整索引：[docs/README.md](docs/README.md)。

## 致谢

- **Web 与服务** — [FastAPI](https://fastapi.tiangolo.com/) · [Uvicorn](https://www.uvicorn.org/) · [Gunicorn](https://gunicorn.org/)
- **推理引擎** — [ONNX Runtime](https://onnxruntime.ai/) · [OpenCV](https://opencv.org/) · [NumPy](https://numpy.org/)
- **异步任务** — [Celery](https://docs.celeryq.dev/) · [RabbitMQ](https://www.rabbitmq.com/) · [Redis](https://redis.io/)
- **LLM 与 Agent** — [OpenAI SDK](https://github.com/openai/openai-python) · [Pydantic AI](https://ai.pydantic.dev/)
- **演示模型** — [Ultralytics YOLOv8n](https://docs.ultralytics.com/)

## 开源协议

[MIT License](LICENSE) © 2026 zjykzj
