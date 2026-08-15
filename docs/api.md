# 接口调用文档（API）

> 接口说明与 curl 调用指南。最后更新：2026-08-15

## 1. 当前接口：POST /predict

同步目标检测接口：输入一张图片，返回检测结果（坐标/类别/置信度）与绘图结果。

### 1.1 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `image` | string | 二选一 | base64 编码的图片（支持 `data:` URL 前缀） |
| `url` | string | 二选一 | 图片 URL（GET 下载，超时 10s，上限 20MB） |

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
```

## 2. 参数设计规范（推理接口的通用模式）

后续新增推理接口（分类、分割、异步等）遵循同一套参数模式，保证调用方心智一致：

### 2.1 输入载体：三选一

| 参数 | 形式 | 适用场景 |
|------|------|---------|
| `image` | base64 字符串 | 中小图、内部服务互调、图片不落盘 |
| `url` | URL 字符串 | 图片已在公网/CDN，省上传流量 |
| `file`（规划） | multipart/form-data | 大图/视频帧——base64 膨胀约 33%，大文件走 multipart |

规则：同一接口最多提供两种载体（如 image + url），**至少一种、至多一种**，冲突即 code=1。

### 2.2 推理参数（规划）

可选的阈值/行为覆盖，不传用服务端默认值：

| 参数 | 类型 | 说明 |
|------|------|------|
| `conf_thres` | float | 置信度阈值（默认 0.25） |
| `iou_thres` | float | NMS IoU 阈值（默认 0.45） |
| `with_image` | bool | 是否返回绘图 base64（默认 true；纯取坐标的调用方省流量） |

### 2.3 异步模式（规划）

长耗时推理（大模型/Agent）不适合同步等待，参数模式变为：

```
POST /predict（异步）→ {"code": 0, "data": {"task_id": "..."}}
GET  /result/<task_id> → 查询结果（完成前返回 processing 状态）
```

同步/异步并存时，由接口路径区分而非参数区分——调用方一眼可知行为。

## 3. 测试规范引用

- 响应格式与业务码：[status-codes.md](status-codes.md)
- 冒烟测试（含 curl 无法覆盖的断言）：[testing.md](testing.md)
- 日志与报障（X-Request-ID）：[logging.md](logging.md)
