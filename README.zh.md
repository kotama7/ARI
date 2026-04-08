<div align="center">
  <img src="docs/logo.png" alt="ARI Logo" width="200"/>

  # ARI — Artificial Research Intelligence

  **通用研究自动化系统。从笔记本到超级计算机。从本地模型到云端 API。从新手到专家。从计算实验到物理世界。**

  [![Tests](https://img.shields.io/badge/tests-1200%2B-brightgreen)](./ari-core)
  [![Version](https://img.shields.io/badge/version-v0.4.1-orange)](https://github.com/kotama7/ARI/releases)
  [![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://python.org)
  [![MCP](https://img.shields.io/badge/protocol-MCP-purple)](https://modelcontextprotocol.io)
  [![License](https://img.shields.io/badge/license-MIT-blue)](./LICENSE)
  [![Discord](https://img.shields.io/badge/Discord-Join-5865F2?logo=discord&logoColor=white)](https://discord.gg/SbMzNtYkq)

  **语言:** [English](README.md) · [日本語](README.ja.md) · **中文**
</div>

---

## 愿景

研究自动化不应该需要超级计算机、云预算或工程团队。

ARI 围绕一个原则设计：**用 Markdown 描述目标 — 其余的交给 ARI 处理。**

- 拥有一台笔记本和本地 LLM 的学生可以在 10 分钟内运行第一个自主实验。
- 拥有 HPC 集群访问权限的研究者可以在一夜之间运行 50 节点并行假设搜索。
- 团队只需添加一个 MCP 技能即可扩展 ARI 来控制实验硬件、机器人或 IoT 传感器 — 无需修改核心代码。

系统在五个维度上扩展：

| 维度 | 最小配置 | 完整配置 |
|------|---------|------|
| **计算** | 笔记本（本地进程） | 超级计算机（SLURM 集群） |
| **LLM** | 本地 Ollama (qwen3:8b) | 商用 API (GPT-5, Claude) |
| **实验规格** | 3 行 `.md` | 详细 SLURM 脚本 + 规则 |
| **领域** | 计算基准测试 | 物理世界（机器人、传感器、实验室） |
| **专业水平** | 新手（仅目标） | 专家（完整参数控制） |

---

## 实际效果

<p align="center">
  <video src="https://github.com/kotama7/ARI/raw/main/docs/movie/zh/ari_dashboard_demo.mp4" controls width="720" muted playsinline>
    您的浏览器不支持内联视频。<a href="docs/movie/zh/ari_dashboard_demo.mp4">点击此处下载演示</a>。
  </video>
</p>

🎬 **仪表板演示视频** — ARI Web 仪表板的完整演示。也提供 [English](docs/movie/en/ari_dashboard_demo.mp4) · [日本語](docs/movie/ja/ari_dashboard_demo.mp4)。

📄 **[示例输出论文 (PDF)](docs/sample_paper.pdf)** — 由 ARI 完全自主生成的真实论文，包含图表、引用和可复现性验证报告。主要数据请参阅[已验证的结果](#已验证的结果)。

<details>
<summary><b>📖 点击展开论文（滚动浏览全部 11 页）</b></summary>

<p align="center">
  <img src="docs/images/sample_paper/page-01.png" alt="示例论文 — 第 1 页" width="720"/>
  <img src="docs/images/sample_paper/page-02.png" alt="示例论文 — 第 2 页" width="720"/>
  <img src="docs/images/sample_paper/page-03.png" alt="示例论文 — 第 3 页" width="720"/>
  <img src="docs/images/sample_paper/page-04.png" alt="示例论文 — 第 4 页" width="720"/>
  <img src="docs/images/sample_paper/page-05.png" alt="示例论文 — 第 5 页" width="720"/>
  <img src="docs/images/sample_paper/page-06.png" alt="示例论文 — 第 6 页" width="720"/>
  <img src="docs/images/sample_paper/page-07.png" alt="示例论文 — 第 7 页" width="720"/>
  <img src="docs/images/sample_paper/page-08.png" alt="示例论文 — 第 8 页" width="720"/>
  <img src="docs/images/sample_paper/page-09.png" alt="示例论文 — 第 9 页" width="720"/>
  <img src="docs/images/sample_paper/page-10.png" alt="示例论文 — 第 10 页" width="720"/>
  <img src="docs/images/sample_paper/page-11.png" alt="示例论文 — 第 11 页" width="720"/>
</p>

</details>

---

## ARI 做什么

```
experiment.md  ──►  ARI Core  ──►  结果 + 论文 + 可复现性报告
                       │
          ┌────────────┼──────────────────────────────┐
          │            │                              │
     BFTS Engine    ReAct Loop            Post-BFTS Pipeline
   (最佳优先         (单节点 agent)        (workflow.yaml 驱动)
    树搜索)              │
                    MCP Skill Servers
                    (插件系统 — 在此添加任何能力)
```

1. **你描述目标。** 编写一个实验文件。ARI 读取它，生成假设，运行实验，并报告结果。
2. **在假设空间上的 BFTS。** 最佳优先树搜索（BFTS）引导探索 — 由证据驱动，而非穷举。
3. **确定性工具，推理 LLM。** MCP 技能是纯函数。LLM 进行推理；技能执行操作。
4. **从论文到证明。** ARI 撰写论文，*并且* 通过可复现性检查验证自己的主张。

---

## 面向扩展的设计 — 走向物理世界

ARI 的 MCP 插件架构有意设计为超越计算的能力扩展：

```
今天（计算）:
  ari-skill-hpc        → SLURM 任务提交
  ari-skill-evaluator  → 从 stdout 提取指标
  ari-skill-paper      → LaTeX 论文写作

明天（物理世界）:
  ari-skill-robot      → 通过 ROS2 MCP 桥接的机械臂控制
  ari-skill-sensor     → 温度/压力传感器读取
  ari-skill-labware    → 移液器控制、酶标仪集成
  ari-skill-camera     → 计算机视觉实验观测
```

添加这些功能 **无需修改 ari-core**。编写带有 `@mcp.tool()` 函数的 `server.py`，在 `workflow.yaml` 中注册即可完成。

---

## 快速开始

```bash
# 1. 安装
git clone https://github.com/kotama7/ARI && cd ARI
bash setup.sh

# 2. 设置 AI 模型（任选其一）
ollama pull qwen3:8b                          # 免费、本地
export ARI_BACKEND=openai OPENAI_API_KEY=sk-… # 或云端 API

# 3. 启动仪表板
ari viz ./checkpoints/ --port 8765
# 打开 http://localhost:8765 → 使用实验向导创建并启动实验
```

或直接通过 CLI 运行：
```bash
ari run experiment.md                 # 运行实验
ari run experiment.md --profile hpc   # 使用 SLURM 集群
```

完整的仪表板演练请参阅 **[docs/zh/quickstart.md](docs/zh/quickstart.md)**，CLI 命令请参阅 **[docs/zh/cli_reference.md](docs/zh/cli_reference.md)**。

---

## 实验文件 — 两个层次

**新手（3 行）:**
```markdown
# 矩阵乘法优化
## Research Goal
最大化此机器上 DGEMM 的 GFLOPS。
<!-- metric_keyword: GFLOPS -->
```

**专家（完整控制）:**
```markdown
# 蛋白质折叠力场扫描
## Research Goal
最小化 AMBER 力场变体的能量分数。
## SLURM Script Template
```bash
#!/bin/bash
#SBATCH --nodes=4 --ntasks-per-node=32 --time=02:00:00
module load gromacs/2024
gmx mdrun -v -deffnm simulation -ntmpi 32
```
## Rules
- HARD LIMIT: 永不超过 128 个 MPI 任务
- 在 slurm_submit 中始终使用 work_dir=/abs/path
<!-- metric_keyword: energy_score -->
<!-- min_expected_metric: -500 -->
```
```

---

## Web 仪表板（主要界面）

用于可视化实验管理的 9 页 React/TypeScript SPA。启动方式：

```bash
ari viz ./checkpoints/ --port 8765   # http://localhost:8765
```

| 页面 | 功能 |
|------|----------|
| **Home** | 快捷操作、最近的实验、系统状态 |
| **New Experiment** | 4 步向导：聊天/编写/上传目标 → 范围（深度、节点、工作进程）→ 资源（LLM、HPC）→ 启动 |
| **Experiments** | 列出/删除/恢复所有检查点项目，显示状态和审稿评分 |
| **Monitor** | 实时阶段步进器（Idle → Idea → BFTS → Paper → Review）、实时日志流（SSE）、成本追踪 |
| **Tree** | 交互式 BFTS 节点树，点击任意节点查看指标、工具调用追踪、生成代码和输出 |
| **Results** | 查看/下载论文（PDF/TeX）、审稿报告、可复现性结果、生成的图表 |
| **Ideas** | VirSci 生成的假设，包含新颖性/可行性评分和差距分析 |
| **Workflow** | 编辑 BFTS 后流水线阶段（依赖、启用/禁用、输入/输出） |
| **Settings** | LLM 提供商/模型、API 密钥（基于 .env）、SLURM 分区自动检测、SSH 远程测试、Ollama 主机 |

通过 WebSocket（树变更）和 SSE（日志流）实现实时更新。所有数据按项目隔离。

### Dashboard API

仪表板暴露了一个 REST + WebSocket API，也可以通过编程方式使用：

| 端点 | 方法 | 用途 |
|----------|--------|---------|
| `/state` | GET | 完整实验状态（阶段、节点、配置、成本） |
| `/api/launch` | POST | 使用完整配置启动新实验 |
| `/api/run-stage` | POST | 运行特定阶段（resume / paper / review） |
| `/api/checkpoints` | GET | 列出所有检查点项目 |
| `/api/settings` | GET/POST | 读写 LLM、SLURM 和 API 密钥设置 |
| `/api/workflow` | GET/POST | 读写 workflow.yaml 流水线 |
| `/api/chat-goal` | POST | 用于实验目标精炼的多轮 LLM 聊天 |
| `/api/upload` | POST | 上传 experiment.md 或数据文件 |
| `/api/stop` | POST | 优雅地停止运行中的实验 |
| `/api/logs` | GET (SSE) | 流式实时日志和成本数据 |
| `/memory/<node_id>` | GET | 检索节点内存（工具调用追踪） |
| `ws://host:{port+1}/ws` | WebSocket | 订阅实时树更新 |

---

## CLI 命令

仪表板的所有功能也可通过命令行使用：

| 命令 | 描述 |
|---------|-------------|
| `ari run <experiment.md>` | 运行新实验（BFTS + 论文流水线） |
| `ari resume <checkpoint_dir>` | 从检查点恢复 |
| `ari paper <checkpoint_dir>` | 仅运行论文流水线（跳过 BFTS） |
| `ari status <checkpoint_dir>` | 显示节点树和摘要 |
| `ari projects` | 列出所有实验运行 |
| `ari show <checkpoint>` | 详细结果（树 + 审稿报告） |
| `ari delete <checkpoint>` | 删除检查点 |
| `ari settings` | 查看/修改配置（模型、分区等） |
| `ari skills-list` | 列出所有可用的 MCP 工具 |
| `ari viz <checkpoint_dir>` | 启动 Web 仪表板 |

### 输出文件

运行完成后，输出保存在 `./checkpoints/<run_id>/`：

| 文件 | 描述 |
|------|-------------|
| `tree.json` | 完整的 BFTS 节点树（所有节点、指标、父子链接） |
| `results.json` | 每个节点的产物、指标和状态 |
| `idea.json` | VirSci 生成的假设和差距分析 |
| `science_data.json` | 面向科学的数据（无内部 BFTS 术语） |
| `full_paper.tex` / `.pdf` | 生成的 LaTeX 论文和编译后的 PDF |
| `review_report.json` | 自动同行评审评分和反馈 |
| `reproducibility_report.json` | 独立的可复现性验证 |
| `figures_manifest.json` | 生成的图表路径和标题 |
| `cost_trace.jsonl` | 每次调用的 LLM 成本追踪 |
| `experiments/<slug>/<node_id>/` | 每个节点的工作目录和生成代码 |

---


## 架构

### 技能（MCP 插件服务器）

共 14 个技能。其中 9 个在 `workflow.yaml` 中默认注册；另外 5 个可以通过添加到配置中启用。

| 技能 | 角色 | LLM? | 默认 |
|---|---|---|---|
| `ari-skill-hpc` | SLURM 提交 / 轮询 / Singularity / bash | ✗ | ✓ |
| `ari-skill-evaluator` | 从实验文件中提取指标 | △ | ✓ |
| `ari-skill-idea` | arXiv 调研 + VirSci 假设生成 | ✓ | ✓ |
| `ari-skill-web` | DuckDuckGo、arXiv、Semantic Scholar、迭代引用收集 | △ | ✓ |
| `ari-skill-memory` | 祖先作用域的节点内存（JSONL） | ✗ | ✓ |
| `ari-skill-transform` | BFTS 树 → 面向科学的数据格式 | ✓ | ✓ |
| `ari-skill-plot` | Matplotlib/seaborn 图表生成 | ✓ | ✓ |
| `ari-skill-paper` | LaTeX 写作 + BibTeX + 评审 | ✓ | ✓ |
| `ari-skill-paper-re` | ReAct 可复现性验证 | ✓ | ✓ |
| `ari-skill-coding` | 代码生成 + 执行 + bash | ✗ | — |
| `ari-skill-benchmark` | CSV/JSON 分析、绘图、统计检验 | ✗ | — |
| `ari-skill-review` | 同行评审解析、反驳生成 | ✓ | — |
| `ari-skill-vlm` | 视觉-语言模型图表/表格审阅 | ✓ | — |
| `ari-skill-orchestrator` | 将 ARI 作为 MCP 服务器暴露给外部 agent | ✗ | — |

✗ = 不使用 LLM，△ = 仅部分工具使用 LLM，✓ = 主要工具使用 LLM。

### 设计原则

| # | 原则 | 含义 |
|---|-----------|---------|
| P1 | 领域无关的核心 | `ari-core` 不包含任何实验特定知识 |
| P2 | 尽可能确定性 | MCP 工具默认是确定性的；使用 LLM 的工具明确标注 |
| P3 | 多目标指标 | 没有硬编码的标量评分 |
| P4 | 依赖注入 | 切换实验 = 仅编辑 `.md` |
| P5 | 可复现性优先 | 论文用规格而非集群名称描述硬件 |

---

## 已验证的结果

ARI 在多核 CPU 上对 **CSR SpMM**（稀疏矩阵与稠密矩阵乘积）进行了端到端的自主研究，包括设计、实现、运行和论文撰写。完整论文（含方法、算法、图表和参考文献）可在 [`docs/sample_paper.pdf`](docs/sample_paper.pdf) 中查看。

> **Stoch-Loopline: Burstiness- and Tail-Latency-Aware Loopline Modeling for Robust Multi-Core CPU CSR SpMM Scaling**

| 配置 | GFLOP/s | 有效带宽 |
|---|---|---|
| K 分块 CSR SpMM（峰值吞吐量） | 23.82 | 58.30 GB/s |
| 验证扫描（峰值，*N* = 16，32 线程） | **26.22** | **65.55 GB/s** |
| 最高测量带宽（root 扫描） | 17.17 | **105.18 GB/s** |
| 软件预取增益（按宽度平均） | **+3.53** | **+8.18 GB/s** |

**硬件:** `fx700` 多核 CPU 节点，OpenMP，32 线程。合成 CSR 矩阵最大规模 *M* = *K* = 200,000（约 3.2M 非零元素），行长分布包含 uniform 与 Zipf，稠密宽度 *N* ∈ {4, 8, 16, 32, 64, 128}。

**ARI 自主完成的工作：** Stoch-Loopline 建模框架、两种 CSR×dense 核函数实现（行并行 gather 与 rows-in-flight）以及显式的循环展开/窗口参数、K 分块 / N 平铺 + 打包 / scalar / no-AVX 消融实验、实验扫描、图表、参考文献和可复现性验证 — 全部由 ARI 端到端自主生成，无需人工干预。

---

## 许可证

MIT。请参阅 [LICENSE](./LICENSE)。
