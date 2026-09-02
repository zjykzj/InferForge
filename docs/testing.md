# 测试规范（Testing）

> 测试策略 + InferForge 当前实现对照。最后更新：2026-08-24

## 1. 核心认知：测试深度与业务阶段匹配

测试不是一步到位的，它跟着服务规模演进。每阶段以前一阶段为基础，不跳级：

| 阶段 | 场景 | 测试内容 |
|------|------|---------|
| **基础**（当前） | 骨架阶段、验证主链路 | 冒烟测试：请求 → 响应不断线 |
| **成长** | 算法/工具逻辑增多 | + 单元测试（边界）、集成测试（真实模型 + 真实图片） |
| **工业级** | SLO 运营 | + 端到端、压测、精度一致性、长稳 |

当前处于基础阶段，`tests/test_sync_detect.py` / `tests/test_sync_segment.py` / `tests/test_sync_classify.py` / `tests/test_async_detect_callback.py` / `tests/test_async_detect_query.py` 即本阶段交付物（§3 以 test_sync_detect.py 为例详解；分割/分类冒烟套件与其同构，另加 mask PNG 往返断言 / ImageNet 类名接线断言）。引擎纯函数（decode_seg / process_mask / preprocess / topk / 输出头识别）的单测已先行落地于 `tests/test_yolo_seg_engine.py` / `tests/test_yolo_cls_engine.py`——算法逻辑已随能力增多，单测不再等到"稳定后"。

## 2. 测试分层（金字塔）

| 层级 | 测什么 | 例子（本项目） | 时机 |
|------|--------|---------------|------|
| 单元测试 | 单个函数/模块的逻辑边界 | `nms()` 的 IoU 计算、`letterbox()` 的 padding | 算法逻辑稳定后 |
| 集成测试 | 模块之间的协作 | 真实 ONNX 模型 + 真实图片的推理结果 | 模型落地后 |
| **冒烟测试** | **主链路通不通** | **`tests/` 全部冒烟用例** | **每次提交 + CI（push/PR 自动执行）** |
| 端到端测试 | 部署形态下的完整行为 | gunicorn 起服务后 curl 真实请求 | 部署流水线 |
| 性能/精度测试 | SLO 指标 | L1 基线压测、检测精度一致性 | 部署上线前 |

原则：下层失败上层无意义——冒烟不过，别的都不用跑。

## 3. 当前阶段：冒烟测试详解

### 3.1 什么是冒烟测试

词源来自硬件：电路板第一次通电只看一件事——**冒不冒烟**。不冒烟说明基本接线没错，可以继续深入调试；信号质量、性能达标是后面的事。

软件冒烟测试继承同一思想：**用最少的一组测试验证系统主链路"通电"**——不追求边界条件、覆盖率、性能，只回答"端到端能不能跑通"。

一句话：**冒烟测试证明"服务从请求到响应没有断线"，不证明"算得对、扛得住"。**

### 3.2 覆盖范围

`test_sync_detect.py` 实际走通的链路（`→` 为真实代码）：

```
HTTP 请求 → FastAPI 路由（Pydantic 结构校验 → code=1 envelope）→ run_detection 编排
         → 真实 base64 解码（cv2）→ FakePredictor ← 唯一被替换的环节
         → 真实绘图（draw_detections）→ 真实 JPEG 编码 → 响应组装
```

除推理内核外全部走真代码——因为冒烟阶段不测模型，测的是**外壳的接线**。

### 3.3 设计要点

| 要点 | 实现 |
|------|------|
| 不依赖模型文件 | `FakePredictor` 实现 `BasePredictor` contract，`monkeypatch` 替换 `get_predictor` |
| 不联网 | URL 分支通过参数校验用例间接覆盖，不发起真实请求 |
| 毫秒级 | 6 个用例 < 0.5s，适合 CI 每次提交跑 |
| 用例直述行为 | 见下表 |

| 用例 | 验证什么 |
|------|---------|
| `test_predict_with_base64` | 主链路通：返回 code=0、绘图 base64、检测列表结构 |
| `test_predict_missing_input` | 缺参 → code=1（Pydantic 校验折叠进 envelope，HTTP 仍 200——422 永不泄漏） |
| `test_predict_both_inputs_rejected` | image+url 同时给 → code=1 |
| `test_predict_invalid_base64` | 非法图片数据 → code=1 |
| `test_response_has_request_id` | 响应头 X-Request-ID 存在且 12 位 |
| `test_request_ids_are_unique` | 两次请求 ID 不同 |

### 3.4 运行方式

```bash
pytest tests/ -v        # 全部冒烟测试
pytest tests/test_sync_detect.py::test_predict_with_base64  # 单用例

# 覆盖率（可选，信息性度量）
pip install pytest-cov
pytest tests/ -q --cov=app --cov=apis --cov=tasks --cov=engines --cov=utils
```

覆盖率（基线约 81%）**只作参考、不作门禁**：scripts/ 按约定只做 py_compile 不单测，防御性错误分支（except 兜底、懒加载单例等）刻意不追求覆盖——覆盖率是找逻辑死角的排查工具，不是目标数字。

## 4. 后续测试计划

| 新增测试 | 内容 | 时机 |
|---------|------|------|
| 单元测试 | `engines/yolo.py` 的 letterbox/decode/nms 边界：空输出、全零置信度、IoU=0/1、极端宽高比图片；分割/分类引擎的纯函数单测已先行落地（`test_yolo_seg_engine.py` / `test_yolo_cls_engine.py`） | 检测引擎单测待算法稳定后补 |
| 集成测试 | 真实 `yolov8n.onnx` + 真实图片：检测数/坐标合理性；精度与官方导出结果一致（mAP 不下降）；分割 mask 与分类 top-k 同法 | 模型落地后 |
| 回归测试 | 同一批冒烟测试在替换后的接口层实现下全数通过——验证接口层可替换 | 接口层替换时 |
| 异步任务测试 | task_id 生命周期、任务失败重试、长任务不阻塞短任务 | 已部分落地：`test_async_detect_query.py` 覆盖 task_id 生命周期（提交/处理中/完成/不存在）与 Redis 故障路径 |
| 压测 | locust 压测 + 扩展比验证 | 部署上线前 |

## 5. 编码约定

1. pytest + fixture；根目录 `conftest.py` 保证包可导入
2. 外部依赖一律可替换：预测器走 `monkeypatch` 注入，禁止测试内直接实例化真实模型
3. 测试不依赖模型文件、不联网、不依赖执行顺序
4. 冒烟测试必须毫秒级——任何让 CI 变慢的用例都归入集成测试
5. 用例命名 `test_<行为>`，直述断言内容，不写编号
