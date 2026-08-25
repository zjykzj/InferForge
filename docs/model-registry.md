# 多模型注册表（Model Registry）

> 记录模型注册表的格式、请求级路由语义、缺省模型推导与向后兼容行为。最后更新：2026-08-25

## 1. 解决的问题

默认形态下，每个 capability 只服务一个模型：detect / segment / classify 各有一个模型路径（`INFERFORGE_[SEG_|CLS_]MODEL_PATH`），想换模型只能改环境变量并重启。注册表把「服务哪些模型」变成一份声明式配置，请求可以用 `model` 字段选择模型；不带 `model` 时走该 capability 的缺省模型，行为与注册表引入之前完全一致。

## 2. 配置文件

文件位置：`models/registry.yaml`（不提交，参考 `models/registry.example.yaml`；可用 `INFERFORGE_REGISTRY_PATH` 覆盖路径）。启动时由 `start.sh` 的 preflight（`scripts/preflight_models.py`）解析校验，进程内缓存，修改后需重启生效（不支持热重载）。

```yaml
defaults:                      # 每个 capability 的缺省模型；可整体省略
  detect: yolov8n
  segment: yolov8n-seg
  classify: yolov8n-cls

models:
  yolov8n:
    capability: detect
    path: models/yolov8n.onnx
  yolov8n-seg:
    capability: segment
    path: models/yolov8n-seg.onnx
  yolov8n-cls:
    capability: classify
    path: models/yolov8n-cls.onnx

  # 自定义模型：类别数不是 80/1000 时用 classes 指向类别名文件
  defect-det:
    capability: detect
    path: models/defect.onnx
    classes: models/defect_classes.txt
```

字段说明：

| 字段 | 必填 | 说明 |
|------|------|------|
| `models.<name>.capability` | 是 | `detect` / `segment` / `classify`；决定该模型能服务哪些端点 |
| `models.<name>.path` | 是 | ONNX 权重路径，相对于项目根目录（容器内外一致） |
| `models.<name>.classes` | 否 | 类别名文件路径（每行一个类名）；省略则用 capability 的内置表：detect/segment → COCO-80，classify → ImageNet-1k |
| `defaults` | 否 | capability → 模型名的缺省映射；见 §4 推导规则 |

未知顶层键（如把 `defaults` 拼成 `default`）会直接报错——配置笔误应当响亮失败，而不是被静默忽略。

## 3. 请求路由

所有 predict 接口接受可选 `model` 字段（同步 3 个 + 异步 detect 2 个）：

```
POST /predict             {"image": ..., "model": "defect-det"}
POST /predict/segment     {"url": ..., "model": "yolov8n-seg"}
POST /predict/classify    {"image": ..., "model": "yolov8n-cls"}
POST /predict/query       {"image": ..., "model": "defect-det"}
POST /predict/callback    {"image": ..., "model": "defect-det", "callback_url": ...}
```

- 缺省模型：不带 `model` 字段
- 模型不存在 / 未登记 → `code=10`（异步接口在**提交时**即拒绝，不会等到轮询才发现）
- capability 不匹配（拿 detect 模型调 `/predict/classify`）→ `code=10`
- 每个进程内，按模型名缓存已加载的 predictor（懒加载、常驻，无淘汰；模板场景模型数少，全部常驻是预期行为）

路由在 **task 层**完成（`tasks/*.py` 各自持有按模型名索引的 predictor 缓存）；api 层只透传 `model` 字段，不感知 predictor（与 [add-engine.md](add-engine.md) 的约定一致）。

vlm / agent 接口不接注册表：它们调用远程 LLM，没有本地模型。

## 4. 缺省模型推导

- `defaults` 声明了该 capability → 用之
- 未声明但该 capability 只注册了 1 个模型 → 自动成为缺省
- 注册了多个又未声明 → **解析期报错**（缺省是谁绝不能取决于 YAML 字典顺序）

## 5. 与 capability 开关的关系

注册表与 `INFERFORGE_SEG` / `INFERFORGE_CLS` 开关**并存、职责分离**：

- 开关决定「哪些 HTTP 路由存在」（`app.py` 注册路由、`/health/ready` 探测范围）
- 注册表决定「请求路由到哪个模型」

两者正交：开关开着但注册表里没有该 capability 的模型 → preflight 放行，请求时 `code=10`；开关关着但注册表里有模型 → 路由不存在（404），模型不会白加载。`/health/ready` 只探测各启用 capability 的**缺省**模型——要求全部注册模型都加载会让服务永远 not-ready（冷门模型在首次请求时才预热）。

## 6. 向后兼容

**没有 `models/registry.yaml` 的部署行为与注册表引入前完全一致**：进程从 `INFERFORGE_MODEL_PATH` / `INFERFORGE_SEG_MODEL_PATH` / `INFERFORGE_CLS_MODEL_PATH`（默认值与历史一致）合成一份单模型注册表。

配置源优先级：

1. `models/registry.yaml` 存在 → 它是唯一事实来源；三个 path 环境变量被忽略（同时设置会打一条 warning 日志）
2. 文件不存在且 `INFERFORGE_REGISTRY_PATH` 未被显式设置 → env 回退
3. `INFERFORGE_REGISTRY_PATH` 显式指定但文件不存在 → **启动失败**（显式配置写错必须响亮失败，而不是静默回退）

## 7. 指标

`inferforge_predictor_loaded{task, model}` 已带 `model` 标签，可观察每个模型的加载状态。已知限制：`inferforge_predict_phase_seconds` 暂不带 `model` 标签——phase 耗时从引擎内部上报，引擎不知道自己的注册名（见 [metrics.md](metrics.md) 已知限制）。

## 8. 运维

- `start.sh` preflight：按启用 capability 枚举注册表中**全部**模型并检查文件存在（任一被路由到的模型文件缺失都会启动失败），顺带解析 YAML
- 启动预热：`INFERFORGE_PRELOAD=1` 让 web / worker 各自在启动时加载所服务能力的**缺省模型**（只预热缺省，冷门模型保持懒加载）；best-effort——单个模型加载失败只记日志，该能力维持 not-ready（readiness 是真相来源）
- Docker：`models/` 已 bind-mount，把 `registry.yaml` 放进 `models/` 即可，镜像无需重建
- 类别表与权重不匹配（类别数不同）：越界 class id 降级为 `class_N` 标签并打 warning，不会让整个请求失败——但这是配置错误，应尽快修正
