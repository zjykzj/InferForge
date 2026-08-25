# 指标规范（Metrics）

> InferForge 的 Prometheus 指标：有哪些、怎么抓取、什么时候需要监控栈。指标与日志的分工：日志回答"发生了什么"（单请求现场），指标回答"量是多少"（趋势与告警）。最后更新：2026-08-24

## 1. 指标清单

| 指标 | 类型 | 标签 | 含义 |
|------|------|------|------|
| `inferforge_http_requests_total` | Counter | method, route | 各接口请求量（route 是路径模板，如 `/predict/query/{task_id}`） |
| `inferforge_http_request_duration_seconds` | Histogram | method, route | 端到端请求延迟 |
| `inferforge_responses_total` | Counter | code | envelope 业务码分布（0–10） |
| `inferforge_predict_phase_seconds` | Histogram | phase, task | 推理三段耗时（pre / infer / post），按能力分（detect / segment / classify） |
| `inferforge_predictor_loaded` | Gauge | task, model（multiprocess 模式下自动带 `pid` 标签） | 本进程某能力的某注册模型 predictor 是否已加载（0/1，与 `/health/ready` 对应；model 为注册模型名，非注册表调用方为空串） |
| `inferforge_celery_tasks_total` | Counter | task, state | worker 任务执行数与状态（success / failure） |
| `inferforge_celery_task_duration_seconds` | Histogram | task | worker 任务耗时 |
| `inferforge_vlm_remote_call_seconds` | Histogram | — | 远程 LLM 调用耗时（含 SDK 重试；无标签防基数爆炸，显式桶到 180s） |
| `inferforge_vlm_remote_errors_total` | Counter | — | 远程 LLM 调用失败数（SDK 重试后仍 OpenAIError） |
| `inferforge_celery_queue_wait_seconds` | Histogram | task | 任务在 broker 队列中的等待时长（显式桶到 300s） |

埋点位置：请求计数在 `MetricsMiddleware`（`utils/metrics.py`）、业务码计数在 `utils/response.py`（envelope 的唯一出口）、推理耗时在 `engines/yolo.py` / `engines/yolo_seg.py` / `engines/yolo_cls.py`（`observe_phase(phase, seconds, task=...)` 按能力打标签，检测调用点用默认值 `detect`）、predictor 加载在 `tasks/*.py` 的 `get_predictor()`（`mark_predictor_loaded(task, model)`，注册模型名打 `model` 标签）、worker 计数在 `celery_app.py` 的 celery signals、远程调用延迟/错误在 `tasks/vlm.py` 与 `tasks/agent.py`（Agent 复用 vlm 的 `inferforge_vlm_remote_call_seconds` / `inferforge_vlm_remote_errors_total` 两个指标——语义是「远程 LLM 调用」而非仅 VLM）、队列等待在 `utils/metrics.py` 的 `record_queue_wait`（`celery_app.py` 的 `task_prerun` 调用——4 个异步 apis 提交任务时携带 `submitted_at` 墙钟时间戳，同机/NTP 假设，负值钳为 0）。

已知限制：`inferforge_predict_phase_seconds` 不带 `model` 标签——phase 耗时从引擎内部上报，引擎不知道自己的注册名；要补标签需在构造后回写 predictor 状态或扩展 `BasePredictor` contract，当前暂不为之。多模型场景下想区分各模型延迟时，可先按部署拆分（各部署各跑一个模型），或给引擎实例挂属性后自行扩展。

## 2. 暴露端点：GET /metrics

- 返回 Prometheus text format，**不走 envelope**（协议端点例外，见 [status-codes.md](status-codes.md)）
- 计数常开、无开关——不接 Prometheus 时就是内存里的计数器，服务行为与性能都不受影响；日常开发可完全忽略

## 3. multiprocess 模式

gunicorn 每个 worker 有独立的内存计数，直接暴露会抓到"随机 worker 的部分数据"。设置 `PROMETHEUS_MULTIPROC_DIR` 后（prometheus_client 在 import 时读取），各进程把指标写入该目录的文件，抓取 `/metrics` 时由 `MultiProcessCollector` 聚合：

- `start.sh` / `start_celery.sh` 自动 export 到 `./logs/metrics`；`docker-compose.yml` 设置 `/app/logs/metrics`（web 与 worker 共享 `./logs` 挂载）
- **web 与 worker 必须指向同一目录**——worker 的指标经 web 的 `/metrics` 一并聚合上报
- 未设置时（开发 `python3 app.py`）：单进程默认注册表，行为不变

**死进程文件卫生（重要）**：prometheus_client 不会清理已退出进程的指标文件——若不做任何处理，死进程的 gauge（如 `predictor_loaded=1`）会永远聚合进 `/metrics`，计数器也会被虚高。本项目的处理分两层：

1. **优雅退出自清理**：`utils.metrics.mark_process_dead()` 按 `*_{pid}.db` glob 删除本进程的指标文件（**不依赖** prometheus_client 自带的 `mark_process_dead`——本项目 pin 的版本 ≤0.26 里它只删 live-mode gauge，会漏掉 `gauge_all`/`counter`/`histogram`）。挂载点（均经实测验证）：
   - **gunicorn worker**：app lifespan shutdown（`app.py`）——每个 worker 退出前删自己的运行期文件
   - **gunicorn master**：`on_exit` 服务器钩子（`gunicorn.conf.py`）——master 因 `preload_app` 在 import 时就写下了自己的 counter/histogram 文件，但它从不服务请求，没有 lifespan 钩子，只能在退出时删
   - **celery 主进程**：`worker_shutdown` 信号（`celery_app.py`）——同样清理 import 期文件
   - **celery prefork 子进程**：`worker_process_shutdown` 信号（`celery_app.py`）——每个子进程退出前删自己的文件
   - **start.sh 的 preflight**：导入项目模块前 unset `PROMETHEUS_MULTIPROC_DIR`——不产生文件，也就不需要清理
   - 注意：**不要**用 gunicorn 的 `worker_exit` 钩子——uvicorn worker 会把 SIGTERM/SIGINT 重置为 SIG_DFL（uvicorn issue #894），worker 的退出路径走不到 gunicorn 的 worker_exit finally（实测三次均不触发）
2. **部署卫生兜底**：master / 主进程被 `kill -9`、进程崩溃时没有退出钩子，文件会残留。部署更新时应在**整套栈都停掉后**清空该目录（web 与 worker 共享同一目录，单边清空会误删另一侧存活进程的文件）——代价是丢掉死进程最后一刻的计数，对运维是标准做法。另外注意：残留文件携带**旧版本进程的 schema**（如旧标签集），与新版本进程的文件混在一起会让看板对不上——这也是升级后清空目录的理由。

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
