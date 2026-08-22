# 部署指南（Deployment）

> 两种常见部署形态的完整方案：**线上灰度发布**（新旧版本短期并存、一个入口分流）与**测试/生产环境长期共存**（两套独立栈、各自入口）。两者目的不同、隔离级别不同，分开规划。最后更新：2026-08-22

## 0. 环境与灰度是什么

**环境（environment）**：同一套软件，为不同目的部署的实例——关键是**目的**不同：

| 环境 | 目的 | 特征 |
|------|------|------|
| 测试环境 | 开发验证：新功能先在自己能控制的地方跑 | 流量自造，挂了不心疼，版本可超前生产 |
| 生产环境 | 对外服务：真实用户、真实流量 | 挂了就是事故，版本必须稳 |

**灰度环境**不是第四种环境，而是**发布过程中生产环境的临时形态**：生产入口背后同时挂新旧两个版本，新版本只接一小部分流量，发布收敛后即消失。

**灰度分流（canary split）**：入口（nginx/ALB）按规则把生产流量按比例导给新版本——先 10% → 观察无异常 → 30% → 100% → 下线旧版本。核心逻辑是**控制爆炸半径**：新版本出问题只影响小比例流量，回滚只需改权重、杀进程，一分钟完成。

**什么时候用哪个**：

| 场景 | 用什么 | 生命周期 |
|------|--------|---------|
| 日常开发、新功能验证 | 测试环境（与生产长期共存） | 长期 |
| 发新版到生产，想小范围先验证 | 灰度环境 + 灰度分流 | 短期（收敛到一个版本） |
| 新旧版本不兼容（envelope 契约破坏） | 灰度不适用，只能停服切换或蓝绿 | — |

灰度成立的前提是**新旧可互操作**——本项目的 envelope 契约跨版本稳定，web/worker 两层才能独立灰度（§2.1 详述）。

## 1. 两种形态的本质区别

| 维度 | 线上灰度（canary） | 测试/生产长期共存 |
|------|-------------------|-------------------|
| 目的 | 验证新版本 → 收敛到一个版本 | 长期并存：测试环境做开发验证，生产环境对外服务 |
| 入口 | **同一个地址**，nginx 按规则分流到新旧后端 | **不同地址**（域名或端口） |
| RabbitMQ / Redis | 共享（envelope 契约兼容） | **完全隔离**（独立实例，或不同 vhost / 不同 DB index） |
| 日志 | 可混（request_id 归因） | 各自独立 |
| 生命周期 | 短期：10% → 30% → 100%，验证完下线旧版本 | 长期 |
| 版本 | 新旧相邻版本 | 各自独立演进（测试环境可超前） |

## 2. 场景一：线上灰度

### 2.1 为什么「web 流量灰度 + worker 先全量」可行

envelope 契约（`{code, message, data}` + detections 结构）是跨版本稳定契约：新旧 web 都能消费同一套 worker 的结果，新旧 worker 的结果新旧 web 都能解析。这让两层可以**独立发布**。

worker 层不适合按比例灰度——celery worker 从共享队列消费，任务"谁抢到算谁的"，天然无法按比例路由。因此 worker 采用先全量（envelope 兼容兜底），web 层做流量灰度。

### 2.2 拓扑

```
                     ┌─ prod-web   (当前版本, 2 workers, :8001)
Nginx/ALB 按比例分流 ─┤
                     └─ canary-web (新版本, 2 workers, :8002)
                              │ delay()
                    RabbitMQ（同一个 broker）
                              │
                        worker（先全量新版本）
                    Redis（同一个结果存储）
```

### 2.3 Nginx 分流配置

```nginx
# 按权重：10% 流量进灰度（两个版本必须放在同一个 upstream 组内，权重才生效）
upstream inferforge_web {
    server 127.0.0.1:8001 weight=90;   # 当前版本
    server 127.0.0.1:8002 weight=10;   # 灰度版本
}
```

分流维度按需选择：

- **权重**（随机分流，适合无差别放量）
- **header**（`X-Canary: 1` 强制走灰度，供测试固定验证）
- **粘性**（同一调用方始终同版本，避免新旧行为交替出现）

完整可拷贝的参考配置（权重切流 + header 定点切换、代理头、20MB body 上限、长推理超时）：[../deploy/nginx-canary.conf](../deploy/nginx-canary.conf)。

### 2.4 发布顺序

1. worker 先全量上新版本（envelope 兼容，无风险）
2. 起 canary-web 渐放流量：10% → 30% → 100%
3. 全量后下线旧 web

### 2.5 观察与回滚

- **观察**：`/health/ready` 保证冷启动实例不接流量；日志按 `request_id` 比对同流量在两侧的表现；业务码分布（code 1/2/3 比例）与推理延迟是核心指标
- **回滚**：nginx 切流 + 杀掉 canary 进程，一分钟内完成

## 3. 场景二：测试/生产环境长期共存

两套完整独立栈，关键在于**三个隔离点**，当前实现全部靠环境变量完成：

### 3.1 基础设施隔离

```bash
# 测试环境
CELERY_BROKER_URL=amqp://guest:guest@localhost:5672/test   # RabbitMQ 不同 vhost
INFERFORGE_REDIS_URL=redis://localhost:6379/1              # Redis 不同 DB index
INFERFORGE_MODEL_PATH=/path/to/test/yolov8n.onnx
INFERFORGE_ASYNC=1 ./start.sh

# 生产环境
CELERY_BROKER_URL=amqp://guest:guest@localhost:5672/prod
INFERFORGE_REDIS_URL=redis://localhost:6379/2
INFERFORGE_MODEL_PATH=/path/to/prod/yolov8n.onnx
INFERFORGE_ASYNC=1 ./start.sh
```

- **RabbitMQ**：共享实例时用不同 vhost 隔离（`amqp://...:5672/test` 与 `/prod`）；要求强隔离时起独立实例（不同端口）
- **Redis**：共享实例时用不同 DB index（`/1`、`/2`）；强隔离时独立实例
- **worker**：同理各起一个（`./start_celery.sh` 读同一组环境变量），两套互不串任务

### 3.2 访问地址分离

两套 web 端口错开，nginx 用两个 `server_name` 分别反代：

```nginx
server {
    server_name test.example.com;
    location / { proxy_pass http://127.0.0.1:8001; }
}
server {
    server_name prod.example.com;
    location / { proxy_pass http://127.0.0.1:8002; }
}
```

### 3.3 目录与日志

建议**两份独立目录**部署（或至少 `INFERFORGE_MODEL_PATH` 指开）：当前 `logs/` 路径基于项目目录定位，同一目录起两套会把日志混在一起；logrotate 配置（`deploy/logrotate.conf`）也要各指各的路径。

### 3.4 Docker Compose 多环境

用 `-p` 起两个独立 project：

```bash
docker compose -p inferforge-test up -d    # 测试栈
docker compose -p inferforge-prod up -d    # 生产栈
```

注意：`docker-compose.yml` 的端口映射写死（8000/5672/6379/15672），起第二套前需用 override 文件错开映射，例如 `docker-compose.override.test.yml` 里改 `web` 的 `ports` 为 `"8001:8000"` 等。

## 4. 当前实现的支撑点与限制

| 支撑 ✅ | 限制 ⚠️ |
|---|---|
| `/health` + `/health/ready` 逐实例探活（新实例冷启动自动绕开） | 无 Prometheus 指标——灰度效果对比靠日志与业务码 |
| envelope 契约稳定 → web/worker 两层独立发布 | worker 与 web 共用同一队列——模型灰度只能先全量（无按队列路由） |
| 环境变量配置化（MODEL_PATH/BROKER/URL/WORKERS）→ 多实例易起 | 无流量染色标记——灰度流量靠 request_id 事后归因 |
| request_id 全链路 → 同流量两侧日志可对比 | 多实例 env 管理靠手工，无配置中心 |
