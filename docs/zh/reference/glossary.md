---
sources:
  - path: ari-core/ari/orchestrator/bfts.py
    role: implementation
  - path: ari-core/ari/evaluator/llm_evaluator.py
    role: implementation
  - path: ari-core/ari/memory/letta_client.py
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
  - path: ari-core/config/reviewer_rubrics
    role: config
  - path: ari-skill-replicate
    role: implementation
  - path: ari-skill-paper-re
    role: implementation
last_verified: 2026-05-26
---

# 术语表

ARI 文档中反复出现的术语的简短定义，每条都指向完整解释该术语的文档。术语按其所属的子系统分组。

## 搜索与编排

**BFTS (Best-First Tree Search，最佳优先树搜索)**
ARI 的实验搜索循环。它探索一棵实验配置的树，始终优先扩展最有希望的已完成节点。实现于
`ari/orchestrator/bfts.py`。参见 [BFTS 算法](../concepts/bfts.md)。

**pending**
BFTS 两个池之一：已从父节点扩展、准备运行但尚未执行的节点。参见 [BFTS 算法](../concepts/bfts.md)。

**frontier (前沿)**
BFTS 的另一个池：等待扩展的已完成节点。前沿是*持久的* —— 一个节点在产生子节点后仍保持可用以供再次扩展，直到它被退役。参见 [BFTS 算法](../concepts/bfts.md)。

**retire (退役一个前沿节点)**
将一个已完成节点从后续扩展中移除。节点在以下情况下退役：**规则 A**
（某个子节点在 `_scientific_score` 上超过它）或 **规则 B**（它已被扩展
`max_expansions_per_node` 次）。参见 [BFTS 算法](../concepts/bfts.md)。

**node label (节点标签)**
BFTS 节点相对于其父节点所扮演的角色：`draft`、`improve`、`debug`、
`ablation`、`validation` 或 `other`。未知标签会归并为 `other`，而
`raw_label` 保留原始字符串。参见 [BFTS 算法](../concepts/bfts.md)。

**diversity bonus (多样性奖励)**
对代表性不足的节点标签（跟踪最近 20 次运行）施加的 `+0.05` 分数微调，使搜索不会坍塌到单一策略上。参见
[BFTS 算法](../concepts/bfts.md)。

**sterile (不育节点)**
执行后其 `work_dir` 与父节点字节完全一致的子节点
（sha256 差异中 `added = modified = deleted = 0`）。它会被标记为
`_sterile = True`，评分为 `0.0` 并被剪枝 —— 这正是阻止子节点在不实际运行任何东西的情况下"继承"父节点结果的机制。参见
[架构 → work_dir 继承](../concepts/architecture.md#work_dir-inheritance--output-artifact-blacklist-v070--phase-7)。

**should_prune**
BFTS 中的硬性截断谓词：当 `current_total ≥ max_total_nodes`、
`depth ≥ max_depth` 或 `_sterile is True` 时剪枝。此处不掺入任何 LLM 判断。参见
[BFTS 算法](../concepts/bfts.md)。

## 评估

**scientific_score / `_scientific_score`**
`LLMEvaluator` 分配给每个节点的同行评审质量分数（0.0–1.0）。存储于
`metrics["_scientific_score"]`，它驱动 BFTS 排名、谱系决策和最佳节点选择。参见
[配置 → BFTS 评估层](configuration.md#bfts-evaluation-layers-configurable)。

**composite formula (复合公式)**
如何将各维度的分数归约为单个标量：`harmonic_mean`（默认）、
`arithmetic_mean`、`weighted_min` 或 `geometric_mean`。可通过
`evaluator.composite` 配置。参见
[配置 → BFTS 评估层](configuration.md#bfts-evaluation-layers-configurable)。

**plan (计划)**
一次运行的*评估细节* —— 测量哪些指标、对比哪些基线、运行哪些消融。来源于
`idea.json[0].experiment_plan`。默认情况下子实验不继承它
（子节点编写自己的计划，因此它们可以自由调整方向）。参见
[架构 → Plan / Venue 契约](../concepts/architecture.md#plan--venue-contract-v070)。

**venue (会场)**
一次运行的*评判标准* —— 评分哪些维度以及如何评分。一个 venue 是
由 `ARI_RUBRIC` 选定的 `ari-core/config/reviewer_rubrics/<id>.yaml` 文件。
切换 venue 会同时改变 BFTS 的评分维度和发表评审的标准。参见
[架构 → Plan / Venue 契约](../concepts/architecture.md#plan--venue-contract-v070)。

**rubric (评分准则)**
一份评分规范。ARI 在两种语境下使用这个词：**reviewer rubric**
（上面的 venue YAML）用于论文评审，以及 **ORS rubric**（一棵 PaperBench
`TaskNode` 树）用于可复现性评分。参见
[Rubric 模式](rubric_schema.md)。

**lineage decision (谱系决策)**
当复合分数停滞时，一个 BFTS 钩子会请求 LLM 选择
`continue` / `switch_to_idea` / `fanout` / `terminate`。参见
[架构 → Plan / Venue 契约](../concepts/architecture.md#plan--venue-contract-v070)。

## 内存

**ancestor scope (祖先范围)**
节点只能从其祖先链（root → parent）读取内存、绝不能从兄弟节点读取的规则。由
`search_memory` 上的元数据过滤器强制执行。参见
[内存架构](../concepts/memory.md)。

**CoW (Copy-on-Write，写时复制)**
使祖先内存在各兄弟节点间保持字节稳定的写入保护：写入侧工具会拒绝任何不等于当前活跃
`$ARI_CURRENT_NODE_ID` 的 `node_id`。参见 [内存架构](../concepts/memory.md)。

**Letta**
自 v0.6.0 起使用的内存后端（前身为 MemGPT）。每个检查点都获得一个专属的代理，持有两个集合：`ari_node_<hash>`（祖先范围的归档）和 `ari_react_<hash>`（扁平 ReAct 轨迹）。参见
[内存架构](../concepts/memory.md)。

## 代理与技能

**ReAct loop (ReAct 循环)**
每节点的代理循环（`ari/agent/loop.py`），它将 LLM 推理与 MCP 工具调用交织在一起以运行一次实验。参见
[架构 → 每节点提示组合](../concepts/architecture.md#per-node-prompt-composition)。

**MCP skill (MCP 技能)**
打包为 Model Context Protocol 服务器的一项能力（例如 `ari-skill-hpc`）。技能只能从 `ari.public.*` 导入。共有 14 个（13 个默认 + 1 个额外）。参见 [MCP 技能](skills.md)。

**VirSci**
将研究目标转化为假说和主要指标的多代理审议，在根节点通过 `generate_ideas` 运行一次。参见
[架构](../concepts/architecture.md#full-data-flow)。

## 状态与发表

**checkpoint (检查点)**
一次运行的自包含目录，`{workspace}/checkpoints/{run_id}/`，其中 `run_id` 为
`YYYYMMDDHHMMSS_<slug>`。所有状态都存于此处；`PathManager`
（`ari/paths.py`）是唯一的事实来源。API 密钥从不存储于此 —— 它们来自 `.env` 或环境变量。参见
[架构 → 文件结构](../concepts/architecture.md#file-structure)。

**EAR (Experiment Artifact Repository，实验产物仓库)**
随论文一同交付的、确定性构建的 `ear/` 包（代码、输入数据、图表、README、
`reproduce.sh`、LICENSE）。实验*输出*被刻意排除在外。参见 [发表生命周期](../concepts/publication-lifecycle.md)。

## 可复现性 (ORS / PaperBench)

**ORS**
ARI 的可复现性检查 —— 一个确定性的、PaperBench 兼容的两阶段流程，它重新运行论文并对其评分。在 v0.7.0 中取代了旧的 LLM 评判路径。参见 [PaperBench 快速入门](../guides/paperbench/paperbench_quickstart.md)。

**TaskNode**
PaperBench 格式 rubric 树中的一个节点。从论文生成的 ORS rubric 是一棵带权重的
`TaskNode` 树，并使用封闭的 `task_category` 词汇表。参见 [Rubric 模式](rubric_schema.md)。

**Phase 1 / Phase 2 (阶段 1 / 阶段 2)**
ORS 的两个阶段：**Phase 1**（`run_reproduce`）在沙箱中执行 `reproduce.sh`
（`slurm` → `docker` → `apptainer` → `singularity` → `local`）；**Phase 2**
（`grade_with_simplejudge`）对 rubric 叶节点运行 PaperBench SimpleJudge。
参见 [PaperBench API](api_paperbench.md)。

**negative control (阴性对照)**
一项 ORS 防护措施：一个空仓库 + 一个无关紧要的 `reproduce.sh` 必须得分低于 5%，以证明 rubric 不会奖励无所作为。参见
[PaperBench API](api_paperbench.md)。

**bridge stage (bridge 阶段)**
v0.8.0 PaperBench bridge 的三个 vendor 协议入口点之一：
`rollout_submission`（代理生成一份提交）、`reproduce_submission`
（执行它）和 `judge_submission`（对其评分）。参见
[PaperBench API](api_paperbench.md)。

**paper-audit mode (论文审计模式)**
对 ORS rubric 机制的一种反向使用（v0.7.2），它审计一篇论文*本身*是否描述得足够充分以可复现，并以一个 venue 模板（`sc` / `neurips` / `nature`）为条件。参见 [Rubric 模式](rubric_schema.md)。

---

另请参阅：[架构](../concepts/architecture.md) ·
[BFTS 算法](../concepts/bfts.md) ·
[内存架构](../concepts/memory.md) ·
[配置](configuration.md)
