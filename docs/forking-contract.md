# 分叉契约（Forking Contract）

> 本仓库是**模板，不是库**：使用方式是 fork/clone 后把代码变成你自己的服务，任意修改、完全拥有。但模板上游会持续演进——本文约定哪些区域你"随便改"、哪些区域"改前想清楚"、以及合并上游更新时冲突怎么取舍。分层背景见 [architecture.md](architecture.md)。最后更新：2026-08-22

## 1. 模板的本质

- **模板 ≠ 依赖库**：你 fork 的是整个可运行服务（含 Dockerfile、compose、启动脚本、日志轮转），不是 `pip install` 进来的黑盒。生产事故发生时，你能读到自己仓库里的每一行
- **上游更新是可选输入**：本仓库的演进（修缺陷、加组件、升级依赖）以 CHANGELOG 发布；跟进与否由你决定，没有"必须升级"的压力
- **取舍总原则**：**你的业务改动优先，上游的基础设施改进优先**（见 §4）

## 2. 三个区域

| 区域 | 文件 | 规则 |
|------|------|------|
| **绿区：业务区（你拥有）** | `apis/`（路由、Pydantic 模型、响应组装）、`tasks/`（业务编排、任务逻辑）、新增的 `engines/<name>.py`、`requirements*.txt`、`scripts/` | 随便改。这是模板留给你的"主战场"，上游不会替你维护它们 |
| **黄区：横切机制（可改，但有合并成本）** | `utils/`（envelope、日志、request_id、图片转换、metrics、auth、rate limit）、`app.py` 装配顺序、`celery_app.py`、`gunicorn.conf.py`、部署脚本与 Docker 文件 | 通常不用动。要动（比如 envelope 加字段、日志改格式）先读对应文档，改后合并上游时需逐处三方合并 |
| **红区：模板的 API（改前先想清楚）** | `engines/base.py`（`BasePredictor` contract）、`{code, message, data}` envelope 与 [status-codes.md](status-codes.md) 状态码表、分层依赖方向（`app -> apis -> tasks -> engines`） | 这些是"模板其余部分成立的公理"。你在红区的改动会让上游更新无法干净合并，也让你无法使用上游后续的文档与组件——如确需调整，优先向上游提 issue/PR |

**为什么红区这么划**：`BasePredictor` 是算法插槽，envelope 是 client contract，依赖方向是架构公理。模板的全部价值（换引擎只动一层、422 不泄漏、request_id 全链路）都建立在这三者上；下游改它们 = 亲手拆掉模板的承重墙。绿区/黄区随便动，红区动了要清醒。

**三色之外还有第四类：`deploy/` 参考工件**——示例配置（logrotate、nginx 灰度分流等），拷走即用、自由修改，不参与 core contract；上游更新它们不影响你的 fork，你改它们也不影响合并上游。

## 3. 日常开发对照（常见场景）

| 我想做的事 | 属于哪个区 | 建议做法 |
|-----------|-----------|---------|
| 换个检测算法（TensorRT/Triton/新模型） | 绿区 | 按 [add-engine.md](add-engine.md) 新增引擎 + 改 task 持有 |
| 加一个新接口 / 改参数校验 | 绿区 | 改 `apis/`；结构校验放 `schemas.py`，语义校验放 task 层 |
| envelope 里加业务字段（如 `data.cost_ms`） | 黄区 | 改 `utils/response.py` + 同步 [status-codes.md](status-codes.md)；记录改动，合并上游时保留 |
| 新增业务状态码（如 `code=7`） | 黄区 | 注册进 `utils/response.py` 文档串 + [status-codes.md](status-codes.md)；**避开 0-6 已有语义**，上游新增码可能与你冲突 |
| 改 `BasePredictor` 方法签名 / envelope 格式 / 状态码语义 | 红区 | 先提 issue 说明动机；上游吸收后所有下游受益，你自己 fork 里单改会断掉合并路径 |

## 4. 合并上游更新的策略

**什么时候合并**：CHANGELOG 里出现了——横切机制修复（日志/envelope/request_id/安全）、你需要的组件（新引擎参考实现、新中间件）、依赖升级（Python floor、RabbitMQ 兼容等）。

**什么时候不合并**：你的业务层已经很定制化，上游更新只是文档、重构或你用不到的组件 → cherry-pick 所需提交，或直接读 diff 手动搬运几行。

**冲突取舍**：

| 冲突位置 | 取舍 |
|---------|------|
| 绿区冲突 | **你的优先**——那是你的业务 |
| 黄区冲突 | 逐处判断：横切机制的**改进**（缺陷修复、通用能力）优先采用上游；你加的业务字段/码保留自己的 |
| 红区冲突 | 不应该发生——发生了说明你或上游破坏了 contract，去提 issue/PR 对齐 |

**能干净合并的前提**：分层把变更关在单一层内（见 [architecture.md](architecture.md) §3 替换原则）——上游换 Web 框架不动 `tasks/`/`engines/`，你换算法不动 `utils/`。双方都守层，冲突就少。
