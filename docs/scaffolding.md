# Scaffolding 工具调研与模板工程化取舍（Scaffolding Landscape）

> 领域知识文档：业界模板/脚手架工具的机制谱系与"确定性生成器 + Agent 做胶水"的工程共识，**不描述本工程的实现**——InferForge 对每条业界做法的采纳/未采纳映射见 §4/§5，实现状态在各节末尾标注（对照 [assembly.md](assembly.md) 与 [design-principles.md](design-principles.md)）。最后更新：2026-09-13

## 1. 背景：模板工程化的三次演进

InferForge 的装配机制经历了三次演进，每一次都对应一个业界早已解决的子问题：

1. **复制全部 → 裁剪**（负向清单）：新工程带着全套行李出生，删除比组装难
2. **正向 include-list + marker 剥离**：未选的文件根本不存在，wiring 文件按标记块剔除——但游离代码（helper、docstring、注释）仍会泄漏进生成物
3. **机制化 + profile 分档 + 确定性 skill**：base 收敛为最小内核，机制按 profile 预设选择，初始化步骤由脚本强制而非 Agent 临场发挥

第三步的每个决策（目标守卫、profile 预设、全覆盖守护、生成物自证）都能在业界工具中找到对应物——本文记录对照与取舍。

（实现状态：第 1/2 步见 assembly.md §1；第 3 步为机制化改造，见 assembly.md §2/§4/§5/§6。）

## 2. 业界工具谱系

| 工具 | 机制要点 | 对本模板的启示 |
|------|---------|---------------|
| **Copier** | questions 驱动条件文件、`_tasks` 前后钩子、**默认拒绝写入非空目录**、`copier update` 把模板更新**回放**到已生成工程 | 非空目录守卫；update 回放是 forking-contract §4 升级路径的潜在形态 |
| **Yeoman** | 生成器框架：提问 → 文件动作 → **冲突解决**（对已存在文件 diff 询问 overwrite/skip） | 目标已有内容时的拦截与提示 |
| **Spring Initializr** | "限定死"的极端形态：固定菜单选能力 → 确定性输出，无任何 LLM | profile 预设的选择模型——固定场景固定实现 |
| **Backstage Software Templates** | 企业内部 golden path 目录：表单 → 步骤化 fetch/action/publish + nextSteps | 企业级"创建服务"的统一入口形态 |
| **Nx generators / Angular schematics** | 对**已有工程**的增量生成（AST 插入） | add-capability 场景：给已生成工程追加能力的对照物 |
| **create-\* 家族**（create-next-app 等） | 固定 flag + 固定文件内容，无对话 | 极简确定性装配的基线 |

## 3. 共识：核心脚手架不交给 LLM 自由发挥

"基于 Agent 进行模板编程"在业界的收敛形态是**确定性生成器 + Agent 做胶水**：

- 核心脚手架由确定性脚本生成——可复现、可审查、可测试（CI 能逐字节验证）
- Agent 负责需求澄清（选哪些能力/机制）、身份文件生成、验收执行与失败 triage、后续业务开发
- 反例：LLM 临场生成脚手架 → 每次输出不同、无法测试、契约漂移

（实现状态：bootstrap skill 已改为确定性步骤——profile 提问、脚本守卫、逐步验收，见 workflow/bootstrap.md 与 `.claude/skills/inferforge-bootstrap/SKILL.md`。）

## 4. 采纳映射（业界做法 → InferForge 实现）

| 业界做法 | InferForge 对应实现 |
|---------|-------------------|
| Copier 拒非空目录 / Yeoman 冲突询问 | assemble.py 目标守卫：非空拒绝 + "已有工程"检测提示（assembly.md §4） |
| Spring Initializr 固定选择菜单 | `--profile bare|kernel|production` 预设 + `--with` 并集（manifest `profiles:`） |
| schematics 增量生成 | marker 块 + add-capability 流程（对已生成工程的追加） |
| 确定性可测的生成器 | wiring 全覆盖守护测试（逐行归属）+ `scripts/check_assembly.py` 六装配自证（py_compile + pyflakes + pytest） |
| create-\* 的极简基线 | bare profile：约 50 行 app.py 的纯 FastAPI 内核 |

## 5. 未采纳与原因

| 候选 | 未采纳原因 |
|------|-----------|
| 以 Copier 替换自研 assemble.py | 评估推迟：manifest 正向清单 + marker + 契约测试已是单一事实源，自研成本已付；Copier 的增量价值（update 回放）是未来增量，届时可在现有 manifest 上评估（forking-contract §4 当前靠 CHANGELOG + 三方合并取舍） |
| marker 否定语法（`!name`） | 范围控制：需要"选中时剔除"的场景用"块内 return + base 回退行"惯用法表达（assembly.md §5），不引入新语法 |
| LLM 自由生成核心脚手架 | 违背 §3 共识——固定场景固定实现，LLM 只做编排与偏差处理 |

## 6. 实现状态汇总

- 已落地：目标守卫、profile 分档、capability_contract 闭包、wiring 全覆盖守护、生成物自证、确定性 bootstrap skill
- 未落地（有意推迟）：Copier 迁移与 update 回放；否定标记
