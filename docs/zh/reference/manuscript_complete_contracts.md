---
sources:
  - path: ari-core/ari/manuscript/contracts.py
    role: implementation
  - path: ari-core/ari/manuscript/digest.py
    role: implementation
  - path: ari-core/ari/manuscript/snapshot.py
    role: implementation
  - path: ari-core/ari/manuscript/builder.py
    role: implementation
  - path: ari-core/ari/manuscript/profiles.py
    role: implementation
  - path: ari-core/ari/manuscript/readiness.py
    role: implementation
  - path: ari-core/ari/manuscript/briefs.py
    role: implementation
  - path: ari-core/ari/manuscript/coordinator.py
    role: implementation
  - path: ari-core/ari/manuscript/state.py
    role: implementation
  - path: ari-core/ari/manuscript/repair.py
    role: implementation
  - path: ari-core/ari/manuscript/publication.py
    role: implementation
  - path: ari-core/ari/manuscript/runtime.py
    role: implementation
  - path: ari-core/ari/manuscript/evaluation.py
    role: implementation
  - path: ari-core/ari/public/manuscript.py
    role: implementation
  - path: ari-core/ari/paper_contract.py
    role: implementation
  - path: ari-core/ari/cli/manuscript.py
    role: implementation
  - path: ari-core/ari/cli/manuscript_repair_runtime.py
    role: implementation
  - path: ari-core/ari/cli/paper_dispatch.py
    role: implementation
  - path: ari-core/ari/rqgm/paper_runtime.py
    role: implementation
  - path: ari-core/ari/rqgm/paper_draft_executor.py
    role: implementation
  - path: ari-core/ari/rqgm/kernel_harness_integrity.py
    role: implementation
  - path: ari-core/ari/rqgm/evaluation/kca_probe.py
    role: implementation
  - path: ari-core/ari/core.py
    role: implementation
  - path: ari-core/ari/pipeline/stages.py
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
  - path: ari-core/ari/schemas/manuscript_requirement_profile_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/manuscript_exploration_snapshot_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/manuscript_omission_manifest_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/manuscript_context_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/manuscript_readiness_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/manuscript_section_brief_bundle_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/manuscript_authoring_binding_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/manuscript_segment_record_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/research_repair_request_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/research_repair_plan_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/manuscript_repair_transaction_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/manuscript_auto_repair_round_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/manuscript_publication_decision_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/manuscript_publication_lock_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/manuscript_evaluation_report_v1.schema.json
    role: schema
  - path: ari-core/ari/schemas/manuscript_transition_v1.schema.json
    role: schema
  - path: scripts/sync_manuscript_schemas.py
    role: implementation
  - path: scripts/evaluate_manuscript_complete.py
    role: implementation
  - path: scripts/run_manuscript_complete_release.py
    role: implementation
  - path: scripts/manuscript_complete_release_gates.json
    role: config
last_verified: 2026-08-09
---

# Manuscript Complete V1 契约

所有规范文档都拒绝 unknown field，使用安全的 checkpoint 相对路径与 canonical JSON
的 SHA-256 identity，并在 read 时校验自己声明的 digest。生成的 JSON Schema 位于
`ari-core/ari/schemas/`，用以下命令检查：

```bash
PYTHONPATH=ari-core python scripts/sync_manuscript_schemas.py --check
```

| Document | Schema version | 恒久角色 |
|---|---|---|
| requirement profile | `ari.manuscript-requirement-profile/v1` | requirement、适用性与 severity |
| exploration snapshot | `ari.manuscript-exploration-snapshot/v1` | 完整的 node/artifact inventory 与 scientific winner |
| omission manifest | `ari.manuscript-omission-manifest/v1` | included 与 omitted 合起来的 inventory 守恒 |
| context | `ari.manuscript-context/v1` | 确定性的、面向 requirement 的 projection |
| readiness | `ari.manuscript-readiness/v1` | 逐 requirement 的 status 与 authoring/publication verdict |
| section brief bundle | `ari.manuscript-section-brief-bundle/v1` | 有界、感知 lane 的 writer 输入，不存在静默的必需项 omission |
| authoring binding | `ari.manuscript-authoring-binding/v1` | 确切的 profile/context/readiness/brief 与 target build |
| segment record | `ari.manuscript-segment-record/v1` | 可恢复的 workflow 输入/输出 transaction |
| repair request/plan | `ari.research-repair-request/v1`、`ari.research-repair-plan/v1` | 固定的 action、authority 与累计 budget |
| repair transaction | `ari.manuscript-repair-transaction/v1` | 已提交且不可变的 resolver 结果与确切的资源用量 |
| automatic repair round | `ari.manuscript-auto-repair-round/v1` | 连续的 coordinator round 与累计用量 |
| publication decision | `ari.manuscript-publication-decision/v1` | 绑定到同一个 build 的六个独立 gate verdict |
| publication lock | `ari.manuscript-publication-lock/v1` | 最终 fresh 的 decision/build/PDF 联锁 |
| evaluation report | `ari.manuscript-evaluation-report/v1` | 带标签的 program metric，并显式给出分母适用性 |
| transition | `ari.manuscript-transition/v1` | append-only 的 state hash chain |

## Digest lineage

规范链条为：

```text
profile + source files/nodes
  → snapshot
  → context + omission manifest
  → readiness
  → section briefs
  → authoring binding
  → PaperBuildV1
  → PublicationDecisionV1
  → PublicationLockV1
```

改变任何一个父项都会使下游的复用失效。在写出 lock 之前，finalizer 会重新 hash
snapshot source、每一个嵌套的 `PaperArtifactV1`、全部五个 manuscript 输入、
reproduction 结果以及最终 PDF；它还会拿确切的最终 TeX 去核对 brief 的
contextual-negative/forbidden evidence ID 与必需 disclosure。上游 paper gate 通过，
并不能弥补这项被绑定的内容检查的失败。

两处 evidence-lane 检查——archive 的逐 candidate screen 与 finalizer 对确切最终 TeX
的检查——都是 identifier 提及检查，而不是对 draft 如何使用该 evidence 的判断。两者
都在所有 section brief 的 `contextual_negative_ids` 与 `forbidden_evidence_ids` 并集
之上，把 evidence ID 本身当作有分隔、大小写不敏感的 token 在 draft 中搜索；token 字母
表取 `A-Za-z0-9_:/-`，因此结尾的句点是分隔符。这类 ID 出现在 draft 的任何位置都会
触发检查；两处都不检查周围 claim 的极性，也都不把某个 section brief 的 ID 限制在该
section 之内。这种粗糙是刻意的：规则是确定性的，不给意图留下任何可争论的余地。渲染
出的 brief 块在正文里陈述的是较弱的极性规则（「披露，绝不作为正面支持使用」），但机械
强制的条件是更严格的那一条——该 ID 根本不得出现。因此，negative 与 inconclusive 的
历史抵达稿件的通道是 brief 的 `required_disclosures`，以及 `negative-results` 与
`limitations` 这两类内容条目——它们携带的是自己的 item ID，而不是 evidence ID。锋利
的边缘在 `results` 内容条目：它们包含以 evidence ID 为键的 exploratory-lane evidence
record，而 exploratory lane 同时也属于 `forbidden_evidence_ids`，因此一份 brief 可以
把某段内容交给 writer，而该内容的 identifier 绝不允许写进 draft。

两处只在后果上不同。finalizer 的检查不受 mode 限定：只要 publication decision 被计算
出来，它就会被应用，并被 AND 进 `claim_evidence` 子判定，因此一次提及就让该 decision
不可发布，lock 步骤随之拒绝它。在 archive screen 中，提及成为一次硬性失格——记录为
`contextual_negative_evidence:<id>` 或 `forbidden_evidence:<id>`，并额外把该 candidate
标记为 `_valid_for_frontier: false`——但这只发生在 `enforce` 下；`audit` 记录完全相同
的 diagnostics，却不改变 candidate 的 eligibility。

## Status 语义

requirement status 恰好是 `satisfied`、`not_applicable`、`unavailable` 或 `missing`
之一。`unavailable` 是关于 resolver 可用性的证据，而不是关于成功的证据。authoring 被
authoring-critical 的 `missing|unavailable` 阻塞；publication 被每一个未解决的
publication-critical requirement 阻塞。

顶层 publication decision 只有在适用的 `manuscript_readiness`、`claim_evidence`、
`assurance`、`build_compile`、`reproduction` 与 `freshness` 子判定都不 fail 时才是
publishable。model validator 会重算这个逻辑 AND。

## 发布 gate

### 子判定的不变量

`PublicationDecisionV1` 恰好携带六条 `PublicationSubVerdictV1`，其 `decision` 仅是这
六条的函数。该结构在 read 时被强制，因此一份被手工编辑或截断的 decision 文档，无法
给出比其自身 reason 所支持的更宽松的判定：

- gate 名称必须恰好是 [Status 语义](#status-语义)中列出的那六个，且各出现一次。缺少
  gate、重复 gate，或该集合之外的 gate，都会被拒绝。
- 没有 reason code 的 `fail` 子判定会被拒绝，因此被阻塞的 decision 总会说明自己为何
  被阻塞。
- 同一条子判定内出现重复的 artifact digest 会被拒绝。
- `decision` 必须等于对这六个 status 重算得到的逻辑 AND。

契约*不*约束什么，与它约束什么同样重要。六条子判定是作为集合而非序列被校验的：gate
以另一种顺序出现的 decision 依然能通过校验，但顺序是 canonical JSON 的一部分，因而会
改变 `decision_digest`，所以对下游的一切来说，重排过的副本就是另一份 decision。
`artifact_digests` 与 `reason_codes` 是没有 pattern、没有封闭词表的普通字符串；这一层
不检查被链接的 digest 是否真是一个 digest。而且 `reason_codes` 在 `pass` 与
`not_required` 上同样被允许——只是 producer 自己不写而已。

那个 producer 就是 `ari-core/ari/manuscript/publication.py` 中的固定 assembler，它在
四个方面收窄了 schema：按下表顺序 emit gate；只为 `fail` 写 reason code；每个失败的
gate 恰好写一条 reason code；且只为 `assurance` 这一个 gate emit `not_required`。

| Gate | `fail` 时的 reason code | 链接的 artifact |
|---|---|---|
| `manuscript_readiness` | `manuscript_not_publication_ready` | readiness report 的 digest |
| `claim_evidence` | `final_claim_gate_failed` | paper build 的 claim gate report digest |
| `assurance` | `required_certification_missing_or_failed` | 被 admit 的 certify-attestation digest——零个或多个 |
| `build_compile` | `paper_compile_failed` | build 的 compile digest |
| `reproduction` | `paper_reproduction_failed` | reproduction record 的 digest |
| `freshness` | `publication_input_stale` | 无 |

有两个 gate 打破了「一个 gate 一个 artifact」的模式。`freshness` 刻意什么都不链接：它是
以下各项的合取——重新 hash 的 attempt snapshot source、被记录的 manuscript state 为
`authored` 或 `finalized`、确切 build 中嵌套的 `PaperArtifactV1` 集合非空且重新 hash
回其记录的 identity，以及——仅在 enforce 下——被绑定的五个 manuscript 输入。它是整个
输入集合的性质，而不是某一个 artifact 的性质。`assurance` 链接的集合可能为空：被 admit
的 certify-attestation 条目的 snapshot digest；只要没有条目被 admit，或者 attempt 的
`source_snapshot.json` 读不出来，它就是空 tuple。另外四个总是恰好链接一个 digest。

第三种情形是记录本身缺席。当某个 gate 所判定的 evidence 根本不存在时——paper build 不
带 claim gate、没有 compile record、或者 checkpoint 在安全的非 symlink 路径上没有
reproduction 文件——runtime 仍然 emit 该 gate，并用全零哨兵 `sha256:0000…0000` 代替真
digest 链接上去。这三种情形下该 gate 已经是 `fail`，所以哨兵是诊断性的而非承重的：它
记录「当时没有任何 evidence」，且绝不会出现在一个通过的 gate 上。

### Evidence 与通过条件

每个 gate 都点名自己读取的 evidence，并施加一条固定的通过条件。任何东西都不会从缺席
中被推断出来：evidence 缺失、不可读，或无法在安全的非 symlink 路径上抵达的 gate，一律
失败。

| Gate | Evidence | 通过条件 |
|---|---|---|
| `manuscript_readiness` | 被绑定的 `ManuscriptReadinessReportV1` | 其 `publication_verdict` 为 `ready` |
| `claim_evidence` | build 的 claim gate 与确切的最终 TeX | gate status 为 `pass`，**且**最终 TeX 载有被绑定 brief 所要求的每一条 disclosure，并且不提及这些 brief 中的任何 contextual-negative 或 forbidden evidence ID |
| `assurance` | 编译出的 context 的 `assurance` 块与 attempt 的 `source_snapshot.json` | [Assurance 子判定与预留的 kernel binding](#assurance-子判定与预留的-kernel-binding) 中的条件成立；除非 context 记录了 `assurance.mode: enforce`，否则它是 `not_required` |
| `build_compile` | `PaperBuildV1.status` 及其 compile record | status 为 `finalized` 且 compile record 的 status 为 `completed` |
| `reproduction` | checkpoint 中的 `ors_phase1.json` | 该文件存在于非 symlink 路径上，并记录 `executed`、`exit_code = 0`、空的 `missing` 列表且没有 `error` |
| `freshness` | attempt snapshot、被记录的 manuscript state、build 中嵌套的 artifact，以及 enforce 下被绑定的五个输入 | 其中每一项都重新 hash 回其记录的 identity，且 state 为 `authored` 或 `finalized`——即[子判定的不变量](#子判定的不变量)中列出的那个合取 |

其中两条条件比它们的 evidence 列所暗示的更宽。当 section brief bundle 未在 checkpoint
内暴露、是 symlink 或无法解析时，当 build 没有恰好点名一个 `final-tex` artifact 时，
或者当那份 TeX 不可读时，`claim_evidence` 同样失败——义务不能靠让它不可读来免除。它的
disclosure 那一半是在必需文本与 TeX 都被归一化之后（丢弃 TeX 控制序列、把每个非字母
数字字符折成一个空格、大小写折叠）运行的子串测试，因此 markup、标点、大小写与换行都
无法使其失效，尽管 disclosure 的词仍必须连续出现；它的 evidence-ID 那一半是
[Digest lineage](#digest-lineage) 中的分隔 token 规则。

当 attempt snapshot 记为 `missing` 的某个 source 又出现时，以及当带路径的 source 没有
记录 digest 与 size 时，`freshness` 也会失败——没有稳定字节 identity 的条目不能授权
发布。它那条仅在 enforce 下生效的绑定输入子句，要求这五个输入就是 attempt 目录自己的
`requirement_profile.json`、`context.json`、`readiness.json`、`section_briefs.json` 与
`authoring_binding.json`，在 build 的输入 artifact 中恰好以这些相对路径声明，重新 hash
回 build 所声明的 identity，与 binding 共享同一条 profile/context/readiness/brief
lineage，点名 target build 的 ID、revision 与 run，并携带 `ready` 或
`ready_with_disclosures` 的 authoring verdict。在 `audit` 下该子句完全不适用，因为
audit 刻意不把 writer 绑定到编译出的 bundle 上；snapshot、state 与 build-artifact 这
几条子句仍然成立。

只有当 runtime manuscript mode 不是 `off`、`paper_build.json` 存在，且 context、
readiness 与 binding 的路径都已暴露时，decision 才会被计算；否则不写出任何 decision，
而 decision 缺席并不等于通过。对于这三条路径和 `paper_build.json`，位于 checkpoint 之
外或含 symlink 组成部分会直接 raise，而不是让某个 gate 失败。decision 在 `audit` 与
`enforce` 下都会作为 `publication_decision.json` 写入 attempt；只有 `enforce` 还会记录
transition，以 reason code `publication_publishable` 或 `publication_blocked` 转到
`finalized` 或 `publication_blocked`。lock 步骤会重跑全部三项 freshness 检查——包括绑定
输入子句，无论何种 mode——要求被记录的 attempt 就是 binding 的那个且其 state 为
`finalized`，并且还会拒绝 `reproduction` 子判定不为 `pass` 的 decision、拒绝已不再 hash
成该子判定所记录 digest 的 `ors_phase1.json`，以及拒绝无法恰好指认一个最终 PDF 的
build。

### decision 不绑定什么

这条记录本身刻意做得很窄。它的全部字段集合是 `schema_version`、`run_id`、`attempt_id`、
`paper_build_digest`、`authoring_binding_digest`、`readiness_digest`、六条子判定、
`decision` 与 `decision_digest`，且 unknown field 会被拒绝，因此不能往上附加别的东西。
lineage 中其他每一个 identity 都要通过解引用其中某个 digest 才能抵达，需要它的消费方
必须去读那个 digest 所指向的 artifact：

| Identity | 抵达途径 |
|---|---|
| profile、context、brief-bundle 与 source-snapshot digest；target build ID 与 revision | `authoring_binding_digest` |
| checkpoint ID | 由 binding 的 `source_snapshot_digest` 点名的 exploration snapshot |
| PDF 与 claim-links artifact digest | `paper_build_digest`，在 finalized build 的 `final_artifacts` 中 |
| EAR digest | `paper_build_digest`，作为必需的 `PaperBuildV1.ear_digest` |
| code-bundle lock 的路径与 digest | context 的 `reproducibility`，当 checkpoint 带有该 lock 时 |
| readiness evaluator 版本 | `readiness_digest`，作为 `ManuscriptReadinessReportV1.evaluator_version` |
| requirement-profile 的 policy 版本 | 由 binding 的 `profile_digest` 点名的 profile |

被链接的 digest 也可能比它背后的检查更窄。`claim_evidence` 是最终硬 gate 与
[Digest lineage](#digest-lineage) 中所述 finalizer 对确切最终 TeX 的检查之合取，但它只
链接 gate report 的 digest，失败时再加上表中那一条 reason code。因此该子判定既不指认第
二项检查所读的 brief bundle 或最终 TeX，也不指明两个条件中是哪一个失败了。

有两处缺席是真实的缺席，而非间接可达。Harness catalog snapshot digest 在 decision 上没
有字段，在整个 `ari.manuscript` 中也没有；正如
[RQGM node projection](#rqgm-node-projection) 所记，它留在被保留的 attestation 文件内
部，只由该文件的相对路径与内容 digest 寻址。而 decision 除了 `schema_version` 这个常量
之外不带自己的版本——记录上没有任何指明生成它的代码的 evaluator 或 policy 版本。因此
复现一份 decision 依靠的是 `decision_digest` 加上固定 assembler 与被 pin 的输入，而不是
某个被记录的 evaluator identity。

## Harness attestation 的 projection

node 的 `attestation_refs` 中每一个非空字符串，都在 exploration snapshot 中成为一个
`harness-attestation` artifact。artifact 记录的 status 是关于可采性的陈述，而不是
attestation 自身 verdict 的副本：

| Artifact status | 条件 |
|---|---|
| `invalid` | 记录的路径不是安全的 checkpoint 相对路径，或穿过 symlink 组成部分，或文件不可读、不是合法 JSON，或未通过 `HarnessAttestationV1` 校验（其中包含重算它自称的 `attestation_digest`），或其 `node_id` 不是引用它的那个 node |
| `missing` | 该安全相对路径解析不到任何常规文件 |
| `stale` | 合法且归属该 node，但其 `target_digest` 不是该 node 的 `verified_target_digest`——包括该 node 根本没有的情形 |
| `present` | 合法、归属该 node，且绑定到该 node 确切的当前 target |

能够解析的 attestation 即使被拒绝也绝不丢弃：该 artifact 仍以 metadata 保留
`attestation_digest`、`target_digest`、`verdict`、`tiers`（排序去重后的 property tier）、
`belongs_to_node`、`target_matches`、`verification_contract_digest` 与
`baseline_harness_lock_digest`，因此 node 不匹配或 stale 的 attestation 仍可诊断。在解析
之前就被拒绝的 attestation 携带的信息更少：不安全的记录路径会记下一个 `unsafe_path`
标记——当路径本身不可用时还会附上逐字的 `recorded_ref`——而缺失、不可读或非法的文件则
完全不带 metadata。attestation 自身的内容、`screen`/`validate`/`certify` 的 tier 阶梯，
以及 verdict 词表，定义在
[Knowledge、Capability 与 Scientific Assurance](knowledge_capability_assurance.md)。

`certify_pass` 是另一项 metadata 事实，独立于 artifact status 记录，且绝不从其中任何一
项推断出来。它是四个条件的合取：该 attestation 归属该 node；其总体 `verdict` 为 `pass`；
其 `target_digest` 等于该 node 的 `verified_target_digest`；并且它至少带有一条
`certify` tier 的 property result，且每一条 `certify` tier 的结果都通过。
`HarnessAttestationV1` 本来就拒绝 property 未全部通过的 `pass` verdict，因此最后一个条件
真正承重的部分，是是否存在 `certify` tier。

只有 `certify_pass` 为真的 `present` artifact 才会进入 node 的
`certify_attestation_item_ids`。在 `enforce` assurance mode 下，一个熬过前面 lane 规则的
node 只有在该 tuple 非空、*且* `assurance_status` 为 `pass`、*且* `assurance_tier`
为 `certify`、*且* `verified_target_digest` 非空时才是 `publishable`；四者缺其一，该
node 就带着理由 `certification_required` 落入 `exploratory` lane。因此一次 screen tier 的
通过，以及一次绑定在已被取代 target 上的 certify 通过，都仍被保留为可采的 evidence，而
两者都不是发布 certification。

可采性在 snapshot 被编译时一次性决定，之后没有任何步骤会重新审视它。
`ari.manuscript.snapshot` 是唯一打开并判定 attestation 文件的地方；下游每一个消费方读
到的都是被冻结的结果——context 的 `assurance.attestation_item_ids`、`MC-AS-001` readiness
resolver 与 finalizer，都把 item ID 与 status 当作既定事实。`finalize_runtime_publication`
和 `lock_runtime_publication` 都不会再次解析 attestation，不会重新检查 node 归属或 target
匹配，也不会 certify 任何东西。finalizer 消费的唯一一项 attestation 事实，是已经为被
admit 的 item ID 记录下来的 digest，而它是从 attempt 的 `source_snapshot.json` 中读回
的，这样 `assurance` 子判定引用的就是它没有重新解释过的字节。

后续步骤重新校验的是文件，不是 verdict。finalizer 与 lock 步骤都会把每一个带路径的
snapshot artifact——包括 harness attestation——按编译时记录的 digest 与 size 重新 hash，
要求被记为 `missing` 的 artifact 依然缺席，并拒绝任何完全没有字节 identity 的带路径
artifact。正是最后这条规则，使得被 symlink 的或无法解析的 attestation 不仅仅是惰性的：
它是 `invalid` 且没有记录 digest，因此过不了 `freshness`，并在任何会计算 decision 的地方
阻塞该 decision。就地修改一份被保留的 attestation 同样是 freshness 失败，而不是改变它被
admit 成什么。freshness 唯一看不见的拒绝，是那种从未解析成相对路径的不安全记录路径，因
为没有路径被存下来供重新 hash。

按需 certification 确实存在，但发生在 decision 的上游且受 budget 约束，绝不在其内部。
`assurance_certification` 是一种 repair resolver kind，其 executor 会对选中的 candidate
调用 RQGM runtime 自身的 `certify_node` 并改写 checkpoint，被计一次 experiment run，并在
该 runtime 不可达时以 `certification_runtime_unavailable` 记录 `unavailable`。它对可采性
的影响，只有在 repair 循环的重建步骤重新编译 snapshot 时才会显现。事实上，重新编译是唯一
能让一份 attestation 在各 status 之间移动的动作：一份 `stale` 的 attestation 变成
`present`，只发生在点名它的那个 node 在下一次编译时带有匹配的 `verified_target_digest`
之时，绝不会更早。

## Assurance 子判定与预留的 kernel binding

`assurance` 子判定在 manuscript 层内部计算，不委派给 Constitutional Kernel。只有当
context 的 `assurance.mode` 为 `enforce` 时才需要它，否则记为 `not_required`，此时它无法
使 decision 失败。在 enforce 下，只有当 context 带有 `publication_candidate`、至少有一个
被 admit 的 certify attestation item ID，并且从 attempt 的 `source_snapshot.json` 读回的
这些条目的 digest 集合非空时，它才通过。candidate 缺失、条目集合为空，或 snapshot 不可
读，都会以 `required_certification_missing_or_failed` 失败关闭。这些 item ID 背后的准入
规则就是上面那个 `certify_pass` 合取；这一层没有任何东西会重新打开 attestation，也没有
任何东西会把它记录的 `verification_contract_digest` 或 `baseline_harness_lock_digest` 与
当前 lock 作比较。

`ConstitutionalKernel.validate_harness_integrity` 接受一个 `publication` 参数，并在
attestation 未通过却声称要发布时，或在 verification contract 要求 `certify` tier、或带有
`block-publication` failure policy 而不存在任何通过的 certify property result 时，抛出
`CK-HAR-018`。**没有任何生产路径会传入 `publication=True`。** RQGM runtime 的 K/C/A
harness report 调用该检查时不带这个参数，而 manuscript 发布评估器根本不调用该检查。唯一
设置这个 flag 的代码，是 kernel 逐 code 的测试 fixture 与 K/C/A 故障注入 probe 的
`reviewer_publishes_uncertified` 变异——它们的存在是为了演示该规则会触发，而不是为了对真
实的发布设 gate。

两层之间的一个 binding 已被设计，但**尚未实现**。它本应让发布评估器把确切的 target
contract 与 attestation 交给固定的完整性检查，覆盖发布主体 node 与 configuration ID、选定
的 source 与 code digest 集合、被覆盖的 ScienceData measurement、Harness 的 ID/version、
runner、container 与 dataset lock、Harness contract 所要求的 environment 或 Provider
binding，以及当前的 catalog lock 与 attestation revision——任何不匹配、必需 certification
缺失、block-publication 发现或陈旧 binding，都作为独立的发布失败抛出，而不是折进
assurance 判定里。今天这些都不存在。真正成立的 binding，是 `HarnessAttestationV1` 自身所
携带的内容，加上 projection 时记录的 node 归属、target digest、verdict 与 certify tier
这几项条件。

### Certification 只被校验，绝不重跑

finalizer 无法取得一份 certification。`finalize_runtime_publication` 读取编译已经
project 进 context 的 `assurance` 块，把被 admit 的 item ID 解析成 attempt 的
`source_snapshot.json` 中的 digest，然后就停下：它不 dispatch 任何 Harness run，也不
import 任何 assurance runner。`assurance` gate 只能追认或拒绝那份 projection，无法为它
添加任何东西。

因此上述 projection 规则同时也是失败模式。被 projection 拒绝的 attestation——不归属该
node、绑定到已被取代的 target，或没有任何通过的 `certify` tier——对
`attestation_item_ids` 毫无贡献，于是在 `enforce` 下，一个所有 certification 都被拒绝的
candidate 会以空的 admit 集合抵达 finalizer，并与从未尝试过 certification 的情形完全一样
失败关闭。两者都落在 `required_certification_missing_or_failed` 上；finalizer 既不区分这
两种情形，也不修复其中任何一种。

取得一份当前有效的 attestation 是另一件更早发生的事。确实存在的路径是
`assurance_certification` 这种 repair kind：它在
`ari-core/ari/cli/manuscript_repair_runtime.py` 中的 executor 会对 verified-context
selector 返回的 candidate 调用 RQGM runtime 的 `certify_node`，计入其最小成本所声明的那
一次 experiment run，并在剩余 budget 无法支付时以 `certification_budget_exhausted` 拒绝、
在没有挂接此类 runtime 时以 `certification_runtime_unavailable` 拒绝。coordinator 在
manuscript 准备阶段运行它——早于 authoring，也早于 finalizer 所跟随的 paper 阶段——而
`ari manuscript repair` 也显式接受同一种 request。不存在「发布时再 certify」的路径：发布
消费 certification 证据，从不制造它。

## RQGM node projection

编译器从交给它的 node 对象上读取 RQGM 状态。`ari.manuscript` 不从 `ari.rqgm` 导入任何东
西，且每一次读取都是鸭子类型的：属性或映射键，缺失即取默认值。
`ManuscriptNodeSnapshotV1` 上逐 node 的类型化 projection 是 `assurance_status`、
`assurance_tier`、`frontier_class`、`attestation_refs`、`certify_attestation_item_ids`、
`verified_target_digest` 与 `property_verdicts`，再加上 repair lineage 的
`repair_request_id`、`repair_requirement_ids`、`repair_context_digest` 与
`repair_allowed_changes`。

`valid_for_frontier` 是导出的而非读取的：当 node 的 metrics 带有
`_valid_for_frontier: false` 或真值的 `_stale`——即 RQGM frontier repair 为逻辑擦除写下
的哨兵——时它为 false。`metrics` 本身只要可 JSON 序列化就被逐字复制，因此其余的 RQGM
哨兵——`_stale_reason`、`_erasure_event_id` 与 `_utility_policy_hash` 戳记——会作为编译器
任何规则都不读取的无类型 metric 存活进 snapshot。编译器唯一会解释的 metric 键是
`_scientific_score`，它成为类型化的 `scientific_score`；当它缺席时，编译器退回到不以下划
线开头的有限 metric 中最大的那个。

可选字段缺失是明确的缺席，而不是历史遗留的成功：

| Field | 默认值 | 该默认值断言什么 |
|---|---|---|
| `assurance_status`、`assurance_tier`、`frontier_class` | `""` | 没有记录任何 assurance verdict |
| `verified_target_digest` | null | 没有绑定任何 verified target |
| `certify_attestation_item_ids` | 空 | 不存在既归属该 node 又通过 certify 的 attestation |
| `valid_for_frontier` | true | 当时不存在擦除哨兵 |

这些默认值绝不会满足上面那条 `enforce` certification 规则。在 `off` 与 `audit` 下它们是
历史遗留的姿态，本身并不降级一个 node：`audit` 只降级那些记录了非 `pass`
`assurance_status` 的 node，因此一个完全不带 assurance 状态、又熬过了前面 lane 规则的
node，在两种 mode 下都保持 `publishable`。

run 级 identity 比 node projection 更薄。`run_id` 从 `tree.json` 或 `nodes_tree.json` 读
取，并回退到 checkpoint 目录名；`checkpoint_id` 就是该目录名；`exploration_mode`、
`research_contract_digest` 与 `research_question` 与它们并列携带。
`selection_policy_digest` 是编译器自身那份固定 scientific-winner policy 的 digest，而不是
任何 RQGM utility policy 的 digest——它是编译器版本的一个常量，因此它标识的是 winner 是
如何被选出的，而绝不是哪个 policy 给 node 打了分。

未被 projection 的部分：RQGM 的 epoch identity 与 Harness catalog snapshot digest 在
`ExplorationSnapshotV1` 与 `ManuscriptNodeSnapshotV1` 上都没有字段。attestation 自身的
`epoch_id` 与 `producer_epoch_id`，以及可经上面记录的 `baseline_harness_lock_digest` 抵达
的 catalog snapshot digest，都留在被保留的 attestation 文件里，只由其相对路径与内容
digest 寻址。governance 与 adversarial 的发现根本不是可采性的输入：`ari.manuscript` 中
不含对这两个子系统的任何引用，因此它们抵达稿件的唯一途径，是已经写进上述 node 字段或
写进编译器所读 checkpoint artifact 的状态。

## 与 PaperBuild 的关系

历史遗留的 `PaperBuildV1` 仍是 paper build 契约。在 enforce 下，它的输入 artifact 集合还
额外包含 `manuscript-profile`、`manuscript-context`、`manuscript-readiness`、
`section-briefs` 与 `manuscript-authoring-binding`。仅有 `PaperBuildV1.status=finalized`
并不意味着 Manuscript Complete 的发布被允许；`PublicationLockV1` 才是最终联锁。

这次整合留在了该契约内部，而不是产出第二个契约：不存在 `PaperBuildV2`。五个 manuscript
输入被加进 `ari-core/ari/paper_contract.py` 的 `PaperArtifactRole` 词表，并由 authoring
skill 作为普通的 input artifact 绑定进来。它们不属于 build 的 `required_inputs`，后者仍
只列出 `science-data`、`figure-batch`、`retrieval-records` 与 `ear-manifest`；强制其存在
与同一性的是 `freshness` gate 中仅在 enforce 下生效的 bound-input 条款，而不是 build
schema。这正是一个五者皆无的历史遗留 build 至今仍能原样通过校验的原因。

该词表中有一个成员是预留且未被使用的。`publication-decision` 与那五个并列声明，并出现在
生成的 `paper_build_v1` 与 `paper_model_call_batch_v1` 的 role 枚举中，但在任何 mode 下都
没有代码构造带该 role 的 artifact：decision 被写入 attempt 目录，名为
`publication_decision.json`，完全位于 build 的 artifact 集合之外。因此这份 role 清单把
build 能承载的东西说多了。把它当作清单来读的读者会到 `input_artifacts` 或
`final_artifacts` 里找 decision，两处都找不到；而遍历某个 finalized build 的 artifact 来
判断发布是否被允许的 consumer，不会明确失败，只会一无所获。绑定方向是反的——
`PublicationDecisionV1.paper_build_digest` 指名 build，而 `PaperBuildV1` 没有任何指名
decision 的字段，所以这条遍历只有从 decision 出发才成立。

稳定的 read type 与固定的编译器 helper 从 `ari.public.manuscript` 导出；可变的 coordinator
内部不是 public API。

## RQGM archive 的 provenance

`paper_draft_archive.jsonl` 仍是 paper archive 既有的 record 流。启用 Manuscript Complete
时，每条 record 还额外携带 attempt、binding/profile/context/readiness/brief 各 digest、有序
的 section brief digest、evidence-lane 的 ID 集合、disclosure、omission 数量，以及一个
canonical 的 `manuscript_input_fingerprint`。candidate 的 diagnostics 记录确切的 artifact
digest、只读的 gate-report digest、contextual-negative 与 forbidden evidence ID 的提及、
缺失的 disclosure，以及硬性失格的理由。

`paper_archive_state.json.manuscript_authoring` 冻结同一个 fingerprint，并记录该 run 的当
前 status。这个 status 不是一个封闭的结果集合。在生成任何 draft 之前会先写入一个值——
enforce 下为 `bound`，audit 下为 `audit_legacy_authoring_observed`，而当先前的状态、
manuscript mode 或已记录的某份 draft 与当前 bundle 不一致时为 `stale_detected`——随后它被
结果值覆盖：`manuscript_bound_winner`、`bound_linear_fallback`、
`authoring_backend_failed`、`audit_legacy_archive_winner`、`audit_legacy_linear_fallback`
或 `verification_or_fallback_failed`，最后一个写于向公共验证尾段——或向 linear fallback
本身——的交接抛出异常时。停在 `bound` 的 checkpoint，就是其 archive 从未走到结果写入的那
一种。`stale_detected` 只在 enforce 下是终态，enforce 会拒绝继续；在 audit 下该 run 继续
进行，该 record 被 `audit_legacy_linear_fallback` 覆盖。因此一次被恢复的 enforce run 会在
继续之前拒绝缺失、不同或未绑定的 draft fingerprint。这些 archive record 是 provenance 面，
不替代规范的 readiness 或最终的 `PublicationDecisionV1` 契约。

抵达 canonical draft 路径的 archive winner 恰好只有一个。`materialize_winner` 是纯粹的
选择加复制：它把获胜 draft 自己的 `.tex` 复制到 checkpoint 的 `full_paper.tex`，除此之外
什么都不做——没有 gate 调用、没有重新打分、没有 LLM 调用——并且当 winner 没有可 materialize
的 `.tex` 时它不碰那个路径，因此没有 winner 的 archive 会退化为 linear 结果而不是失败。在
所有*生成*该文件的阶段中，它是 archive 路径上唯一的写入者：`write_paper` 通过自己的
`skip_if_exists: {{checkpoint_dir}}/full_paper.tex` 守卫变成 no-op；而 `paper_refine`
——`ari-core/config/workflow.yaml` 中唯一另一个把 `{{checkpoint_dir}}/full_paper.tex` 声明
为输出的阶段，若不加处理它会在已 materialize 的字节上继续 refine——被
`HANDOFF_DISABLED_STAGES` 点名，并在交接进 linear 流水线的调用中作为被禁用阶段传入。该集
合只含 `paper_refine`，没有别的。这项抑制以确实存在 winner 为条件：交接同时以持久的
best-belief archive record *和*已存在的 `full_paper.tex` 为键，因此 fail-open 或 fallback
的 run 传入的是原始阶段集合，两个阶段的行为与 linear run 完全一致。禁用某个阶段不会级联
——`depends_on` 点名了被禁用阶段的阶段仍然运行——而且由于只有 `paper_refine` 被禁用，
`review_paper` 与 `merge_reviews` 仍照常产出各自的 artifact。交接所抑制的是把这些 review
应用到 TeX 上，而不是它们的计算。

单一写入者说的是生成，而不是不可变性。验证尾段仍然像对待 linear draft 那样，在 canonical
路径上做自己的就地编辑——`finalize_paper` 注入或刷新 Code Availability 块，被锁定的
claim-evidence 检查随后在被编辑过的文件上重跑。交接所保证的是：在 materialize 与读取它的
claim-evidence gate 之间，没有任何东西会重写或修订 winner 的内容。

结果记录点名它 materialize 的那个 winner。只要获胜 draft 能解析出一个 `.tex`，
`manuscript_authoring` 就额外携带 `winner_id` 与 `winner_tex_sha256`——即那份 draft 自己的
`.tex` 的 SHA-256，也就是被复制到 canonical 路径的确切字节，当这些字节读不出来时留空——因此
一次 build 可以被追溯回 `paper_draft_archive.jsonl` 中的 candidate record。有一个后果是刻
意的，值得说明：archive winner 绝不会得到 linear 流水线的 `paper_refine` 修订 pass。那次修
订转而发生在 archive 自己的、由 reviewer 驱动的 `paper_refine` 子节点上，这使它恰好与每一
轮所构建的 reviewer 一样「活」。在默认路径上，那个 reviewer 从第一轮起就是活的：在没有注入
reviewer oracle 时，`run_archive` 走 co-evolution 分支，每一轮都从该 epoch 处于 active 的
`paper_reviewer` prompt 重建一个 `GovernedPaperReviewer`——当 governance 尚未采纳任何
prompt 时回退到 founding prompt 的字节——其 `review` 即使没有注入修订接缝也会返回真实的修
订指令。那个确定性的、不含 LLM 的默认 reviewer——其 `review` 根本不返回任何可执行的修订
——只会在内层 RQGM runtime 无法构建、archive 退化为单轮无治理的情形下才被用到。调用方注入
自己的 reviewer oracle 时走的是同一个单轮无治理路径，但跑的是被注入的 oracle：构造函数的
默认值是被替换掉，而不是被用到。

## Program evaluation

`scripts/evaluate_manuscript_complete.py CASES.json --output REPORT.json` 构建一份
`ManuscriptEvaluationReportV1`。每个比值都保留自己的分子、分母与 evidence ref。分母为零
的比值 status 为 `not_applicable` 且没有值；它绝不会被报告成满分。对象形式的输入可以提供
`dataset_id`；裸列表则需要 `--dataset-id DATASET_ID`。

该 report 由一个固定的 evaluator identity 标定版本：`evaluator_version` 恒为
`manuscript-program-evaluator-v1`，它是 `ari-core/ari/manuscript/evaluation.py` 的常量，
而不是从 case 中读出的任何东西。它与编译器的 `manuscript-evaluator-v1` 是不同的 identity；
后者是 requirement profile 作为自己的 `evaluator_compatibility` 声明的值，也是 requirement
result 与 readiness report 所携带的值——这两个字符串标定的是不同的东西，各自独立演进。该
evaluator 函数以 `evaluate_labelled_cases` 从 `ari.public.manuscript` 导出，并拒绝含重复
`case_id` 的 case 集合。编译、authoring 或发布路径中没有任何东西调用它：这是对人工标注
case 的离线测量，绝不是一道 gate。

### Metric 词表

该词表是封闭且无条件的。无论 case 中有什么，每份 report 都以相同顺序携带相同的十三个
metric ID——无可测量内容的 metric 也以分母为零、status 为 `not_applicable` 的形式出现，绝不
省略。其中十二个是比值；`silent-omission-count` 是唯一的计数，而计数的分母为 null，把分子
直接作为自己的值，因此永远是 `measured`。

| Metric ID | 分子 | 分母 |
|---|---|---|
| `requirement-accounting-rate` | `observed_status` 为四个 status 值之一的已标注 requirement | 全部已标注 requirement |
| `missing-detection-precision` | 被标注为 `expected_missing` 且被观测为 `missing` 或 `unavailable` 的 requirement | 全部被观测为 `missing` 或 `unavailable` 的 requirement |
| `missing-detection-recall` | 同一个分子 | 全部被标注为 `expected_missing` 的 requirement |
| `silent-omission-count` | Σ `max(0, inventory_count − included_count − omission_count)` | 无——这是一个计数 |
| `inventory-projection-accounting-rate` | Σ (`included_count` + `omission_count`) | Σ `inventory_count` |
| `headline-publishable-evidence-coverage` | Σ `headline_evidence_covered` | Σ `headline_claim_count` |
| `negative-result-visibility` | Σ `negative_result_visible` | Σ `negative_result_count` |
| `unnecessary-repair-rate` | Σ `unnecessary_repair_count` | Σ `repair_request_count` |
| `repair-success-rate` | Σ `repair_satisfied_count` | Σ `repair_request_count` |
| `repair-marginal-cost` | Σ `repair_cost` | Σ `repair_satisfied_count` |
| `attempts-to-finalization` | 在 finalized 的 case 上求 Σ `attempt_count` | finalized 的 case |
| `rounds-to-finalization` | 在 finalized 的 case 上求 Σ `round_count` | finalized 的 case |
| `legacy-off-identity-rate` | `off_identity` 为真值的 case | 带有 `off_identity` 键的 case |

其中四个分母承载的是论据而非算术。

missing-detection 的 precision 与 recall 把 `missing` 与 `unavailable` 折成同一个检测事件，
因为两者都是关于编译器无法解析的 evidence 的陈述。这两个 metric 都不区分 artifact 缺席与
resolver 故障。

`silent-omission-count` 是既没有被 included、也没有被记为 omission 的 inventory，因此一次
守恒的 projection 报告零。它按 case 在零处被截断，这意味着某个 project 出比自身 inventory
更多内容的 case 只是毫无贡献，而不会抵消另一个 case 中真实的 omission。
`inventory-projection-accounting-rate` 没有这种截断，可以超过 1，因此过度 projection 在那里
保持可见，而不是藏进计数里。

attempt 与 round 只在 finalized 的 case 上求和并相除。未完成的 case 对分子和分母都无贡献，
因此放弃一个困难的 case 无法美化平均值。

`legacy-off-identity-rate` 以那些确实给出了 `off_identity` 判定的 case 为分母。省略该键的
case 落在分子与分母之外，而不是被算作一次失败，因此该 metric 描述的是被标注的 off-mode 子
集，而不是整个数据集。

每个 metric 的 `evidence_refs` 都是同一个完整、有序的 case ID tuple。这些 ref 标识的是该
metric 是在哪个 case 集合上计算的；它们不是逐 metric 的 provenance，也不会收窄到那些真正
让某个数字发生变化的 case。

### 不是 metric 的 report 字段

有两个 report 字段不是 metric，不带分母语义，也在零分母规则之外。

`blocked_reason_distribution` 统计每个 case 在 `blocked_reasons` 下列出的每一个字符串，以
理由为键并排序。词表就是被标注的 case 所提供的那些；evaluator 既不拿它去核对某份契约，也
不定义一个封闭的理由集合。

`topology_costs` 是每个不同 `topology` 值一行、按该值排序，携带 case 数量以及这些 case 在
`cost` 下报告的 `llm_calls`、`experiment_runs` 与 `resource_units` 之和。没有 `topology`
的 case 累计到 `unspecified` 之下。这三个计数器就是本契约 emit 的全部成本词表：没有 token
计数器，也没有 wall-clock 字段。

## Release evidence

`scripts/manuscript_complete_release_gates.json` 是恒久且封闭的发布 manifest。它点名全部
四种 research/paper 拓扑、13 个必需的故障注入族、历史遗留的迁移/回滚测试，以及每一个可执
行套件。`scripts/run_manuscript_complete_release.py` 校验它所拥有的每一项测试仍然存在，运
行这些套件，按 SHA-256 保留 stdout/stderr，并 emit 绑定到确切 Git commit/tree 与 manifest
digest 的 `ari.manuscript-release-evidence/v1`。这是一份运维性的发布记录，不是科学
Attestation，也不能替代被保留的原生 Harness 证据。

## Repair 的准入与排序

repair request 的集合仅由 readiness report 导出；围绕它们的 plan 只是补上被 admit 的
policy、budget 与 authority digest。凡 status 为 `missing` 或 `unavailable`、且其 profile
条目声明了至少一个 resolver 的 requirement，都会按其 resolver kind——即该 requirement
`resolver_kinds` 的第一个条目——分组，把自己的 ID 贡献给恰好一个 request。因此共享同一个
resolver kind 的若干 requirement 会成为一个有界的 request，而不是各自一个。`satisfied` 或
`not_applicable` 的 requirement，以及 profile 未声明任何 resolver 的 requirement，根本不
产生 request。

request 的 identity 是对 source context digest、排序后的 requirement ID、resolver kind 与
success predicate 取的 canonical digest，截断为 24 个十六进制字符并冠以 `repair-` 前缀。
因此同一个 context 上的同一个 gap 总是产出同一个 request ID，这正是让以它命名的已提交
transaction 得以充当幂等键的原因。

request 按 `ari-core/ari/manuscript/repair.py` 中的固定优先级表排序，同一 tier 内再按
resolver kind 名排序；表中没有的 kind 排在最后。request 内部的 requirement ID 是排序过的。
这个顺序是承重的而非装饰性的：执行会严格按该顺序遍历 plan 的 request，并边走边计入共享
budget，因此廉价的恢复总是先于某个 experiment 把 budget 耗尽而运行。在
`repair.policy: auto` 下，coordinator admit plan 中的每一个 request；
`ari manuscript repair --request` 只 admit 被点名的子集；policy 为 `disabled` 的 plan 无论
其 request 说什么都什么也不执行。

| Tier | Resolver kind | 为何排在这里 |
|---:|---|---|
| 1 | `projection_rebuild`、`artifact_recovery` | 有可能通过重算或恢复已经存在的东西来闭合该 gap |
| 2 | `assurance_certification` | 对已经存在的 evidence 做 certify |
| 3 | `literature_search` | 有记录的检索，没有新的测量 |
| 4 | `validation_experiment` | 校验一个矛盾的或对完整性至关重要的结果 |
| 5 | `baseline_comparison`、`repetition_or_uncertainty`、`ablation` | 为处于阻塞状态的 claim 做最小限度的新测量 |
| 6 | `method_clarification` | 需要一份被 admit 的 method record |
| 7 | `limitation_disclosure` | 记录一条 disclosure，而不是一个事实 |
| 8 | `human_decision` | 没有人就无法闭合 |

每个 request 以 plan budget 作为自己的上限，每种 kind 带有一个固定的最小成本。在调用
resolver 之前，剩余 budget 等于 plan budget 减去已提交的用量；其 kind 装不下的 request 会
在**其 resolver 未被调用**的情况下被记为 `exhausted`，理由 `plan_budget_exhausted`，因此
budget 不足的一轮不会把一个 experiment 跑到一半。没有注册 executor 的 kind 同样被记为
`unavailable`，理由 `resolver_unavailable`，且不花费任何东西。

| Resolver kind | 最小 new node / experiment run / LLM call |
|---|---|
| `baseline_comparison`、`repetition_or_uncertainty`、`ablation`、`validation_experiment` | 1 / 1 / 1 |
| `assurance_certification` | 0 / 1 / 0 |
| `literature_search`、`method_clarification` | 0 / 0 / 1 |
| 其余所有 kind | 0 / 0 / 0 |

这项准入检查只覆盖那三个计数器。`max_resource_units` 不在其中：资源超支是在 executor 返回
之后才被捕获的——当它报告的用量超过 request 或 plan 上限时，该次调用失败关闭。

分组绝不合并 budget 归属。每个 request 保留自己的 success predicate、自己的 allowed-change
集合，以及自己那份精确记录了它所消耗的 node、experiment run、LLM call 与 resource unit 的
已提交 transaction。累计用量是通过把这些经过校验的 transaction record 求和重新算出来的，而
不是在内存中传递，因此一轮被恢复的执行是从已提交的证据出发的。

## Repair 提交记录

自动 repair 把每个被执行的 request 持久化为一份 `ManuscriptRepairTransactionV1`，把
coordinator 的每一轮持久化为一份 `ManuscriptAutoRepairRoundV1`。两者都不可变且受 digest
绑定。恢复时会在调用下一个 resolver 之前，校验 request/authority identity、transaction
digest、round digest、连续的 round 序号以及累计 budget。被修改过或被 symlink 的
transaction/round record 一律失败关闭。

一轮由它所执行的 plan 的 digest 标识。其记录存放在 `auto-rounds/` 下，文件名取该 digest
去掉 `sha256:` 前缀后的前 32 个字符，写入与恢复读取双方都强制这个名字，因此文件名与自身
`plan_digest` 不一致的记录会被拒绝——空的或重复的 `plan_digest`，以及不是恰好 `0 … n-1`
的 `round` 序列，同样会被拒绝。一份 transaction 由其 request 标识，存放在
`repair-transactions/` 下，文件名取 `request_id`，遵循同一条文件名规则。两处写入都走
state store 的一次性写入路径，该路径拒绝替换字节不同的既有记录。

因此 `repair.max_rounds` 限制的是整个 checkpoint 上不同的已提交轮次数量，而不是每次调用
的数量。一次新的调用会在它第一次调用 executor 之前载入每一份已持久化的轮次记录，守卫把
已持久化轮次的总数——恢复出来的加上此后提交的——与最大值比较，并以
`round_budget_exhausted` 终止。重启不会补满轮次 budget。循环返回的 `rounds` 计数，是那一
次调用所提交轮次这个更窄的数字。

累计的 `new_nodes`、`experiment_runs`、`llm_calls` 与 `resource_units` 以同样方式恢复：在
循环开始前，把每一份已持久化 transaction 记录的用量求和。恢复出的值若非数值、为负或非有
限，会让该次调用失败关闭，而不是被当作零读取。若恢复出的用量已经超过某个配置的最大值，
循环会以 `cumulative_budget_exhausted` 结束且不调用任何 resolver；该检查在轮次 budget 检
查之后运行，因此同时越过两条上限的调用报告 `round_budget_exhausted`。运行时环境中不存在
的最大值按零读取，唯有资源上限例外——它是可选的，未设置时不限制任何东西。

在一轮之内，恢复出的用量会从 plan budget 中扣除，从而给每个 request 剩下的 budget；其
kind 的固定最小成本装不进剩余额度的 request 会被直接返回 `exhausted` 而不是被尝试。没有
任何 request 达到 `executed` 或 `satisfied` 的一轮会终止循环，其理由按固定顺序从剩余
status 中读出：只要有 `human_required` 就给出 `human_decision_required`，否则只要有
`exhausted` 就给出 `cumulative_budget_exhausted`，再否则是
`required_resolver_unavailable`。报告的用量超过自己 request budget 的 executor，或把累计
用量推过 plan budget 的 executor，都是硬错误，而不是被静默截断。

重复执行是在 request 这一级被阻止的，而不仅仅在轮次一级。resolver 被包裹起来，使得
transaction 文件已经存在的 request 绝不会被再次调用：包装层会重新读取那份 transaction，
要求它的 run、request、request digest、source context digest 与 authority digest 都与正
被 admit 的 request 一致，然后返回其记录的 status，用量清零，并附上一个
`idempotent_reuse` 标记和它当初计入的 `prior_budget_use`。因此一次被恢复的 run 既不能重
复一个已提交的副作用，也不能重复计入其成本，更不能在另一个 authority 下重新 admit 它。
有一种情形刻意先于两项 budget 检查：轮次记录已经持久化的 plan，每次调用至多被调和一次
——做法是重建证据并重新编译，不调用任何 resolver——这闭合了「提交一轮」与「重建该轮所产出证
据」之间的窗口；若重新编译返回相同的 context digest 与 requirement-status 向量，循环便以
`no_progress_cycle` 停止。
