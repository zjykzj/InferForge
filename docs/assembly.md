# 装配说明（Assembly）

> 模板按需装配机制：为什么是正向清单、manifest 与 assemble.py 怎么工作、标记块约定与扩展纪律。使用流程见 [bootstrap.md](workflow/bootstrap.md)（怎么跑）；本文讲机制（为什么、怎么扩展）。最后更新：2026-09-13

## 1. 为什么是装配

模板曾是"复制全部 → 裁剪"：新工程先带走全套 demo 能力，再按删除面清单删掉不用的——**负向清单**。问题有两个：生成物带全套行李（Dockerfile、celery、deploy、全部 scripts 都跟着走），且删除比组装难（删除面、守护测试都是为"删"而生的机制）。此外还有一个隐蔽错误：模板的**身份文件与知识库**（README/CHANGELOG/LICENSE/docs）也被当成了拷贝对象——模板是参考，不是拷贝源；新工程的身份由自己生成。

装配把流程反转为**正向清单**：初始化时只复制所选能力/特性的文件，未选的根本不存在。生成物 = base + 选择闭包，没有删除步骤。

## 2. 选择模型

`templates/manifest.yaml` 里有这些条目：

| 类别 | 语义 | 例子 |
|------|------|------|
| `base` | 总是装配：**最小内核**——app 工厂、健康探针、占位包（tasks/engines）、契约测试、开发 skills；无机制、无业务能力、无模板身份文件——bare profile 下就是一个普通 FastAPI 服务 | `app.py`、`apis/health.py`、`.claude/skills/*` |
| `mechanisms` | 横切组件，opt-in；每个组件自带文件 + **依赖声明**（`requires` 展开机制间依赖） | envelope（{code, message, data} 契约 + body-limit + 422 折叠）、request_id、dotenv、metrics、auth、rate_limit、logging |
| `capability_contract` | **选中任何能力自动带入的机制清单**（envelope/request_id/dotenv）——业务 api 在任何 profile 上都保有服务契约 | — |
| `profiles` | 命名机制预设：`bare`（无机制）/ `kernel`（契约机制，默认）/ `production`（kernel + metrics/auth/rate_limit/logging）；`--profile` 选择，`--with` 与预设取并集 | — |
| `capabilities` | 能力文件集，opt-in；`requires` 自动展开依赖闭包 | detect / seg / cls / pipeline / embed / dedup / async / vlm / agent / search |
| `shared` | 任一 `any_of` 名称选中即包含 | `serving-stack`（engines/registry/start.sh/preflight——模型服务设施）、`http-stack`（schemas/image——HTTP 业务能力共用）、export_yolo |
| `features` | 部署/工具特性，opt-in | ci / docker / deploy / benchmark |
| `template` | 模板身份与知识库，**永不装配**——新工程的身份文件由 bootstrap §3 **生成**，不是复制 | README / CHANGELOG / LICENSE / CLAUDE.md / docs |
| `generated` | 装配器**写入**而非拷贝的文件 | requirements.txt = 所选条目依赖声明的合并 |
| `wiring` | 必须被标记块 100% 覆盖的文件清单（守护测试强制，见 §6） | app.py / conftest.py / apis/health.py / celery_app.py |

依赖展开：能力 `seg` → detect；`pipeline` → detect+cls；`dedup` → embed；`async` → detect；`vlm` → async；`agent` → detect+async；`search` → embed+async。机制 `auth` → envelope；`rate_limit` → auth；`logging` → request_id。任何能力 → capability_contract 机制（第二遍闭包）。

## 3. manifest.yaml

- 每个被跟踪文件**恰好归属一处**（base / 机制 / 能力 / shared / 特性）；目录条目以 `/` 结尾覆盖整棵子树
- 归属由守护测试强制执行（见 §6）——新文件进仓库必须登记，漏了 CI 会指出

## 4. assemble.py

```bash
python3 scripts/assemble.py --target /path/to/proj [--profile bare|kernel|production] [--with a,b] [--features x,y]
```

- `--profile` 默认 `kernel`（envelope + request_id + dotenv，与旧版 base 行为一致）；`bare` 是最小内核；`--with` 与 profile 取并集
- 装配动作：按清单复制 → 对含标记的文件剔除未选名称块（`base` 块永远保留，标记行本身始终剔除）→ 选中能力时把装配后的 `registry.example.yaml` 写成 `models/registry.yaml` → **合并所选条目的依赖声明写入 requirements.txt**
- **目标守卫（脚本执行，永不覆盖）**：目标不存在或为空 → 创建/使用；已存在且非空 → 拒绝——检出 `app.py`/`requirements.txt`/`pyproject.toml`/`.git` 时提示"看起来是已有工程"；目标落在模板仓库内 → 拒绝。装配器没有任何删除或覆盖路径（`--force` 已移除）

## 5. 标记块约定

能力代码大多在独立文件里（按文件集归属），但有一部分长在**共享的 wiring 文件**中——这部分用标记块声明归属：

```
# @inferforge:detect
from apis.sync_detect import sync_detect_router
# @inferforge:end:detect
```

- 复合标签 `# @inferforge:seg+cls` = 所有名字都选中才保留（AND 语义）
- `# @inferforge:base` = 无条件保留的常驻代码（标记行仍剔除）——**禁止 `base+x` 复合**（会被静默剔除，守护测试拦截）
- 装配规则：未选 → 整块剔除；选中 → 只剔除标记行本身；连续空行上限 2 行（被剔除块不留空洞）
- **全覆盖规则**：wiring 文件（manifest `wiring:` 清单）里每一非空行都必须在某个标记块内——游离代码（helper、docstring、注释）会被原样拷进所有装配，等于死代码。守护测试逐行强制（§6）
- **可选返回惯用法**：机制可选的分支用"块内 return + base 回退行"表达（如 health 的 envelope 返回与 bare 回退 `return {"status": "ok"}`）——机制选中时回退行不可达，未选时机制行被剔除；不支持否定标记（`!name`）是刻意的范围控制
- **编辑纪律**：改这些文件时标记必须配对（嵌套安全，守护测试会抓）；给能力/机制新增 wiring 代码时加标记块并同步登记 manifest；块内借用其他块的导入时必须有 `requires` 闭包保证（如 test_metrics.py 的 vlm 块借用 detect 块的 pytest 导入——vlm→async→detect）

## 6. 工厂专属与守护

工厂专属（FACTORY_ONLY，永不出厂）：`templates/manifest.yaml`、`scripts/assemble.py`、`scripts/check_assembly.py`、`tests/test_bootstrap_manifest.py`。

守护检查（`tests/test_bootstrap_manifest.py`）：

1. 每个被跟踪文件恰好被声明一次（无孤儿、无重复归属）
2. 每条声明路径在仓库中存在
3. 标记块配对（嵌套安全）+ 只用已知标签（能力/机制/特性/base）
4. `requires`/`any_of` 引用已知名称；能力/机制文件集与 base 无交集；模板文件不被能力/shared 认领
5. wiring 文件全覆盖（逐行归属，见 §5）
6. profiles / capability_contract / 机制 `requires` 只引用已知机制

**生成物自证**（`scripts/check_assembly.py`，工厂专属，CI 执行）：bare/kernel/detect/detect-async/production/full 六种装配进临时目录，各跑 py_compile + pyflakes + pytest——生成工程必须编译干净、无死代码（pyflakes；celery_app 的任务注册导入按刻意 F401 过滤）、自身测试全绿。

## 7. 扩展指南

模板侧新增一个能力（或机制）：

1. 文件加进 manifest `capabilities`（或 `mechanisms`），`requires` 声明依赖，`requirements` 声明 pip 依赖
2. wiring 文件里的共享代码加标记块（配对、全覆盖）；新 wiring 文件登记进 `wiring:` 清单
3. `pytest tests/test_bootstrap_manifest.py` 通过
4. `python scripts/check_assembly.py` 全绿（六种装配编译 + lint + 自测）——生成物自证
5. 新机制要进 profile 时更新 `profiles`（如 production 想带新机制）

与 [add-capability.md](workflow/add-capability.md) §3 footprint 的关系：footprint 回答"一个能力由哪些文件构成"（业务侧约定），manifest 回答"这些文件在装配时如何选择"（模板侧登记）——新增能力时两处都要更新。

## 8. 与 bootstrap.md 的分工

- [bootstrap.md](workflow/bootstrap.md)：使用视角——下载、选 profile 与能力、跑装配、改名、验收
- 本文：机制视角——为什么、manifest/标记约定、怎么扩展
