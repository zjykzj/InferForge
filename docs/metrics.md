# 指标规范（Metrics）

> InferForge 的 Prometheus 指标：有哪些、怎么抓取、什么时候需要监控栈。指标与日志的分工：日志回答"发生了什么"（单请求现场），指标回答"量是多少"（趋势与告警）。最后更新：2026-08-24

## 1. 指标清单

| 指标 | 类型 | 标签 | 含义 |
|------|------|------|------|
| `inferforge_http_requests_total` | Counter | method, route | 各接口请求量（route 是路径模板，如 `/predict/query/{task_id}`） |
| `inferforge_http_request_duration_seconds` | Histogram | method, route | 端到端请求延迟 |
| `inferforge_responses_total` | Counter | code | envelope 业务码分布（0–9） |
| `inferforge_predict_phase_seconds` | Histogram | phase | 推理三段耗时（pre / infer / post） |
| `inferforge_predictor_loaded` | Gauge | —（multiprocess 模式下自动带 `pid` 标签） | 本进程 predictor 是否已加载（0/1，与 `/health/ready` 对应） |
| `inferforge_celery_tasks_total` | Counter | task, state | worker 任务执行数与状态（success / failure） |
| `inferforge_celery_task_duration_seconds` | Histogram | task | worker 任务耗时 |
| `inferforge_vlm_remote_call_seconds` | Histogram | — | 远程 LLM 调用耗时（含 SDK 重试；无标签防基数爆炸，显式桶到 180s） |
| `inferforge_vlm_remote_errors_total` | Counter | — | 远程 LLM 调用失败数（SDK 重试后仍 OpenAIError） |
| `inferforge_celery_queue_wait_seconds` | Histogram | task | 任务在 broker 队列中的等待时长（显式桶到 300s） |

埋点位置：请求计数在 `MetricsMiddleware`（`utils/metrics.py`）、业务码计数在 `utils/response.py`（envelope 的唯一出口）、推理耗时在 `engines/yolo.py`、worker 计数在 `celery_app.py` 的 celery signals、远程调用延迟/错误在 `tasks/vlm.py` 与 `tasks/agent.py`（Agent 复用 vlm 的 `inferforge_vlm_remote_call_seconds` / `inferforge_vlm_remote_errors_total` 两个指标——语义是「远程 LLM 调用」而非仅 VLM）、队列等待在 `utils/metrics.py` 的 `record_queue_wait`（`celery_app.py` 的 `task_prerun` 调用——4 个异步 apis 提交任务时携带 `submitted_at` 墙钟时间戳，同机/NTP 假设，负值钳为 0）。

## 2. 暴露端点：GET /metrics

- 返回 Prometheus text format，**不走 envelope**（协议端点例外，见 [status-codes.md](status-codes.md)）
- 计数常开、无开关——不接 Prometheus 时就是内存里的计数器，服务行为与性能都不受影响；日常开发可完全忽略

## 3. multiprocess 模式

gunicorn 每个 worker 有独立的内存计数，直接暴露会抓到"随机 worker 的部分数据"。设置 `PROMETHEUS_MULTIPROC_DIR` 后（prometheus_client 在 import 时读取），各进程把指标写入该目录的文件，抓取 `/metrics` 时由 `MultiProcessCollector` 聚合：

- `start.sh` / `start_celery.sh` 自动 export 到 `./logs/metrics`；`docker-compose.yml` 设置 `/app/logs/metrics`（web 与 worker 共享 `./logs` 挂载）
- **web 与 worker 必须指向同一目录**——worker 的指标经 web 的 `/metrics` 一并聚合上报
- 未设置时（开发 `python3 app.py`）：单进程默认注册表，行为不变

## 4. 监控栈（可选）

不接监控栈，服务照常运行。要看指标时，用参考工件起 Prometheus + Grafana（与主 compose 合并使用）：

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.monitoring.yml up -d
```

- Prometheus：http://localhost:9090（Status → Targets 中 `inferforge` 应为 UP）
- Grafana：http://localhost:3000（admin / admin；添加数据源 `http://prometheus:9090`）
- 裸机部署：`deploy/prometheus.yml` 把 targets 改成 `localhost:8000`，自行起 Prometheus/Grafana

## 5. 与日志、探针的分工

| 机制 | 回答什么 | 生命周期 |
|------|---------|---------|
| 指标 | 量是多少：错误率、延迟 p95、任务积压 | 聚合数字，长期保存，画趋势、配告警 |
| 日志 | 发生了什么：单请求现场，request_id 归因 | 按天轮转（logrotate） |
| 探针 | 现在能不能用：存活/就绪 | orchestrator 即时判断，不用于趋势 |

## 6. 对灰度的价值

[deployment.md](deployment.md) §2.5 的观察手段（业务码分布、推理延迟）在这里变成图表：`inferforge_responses_total{code}` 直接对比新旧版本的错误率，`inferforge_predict_phase_seconds` 对比延迟分布。当前模板按进程聚合，版本对比靠两份部署各自注册为 Prometheus 目标实现。
