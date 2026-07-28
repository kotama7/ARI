---
sources:
  - path: ari-core/ari/schemas
    role: schema
  - path: ari-core/ari/paths.py
    role: implementation
  - path: ari-core/ari/checkpoint.py
    role: implementation
  - path: ari-core/ari/pipeline/verified_context.py
    role: implementation
  - path: ari-core/ari/pipeline/claim_gate
    role: implementation
last_verified: 2026-07-10
---

# 文件格式参考

每个 ARI 检查点都是一个自描述目录。本页归录了 ARI 读写的 JSON / YAML / Markdown 文件，列出规范键列表，并指向生成它们的实现。

正式以 JSON Schema 规定的 schema 请参见 `ari-core/ari/schemas/`。

## `experiment.md`

纯 Markdown 文件，有一个关键约定：一行 `Metrics: <token>, <token>, ...`，由确定性辅助函数 `parse_metric_from_experiment_md`（`ari-core/ari/pipeline/experiment_md.py:31`）提取为回退 `primary_metric`。完整指南请参见 `docs/guides/experiment_file.md`。

`generate_ideas` 运行后，流水线会附加一个幂等块，以下列方式分隔：

```markdown
<!-- AUTO-APPENDED BY VirSci (idea.json) — DO NOT EDIT -->
...
<!-- END AUTO-APPENDED -->
```

仅在标记**上方**编辑正文内容。

## `idea.json`

`ari-skill-idea.generate_ideas` 的输出。位于 `{checkpoint}/idea.json`，为 BFTS 运行的计划提供种子。

顶层结构：

```json
{
  "ideas": [
    {
      "title": "...",
      "experiment_plan": "Markdown-formatted plan with §-tags",
      "primary_metric": "GFlops/s",
      "alternatives_considered": ["..."],
      "_pinned": false
    }
  ]
}
```

子节点通过将继承条目中的 `"_pinned"` 设置为 `true` 来锁定父节点的选定 idea；后续 `generate_ideas` 运行会在其后追加新 idea 而不覆盖原有内容。

## `evaluation_criteria.json`

流水线侧缓存，派生自 `idea.json` + experiment.md。

```json
{
  "primary_metric": "GFlops/s",
  "higher_is_better": true,
  "metric_rationale": "..."
}
```

来源：`ari-core/ari/pipeline/orchestrator.py`（加载器在第 98 行左右，回退路径在第 170 行左右）。

## `tree.json`

实时 BFTS 状态，每次节点转换时重写。结构：

```json
{
  "schema_version": 1,
  "root_node_id": "...",
  "nodes": {
    "<node_id>": {
      "id": "...",
      "parent_id": "...",
      "depth": 2,
      "status": "running" | "completed" | "errored" | "pending",
      "label": "draft" | "improve" | "debug" | "ablation" | "validation" | "other",
      "metrics": {"GFlops/s": 312.4, ...},
      "score": 0.74,
      "children": ["<node_id>", ...]
    }
  }
}
```

`tree.json` 是一份*摘要*；每节点的详细信息位于 `nodes_tree.json`。

## `nodes_tree.json`

`ari-skill-transform`、`ari-skill-plot`、viz 仪表盘和 EAR 流水线所使用的完整每节点详情。结构与 `tree.json` 一致，但每个节点还包含：

| 键 | 含义 |
|---|---|
| `eval_summary` | LLM judge 的自然语言裁决 |
| `metrics_with_metadata` | 每个指标的置信度 + 提取代码 |
| `has_real_data` | 评估器确认为真实测量值时为 `true` |
| `trace_log` | `{role, content}` 记录列表（LLM + 工具消息） |
| `work_dir` | 每节点工作目录（相对于检查点根目录） |
| `artifacts` | 节点生成的文件，含 sha256 |

## `node_report.json`

在 `mark_success` / `mark_failed` 时写入的每节点自报告。Schema：`ari-core/ari/schemas/node_report.schema.json`。

必需键：`schema_version`（常量 `1`）、`node_id`、`label`、`depth`、`status`、`files_changed`、`metrics`、`artifacts`。

```json
{
  "schema_version": 1,
  "node_id": "...",
  "parent_id": "...",
  "ancestor_ids": ["..."],
  "label": "improve",
  "depth": 2,
  "status": "completed",
  "started_at": "2026-05-08T11:30:00Z",
  "completed_at": "2026-05-08T11:42:00Z",
  "files_changed": {
    "added":    [{"path": "src/main.cpp", "sha256": "..."}],
    "modified": [{"path": "Makefile",     "sha256": "..."}],
    "deleted":  [],
    "inherited_unchanged": []
  },
  "metrics": {"GFlops/s": 312.4},
  "artifacts": [{"path": "results.csv", "sha256": "..."}]
}
```

`generate_ear`、`nodes_to_science_data` 和 `bfts.expand` 会读取此文件。

## `results.json`

运行完成时生成的最终聚合结果。

```json
{
  "run_id": "...",
  "experiment_goal": "...",
  "primary_metric": "GFlops/s",
  "best_node": {"id": "...", "metrics": {...}, "score": 0.91},
  "nodes": {
    "<node_id>": {"metrics": {...}, "has_real_data": true, ...}
  }
}
```

`ari-skill-coding.emit_results` 写入的每节点 `results*.json` 文件还可能携带一个可选的 `_provenance` 键——一个标记每个上报值来源的 `{operand: source}` 映射（测得的天花板用 `microbench` / `benchmark`，校验残差用 `correctness` / `reference`，其余用 `declared` / `constant`）。为空时省略该键。claim-evidence 硬门（经由 `science_data.json` 的 `configurations[]._provenance`）读取它，以确认确实运行了测得的天花板或正确性检查。

## `science_data.json`

由 `ari-skill-transform.nodes_to_science_data` 从已执行节点的证据构建的面向论文的科学数据面。除 `configurations[]` / `experiment_context` / `summary_stats` 外，它还保存 claim-evidence 硬门验证的 Research Contract 基底：

| 键 | 含义 |
|---|---|
| `claims` | 从节点证据确定性派生的候选声明；每条声明锚定到真实的 `node_id` + `metric_path`。正文是论文撰写器在保留 `% CLAIM:Cx:NCx` 锚点的同时重写的模板种子。 |
| `numeric_assertions` | 硬门重新推导并在容差内与论文上报数值比较的操作数/公式记录。 |
| `metric_contract` | 从 `metric_contract.json`（见下文）graft 而来的 idea 所有的指标正确性契约，使硬门强制执行*声明的*契约，而不仅是通用不变式注册表。 |

`_config_nodes`、`_anomalies`、`_anomalous_metrics` 是内部（下划线前缀）注释，不属于面向论文的数据面。

## `metric_contract.json`

由 `make_metric_spec`（ari-skill-evaluator）生成、写入 `idea.json` / `tree.json` 旁的 `{checkpoint}/metric_contract.json` 的 idea 所有的指标正确性契约，以便 `nodes_to_science_data` 将其 graft 到 `science_data.json`。所有表达式均为受限 AST（参见 `ari-core/ari/pipeline/claim_gate/formula_eval.py`）。

```json
{
  "key": "<metric the paper reports>",
  "formula": "geomean(gflops_byK / ceiling_byK)",
  "ceiling_select": "cache_bw if effective_bw > dram_peak_bw else dram_peak_bw",
  "invariants": ["value <= 1", "model_sec <= sec"],
  "correctness": {"expr": "max_abs_err < 1e-4", "requires": ["max_abs_err"]},
  "required_measured": ["dram_peak_bw", "cache_bw", "ceiling_byK"],
  "claims": [{"claim": "...", "required_evidence": ["thp_on_tput", "thp_off_tput"]}],
  "correctness_required": true,
  "ceiling_must_be_measured": true,
  "tolerance": {"absolute": 0.0, "relative": 0.02}
}
```

`correctness_required` / `ceiling_must_be_measured` 是 agent 无法丢弃的 idea 所有标志；它们由 `results.json._provenance` 中的证据标签（测得来源的天花板、正确性来源的残差）满足，而非由 agent 声明的名称满足。来源：`ari-core/ari/pipeline/claim_gate/contract.py`。

## `verified_context.json`

限定到最佳节点 root→best 谱系的、由产物支撑的声明，由 `ari-core/ari/pipeline/verified_context.py` 写入，使 `write_paper` 阶段能够将其定量声明落地于经验证、由产物支撑（理想情况下已复现）的结果。**仅**当类型化 research-memory 存储中至少有一条有支撑的声明时才写入——存储为空时不留下文件，论文阶段的行为与之前完全一致。

```json
{
  "best_node_id": "...",
  "lineage": ["<root_id>", "...", "<best_id>"],
  "claims": [...],
  "limitations": [...],
  "usable_for_claims": [
    {"text": "...", "repro_status": "rerun_passed" | "unverified",
     "artifact_refs": [{"path": "...", "sha256": "..."}]}
  ]
}
```

## `paper_claim_links.json`

对论文的 `% CLAIM:Cx:NCx` 锚点与 `science_data.json` 声明注册表的确定性（无 LLM）对账结果，由 `ari-skill-paper.link_paper_claims` 在 `write_paper`（draft）后以及 `paper_refine`（final）后生成。

| 键 | 含义 |
|---|---|
| `paper_claim_links` | 以锚点为键的记录（`claim_id` / `numeric_id` / `section` / `span_hash` / `line_range` / figures）。**锚点**是在 refine/render 中保持稳定的键，`span_hash` 检测句子变更。 |
| `numeric_mentions` | 论文中每个数值 token 的分类（`result_claim` / `experimental_setting` / `citation_year` / `figure_table_ref` / `ambiguous`），含章节归属和 `requires_assertion` 标志。 |
| `figure_refs` | 论文中实际引用的图 id（图绑定记录于此，`science_data.json` 永不被修改）。 |
| `unresolved_anchors` / `uncovered_numeric_candidates` | 硬门消费的诊断信息。 |

## `evaluation/claim_evidence_hard_gate_{draft,final}.json`

由 `ari-skill-evaluator.claim_evidence_hard_gate` 写入的确定性 claim/evidence 硬门报告（每个 `phase` 一份：`draft`，随后 `final`）。它验证声明存在性、数值重算、数值覆盖、图存在性以及声明的 `metric_contract`——它检查论文与已记录结果之间的转录/推导一致性，**而非**结果本身的真实性。

```json
{
  "gate": "claim_evidence_hard_gate",
  "phase": "final",
  "policy": "strict" | "warn",
  "status": "...",
  "should_block": true,
  "errors": [...],
  "warnings": [...],
  "metrics": {"total_claims": 0, "grounded_claims": 0, ...}
}
```

MCP 包装器将 `should_block`（仅在 strict 策略下的 `phase: final`，或在客观虚假发现时设置）转换为流水线硬失败，从而跳过 finalize。来源：`ari-core/ari/pipeline/claim_gate/gate.py`。

## `evaluation/evidence_grounded_semantic_review.json`

由 `ari-skill-evaluator.evidence_grounded_semantic_review` 写入的非阻塞、由证据支撑的语义评审。它基于硬门证据检测过度声称 / 解释问题，并为 `paper_refine` 输出 `suggested_revisions`。绝不阻塞流水线；出错时返回空的（`status: "ok"`）评审。refine 后的过程会在其旁写入 `evidence_grounded_semantic_review_post_refine.json` 变体。

## `lineage_decisions.jsonl`（v0.7.0）

停滞规则决策的仅追加日志。每行一条 JSON 记录：

```json
{"node_id": "...", "decision": "switch_to_idea", "rationale": "...", "ts": "..."}
{"node_id": "...", "decision": "fanout",        "rationale": "...", "ts": "..."}
```

决策类型：`continue` / `switch_to_idea` / `fanout` / `terminate`。来源：`ari-core/ari/orchestrator/lineage_decision.py`。

## RQGM 纪元治理文件（可选启用的 `ari_rqgm` 模式）

仅当 `ari.mode: ari_rqgm` **且** `rqgm.enabled: true` 一致时才写入
（docs/plans/ari_rqgm Task 02）。在所有默认 `simple_bfts` 检查点上
均不存在；每个读取方都把缺失视为「RQGM 从未运行」。来源：
`ari-core/ari/rqgm/store.py`；JSON Schema：
`ari-core/ari/schemas/{epoch_state,rqgm_registry,rqgm_transition_event,rqgm_defs}.schema.json`。

### `rqgm_transitions.jsonl`

纪元/注册表治理状态的**真相源**。追加式、哈希链式的 JSONL；每行
一个自包含事件：

```json
{"schema_version": 1, "event_id": "evt_000042", "event_type": "prompt_status_change",
 "payload": {"prompt_id": "reviewer_prompt_v4", "from_status": "shadow",
             "to_status": "probationary_active", "transition_id": "transition_003_to_004"},
 "event_hash": "112233445566", "prev_event_hash": "77aa88bb99cc",
 "ts": 1751700000.0, "ts_iso": "2026-07-05T12:00:00Z"}
```

`event_hash = sha256(canonical_json(payload))[:12]`（与提示词溯源
相同的 `hash12` 方案 —— 不存在第二套方案）；`prev_event_hash` 链到
上一行（首行为 `""`）。时间戳是被哈希载荷之外的元数据。事件类型
（封闭 v1 集合）：`epoch_transaction_prepare`、
`component_registered`、`prompt_registered`、
`component_status_change`、`prompt_status_change`、`epoch_close`、
`epoch_open`、`epoch_transaction_commit`、`emergency_quarantine`
（唯一的纪元中途变更）。注册表状态变更**只**通过纪元边界的
prepare/commit 事务被接受；加载时，位于一个没有匹配 commit 的
prepare 之后的事件被忽略（崩溃恢复）。

状态变更载荷由 RegistryTransitionEngine 提供（RQGM Task 09，
`ari-core/ari/rqgm/transition_engine.py` —— 唯一的注册表状态写入
方）：每条都携带 `transition_id`、一个固定的 T1-T21 `rule_id`
（`ari/rqgm/transition_rules.py`；拓扑是冻结代码，仅
`rqgm.transition.*` 数值阈值可配置）、`from_status` /
`to_status`、`evidence_refs`、
`produced_by: registry_transition_engine`（内核 CK-REG-004），
以及冻结边界输入（GovernanceReport + 候选评估 + 注册表哈希）的
`inputs_sha256` 内容哈希，使每次已提交变更都可确定性重放。

### `rqgm_audit.jsonl`

RQGM 的 **ImmutableAuditLog**：同样的追加式哈希链式行信封，带独立
的按文件链。写入其中的治理记录载荷由 GovernanceOrchestrator 拥有
（RQGM Task 05）；链完整性校验属于 ConstitutionalKernel
（Task 04）。内核裁定以 `kernel_report` 条目追加：
`{"context": ..., "constitution_hash": ..., "blocking": ...,
"violations": [{"code": "CK-…", "check": ..., "severity": ...,
"subject_ref": ..., "rule_id": ..., "detail": ...}]}` —— 每次裁定
均可重放。

在每个纪元边界，GovernanceOrchestrator 的 `audit_epoch` 把它的
记录追加到这里（全部携带共同的 `rqgm_record_base` 信封）：
`evidence_bundle`（仅 EvidenceClerk 可撰写）、`impeachment_motion`
（仅 Auditor 可撰写；同角色指控在构造上即被拒绝并被内核否决）、
`governance_defense`、`impeachment_outcome`，以及最终的
`governance_report`（schema：
`ari-core/ari/schemas/governance_report.schema.json`；
`recommendations[].action` 是封闭集合 `promote_candidate | promote |
demote | warn | quarantine | retire | no_action`，由 Task 09
消费）。一个纪元的最新报告是带该 `epoch_id` 的「最后」一条
`governance_report` 行（审计崩溃后的重跑会追加新的记录 id；之前的
部分记录作为历史保留）。不存在治理快照文件；JSONL 就是真相。

RegistryTransitionEngine（RQGM Task 09）还会把每次边界决议作为
`epoch_transition` 记录审计到这里（schema：
`ari-core/ari/schemas/epoch_transition.schema.json`；`status` 为
`pending | committed | aborted | rejected | failed` 之一 ——
被中止/被内核阻断的转换会被记录但**不**施加任何注册表变更），
并在每次已提交的退役上（T17，以及角色范围的 T20 `utility_policy`
取代）追加 `retirement_event` 记录，在每次已提交的 T17 退役上追加
`clean_room_generation_request` 记录（由 Task 08/10 消费）。

FrontierRepairEngine（RQGM Task 10，
`ari-core/ari/rqgm/frontier_repair.py`）在每次带退役的已提交转换
上追加另外三种行：

- `selective_erasure` —— 一条 `SelectiveErasureEvent`（schema：
  `ari-core/ari/schemas/selective_erasure_event.schema.json`）：
  内核所写（`prompt_hash` 为 null，`component_id` 为
  `frontier_repair_engine`），列出已退役的哈希/组件、直接 + 传递
  的过期记录 id，以及被无效化/重算/放弃的节点 id。擦除是**仅
  逻辑的**（不变量 13）：所列记录在 `rqgm_erasure_state.json` 中
  被打标，绝不重写或删除。
- `frontier_rebuild` —— 一条 `FrontierRebuildEvent`（schema：
  `ari-core/ari/schemas/frontier_rebuild_event.schema.json`）：
  `frontier_before/after`、被移除/被复位的节点 id（对获胜子节点
  被擦除的父节点的规则 A 复位）、被重算的节点 id，以及
  `kernel_validation`。两种事件的 `status` 均为
  `applied | conservative | halted_expansion`（§5.6 的
  fail-closed 降级阶梯）。
- `utility_record` —— 每当 reviewer/adversary/defender/judge 的
  擦除留下幸存的已评分证据时，一条**重算的** UtilityRecord
  （schema：`ari-core/ari/schemas/rqgm_utility_record.schema.json`
  外加 `supersedes: <stale record_id>` 和
  `recomputed_in_epoch`）：在「原始」纪元的冻结权重下由幸存输入
  重算，绝不重新缩放 —— 被取代的记录留在磁盘上，标记为过期。

### `constitution.yaml`

宪法层的人类可读声明，在 `ari run` 启动时从打包的
`ari-core/config/constitution.yaml` 复制「一次」（绝不覆盖，仅
`ari_rqgm`；在 `simple_bfts` 检查点上不存在）。权威规则是冻结代码
（`ari/rqgm/kernel_rules.py` + `ari/rqgm/transition_rules.py`），
由 `constitution_hash` —— `sha256(canonical_json(<全部规则表>))[:12]`
—— 钉住，该哈希还以可选的 `constitution_hash` 键增量式地记录进
`meta.json`。

### `epoch_state.json`

当前打开（或最近关闭）纪元的派生整写快照：冻结的活跃组件集合、
活跃提示词哈希、效用策略、`registry_version`，以及确定性的
`epoch_fingerprint`（`created_at` 是元数据，被指纹排除）。可
丢弃 —— 加载时对照事件日志重放校验，不匹配则重建。

### `rqgm_registry.json`

把 ComponentRegistry + PromptRegistry 合入一个文件的派生整写快照
（`registry_version`、`as_of_event_hash`、`components[]`、
`prompts[]`）。提示词条目按来源引用其文本（`committed_template`
加载键；`checkpoint_file` 为 `rqgm_prompts/` 下一次写入的
进化提示词本体；`policy` 为 Task 14 的受治 utility-policy 本体，按 `path` 引用），并
同时携带 `prompt_hash`（`sha256[:12]`）与完整的 `prompt_sha256`。
状态生命周期（提示词与组件共享）：
`candidate → validated → shadow → probationary_active → active`、
`active → warning | probation | quarantine`、
`quarantine → retired → banned` —— 变更只经由转换事件。

### `proposals/`（RQGM Task 03）

检查点范围的提案存储 —— 「存储全部；只把摘要交给 BFTS」。只由
`ari_rqgm` 的 ProposalRouter 或显式选择启用的
`proposal_router.record_only` 双写创建；默认的 `simple_bfts` 运行
**不**创建任何 `proposals/` 目录。来源：
`ari-core/ari/rqgm/proposals/store.py`；JSON Schema：
`ari-core/ari/schemas/{proposal_record,proposal_summary_view}.schema.json`。

```
proposals/
  proposal_records.jsonl       # append-only truth (one ProposalRecord per line)
  proposal_index.json          # derived rollup: record_id → status/generator/epoch
  archive/<record_id>/…        # raw outputs, transcripts refs, generator configs
```

`proposal_records.jsonl` 的每一行都携带必备的 RQGM 记录字段
（`record_id` `prop_%06d`、`epoch_id` —— 仅记录模式下为 `null`、
`component_id`、`role: "generator"`、`prompt_hash` —— 标准的
`sha256[:12]`，遗留导入为 `null`、`created_at`、`source_refs`、
`status: candidate|selected|expanded|superseded`），外加
`generator`
（`cheap|mutation|attack_driven|prior_art|virsci|legacy_idea_json`）、
内联的有界 `summary`（ProposalSummaryView；BFTS 所见的「唯一」
形状）、`archive_refs`（检查点相对引用，绝不复制），以及仅逻辑的
`stale` / `valid_for_frontier` 标志（读取时语义由 RQGM Task 10
拥有；已存 JSONL 绝不重写）。记录按内容键（generator +
source_refs + summary）去重，因此被重试的 MCP 调用绝不产生重复
行。在 `ari_rqgm` 中，`idea.json` 是该存储对这些记录维护的兼容性
投影（固定的想法保持在前；`_pinned` / `_inherited_from` /
`_root_choice` 标记逐字保留；`ideas[i]._proposal_record_id` 链接
回记录）。

### `rqgm_adversarial_cases.jsonl`（RQGM Task 06）

对抗进化循环的追加式真相（每行一个 JSON，带锁保护，绝不抛出 ——
`lineage_decisions.jsonl` 的姿态）。仅当 `ari_rqgm` 的对抗回合
运行时才创建；在所有 `simple_bfts` 检查点上均不存在。来源：
`ari-core/ari/rqgm/adversarial/pool.py`；JSON Schema：
`ari-core/ari/schemas/{rqgm_attack_records,
rqgm_utility_record,rqgm_replay_pool}.schema.json`。行类型，按每
节点 §5.3 的顺序 raw → defense → judgment → validated → utility：

- `rqgm_adversarial_round` —— 每节点的幂等标记（`node_id`、
  `epoch_id`）：回合每节点至多运行一次，resume 安全。
- `raw_attack` —— 一次对抗者攻击（`atk_%06d`，角色
  `adversary`）。目标是一个**封闭的工件集合**（`proposal |
  experiment_plan | node_report | metric_result | paper_claim |
  novelty_claim | citation_claim | reproducibility_claim`）——
  绝不是组件 —— 且必须引用 ≥ 1 个 `attack_evidence_refs`。仅为
  审计材料：原始攻击从不触碰任何分数（不变量 8）。
- `defender_response` —— 对每次攻击的 `rebut | concede |
  propose_fix`（`def_%06d`，角色 `defender`）。
- `judgment_record` —— ArtifactJudge 的裁定
  `valid | partially_valid | invalid`，附裁判指定的严重度
  （`jdg_%06d`，角色 `judge`）；总是写入，即使为 `invalid`。
- `validated_attack` —— **仅**对 `valid | partially_valid` 裁定
  存在（`vat_%06d`；必须经过裁决，不变量 9）。
- `utility_record` —— §5.4 惩罚通道的审计记录（`utl_%06d`，角色
  `utility_policy`）：`base_score` / `penalty` / `final_score`、
  按值内嵌的纪元冻结策略权重，以及
  `input_refs.validated_attack_ids`（只要 `penalty > 0` 即非
  空）。
- `adversarial_replay_case` —— 在纪元边界被准入的一条
  AdversarialReplayCase（`adv_case_%05d`）：`replay_view`（完整
  材料；对角色 `clean_room_generator` 拒绝）+ `abstract_view`
  （污染安全的 FailureSummary —— 不含原始攻防文本）。

被惩罚的节点还携带增量的 `Node.metrics` 键
`_pre_penalty_score` 和 `_validated_attack_penalty`；
`_scientific_score` 被重写（sterile-gate 先例），绝不被遮蔽。

### `rqgm/adversarial_replay_pool.json`（RQGM Task 06）

AdversarialReplayPool 的派生字节固定快照（`schema_version`、
`case_seq`、`cases[]`），由 GovernanceOrchestrator 的第 7 步在
纪元边界重写；`rqgm_adversarial_cases.jsonl` 仍是真相源，并在
加载时补齐任何崩溃尾部。逐出是仅逻辑的（`status: "evicted"`；
JSONL 中不移除任何内容）。

### `prompt_evolution.jsonl`（RQGM Task 07）

提示词进化的追加式真相（以 `prompt_trace.jsonl` 为范本的
fail-open 写入器）。仅当 `ari_rqgm` 的提示词进化流水线运行时才
创建；在所有 `simple_bfts` 检查点上均不存在。来源：
`ari-core/ari/rqgm/prompt_evolution.py`；JSON Schema：
`ari-core/ari/schemas/rqgm_prompt_evolution.schema.json`。行类型：

- `prompt_candidate` —— 一个 PromptMutator/洁净室输出
  （`pcand_%05d`），携带完整内嵌的 PromptSpec
  （`ari-core/ari/schemas/rqgm_prompt_spec.schema.json`）；总是以
  `status: "candidate"` 出生 —— 没有即时激活。
- `prompt_candidate_validation` —— 一次生命周期阶段执行
  （`pval_%05d`；阶段 `static_validation → constitutional_validation →
  schema_dry_run → replay_evaluation → anchor_evaluation → shadow`，
  单调 —— 记录链使跳过阶段可被检测）。
- `comparison_observation` —— 一个 shadow 并排样本
  （`cobs_%05d`）：只有输入/输出**哈希**和分歧摘要 —— shadow
  输出文本从不触达本文件、节点指标或前沿（仅观察）。

进入 `probationary_active`/`active` 的采纳**只**通过
RegistryTransitionEngine 在 `rqgm_transitions.jsonl` 中的纪元边界
事务发生（Task 09），绝不通过本文件。

### `prompt_specs.json`（RQGM Task 07）

提示词进化注册表视图的派生汇总
（`schema_version`、`specs{candidate_id → prompt_spec,
stages_passed, rejected}`），在纪元边界和运行结束时尽力重写
（`prompt_versions.json` 模式）；`prompt_evolution.jsonl` 仍是
真相源。

### `rqgm_prompts/`（RQGM Task 07）

检查点范围的进化模板正文，每个进化提示词一个一次写入的
`<prompt_id>.md`（不同内容的重写会被拒绝 —— 活跃提示词文本永不
原地修改；变更即铸造新的 `prompt_id`）。字节由
`prompt_hash = sha256(text)[:12]` 钉住 —— 与
`FilesystemPromptLoader.load_versioned` 完全相同的方案。Gate 10
的例外条款：报告附录恰好覆盖已提交的 `ari-core/ari/prompts/**`
模板；运行时进化的提示词改由本目录加上 `prompt_trace.jsonl` 的
溯源字段（`prompt_version`、`prompt_registry_version`）覆盖。
`rqgm_prompts/` 的缺失 == 完全由已提交提示词构成的轨迹
（`bfts_web_provenance.json` 的 P5 模式应用于提示词）。

### `rqgm_cleanroom.jsonl`（RQGM Task 08）

洁净室再生成的追加式真相（以 `prompt_evolution.jsonl` 为范本的
fail-open 写入器）。仅当某次退役产生
`EpochTransition.clean_room_requests` 时才创建；在所有
`simple_bfts` 检查点上均不存在。来源：
`ari-core/ari/rqgm/clean_room.py`；JSON Schema：
`ari-core/ari/schemas/clean_room_request.schema.json`（请求）和
`ari-core/ari/schemas/clean_room_bundle.schema.json`（封闭输入
bundle）。事件种类（`event` 字段）：

- `request_created` —— 一条完整的 `CleanRoomGenerationRequest`
  （五个禁止输入标志为 const-false；请求在 resume 时从本文件
  重放 —— pending 的请求在下一个纪元边界、在
  `rqgm.prompt_evolution.max_clean_room_generations_per_epoch`
  预算下重试）。
- `bundle_assembled` —— `bundle_id` + `bundle_hash`（对规范
  bundle 载荷的 hash12；除已提交的
  `rqgm/clean_room_generator.md` 元提示词外，该 bundle 就是
  生成器的「全部」上下文）。
- `generation_attempted` —— 单次补全标记，带
  `rendered_prompt_hash`（审计：恰好是元提示词 + 规范 bundle
  JSON 到达了 LLM）。
- `clean_room_violation` / `candidate_rejected_contaminated` ——
  内核 CK-CLN-001/CK-CLN-002 筛查发现；被污染的候选绝不进入
  Task 07 生命周期（准入处阻断，对运行 fail-open）。
- `candidate_registered` —— 以 `status: "candidate"` 交接进
  `prompt_evolution.jsonl`（绝不即时激活）。
- `request_status` —— 请求状态转换
  （`pending|generating|generated|rejected_contaminated|failed|superseded`）。
- `fallback_to_baseline` —— 无空缺规则：没有活跃提示词也没有可
  准入候选的角色回退到其已提交的基线模板。

### `rqgm_erasure_state.json`（RQGM Task 10）

选择性擦除过期状态的派生整写快照，可通过折叠
`rqgm_audit.jsonl` 中的每个 `selective_erasure` /
`frontier_rebuild` 事件重建（`prompt_trace` → `prompt_versions`
的「JSONL 是真相、快照是派生」先例）。仅当修复运行过才创建；在
所有 `simple_bfts` 检查点和没有退役的运行上均不存在。来源：
`ari-core/ari/rqgm/erasure_state.py`（写入统一经
`ari.checkpoint.save_erasure_state_json`；`indent=2,
ensure_ascii=False`）；JSON Schema：
`ari-core/ari/schemas/erasure_state.schema.json`。注册在
`PathManager.META_FILES` 和 node_report 的 `files_changed`
黑名单中。

```json
{
  "schema_version": 1,
  "retired_prompt_hashes": {"a1b2c3d4e5f6": {"retirement_event_id": "retire_00042",
                                              "retired_in_epoch": "epoch_004"}},
  "stale_record_ids": {"review_00311": "erase_00007"},
  "invalid_frontier_node_ids": {"node_031": "erase_00007"},
  "last_erasure_event_id": "erase_00007",
  "last_rebuild_event_id": "rebuild_00007"
}
```

过期状态是**读取时**判定的：一条记录过期当且仅当其 `record_id`
在 `stale_record_ids` 中 —— 已存 JSONL 行绝不重写（不变量 13），
且本文件缺失意味着「无过期，全部有效」（Task-10 之前的检查点
保持有效）。被擦除/无效化的节点还携带增量的 `Node.metrics` 哨兵
键 `_stale`、`_valid_for_frontier`、`_stale_reason`
（`generator_retired | utility_invalidated |
trace_depth_exceeded` —— 仅诊断用）和 `_erasure_event_id`，通过
`tree.json` 持久化；即使切回 `simple_bfts` 模式，它们也让被擦除
的节点保持被排除（污染不会因为切换模式而变干净）。

### `rqgm_governance_cache.jsonl`（RQGM Task 12）

治理结果缓存：追加式 JSONL，每条缓存的治理评估一条记录。来源：
`ari-core/ari/rqgm/governance_cache.py`；JSON Schema：
`ari-core/ari/schemas/rqgm_governance_cache.schema.json`。注册在
`PathManager.META_FILES` / `_TRACE_FILES` 和 node_report 的
`files_changed` 黑名单中。缺失 == 空缓存，绝不是错误；在所有
`simple_bfts` 检查点上均不存在。

```json
{"schema_version": 1, "cache_key": "a3f19c02b7d4e881", "role": "judge",
 "epoch_id": "epoch_004", "prompt_hash": "9f2c01ab34de",
 "artifact_hash": "sha256:…", "input_context_hash": "sha256:…",
 "output_schema_hash": "sha256:…", "result_ref": "judgment_00042",
 "score": 0.8, "created_at": "2026-07-05T00:00:00Z"}
```

`cache_key = sha256(artifact_hash ␟ prompt_hash ␟ role ␟ epoch_id ␟
input_context_hash ␟ output_schema_hash)[:16]`（`␟` = `\x1f`）；
两个内容哈希是对规范 JSON 的完整 sha256。`created_at` 仅为溯源
—— 绝不参与键（P2）。重放查询
（`rqgm.replay.use_cached_results`）用案例的**来源**纪元 id 和
候选自己的 `prompt_hash` 计算键 —— 唯一被许可的跨纪元命中；纪元
边界的候选评估先查询此缓存，并把由池派生的逐案例 `score` 写回
（`ari-core/ari/rqgm/governance/_adjudication.py`）。条目从不
原地失效：已退役提示词的条目只是不再可被寻址，因为其
`prompt_hash` 不会再出现在查询中（不变量 13）。预算消耗与治理
级别分配「不」存放在这里 —— 它们以 `budget_consumed` /
`budget_degraded` / `governance_level` 行的形式记入
`rqgm_audit.jsonl`（来源：`ari-core/ari/rqgm/budget.py`），每纪元
预算计数器也因此在 `ari resume` 后幸存。

### `rqgm_eval_metrics.json` / `rqgm_injection_provenance.json`（RQGM Task 13）

评估工具链工件，「只」写在由
`scripts/rqgm_eval/run_ablation.py` 工具链自己启动的运行上
（两种模式下的所有正常检查点上均不存在）。来源：
`ari-core/ari/rqgm/evaluation/{metrics,injection}.py`。两者都
注册在 `PathManager.META_FILES` 和 node_report 的
`files_changed` 黑名单中。

- `rqgm_eval_metrics.json` —— `compute_metric_report` 的十三个
  事后指标（对持久化工件的纯函数；无 LLM，派生值中无挂钟 ——
  指标 13 仅为元数据，从不哈希）。信封：`schema_version`、
  `computed_by_version`、`condition_id`、`run_id`、`seed`、
  `config_digest`（`workflow.yaml` 的 sha256-12）、
  `injection_ids`，以及按固定的计划 §5.4 键顺序排列的
  `metrics{key → {value, numerator, denominator, evidence_refs,
  applicable[, detail]}}`。数据源缺失时产出
  `applicable: false`，绝不是错误。
- `rqgm_injection_provenance.json` —— 持久的合成轨迹标记
  （`bfts_web_provenance.json` 先例）：`schema_version`、
  `injection_ids`（保留的 `eval_*` 命名空间，与 `adv_*` /
  `anchor_*` 案例不相交）、`specs_digest`（对按 id 排序的规范
  规格列表的 hash12）、`harness_version`。任何携带此文件的检查
  点都是被注入的评估运行，绝不能被误认为真实运行。

活动级输出（`ablation_report.{json,md}`、展开后的条件配置）位于
检查点之外的 `workspace/rqgm_eval/<eval_id>/` 下 —— 见
`docs/guides/rqgm_evaluation.md`。

## `settings.json`

viz 仪表盘使用的每检查点设置。

```json
{
  "model": "ollama/qwen3:32b",
  "provider": "ollama",
  "hpc": {"partition": "your_partition", "cpus": 64},
  "registries": [
    {"name": "default", "url": "http://127.0.0.1:8290", "token_env": "ARI_REGISTRY_TOKEN"}
  ]
}
```

API 密钥**绝不**存储在此处 — 它们存放在 `.env` 文件中（搜索顺序：checkpoint → ARI root → ari-core → home）。

## `workflow.yaml`

由 `ari-core/ari/pipeline/yaml_loader.py` 解析的流水线定义。每个阶段指定要调用的技能 + 工具以及输入/输出。

```yaml
stages:
  - name: idea_generation
    skill: idea
    tool: generate_ideas
    inputs:
      - experiment.md
    outputs:
      - idea.json
  - name: bfts
    skill: orchestrator
    ...
```

捆绑的默认值位于 `ari-core/ari/configs/workflow.default.yaml`。

## `memory_store.jsonl` / `memory_backup.jsonl.gz`

写入 `ARI_CHECKPOINT_DIR` 下的记忆后端产物：

| 文件 | 后端 | 备注 |
|---|---|---|
| `memory_store.jsonl` | `file` | 旧版 v0.5 格式，行分隔 JSON 条目 |
| `memory_backup.jsonl.gz` | `letta` | 可移植快照（在阶段边界 + 退出时自动写入） |
| `memory_access.jsonl` | 任意 | 写入/读取操作的仅追加遥测数据 |

快照记录结构：

```json
{
  "node_id": "...",
  "ancestor_ids": ["..."],
  "kind": "node_scope" | "react_trace",
  "text": "...",
  "metadata": {...},
  "ts": "..."
}
```

## EAR bundle（v0.7.0）

`{checkpoint}/ear/` 是候选集；`{checkpoint}/ear_published/` 是已策展并发布到后端的子集。信任锚点为：

```
ear_published/
├── manifest.lock         # canonical JSON, files-only sha256 + bundle_sha256
├── publish_record.json   # backend, ref, sha256, visibility
└── ...                   # curated artefacts
```

`manifest.lock` schema：`ari-core/ari/schemas/publish.schema.json`。`bundle_sha256` 必须等于烧入已发布论文的 `\codedigest{...}` 宏。

## 另请参阅

- `docs/concepts/architecture.md`（检查点目录布局）— 相同文件的叙述视图。
- `ari-core/ari/schemas/` — `node_report` 和发布 manifest 的正式 JSON Schema。
- `ari-core/ari/pipeline/yaml_loader.py` — workflow.yaml 解析器。
- `docs/guides/experiment_file.md` — 详细的 `experiment.md` 指南。
