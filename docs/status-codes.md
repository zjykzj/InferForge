# 业务状态码规范（Business Status Codes）

> 记录 InferForge 接口层统一响应格式的规范、使用方式与方案比较。最后更新：2026-08-22

## 1. 响应格式规范

所有接口统一返回如下 JSON 结构：

```json
{
  "code": 0,
  "message": "success",
  "data": { }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | int | 业务状态码，`0` 成功，非 `0` 失败 |
| `message` | string | 面向调用方的人类可读说明 |
| `data` | any | 成功时返回业务载荷；失败时为 `null` |

这个外壳在 API 设计里有专门的名字——**response envelope（响应信封）**：业务数据（`data`）包在固定的元信息结构（`code` / `message`）里，就像信装在信封中。客户端永远从同一个位置读状态和正文，不需要理解 HTTP 状态码或异常结构。本文档与其他文档里的「envelope」均指代这个 `{code, message, data}` 结构。

当前约定：**HTTP 状态码永远返回 200**，业务成败完全由 `code` 表达（取舍分析见 §4）。唯一例外是健康检查端点（见 §2「例外：健康检查端点」）。

## 2. 业务状态码表

| code | 含义 | 场景 |
|------|------|------|
| `0` | success | 请求被正常处理 |
| `1` | invalid request | 参数缺失/冲突、图片数据非法（如同时传 `image` 和 `url`） |
| `2` | download failure | 图片 URL 下载失败（超时、404、文件过大） |
| `3` | internal error | 服务内部异常（推理失败、未预期异常） |
| `4` | task not found | 查询任务结果不存在：从未提交、结果已过期（TTL 回收）或结果写入失败 |
| `5` | task pending | 查询任务处理中：已提交、worker 尚未写入结果 |
| `6` | service not ready | 就绪检查未通过：predictor 尚未加载（`GET /health/ready` 冷启动期间） |

扩展原则：

- 按错误类别递增分配新码；已发布过的码**不删除、不复用**（客户端可能依赖）
- 每个码的语义在 `utils/response.py` docstring 与本文档同步登记
- 预留段位：`1xxx` 请求类 / `2xxx` 外部依赖类 / `3xxx` 推理类 / `5xxx` 系统类——当前用短码，需要细分时再启用段位

### 例外：健康检查端点

`GET /health` 与 `GET /health/ready` 是基础设施探针（K8s / Docker / 负载均衡），**不适用「永远 200」约定**——探针只读 HTTP 状态码：

| 端点 | 就绪时 | 未就绪时 |
|------|--------|----------|
| `/health`（存活） | `200` + `{"code": 0, "data": {"status": "ok"}}` | 进程存活则永远就绪，无失败态 |
| `/health/ready`（就绪） | `200` + `{"code": 0, "data": {"status": "ready"}}` | `503` + `{"code": 6, "message": "model not loaded"}` |

若 `/health/ready` 永远返回 200，就绪探针就失去意义。这是本项目**唯一**使用非 200 HTTP 状态码的地方，业务接口（/predict 系列）不受影响。`utils/response.error()` 为此增加了可选参数 `http_status`（默认 200）。

## 3. 使用方式

### 3.1 服务端

统一入口在 `utils/response.py`，apis 层只做：校验输入 → 调用任务层 → 包装响应：

```python
from utils import response

# 成功
return response.success({"image": b64, "detections": [...]})

# 业务失败（HTTP 仍为 200）
return response.error("provide either 'image' or 'url'", code=1)
return response.error("failed to download image: %s" % exc, code=2)
return response.error("internal server error", code=3)
return response.error("task not found", code=4)
return response.error("task is still processing", code=5)
return response.error("model not loaded", code=6, http_status=503)  # 仅健康检查端点
```

参数结构校验（Pydantic 模型）失败时同样走 code=1：FastAPI 抛出的 `RequestValidationError` 由 `utils.response.validation_error_handler` 统一折叠为 `200 + code=1` envelope——框架默认的 422 永不泄漏。

分层约束：**任务层 / 算法层不接触响应格式**——它们抛异常或返回数据，由 apis 层统一捕获并包装，保持各层可替换。

### 3.2 客户端

```python
resp = requests.post(url, json=payload)
body = resp.json()
if body["code"] != 0:
    handle_error(body["code"], body["message"])
else:
    use(body["data"])
```

客户端只需判断 `code`，不依赖 HTTP 状态码。

### 3.3 新增业务码流程

1. 在 `utils/response.py` docstring 与本文档 §2 登记新码语义
2. apis 层调用 `response.error(msg, code=N)`
3. 在对应测试文件（`tests/test_predict.py` / `tests/test_predict_query.py`）补充对应断言

## 4. 方案比较：永远 200 vs HTTP 状态码

| 维度 | 永远 200 + 业务码 | HTTP 状态码 + 业务码 |
|------|------------------|---------------------|
| 代表生态 | 阿里/腾讯/字节系 API 主流 | Google / GitHub / Stripe / OpenAI 等国际 API |
| 理念 | HTTP 状态只管"传输"，业务成败看 `code` | HTTP 状态本身表达语义，`code` 做业务细分 |
| 客户端复杂度 | 单一路径处理 | 需同时处理状态码与 body |
| 网关/防火墙兼容 | 非 200 不会被拦截或改写 | 部分网关会改写/拦截非 200 |
| 监控告警（5xx 率） | ❌ 失效，错误全部藏在 body | ✅ 自动生效 |
| 缓存/CDN 语义 | 需额外配置避免错误响应被缓存 | 状态码天然区分 |
| 重试语义 | 客户端需解析 body 才知可否重试 | 客户端库基于状态码自动处理 |

### 本项目选择

采用「永远 200 + 业务码」：

1. 服务面向自有客户端，无第三方 REST 消费者
2. 与国内主流 API 生态惯例一致
3. 统一格式降低客户端与网关的处理复杂度

已知取舍：`code=3`（内部错误）暂以 200 返回，会丢失 5xx 监控告警能力。当监控体系（Prometheus 等）落地时，可评估将 `code=3` 改为 HTTP 500 的折中方案（业务错误保持 200）。健康检查端点已按探针语义使用 503（见 §2 例外说明），业务接口仍保持永远 200。
