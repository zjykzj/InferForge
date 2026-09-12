# 装配说明（Assembly）

> 模板按需装配机制：为什么是正向清单、manifest 与 assemble.py 怎么工作、标记块约定与扩展纪律。使用流程见 [bootstrap.md](workflow/bootstrap.md)（怎么跑）；本文讲机制（为什么、怎么扩展）。最后更新：2026-09-12

## 1. 为什么是装配

模板曾是"复制全部 → 裁剪"：新工程先带走全套 demo 能力，再按删除面清单删掉不用的——**负向清单**。问题有两个：生成物带全套行李（Dockerfile、celery、deploy、全部 scripts 都跟着走），且删除比组装难（删除面、守护测试都是为"删"而生的机制）。

装配把流程反转为**正向清单**：初始化时只复制所选能力/特性的文件，未选的根本不存在。生成物 = base + 选择闭包，没有删除步骤。

## 2. 选择模型

`templates/manifest.yaml` 里有四类条目：

| 类别 | 语义 | 例子 |
|------|------|------|
| `base` | 总是装配：服务外壳 + 健康探针，**无任何业务能力**（默认装配） | `app.py`、`utils/*`、`apis/health.py` |
| `capabilities` | 能力文件集，opt-in；`requires` 自动展开依赖闭包 | detect / seg / cls / pipeline / embed / dedup / async / vlm / agent / search |
| `shared` | 任一 `any_of` 能力选中即包含 | `scripts/export_yolo.py`（detect/seg/cls 任一） |
| `features` | 部署/工具特性，opt-in | docker / deploy / benchmark |

依赖展开表：`seg` → detect；`pipeline` → detect+cls；`dedup` → embed；`async` → detect；`vlm` → async；`agent` → detect+async；`search` → embed+async。

## 3. manifest.yaml

- 每个被跟踪文件**恰好归属一处**（base / 能力 / shared / 特性）；目录条目以 `/` 结尾覆盖整棵子树
- 归属由守护测试强制执行（见 §6）——新文件进仓库必须登记，漏了 CI 会指出

## 4. assemble.py

```bash
python3 scripts/assemble.py --target /path/to/proj [--with a,b] [--features x,y] [--force]
```

- 不带 `--with`：仅 base
- 装配动作：按清单复制 → 对含标记的文件剔除未选能力块 → 选中能力时把装配后的 `registry.example.yaml` 写成 `models/registry.yaml`
- 目标目录必须为空（`--force` 覆盖），可重复生成

## 5. 标记块约定

能力代码大多在独立文件里（按文件集归属），但有一部分长在**共享的 wiring 文件**中——这部分用标记块声明归属：

```
# @inferforge:detect
from apis.sync_detect import sync_detect_router
# @inferforge:end:detect
```

- 复合标签 `# @inferforge:seg+cls` = 所有名字都选中才保留（AND 语义）
- 装配规则：未选 → 整块剔除；选中 → 只剔除标记行本身
- wiring 文件清单：`app.py`、`apis/health.py`、`tasks/warmup.py`、`scripts/preflight_models.py`、`engines/registry.py`、`models/registry.example.yaml`、`conftest.py`、`docs/README.md` 及共享测试文件（`tests/test_app.py`、`test_health.py`、`test_metrics.py`、`test_preload.py`、`test_registry.py`、`test_architecture.py`）
- **编辑纪律**：改这些文件时标记必须配对（嵌套安全，守护测试会抓）；给能力新增 wiring 代码时加标记块并同步登记 manifest

## 6. 工厂专属与守护

工厂专属（FACTORY_ONLY，永不出厂）：`templates/manifest.yaml`、`scripts/assemble.py`、`tests/test_bootstrap_manifest.py`。

守护四类检查（`tests/test_bootstrap_manifest.py`）：

1. 每个被跟踪文件恰好被声明一次（无孤儿、无重复归属）
2. 每条声明路径在仓库中存在
3. 标记块配对（嵌套安全）+ 只用已知能力/特性标签
4. `requires`/`any_of` 引用已知能力；能力文件集与 base 无交集

## 7. 扩展指南

模板侧新增一个能力：

1. 能力文件加进 manifest `capabilities`（`requires` 声明依赖）
2. wiring 文件里的共享代码加标记块（配对）
3. `pytest tests/test_bootstrap_manifest.py` 通过
4. 用 assemble.py 生成含该能力的工程，其内 `pytest` 全绿——生成物自证

与 [add-capability.md](workflow/add-capability.md) §3 footprint 的关系：footprint 回答"一个能力由哪些文件构成"（业务侧约定），manifest 回答"这些文件在装配时如何选择"（模板侧登记）——新增能力时两处都要更新。

## 8. 与 bootstrap.md 的分工

- [bootstrap.md](workflow/bootstrap.md)：使用视角——下载、选能力、跑装配、改名、验收
- 本文：机制视角——为什么、manifest/标记约定、怎么扩展
