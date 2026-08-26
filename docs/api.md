# 接口调用文档（API）

> 接口说明与 curl 调用指南。最后更新：2026-08-24

## 1. 当前接口：POST /predict

同步目标检测接口：输入一张图片，返回检测结果（坐标/类别/置信度）与绘图结果。

### 1.1 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `image` | string | 二选一 | base64 编码的图片（支持 `data:` URL 前缀） |
| `url` | string | 二选一 | 图片 URL（GET 下载，超时 10s，上限 20MB） |
| `model` | string | 否 | 注册的模型名（见 [model-registry.md](model-registry.md)）；缺省用 detect 缺省模型，未登记返回 code=10 |

两个参数**同时给或都不给**返回 code=1。

### 1.2 响应结构

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "image": "<base64 绘图结果 JPEG>",
    "detections": [
      {"bbox": [x1, y1, x2, y2], "class_id": 0, "class": "person", "confidence": 0.90}
    ]
  }
}
```

- `bbox`：像素坐标 `[x1, y1, x2, y2]`（左上角 + 右下角）
- `confidence`：保留 4 位小数
- 响应头 `X-Request-ID`：本次请求的 trace id，报障时提供
- 自动文档：`GET /docs`（Swagger UI 交互式调试）、`GET /openapi.json`（机器可读 contract）

业务状态码见 [status-codes.md](status-codes.md)。

### 1.3 curl 调用

```bash
# 方式一：base64 内联（小图，几百 KB 以内）
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d "{\"image\": \"$(base64 -w 0 assets/zidane.jpg)\"}" | python3 -m json.tool

# 方式二：base64 + payload 文件（大图——内联会触发命令行参数长度限制）
python3 -c "import base64,json; json.dump({'image': base64.b64encode(open('assets/bus.jpg','rb').read()).decode()}, open('/tmp/payload.json','w'))"
curl -s -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" -d @/tmp/payload.json -o result.json

# 方式三：URL 下载
curl -s -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"url": "https://ultralytics.com/images/bus.jpg"}' -o result.json

# 解析响应（打印检测列表 + 保存绘图）
python3 -c "
import base64, json
d = json.load(open('result.json'))
print(json.dumps(d['data']['detections'], indent=2, ensure_ascii=False))
open('result.jpg', 'wb').write(base64.b64decode(d['data']['image']))
"
```

### 1.4 常用 curl 技巧

```bash
curl -i ...            # 带响应头（看 X-Request-ID）
curl -o result.json ... # 响应存文件（base64 图像会刷屏）
curl -w "time_total: %{time_total}s\n" -o /dev/null ...  # 只测耗时
```

错误场景自测：

```bash
curl -d '{}' ...                                        # → code=1 缺参数
curl -d '{"image":"x","url":"http://a/b.jpg"}' ...      # → code=1 双参数
curl -d '{"image":"!!not-base64!!"}' ...                # → code=1 非法图片
curl -d '{"url":"http://localhost:9/x.jpg"}' ...        # → code=2 下载失败
curl -d '{bad json' ...                                 # → code=1 非法 JSON（Pydantic 校验折叠进 envelope，HTTP 仍 200）
```

## 2. 同步分割接口：POST /predict/segment

输入一张图片，返回实例分割结果（每实例二值 mask + 坐标/类别/置信度）与叠加绘图。需 `INFERFORGE_SEG=1` 启动且 `models/yolov8n-seg.onnx` 就位（见 README 快速开始）。

### 2.1 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `image` | string | 二选一 | base64 编码的图片（同检测接口） |
| `url` | string | 二选一 | 图片 URL（同检测接口） |
| `model` | string | 否 | 注册的模型名；缺省用该 capability 的缺省模型，未登记返回 code=10 |

### 2.2 响应结构

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "image": "<base64 叠加绘图 JPEG>",
    "segments": [
      {"bbox": [x1, y1, x2, y2], "class_id": 0, "class": "person",
       "confidence": 0.90, "mask": "<base64 PNG 二值掩码，尺寸与原图一致>"}
    ]
  }
}
```

- `mask`：整图尺寸的单通道二值掩码（PNG，白色=目标像素），每个实例一张——稠密场景下 JSON 体积随实例数线性增长，调用方按需取舍
- `bbox` / `confidence` 舍入规则、`X-Request-ID`、业务状态码语义均同 §1

### 2.3 curl 示例

```bash
# 请求方式同 §1（image base64 / url 二选一）
python3 -c "import base64,json; json.dump({'image': base64.b64encode(open('assets/bus.jpg','rb').read()).decode()}, open('/tmp/payload.json','w'))"
curl -s -X POST http://localhost:8000/predict/segment \
  -H "Content-Type: application/json" -d @/tmp/payload.json -o result_seg.json

# 解析响应（保存叠加图 + 第一张 mask）
python3 -c "
import base64, json
d = json.load(open('result_seg.json'))
print(json.dumps([{k: s[k] for k in ('class', 'confidence', 'bbox')} for s in d['data']['segments']], indent=2))
open('result_seg.jpg', 'wb').write(base64.b64decode(d['data']['image']))
if d['data']['segments']:
    open('mask0.png', 'wb').write(base64.b64decode(d['data']['segments'][0]['mask']))
"
```

自动化客户端：`python3 scripts/test_sync_segment.py --image assets/bus.jpg --save result_seg.jpg`

## 3. 同步分类接口：POST /predict/classify

输入一张图片，返回 ImageNet-1k top-5 分类结果（纯文本，无绘图）。需 `INFERFORGE_CLS=1` 启动且 `models/yolov8n-cls.onnx` 就位。

### 3.1 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `image` | string | 二选一 | base64 编码的图片（同检测接口） |
| `url` | string | 二选一 | 图片 URL（同检测接口） |
| `model` | string | 否 | 注册的模型名；缺省用该 capability 的缺省模型，未登记返回 code=10 |

### 3.2 响应结构

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "classifications": [
      {"class_id": 779, "class": "school bus", "confidence": 0.8713},
      {"class_id": 874, "class": "trolleybus", "confidence": 0.0562}
    ]
  }
}
```

- 固定返回 top-5，按置信度降序；`confidence` 为 softmax 概率，保留 4 位小数
- 类名表为 ImageNet-1k（1000 类），顺序与模型训练集一致（`engines/imagenet_classes.py`）
- 分类接口不返回任何图片数据

### 3.3 curl 示例

```bash
python3 -c "import base64,json; json.dump({'image': base64.b64encode(open('assets/bus.jpg','rb').read()).decode()}, open('/tmp/payload.json','w'))"
curl -s -X POST http://localhost:8000/predict/classify \
  -H "Content-Type: application/json" -d @/tmp/payload.json | python3 -m json.tool
```

自动化客户端：`python3 scripts/test_sync_classify.py --image assets/bus.jpg`

## 4. 异步回调接口：POST /predict/callback

提交检测任务后立即返回，检测完成时服务端把结果 POST 到调用方提供的 `callback_url`。需要 Celery + RabbitMQ + Redis，且 web 以 `INFERFORGE_ASYNC=1` 启动（见 README 快速开始）。

### 4.1 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `callback_url` | string | 是 | 结果回调地址（服务端主动 POST 结果到这里） |
| `image` | string | 二选一 | base64 图片（同同步接口） |
| `url` | string | 二选一 | 图片 URL（同同步接口） |
| `model` | string | 否 | 注册的模型名；缺省用 detect 缺省模型，未登记在提交时即返回 code=10（不会入队） |

### 4.2 响应与回调

```json
// 提交响应（立即返回）
{"code": 0, "data": {"task_id": "76898f32-c64d-..."}}

// 回调 payload（服务端 → callback_url，与 business envelope 一致）
{"code": 0, "message": "success", "data": {"image": "<base64>", "detections": [...]}}
{"code": 1, "message": "...", "data": null}    // 检测业务失败（图片非法等）
{"code": 2, "message": "...", "data": null}    // 图片下载失败
{"code": 3, "message": "...", "data": null}    // 服务内部错误
{"code": 10, "message": "...", "data": null}   // 模型未登记（web/worker 注册表漂移时）
```

语义：**回调恰好触发一次**——检测业务错误不重试，只有回调 POST 本身的网络故障才指数退避重试（最多 3 次）。

```bash
# curl 示例（回调接收端自备——可用 scripts/callback_receiver.py 起一个测试接收器）
curl -X POST http://localhost:8000/predict/callback \
  -H "Content-Type: application/json" \
  -d '{"image": "<base64>", "callback_url": "http://localhost:9000/result"}'
```

## 5. 异步轮询接口：POST /predict/query + GET /predict/query/&lt;task_id&gt;

提交检测任务后立即返回 `task_id`，worker 把 result envelope 写入 Redis，调用方**主动轮询**拉取结果。需要 Celery + RabbitMQ + Redis，且 web 以 `INFERFORGE_ASYNC=1` 启动。

### 5.1 请求参数（提交）

| 参数 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `image` | string | 二选一 | base64 图片（同同步接口） |
| `url` | string | 二选一 | 图片 URL（同同步接口） |
| `model` | string | 否 | 注册的模型名；缺省用 detect 缺省模型，未登记在提交时即返回 code=10（不会入队） |

### 5.2 提交响应

```json
// 成功（立即返回）
{"code": 0, "message": "success", "data": {"task_id": "76898f32-c64d-..."}}
// RabbitMQ 或 Redis 不可用
{"code": 3, "message": "failed to submit task", "data": null}
```

### 5.3 轮询响应（GET /predict/query/<task_id>）

| 场景 | 响应 |
|------|------|
| 任务处理中 | `{"code": 5, "message": "task is still processing", "data": null}` |
| 任务不存在（未提交 / 已过期） | `{"code": 4, "message": "task not found", "data": null}` |
| 完成（成功） | `{"code": 0, "message": "success", "data": {"image": "<base64>", "detections": [...]}}` |
| 完成（业务失败） | `{"code": 1/2/3/10, "message": "...", "data": null}`（与提交时的错误语义一致） |
| Redis 掉线 / 存储值损坏 | `{"code": 3, "message": "internal server error", "data": null}` |

### 5.4 语义

- 轮询**幂等**：result envelope 写入 Redis 后原样返回，多次轮询结果一致，无重试副作用
- 结果带 TTL（默认 3600s，`INFERFORGE_RESULT_TTL` 可调）：过期后轮询返回 code=4；code=4 同时覆盖「从未提交 / 已过期 / 结果写入失败」三种情形
- 无回调重试概念：worker 只写 Redis 不联系调用方；Redis 写入失败时任务报错（`logs/celery.log` 可见）

### 5.5 curl 示例

```bash
# 提交（payload 文件方式避免 base64 超长）
python3 -c "import base64,json; json.dump({'image': base64.b64encode(open('assets/bus.jpg','rb').read()).decode()}, open('/tmp/payload.json','w'))"
curl -s -X POST http://localhost:8000/predict/query \
  -H "Content-Type: application/json" -d @/tmp/payload.json

# 轮询（task_id 为提交响应里的值；code=5 继续轮询，0/1/2/3 为终态）
curl -s http://localhost:8000/predict/query/<task_id>
```

自动化客户端可直接用 `python3 scripts/test_async_detect_query.py --image assets/bus.jpg`（自带轮询循环）。

## 6. 健康检查接口：GET /health + GET /health/ready

供 K8s / Docker / 负载均衡等基础设施探活使用的端点，业务调用方一般无需关心。始终注册，无需环境变量开关。

### 6.1 存活检查：GET /health

进程活着即返回 200，不做任何实际工作（不加载模型、不查外部依赖）：

```json
{"code": 0, "message": "success", "data": {"status": "ok"}}
```

### 6.2 就绪检查：GET /health/ready

检查当前 worker 进程**已启用能力**的**缺省模型**是否已加载（检测恒启用；分割/分类在对应开关开启时纳入检查；多模型注册表下只探缺省模型，见 [model-registry.md](model-registry.md)）：

| 场景 | HTTP | 响应 |
|------|:---:|------|
| 已加载（预热完成） | 200 | `{"code": 0, "data": {"status": "ready"}}` |
| 未加载（冷启动） | **503** | `{"code": 6, "message": "model not loaded", "data": null}` |

注意：

- predictor 默认**懒加载**：新部署的 worker 在收到第一个 /predict 请求前，就绪检查返回 503——探针会把流量导到已就绪的 worker，冷启动期间表现为逐实例渐进就绪。`INFERFORGE_PRELOAD=1` 启动预热可消除该窗口：启动事件里加载各启用能力的缺省模型，ready 立即为 true
- 健康检查是**唯一**返回非 200 HTTP 状态码的接口（探针只读状态码）；业务接口永远返回 200，见 [status-codes.md](status-codes.md) §2 例外说明
- 多 worker 部署（默认 gunicorn 2 workers）下就绪状态**每进程独立**：各 worker 各自持有 predictor，负载均衡需逐实例探活

### 6.3 curl 示例

```bash
curl -i http://localhost:8000/health
curl -i http://localhost:8000/health/ready    # 冷启动期间返回 HTTP/1.1 503
```

## 7. 指标暴露接口：GET /metrics

Prometheus 文本格式的指标端点，**不走 `{code, message, data}` envelope**（协议端点例外，见 [status-codes.md](status-codes.md)）：

```bash
curl http://localhost:8000/metrics
```

指标清单、multiprocess 聚合与监控栈接入见 [metrics.md](metrics.md)。

## 8. 访问控制：鉴权与限流（可选，默认关闭）

设置 `INFERFORGE_API_KEY` 后，除豁免路径外所有接口要求 `X-API-Key` header：

```bash
# 服务端：带密钥启动
INFERFORGE_API_KEY=your-secret ./start.sh

# 客户端：带 header 调用（payload 同 §1）
curl -H "X-API-Key: your-secret" -H "Content-Type: application/json" \
  -d '{"image": "<base64>"}' http://localhost:8000/predict
python3 scripts/test_sync_detect.py --image assets/bus.jpg    # 脚本自动读取 INFERFORGE_API_KEY
```

- 鉴权失败：**HTTP 401 + `{"code": 7, "message": "unauthorized"}`**（协议层例外，见 [status-codes.md](status-codes.md)）
- **豁免路径**：`/health`、`/health/ready`、`/metrics`、`/docs`、`/openapi.json` 匿名可访问
- 不设置 `INFERFORGE_API_KEY` = 功能完全关闭，无任何行为差异
- 单 key 模型，无用户体系；多用户 / SSO 场景走网关层（见 [security.md](security.md)）

### 限流（固定窗口）

设置 `INFERFORGE_RATE_LIMIT=N` 后，每个调用方每分钟最多 N 个请求：

```bash
INFERFORGE_RATE_LIMIT=60 ./start.sh
```

- 计数维度：鉴权开启时按 `X-API-Key` 分桶，否则按客户端 IP
- 超限响应：**HTTP 429 + `{"code": 8}` + `Retry-After` 头**（协议层例外，见 [status-codes.md](status-codes.md)）
- 已知近似：计数在进程内存，gunicorn 多 worker 下有效配额约为 N × worker 数——单机部署可接受；严格配额接 Redis 共享计数（见 [security.md](security.md)）
- 豁免路径同鉴权：探针、文档与指标端点不限流

## 9. 参数设计规范（推理接口的通用模式）

后续新增推理接口（分类、分割、异步等）遵循同一套参数模式，保证调用方心智一致：

### 9.1 输入载体：三选一

| 参数 | 形式 | 适用场景 |
|------|------|---------|
| `image` | base64 字符串 | 中小图、内部服务互调、图片不落盘 |
| `url` | URL 字符串 | 图片已在公网/CDN，省上传流量 |
| `file`（规划） | multipart/form-data | 大图/视频帧——base64 膨胀约 33%，大文件走 multipart |

规则：同一接口最多提供两种载体（如 image + url），**至少一种、至多一种**，冲突即 code=1。

### 9.2 推理参数

可选的阈值/行为覆盖，不传用服务端默认值：

| 参数 | 类型 | 说明 |
|------|------|------|
| `model` | string | **已落地**：注册的模型名（[model-registry.md](model-registry.md)），缺省用该 capability 的缺省模型 |
| `conf_thres` | float | 置信度阈值（默认 0.25）（规划） |
| `iou_thres` | float | NMS IoU 阈值（默认 0.45）（规划） |
| `with_image` | bool | 是否返回绘图 base64（默认 true；纯取坐标的调用方省流量）（规划） |

### 9.3 异步模式

长耗时推理（大模型/Agent）不适合同步等待，参数模式变为：

```
POST /predict/query → {"code": 0, "data": {"task_id": "..."}}
GET  /predict/query/<task_id> → 查询结果（完成前返回 code=5 processing 状态）
```

已落地：见 §5 异步轮询接口（POST /predict/query + GET 轮询）。同步/异步并存时，由接口路径区分而非参数区分——调用方一眼可知行为。

## 10. VLM 异步接口：POST /predict/vlm/query

图片理解（VLM）异步接口：输入一张图片，worker 内部组装**固定服务端提示词**并**远程调用 LLM**（OpenAI 兼容 chat completions），返回文本答案。**仅 query 轮询形态**——远程调用秒级到几十秒，没有同步版本（长连接易超时且客户端重试会重复计费）；callback 推送模式以检测任务（§4）为参照，VLM/Agent 类任务按需再启用。

启用前置：

- web：`INFERFORGE_ASYNC=1 INFERFORGE_LLM=1` 启动（仅 `INFERFORGE_LLM=1` 时告警并跳过注册）
- worker：`INFERFORGE_LLM_MODEL`（必填）、`INFERFORGE_LLM_API_KEY`（必填）、`INFERFORGE_LLM_BASE_URL`（可选）、`INFERFORGE_LLM_PROMPT`（可选，覆盖默认提示词）

### 10.1 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `image` | string | 二选一 | base64 图片（同检测接口） |
| `url` | string | 二选一 | 图片 URL（同检测接口） |

提示词完全由服务端固定（默认 "Please describe this image in detail."），客户端**不传**文本参数。

### 10.2 响应与结果 envelope

```json
// 提交响应（立即返回，同检测异步）
{"code": 0, "message": "success", "data": {"task_id": "76898f32-c64d-..."}}

// 结果 envelope（轮询原样返回）
{"code": 0, "message": "success", "data": {"answer": "<文本答案>", "model": "<模型名>"}}
{"code": 1, "message": "...", "data": null}    // 图片非法（付费调用前校验）
{"code": 2, "message": "...", "data": null}    // 图片下载失败
{"code": 9, "message": "upstream LLM call failed: ...", "data": null}  // 远程 LLM 失败（SDK 重试耗尽）
{"code": 3, "message": "...", "data": null}    // 配置缺失（点名环境变量）/ 内部错误
```

### 10.3 语义

- 轮询**幂等**：result envelope 写入 Redis 后原样返回，多次轮询无副作用；结果带 TTL（默认 3600s）
- 远程调用的基础设施重试由 openai SDK 内置（连接 / 429 / 5xx，`max_retries=2`），worker 内不手写重试循环
- **付费前校验**：图片先解码验证（code 1/2 阶梯复用检测路径），通过后才发起远程调用——非法输入不产生费用
- v1 无结果缓存：重复提交同一图片会重复调用远程 LLM（缓存留待后续版本）
- worker 为 I/O 密集：`./start_celery.sh -c N` 提升并发（`worker_prefetch_multiplier` 保持 1，见 [architecture.md](architecture.md)）

### 10.4 curl 示例

```bash
# 提交（payload 文件方式避免 base64 超长）
python3 -c "import base64,json; json.dump({'image': base64.b64encode(open('assets/bus.jpg','rb').read()).decode()}, open('/tmp/payload.json','w'))"
curl -s -X POST http://localhost:8000/predict/vlm/query \
  -H "Content-Type: application/json" -d @/tmp/payload.json

# 轮询（task_id 为提交响应里的值；code=5 继续轮询，0/1/2/3/9 为终态）
curl -s http://localhost:8000/predict/vlm/query/<task_id>
```

自动化客户端：`python3 scripts/test_async_vlm_query.py --image assets/bus.jpg`（自带轮询循环）。

## 11. Agent 异步接口：POST /predict/agent/query

图片人物发型统计（Pydantic AI 编排示例）：输入一张图片，worker 内 Agent 先调用**本地检测引擎**（工具）定位每个人，再由**远程 LLM** 逐人判断是否有头发，返回结构化结果。与 VLM 一致为**仅 query 轮询形态**，没有同步版本。

启用前置：

- web：`INFERFORGE_ASYNC=1 INFERFORGE_AGENT=1` 启动（仅 `INFERFORGE_AGENT=1` 时告警并跳过注册）
- worker：`INFERFORGE_LLM_MODEL` / `INFERFORGE_LLM_API_KEY`（必填，与 VLM 共用）、`INFERFORGE_LLM_BASE_URL`（可选）、`INFERFORGE_AGENT_INSTRUCTIONS`（可选，覆盖默认指令）
- 本地模型：`models/yolov8n.onnx`（检测工具需要）

### 11.1 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `image` | string | 二选一 | base64 图片（同检测接口） |
| `url` | string | 二选一 | 图片 URL（同检测接口） |

指令与输出 schema 完全由服务端固定，客户端**不传**任何业务参数。

### 11.2 响应与结果 envelope

```json
// 提交响应（立即返回，同检测异步）
{"code": 0, "message": "success", "data": {"task_id": "76898f32-c64d-..."}}

// 结果 envelope（轮询原样返回）
{"code": 0, "message": "success", "data": {
  "total_persons": 2,
  "with_hair": 1,
  "without_hair": 1,
  "per_person": [
    {"index": 0, "bbox": [746.8, 40.92, 1144.04, 709.51], "has_hair": false},
    {"index": 1, "bbox": [119.07, 196.0, 1110.4, 710.44], "has_hair": true}
  ]
}}
{"code": 1, "message": "...", "data": null}    // 图片非法（付费调用前校验）
{"code": 2, "message": "...", "data": null}    // 图片下载失败
{"code": 9, "message": "upstream LLM call failed: ...", "data": null}  // Agent 运行失败（传输重试耗尽/输出重试耗尽）
{"code": 3, "message": "...", "data": null}    // 配置缺失（点名变量）/ 检测工具失败 / 内部错误
```

### 11.3 语义

- 轮询**幂等**：result envelope 写入 Redis 后原样返回，多次轮询无副作用
- 传输重试在 Pydantic AI 的 transport 层（429/5xx/连接，3 次，尊重 Retry-After）——语义对齐 VLM 的 SDK 重试；结构化输出验证失败由框架自动让模型修正重试
- **付费前校验**：图片先解码验证（code 1/2），通过后才构建 Agent 发起远程调用
- 检测工具失败（本地引擎异常）→ code 3，与上游 LLM 失败（code 9）语义分开
- 编排细节、schema 与泛化方法见 [agent.md](agent.md)

### 11.4 curl 示例

```bash
# 提交（payload 文件方式避免 base64 超长）
python3 -c "import base64,json; json.dump({'image': base64.b64encode(open('assets/zidane.jpg','rb').read()).decode()}, open('/tmp/payload.json','w'))"
curl -s -X POST http://localhost:8000/predict/agent/query \
  -H "Content-Type: application/json" -d @/tmp/payload.json

# 轮询（task_id 为提交响应里的值；code=5 继续轮询，0/1/2/3/9 为终态）
curl -s http://localhost:8000/predict/agent/query/<task_id>
```

## 12. 测试规范引用

- 响应格式与业务码：[status-codes.md](status-codes.md)
- 分层与异步数据流：[architecture.md](architecture.md)
- 冒烟测试（含 curl 无法覆盖的断言）：[testing.md](testing.md)
- 日志与报障（X-Request-ID）：[logging.md](logging.md)
