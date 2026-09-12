# 新增业务能力（Add Capability）

> 在新工程中新增一个业务能力的完整流程：先按 §2 分解需求、查边界、确认架构提案，再按 §3 的能力文件集（footprint）逐层实现，每层都有 canonical 参照可模仿。模板没有同形态参照的场合，走 §6 契约推导路径。前提：已完成 [bootstrap.md](bootstrap.md) 的初始化与底座验收。最后更新：2026-09-11

## 1. 成长剧本：业务阶段与形态选择

新工程的能力通常按下面三个阶段演进，每个阶段对应一种服务形态——这是模板在自身演进中沉淀下来的选择，业务诉求相同就不用重新发明：

| 阶段 | 业务诉求 | 形态 | 引入的机制 | 模板 canonical |
|------|---------|------|-----------|---------------|
| 一 | 本地推理、毫秒~秒级、请求-响应就够 | **同步** | FastAPI 线程池并发、predictor 懒加载 | `sync_detect` 全链路 |
| 二 | 耗时/排队，需要"做完通知我"或"我自己查" | **异步** callback / query | Celery + broker、恰好一次投递、队列等待指标、结果 TTL | `detection_callback` / `detection_query` |
| 三 | 依赖远程服务（LLM）或单进程独占资源（本地向量库） | **query-only**（无 sync、无 callback） | worker-only 依赖懒加载、远端调用指标 | `vlm_query` / `search_query` |

每个机制的存在理由都写在其参照实现的 docstring 与 [architecture.md](../architecture.md) 里——模仿前先读参照的"为什么"，避免照猫画虎。

## 2. Step 0：需求分解与形态决策

新增任何能力前，先把需求分解到两个正交的轴上，再回答形态决策表：

| 业务特征 | 选 | 细节看 |
|---------|-----|--------|
| 本地推理、请求-响应够用 | 同步 | §4 |
| 本地推理但耗时长、需要服务端主动通知 | 异步 callback | §5 |
| 本地推理但耗时长、客户端轮询 | 异步 query | §5 |
| 依赖远程服务 / 单进程独占资源 | query-only | §5 |
| 模板没有同形态参照 | 契约推导 | §6 |

callback 与 query 可以并存（检测能力就是双变体），选型是**按请求**的——同一能力的两个变体共享 task 层。

### 2.1 两个正交的轴（不枚举组合）

形态轴（同步 / 异步 callback / 异步 query / query-only）与能力轴（检测 / 分割 / 分类 / 嵌入 / 新算法）**正交**——任何形态 × 任何能力的组合原则上都可行，模板不枚举组合清单：

- **模板没实现过 ≠ 模板不支持**。例如"异步接口 + 分割算法"模板里没有，但它 = 现有分割 task（`tasks/segmentation.py`）+ 检测能力的异步变体 canonical（`detection_callback` / `detection_query`），是机械组合
- 组合时**引擎层不动**：形态只改变接口层与任务层的包装，引擎没有 sync/async 之分——换形态不换引擎
- 组合拆成两部分：**机械部分**（照对应形态 canonical 抄）与**非机械决策点**（组合特有的取舍，§2.4 落位表中标 ⚠️）——只有后者需要用户拍板

### 2.2 边界：不成立的组合

少数组合**形态上不成立**——不做不是"没实现"，而是语义不成立。命中边界时直接告知用户原因与可选路径，不要硬做：

| 不成立的组合 | 原因 | 可选路径 |
|-------------|------|---------|
| 远程服务（LLM）的 sync 形态 | 远程失败是业务结果不是投递失败；长阻塞不适合 web 线程池（现 vlm/agent 均为 query-only） | 用 query-only 轮询；或在新工程内自建 sync（承担自维护成本） |
| 远程服务的 callback 形态 | 同上——callback 的"恰好一次投递"语义对"远程失败 = 业务结果"不成立 | 同 query-only |
| milvus-lite 检索的 sync 形态 | 图库 db 单进程独占，只能 worker 持有，web 进程无法打开 | 用 query-only（现 search/check） |

### 2.3 最小追问

canonical 已经覆盖的（envelope、错误阶梯、指标、registry 姿势）**不问**。只问用户没给的：

1. 变体选择：异步时 callback / query / 双变体——需求常只说"异步"，没给调用方式
2. 输入输出（业务级）：什么进、什么出——JSON schema 由对应 canonical 推导，不追问字段级细节
3. 特殊编排差异：特殊校验规则、任务组合、自定义状态码、结果 TTL——没有就照 canonical

形态与算法来源通常已在需求第一句话里（"异步""分割"），不要重复问。

### 2.4 架构提案与确认闸门

追问完成后，输出**分层落位表**提案——每层：落点 + 参照 + 是否机械：

| 层 | 落点 | 参照 | 机械？ |
|----|------|------|--------|
| 引擎 | 零改动 / 复用 / 新引擎 | `engines/yolo.py` | ✅ / ⚠️ |
| 任务 | `tasks/<name>.py`（+ 异步变体） | `tasks/detection.py`（+ `detection_callback.py`） | ✅ |
| 接口 | `apis/sync_<name>.py`（+ 异步变体） | `apis/sync_detect.py` | ✅ |
| 装配 | `app.py` 开关、preflight、warmup、健康探测 | §3 footprint 第 5-8 项 | ⚠️ 组合特有取舍 |

⚠️ 行 = 组合特有的非机械决策点，逐条摆出选项等用户拍板。**等待用户确认后才进入 §3/§4/§5 实施**——未确认不动手。确认的实质是 ⚠️ 行的取舍，其余行是 canonical 的必然推论，用户扫一眼即可。

### 2.5 示例：异步 + 分割

> 模板当前无此组合，仅演示需求分解与提案的推导过程。

需求："帮我新建一个异步接口，使用分割算法。"

1. **分解**：形态轴 = 异步（变体未给）；能力轴 = 分割（`tasks/segmentation.py` 已存在，引擎零改动）
2. **查边界**：本地推理，无命中 ✅
3. **追问**：调用方轮询还是等通知？（定 callback/query）；输出沿用 sync 的 overlay JPEG + 每实例掩码 PNG？——由此引出非机械点
4. **提案**：

| 层 | 落点 | 机械？ |
|----|------|--------|
| 引擎 | 零改动（复用 `yolo_seg` + registry 现有条目） | ✅ |
| 任务 | `tasks/segmentation_callback.py` / `_query.py`，thin wrapper 包 `run_segmentation` | ✅ 抄 `detection_callback` |
| 接口 | `apis/async_segment_*.py`，submit 时 `validate_model` code 10 同步拒绝 | ✅ 抄 `async_detect_callback` |
| 装配 | 开关：`INFERFORGE_SEG` + `INFERFORGE_ASYNC` 双门还是独立开关？ | ⚠️ 拍板 |
| 预热 | worker 侧 `preload_worker` 目前只预热 detection——异步分割进不进 worker 预热？ | ⚠️ 拍板 |
| 指标 | `task="segment"` label 复用 | ✅ |

5. **确认后**：按 §4/§5 抄 canonical + `pytest` / `check_capability.py` / 全链路脚本验收

## 3. 能力文件集（footprint）

一个能力在模板里的完整足迹。逐项核对，Agent 漏一项，`scripts/check_capability.py` 会指出：

| # | 文件 | 作用 | canonical 参照 |
|---|------|------|---------------|
| 1 | `engines/<name>.py` | 算法实现（新算法时；复用现有引擎则跳过） | `engines/yolo.py`（步骤见 [add-engine.md](add-engine.md)） |
| 2 | `models/registry.yaml` | capability + 模型条目（可多个）+ `defaults` | 见 [model-registry.md](../model-registry.md) |
| 3 | `tasks/<name>.py` | 编排：懒加载 predictor、语义校验、指标 | `tasks/detection.py` |
| 4 | `apis/schemas.py` | 请求模型（**结构**校验：形状/类型/二选一） | `PredictRequest` / `DedupRequest` |
| 5 | `apis/sync_<name>.py` | 路由：转发 task 层、try/except 阶梯、组装 envelope | `apis/sync_detect.py` |
| 6 | `app.py` | 开关函数 + 门控 import + `include_router` | `_seg_enabled` 注册块 |
| 7 | `scripts/preflight_models.py` | `CAPABILITY_SWITCH` 条目（启动时模型文件检查） | `"segment": "INFERFORGE_SEG"` |
| 8 | `tasks/warmup.py` + `apis/health.py` | `INFERFORGE_PRELOAD` 预热 + `/health/ready` 就绪探测 | `detection.preload` / `default_model_loaded` |
| 9 | `tests/test_sync_<name>.py` | 冒烟测试（FakePredictor + seam） | `tests/test_sync_detect.py` |
| 10 | `scripts/run_<name>.py` | task 层直调脚本（无 web，调试用） | `scripts/run_detection.py` |
| 11 | `scripts/test_sync_<name>.py` | API 调用示例脚本 | `scripts/test_sync_detect.py` |
| 12 | `utils/metrics.py` | `observe_phase(task="<name>")`、`mark_predictor_loaded(task=...)` | 检测的调用点 |
| 13 | `docs/` + `CHANGELOG.md` | api.md 接口小节、文档索引、changelog 条目 | — |

异步形态额外增加：`tasks/<name>_callback.py`（或 `_query.py`）+ `apis/async_<name>_*.py`（§5）；query-only 形态无 callback 变体。

## 4. 同步形态实现步骤

以新增同步能力 `X` 为例（每步带验证）：

1. **引擎**（新算法才需要）：`engines/x.py` 实现 `BasePredictor`，重型依赖（如 onnxruntime）import 写在函数体内。按 [add-engine.md](add-engine.md) §4 验证清单自查
2. **registry**：`models/registry.yaml` 加 `x` 条目 + `defaults.x`；类别表放 `classes` 字段
3. **task 层** `tasks/x.py`，照 `tasks/detection.py` 三件套：
   - `_predictors` dict + 单把锁的 `get_predictor(model=None)`（`registry.resolve` → 懒加载 → `mark_predictor_loaded`）
   - 编排函数 `run_x(image_b64, image_url, model)`：`input_to_image`（语义校验，code 1/2 的出处）→ predict → 结果组装
   - `default_model_loaded()` 供就绪探测（读不到注册模型时返回 False 而非抛异常）
4. **schemas + api 层**：请求模型进 `apis/schemas.py`（结构校验）；`apis/sync_x.py` 的路由是 plain `def`（推理阻塞，交给线程池），try/except 阶梯**顺序固定**：`ModelNotFound`(code 10) → `ValueError`(code 1) → `requests.RequestException`(code 2) → `Exception`(code 3)，最后 `response.success`
5. **装配**：`app.py` 加 `_x_enabled()` 开关函数 + 门控 import 注册块（开关关着就不 import，能力完整隔离）；`scripts/preflight_models.py` 的 `CAPABILITY_SWITCH` 加条目
6. **测试**：`tests/test_sync_x.py`——`FakePredictor` 实现 contract，`monkeypatch.setattr(tasks.x, "get_predictor", lambda model=None: FakePredictor())`，用 `app_factory(sync_x_router)` 起 TestClient。覆盖：成功路径、缺参/双参（code 1）、坏 base64（code 1）、未知模型（code 10）
7. **脚本**：`scripts/run_x.py`（task 层直调，注意文件头的 sys.path insert）+ `scripts/test_sync_x.py`（HTTP 调用）
8. **指标**：推理分阶段耗时用 `observe_phase(..., task="x")`；predictor 加载用 `mark_predictor_loaded(task="x", model=...)`
9. **预热/就绪**（可选）：`tasks/warmup.py` 挂 `x.preload`；`apis/health.py` 就绪探测加 `x.default_model_loaded()`
10. **验收**（§7 定义 done）

## 5. 异步形态要点

在 §4 的 1-4 步基础上分叉：

**callback 变体**（参照 `tasks/detection_callback.py` + `apis/async_detect_callback.py`）：

- task 用 `shared_task`（**任务模块永远不 import celery_app**，避免循环导入），`bind=True` 取 self
- submit api 在入队前调 `x.validate_model(payload.model)` ——未知模型**同步**拒绝（code 10），不让错误沉到 worker
- `.delay()` kwargs 打两个章：`request_id`（日志关联）+ `submitted_at=time.time()`（队列等待指标自动记录，墙钟时间跨进程）
- 业务错误（code 1/2/3/10）**不重试**、组失败 envelope 照发；只有 callback POST 的网络失败重试（复用 `tasks.detection_callback.post_callback`——恰好一次投递的单一事实源）

**query 变体**（参照 `tasks/detection_query.py` + `apis/async_detect_query.py`）：task 返回结果进 redis（TTL 由 `INFERFORGE_RESULT_TTL` 控制），提交回 `task_id`，轮询接口返回状态与结果。

**query-only 形态**（参照 `tasks/vlm.py` / `tasks/search.py`）：

- **只有 query 变体，没有 sync/callback**——单进程独占资源（milvus-lite 库文件）做不了 sync；远程调用失败是业务结果不是投递失败，callback 语义不成立
- worker-only 依赖（openai SDK / pymilvus）**import 写在函数体内**，web 进程和测试永远不 import
- 配置读懒加载（`get_llm_config` 模式）：缺配置 → code 3，命名缺失的变量
- 远端调用单独观测（延迟 histogram + 错误 counter，参照 `_call_remote_llm`）

**验证**：`./start_celery.sh` 起 worker + 对应 `scripts/test_async_*` 脚本走全链路。

## 6. 无参照时：契约推导路径

模板没有同形态参照 = 模板"算法无关"承诺的考试。不猜、不硬造，按三步推导：

**① 从 contract 出发定义结果**：`BasePredictor` 已有三个结果类型（Detection/Segmentation/Classification，见 [add-engine.md](add-engine.md) §2）。优先复用；确需新结果类型 = 动红区（[forking-contract.md](forking-contract.md) §2），在 fork 里可做，但要知道模板上游不会替你维护

**② 按分层公理落位**：`app -> apis -> tasks -> engines`，`utils/` 横切。新能力 = 引擎（或复用）+ task（拥有 predictor）+ api（转发+envelope），不发明新层

**③ 复用横切工具箱，用测试当契约**：envelope（`response.success/error` + 已有状态码表）、registry（多模型路由）、request_id、指标——都是现成积木。**先写 `tests/test_<name>.py` 的 FakePredictor 冒烟测试再写实现**：测试即规格，红灯驱动，跑绿即契约成立

完成后对照 §3 footprint 自查 + §7 验收。形态选择仍走 §2（需求分解与边界检查）——推导的是实现，不是形态。

## 7. 验收（done 的定义）

```bash
pytest tests/test_<name>*.py -v        # 新能力冒烟全绿
pytest tests/ -q                        # 全量无回归
python3 -m py_compile apis/*.py tasks/*.py engines/*.py utils/*.py
python3 scripts/check_capability.py     # footprint 校验通过
./start.sh                              # preflight 通过（注册模型文件在盘）
```
