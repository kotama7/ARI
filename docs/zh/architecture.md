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
    规范驱动审稿。运行 N 个独立审稿人代理
    (N 由 ARI_NUM_REVIEWS_ENSEMBLE / rubric 默认值控制；N=1 为单审稿人)。
    N>1 时还会运行 Area Chair 元审稿以聚合评分。
    输出：review_report.json { score, verdict, citation_ok, feedback,
          ensemble_reviews[] (N>1), meta_review{} (N>1) }

  阶段 7：reproducibility_check  (ari-skill-paper-re + react_driver)  [在阶段 5 之后]
    pre_tool  (paper-re.extract_repro_config)
        从论文抽取作者宣传的结果
        { metric_name, claimed_value, description, threads }
    react_driver  (ari-core/ari/agent/react_driver.py)
        只驱动 phase=reproduce 已加入的 MCP 技能 (web / vlm / hpc / coding)
        构成的 ReAct 循环。memory-skill / transform-skill / evaluator-skill
        被刻意排除，智能体无法访问 BFTS 阶段的产物 (nodes_tree.json、
        祖先记忆等)。沙箱限定在 {{checkpoint_dir}}/repro_sandbox 内。
    post_tool (paper-re.build_repro_report)
        比较实测值与声称值，输出裁决和解释。
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
├── review_report.json          # LLM 同行评审输出 (N>1 时内联 ensemble_reviews[] 和 meta_review{})
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
├── memory_backup.jsonl.gz   # Letta 快照（流水线阶段结束和退出时自动）
├── memory_access.jsonl       # 写/读遥测
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
| `ari-skill-memory` | `add_memory`、`search_memory`、`get_node_memory`、`clear_node_memory`、`get_experiment_context` | 祖先作用域的节点记忆（Letta 后端） | △ |
| `ari-skill-idea` | `survey`、`generate_ideas` | 文献搜索（Semantic Scholar）+ VirSci 多智能体假设生成 | ✓ |
| `ari-skill-evaluator` | `make_metric_spec` | 从实验文件提取指标规格 | △ |
| `ari-skill-transform` | `nodes_to_science_data` | BFTS 树 → 面向科学的数据（剥离内部字段） | ✓ |
| `ari-skill-web` | `web_search`、`fetch_url`、`search_arxiv`、`search_semantic_scholar`、`collect_references_iterative` | 网络搜索、arXiv、Semantic Scholar、迭代式引用收集 | △ |
| `ari-skill-plot` | `generate_figures`、`generate_figures_llm` | 确定性 + LLM 图表生成（按图通过 `kind` 字段选择 matplotlib 绘图或 SVG 图） | ✓ |
| `ari-skill-paper` | `list_venues`、`get_template`、`generate_section`、`compile_paper`、`check_format`、`review_section`、`revise_section`、`write_paper_iterative`、`review_compiled_paper`、`list_rubrics` | LaTeX 论文撰写、编译、基于评审规范的同行评审 (兼容 AI Scientist v1/v2)。`review_compiled_paper` 通过集成路径运行 N 名独立审稿人；当 N>1 时还会在内部运行 Area Chair 元审稿。 | ✓ |
| `ari-skill-paper-re` | `extract_repro_config`、`build_repro_report`、`extract_metric_from_output` | 可复现性 ReAct 的确定性 pre/post 端点 (循环本体位于 `ari-core/ari/agent/react_driver.py`) | ✓ |
| `ari-skill-benchmark` | `analyze_results`、`plot`、`statistical_test` | CSV/JSON/NPY 分析、绘图、scipy 统计（BFTS analyze 阶段使用） | ✗ |
| `ari-skill-vlm` | `review_figure`、`review_table` | VLM 驱动的图表/表格审查（驱动 VLM 审查循环） | ✓ |
| `ari-skill-coding` | `write_code`、`run_code`、`read_file`、`run_bash` | 代码生成 + 执行 + 分页文件读取 | ✗ |

**附加技能**（可用，不在默认工作流中）：

| 技能 | 工具 | 角色 | LLM? |
|------|------|------|------|
| `ari-skill-orchestrator` | `run_experiment`、`get_status`、`list_runs`、`list_children`、`get_paper` | 将 ARI 作为 MCP 服务器暴露，递归子实验，双 stdio+HTTP 传输 | ✗ |

✗ = 无 LLM、△ = 仅部分工具使用 LLM、✓ = 主要工具使用 LLM。13 个技能（12 默认，1 附加）。

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

## 流水线驱动的 ReAct (react_driver)

BFTS 自带的 ReAct 循环(`ari.agent.AgentLoop`，与 `Node` 树紧耦合)之外，还有一个轻量 ReAct 驱动 `ari.agent.react_driver.run_react`，面向无需 BFTS 上下文的 ReAct 智能体。当 stage 声明 `react:` 块时，由 `ari.pipeline._run_react_stage` 调用；目前被 `reproducibility_check` 使用。

```
pipeline.py ──▶ pre_tool (MCP)  → 声称的配置
             ─▶ react_driver.run_react
                   ├─ phase 过滤：MCPClient.list_tools(phase="reproduce")
                   ├─ 对每个工具调用的参数执行沙箱校验
                   └─ 智能体调用 `final_tool` 即终止
             ─▶ post_tool (MCP) → 裁决 + 解释
```

关键特性：

- **Phase 白名单**：`workflow.yaml` 中 `skills[].phase` 可以是单个字符串或数组。只有 phase 列表包含 stage `react.agent_phase` 的技能才能被智能体看到。默认 `workflow.yaml` 将 `web-skill` / `vlm-skill` / `hpc-skill` / `coding-skill` 加入 `reproduce`；`memory-skill` / `transform-skill` / `evaluator-skill` 被刻意排除，智能体无法观测 BFTS 状态(`nodes_tree.json`、祖先记忆、science data)。
- **沙箱**：`react.sandbox` 指向一个目录(默认 `{{checkpoint_dir}}/repro_sandbox/`)。工具参数会被扫描绝对路径和 `..` 穿越，沙箱外的路径(论文 `.tex` 的 allow-list 除外)会在抵达 MCP 之前被拒绝并返回 `sandbox violation`。MCP 服务器 fork 之前会将 `ARI_WORK_DIR` 设置为沙箱目录，所以 `coding-skill.run_bash` 的默认 cwd 也会在沙箱内。
- **终止条件**：智能体调用 `react.final_tool`(默认 `report_metric`)结束循环。该调用不会转发给 MCP，而是被驱动捕获，其参数成为传递给 stage `post_tool` 的 `actual_value` / `actual_unit` / `actual_notes`。

这一分离使 `reproduce_from_paper` 式 stage 的"仅读论文文本"约束能从 YAML 审计，而不是埋在技能 Python 里。

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

### v0.6.0：基于 Letta

两个层级共存于每个检查点的同一个 Letta 代理中：

- `ari_node_<ckpt_hash>` — 节点作用域的 archival 集合，使用上述祖先作用域元数据过滤器。
- `ari_react_<ckpt_hash>` — 每个检查点的扁平 ReAct 轨迹（`LettaMemoryClient`，不做祖先过滤）。

代理还会向核心记忆块（`persona` + `human` + `ari_context`）种入实验目标、主要指标和硬件规格 ── 时机为首个节点的 `generate_ideas` 完成时（即 `primary_metric` 被确定的时刻）。技能可通过 `get_experiment_context()` 读取，无需付出搜索成本；在 seed 执行之前调用会返回 `{}`。

**Copy-on-Write**：写端工具拒绝 `node_id` ≠ `$ARI_CURRENT_NODE_ID` 的写入，因此祖先条目在兄弟节点之间保持字节稳定；出于同样的原因，Letta 自编辑默认禁用。

**可移植性**：每个检查点都携带 `memory_backup.jsonl.gz` 快照，在 `ari resume` 时若目标 Letta 为空将自动恢复 ── 让 `cp -r checkpoints/foo /elsewhere/` + `ari resume` 持续可用。

---

## 节点级提示构建

每个 BFTS 节点都通过 `ari/agent/loop.py:370` 中的 `AgentLoop.run(node, experiment)` 这一单一入口执行。同一循环既处理根节点也处理子节点；它构建的提示仅根据 `node.depth` 和从祖先继承的状态分支。本节是 *代理在节点开始时实际看到什么* 的权威来源。在此处更改需要谨慎审查。

### `AgentLoop.run` 的输入

每次调用接收两个参数：

1. **`node: Node`** — 由 `BFTS.expand`（`ari/orchestrator/bfts.py:431-441`）创建。影响提示的字段：
   - `id`、`depth`、`label`（`draft|improve|debug|ablation|validation|other`）、`raw_label`
   - `ancestor_ids` — 从根到父节点（含父节点）的严格 CoW 链，用作 `search_memory` 过滤器。
   - `eval_summary` — 对于刚扩展的子节点，此字段保存 LLM 提议的方向（一句话）。执行后该字段会被评估器摘要覆盖。
   - `memory_snapshot` — 父节点快照的副本；当前提示构建器未使用，但会持久化到 `tree.json`。
2. **`experiment: dict`** — 调度器按节点组装：
   - `goal` — 整个 `experiment.md` 文本（运行级别，所有节点相同）
   - `work_dir` — `PathManager` 创建的节点专属目录
   - `slurm_partition`、`slurm_max_cpus` — SLURM 启用时由 `env_detect` 填充

### 系统提示 — `ari/agent/loop.py:41-58`

```
You are a research agent. You MUST use tools to execute experiments. ...

AVAILABLE TOOLS:
{tool_desc}                ← 当前阶段枚举的 MCP 工具

RULES:
- Your FIRST action must be a tool call ...
- If `make_metric_spec` is available and this is a new experiment ...
- NEVER fabricate numeric values ...
- When all experiments are done, return JSON {...}
- Do NOT call gap_analysis or generate_hypothesis
- Ensure your experiment is reproducible: ...
{memory_rules}{extra}
```

`{extra}` 块（在 L448-453 构建）追加：

| 子块 | 来源 | 备注 |
|------|------|------|
| `NODE ROLE: {label_hint}` | `node.label.system_hint()` | 由 BFTS 标签衍生的一句话行为提示 |
| `EXPERIMENT ENVIRONMENT` | L433-442 | `work_dir` + 已有文件 + SLURM partition/CPUs + 容器镜像（`ARI_CONTAINER_IMAGE`） |
| `RESOURCE BUDGET` | L443-447 | `max_react_steps`、`timeout_per_node // 60` 分钟 |
| `extra_system_prompt` | `WorkflowHints.extra_system_prompt` | 由 `from_experiment_text` / 流水线配置可选设置的逃生口 |

`{memory_rules}` 块（L454-456）仅在代理实际拥有 `add_memory` 工具时附加，并将活跃节点 id 内联到提示中，使 LLM 无法意外写入其他作用域：

```
- When available, save decisive intermediate findings with
  add_memory(node_id="<本节点的 id>", text=..., metadata=...)
- Use search_memory(query=..., ancestor_ids=[...], limit=5) ...
```

### 工具目录（`tool_desc`）

L389 的 `tools = self._available_tools_openai(suppress=..., phase="bfts")` 枚举 MCP 为 `phase="bfts"` 暴露的所有工具，然后丢弃 `_suppress_tools` 中的任何工具。可变的 suppression 集合存在于 `AgentLoop` 实例上，并随运行进展更新：

- 第一次成功的 `generate_ideas` 调用之后，循环设置 `self._suppress_tools = {"generate_ideas"}`（L873-874），后续节点不再重新生成 idea。
- `survey` 对子节点 **不被 suppress**；仅在文字中被劝阻（见下文「User message #1 — 子节点」）。忽略文字劝阻的子仍然可以调用 `survey()`。

`_PINNED_TOOLS = {"survey", "generate_ideas", "make_metric_spec"}`（L613）标记消息窗口修剪器必须保留的工具结果；即使聊天历史被压缩，它们的内容也会在每个 ReAct 轮次存活。

### User message #1 — 根节点（`node.depth == 0`）

`loop.py:501-511`:

```
Experiment goal:
{goal_text(截断到 1500 字符)}

Node: {node.id} depth={node.depth}

START NOW: call {first_tool}() immediately. Do NOT output any text or
plan — your first response must be a {first_tool}() tool call.

IMPORTANT: After make_metric_spec, call survey() to search related
literature. The survey results will be used to generate citations in
the paper. Without survey, the paper will have no references.
```

`first_tool` 是 `WorkflowHints.tool_sequence[0]`，当对应技能存在时，`enrich_hints_from_mcp` 默认顺序为 `make_metric_spec` → `survey` → `generate_ideas` → executor。

### User message #1 — 子节点（`node.depth > 0`）

`loop.py:477-500`:

```
Experiment goal:
{goal_text(截断到 1500 字符)}

Node: {node.id} depth={node.depth} task={node.label}

Task: {label-specific one-line description from _label_desc}
The parent node already completed the survey and established a research
direction. Prior results are provided below. Implement and run your
specific experiment, then return JSON with measurements.

Workflow:
{WorkflowHints.post_survey_hint}        ← 例如：slurm_submit / run_bash 步骤
```

`_label_desc`（L479-485）是节点级提示中标签语义出现的唯一位置：

| Label | 一行任务 |
|-------|---------|
| `improve` | Improve performance or accuracy beyond what the parent achieved. |
| `ablation` | Ablation study: remove or vary one component from the parent approach. |
| `validation` | Validate the parent result under different conditions or parameters. |
| `debug` | The parent experiment had issues. Diagnose and fix them. |
| `draft` | Try a new implementation approach for the same goal. |
| *(other / unknown)* | Extend or vary the parent experiment. |

注意 `node.eval_summary`（BFTS 扩展器 LLM 为该子节点提议的具体方向）**不会逐字写入此提示**。子节点只看到通用标签任务；提议的方向通过下方的先验知识记忆搜索间接传达给代理。

### User message #2 — 先验知识（仅子节点）

`loop.py:522-549`。当 `node.depth > 0` 且 `node.ancestor_ids` 非空时，循环调用：

```python
search_memory(
    query        = (node.eval_summary or self.experiment_goal or "experiment result")[:200],
    ancestor_ids = node.ancestor_ids,
    limit        = 5,
)
```

然后追加一条 user 消息：

```
[Prior knowledge from ancestor nodes (N entries):]
{join(entry.text for entry in results)[:800]}
```

三个上限是硬编码的：

| 上限 | 值 | 位置 |
|-----|---|------|
| 查询长度 | 200 字符 | L528 |
| 条目数 | 5 | L532 |
| 拼接后内容 | 800 字符 | L545 |

失败（记忆后端宕机、结果格式异常等）在 `logger.debug` 级别被吞掉，节点仍然运行。

遗留的 `search_global_memory` 注入块（L551-574）在 v0.6.0 中是死代码；全局记忆工具已被移除（`CHANGELOG.md` v0.6.0 §3），条件分支永不触发。

### 截断速查表

| 项目 | 上限 | 代码 |
|------|-----|------|
| `goal_text` | 1500 字符 | `loop.py:469-474` |
| Survey 结果记忆条目 | 前 5 篇论文，每篇 abstract 200 字符 | `loop.py:830-833` |
| 先验知识查询 | 200 字符 | `loop.py:528` |
| 先验知识条目 | relevance 前 5 名 | `loop.py:532` |
| 先验知识拼接 | 800 字符 | `loop.py:545` |

### 故意 **不注入** 的信息

以下信息可达但绝不会自动添加到提示中；如果代理需要，必须自己调用相关工具：

- **`get_experiment_context()` 载荷**（`experiment_goal`、`primary_metric`、`hardware_spec`、`metric_rationale`、`higher_is_better`）。在首次 `generate_ideas` 调用后种入；可通过 MCP 工具读取，但不会粘贴到任何提示块。
- **子节点的 `node.eval_summary` 方向文本**。持久化在 Node 对象上，BFTS 扩展/评估可见，但子代理的 user prompt 中不出现。
- **`memory_snapshot`**。从父节点带入子 Node，但提示构建器不消费；保留供未来使用。
- **兄弟节点 metrics**。提议子节点时 `BFTS.expand`（即 *扩展器 LLM*）可见，但该子节点的 *执行代理* 看不到。

### CoW 桥接 — 与记忆技能保持同步

在 LLM 往返开始之前，`loop.py:378-381` 发出：

```python
self.mcp.call_tool("_set_current_node", {"node_id": node.id})
```

这是 `ari-skill-memory` 暴露的内部工具；它更新池化技能子进程内的 `$ARI_CURRENT_NODE_ID`，使任何后续 `add_memory(node_id=...)` 调用可以针对活跃节点进行 CoW 验证。代理永远看不到此工具 ── 它被 `_INTERNAL_MCP_TOOLS` 从 `tool_desc` 中过滤。

### Soft 强制 vs Hard 强制

代理看似遵守的某些「规则」在代码中被严格强制，其他则仅由提示文字控制。在调试代理意外行为时，知道哪个属于哪种很重要：

| 规则 | 强制方式 |
|-----|---------|
| 不能为其他节点写记忆 | **Hard** — 后端拒绝 `node_id` ≠ `$ARI_CURRENT_NODE_ID` |
| 不能读取兄弟记忆 | **Hard** — `search_memory` 按 `ancestor_ids` 过滤 |
| `generate_ideas` 最多调用一次 | **Hard** — 首次后 `_suppress_tools` 排除 |
| 子节点不应调用 `survey` | **Soft** — 仅文字（"parent already completed the survey"）；工具仍在 `tool_desc` 中 |
| 子节点应实现而非计划 | **Soft** — 仅文字；依赖系统提示的 `RULES` 块 |
| 资源预算 | 提示中的 **Soft 提示** + 循环中的 **Hard** timeout / step cap |

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
