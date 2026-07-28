---
sources:
  - path: ari-core/ari/schemas
    role: schema
  - path: ari-core/ari/rqgm
    role: implementation
  - path: ari-core/ari/checkpoint.py
    role: implementation
  - path: ari-core/ari/paths.py
    role: implementation
  - path: ari-core/tests/test_rqgm_state_store.py
    role: test
last_verified: 2026-07-16
---

# RQGM Schema 参考

可选启用的 `ari_rqgm` 执行模式所持久化的每种记录的正式 JSON
Schema。它们全部随 `ari-core/ari/schemas/` 一起发布，并通过
`ari.schemas.load(name)` 按 basename 加载。这些记录在默认的
`simple_bfts` 检查点上一个也不存在 —— 每个读取方都把缺失视为
「RQGM 从未运行」。

本页记录的是**记录形状**（用途、所属模块、关键字段、id/哈希
纪律）。关于这些记录所在的检查点**文件** —— 创建条件、真相源 vs
派生快照的关系、resume 语义 —— 见
[文件格式参考](file_formats.md)；本页末尾的
[清单表](#checkpoint-file-inventory)把每个文件映射到它的 schema。
配置旋钮见
[配置 → 执行模式与 RQGM](configuration.md#execution-mode-and-rqgm-governance-opt-in)；
模式语义见[执行模式](../guides/execution_modes.md)。

## Id 与哈希纪律

每种 RQGM id 和哈希格式都由一个模块拥有：
`ari-core/ari/rqgm/events.py`（RQGM Task 02）。所有哈希遵循设计
原则 P2（确定性）：挂钟时间、git SHA、主机名或绝对路径永远不进入
任何哈希。

- **`canonical_json(payload)`** —— 所有 RQGM 哈希计算所依据的唯一
  规范 JSON 形式：键排序、无空白、`ensure_ascii=False`（由测试
  逐字节钉住）。
- **`hash12`** —— `sha256(text)[:12]`，逐字复用自
  `ari.prompts._provenance.hash12`（与
  `FilesystemPromptLoader.load_versioned` 完全相同的提示词溯源
  方案；不存在第二套方案）。Schema 模式：`^[0-9a-f]{12}$`。
- **`sha256_hex`** —— 完整的 64 位十六进制摘要，用于完整哈希重要
  的场合（`prompt_sha256` / `full_sha256`、`inputs_sha256`、治理
  缓存中的内容哈希）。
- **`payload_hash(payload)`** = `hash12(canonical_json(payload))`
  —— 事件哈希与指纹函数。
- **`epoch_fingerprint`**（`ari/rqgm/state.py`）——
  `hash12(canonical_json(EpochState payload))`，其中排除
  `created_at`（挂钟元数据）、指纹字段本身和 `status`，因此
  open→closed 不会对冻结内容重新指纹。

Id 格式（全部零填充、按检查点计数）：

| 格式 | 生产者 | 示例 |
|---|---|---|
| `epoch_%03d` | 纪元计数器，始于 `epoch_000` | `epoch_004` |
| `transition_%03d_to_%03d` | 纪元边界转换 id | `transition_003_to_004` |
| `evt_%06d` | 事件日志行计数器，始于 `evt_000000` | `evt_000042` |
| `{role}_v{N}` | 组件 id | `reviewer_v3` |
| `{role}_prompt_v{N}` | 提示词 id | `reviewer_prompt_v4` |
| `epochstate_{epoch_id}` | `epoch_state.json` 记录 id | `epochstate_epoch_004` |
| `prop_%06d` | ProposalRecord | `prop_000031` |
| `atk_` / `def_` / `jdg_` / `vat_` / `utl_%06d` | 对抗循环记录 | `atk_000007` |
| `adv_case_%05d` | AdversarialReplayCase | `adv_case_00003` |
| `pcand_` / `pval_` / `cobs_%05d` | 提示词进化记录 | `pcand_00002` |
| `upc_%06d` | UtilityPolicyCandidate（Task 14） | `upc_000004` |
| `erase_` / `rebuild_%05d` | 擦除 / 重建事件 | `erase_00007` |
| `meta_out_` + hash12 | MetaAgentOutputRecord | `meta_out_a1b2c3d4e5f6` |
| 16 位十六进制 `cache_key` | 治理缓存（见下） | `a3f19c02b7d4e881` |

## 共享信封（`rqgm_defs.schema.json`）

**用途：**所有 RQGM 记录 schema 引用的规范共享 `$defs` ——
`rqgm_record_base` 信封、封闭的状态 / 角色 / 层级词汇表，以及
id/哈希格式。**所属模块：**`ari/rqgm/events.py`（词汇表的 Python
镜像）。其他 schema 文件中内嵌的这些 `$defs` 副本由
`ari-core/tests/test_rqgm_state_store.py` 钉为与本文件逐字节相等。

每条治理记录都携带 `rqgm_record_base` 的八个必填字段（**只在**此处
记录一次；下面各 schema 表只列记录特有字段）：

| 信封字段 | 含义 |
|---|---|
| `record_id` | 类型化、零填充的 id（格式见上） |
| `epoch_id` | 产生该记录的 `epoch_%03d` |
| `component_id` | 生产组件（`{role}_v{N}` 或固定引擎名） |
| `prompt_hash` | 生产提示词的 `hash12`；内核/引擎所写记录为 `null` |
| `role` | 下方封闭角色词汇表之一 |
| `created_at` | ISO 时间戳 —— 仅元数据，从不参与哈希 |
| `source_refs` | 指向输入的检查点相对引用 |
| `status` | 记录特有的状态词汇表 |

封闭词汇表：

- **状态生命周期**（提示词与组件共享；合法转换即
  `ari/rqgm/transition_rules.py` 中的 T1–T21 表）：
  `candidate → validated → shadow → probationary_active → active`，
  然后 `active → warning | probation | quarantine`，以及
  `quarantine → retired → banned`。`active` 与
  `probationary_active` 构成每纪元冻结的活跃集合。
- **角色** —— 可进化：`generator`、`reviewer`、`adversary`、
  `defender`、`judge`、`router`、`prompt_mutator`、
  `clean_room_generator`、`replay_selector`、
  `failure_summary_compressor`、`policy_mutator` 与 `utility_policy`
  （RQGM Task 14 —— 受治的分数及其提案者）、`paper_writer` 与
  `paper_reviewer`（paper-archive；仅在实效的 `rqgm_archive` paper
  模式下注册，因此探索启动字节一致）；固定（为溯源而注册，宪法上
  不可变）：`constitutional_kernel`、`fixed_verifier`、`audit_log`。
- **层级**：`fixed`、`institutional`、`meta`。

## 状态与事件日志 schema（Task 02）

### `rqgm_transition_event.schema.json`

**用途：**`rqgm_transitions.jsonl` 的哈希链式、追加式行信封 ——
并且（以独立的按文件链）也是 `rqgm_audit.jsonl` 的信封。
**所属模块：**`ari/rqgm/events.py`（`TransitionEvent` /
`finalize_event`）；持久化在 `ari/rqgm/store.py`。

| 字段 | 说明 |
|---|---|
| `schema_version` | const `1` |
| `event_id` | `evt_%06d`，按检查点单调 |
| `event_type` | 封闭 v1 集合：`epoch_transaction_prepare`、`component_registered`、`prompt_registered`、`component_status_change`、`prompt_status_change`、`epoch_close`、`epoch_open`、`epoch_transaction_commit`、`emergency_quarantine`（唯一的纪元中途变更） |
| `payload` | 事件正文 —— 唯一被哈希的部分 |
| `event_hash` | `hash12(canonical_json(payload))` |
| `prev_event_hash` | 链到上一行；首行为 `""` |
| `ts` / `ts_iso` | 信封元数据，在哈希之外（P2） |

### `epoch_state.schema.json`

**用途：**当前打开（或最近关闭）纪元的派生 `epoch_state.json`
汇总。`rqgm_transitions.jsonl` 是真相源；该快照可丢弃，不匹配时
从重放重建。**所属模块：**`ari/rqgm/state.py`（`EpochState`、
`epoch_state_payload`、`epoch_fingerprint`）；经
`ari.checkpoint.save_epoch_state_json` 持久化。

| 字段 | 说明 |
|---|---|
| `record_id` | `epochstate_epoch_%03d` |
| `epoch_id` / `epoch_seq` / `previous_epoch_id` / `opened_by_transition_id` | 纪元链位置 |
| `status` | `open` \| `closed` |
| `run_id` / `node_count_at_open` | 运行关联 + 边界簿记 |
| `active_components` / `active_prompt_hashes` / `utility_policy` | 每纪元冻结的集合（冻结时复制；全局不变量 1–3）。`utility_policy` 是**受治的分数正文** —— `composite`、`axis_weights`、`frontier_score`、`depth_penalty_lambda`、`ucb_c` 加上封印的 `utility_policy_hash` —— 由 `ari/rqgm/state.py:capture_utility_policy` 从已采纳策略中捕获（纪元 0 / `simple_bfts` 回退到 cfg）；见[受治效用进化 schema](#governed-utility-evolution-schema-task-14) |
| `registry_version` | 冻结时点注册表的 `hash12` |
| `epoch_fingerprint` | 排除 `created_at`、`status` 和其自身的 `hash12` |
| `created_at` | 元数据；被指纹排除 |

### `rqgm_registry.schema.json`

**用途：**把 ComponentRegistry + PromptRegistry 合入一个文件的
派生 `rqgm_registry.json` 汇总，使两者在磁盘上保持事务一致；
事件日志才是真相。**所属模块：**`ari/rqgm/registry.py`
（类 `GovernedPromptRegistry`；磁盘上的名字仍为
`PromptRegistry`）；经 `ari.checkpoint.save_rqgm_registry_json`
持久化。

| 字段 | 说明 |
|---|---|
| `registry_version` | `hash12` |
| `as_of_event_hash` | 最后折叠事件的 `event_hash`（为空时 `""`） |
| `components[]` | 组件条目（status、role、tier；meta 层条目附加 `rqgm_meta` 能力标志） |
| `prompts[]` | 提示词条目：文本按来源引用（当前为 `committed_template` 键；`checkpoint_file` 用于进化提示词），同时携带 `prompt_hash`（`hash12`）**和**完整 `prompt_sha256`；v1 中 `spec_ref` 为 `null` |

## 提案 schema（Task 03）

### `proposal_record.schema.json`

**用途：**`proposals/proposal_records.jsonl` 的一行 —— 追加式提案
真相（"存储全部；只把摘要交给 BFTS"）。**所属模块：**
`ari/rqgm/proposals/records.py`（数据类）+
`ari/rqgm/proposals/store.py`（持久化、去重、`idea.json` 投影）。

| 字段 | 说明 |
|---|---|
| `record_id` | `prop_%06d` |
| `epoch_id` | `simple_bfts` 仅记录模式下为 `null` |
| `role` | const `generator` |
| `generator` | `cheap` \| `mutation` \| `attack_driven` \| `prior_art` \| `virsci` \| `legacy_idea_json` |
| `prompt_hash` | 遗留导入为 `null` |
| `status` | `candidate` \| `selected` \| `expanded` \| `superseded` |
| `stale` / `valid_for_frontier` | 仅逻辑标志；读取时语义由前沿修复（Task 10）拥有，已存行绝不重写 |
| `source_refs` | 与信封的字符串数组不同：是一个对象（`node_id`、`parent_node_id`、`parent_proposal_id`、`dispatch_head`、...） |
| `summary` | 内联的有界 `ProposalSummaryView` —— BFTS 看到的唯一形状 |
| `archive_refs` | 指向 `proposals/archive/<record_id>/` 的检查点相对引用（`raw_output`、`transcript`、`discussion_log`、`retrieval_snapshot`、`generator_config`、...），绝不复制 |
| `idea_projection` | 维护中的 `idea.json` 兼容投影的 `{projected, idea_index}` 簿记 |

### `proposal_summary_view.schema.json`

**用途：**有界的提案摘要 —— BFTS 可以消费的**唯一**提案表示；完整
的 VirSci 转录只进归档，无法塞进硬性字符预算。**所属模块：**
`ari/rqgm/proposals/records.py`。必填字段：
`proposal_record_id`、`title`、`short_description`、`hypothesis`、
`experiment_plan[]`、`success_metric`、`novelty_risks[]`、
`expected_artifacts[]`、`dissent_summary`、`scores`。
`schema_version` 位于外层的 ProposalRecord 上；演进只允许增量。

## 治理 schema（Task 05）

### `governance_report.schema.json`

**用途：**`GovernanceOrchestrator.audit_epoch` 的唯一返回类型，
作为 `governance_report` 记录追加到 `rqgm_audit.jsonl` —— 一个纪元
的最新报告是带该 `epoch_id` 的*最后*一行。**所属模块：**
`ari/rqgm/governance/`（`_records.py` 构建器、`_pipeline.py`
编排）。

| 字段 | 说明 |
|---|---|
| `component_id` / `role` | const `governance_orchestrator` / `governance` |
| `status` | 类 const 枚举 `final` |
| `governance_level` / `degraded` / `degradation_reasons` | 本次审计的预算/降级姿态 |
| `reliability` / `observations` / `evidence_bundles` | 每组件可靠性输入（证据 bundle 由 EvidenceClerk 独家撰写） |
| `impeachment_motions` / `defenses` / `adjudications` | 弹劾流水线（动议仅限 Auditor；同角色指控被拒绝） |
| `candidate_evaluations` | 馈入 RegistryTransitionEngine 的重放/锚定分数 |
| `replay_pool_updates` / `self_audit` / `bond_accounting` / `budget_usage` | 边界簿记 |
| `recommendations[]` | `action` 是封闭集合 `promote_candidate` \| `promote` \| `demote` \| `warn` \| `quarantine` \| `retire` \| `no_action`，由 Task 09 消费 |

## 对抗循环 schema（Task 06）

### `rqgm_attack_records.schema.json`

**用途：**复用进 `rqgm_adversarial_cases.jsonl`（并作为治理证据进
审计日志）的四种攻击循环记录形状。**所属模块：**
`ari/rqgm/adversarial/records.py`（形状 + 构造性预防构建器）、
`ari/rqgm/adversarial/round.py`（逐节点回合）。

| 记录（`record_type`） | Id / 角色 | 特有字段 |
|---|---|---|
| `raw_attack` | `atk_%06d` / `adversary` | `adversary_type`（随发布 schema 的 enum 是封闭七类**探索**集合：`overclaim`、`metric_gaming`、`prior_art`、`reproducibility`、`evidence_gap`、`cost_explosion`、`prompt_injection`；paper 阶段增加第八类 `paper_self_preference` —— 见 [Paper-archive schema](#paper-archive-schemas-paper-rqgm_archive-mode)）；`target_artifact.type`（封闭集合：`proposal`、`experiment_plan`、`node_report`、`metric_result`、`paper_claim`、`novelty_claim`、`citation_claim`、`reproducibility_claim` —— 绝不是组件）；`attack_claim`；`attack_evidence_refs`（要求 ≥ 1）；`severity_claimed`。仅为审计材料 —— 原始攻击从不触碰分数（不变量 8） |
| `defender_response` | `def_%06d` / `defender` | `raw_attack_id`；`stance` `rebut` \| `concede` \| `propose_fix` |
| `judgment_record` | `jdg_%06d` / `judge` | `raw_attack_id`；`verdict` `valid` \| `partially_valid` \| `invalid`；裁判指定的 `severity`（`low`–`critical`）；`defense_status`。总是写入，即使为 `invalid` |
| `validated_attack` | `vat_%06d` / `judge` | `case_type`、`raw_attack_id`、`judgment_id`、`validated`、`verdict`、`severity`。**仅**对 `valid` / `partially_valid` 裁定存在（必须经过裁决，不变量 9）。承载问责绑定 —— 见下文 |

#### `validated_attack` 上的问责绑定

角色是**被观测**的；组件是**被绑定**的；而绑定**仅在裁决之后**才被铸造。
`validated_attack` 的两个目标形字段并非同义词：

| 字段 | 值空间 | 读者 |
|---|---|---|
| `affected_components` | 角色名（`["reviewer"]`）—— 关于谁被牵涉的复数观测。角色是攻击唯一能诚实知晓的东西，而没有任何机制会制裁一个角色。（该名称承载的是角色；之所以不改名，是因为改名会重写每一条已存储的记录） | FailureSummary 的 `affected_roles` |
| `target_component_id` | **单个**可由注册表解析的组件 id（`"reviewer_v3"`）—— 做出该攻击所推翻之决定的在任者 | `ReliabilityMonitor.validated_attack_involvement`、`EvidenceClerk` 的目标选择 ⇒ 整条弹劾链 |

`target_component_id` 是**可选的，且要么存在要么缺席，绝不会存在但为空**
（`minLength: 1`）：空目标不是目标，不指名任何人的记录就什么都不说 —— 因此
不绑定任何人的记录与引入绑定之前保持字节一致，无需迁移。它在记录构造时由被
牵涉的角色针对**纪元冻结的**活跃组件集合解析得出，绝不做实时注册表读取（在
边界采纳之后的实时读取会让继任者为前任的缺陷被弹劾），也绝不绑定到作者本身：
绑定自身裁判的记录会被拒绝（角色分离 —— 没有任何行动者可以在同一条记录中既
裁决又被制裁）。

这并不削弱"仅以工件为目标"的规则。对抗者仍然只攻击工件；绑定仅存在于裁决之后
由裁判撰写的记录上。对抗者负责观测，而使观测具备问责效力的是裁判的判定。

在探索（`ari_rqgm`）侧，七种对抗者类型不绑定任何对象：它们攻击的工件由
`generator` 角色撰写，而该角色没有已注册的组件（没有任何东西会刻印
`generator_v1` id），因此其记录带有 `affected_components: []` 且没有
`target_component_id`。该机制是角色驱动的 —— 一旦某个撰写工件的角色拥有已注册
的在任者，指名它即可绑定这些案例类型，无需其他改动。

### `rqgm_utility_record.schema.json`

**用途：**一条受治效用审计记录；§5.4 惩罚通道是其 v1 唯一发出方，
前沿修复（Task 10）在擦除后重新发出重算记录。**所属模块：**
`ari/rqgm/adversarial/records.py`（发出）+
`ari/rqgm/frontier_repair.py`（重算）。

| 字段 | 说明 |
|---|---|
| `record_id` | `utl_%06d` |
| `role` | const `utility_policy` |
| `node_id` / `base_score` / `penalty` / `final_score` | 每节点的惩罚算术 |
| `input_refs` | `penalty > 0` **要求** `input_refs.validated_attack_ids` 中 ≥ 1 个 id（内核检查 —— 原始攻击从不计分） |
| `utility_policy_hash` / `frozen_policy` | 纪元冻结策略，**按值**内嵌，使得可以在原始权重下重算 |
| `supersedes` / `recomputed_in_epoch` | 仅在 Task-10 重算记录上设置；被取代的记录留在磁盘上，标记为过期 |

### `rqgm_replay_pool.schema.json`

**用途：**AdversarialReplayPool 的派生字节固定快照
`rqgm/adversarial_replay_pool.json`；`rqgm_adversarial_cases.jsonl`
仍是真相源，并在加载时补齐任何崩溃尾部。**所属模块：**
`ari/rqgm/adversarial/pool.py`；经
`ari.checkpoint.save_adversarial_pool_json` 持久化。

| 字段 | 说明 |
|---|---|
| `case_seq` | 单调案例计数器 |
| `cases[]` | AdversarialReplayCase：`case_id`（`adv_case_%05d`）、`case_type`（七类集合）、`validated_attack_id`、`severity`、`admitted_epoch` / `last_confirmed_epoch`、`status` `active` \| `evicted`（逐出为仅逻辑）、`replay_view`（完整材料 —— 对角色 `clean_room_generator` 拒绝）与 `abstract_view`（污染安全的 FailureSummary —— 不含原始攻防文本） |

## 提示词进化 schema（Task 07）

### `rqgm_prompt_spec.schema.json`

**用途：**一个带版本、不可变的提示词身份（PromptSpec）—— 对模板
字节的任何更改都会铸造**新的** `prompt_id` + `prompt_hash`；活跃
提示词文本永不原地修改。**所属模块：**`ari/rqgm/prompt_spec.py`；
实例内嵌于 `prompt_evolution.jsonl` 的候选记录中，并汇总进
`prompt_specs.json`。

| 字段 | 说明 |
|---|---|
| `prompt_id` / `role` / `version` / `status` | 身份 + 生命周期位置 |
| `generation_mode` | `founding` \| `mutation` \| `clean_room` |
| `parent_prompt_id` | 世系（创始提示词为 `null`） |
| `template_ref` | `{kind: package \| checkpoint \| policy, key\|path}` —— 字节所在位置（已提交模板、进化后的正文 `rqgm_prompts/<prompt_id>.md`，或由 `path` 引用的 Task-14 受治效用策略正文） |
| `prompt_hash` / `full_sha256` | 模板字节的 `hash12` + 完整 sha256（与 `FilesystemPromptLoader.load_versioned` 完全相同的方案） |
| `evolvable` / `epoch_introduced` | 进化资格 + 溯源 |
| `spec` | 行为契约：`role_instruction`、`constitutional_constraints[]`、`input_contract.required_fields[]`、`output_schema`，可选 `rubric` / `calibration_policy` / `budget_policy` |

### `rqgm_prompt_evolution.schema.json`

**用途：**复用进 `prompt_evolution.jsonl` 的三种记录形状。进入
`probationary_active` / `active` 的采纳**只**通过
RegistryTransitionEngine 的纪元边界事务发生 —— 绝不通过本文件。
**所属模块：**`ari/rqgm/prompt_records.py`（形状 + 持久化）、
`ari/rqgm/prompt_evolution.py`（流水线）。

| 记录（`record_type`） | Id | 特有字段 |
|---|---|---|
| `prompt_candidate` | `pcand_%05d` | `candidate_id`、`generation_mode`（`mutation` \| `clean_room`）、`mutation_kind`（`freeform_mutation`、`threshold_tuning`、`schema_tightening`、`specialization`、`distillation`）、`source_prompt_id`、`failure_summary_refs`、`rationale`、完整内嵌的 `prompt_spec`。总是以 `status: candidate` 出生 —— 没有即时激活 |
| `prompt_candidate_validation` | `pval_%05d` | `candidate_id`、`stage`（单调阶梯 `static_validation → constitutional_validation → schema_dry_run → replay_evaluation → anchor_evaluation → shadow` —— 记录链使跳过阶段可被检测）、`passed`、`evaluated_by`、`case_results`、`metrics` |
| `comparison_observation` | `cobs_%05d` | `candidate_id`、`incumbent_id`、`input_context_hash`、`node_id`、`candidate_output_hash` / `incumbent_output_hash`、`divergence`。只有哈希和分歧摘要 —— 影子输出文本从不进入本文件、节点指标或前沿 |

## 洁净室 schema（Task 08）

### `clean_room_request.schema.json`

**用途：**一条 CleanRoomGenerationRequest，由
RegistryTransitionEngine 的 RetirementEvent
（`EpochTransition.clean_room_requests`）产生，持久化到
`rqgm_cleanroom.jsonl`，使待处理请求在 resume 后仍存活。
**所属模块：**`ari/rqgm/clean_room.py`（请求 + 流水线；筛查策略在
`ari/rqgm/clean_room_rules.py`）。

| 字段 | 说明 |
|---|---|
| `component_id` / `trigger` | const `registry_transition_engine` / `retirement_event`；`prompt_hash` 为 `null` |
| `retirement_event_id` / `target_role` | 哪次退役、再生成哪个角色（封闭角色枚举） |
| `status` | `pending` \| `generating` \| `generated` \| `rejected_contaminated` \| `failed` \| `superseded` |
| `allowed_inputs` | 五个禁止输入标志为 **const-false** —— 把其中任何一个设为 `true` 的请求都是 schema 无效且被内核阻断 |
| `requirements` / `replay_case_ids` / `budget_policy` | 再生成要求；重放案例仅用于评估时 |

### `clean_room_bundle.schema.json`

**用途：**交给 CleanRoomPromptGenerator 的物化、**封闭**输入集合
（`additionalProperties: false` —— 除已提交的
`rqgm/clean_room_generator` 元提示词外，该 bundle 就是生成器的
全部上下文）。**所属模块：**`ari/rqgm/clean_room.py`。

| 字段 | 说明 |
|---|---|
| `bundle_id` / `request_id` | 与请求的关联 |
| `bundle_hash` | 对所有其他字段的规范 JSON 的 `hash12` |
| `role_spec` / `output_schema` / `constitutional_constraints` | 再生成的提示词必须满足的内容 |
| `abstract_failure_summary` | 污染安全的故障摘要（仅抽象视图） |
| `replay_requirements` / `cost_budget` | 验收要求 + 预算 |

## 转换 schema（Task 09）

### `epoch_transition.schema.json`

**用途：**一次 RegistryTransitionEngine 边界决议的唯一输出记录，
作为 `epoch_transition` 记录审计到 `rqgm_audit.jsonl`。每次状态
变更都钉住 `ari/rqgm/transition_rules.py` 中固定 T1–T21 表的一个
`rule_id` 行（T1–T19 基础表加上角色范围的 T20 / T21 取代行）；只有
`rqgm.transition.*` 数值阈值可配置。
**所属模块：**`ari/rqgm/transition_engine.py` —— 唯一的注册表状态
写入方（`produced_by` 为 const `registry_transition_engine`，内核
CK-REG-004）。

| 字段 | 说明 |
|---|---|
| `epoch_transition_id` | `transition_%03d_to_%03d` |
| `status` | `pending` \| `committed` \| `aborted` \| `rejected` \| `failed` —— 被中止/被内核阻断的转换会被记录但**不**施加任何注册表变更 |
| `emergency` | `true` 是唯一的纪元中途形状（单一制裁进入 quarantine） |
| `inputs` | 含冻结边界输入（GovernanceReport + 候选评估 + 注册表哈希）的 `inputs_sha256` 内容哈希，使每次已提交变更都可确定性重放 |
| `adoptions` / `sanctions` / `retirements` / `bans` | 状态变更列表，每项钉住一个 `rule_id` |
| `clean_room_requests` | 交给 Task 08 的再生成请求 |
| `next_active_components` / `fallbacks` | 下一纪元的冻结活跃集合 + 无空缺回退 |
| `kernel_validation`（+ 可选 `kernel_violation`） | 内核对该事务的裁定 |

## 前沿修复 schema（Task 10）

### `selective_erasure_event.schema.json`

**用途：**当 FrontierRepairEngine 将某个已退役 `prompt_hash` 的
依赖闭包标记为过期时，追加（在 Task 02 审计信封内）到
`rqgm_audit.jsonl` 的一条 SelectiveErasureEvent。擦除是仅逻辑的
（不变量 13）：列出的 id 在 `rqgm_erasure_state.json` 中被打标，
绝不重写或删除。**所属模块：**`ari/rqgm/frontier_repair.py`。

| 字段 | 说明 |
|---|---|
| `record_id` | `erase_%05d` |
| `component_id` / `role` / `prompt_hash` | const `frontier_repair_engine` / `kernel` / `null`（内核所写） |
| `status` | `applied` \| `conservative` \| `halted_expansion`（fail-closed 降级阶梯） |
| `retired_prompt_hashes` / `retired_component_ids` | 退役了什么 |
| `direct_stale_record_ids` / `transitive_stale_record_ids` | 依赖闭包 |
| `invalidated_node_ids` / `recompute_node_ids` / `abandoned_pending_node_ids` | 节点处置 |
| `trace_stats` | BFS 追踪器统计（`rqgm.frontier_repair.max_trace_depth` 限制遍历） |

### `frontier_rebuild_event.schema.json`

**用途：**引擎以声明式方式重算前沿（资格 + 对「获胜子节点被擦除的
父节点」的规则 A 复位）之后，追加到 `rqgm_audit.jsonl` 的一条
FrontierRebuildEvent。**所属模块：**`ari/rqgm/frontier_repair.py`。

| 字段 | 说明 |
|---|---|
| `record_id` | `rebuild_%05d` |
| `component_id` / `role` / `prompt_hash` | const `frontier_repair_engine` / `kernel` / `null` |
| `status` | `applied` \| `conservative`（内核校验失败后丢弃被标记节点）\| `halted_expansion`（运行降级为仅排空） |
| `frontier_before` / `frontier_after` | 节点 id 列表 |
| `removed_node_ids` / `reinstated_node_ids` / `recomputed_utility_node_ids` | 增量 |
| `kernel_validation` | `passed` \| `failed` |

### `erasure_state.schema.json`

**用途：**派生的、可重建的 `rqgm_erasure_state.json` 过期状态
汇总 —— 可由 `rqgm_audit.jsonl` 中的每个擦除/重建事件折叠而得。
过期状态是读取时判定的：一条记录过期当且仅当其 `record_id` 在
`stale_record_ids` 中；文件缺失意味着「无过期，全部有效」。
**所属模块：**`ari/rqgm/erasure_state.py`；写入统一经
`ari.checkpoint.save_erasure_state_json`。

| 字段 | 说明 |
|---|---|
| `retired_prompt_hashes` | `hash12 → {retirement_event_id, retired_in_epoch}` |
| `stale_record_ids` | `record_id → 擦除事件 id` |
| `invalid_frontier_node_ids` | `node_id → 擦除事件 id` |
| `last_erasure_event_id` / `last_rebuild_event_id` | 折叠游标 |

## 元进化 schema（Task 11）

### `rqgm_meta.schema.json`

**用途：**元层 `$defs` —— ComponentRegistry 的 `tier` + 能力标志
扩展、`rqgm_meta_outputs.jsonl` 的 MetaAgentOutputRecord 行形状，
以及 RegistryTransitionEngine 消费的 MetaCandidateEvaluation
记录。**所属模块：**`ari/rqgm/meta_rules.py`（确定性 Python 镜像
—— `capability_entry_failures` —— 必须与 schema 一致）+
`ari/rqgm/meta_evolution.py`。

| 定义 | 关键字段 |
|---|---|
| `capability_flags` | 布尔能力矩阵（`can_modify_registry`、`can_activate_candidates`、`can_read_retired_prompt_text`、`can_file_impeachment`、`can_author_evidence_bundle`、`can_emit_candidates`、`can_emit_replay_recommendation`、`can_emit_failure_summary`）+ `allowed_targets` / `forbidden_targets` / `max_outputs_per_epoch`。标志默认 false；硬性拒绝的标志在 `tier: meta` 上为 const-false |
| `meta_component_entry` | `component_id`、`role`、`tier`、`status`、`prompt_hash`、`capabilities` |
| `meta_agent_output_record` | `record_id` `meta_out_` + hash12；`status` `recorded` \| `denied`；`output_kind` 封闭集合 `prompt_candidate` \| `clean_room_candidate` \| `replay_case_recommendation` \| `failure_summary`；`target_role`；`shadow` / `sandboxed` 标志；`input_bundle_hash` / `output_payload_hash` |
| `meta_candidate_evaluation` | `candidate_component_id` vs `incumbent_component_id`、`sandbox` / `shadow` 结果、`downstream_fate`、`authority_non_expansion_check` `pass` \| `fail` |

## 治理缓存 schema（Task 12）

### `rqgm_governance_cache.schema.json`

**用途：**追加式治理结果缓存 `rqgm_governance_cache.jsonl` 的
一行。**所属模块：**`ari/rqgm/governance_cache.py`；由
`ari/rqgm/governance/_adjudication.py`（纪元边界候选评估）和
`rqgm.replay.use_cached_results` 重放查询消费。

| 字段 | 说明 |
|---|---|
| `cache_key` | `sha256(artifact_hash ␟ prompt_hash ␟ role ␟ epoch_id ␟ input_context_hash ␟ output_schema_hash)[:16]`（`␟` = `\x1f`）；16 位十六进制 |
| `artifact_hash` / `input_context_hash` / `output_schema_hash` | 对规范 JSON 的完整 sha256 |
| `result_ref` / `score` | 指向底层记录的指针 + 缓存的分数 |
| `created_at` | 仅溯源 —— **绝不**参与键（P2） |

条目从不原地失效：已退役提示词的条目只是不再可被寻址，因为其
`prompt_hash` 不会再出现在查询中（不变量 13）。预算计数器与治理
级别分配不存放在这里 —— 它们以 `budget_consumed` /
`budget_degraded` / `governance_level` 行的形式记入
`rqgm_audit.jsonl`（`ari/rqgm/budget.py`）。

## 受治效用进化 schema（Task 14）

### `rqgm_utility_policy_candidate.schema.json`

**用途：**一个提议的后继**效用策略** —— 受治的分数本身现在是一个
可在边界重写的进化对象（RQGM Task 14）。`utility_policy_candidate`
镜像 `prompt_candidate`，并搭乘**同一个** `prompt_evolution.jsonl`
日志 —— 没有新的存储。它的信封作者是 `policy_mutator` 而非策略本身：
候选是**由**某个组件发出的提案，因此 `component_id` / `prompt_hash`
指名提案者，而被提议的策略搭乘 `policy`（按值）+ `policy_hash`。
**所属模块：**`ari/rqgm/utility_evolution.py`
（`UtilityPolicyCandidate`、`PolicyMutator`）；在边界铸造，经
`ari/rqgm/prompt_records.record_prompt_evolution_event` 追加。

| 字段 | 说明 |
|---|---|
| `record_id` | `upc_%06d` |
| `role` | const `policy_mutator` —— **作者**的角色；**目标**角色（`utility_policy`）由 `record_type` 隐含 |
| `candidate_id` | 铸造出的候选身份；入库时也是提示词注册表的 `prompt_id` |
| `mutation_kind` | 封闭集合 `axis_reweighting` \| `composite_swap` \| `frontier_score_swap` \| `exploration_tuning` \| `freeform_policy_proposal` |
| `policy` | 策略正文：`composite`、`axis_weights`（逐轴权重映射）、`frontier_score`、`depth_penalty_lambda`、`ucb_c`。正文绝不含 `utility_policy_hash` —— 哈希是对正文*本身*计算的 |
| `policy_hash` | `hash12(canonical_json(policy))` —— 一值三名：`policy_hash` **就是**入库条目的 `prompt_hash`，**就是**候选若被采纳将冻结的 `utility_policy_hash` |
| `parent_prompt_id` / `rationale` / `source_refs` | 世系 + 仅抽象证据 —— `rationale` / `source_refs` 绝不携带原始攻击文本 |

合法性（封闭值空间 + 轴权重界）不在本 schema 中表达：它是
`ari.rqgm.kernel_rules.UTILITY_POLICY_RULES` 中的冻结代码，位于
`constitution_hash` 内部，并在候选能对任何节点计分之前由
CK-UTL-001..008 强制。采纳**只**通过 RegistryTransitionEngine 的边界
事务发生 —— 角色无关的 T1→T6 主干，加上 Task-14 的取代边 **T20**
`superseded_by_adopted_successor`（`ari/rqgm/transition_rules.py`；唯一
的 `active → retired` 边，被内核守卫为仅 `utility_policy`）—— 绝不通过
本记录。进化后的策略正文以 write-once 写入
`rqgm_prompts/<candidate_id>.json`（按来源引用，绝不内联），而被采纳的
策略正是 `ari/rqgm/state.py:capture_utility_policy` 冻结进
`epoch_state.json` 的内容。

## Paper-archive schema（paper `rqgm_archive` 模式）

paper-archive 的 paper 模式（`paper.mode: rqgm_archive`，由
`rqgm.paper.enabled` 门控）持久化四个检查点文件。与 `rqgm_state.json`
和评估工具链工件一样，**它们都没有正式的 JSON schema** —— 每种形状由
其 Python 模块拥有并按值携带 —— 且四者在默认的 `linear` paper 运行中
都不存在（linear 路径不加载任何 `ari.rqgm` 模块）。

### `paper_archive_state.json` —— paper 阶段模式溯源

在 paper 阶段开始时一次写入。形状由 `ari/rqgm/paper_runtime.py`
（`build_paper_run_start_state`）拥有：`schema_version`、`paper_mode`
（`linear` \| `rqgm_archive`）、`rqgm_paper_enabled`、`mode_source`
（∈ `config` \| `env` \| `resume`）、`created_at`（仅元数据，从不哈希）、
`exploration_mode`、`seed_node_id`、`switch_journal[]`。持久化的模式在
再次调用时胜出 —— resume 绝不静默翻转 paper 模式。写入方：
`ari.checkpoint.save_paper_archive_state_json`。

### `paper_draft_archive.jsonl` —— 打分的草稿母体

追加式、字节固定、尽力而为（记录写入失败绝不破坏 paper 阶段；缺失
文件读作空 —— linear 运行不留下归档）。形状由 `ari/rqgm/paper_archive.py`
/ `ari/rqgm/paper_draft_executor.py` 拥有：每行一个草稿节点 ——
`schema_version`、`draft_id` / `node_id`、`kind`（`seed` \| `refine`）、
`parent_draft_id`、`refine_pass`、`tex_path`、`tex_sha256`、
`writer_prompt_hash`（framing / `diversity_bonus` 键）、
`reviewer_prompt_hash`、`review_score`（受治的 `paper_reviewer` 复合分
—— 前沿 + best-belief 排序键）、`suggested_revisions_ref`、
`anchors_preserved`、`decode_seed`、`epoch_id`，以及读取时标志
`is_best_belief` / `compiled`（由 `mark_paper_draft_flags` 原地更新）。

### `paper_anchor_corpus.jsonl` —— 只读 accept/reject 锚

锚定 `paper_reviewer` 效用的 APReS 等价 held-out 语料库。形状由
`ari/rqgm/paper_anchor.py`（`PaperAnchorCase`）拥有：`case_id`、
`record_type`、`ground_truth_label`（`accept` \| `reject`）、
`label_source`（`human_curated` \| `gate_bootstrap`）、`manuscript_sha256`
/ `manuscript_ref` / `manuscript_text`、`venue`、`authorship`
（`human` \| `ai`）、`split`（`train` \| `held_out`，在加载时确定性
分配）、`origin_epoch_id`、`expected_behavior`、`results`。由 curation /
bootstrap 工具**一次性**写入 —— **绝不**由受治角色写入（锚是固定的
ground truth，不是可进化的工件）。对 `gate_bootstrap` 标签的
`max_bootstrap_label_fraction` 上限由机器强制（降级为无 held-out
split，绝不 raise）。**默认关闭**（`anchor.enabled: false`）：降级的
on-ramp 不留下语料库，因此默认的 `rqgm_archive` 运行在提供 curated
语料库之前是 reviewed best-of-N。

### `rqgm/paper_self_preference_stat.json` —— 自我偏好统计

第八个对抗者作为其 `attack_evidence_ref` 引用的、每纪元确定性的
AI 对人类自我偏好边际。写入 `{ckpt}/rqgm/` 快照目录，尽力而为（绝不
向 paper 阶段 raise）。形状由 `ari/rqgm/paper_self_preference.py`
（`compute_self_preference_margin`）拥有：`record_type`、`schema_version`、
`epoch_id`、`sample_ids[]`、`per_case_scores`、`ai_mean`、`human_mean`、
`margin` —— `mean(reviewer accepts | authorship == ai) − mean(… |
authorship == human)`，**当语料库无 AI/人类划分时为 `0.0`**（语料缺失 /
仅 AI 的降级，绝非错误）。

**第八个对抗者类型。** `paper_self_preference` 是 Python `ADVERSARY_TYPES`
元组（`ari/rqgm/adversarial/records.py`，写入路径有效性检查
`validate_raw_attack` 使用的）的第八个成员，为 paper 阶段而加，在其之外
inert；随发布的 `rqgm_attack_records.schema.json` 的 `adversary_type` /
`case_type` enum 记录七个**探索**类型。`paper_self_preference` 案例牵涉
`paper_reviewer` 角色，它 —— 不同于七类的 `generator` —— **拥有**已注册
在任者（paper 模式下的 `paper_reviewer_v1`），因此 Task-15 的
`target_component_id` 绑定发火，validated-attack → 弹劾链在生产中运行；
在 paper 阶段之外，角色解析为 `""`，探索保持字节一致。

## 检查点文件清单

完整的按文件行为（创建条件、真相 vs 快照、resume 语义）记录在
[文件格式参考](file_formats.md#rqgm-epoch-governance-files-opt-in-ari_rqgm-mode)；
本表只把文件映射到 schema 和所有者。下表中的每个文件都在
`PathManager.META_FILES` 中按名注册（JSONL 真相文件额外进入
trace 文件集合），且 `proposals/` 和 `rqgm_prompts/` 目录位于
节点报告目录黑名单（`ari/orchestrator/node_report/builder.py`）
上，因此它们绝不会出现在任何节点的 `files_changed` 中。

| 检查点路径 | 类型 | Schema | 写入方 |
|---|---|---|---|
| `rqgm_state.json` | 模式溯源快照（一次写入） | 无 —— 形状由 `ari/rqgm/state.py` 拥有（`schema_version`、`mode`、`rqgm_enabled`、`mode_source` ∈ `config\|env\|resume`、`created_at`、`switch_journal[]`） | `ari.checkpoint.save_rqgm_state_json` |
| `constitution.yaml` | 人类可读声明，从 `ari-core/config/constitution.yaml` 一次性复制 | 无 —— 权威规则是由 `constitution_hash` 钉住的冻结代码 | `ari/rqgm/state.py`（`copy_constitution_if_missing`） |
| `rqgm_transitions.jsonl` | 追加式真相（哈希链式） | `rqgm_transition_event` | `ari/rqgm/store.py` |
| `rqgm_audit.jsonl` | 追加式审计日志（独立链） | 信封 `rqgm_transition_event`；记录载荷：`governance_report`（+ 弹劾流水线记录）、内核报告、`epoch_transition`（+ 退役 / 洁净室请求记录）、`selective_erasure_event`、`frontier_rebuild_event`、重算的 `rqgm_utility_record`、预算行 | 治理 / 转换 / 修复引擎经由存储 |
| `epoch_state.json` | 派生快照 | `epoch_state` | `ari.checkpoint.save_epoch_state_json` |
| `rqgm_registry.json` | 派生快照 | `rqgm_registry` | `ari.checkpoint.save_rqgm_registry_json` |
| `proposals/proposal_records.jsonl` | 追加式真相 | `proposal_record`（内嵌 `proposal_summary_view`） | `ari/rqgm/proposals/store.py` |
| `proposals/proposal_index.json` | 派生汇总 | 无（派生） | `ari/rqgm/proposals/store.py` |
| `rqgm_adversarial_cases.jsonl` | 追加式真相 | `rqgm_attack_records` + `rqgm_utility_record` + 重放案例行 | `ari/rqgm/adversarial/pool.py` |
| `rqgm/adversarial_replay_pool.json` | 派生快照 | `rqgm_replay_pool` | `ari.checkpoint.save_adversarial_pool_json` |
| `prompt_evolution.jsonl` | 追加式真相 | `rqgm_prompt_evolution`（内嵌 `rqgm_prompt_spec`）+ `rqgm_utility_policy_candidate`（Task 14 搭乘同一日志） | `ari/rqgm/prompt_records.py` |
| `prompt_specs.json` | 派生汇总 | `rqgm_prompt_spec` 的汇总 | `ari.checkpoint.save_prompt_specs_json` |
| `rqgm_prompts/<prompt_id>.{md,json}` | 一次写入的进化字节（`.md` 为提示词模板；`.json` 为 Task-14 策略正文） | 无 —— 字节由 `prompt_hash` 钉住 | `ari/rqgm/prompt_loader.py` |
| `rqgm_cleanroom.jsonl` | 追加式真相 | `clean_room_request` + `clean_room_bundle` | `ari/rqgm/clean_room.py` |
| `rqgm_erasure_state.json` | 派生快照 | `erasure_state` | `ari.checkpoint.save_erasure_state_json` |
| `rqgm_meta_outputs.jsonl` | 追加式真相 | `rqgm_meta`（`meta_agent_output_record`） | `ari/rqgm/meta_evolution.py` |
| `rqgm_governance_cache.jsonl` | 追加式缓存 | `rqgm_governance_cache` | `ari/rqgm/governance_cache.py` |
| `rqgm_eval_metrics.json` / `rqgm_injection_provenance.json` | 评估工具链工件（仅工具链启动的运行） | 无 —— 形状由 `ari/rqgm/evaluation/{metrics,injection}.py` 拥有 | 评估工具链 |
| `paper_archive_state.json` | paper 阶段模式溯源快照（一次写入） | 无 —— 形状由 `ari/rqgm/paper_runtime.py` 拥有 | `ari.checkpoint.save_paper_archive_state_json` |
| `paper_draft_archive.jsonl` | 追加式草稿母体（尽力而为） | 无 —— 形状由 `ari/rqgm/paper_archive.py` 拥有 | `ari/rqgm/paper_draft_executor.py` |
| `paper_anchor_corpus.jsonl` | 只读锚语料库（一次写入） | 无 —— 形状由 `ari/rqgm/paper_anchor.py` 拥有 | curation / bootstrap 工具 |
| `rqgm/paper_self_preference_stat.json` | 派生的每纪元统计（尽力而为） | 无 —— 形状由 `ari/rqgm/paper_self_preference.py` 拥有 | `ari/rqgm/paper_self_preference.py` |

## 另请参阅

- [文件格式参考](file_formats.md) —— 这些 schema 所校验的检查点
  文件。
- [配置参考](configuration.md#execution-mode-and-rqgm-governance-opt-in)
  —— `ari.mode`、`rqgm.*` 与 `proposal_router.*` 块。
- [执行模式](../guides/execution_modes.md) —— 模式激活与宪法内核。
- [RQGM 评估](../guides/rqgm_evaluation.md) —— 消费
  `rqgm_eval_metrics.json` 的消融工具链。
- `ari-core/ari/schemas/README.md` —— 每个随发布 schema 的一行
  索引。
