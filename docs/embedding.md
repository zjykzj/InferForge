# Embedding 检索与去重（Embedding Search & Dedup）

> 图像 embedding 能力的三个业务场景——检索（以图搜图）、库查重（有没有相同内容的图）、批内去重（谁和谁重复）——的差异、实现场景与算法。最后更新：2026-09-02

## 1. 三个场景的差异

三个场景共享**同一个 embedding engine**（把图片编码为语义向量）与同一份 gallery 索引，差异在 task 层的编排与输出语义：

| 维度 | 检索（search） | 库查重（dupcheck） | 批内去重（dedup） |
|------|----------------|--------------------|--------------------|
| 输入 | 1 张 query + 预建好的 gallery 库 | 1 张图 + gallery 库 | 一批 N 张图（批次本身就是比对全集） |
| 底层计算 | query 向量 → 索引 top-k | query 向量 → 索引 top-1 + 阈值判定 | 批内 N×N cosine + 阈值 + 连通分组 |
| 输出 | 相似度排序列表 `[{id, path, score}]` | `{found, match, threshold}` | `{groups, total, duplicates}` |
| 阈值判定谁做 | **调用方**自己看分决定 | **服务端**（top-1 ≥ 阈值即判重） | 服务端 |
| 状态 | 有状态——依赖 gallery 索引 | 有状态——依赖 gallery 索引 | 无状态 |
| 索引 | milvus-lite 单文件嵌入式索引 | 同左 | 不需要索引 |
| 部署形态 | async worker（query-only，见 §5 约束） | 同左 | 同步（纯 numpy） |

检索与库查重是**同一个底层查询的两种语义**：检索返回候选让调用方判断，查重是"库里有没有内容相同的图"的 yes/no 判定。一个 engine、三个 task，是模板里「算法实现与业务编排分离」最直观的展示：换 backbone（如 CLIP、ResNet 特征）只动 `engines/`，三个业务场景零改动。

## 2. 实现场景

**检索（以图搜图）**：给定一张 query 图，从候选图库（gallery）中找出语义最相似的图片。典型业务：版权素材查重、商品相似款、图片内容检索。

**库查重（素材入库防重）**：给定一张新图，判定 gallery 里是否已有内容相同的图（`found=true` 则业务方拒绝入库）。服务端下判定，阈值是服务端业务参数。

**批内去重（近似重复）**：给定一批图片，找出互为近似重复的分组。**near-duplicate** 才是 embedding 的用武之地——同一张图被压缩、加字/水印、裁剪、换分辨率后像素完全不同但语义相同，哈希类方法（MD5 / pHash）只对 exact duplicate 有效，识别不了这类变换。接口只**识别**分组，删除动作由调用方在自己的存储上执行。

## 3. 算法

### 3.1 引擎：DINOv2-small（`engines/dinov2.py`）

- ViT-S/14，22M 参数，输出 384 维向量；预处理 resize 到 224 + ImageNet 归一化，后处理取 CLS token → L2 归一化
- 自写前/后处理（不 import 任何 AGPL 代码），权重由用户导出 ONNX 放入 `models/`（同 yolov8n 的方式）；导出脚本 `python3 scripts/export_dinov2.py`（torch 一次性依赖，脚本内含形状自校验；hub 模型 `forward_features` 返回字典，脚本用包装模块把 CLS + patch tokens 拼回 `(1, 257, 384)` 经典 token 序列，见脚本 docstring）；预处理必须与所用 ONNX 导出匹配（resize/归一化各导出有差异，见引擎 docstring）
- 权重 license 提醒：官方 DINOv2 权重为 **CC-BY-NC-4.0**（非商用）——模板 demo 无碍，商用部署需替换 backbone（引擎契约不变，正是 §1 说的换 engine 路径）
- `engines/base.py` 的 `EmbeddingResult`（`vector: (D,)`），registry 新增 `embed` capability（`INFERFORGE_EMBED_MODEL_PATH` 环境回退，默认 `models/dino2-small.onnx`）

### 3.2 检索 / 查重：预索引 + cosine + top-k

1. 建库：`scripts/build_gallery.py` 扫描 gallery 目录（`INFERFORGE_GALLERY_DIR`，默认 `gallery/`）→ 逐张过 engine 出向量 → 写入 milvus-lite db 文件（`INFERFORGE_GALLERY_DB`，默认 `data/gallery.db`；collection：id=文件名、vector、path）
2. 检索：query 图过同一个 engine 出向量 → 索引 cosine → top-k（请求参数 `top_k`，默认 5，上限 50）
3. 查重：同检索但取 top-1，与阈值（`INFERFORGE_DUP_THRESHOLD`，默认 0.95）比较后输出判定
4. 模板规模用 milvus-lite 线性扫描即可；生产量级替换为 FAISS / Milvus 集群——task 层对索引实现的依赖只隔着「query 向量 → top-k」这层薄接口

### 3.3 去重：N×N cosine + 阈值 + union-find

1. 批量 N 张图各自出向量 → N×N cosine 相似度矩阵
2. 阈值过滤（`INFERFORGE_DUP_THRESHOLD`，默认 0.95——**业务参数放 task 层**："多像才算重复"是业务决策，不是算法参数）
3. 相似对做 union-find 连通分量——**近似重复是传递的**：A~B、B~C 时 A/C 单独比可能低于阈值（A 被压缩过、C 被裁过边），但三张是同一张图的变换，必须合并为一组；贪心配对会拆散这条链
4. 每个连通分量 = 一个重复组；representative = 组内与其他成员平均 cosine 最高的一张（建议保留），confidence = 该平均相似度；单元素组丢弃
5. 复杂度 O(N²)，N 是批次张数（同步接口上限 50）；上千张的批量去重再考虑 ANN 或分块

## 4. 分层与泛化

- engine 只出向量，不知道「搜索」「查重」「去重」的存在；三个 task 各自编排、各自定义 payload 与错误语义
- 与 pipeline 任务一样是**组合模式**：`tasks/search.py`（检索 + 查重）/ `tasks/dedup.py` 通过 `tasks/embedding.py` 的缓存持有 embed predictor（按注册模型名 key），API 层看不到 predictor
- gallery 绑定 **embed 缺省模型**：建库脚本与 worker 用同一个模型编码，换模型必须重建索引；多模型 embed（每模型一个 collection）超出模板范围
- 泛化：把 DINOv2 换成 CLIP（支持图文检索）或 ResNet 特征，只新增一个 engine 文件 + registry 条目；把阈值/度量（cosine → L2）换成别的，只改 task 层

## 5. 选型与约束（milvus-lite）

- **为什么 milvus-lite**：单文件嵌入式向量库，无需 server 组件（docker-compose 不用加服务），Apache-2.0，384 维 float 向量在模板规模（几千~几万张）毫无压力
- **单进程独占是硬约束**：同一个 db 文件同一时刻只能被一个进程打开。推论：
  1. search/dupcheck 只能走 **async worker**（query-only，与 vlm/agent 同一部署形状）——只有 celery worker 进程开 db；做成同步 web API 的话，gunicorn 多 worker 会同时打开同一个文件直接冲突
  2. 重建 gallery 前要停 worker（文档写明）；`scripts/build_gallery.py --force` 重建
- **依赖懒加载**：`pymilvus[milvus-lite]` 是重依赖，按项目规矩 worker-only + 函数体内 import（web 与测试不安装也能跑）；测试用 FakePredictor seam、永不打开 milvus，CI 保持免模型免网络
- **建库脚本**：`scripts/build_gallery.py`（对齐 preflight 脚本的套路——import 项目代码前 unset `PROMETHEUS_MULTIPROC_DIR`，避免污染共享 metrics 目录）

## 6. 接口与开关（已落地）

| 接口 | 形态 | 开关 |
|------|------|------|
| `POST /predict/dedup` | 同步 | `INFERFORGE_DEDUP=1`（独立） |
| `POST /predict/search/query` + `GET .../<task_id>` | 异步 query-only | `INFERFORGE_SEARCH=1`（需 `INFERFORGE_ASYNC=1`，否则告警跳过） |
| `POST /predict/search/check` + `GET .../<task_id>` | 异步 query-only | 同 `INFERFORGE_SEARCH` |

- `INFERFORGE_GALLERY_DIR`（默认 `gallery/`）：检索/查重的 gallery 图片目录
- `INFERFORGE_GALLERY_DB`（默认 `data/gallery.db`）：milvus-lite 索引文件
- `INFERFORGE_DUP_THRESHOLD`（默认 0.95）：查重与去重共用的近重复阈值
- `INFERFORGE_EMBED_MODEL_PATH`（默认 `models/dino2-small.onnx`）：embed 模型路径（注册表文件不存在时生效）
- readiness/preflight/预热：`INFERFORGE_DEDUP` 开启时 web 探测 embed 缺省模型；`INFERFORGE_SEARCH` 开启时只影响 worker（web 不探——worker-only 能力探了会永远 503）；preflight 在任一开关开启时检查 embed 模型文件
- 接口细节与 curl 示例见 [api.md](api.md) §5（去重）、§14（检索）、§15（查重）
