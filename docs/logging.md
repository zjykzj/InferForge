# 日志模块规范（Logging）

> 生产环境的日志实践指南 + InferForge 当前实现对照。最后更新：2026-08-15

## 1. 核心认知：日志能力与业务阶段匹配

日志模块不是一步到位的，它跟着服务规模演进。每阶段以前一阶段为基础，不跳级：

| 阶段 | 场景 | 日志能力 |
|------|------|---------|
| **基础**（当前） | 单机、自用、排障靠 grep | 分级 + 全链路埋点 + trace_id + 轮转保留 + JSON 文件 |
| **成长** | 多副本、日志量上来、多人排障 | 集中采集、字段检索、ERROR 告警、动态级别 |
| **工业级** | 平台化、SLO 运营 | 三支柱（logs/metrics/traces）、采样、成本治理 |

基础版已实现（§3）；成长/工业级是路线图（§4/§5），到对应阶段再落地。

## 2. 分级纪律

| 级别 | 用途 | 原则 |
|------|------|------|
| DEBUG | 排障细节、中间状态 | 只进文件不进生产 console |
| INFO | 关键业务节点：请求开始/结束、任务完成、耗时 | 常规运营 |
| WARNING | 可恢复异常：重试、降级、参数拒绝 | 不告警但留痕 |
| ERROR | 需要人关注的失败 | **每条 ERROR 都应可行动**——看到它就该知道要做什么 |
| CRITICAL | 服务不可用 | 必须告警 |

## 3. 基础版清单（当前已实现）

| 能力 | 实现 |
|------|------|
| 双通道 | console 文本（INFO+，给人看）/ 文件 JSON（DEBUG+，给机器采集） |
| 统一格式 | `时间 \| 级别 \| 模块名 \| request_id \| 消息` |
| 全链路埋点 | apis（请求/成败）→ tasks（总耗时、检测数）→ engines（预处理/推理/后处理分段耗时）→ utils（解码耗时） |
| trace_id | 请求入口生成 12 位 hex，贯穿该请求所有日志行；响应头 `X-Request-ID` 回传给调用方 |
| 轮转与保留 | 按天轮转（midnight），保留 7 天 |
| 异常带堆栈 | `logger.exception()` → 文件 JSON 的 `exc_info` 字段 |
| 第三方降噪 | onnxruntime / urllib3 / requests → WARNING |

实现说明：

- 文件日志为 JSON 的原因：文本只能 grep，JSON 才能被 ELK/Loki 等采集系统按字段（request_id/level/logger）检索聚合
- console 保持文本的原因：开发者 `tail` 时人眼可读
- `request_id` 12 位 hex（48 bit）：服务规模下碰撞可忽略，日志行又足够短

## 4. 成长版（多副本 / 日志量上来后）

- **集中采集**：文件 JSON → Filebeat/Fluentd → ELK/Loki；或改为 stdout 输出交给容器平台采集（二选一，不并存）
- **按字段检索**：用 request_id 过滤单个请求链路；按 level/logger 聚合错误分布
- **告警**：ERROR 率异常告警（IM/电话）——注意最终告警应基于 metrics，日志用于排障（见 §6）
- **动态调级别**：线上排障时临时打开某模块 DEBUG，不重启
- **异步写入**：`QueueHandler`，日志 IO 不阻塞请求热路径

## 5. 工业级（平台化 / SLO 运营）

- **三支柱**：logs + Prometheus 指标 + OpenTelemetry 链路，三者通过 trace_id 关联——"发生了什么 / 多频繁 / 在哪一层"各司其职
- **采样**：DEBUG 级按比例采样，控制日志成本
- **分级存储**：热数据快速检索，冷数据归档压缩

## 6. 使用规范（本项目编码约定）

1. **模块级 logger**：`logger = logging.getLogger(__name__)`，禁止在函数内现取
2. **级别选择**：DEBUG 中间状态 / INFO 请求与任务节点 / WARNING 可恢复异常 / ERROR 需要人处理
3. **每条 ERROR 可行动**：写清楚"什么失败了、什么原因、下一步"——`"inference failed"` 不合格，`"predict failed (internal)"` + 堆栈合格
4. **异常统一 `logger.exception(...)`**：自动带堆栈
5. **不落敏感信息**：图片数据、token 等一律不进日志
6. **分层纪律**：只有 apis 层捕获异常并包装响应；tasks/engines 只记录与抛出，不接触响应格式

## 7. 与响应格式的配合

- 客户端报障时携带响应头 `X-Request-ID` → 服务端用该 ID 过滤 `logs/app.log` 得到该请求完整链路
- 日志级别与业务状态码对应：code=1/2（业务错误）→ WARNING；code=3（内部错误）→ ERROR（见 [status-codes.md](status-codes.md)）
