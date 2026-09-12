# InferForge

> 🔨 从推理内核到部署——InferForge 把视觉模型锻造成生产服务，Agent-First。
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

InferForge 是面向**视觉推理服务**的生产级服务模板：推理内核之上的一层薄服务外壳，把任意视觉模型变成可部署的 HTTP 服务。

- **Agent-First 开发。** 模板以 LLM/Agent 作为首要开发主体设计：在新项目或老项目的开发中，agent 参考本工程的实现进行开发。
- **面向业务开发的 Web 服务与任务架构。** 提供对外的 Web 服务和任务实现的架构模板：服务基础设施开箱即得，业务任务与接口由你定义。
- **与底层推理引擎无关。** onnxruntime、TensorRT、Triton 等任意推理后端都可自由替换，服务本身不受影响。

在视觉内核之上，模板还内置了 VLM 与 Agent 编排的参照实现（远程 LLM 集成、异步 query-only），演示从视觉推理延伸到 LLM 编排的完整路径。

## 快速开始

开发由 agent 驱动——三个示例走完"空壳 → 可用的服务"完整路径（以 Claude Code 为例，其他编码 agent 按同样对话操作——workflow 文档与工具无关）：

### 1. 初始化一个 web 服务

```bash
# 下载模板（只读工厂，永不修改）
git clone https://github.com/zjykzj/InferForge.git ~/InferForge
```

```text
# 在模板目录启动 Claude Code（没给路径？agent 会先问）
cd ~/InferForge && claude
> 初始化一个 web 服务到 /srv/my-service。

Agent：逐个确认横切机制（metrics / 鉴权 / 限流 / 日志——默认都不要）→
      assemble.py --target /srv/my-service → 生成身份文件
      （README / CLAUDE.md）→ 配置 → 底座验收全绿
      → git init + 首次提交（默认装配 = 契约内核 + 健康探针）
```

```bash
# 验证：服务起得来，健康探针可用
cd /srv/my-service && python3 app.py
curl http://localhost:8000/health       # → {"code":0,"message":"success","data":{"status":"ok"}}
```

### 2. 新增同步检测接口

```text
cd /srv/my-service && claude
> 帮我新增一个同步检测接口，模型用 yolov8n。

Agent：需求分解（形态=同步 × 能力=检测，canonical 参照在模板目录）→
      分层落位提案 → 实现 → pytest + check_capability.py 通过 → 提交
```

```bash
python3 scripts/test_sync_detect.py --image assets/bus.jpg   # → {"code":0,"data":{...检测框...}}
```

### 3. 新增异步分类接口

```text
> 再帮我新增一个异步分类接口，query 方式。

Agent：需求分解（形态=异步 query × 能力=分类）、边界检查无命中 → 分层落位提案：
      引擎层零改动 ✅、任务抄 detection_query canonical ✅、
      开关双门（INFERFORGE_ASYNC 会顺带注册检测的异步接口）⚠️ 等你拍板
> 确认。

Agent：实现 → pytest + check_capability.py 通过 → 提交
```

```bash
INFERFORGE_ASYNC=1 ./start.sh
./start_celery.sh
python3 scripts/test_async_cls_query.py --image assets/bus.jpg   # 提交 → 轮询 → top-5
```

之后新增能力同理：agent 从 `~/InferForge`（模板目录 = 参照库）抄 canonical 实现。[docs/README.md](docs/README.md) 的入口表覆盖初始化 / 新增能力 / 修改服务 / 引擎工作；每个新工程自带的架构检查保证每次改动都在契约之内；`.claude/skills/` 为 Claude Code 提供同一套流程的薄壳。

## 运行示例服务

先跑一下模板自带的检测服务，看看效果，再初始化你自己的工程：

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

配置可写进 `.env` 文件（`cp .env.example .env` 后填写——shell 已导出的变量优先）。异步（Celery + RabbitMQ + Redis，callback/query）、其余能力与 Docker 全栈：见 [quick-start](docs/quick-start.md)（§2–3 异步、§4 容器化）与 [api](docs/api.md)。测试刻意免模型、免服务（`pytest tests/`——见 [testing](docs/testing.md)）。

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

开关均为可选环境变量（检测常开）；开关只决定路由是否存在，不决定加载哪个模型——那是注册表的职责（[model-registry](docs/model-registry.md)）。所有异步能力共用同一套 Celery + RabbitMQ + Redis 底座；投递方式按请求选择——callback 或 query。检索 / VLM / Agent 无 callback 形态。

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

## 文档

| 分类 | 文档 |
|---|---|
| 使用指南 | [quick-start](docs/quick-start.md) · [architecture](docs/architecture.md) · [api](docs/api.md) · [model-registry](docs/model-registry.md) · [agent](docs/agent.md) · [embedding](docs/embedding.md) · [benchmark](docs/benchmark.md) · [deployment](docs/deployment.md) |
| 领域知识 | [concepts](docs/concepts.md) · [release-strategies](docs/release-strategies.md) |
| 规范 | [forking-contract](docs/workflow/forking-contract.md) · [bootstrap](docs/workflow/bootstrap.md) · [assembly](docs/assembly.md) · [add-capability](docs/workflow/add-capability.md) · [add-engine](docs/workflow/add-engine.md) · [modify-service](docs/workflow/modify-service.md) · [status-codes](docs/status-codes.md) · [logging](docs/logging.md) · [metrics](docs/metrics.md) · [testing](docs/testing.md) · [security](docs/security.md) |
| 技术栈 | [stack](docs/stack.md) · [design-principles](docs/design-principles.md) · [fastapi-migration](docs/fastapi-migration.md) |

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
