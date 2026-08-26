# Agent 编排指南（Agent）

> Pydantic AI 接入示例：检测引擎 + LLM Agent 的编排模式、泛化方法与工具约定。零基础读者建议先读 [concepts.md](concepts.md) 与 [add-engine.md](add-engine.md)。最后更新：2026-08-24

## 1. 示例功能：图片人物发型统计

输入一张图片，返回图中人数以及**有头发 / 无头发**各几人（示例图 `assets/zidane.jpg`：2 人，齐达内光头 + 另一名球员有头发，期望 1:1）。

**为什么这个例子成立**：检测引擎（YOLO）只能数出 person（类别里没有「头发」属性），LLM 单独看全图在远距离/小目标/遮挡场景容易漏数——组合让检测负责**定位隔离个体**、LLM 负责**逐人语义判断**，各展所长。这是「CV 内核 + LLM 编排」的最小可验证形态。

### 1.1 流程

```
图片 → tasks/agent.py run_hair_count
        ├─ 1. utils.image 解码校验（code 1/2 阶梯，付费前）
        ├─ 2. _build_agent()：OpenAIChatModel + OpenAIProvider（复用 INFERFORGE_LLM_* 配置）
        │      + 传输层重试 transport（429/5xx/连接，3 次，Retry-After 感知）
        ├─ 3. agent.run_sync([指令, BinaryContent(jpeg)], deps=解码后的图)
        │      ├─ LLM 调用工具 detect_persons
        │      │    └─ _detect_persons(deps, model)：tasks.detection 的本地预测器
        │      │        按 INFERFORGE_AGENT_TARGET_CLASS（默认 person）过滤，类名表
        │      │        来自所选注册模型（classes 文件可覆盖）→ 每人 index + bbox
        │      └─ LLM 依据全图 + 每人 bbox 逐人判断 has_hair
        └─ 4. result.output（HairCountResult，Pydantic 校验）→ model_dump() 返回 dict
```

结果 schema（`tasks/agent.py`）：

```python
class PersonHair(BaseModel):
    index: int          # detect_persons 工具给出的人员序号（0 起，稳定）
    bbox: list[float]   # [x1, y1, x2, y2] 原图像素坐标
    has_hair: bool

class HairCountResult(BaseModel):
    total_persons: int
    with_hair: int
    without_hair: int
    per_person: list[PersonHair]
```

### 1.2 接口与启用

- 接口：`POST /predict/agent/query` + `GET /predict/agent/query/{task_id}`——与检测/VLM 异步轮询完全同构（详见 [api.md](api.md)）；**query-only**（callback 推送以检测任务为参照，LLM/Agent 类任务的调用方是主动业务系统，query 是主路）
- 检测模型：请求 `model` 字段（可选）指定检测工具使用的注册模型（缺省 detect 缺省模型；未登记提交时 code 10，worker 侧复检防注册表漂移）
- 启用：`INFERFORGE_ASYNC=1 INFERFORGE_AGENT=1` 启动 web；worker 侧配置 `INFERFORGE_LLM_MODEL` / `INFERFORGE_LLM_API_KEY`（必填）+ `INFERFORGE_LLM_BASE_URL`（可选），与 VLM 共用
- 检测工具目标类：`INFERFORGE_AGENT_TARGET_CLASS`（默认 `person`；须在所选检测模型类名表内——注册表 `classes` 文件可覆盖内置表——否则 code 3 点名报错）；指令服务端固定（`INFERFORGE_AGENT_INSTRUCTIONS` 可覆盖），客户端只传图片
- 业务码：图片校验 1/2、上游失败 9、模型未登记 10、内部 3

### 1.3 为什么用 Pydantic AI

手写 openai SDK 能做到「调模型 + 解析 JSON」，但做不到这些开箱即用的部分：

| 能力 | 手写时的成本 | Pydantic AI |
|------|------------|-------------|
| 结构化输出 | 手写 JSON prompt + 解析 + 容错 | `output_type=HairCountResult`，Pydantic 校验，验证失败自动让模型修正重试 |
| 工具调用 | 手写 function-calling 协议 | `@agent.tool` 装饰器，返回 Pydantic 模型自动序列化 |
| 依赖注入 | 自行管理上下文 | `deps` + `RunContext`（本示例把解码后的图注入工具） |
| 用量/成本 | 手算 token | `result.usage` |

## 2. Pydantic AI V2 用法要点（版本陷阱）

本项目钉板 `pydantic-ai-slim[openai,retries]>=2.33,<3.0`（requirements-async.txt）。**V2 与网上大量 V1 教程的命名不同**：

| V1（旧教程） | V2（本项目使用） |
|-------------|----------------|
| `result_type=` | `output_type=` |
| `system_prompt=` | `instructions=` |
| `ImagePart` | `BinaryContent(data=bytes, media_type=...)` / `ImageUrl(url=...)` |
| `OpenAIModel` | `OpenAIChatModel`（chat completions；OpenAI 兼容端点用这个） |
| 模型字符串 `'openai:xxx'` | 显式 `OpenAIChatModel(model_name, provider=OpenAIProvider(...))` |

- **传输层重试不是内置的**：V2 无默认 HTTP 重试——`_build_agent()` 配置 `AsyncHTTPX2TenacityTransport`（429/5xx/连接重试 3 次、尊重 Retry-After），语义对齐 VLM 任务的 SDK `max_retries=2`
- **client 生命周期**：`run_sync` 每次自建事件循环（asyncio.run），因此 httpx2 client **不能跨任务复用**——每次任务新建 agent/client（celery worker 子进程无事件循环，run_sync 安全）
- **异常映射**：`AgentRunError`（含 ModelHTTPError/UsageLimitExceeded/UnexpectedModelBehavior）→ code 9；`ToolFailed`（工具=检测引擎失败）→ code 3
- 依赖纪律与 VLM 一致：pydantic-ai 只进 requirements-async.txt，全部在函数体内惰性导入——web 进程与测试在未安装时照常工作（缺 SDK 时返回点名变量的 code 3，同 openai 规则）

## 3. 泛化指南：换成你自己的属性任务

这个示例是**模板**：换一个业务问题只动 `tasks/agent.py` 的三个点，其余层零改动：

| 改什么 | 怎么做 | 示例（换成「戴眼镜人数」） |
|--------|--------|---------------------------|
| 输出 schema | 改 `HairCountResult`/`PersonHair` 模型 | `has_hair: bool` → `has_glasses: bool` |
| 指令 | 改 `DEFAULT_AGENT_INSTRUCTIONS`（或 `INFERFORGE_AGENT_INSTRUCTIONS`） | 「judge whether they wear glasses」 |
| 工具 | 改/换 `_detect_persons`（检测引擎、返回字段） | 目标类改 `INFERFORGE_AGENT_TARGET_CLASS` 即可（类名表来自注册模型，`classes` 文件可覆盖）；复杂场景可换分类/分割引擎 |

工具约定（对应 [add-engine.md](add-engine.md) 之于引擎层）：

- 工具函数放 tasks 层（Agent 是编排不是内核）；重计算走本地引擎（`get_predictor`），轻逻辑可直接在工具内完成
- 工具返回 Pydantic 模型（自动序列化给模型），字段带 `Field(description=...)`——描述直接影响模型调用正确率
- 通过 `deps` 注入工具需要的上下文（本示例是解码后的图像），不要把大对象塞进指令文本
- 工具抛异常会被包装成 `ToolFailed` → code 3：检测引擎失败与上游 LLM 失败（code 9）语义分开

## 4. 编排形态的选择：workflow / 单 Agent / 多 Agent

三种形态是一个谱系：灵活性递增、成本递增、确定性递减。本节回答三个问题：三者什么关系、是否互相替代、各自何时用。

### 4.1 三种形态

| 形态 | 步骤由谁决定 | 确定性 | LLM 成本 | 项目现有形态 |
|---|---|---|---|---|
| 固定 workflow | 代码 | 最高 | 零或单次调用 | `/predict` 检测链路、VLM 任务 |
| 单 ReAct agent | LLM 每步决策 | 中 | 每步一次调用 | hair-count（本示例） |
| 多 agent | LLM + 职责拆分 | 中 | 再加编排开销 | — |

注意 workflow 不等于「无 LLM」：VLM 任务就是 workflow + 单次模型调用——区别在于**没有循环、没有由 LLM 决定的工具调用**。

### 4.2 替代关系

- **能力上 workflow ⊂ agent**：固定 workflow 是「每一步都确定」的 agent 特例，ReAct 循环（think → act → observe → repeat）是 `run()` 内置的，单 agent 能走完任何固定流程。但**能替代 ≠ 该替代**：LLM 每步决策的代价（钱 / 延迟 / 不确定性）只在「步骤需要运行时决定」时才划算，步骤一旦可预知就该退化回 workflow
- **反向不成立**：步骤取决于中间结果的任务（下一步要看了上一步结果才知道）无法预先编码成 workflow
- **单/多 agent 之间也不是替代**：多 agent 是单 agent 的工程拆分（上下文隔离 / 并行 / 模型分层），能力上没有新增——多步 ≠ 多 Agent，循环本就不需要多个实例接力；不出现拆分信号（§4.5）时单 agent 就是终态
- **演进单向**：先 workflow → 出现不确定步骤才 agent 化 → 出现拆分信号才多 agent 化。把确定步骤塞回给 LLM 属于过度工程

### 4.3 选择顺序

1. 步骤能否预先确定？能 → 固定 workflow；不能 → ReAct agent
2. 用 agent 时是否出现拆分信号（§4.5 表）？否 → 单 agent；是 → 多 agent

### 4.4 各自举例（同一业务线：图片人物属性审核）

**例 1 固定 workflow——步骤完全确定，零 LLM 决策**

需求「数图中有几个人」：`POST /predict` 直接检测引擎输出，解码 → 推理 → 后处理每次都一样，没有任何语义决策点。此时上 agent 只会每步白付 LLM 调用、还得靠指令祈祷模型记得调工具——更贵、更慢、更不确定。

**例 2 单 ReAct agent——存在语义决策点**

需求「数有头发 / 无头发各几人」：hair-count，`detect_persons` 工具定位、LLM 逐人判断。注意它已是 **hybrid**：指令钉死「先调工具」（把已知步骤 workflow 化），只有逐人判断交给循环。原则——**能固定的步骤固定（代码或指令），只留语义决策点给 agent**。

**例 3 多 agent——出现拆分信号**

- 并行（信号 1）：「一张图同时数头发 / 口罩 / 眼镜」——三个判断互相独立，单 agent 串行共享上下文互相干扰、延迟 t1+t2+t3；拆三个 agent 并行，延迟 = max、上下文隔离。注意 worker 内 `run_sync` 各自 spin 独立事件循环（见 §2），并行需要同一事件循环内的 `agent.run()` + `asyncio.gather`
- 上下文隔离（信号 2）：「视频 500 帧统计安全帽」——逐帧检测框全塞进 message_history 会撑爆上下文、稀释注意力；拆 per-frame workers，只回传 `{frame_id, count}` 摘要，orchestrator 只见汇总表
- 其余信号（工具集分离 / 模型分层 / 质检）见 §4.5 表

### 4.5 拆多 Agent 的触发信号

默认姿势：**能单 Agent + 多工具解决就单 Agent**。拆多 Agent 只在出现下列信号之一时成立：

| 触发信号 | 形态 | 具体场景 |
|---|---|---|
| 多个独立结论可并行出 | 并行 workers | 一张图同时数头发 / 数口罩 / 数眼镜：并行后延迟 = max 而非相加，各 Agent 上下文隔离 |
| 中间数据太大污染上下文 | per-unit workers + 摘要回传 | 视频逐帧 / 长文档分析：worker 只回传摘要，orchestrator 只见汇总表 |
| 不同子任务需要不同工具集 | orchestrator + workers | 复合单据任务（定位 + OCR + 查库）：单 Agent 挂三套工具 prompt 臃肿且易选错工具；拆成各自只懂一种工具的 worker，orchestrator 拆解并汇总 |
| 简单场景占绝大多数 | 便宜模型粗筛 + 强模型精判 | 大规模属性标注：便宜模型先对所有 bbox 粗筛，仅低置信度框升级强模型——分级漏斗，不是协作 |
| 输出有对错、需要质检 | 生成 + 评审（reviewer） | 计数类任务客观可验：评审 Agent 换模型/换视角独立复检，不合格带反馈打回重跑 |

反例：「任务步数多」「感觉更智能」不构成拆分的理由——循环本就内置多步，拆分会额外付出 LLM 调用次数、延迟与编排代码。当前 hair-count 示例满足单 Agent 形态的全部条件（单一工具、单一结论、上下文小），不该拆；出现上表信号时再拆。

## 5. 与 VLM 的关系

| | VLM 任务（tasks/vlm.py） | Agent 任务（tasks/agent.py） |
|---|---|---|
| 输入 | 仅图片 | 仅图片 |
| 模型调用 | openai SDK 手写 chat completions | Pydantic AI Agent（OpenAIChatModel） |
| 输出 | 自由文本 | 结构化 schema（Pydantic 校验） |
| 编排 | 单次调用 | 工具调用 + 结构化输出 |
| 配置/错误码/指标 | 共享 `INFERFORGE_LLM_*`、code 1/2/9/3、`inferforge_vlm_remote_*` 指标 |

两者同构且可并存：`INFERFORGE_LLM=1` 开 VLM，`INFERFORGE_AGENT=1` 开 Agent，开关独立。
