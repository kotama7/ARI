# ARI 架构

## ARI 做什么

ARI 是一个端到端的自主研究系统。给定一个纯文本研究目标，它会：

1. **调研**先前的工作（学术数据库）
2. **生成**研究假设，通过多智能体讨论（VirSci）
3. **搜索**最佳实验配置，使用最佳优先树搜索（BFTS）
4. **执行**真实实验，在您的硬件上运行（笔记本电脑、SLURM、PBS、LSF）
5. **评估**每个实验，以同行评审者的角色（LLM 分配科学质量评分）
6. **分析**完整的实验树：提取硬件上下文、方法论、消融实验发现
7. **生成**出版级质量的图表（LLM 根据数据编写 matplotlib 代码）
8. **撰写**完整的 LaTeX 论文及引用
9. **审阅**论文，LLM 充当审稿人
10. **验证**可复现性：仅根据论文文本重新运行实验

系统不包含硬编码的领域知识。同一流水线适用于 HPC 基准测试、ML 超参数调优、化学优化或任何可测量的现象。

---

## 系统概览

```
┌────────────────────────────────────────────────────────────────┐
│                         User Interface                         │
│                   experiment.md  /  CLI  /  API                │
└────────────────────────────────┬───────────────────────────────┘
                             │
┌────────────────────────────▼───────────────────────────────────┐
│                          ari-core                              │
│                                                                │
│  ┌─────────────────┐   ┌─────────────────┐                    │
│  │  BFTS           │   │  ReAct Loop     │                    │
│  │  (tree search)  │──▶│  (per node)     │                    │
│  └─────────────────┘   └────────┬────────┘                    │
│                                 │                              │
│  ┌──────────────────────────────▼──────────────────────────┐  │
│  │            MCP Client (async tool dispatcher)           │  │
│  └──────────────────────────────┬──────────────────────────┘  │
└─────────────────────────────────┼──────────────────────────────┘
                                  │ MCP protocol (stdio/HTTP)
     ┌────────────────────────────┼──────────────────────────────┐
     │                            │                              │
┌────▼──────────┐  ┌─────────────▼──────┐  ┌───────────────────▼──┐
│ari-skill-hpc  │  │ari-skill-idea      │  │ari-skill-evaluator   │
│ slurm_submit  │  │ survey             │  │ make_metric_spec     │
│ job_status    │  │ generate_ideas     │  │ (scientific_score)   │
│ run_bash      │  │ (VirSci MCP)       │  │                      │
└───────────────┘  └────────────────────┘  └──────────────────────┘

Post-BFTS Pipeline (workflow.yaml):
┌─────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ari-skill-       │  │ari-skill-plot    │  │ari-skill-paper   │
│transform        │  │ generate_figures │  │ write_paper      │
│ nodes_to_       │  │ _llm (LLM writes │  │ review_compiled  │
│ science_data    │  │  matplotlib)     │  │ reproduce_from   │
│ (LLM analysis)  │  │                  │  │  _paper          │
└─────────────────┘  └──────────────────┘  └──────────────────┘
```

---

## 完整数据流

```
experiment.md
  (仅包含研究目标 — 最少 3 行)
    │
    ▼
[ari-skill-idea: survey]
  arXiv / Semantic Scholar 关键词搜索
  返回：相关论文摘要
    │
    ▼
[ari-skill-idea: generate_ideas]  ← VirSci 多智能体讨论
  多个 AI 角色就研究问题进行辩论
  输出：hypothesis、primary_metric、evaluation_criteria
    │
    ▼
BFTS 根节点创建
    │
    ▼ (对每个节点重复，最多 ARI_MAX_NODES 个，ARI_PARALLEL 个并发)
┌──────────────────────────────────────────────────────────────────┐
│  ReAct Loop (ari/agent/loop.py)                                  │
│                                                                  │
│  1. LLM 从 MCP 注册表中选择工具                                    │
│  2. 工具执行（run_bash / slurm_submit / job_status / ...）         │
│  3. 如果是 SLURM 作业：自动轮询直到 COMPLETED（无步骤预算限制）       │
│  4. LLM 读取 stdout → 生成实验代码 → 提交                          │
│  5. LLM 从输出中提取指标 → 返回 JSON                               │
│                                                                  │
│  记忆：结果摘要保存到祖先链记忆中                                    │
│  子节点：搜索祖先记忆以获取先前结果                                  │
└──────────────────────────────────────────────────────────────────┘
    │
    ▼
[LLMEvaluator] (ari/evaluator/llm_evaluator.py)
  输入：节点产物（stdout、日志、脚本）
  输出：{
    has_real_data: bool,
    metrics: {key: value, ...},       ← 提取的数值
    scientific_score: float 0.0-1.0,  ← LLM 同行评审质量分
    comparison_found: bool             ← 是否与现有方法进行了比较？
  }
  _scientific_score 存储在 metrics 中 → 驱动 BFTS 排名
    │
    ▼
BFTS expand() (ari/orchestrator/bfts.py)
  - 按 _scientific_score 对节点排名
  - 将分数传递给子节点提议 LLM
  - LLM 每次扩展调用提议 1 个子方向（改进 / 消融 / 验证 / 草稿 / 调试 / 其他）
  - 无领域提示 — LLM 决定"改进"的含义
    │
    ▼ (达到 ARI_MAX_NODES 后)
nodes_tree.json  (所有节点：指标、产物、记忆、父子关系)
    │
    ▼
[workflow.yaml Post-BFTS 流水线]

  阶段 1：transform_data  (ari-skill-transform)
    对完整树进行 BFS 遍历（根 → 叶）
    LLM 读取所有节点产物（stdout、日志、生成的代码）
    LLM 提取：硬件规格、方法论、关键发现、比较结果
    输出：science_data.json  { configurations, experiment_context, per_key_summary }

  阶段 2：search_related_work  (ari-skill-web)  [与阶段 1 并行]
    LLM 生成的关键词 → 可插拔检索后端 (Semantic Scholar / AlphaXiv / both)
    输出：related_refs.json

  阶段 3：generate_figures  (ari-skill-plot)  [在阶段 1 之后]
    输入：完整的 science_data.json（包含 experiment_context）+ {{vlm_feedback}}
    LLM 编写完整的 matplotlib 代码 → 执行 → 保存为 PDF 图表
    图表类型由 LLM 根据数据自主选择（非预设）
    输出：figures_manifest.json

  阶段 3b：vlm_review_figures  (ari-skill-vlm)  [在阶段 3 之后]
    VLM 视觉审阅主图 (fig_1.png)
    若得分 < 0.7：携带 VLM 反馈回环到 generate_figures（最多 2 次迭代）
    输出：vlm_figure_review.json

  阶段 4：generate_ear  (ari-skill-transform)  [在阶段 1 之后]
    构建 Experiment Artifact Repository：代码、数据、日志、可重现性元数据
    输出：ear_manifest.json、ear/ 目录

  阶段 5：write_paper  (ari-skill-paper)  [在阶段 2、3、4 之后]
    paper_context = experiment_context + best_nodes_metrics
    迭代式章节撰写：草稿 → LLM 审阅 → 修改（最多 2 轮）
    BibTeX 引用来自 Semantic Scholar 结果
    输出：full_paper.tex、refs.bib

  阶段 6：review_paper  (ari-skill-paper)  [在阶段 5 之后]
    PDF → pdftotext → LLM 整体审阅
    输出：review_report.json { score, verdict, citation_ok, feedback }

  阶段 7：respond_to_review  (ari-skill-review)  [在阶段 6 之后]
    解析评审顾虑 → 生成逐点反驳
    输出：rebuttal.json

  阶段 8：reproducibility_check  (ari-skill-paper-re)  [在阶段 5 之后]
    读取论文 → 提取配置 → 运行 HPC 作业 → 比较声称值与实际值
    输出：reproducibility_report.json { verdict, claimed, actual, tolerance_pct }
```

---

## 文件结构

### 检查点目录布局

每次 ARI 运行都会在 `{workspace}/checkpoints/{run_id}/` 下生成检查点目录。
`run_id` 格式为 `YYYYMMDDHHMMSS_<slug>`。`ari/paths.py` 中的 `PathManager`
是目录构造的唯一真实来源。

```
checkpoints/{run_id}/
├── experiment.md               # 输入: 研究目标 (启动时复制)
├── launch_config.json          # 向导/CLI 启动参数
├── meta.json                   # 子实验元数据 (父/递归深度)
├── workflow.yaml               # 启动时流水线配置的快照
├── .ari_pid                    # 用于存活检测的 PID 文件
├── tree.json                   # 完整 BFTS 树 (BFTS 阶段写入)
├── nodes_tree.json             # 轻量树导出 (流水线输入)
├── results.json                # 每节点 artifact + metrics 摘要
├── idea.json                   # 生成的假设 (VirSci 输出)
├── evaluation_criteria.json    # 主要指标 + 方向
├── cost_trace.jsonl            # 每次 LLM 调用的成本/token 日志
├── cost_summary.json           # 成本汇总
├── ari.log                     # 结构化 JSON 日志
├── ari_run_*.log               # GUI 启动时的 stdout/stderr 日志
├── .pipeline_started           # 标记: post-BFTS 流水线已开始
├── science_data.json           # Transform-skill 输出
├── related_refs.json           # 文献搜索结果
├── figures_manifest.json       # 生成的图片元数据
├── fig_*.{pdf,png,eps,svg}     # 生成的图片
├── vlm_review.json             # VLM 图片审查输出
├── full_paper.tex              # 生成的 LaTeX 论文
├── refs.bib                    # BibTeX 引用
├── full_paper.pdf              # 编译后的 PDF
├── full_paper.bbl              # 参考文献输出
├── review_report.json          # LLM 同行评审输出
├── rebuttal.json               # 逐点反驳
├── reproducibility_report.json # 可复现性验证
├── uploads/                    # 用户上传的文件 (复制到节点 work_dir)
├── paper/                      # LaTeX 编辑工作区 (类 Overleaf)
│   ├── full_paper.tex
│   ├── full_paper.pdf
│   ├── refs.bib
│   └── figures/
├── ear/                        # 实验 Artifact Repository
│   ├── README.md
│   ├── RESULTS.md
│   └── <artifacts>
└── repro/                      # 可复现性运行工作区
    ├── run/
    ├── reproducibility_report.json
    └── repro_output.log
```

### 节点工作目录

每节点的工作目录作为 `checkpoints/` 的兄弟目录创建:

```
{workspace}/experiments/{slug}/{node_id}/
```

在节点执行时，`_run_loop` 将以下用户文件复制到每个节点的 work_dir:
- **Provided files**: `experiment.md` 中 `## Provided Files` (`## 提供ファイル` / `## 提供文件`) 下列出的路径
- **检查点根**: 检查点目录中的非 meta 文件
- **uploads 子目录**: `checkpoint/uploads/` 中的非 meta 文件

`PathManager.META_FILES` 定义了绝不能复制到节点 work_dir 的文件
(`experiment.md`, `tree.json`, `nodes_tree.json`, `launch_config.json`, `meta.json`,
`results.json`, `idea.json`, `cost_trace.jsonl`, `cost_summary.json`, `workflow.yaml`,
`ari.log`, `evaluation_criteria.json`, `.ari_pid`, `.pipeline_started`)。
扩展名为 `.log` 的文件也视为 meta。

### tree.json 和 nodes_tree.json

两个文件都包含 BFTS 节点树，但在生命周期的不同阶段写入:

| 文件              | 写入方                                                | 阶段             | 模式                                                  |
|-------------------|-------------------------------------------------------|------------------|-------------------------------------------------------|
| `tree.json`       | `cli.py` 中的 `_save_checkpoint()`                    | BFTS 阶段        | `{run_id, experiment_file, created_at, nodes}`        |
| `nodes_tree.json` | `_save_checkpoint()` + `generate_paper_section()`     | BFTS + post-BFTS | `{experiment_goal, nodes}` (轻量)                     |

**读取方约定**: 所有读取方必须优先使用 `tree.json` 并回退到 `nodes_tree.json`。
这可确保 BFTS 期间获得最新数据，同时保持与预期 `nodes_tree.json` 的流水线阶段的兼容性。

### 项目级状态 (每个检查点)

ARI 不再维护全局配置目录。所有设置文件和代理记忆都存储在活动检查点目录下，
因此每个实验拥有独立状态，`~/.ari/` 可以安全删除:

```
checkpoints/{run_id}/
├── settings.json        # GUI 设置 (LLM 模型、提供者、HPC 默认值)
├── memory.json          # FileMemoryClient 存储 (祖先链)
├── memory_store.jsonl   # ari-skill-memory MCP 服务条目
└── ...                  # tree.json / launch_config.json / uploads / ari.log
```

API 密钥 **绝不** 存储在 `settings.json` 中。它们从 `.env` 文件
(搜索顺序: checkpoint → ARI root → ari-core → home) 或启动时注入的环境变量中读取。

---

## 模块参考

### ari-core

| 模块 | 描述 |
|------|------|
| `ari/orchestrator/bfts.py` | 最佳优先树搜索 — 节点扩展、选择、剪枝；按 `_scientific_score` 排名 |
| `ari/orchestrator/node.py` | Node 数据类 — id、parent_id、depth、label、metrics、artifacts、memory |
| `ari/agent/loop.py` | ReAct 智能体循环 — 每个节点的 LLM + 工具调用；自动轮询 SLURM 作业；注入祖先记忆 |
| `ari/agent/workflow.py` | WorkflowHints — 从实验文本自动提取（工具序列、指标关键词、分区） |
| `ari/pipeline.py` | Post-BFTS 流水线驱动器 — 模板解析、阶段执行、输出连接 |
| `ari/evaluator/llm_evaluator.py` | 指标提取 + 同行评审评分（`scientific_score`、`comparison_found`） |
| `ari/memory/file_client.py` | 基于文件的记忆客户端（祖先链作用域） |
| `ari/mcp/client.py` | 异步 MCP 客户端 — 线程安全，为并行执行创建新的事件循环 |
| `ari/llm/client.py` | 通过 litellm 进行 LLM 路由（Ollama、OpenAI、Anthropic、任何 OpenAI 兼容接口） |
| `ari/config.py` | 配置数据类（BFTSConfig、LLMConfig、PipelineConfig） |
| `ari/core.py` | 顶层运行时构建器 — 连接所有组件 |
| `ari/cli.py` | CLI：`ari run`、`ari paper`、`ari status` |

### 技能（MCP 服务器）

**默认技能**（在 `workflow.yaml` 中注册）：

| 技能 | 工具 | 角色 | LLM? |
|------|------|------|------|
| `ari-skill-hpc` | `slurm_submit`、`job_status`、`job_cancel`、`run_bash`、`singularity_build`、`singularity_run`、`singularity_pull`、`singularity_build_fakeroot`、`singularity_run_gpu` | HPC 作业管理 + Singularity 容器 | ✗ |
| `ari-skill-memory` | `add_memory`、`search_memory`、`get_node_memory`、`clear_node_memory` | 祖先链实验记忆（JSONL） | ✗ |
| `ari-skill-idea` | `survey`、`generate_ideas` | 文献搜索（Semantic Scholar）+ VirSci 多智能体假设生成 | ✓ |
| `ari-skill-evaluator` | `make_metric_spec` | 从实验文件提取指标规格 | △ |
| `ari-skill-transform` | `nodes_to_science_data` | BFTS 树 → 面向科学的数据（剥离内部字段） | ✓ |
| `ari-skill-web` | `web_search`、`fetch_url`、`search_arxiv`、`search_semantic_scholar`、`collect_references_iterative` | 网络搜索、arXiv、Semantic Scholar、迭代式引用收集 | △ |
| `ari-skill-plot` | `generate_figures`、`generate_figures_llm` | 确定性 + LLM 驱动的 matplotlib 图表生成 | ✓ |
| `ari-skill-paper` | `list_venues`、`get_template`、`generate_section`、`compile_paper`、`check_format`、`review_section`、`revise_section`、`write_paper_iterative`、`review_compiled_paper` | LaTeX 论文撰写、编译、同行评审 | ✓ |
| `ari-skill-paper-re` | `extract_metric_from_output`、`reproduce_from_paper` | ReAct 可复现性验证智能体 | ✓ |
| `ari-skill-figure-router` | （图表类型分类） | 图表类型分类和生成路由（SVG/matplotlib/LaTeX） | ✓ |
| `ari-skill-benchmark` | `analyze_results`、`plot`、`statistical_test` | CSV/JSON/NPY 分析、绘图、scipy 统计（BFTS analyze 阶段使用） | ✗ |
| `ari-skill-review` | `parse_review`、`generate_rebuttal`、`check_rebuttal` | 同行评审解析 + 反驳生成 | ✓ |
| `ari-skill-vlm` | `review_figure`、`review_table` | VLM 驱动的图表/表格审查（驱动 VLM 审查循环） | ✓ |
| `ari-skill-coding` | `write_code`、`run_code`、`read_file`、`run_bash` | 代码生成 + 执行 + 分页文件读取 | ✗ |

**附加技能**（可用，不在默认工作流中）：

| 技能 | 工具 | 角色 | LLM? |
|------|------|------|------|
| `ari-skill-orchestrator` | `run_experiment`、`get_status`、`list_runs`、`list_children`、`get_paper` | 将 ARI 作为 MCP 服务器暴露，递归子实验，双 stdio+HTTP 传输 | ✗ |

✗ = 无 LLM、△ = 仅部分工具使用 LLM、✓ = 主要工具使用 LLM。15 个技能（14 默认，1 附加）。

---

## BFTS 算法

ARI 实现了真正的最佳优先树搜索，采用双池设计：

- **`pending`**：准备运行的节点（已从父节点扩展）
- **`frontier`**：已完成但尚未扩展的节点

```python
def bfts(experiment, config):
    root = Node(experiment, depth=0)
    pending = [root]      # nodes ready to execute
    frontier = []         # completed nodes awaiting expansion
    all_nodes = [root]

    while len(all_nodes) < config.max_total_nodes:

        # --- BFTS STEP 1: expand the best frontier node ---
        # LLM reads metrics of all completed nodes and selects
        # the most promising one to expand (not all at once)
        while frontier and len(pending) < max_parallel:
            best = llm_select_best_to_expand(frontier)  # by _scientific_score
            frontier.remove(best)
            children = llm_propose_directions(best)     # improve/ablation/validation
            pending.extend(children)
            all_nodes.extend(children)

        # --- BFTS STEP 2: run a batch of pending nodes ---
        batch = llm_select_next_nodes(pending, max_parallel)
        results = parallel_run(batch)

        for node in results:
            memory.write(node.eval_summary)   # save to ancestor-chain memory
            if node.status == SUCCESS:
                frontier.append(node)         # will expand when selected
            else:
                frontier.append(node)         # failed → expand with "debug" children

    return max(all_nodes, key=lambda n: n.metrics.get("_scientific_score", 0))
```

关键特性：
- **惰性扩展**：已完成的节点不会立即扩展，而是等到 LLM 选择它 — 低分节点可能无限期等待
- **不重试**：失败的节点通过 `expand()` 产生 `debug` 子节点，而非重新执行
- **严格预算**：`len(all_nodes) < max_total_nodes` 防止超额
- **`generate_ideas` 仅调用一次**：在根节点之后被抑制以防止循环

### 节点标签

| 标签 | 含义 |
|------|------|
| `draft` | 从头开始的新实现 |
| `improve` | 调优父节点的参数或算法 |
| `debug` | 修复父节点的失败 |
| `ablation` | 移除一个组件以衡量其影响 |
| `validation` | 在不同条件下重新运行父节点 |

---

## 记忆架构

每个节点仅从其祖先链中读取：

```
root ──▶ memory["root"]
  ├─ node_A ──▶ memory["node_A"]
  │    ├─ node_A1  (读取：root + node_A)
  │    └─ node_A2  (读取：root + node_A，不读取 node_A1)
  └─ node_B  (仅读取 root，不读取 node_A 分支)
```

`search_memory` 查询 = 节点自身的 `eval_summary` 文本（而非领域关键词）。
这确保了检索到的记忆与当前节点的工作在语义上相关。

---

## 设计不变量

ARI 的生产代码包含**零领域知识**。所有领域决策都在运行时委托给 LLM。

| 决策 | 由谁决定 |
|------|----------|
| 哪些指标重要 | LLM 评估器 |
| 与什么进行比较 | LLM 评估器（`comparison_found`） |
| 运行什么实验 | ReAct 智能体（LLM） |
| 使用了什么硬件 | Transform 技能 LLM（从产物中读取 lscpu 等信息） |
| 绘制什么图表 | Plot 技能 LLM |
| 从树中提取什么 | Transform 技能 LLM |
| 如何对节点排名 | LLM 分配的 `_scientific_score` |
| 使用什么引用关键词 | LLM 从节点摘要中生成 |
| 是否收集环境/设置信息 | ReAct 智能体 LLM（由系统提示中的可复现性原则引导） |

---

## 扩展 ARI

要添加新功能，请创建一个新的 MCP 技能：

```bash
mkdir ari-skill-myskill/src
# Implement server.py with FastMCP tools
# Register in workflow.yaml skills section
```

```yaml
# workflow.yaml
skills:
  - name: myskill
    path: "{{ari_root}}/ari-skill-myskill"

pipeline:
  - stage: my_stage
    skill: myskill
    tool: my_tool
    inputs:
      data: "{{ckpt}}/science_data.json"
```

无需修改 `ari-core`。
