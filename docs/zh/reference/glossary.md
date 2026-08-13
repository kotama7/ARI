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
  - path: ari-core/ari/pipeline/claim_gate
    role: implementation
  - path: ari-core/ari/pipeline/verified_context.py
    role: implementation
  - path: ari-skill-memory
    role: implementation
  - path: ari-core/ari/rqgm
    role: implementation
  - path: ari-core/ari/viz/v1/launch.py
    role: implementation
  - path: ari-core/ari/viz/v1/queries.py
    role: implementation
  - path: ari-core/ari/viz/api_orchestrator.py
    role: implementation
  - path: ari-core/ari/cli/run.py
    role: implementation
  - path: ari-core/config/profiles
    role: config
last_verified: 2026-08-13
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
执行后相对父节点没有任何改动的子节点。当 pin 定的 problem 声明了 `score_inputs` 时，
不育性由这些文件的 sha256 比较判定；否则回退到整个 `work_dir` 的差异
（`added = modified = deleted = 0`；不复制父 `work_dir` 时为 `added = modified = 0`）。
两条路径都会把节点标记为 `_sterile = True` 并剪枝，且不育的子节点绝不会让父节点退役；
整个 `work_dir` 这条路径还会把 `_scientific_score` 钳制为 `0.0`、`has_real_data` 钳制为
`False`，而 `score_inputs` 这条路径则保留已测得的分数、`has_real_data` 与
`evaluation_status`。这正是阻止子节点在不实际运行任何东西的情况下"继承"父节点结果的机制。参见
[架构 → work_dir 继承](../concepts/architecture.md#work_dir-inheritance--output-artifact-blacklist-v070--phase-7)。

**should_prune**
BFTS 中的硬性截断谓词：当 `current_total ≥ max_total_nodes`、
`depth ≥ max_depth`、`_sterile is True` 或 `_valid_for_frontier is False`
（RQGM 选择性擦除）时剪枝。此处不掺入任何 LLM 判断。参见
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
一次运行的*评判标准* —— 评分哪些维度以及如何评分。一个 venue 是一份
`ari-core/config/reviewer_rubrics/<id>.yaml` 文件。有两个彼此独立的选择器：
`ARI_RUBRIC`（默认 `neurips`）决定 BFTS 的评分维度，`workflow.yaml` 的顶层
`paper_rubric` 键（默认 `generic_conference`）作为显式 `rubric_id` 传给评审
阶段。若要让同一个 venue 同时驱动打分与评审，请将两者设为同一个 id。参见
[架构 → Plan / Venue 契约](../concepts/architecture.md#plan--venue-contract-v070)。

**rubric (评分准则)**
一份评分规范。ARI 在两种语境下使用这个词：**reviewer rubric**
（上面的 venue YAML）用于论文评审，以及 **ORS rubric**（一棵 PaperBench
`TaskNode` 树）用于可复现性评分。参见
[Rubric 模式](rubric_schema.md)。

**lineage decision (谱系决策)**
当复合分数停滞时，一个 BFTS 钩子会*首先*以确定性方式，通过 `switch_to_idea`
转向最强的*未使用*次优想法 —— 这样次优想法会被真正尝试，而不是未经使用便被搁置。
LLM 评判器（它从 `continue` / `switch_to_idea` / `fanout` / `terminate` 中选择）
仅作为回退被征询 —— 当预算耗尽、达到递归上限，或没有剩余的未使用备选时。参见
[架构 → Plan / Venue 契约](../concepts/architecture.md#plan--venue-contract-v070)。

**claim-evidence gate (主张-证据门)**
一个确定性的、不使用 LLM 的门（`claim_evidence_hard_gate`）。它在容差范围内从记录的结果
重新推导论文中报告的每个数字，并检查数值覆盖率 / 操作数解析 / 图表存在性。默认在 `warn`
模式下启用，该模式只在 FINAL 阶段阻断 objective-integrity 的 `always_block_on` 层
（invariant 违反、correctness 失败或未覆盖、ceiling 未测量、recompute 不可复现、
跨 run 或未绑定的 evidence）；设置 `claim_gate_policy.mode: strict`（或
`ARI_CLAIM_GATE_MODE=strict`）可额外阻断配置的 `block_on` 所见以及 strict 小节中
未覆盖的结果数字。draft 阶段的报告从不阻断。当 `comparison_scope`
为 `any`（默认）时，跨环境比较被视为透明性警告；为 `same_environment` 时，它会成为阻断性
错误。参见 [配置](configuration.md)。

## 内存

**ancestor scope (祖先范围)**
节点只能从其祖先链（root → parent）读取内存、绝不能从兄弟节点读取的规则。
`search_memory` 会拒绝签名谱系之外的任何 id，后端还会按 `node_id ∈ ancestor_ids`
做元数据过滤。参见
[内存架构](../concepts/memory.md)。

**CoW (Copy-on-Write，写时复制)**
使祖先内存在各兄弟节点间保持字节稳定的写入保护：写入侧工具会拒绝任何不等于调用所携带的
签名 `NodeContextV1` 自身节点的 `node_id`。环境变量 `$ARI_CURRENT_NODE_ID` 不具备任何权限。
参见 [内存架构](../concepts/memory.md)。

**Letta**
自 v0.6.0 起使用的内存后端（前身为 MemGPT）。每个检查点都获得一个专属的代理，持有两个集合：`ari_node_<hash>`（祖先范围的归档）和 `ari_react_<hash>`（扁平 ReAct 轨迹）。参见
[内存架构](../concepts/memory.md)。

**verified context / verifiable research memory (已验证上下文 / 可验证研究内存)**
构建于 Letta 之上的一个带类型、带 sha256 来源的层。在节点结束时，`node_report.json` 会被
整合为带类型、带来源的记录（`experiment_result` / `failure_case` / `reflection`）；随后
论文流水线据此推导出一个以产物为依据的 `verified_context.json`（范围限定为最佳节点的
root→best 谱系），从而将论文主张接地到实际测量到的内容上。通过 `ARI_MEMORY_CONSOLIDATE`
默认启用。参见 [可验证研究内存](../concepts/verifiable_research_memory.md)。

## 代理与技能

**ReAct loop (ReAct 循环)**
每节点的代理循环（`ari/agent/loop.py`），它将 LLM 推理与 MCP 工具调用交织在一起以运行一次实验。参见
[架构 → 每节点提示组合](../concepts/architecture.md#per-node-prompt-composition)。

**MCP skill (MCP 技能)**
打包为 Model Context Protocol 服务器的一项能力（例如 `ari-skill-hpc`）。技能只能从 `ari.public.*` 导入。`ari-skill-*` 包共有 17 个，随附的 `workflow.yaml` 显式列出了其中 13 个。参见 [MCP 技能](skills.md)。

**VirSci**
将研究目标转化为假说和主要指标的多代理审议，在根节点通过 `generate_ideas` 运行一次。参见
[架构](../concepts/architecture.md#full-data-flow)。

## RQGM（可选启用的宪法治理）

专属于可选启用的 `ari_rqgm` 执行模式的术语。它们对默认运行一概不
适用。参见[执行模式](../guides/execution_modes.md)与
[RQGM 评估](../guides/rqgm_evaluation.md)。

**simple_bfts / ari_rqgm（执行模式）**
`ari.mode` 的两个取值。`simple_bfts`（默认）就是当前的 ARI，行为
不变 —— 它不构造任何 RQGM 对象、不导入任何 `ari.rqgm` 模块。
`ari_rqgm` 选择启用纪元治理，且还需要 `rqgm.enabled: true` 联锁；
任何不一致都带着警告安全回退到 `simple_bfts`
（`ari/rqgm/mode.py`）。参见
[执行模式](../guides/execution_modes.md)。

**epoch（纪元）**
一次 `ari_rqgm` 运行的治理时间片。每产生
`rqgm.epoch.nodes_per_epoch` 个新 BFTS 节点（默认 10；`<= 0` 使
运行停留在 `epoch_000`）就触发一次边界事务。治理、注册表转换和
重放池准入只发生在这些边界上。

**EpochState**
每纪元对活跃提示词/组件集合与效用策略的不可变冻结
（`ari/rqgm/state.py`，快照到 `epoch_state.json`）。在纪元持续期间
被冻结，指纹不含挂钟字段，因此之后的注册表变化绝不会泄漏进一个
已关闭的纪元。

**utility policy hash（效用策略哈希）**
对纪元效用策略正文 —
`{composite, axis_weights, frontier_score, depth_penalty_lambda, ucb_c}` —
计算的 `hash12(canonical_json(body))`（`ari/rqgm/state.py` 的
`utility_policy_body` / `seal_utility_policy`）。这枚封印从不属于它所封印的
字节，同一个值也是已注册 `utility_policy` 条目的 `prompt_hash`。另有一份
互不相交的策略 —— 由 `ari/rqgm/adversarial/engine.py` 计算的惩罚策略
`{penalty_cap, severity_weights, verdict_factors}` —— 在受治效用工作之前
写下的记录里使用同一个键名；两者的键集合从不重叠，因此两个哈希绝不会相等。
在不同哈希下形成的分数不构成同一个序列。

**ConstitutionalKernel（宪法内核）**
不进化的第 0 层检查器（`ari/rqgm/kernel.py`）：一个纯粹、确定性的
校验器，返回逐字节稳定的 `KernelReport` 裁定且不写任何东西。
严重度冻结在代码中（`kernel_rules.py`），绝不可配置；只有姿态
（`rqgm.kernel.enforcement`：`standard` / `audit_only`）和浮点容差
在配置里。

**GovernanceOrchestrator（治理编排器）**
唯一的纪元边界治理入口（`ari/rqgm/governance/`）：对将关闭纪元的
证据收集、检控、辩护和裁决，并由 ConstitutionalKernel 自我审计。
预算与姿态位于 `rqgm.governance` / `rqgm.replay` 之下。

**RegistryTransitionEngine（注册表转换引擎）**
注册表状态的唯一写入方（`ari/rqgm/transition_engine.py`）。它把
一个治理结果变成通过 RQGM 存储持久化的已提交 `EpochTransition`
（激活 / 退役）；任何其他组件都不得更改提示词或组件的状态。

**registry status（注册表状态）**
提示词与组件共享的 10 值生命周期（`ari.rqgm.events.STATUS_VALUES`，
一个封闭集合）：`candidate`、`validated`、`shadow`、`probationary_active`、
`active`、`warning`、`probation`、`quarantine`、`retired`、`banned`。
`active` 与 `probationary_active` 共同构成每纪元被冻结的活跃集合。参见
[RQGM GUI 读模型](rqgm_gui_read_models.md)的「两套词汇表，两台状态机」一节。

**transition rule id（转换规则 ID，`T1`–`T21`）**
每一次注册表状态变更都会 pin 定 `ari/rqgm/transition_rules.py` 中转换表的
一行，该行由 `T1` 到 `T21` 的 `rule_id` 命名。表中不存在的边，或与表相矛盾的
`rule_id` 声明，都是 ConstitutionalKernel 违规。紧急 quarantine 的边是另一个
集合 `EMERGENCY_EDGE`。参见 [RQGM schema](rqgm_schemas.md)的
「转换 schema（Task 09）」一节。

**FrontierRepairEngine（前沿修复引擎）**
在带退役的转换之后于纪元边界运行
（`ari/rqgm/frontier_repair.py`）：追踪实质依赖已退役
`prompt_hash` 的记录，把它们标记为过期（仅逻辑 —— 什么都不
删除），重算幸存者，并确定性地重建 BFTS 前沿。

**node score state（节点分数状态）**
针对节点分数的另一套 5 值词汇 —— `computed`、`recomputed`、`stale`、
`invalidated`、`removed` —— 它与 **registry status** 是不同的状态机，绝不可
混入同一个字段或同一个图例。这五个都是*逻辑*状态：没有任何一个意味着节点
的文件被物理删除，「Deleted」对其中任何一个都不是合法标签。其依据是节点的
指标哨兵 `_stale`、`_stale_reason`、`_valid_for_frontier` 与
`_erasure_event_id`（`ari/rqgm/frontier_repair.py`）。参见
[RQGM GUI 读模型](rqgm_gui_read_models.md)的「两套词汇表，两台状态机」一节。

**ProposalRecord / ProposalSummaryView**
`ProposalRecord` 是一条归档提案（追加式
`{checkpoint}/proposals/proposal_records.jsonl`）；
`ProposalSummaryView` 是从它派生的有界摘要 —— BFTS 所见的**唯一**
形状（`ari/rqgm/proposals/records.py`）。`ProposalRouter` 在
`proposal_router.*` 预算下把生成分派给生成器注册表；VirSci 生成器
为可选启用且默认关闭。

**PromptSpec**
一个带版本的提示词身份（`ari/rqgm/prompt_spec.py`）。不可变：
任何更改都是新的 `prompt_id` + `prompt_hash`，绝不是编辑。进化后
的模板正文以一次写入方式存放在 `{checkpoint}/rqgm_prompts/` 下。

**RawAttackRecord（原始攻击）**
一次未经裁决的 adversary 攻击，id 为 `atk_*`
（`ari/rqgm/adversarial/records.py`）。它只是审计日志素材：不会被读入任何
分数。它经裁决后的后代就是下面的 ValidatedAttackRecord，因此原始攻击的
计数与惩罚是两个不同的量，不得共用同一个标签。

**ValidatedAttackRecord**
一条在裁决中幸存的对抗发现 —— 只对裁定
`valid` / `partially_valid` 存在，带有 `vat_*` 的 id
（`ari/rqgm/adversarial/records.py`），
且是唯一可被重放池准入的攻击形状。

**UtilityRecord**
一条受治效用审计记录，id 为 `utl_*`，追加写入
`rqgm_adversarial_cases.jsonl`（`ari/rqgm/adversarial/records.py`）：一个
节点的 base / penalty / final 分数，并把它所依据的策略*按值*一并存下，
因此日后的重算无需查询注册表。节点自身则保留对应的指标哨兵
`_pre_penalty_score` / `_validated_attack_penalty`。参见
[RQGM GUI 读模型](rqgm_gui_read_models.md)的「两条得分改写通道」一节。

**AdversarialReplayPool（对抗重放池）**
经裁决的失败案例的策展池
（`ari/rqgm/adversarial/pool.py`），快照到
`{checkpoint}/rqgm/adversarial_replay_pool.json`；追加式真相是
`rqgm_adversarial_cases.jsonl`。准入只发生在纪元边界；容量配置在
`rqgm.adversarial.pool.*` 下。

**selective erasure（选择性擦除）**
对由已退役提示词产生 —— 或实质依赖它 —— 的记录的仅逻辑失效。
什么都不物理删除或重写：过期状态存在于 `SelectiveErasureEvent` /
`FrontierRebuildEvent` 审计日志行和派生的
`rqgm_erasure_state.json` 汇总中，读取方在读取时推导 `stale`。

**clean-room regeneration（洁净室再生成）**
在无法访问已退役提示词文本的情况下起草其替代提示词
（`ari/rqgm/clean_room.py`，`CleanRoomCoordinator`）。对候选准入
fail-closed，对运行 fail-open：任何违规时该角色回退到其已提交的
基线模板，循环继续。

**meta tier（元层）**
三个注册表层级（`fixed` / `institutional` / `meta`）中最高的一
个。元层治理组件可以进化，但其权限不能扩张：能力标志默认拒绝，
并对照 `ari/rqgm/meta_rules.py` 中冻结的权限表检查。

## 配置与启动

**project（项目）**
GUI 的顶层实体，而且是同类中唯一的一个：`GET /api/v1/projects` 恰好返回
一个 id 为 `default` 的虚拟项目（`ari/viz/v1/queries.py` 中的
`DEFAULT_PROJECT_ID`），其 run 列表是对各检查点搜索基址的目录扫描。任何
其他 id 都会得到一个类型化的 `404`；没有创建 / 重命名 / 删除，run 作用域的
端点也不带项目段，因此 `project_id` 从不缩小任何范围。参见
[GUI 架构](../concepts/gui_architecture.md)的「5. 实体模型只有一层」一节。

**environment profile（环境配置档，`--profile`）**
随附的部署叠加层 `laptop` / `hpc` / `cloud` 之一
（`ari-core/config/profiles/<name>.yaml`），由 CLI 的 `--profile` 标志选择。
它*不是*深度合并：`_apply_profile`（`ari/cli/run.py`）恰好应用
`bfts.max_total_nodes`、`bfts.max_parallel_nodes`（历史拼写
`bfts.parallel`，仅在 `max_parallel_nodes` 缺席时才被接受）、`hpc.enabled`
与 `hpc.scheduler`；文件中其余的键一律被忽略，解析器会警告并列出它丢弃的
键。它与 **execution mode**（`ari.mode`）是不同概念，与 PaperBench rubric
的字段 `execution_profile` 也不同。参见[配置](configuration.md)的
「解析模型」一节。

**`resolved_config.json`**
`POST /api/v1/runs` 物化进检查点的启动清单（`ari/viz/v1/launch.py`）——
预览过的解析后配置在启动时成为现实。它是增量的：为兼容旧的展示路径，
`launch_config.json` 仍会写出。密钥从不出现在 `values` 或 `provenance` 中，
只作为 `secret_references` 标志出现；`digest` 是仅对 `values` 的规范 JSON
计算的 `sha256:`，因此它是在已脱敏的文档上计算的。回读端点为
`GET /api/v1/runs/{run_id}/resolved-config`。参见[配置](configuration.md)的
「`resolved_config.json`（启动清单）」一节。

**paper mode（论文模式，`linear` / `rqgm_archive`）**
`paper.mode` 的两个取值 —— 一个与执行模式相互独立的轴，四种组合都有效。
`linear`（默认）保持当前的论文流水线；`rqgm_archive` 选择启用 paper-archive
协同进化，并且*还*需要 `rqgm.paper.enabled: true` 联锁（只设一半时回退为
`linear`）。生效的模式在每个论文阶段被记录一次，写入
`{checkpoint}/paper_archive_state.json`（`ari/rqgm/paper_runtime.py`），
连同 `mode_source` 与 `switch_journal`。

## 状态与发表

**research phase（研究阶段）**
一次运行在自身生命周期中所处的位置：`idle`、`starting`、`bfts`、`paper`、
`review`。它由存在哪些检查点产物推导而来（`ari/viz/services/state_service.py`
中的 `current_phase`，与 GUI 里 `RESEARCH_PHASES` 所持的是同样五个 token）。
run Overview 把它渲染为独立的带标签行，绝不与治理阶段行（只在 RQGM 运行上
出现）合并。

**sub-experiment（子实验，子运行）**
从父检查点启动的一次运行。子运行在自己的 `meta.json` 中记录谱系：
`parent_run_id`、`recursion_depth`、`max_recursion_depth`（默认 3，
`api_orchestrator.DEFAULT_MAX_RECURSION_DEPTH`）与 `inherit_idea_index`。
有两道守卫会拒绝启动 —— 深度达到或超过上限，以及父 `meta.json` 带有
`parent_terminated`（当 lineage decision 选择 `terminate` 时由
`ari/cli/lineage.py` 写入）。这是运行*之间*的关系，与一次运行内部的 BFTS
节点树不同。参见 [REST API](rest_api.md)的「子实验 + 谱系」一节。

**checkpoint (检查点)**
一次运行的自包含目录，`{workspace}/checkpoints/{run_id}/`，其中 `run_id` 为
`YYYYMMDDHHMMSS_<slug>`。所有状态都存于此处；`PathManager`
（`ari/paths.py`）是唯一的事实来源。API 密钥从不存储于此 —— 它们来自 `.env` 或环境变量。完整布局参见
[架构 → 文件结构](../concepts/architecture.md#file-structure)，
逐文件 schema 参见[文件格式](file_formats.md)。一次 `ari_rqgm`
运行会额外写入 RQGM 状态文件（`rqgm_state.json`、
`rqgm_registry.json`、`rqgm_audit.jsonl`、`proposals/`、
`rqgm_prompts/`、…）—— 在所有默认运行上均不存在。

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
[执行模式](../guides/execution_modes.md) ·
[配置](configuration.md)
