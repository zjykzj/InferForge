# 安全边界说明（Security）

> 当前实现的安全边界如实记录：已知风险点、已有防护与部署建议。最后更新：2026-09-05

## 1. 已知风险点

| 风险 | 说明 | 现状 |
|------|------|------|
| SSRF（`url` 参数） | 服务端会下载任意 URL——可被用来探测内网服务（如 `http://localhost` 管理端口、私网地址） | 无防护（风险背景与业界规范见 §2） |
| SSRF（`callback_url` 参数） | worker 会向任意 callback_url 发起 POST——同样的内网探测面 | 无防护（见 §2） |
| 轮询接口 | 持有 task_id 即可读取该任务结果；task_id 为随机 UUID，不可猜测，风险低 | 无防护 |
| 内存消耗（`image` 参数） | base64 解码前无大小上限——超大 base64 会耗尽内存 | ✅ 部分防护：Content-Length 20MB 守卫（`app.py` 中间件，超限返回 code=1 envelope；chunked 无 Content-Length 的请求可绕过） |
| 图片下载 | 已有 20MB 上限 + 10s 超时 | ✅ 已防护 |
| 认证 | 接口无认证——任何可达服务的人都可调用 | ✅ 已防护：API-key 中间件（设置 `INFERFORGE_API_KEY` 后启用，401 + code=7；探针/文档/指标端点豁免） |
| 限流 | 无速率限制——恶意或失控的调用方可持续打满推理资源 | ✅ 已防护：固定窗口限流（设置 `INFERFORGE_RATE_LIMIT` 后启用，429 + code=8 + Retry-After；计数在进程内存，多 worker 下为近似值——严格限流需共享存储如 Redis） |
| `/metrics` 暴露 | 指标不含业务数据，但暴露接口名与流量形态（路由模板、业务码分布） | 低风险；公网部署建议网关层限制访问（与 `/docs` 同理） |

## 2. SSRF 风险专述（背景与业界防护规范）

> 本节记录风险背景与业界防护规范，不描述实现——`url` 与 `callback_url` 两个参数当前仍**无防护**（见 §1）。是否实现取决于部署形态，分级见 §2.3。

### 2.1 为什么是风险

服务端可被当作代理使用，两个参数对应两种形态：

| 攻击面 | 位置 | 形态与危害 |
|------|------|------|
| `url` 参数 | 服务端下载任意 URL | GET 型 SSRF：内网探测、读取内网服务 |
| `callback_url` 参数 | worker 主动向任意地址 POST 结果 | POST 型 SSRF：可向内网服务写入/触发状态变更，危害更大 |

典型威胁场景：

- **云 metadata 窃取**：请求 `http://169.254.169.254/...` 可获取云主机凭证（AWS/GCP/阿里云等平台的经典攻击路径）
- **内网探测**：利用响应时间与内容差异做端口扫描与服务识别；服务与 broker/redis 同网段部署时天然是内网跳板
- **绕过防火墙**：请求从受信服务器发出，边界防火墙拦的是外部入站流量，拦不住内部发起的外联

严重性业界定性：CWE-918，OWASP Top 10 2021 A10（Server-Side Request Forgery）。

### 2.2 业界防护规范

权威参考：[OWASP SSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)。业界共识是分层防御：

**网络层（最有效，属部署形态）**

- 出站流量经 egress 代理/防火墙白名单；内网敏感服务与业务网段网络隔离
- 云平台侧启用 metadata 防护（如 AWS IMDSv2 强制 token）

**应用层校验**

1. Allowlist（白名单）优先：只允许已知域名/IP。对 `callback_url` 尤其可行——回调目标通常是业务可控的有限集合
2. Denylist（黑名单）次之：拒绝私网段（10/8、172.16/12、192.168/16）、loopback（127/8、::1）、链路本地（169.254/16，含 metadata 地址）、保留段
3. 协议白名单：只放行 http/https（拒绝 file://、gopher:// 等）
4. DNS 解析后逐一校验：hostname 解析出的**所有** IP 都要过名单——同时解析出公网与私网地址时必须拒绝
5. 重定向处理：不允许 HTTP client 自动跟随重定向——白名单域名 302 到内网地址是经典绕过路径；拒绝或逐跳重校验
6. DNS rebinding / TOCTOU：校验与连接之间存在时间窗口（check-then-use），彻底消除需自定义 transport 在 connect 时复核 IP——业界一般如实标注为残留风险

**按参数类型区别对待**

- `callback_url`：Allowlist 可行且应优先——回调域是有限可控集合
- `url`（图片源）：Allowlist 通常不可行（任意图床），务实组合为协议白名单 + IP 黑名单 + 重定向拒绝，残留风险交给网络层隔离

### 2.3 触发条件与优先级

是否实现防护取决于部署形态，不是无条件必修项：

| 部署形态 | 结论 |
|------|------|
| 内网/受信网络（当前推荐形态） | 仅记录风险即可，实现可缓 |
| 公网 + 认证已开 | 优先级中高；先做 `callback_url` 侧（POST 型危害大、Allowlist 可行性高） |
| 公网 + 无认证 | 先启用认证（`INFERFORGE_API_KEY`）——无认证的任意调用是更直接的暴露面，SSRF 不是第一优先级 |
| 云主机部署 + 内网可达 metadata/管理服务 | 上线前必修 |

## 3. 部署建议

- **内网部署**：当前版本建议仅在内网/受信网络使用——无认证与 SSRF 风险的组合下，公网直接暴露不安全
- **公网暴露前的加固清单**（按需实施）：
  - `url` 过滤：拒绝私网段 / localhost / 链路本地地址，限制协议与端口（规范与分级见 §2）
  - `callback_url` 校验：域名白名单，或至少拒绝内网地址（见 §2）
  - 请求体大小上限：已有 `app.py` 的 Content-Length 20MB 守卫（默认开启，与图片下载上限一致；如需覆盖 chunked 请求，可在网关层限制 `client_max_body_size`）
  - 认证：接口层已内置——设置 `INFERFORGE_API_KEY` 即启用（默认关闭）；多用户 / SSO 场景仍走网关层
  - 限流：接口层已内置——设置 `INFERFORGE_RATE_LIMIT` 即启用（默认关闭）；多 worker 部署要求严格配额时接 Redis 共享计数或走网关层
  - `/docs` 与 `/openapi.json` 无认证暴露接口文档——公网部署时建议网关层屏蔽或加认证
  - `/metrics` 同理——网关层限制访问（如只允许 Prometheus 的来源 IP）
