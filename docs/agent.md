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
        │      │    └─ _detect_persons(deps)：tasks.detection 的本地预测器
        │      │        过滤 person 类 → 每人 index + bbox（DetectedPersons）
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
- 启用：`INFERFORGE_ASYNC=1 INFERFORGE_AGENT=1` 启动 web；worker 侧配置 `INFERFORGE_LLM_MODEL` / `INFERFORGE_LLM_API_KEY`（必填）+ `INFERFORGE_LLM_BASE_URL`（可选），与 VLM 共用
- 指令：服务端固定（`INFERFORGE_AGENT_INSTRUCTIONS` 可覆盖），客户端只传图片
- 业务码：图片校验 1/2、上游失败 9、内部 3——零新增

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
| 工具 | 改/换 `_detect_persons`（检测引擎、类别过滤、返回字段） | 过滤 person 类不变；复杂场景可换分类/分割引擎 |

工具约定（对应 [add-engine.md](add-engine.md) 之于引擎层）：

- 工具函数放 tasks 层（Agent 是编排不是内核）；重计算走本地引擎（`get_predictor`），轻逻辑可直接在工具内完成
- 工具返回 Pydantic 模型（自动序列化给模型），字段带 `Field(description=...)`——描述直接影响模型调用正确率
- 通过 `deps` 注入工具需要的上下文（本示例是解码后的图像），不要把大对象塞进指令文本
- 工具抛异常会被包装成 `ToolFailed` → code 3：检测引擎失败与上游 LLM 失败（code 9）语义分开

## 4. 与 VLM 的关系

| | VLM 任务（tasks/vlm.py） | Agent 任务（tasks/agent.py） |
|---|---|---|
| 输入 | 仅图片 | 仅图片 |
| 模型调用 | openai SDK 手写 chat completions | Pydantic AI Agent（OpenAIChatModel） |
| 输出 | 自由文本 | 结构化 schema（Pydantic 校验） |
| 编排 | 单次调用 | 工具调用 + 结构化输出 |
| 配置/错误码/指标 | 共享 `INFERFORGE_LLM_*`、code 1/2/9/3、`inferforge_vlm_remote_*` 指标 |

两者同构且可并存：`INFERFORGE_LLM=1` 开 VLM，`INFERFORGE_AGENT=1` 开 Agent，开关独立。
