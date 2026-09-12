# 从模板创建新工程（Bootstrap）

> 模板的使用方式：把模板装配为一个新业务工程的起点（模板仓库只读）——按需选择能力、改名、配置初始化、底座验收。完成后你拥有一个能跑的服务，后续开发见 [add-capability.md](add-capability.md)（新增）与 [modify-service.md](modify-service.md)（修改）；与模板上游的关系见 [forking-contract.md](forking-contract.md)。最后更新：2026-09-12

## 1. 总流程

> 使用方式：在模板目录与开发 Agent 对话，指定新工程的目标路径——初始化（装配、改名、配置、验收）全部发生在目标路径，模板仓库只读、永不修改。fork + PR 是改进模板自身的贡献路径，不属于使用流程。

1. 下载模板到本地（§2，一次性）
2. 在模板目录与 Agent 对话，指定目标路径与能力："初始化一个 web 服务到 `<路径>`，要检测 + 异步"（未给路径先问）
3. Agent 在目标路径执行：按需装配（§2、§4）→ 改名（§3，一次性）→ 配置初始化（§5）→ 底座验收（§6，通过后才开始业务开发）
4. 切换到目标路径继续开发（后续会话在目标路径启动）

**约定：模板仓库本身不参与后续开发**——全部业务改动发生在新工程；模板上游更新以 CHANGELOG 发布，是否跟进由你决定（见 [forking-contract.md](forking-contract.md) §4）。

## 2. 下载模板与按需装配

模板目录是只读工厂——下载到本地，初始化与开发全部发生在新工程路径，模板本身永不修改：

```bash
git clone https://github.com/zjykzj/InferForge.git ~/InferForge
```

新工程由 `scripts/assemble.py` **按需装配**（正向清单）：只复制所选能力/特性的文件，未选的根本不存在——不需要"复制全部再删除"：

```bash
python3 ~/InferForge/scripts/assemble.py --target /path/to/my-service \
    --with detect,async --features docker
```

- 不带 `--with`：仅 base——服务外壳 + 健康探针，无任何业务能力（默认装配）
- `--with`：能力清单，依赖自动展开（如 `pipeline` 自动带上 detect+cls，见 §4）
- `--features`：docker / deploy / benchmark
- 装配器按选择剔除 wiring 文件里的 `# @inferforge:<name>` 标记块（app.py 路由、就绪探测、注册表条目等），生成工程不含任何对缺失文件的引用；选中能力时自动生成 `models/registry.yaml`

装配完成后在目标路径初始化仓库：

```bash
cd /path/to/my-service && git init && git add -A && git commit -m "init: from InferForge"
```

模板更新：`cd ~/InferForge && git pull`——与业务工程零耦合。改进模板本身走 fork + PR（贡献路径，见 [forking-contract.md](forking-contract.md)）。

新工程继承的远不止代码：`CLAUDE.md`（硬规则）、`docs/`（知识与食谱）、`tests/`（可执行契约）、`.github/workflows/ci.yml`（CI，复制后自动生效）、`deploy/`（部署参考工件）全部随仓库走。**这些是给开发 Agent 的知识与验证底座**——开发时 CLAUDE.md 随工作目录常驻上下文，测试跑出红灯就是反馈。

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

## 4. 能力与特性选择（正向装配）

模板自带的能力是**参照物**，也是可选零件——初始化时按需选择，未选的文件根本不会出现在新工程里：

| 能力 | 形态 | 开关 | 参照价值 |
|------|------|------|---------|
| detect | 同步 + 异步变体可选 | 选中即常开；`INFERFORGE_ASYNC` 叠加 | 同步形态 canonical、callback/query 双变体 canonical |
| segment / classify / pipeline / dedup | 同步 | `INFERFORGE_SEG` / `CLS` / `PIPELINE` / `DEDUP` | 同形态多能力的 footprint 参照 |
| embed | 本地嵌入引擎（DINOv2） | —（被 dedup/search 复用） | 引擎 + 业务任务的底座 |
| async | 检测的异步变体（Celery） | `INFERFORGE_ASYNC` | callback/query 双变体 canonical |
| vlm / agent / search | query-only 异步 | `INFERFORGE_LLM` / `AGENT` / `SEARCH` | query-only 形态 canonical |

| 特性 | 内容 |
|------|------|
| docker | Dockerfile + compose 全栈 |
| deploy | nginx 灰度、logrotate、监控栈 |
| benchmark | 压测脚本 + 基线文档 |

- **依赖自动展开**：`pipeline` → detect+cls；`search` → embed+async；`agent` → detect+async；`vlm` → async；`seg` → detect
- **建议保留至少一个与目标业务同形态的参照，直到自建第一个业务能力跑通**——Agent 开发靠模仿 canonical，删了就没了模仿对象
- 装配机制：正向清单在 `templates/manifest.yaml`（每个文件恰好归属一处，`tests/test_bootstrap_manifest.py` 守护）；wiring 文件里的 `# @inferforge:<name>` 标记块由 assemble.py 按选择剔除
- **事后裁剪**：先按全量装配、之后想删某个能力时，走删除面清单（漏一处 pytest 就会告诉你）：

1. `engines/<name>.py`、`tasks/<name>*.py`、`apis/<name>*.py`、`tests/test_<name>*.py`、`scripts/run_<name>.py`、`scripts/test_<name>*.py`
2. `app.py` 里对应的开关函数与 `include_router` 注册块
3. `scripts/preflight_models.py` 的 `CAPABILITY_SWITCH` 条目
4. `models/registry.yaml` 里该 capability 的条目与 `defaults`
5. `apis/health.py` 就绪探测中的对应能力
6. `utils/metrics.py` 中该能力专属的指标（如 vlm remote 指标）
7. docs 中引用该能力的小节
8. 若没有 `registry.yaml`（env 合成模式），内置能力的合成注册表硬编码在 `engines/registry.py` 的 `CAPABILITIES` / `_ENV_FALLBACK`——删除内置能力需同步改这两处（模板文件，合并上游时按 forking-contract 黄区处理）

删除后 `pytest tests/` 必须全绿，`py_compile` 必须干净——这就是模板的删除守护。

## 5. 配置初始化

```bash
cp .env.example .env                    # 按需填（VLM/agent 配置、部署开关）
# 模型文件（onnx 等）放进 models/（git 忽略、compose 绑定挂载，永不进镜像）
```

- `.env` 由 `app.py`/`celery_app.py` 在 import 时加载（`override=False`：shell/compose 环境变量优先）
- registry：装配时已为所选能力生成 `models/registry.yaml`（来源是 `registry.example.yaml` 的装配结果）；embed 不在示例注册表中，选中 embed 时手工补条目（见 [model-registry.md](../model-registry.md)）。无能力装配（仅 base）不生成 registry 文件——env 合成模式返回空注册表，健康探针正常工作

## 6. 底座验收（开始业务开发的 done 定义）

```bash
pytest tests/ -v                       # 全绿（装配所选能力的冒烟测试，模型无关网络无关）
python3 -m py_compile app.py apis/*.py tasks/*.py engines/*.py utils/*.py tests/*.py scripts/*.py
python3 app.py                         # 起服务，GET /health 返回 200（无模型也能起）
./start.sh                             # 正式启动路径（含 preflight 模型检查，需要 models/ 里有注册的模型）
```

push 后 GitHub Actions 自动跑 CI（冒烟测试 + 编译检查 + docs 链接检查）——模板的 workflow 随复制生效，无需配置。

## 7. 知识层的继承与生长（重要约定）

| 规则 | 说明 |
|------|------|
| 模板知识是**种子** | 新工程里的 `CLAUDE.md`/`docs/` 描述的是**模板基线**，不是新工程的现状 |
| 开发技能随代码继承 | `.claude/skills/` 的四份薄壳（bootstrap/add-capability/add-engine/modify-service）随复制保留、路径不变、开箱即用；与文档同源，业务规则沉淀时按需同步 |
| 业务规则写进新工程 | 每沉淀一条业务规则（新增状态码、新增能力、部署差异），同步更新新工程自己的 `CLAUDE.md`/`docs/`——它们是**活文档**，随业务生长 |
| 不回改模板 | 模板文档只描述基线；想让模板改进则向上游提 issue/PR（见 [forking-contract.md](forking-contract.md)） |
| 漂移是正常的 | 新工程代码与模板文档逐渐不一致是预期状态；合并上游更新时的取舍见 forking-contract §4 |
