# deploy/ — Reference artifacts（参考工件）

本目录是**参考工件库，不属于模板 core contract**：每个文件是一份带使用说明的参考配置，练手产出与生产参考并存，按需拷贝、自由修改。上游更新这些文件不影响你的业务代码（见 [forking-contract](../docs/forking-contract.md)）。

| 文件 | 用途 | 相关文档 |
|------|------|---------|
| [logrotate.conf](logrotate.conf) | 日志轮转：gunicorn / 业务日志落盘后的系统级轮转（copytruncate，无多进程竞态） | [logging](../docs/logging.md) |
| [nginx-canary.conf](nginx-canary.conf) | 灰度发布流量分流：权重切流 + `X-Canary: 1` 定点切换 | [deployment](../docs/deployment.md) §2 |

使用方式：拷到你的部署环境，按文件顶部注释替换占位，`nginx -t` / `logrotate -d` 验证后上线。它们是**示例，不是成品**——TLS、域名、端口替换成你自己的。
