# 性能基准（Benchmark）

> 压测工具、基线数据与复现步骤。检测链路（CPU 密集）与 VLM 链路（I/O 密集）性质不同，分开评估；所有数据都**绑定部署参数**——不同 workers / 并发 / 机型下的数字不可直接比较。最后更新：2026-08-24

## 1. 工具

### 1.1 `scripts/benchmark.py`（固定并发负载发生器，零新依赖）

| 模式 | 测量对象 | 前置条件 |
|------|---------|---------|
| `detect` | HTTP `POST /predict` 端到端延迟与吞吐 | `./start.sh` 起的 web（需 `models/yolov8n.onnx`） |
| `vlm-direct` | 进程内 `tasks.vlm.run_vlm`：图片管线 + 远程调用（不经 web/celery） | `INFERFORGE_LLM_MODEL` / `INFERFORGE_LLM_API_KEY`（+ 可选 `INFERFORGE_LLM_BASE_URL`） |
| `vlm-http` | `POST /predict/vlm/query` 提交 + 轮询的完整异步链路 | RabbitMQ + Redis + 带 `INFERFORGE_LLM_*` 的 worker |

关键参数：`--concurrency`（固定并发）、`--requests`、`--warmup`（默认 2——每个 web worker 各需一次请求触发懒加载模型）、`--image`（base64 载荷复用）、`--output`（stats JSON）。

统计口径：

- 百分位：numpy `linear` 插值（`index=(n-1)*p/100`），P50/P95/P99 优先于均值（长尾来自队列/GC）
- RPS = completed / wall 秒（closed system：并发数固定、全部请求先行提交）
- 结果分布：HTTP 模式记 envelope 业务码，`vlm-direct` 记结果标签（ok / llm_error / config_error / error）
- `detect` 的 warmup 请求不计入统计（懒加载冷启动单独观察，见 §3）

### 1.2 `scripts/mock_llm.py`（本地 OpenAI 兼容假端点）

`--port`（默认 8001）/ `--delay`（固定每请求延迟秒数）。响应体是 openai SDK 校验所需的完整 `ChatCompletion` 形状（**`created` 字段必填**——缺失会被 SDK 校验失败伪装成 code 9）。压测 VLM 时把 `INFERFORGE_LLM_BASE_URL` 指向它，隔离 provider 限流与计费变量。

## 2. 环境与参数（本次基线）

| 项 | 值 |
|----|----|
| 机器 | WSL2（Windows 11 宿主），conda env py312（Python 3.12） |
| 部署 | gunicorn `INFERFORGE_WORKERS=2` + UvicornWorker，preload_app，timeout 60 |
| 载荷 | `assets/bus.jpg`（487KB，810×1080 JPEG；base64 请求体约 650KB，远低于 20MB 上限） |
| 模型 | `models/yolov8n.onnx`（12.2MB），ONNX Runtime CPU |
| 假设 | 同机墙钟（队列等待指标的 `submitted_at` 跨进程）；无鉴权/限流（未设 `INFERFORGE_API_KEY` / `INFERFORGE_RATE_LIMIT`） |
| 限制 | 本机无 RabbitMQ、无 docker——celery 异步链路未出基线（见 §5） |

## 3. 检测基线（HTTP /predict，bus.jpg × 100 请求/档）

| 并发 | RPS | mean | p50 | p95 | p99 | 业务码分布 |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 1 | 6.70 | 0.148s | 0.127s | 0.276s | 0.310s | 0 × 100 |
| 2 | 8.67 | 0.228s | 0.198s | 0.436s | 0.471s | 0 × 100 |
| 4 | 8.26 | 0.478s | 0.413s | 0.885s | 0.970s | 0 × 100 |
| 8 | 9.61 | 0.811s | 0.739s | 1.323s | 1.595s | 0 × 100 |

原始数据：`logs/bench-detect-c*.json`（gitignored）。

解读：

- **吞吐在并发 2 后饱和**（8.3–9.6 RPS）：2 个 worker 共享 CPU 核，推理 CPU 密集，并发再高只是排队——饱和点 = 可用 CPU × worker 数，扩容需加 worker（`INFERFORGE_WORKERS=N`）或换 GPU 后端
- **延迟随并发近似线性增长**而 RPS 持平：经典 CPU 排队行为，P99/mean 比 P50 上升更快（长尾来自排队）
- 单请求稳态延迟约 110–130ms（bus.jpg），其中推理分段耗时可直接看 `inferforge_predict_phase_seconds`（§7）

## 4. VLM 基线（vlm-direct + mock，bus.jpg × 30 请求/档）

本地 mock 延迟模拟远程 LLM；每请求延迟 ≈ mock 延迟 + ~20ms（图片解码/编码 + HTTP 序列化开销）。

| mock 延迟 | 并发 | RPS | p50 | p95 | p99 | 结果分布 |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 0.1s | 1 | 8.45 | 0.118s | 0.122s | 0.125s | ok × 30 |
| 0.1s | 4 | 29.53 | 0.125s | 0.135s | 0.139s | ok × 30 |
| 1.0s | 1 | 0.98 | 1.019s | 1.026s | 1.031s | ok × 30 |
| 1.0s | 4 | 3.62 | 1.033s | 1.051s | 1.056s | ok × 30 |

原始数据：`logs/bench-vlm-c*-d*.json`（gitignored）。

解读：

- **I/O 密集的横向扩展近乎线性**：mock 1.0s 档并发 4 的 RPS ≈ 3.6 ≈ 4/1.05——与检测的 CPU 饱和形成对照，这正是 vlm worker 建议 `./start_celery.sh -c N` 的原因
- 真实 provider 的延迟与限流由 provider 决定：换真实端点后基线数字不同，但**方法与读法不变**；`vlm-direct` 不产生服务端指标（指标记在脚本进程自己的注册表），服务端 `inferforge_vlm_remote_call_seconds` 需走 worker 路径（§5）

## 5. 队列等待（指标已实现，基线待有 broker 环境）

`inferforge_celery_queue_wait_seconds{task}` 已实现并单测覆盖（api 提交时打 `submitted_at` 墙钟戳，`task_prerun` 相减、负值钳 0；不用 `task_received`——它在任务被取走后触发，测不到 broker 排队时间）。**本机无 RabbitMQ（无二进制、无 docker），未出基线**。有 broker 环境后执行：

```bash
INFERFORGE_ASYNC=1 ./start.sh
./start_celery.sh
python3 scripts/benchmark.py --mode vlm-http --image assets/bus.jpg \
  --concurrency 4 --requests 30        # 提交+轮询端到端（含队列等待）
# 压测期间观察：
curl -s localhost:8000/metrics | grep inferforge_celery_queue_wait_seconds
```

预期读法：worker 满载时队列等待随并发上升（`worker_prefetch_multiplier=1`，每子进程一次一个任务）；`-c N` 扩容后等待应回落。

## 6. 复现步骤

```bash
# 检测
INFERFORGE_WORKERS=2 ./start.sh
python3 scripts/benchmark.py --mode detect --image assets/bus.jpg \
  --concurrency 4 --requests 100 --output logs/bench-detect-c4.json

# VLM（mock 端点）
python3 scripts/mock_llm.py --port 8001 --delay 1.0 &
INFERFORGE_LLM_MODEL=test INFERFORGE_LLM_API_KEY=x \
INFERFORGE_LLM_BASE_URL=http://127.0.0.1:8001/v1 \
python3 scripts/benchmark.py --mode vlm-direct --image assets/bus.jpg \
  --concurrency 4 --requests 30 --output logs/bench-vlm-c4-d1.0.json
```

## 7. 指标联动

压测期间 `/metrics` 可观察（配合 [metrics.md](metrics.md)）：

- 端到端：`inferforge_http_request_duration_seconds{route="/predict"}`
- 检测瓶颈定位：`inferforge_predict_phase_seconds{phase="pre|infer|post"}`
- VLM 远程调用：`inferforge_vlm_remote_call_seconds` / `inferforge_vlm_remote_errors_total`（worker 路径）
- 异步链路：`inferforge_celery_queue_wait_seconds{task}` + `inferforge_celery_task_duration_seconds{task}`
- 业务码分布：`inferforge_responses_total{code}`（压测若出现非 0 码立即可见）
