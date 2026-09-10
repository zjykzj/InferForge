# 修改已有服务（Modify Service）

> 在新工程中修改已存在功能的流程：先定位改动该落在哪一层，再核对绿黄红区，改实现与测试同步，最后回归验收。换算法的场景见 [add-engine.md](add-engine.md)，新增能力见 [add-capability.md](add-capability.md)。最后更新：2026-09-10

## 1. 定位：常见修改场景 → 动手层

| 我想改 | 动手层 | 风险区 | 参照 |
|--------|--------|--------|------|
| 业务编排逻辑（画图样式、结果字段、置信度阈值） | `tasks/` | 绿区 | `tasks/detection.py` |
| 请求参数 / 响应字段 | `apis/schemas.py`（**结构**校验：形状、类型、二选一）+ `apis/` 路由（组装 envelope） | 绿区 | `apis/schemas.py` |
| 业务校验规则（base64 内容、下载限制） | task 层语义校验（`utils/image.py` 的 `input_to_image`） | 绿区 | `tasks/detection.py` |
| 换推理算法 | `engines/<new>.py` + task 层的持有与路由 | 绿区 | [add-engine.md](add-engine.md) §3 |
| envelope / 中间件 / 日志格式 | `utils/` + `app.py` 装配顺序 | 黄区 | [forking-contract.md](forking-contract.md) §2 |
| `BasePredictor` 签名 / envelope 格式 / 分层依赖方向 | 红区公理 | 红区 | 先想清楚，见下 |

**绿黄红区是 [forking-contract.md](forking-contract.md) 的分区约定**：绿区随便改；黄区可改但合并上游有成本；红区是模板其余部分成立的公理（envelope、`BasePredictor`、依赖方向），动了模板的承重墙——确需调整优先向上游提 issue/PR。

## 2. 修改流程

1. **定位**：按 §1 表找到动手层；不确定时先读对应 canonical 参照与 [architecture.md](../architecture.md) 分层说明
2. **区检查**：确认改动落在哪个区。绿区直接做；黄区先读对应文档（改 envelope 读 [status-codes.md](../status-codes.md)，改指标读 [metrics.md](../metrics.md)）；红区停下重新评估
3. **改实现 + 同步改测试**：实现和测试同一次改动里完成——测试是契约，改行为就改测试。冒烟测试模仿 `tests/test_sync_detect.py` 的 seam（FakePredictor + monkeypatch）
4. **契约类改动双注册**（漏一处 CI/文档检查会指出）：
   - 新增业务状态码 → `utils/response.py` 文档串 **和** `docs/status-codes.md` 两处注册，避开 0-10 已有语义
   - 接口参数/响应变化 → 更新 `docs/api.md` 对应小节
5. **回归验收**：跑 §4 的验收命令；涉及启动路径的改动额外跑一次 `./start.sh`

## 3. 换算法专项

换算法是修改场景里最独立的一支，模板已把它单独成文：

- 步骤走 [add-engine.md](add-engine.md)：新引擎实现 `BasePredictor` → registry 登记 → task 层改持有（或按 `model` 字段路由多引擎并存）
- 前后处理必须自研（模板不引入 ultralytics，AGPL-3.0）；重型依赖 import 在函数体内
- 引擎层纯函数（letterbox/NMS/decode 等）先落单测——参照 `tests/test_yolo_seg_engine.py` / `tests/test_yolo_cls_engine.py`
- 换完跑既有冒烟测试：同一 contract 下上层零改动，`tests/test_sync_<capability>.py` 全绿即证明"只动了引擎层"

## 4. 回归验收（done 的定义）

```bash
pytest tests/test_<affected>*.py -v     # 受影响能力的冒烟测试
pytest tests/ -q                         # 全量无回归
python3 -m py_compile apis/*.py tasks/*.py engines/*.py utils/*.py scripts/*.py
python3 scripts/check_capability.py      # footprint 校验通过
python3 scripts/run_<affected>.py --image assets/bus.jpg   # 有模型时 task 层直调抽查
./start.sh                               # 涉及启动路径/registry 改动时
```

红线提醒：HTTP 永远 200 + `{code, message, data}` envelope、Pydantic 校验失败折叠为 code 1（422 永不泄漏）、状态码双注册——这三条是验收必查项，`tests/test_architecture.py` 也会替你盯着。
