# 从模板创建新工程（Bootstrap）

> 模板的使用方式：把本仓库变成一个新业务工程的起点——改名、裁剪 demo 能力、配置初始化、底座验收。完成后你拥有一个能跑的服务，后续开发见 [add-capability.md](add-capability.md)（新增）与 [modify-service.md](modify-service.md)（修改）；与模板上游的关系见 [forking-contract.md](forking-contract.md)。最后更新：2026-09-10

## 1. 总流程

1. 复制模板为新仓库（§2）
2. 改名（§3，一次性）
3. 裁剪不用的 demo 能力（§4）
4. 配置初始化（§5）
5. 底座验收（§6，通过后才开始业务开发）

**约定：模板仓库本身不参与后续开发**——全部业务改动发生在新工程；模板上游更新以 CHANGELOG 发布，是否跟进由你决定（见 [forking-contract.md](forking-contract.md) §4）。

## 2. 复制模板

两种方式，效果相同：

| 方式 | 操作 | 适用 |
|------|------|------|
| fork | GitHub 上 fork 后 clone 到本地 | 想保留与模板的 fork 关联（提 PR 回上游方便） |
| 新仓库 | `git clone` 模板 → 删除 `.git` → 在新仓库 `git init` + 首次提交 | 完全独立的业务仓库，不留模板痕迹 |

新工程继承的远不止代码：`CLAUDE.md`（硬规则）、`docs/`（知识与食谱）、`tests/`（可执行契约）、`.github/workflows/ci.yml`（CI，fork 后自动生效）、`deploy/`（部署参考工件）全部随仓库走。**这些是给开发 Agent 的知识与验证底座**——开发时 CLAUDE.md 随工作目录常驻上下文，测试跑出红灯就是反馈。

## 3. 改名清单（一次性）

| 位置 | 现状 | 操作 |
|------|------|------|
| `app.py` `create_app()` | `title="InferForge"`、description | 改为你的服务名与描述（显示在 `/docs` OpenAPI 页面） |
| `docker-compose.yml` | `image: inferforge:latest`（web/worker 两处） | 改为你的镜像名（仅本地 `docker compose up` 不改也能跑） |
| `README.md` / `README.zh-CN.md` | 标题、badge 里的 `github.com/zjykzj/InferForge` 链接（CI/Release 两处）、DeepWiki badge | 改为新仓库地址，或删掉不适用的 badge |
| `CLAUDE.md` Maestro 配置节 | `{{REPO_URL}} = https://github.com/zjykzj/InferForge` | 改为新工程仓库地址（发布技能会用） |
| `VERSION` | 模板版本号 | 重置为 `0.1.0`；`CHANGELOG.md` 写新工程的首个 `[Unreleased]` 条目 |
| `LICENSE` | MIT + 模板作者 | 保留 MIT 则更新版权行 |
| 各文件 docstring/注释里的 "InferForge" | `gunicorn.conf.py`、`utils/logger.py`、`engines/base.py`、`start.sh`、`.env.example` 等 | 纯外观，不阻塞运行，建议顺手改 |

改名不影响任何功能——代码里没有硬编码的仓库路径或模板专属资源。

## 4. 裁剪 demo 能力

模板自带的能力是**参照物**，不是必选功能：

| 能力 | 形态 | 开关 | 参照价值 |
|------|------|------|---------|
| detect | 同步 + 异步（callback/query） | 始终开启 | 同步形态 canonical、callback/query 双变体 canonical |
| segment / classify / pipeline / dedup | 同步 | `INFERFORGE_SEG` / `CLS` / `PIPELINE` / `DEDUP`（默认关） | 同形态多能力的 footprint 参照 |
| vlm / agent / search / check | query-only 异步 | `INFERFORGE_LLM` / `AGENT` / `SEARCH`（默认关） | query-only 形态 canonical |

**原则：不用的能力默认关着即可，不必删除。** 尤其建议**保留至少一个与目标业务同形态的参照，直到自建第一个业务能力跑通**——Agent 开发靠模仿 canonical，删了就没了模仿对象。

确需删除时，一个能力的完整删除面（漏一处 pytest 就会告诉你）：

1. `engines/<name>.py`、`tasks/<name>*.py`、`apis/<name>*.py`、`tests/test_<name>*.py`、`scripts/run_<name>.py`、`scripts/test_<name>*.py`
2. `app.py` 里对应的开关函数与 `include_router` 注册块
3. `scripts/preflight_models.py` 的 `CAPABILITY_SWITCH` 条目
4. `models/registry.yaml` 里该 capability 的条目与 `defaults`
5. `apis/health.py` 就绪探测中的对应能力
6. `utils/metrics.py` 中该能力专属的指标（如 vlm remote 指标）
7. docs 中引用该能力的小节
8. 若没有 `registry.yaml`（env 合成模式），内置四能力的合成注册表硬编码在 `engines/registry.py` 的 `CAPABILITIES` / `_ENV_FALLBACK`——删除内置能力需同步改这两处（模板文件，合并上游时按 forking-contract 黄区处理）

删除后 `pytest tests/` 必须全绿，`py_compile` 必须干净——这就是模板的删除守护。

## 5. 配置初始化

```bash
cp .env.example .env                    # 按需填（VLM/agent 配置、部署开关）
cp models/registry.example.yaml models/registry.yaml   # 注册你自己的模型（见 model-registry.md）
# 模型文件（onnx 等）放进 models/（git 忽略、compose 绑定挂载，永不进镜像）
```

- `.env` 由 `app.py`/`celery_app.py` 在 import 时加载（`override=False`：shell/compose 环境变量优先）
- registry 缺省行为：没有 `registry.yaml` 时由 `INFERFORGE_*_MODEL_PATH` 合成单模型注册表——新工程建议一开始就建 registry 文件，多模型路由是模板的默认姿势（见 [model-registry.md](../model-registry.md)）

## 6. 底座验收（开始业务开发的 done 定义）

```bash
pytest tests/ -v                       # 全绿（模板自带 250+ 冒烟测试，模型无关网络无关）
python3 -m py_compile app.py apis/*.py tasks/*.py engines/*.py utils/*.py tests/*.py scripts/*.py
python3 app.py                         # 起服务，GET /health 返回 200（无模型也能起）
./start.sh                             # 正式启动路径（含 preflight 模型检查，需要 models/ 里有注册的模型）
```

push 后 GitHub Actions 自动跑 CI（冒烟测试 + 编译检查 + docs 链接检查）——模板的 workflow 随 fork 生效，无需配置。

## 7. 知识层的继承与生长（重要约定）

| 规则 | 说明 |
|------|------|
| 模板知识是**种子** | fork 里的 `CLAUDE.md`/`docs/` 描述的是**模板基线**，不是新工程的现状 |
| 业务规则写进新工程 | 每沉淀一条业务规则（新增状态码、新增能力、部署差异），同步更新新工程自己的 `CLAUDE.md`/`docs/`——它们是**活文档**，随业务生长 |
| 不回改模板 | 模板文档只描述基线；想让模板改进则向上游提 issue/PR（见 [forking-contract.md](forking-contract.md)） |
| 漂移是正常的 | fork 代码与模板文档逐渐不一致是预期状态；合并上游更新时的取舍见 forking-contract §4 |
