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
  - LLM 提议 2-3 个子方向（改进 / 消融 / 验证）
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
    LLM 生成的关键词 → Semantic Scholar API
    输出：related_refs.json

  阶段 3：generate_figures  (ari-skill-plot)  [在阶段 1 之后]
    输入：完整的 science_data.json（包含 experiment_context）
    LLM 编写完整的 matplotlib 代码 → 执行 → 保存为 PDF 图表
    图表类型由 LLM 根据数据自主选择（非预设）
    输出：figures_manifest.json

  阶段 4：write_paper  (ari-skill-paper)  [在阶段 2、3 之后]
    paper_context = experiment_context + best_nodes_metrics
    迭代式章节撰写：草稿 → LLM 审阅 → 修改（最多 2 轮）
    BibTeX 引用来自 Semantic Scholar 结果
    输出：full_paper.tex、refs.bib

  阶段 5：review_paper  (ari-skill-paper)  [在阶段 4 之后]
    PDF → pdftotext → LLM 整体审阅
    输出：review_report.json { score, verdict, citation_ok, feedback }

  阶段 6：reproducibility_check  (ari-skill-paper-re)  [在阶段 4 之后]
    读取论文 → 提取配置 → 运行 HPC 作业 → 比较声称值与实际值
    输出：reproducibility_report.json { verdict, claimed, actual, tolerance_pct }
```

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

| 技能 | 工具 | 角色 |
|------|------|------|
| `ari-skill-hpc` | `run_bash`、`slurm_submit`、`job_status`、`read_output` | 代码执行 / HPC 作业管理 |
| `ari-skill-memory` | `add_memory`、`search_memory`、`get_node_memory` | 祖先链实验记忆 |
| `ari-skill-idea` | `survey`、`generate_ideas`、`make_metric_spec` | 文献搜索 + 假设生成（VirSci） |
| `ari-skill-evaluator` | `make_metric_spec` | 指标规格生成（领域无关） |
| `ari-skill-transform` | `nodes_to_science_data` | LLM 驱动的完整树分析 → science_data.json |
| `ari-skill-web` | `search_semantic_scholar` | 学术文献搜索 |
| `ari-skill-plot` | `generate_figures_llm` | LLM 编写 matplotlib → PDF 图表 |
| `ari-skill-paper` | `write_paper_iterative`、`review_compiled_paper` | LaTeX 论文撰写 + 同行评审 |
| `ari-skill-paper-re` | `reproduce_from_paper` | 可复现性验证智能体 |

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
