# 新增推理引擎指南（Add Engine）

> 引擎层是模板的"算法插槽"：接一种新的推理后端（ONNXRuntime 新模型 / TensorRT / Triton 等）只需实现 `BasePredictor` contract，上层零改动。本文说明 contract 逐项、参照实现、接入步骤与验证清单。零基础读者建议先读 [concepts.md](concepts.md)，分层规则见 [architecture.md](architecture.md)。最后更新：2026-08-22

## 1. 引擎层的定位

- 依赖方向：`app -> apis -> tasks -> engines`，上层只依赖 `engines/base.py` 的抽象，**从不 import 具体引擎**
- 换算法只动 `engines/`（+ 对应 task 的持有关系）——见 [architecture.md](architecture.md) §3 替换原则
- 一个引擎 = 一个 `BasePredictor` 实现；**task 层拥有预测器**（懒加载、常驻内存），api 层永远看不到它

## 2. contract 逐项说明（`engines/base.py`）

```python
@dataclass
class DetectionResult:
    boxes: np.ndarray      # (N, 4) [x1, y1, x2, y2]，原图像素坐标
    scores: np.ndarray     # (N,)，置信度
    class_ids: np.ndarray  # (N,)，整数类别 id

@dataclass
class SegmentationResult:
    boxes: np.ndarray      # (N, 4)，原图像素坐标
    scores: np.ndarray     # (N,)
    class_ids: np.ndarray  # (N,)
    masks: np.ndarray      # (N, H, W) bool，整图尺寸，每 box 一张

@dataclass
class ClassificationResult:
    scores: np.ndarray     # (K,)，top-k 概率（降序）
    class_ids: np.ndarray  # (K,)

PredictResult = DetectionResult | SegmentationResult | ClassificationResult

class BasePredictor(ABC):
    def load(self, model_path: str) -> None: ...
    def predict(self, image: np.ndarray) -> PredictResult: ...
```

| contract 项 | 约定 |
|--------|------|
| `predict` 输入 | BGR、uint8、`(H, W, 3)` 的 numpy 数组（`utils/image.py` 统一产出此格式） |
| `predict` 返回值 | 三个结果类型三选一，**按能力而定**——分割/分类就是现成的参照实现（`engines/yolo_seg.py` / `engines/yolo_cls.py`）；lifecycle（load）统一，推理语义按能力分叉 |
| 返回值坐标 | 必须映射回**原图像素空间**——letterbox/resize 的反变换是引擎自己的事，task 层拿到结果直接画图、序列化（分割的 mask 同理是整图尺寸） |
| `class_ids` | 整数数组，task 层用它索引类别名（`engines/yolo.py` 的 `COCO_CLASS_NAMES`、`engines/imagenet_classes.py` 的 `IMAGENET_CLASS_NAMES` 同理） |
| `load` | 加载权重并驻留内存；**重型依赖的 import 写在函数体内**（如 `onnxruntime`），保证测试和轻量场景不需要装模型依赖 |
| `predict` | 同步阻塞调用——推理是 CPU 密集操作，并发由接口层的线程池解决，**不要在引擎内部自起线程** |
| 构造函数 | **注册表就绪**：构造函数不带模型路径，`load(path)` 注入——多模型注册表据此按需加载（现有三个引擎均已如此；注册表格式见 [model-registry.md](model-registry.md)） |
| 预/后处理 | 必须自研（本项目不引入 ultralytics，AGPL-3.0）；参照 `engines/yolo.py` 的 letterbox / decode / NMS、`engines/yolo_seg.py` 的双输出 mask 解码自实现 |

## 3. 接入步骤（以 YOLOv8n 为参照）

1. **新建 `engines/<name>.py`**，实现 `load` + `predict` 两个方法。参照 [engines/yolo.py](../engines/yolo.py)：预处理（letterbox）→ 推理 → 后处理（decode + NMS）→ 坐标反变换
2. **模型文件放 `models/`**（git 忽略、docker 绑定挂载，不进镜像）
3. **登记进模型注册表**：在 `models/registry.yaml` 加一个条目（`capability` + `path`，可选 `classes`），请求即可用 `model` 字段选中它（见 [model-registry.md](model-registry.md)）。没有注册表文件时，单模型路径由 `INFERFORGE_MODEL_PATH` 覆盖，默认 `models/yolov8n.onnx`
4. **task 层持有**：`tasks/*.py` 的 `get_predictor(model)` 已按注册模型名懒加载并缓存 predictor——同 capability 的引擎实现切换改这里（实例化你的引擎），或新建 task 持有其他 capability 的引擎
5. **类别名与绘图**：`draw_detections(image, result, class_names=你的类别表)`——`DetectionResult` 只有类别 id，名字表属于引擎的附属资源（注册表的 `classes` 字段可选，省略用 capability 内置表）
6. **多引擎并存**：task 各持各的预测器；需要"按请求选引擎"时在 **task 层**做路由（按 `model` 字段分派到不同 predictor），api 层只透传参数、不感知

## 4. TensorRT / Triton 接入说明

| 后端 | 接入本质 | 注意点 |
|------|---------|--------|
| **TensorRT**（本地推理） | 与 onnxruntime 同构：`load()` 里建 engine/context，`predict()` 里跑 inference | 输入输出张量约定不变，contract 照旧；engine 文件同理放 `models/` |
| **Triton**（远程推理服务） | 把"引擎"变成 **gRPC/HTTP 客户端**：`load()` 检查 Triton server 就绪，`predict()` 发推理请求 | ① 耗时假设变了：网络 RTT + 远端排队，任务级超时和日志耗时口径要相应调整 ② `request_id` 建议随请求透传给 Triton，链路才不断 ③ 本机不再吃模型内存，`/health/ready` 的"已加载"语义变成"client 已建连 + server 就绪" |

两者都只需改 `engines/`（+ task），上层零改动——这就是 contract 的价值。

## 5. 验证清单（接入正确与否）

| 验证项 | 操作 | 预期 |
|--------|------|------|
| 冒烟测试 | `pytest tests/ -v` | 全绿（测试用 `FakePredictor` 注入，不需要模型、不联网——见 [testing.md](testing.md)） |
| 真实推理 | `python3 scripts/test_predict.py --image assets/bus.jpg` | `code=0`，`detections` 非空，坐标落在图片尺寸内 |
| 就绪探针 | 重启服务后先 `GET /health/ready` 再发一次推理请求 | 推理前 `503 + code=6`，懒加载完成后 `code=0` |
| 错误路径 | 把模型文件移走/改名后请求 | 加载失败走 `code=3` envelope（api 层的通用异常 fallback），服务不崩 |
| 预/后处理 | 与官方实现对比一张已知图片 | 检测数量/坐标一致（精度一致性，进入 [testing.md](testing.md) 的"成长"阶段后做） |
