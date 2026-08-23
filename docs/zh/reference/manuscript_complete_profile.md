---
sources:
  - path: ari-core/ari/manuscript/profiles.py
    role: implementation
  - path: ari-core/ari/manuscript/builder.py
    role: implementation
  - path: ari-core/ari/manuscript/snapshot.py
    role: implementation
  - path: ari-core/ari/manuscript/readiness.py
    role: implementation
  - path: ari-core/ari/manuscript/briefs.py
    role: implementation
  - path: ari-core/ari/manuscript/publication.py
    role: implementation
  - path: ari-core/ari/manuscript/runtime.py
    role: implementation
  - path: ari-core/ari/manuscript/coordinator.py
    role: implementation
  - path: ari-core/ari/manuscript/contracts.py
    role: schema
  - path: ari-core/ari/cli/paper_dispatch.py
    role: implementation
  - path: ari-core/ari/config/__init__.py
    role: config
  - path: ari-core/config/workflow.yaml
    role: config
  - path: docs/adr/manuscript_complete/MC-ADR-007-runner-up.md
    role: doc
last_verified: 2026-08-16
---

# `generic_empirical_v1` profile

首个 profile 面向 empirical 论文。适用性由带类型的 context 特性推导得出；
写作者无法把某条 requirement 排除在外。

| Requirement | 适用条件 | Authoring | Publication | 主 resolver |
|---|---|---:|---:|---|
| MC-RQ-001 问题/目标 | 始终 | block | block | method/人工澄清 |
| MC-RQ-002 hypothesis/证伪 | hypothesis testing | block | block | method/人工澄清 |
| MC-ME-001 method | 始终 | block | block | artifact recovery |
| MC-ME-002 configuration/environment | empirical | block | block | artifact recovery |
| MC-ME-003 protocol/workload/停止规则 | empirical | block | block | artifact recovery/validation |
| MC-RS-001 primary result 的 identity | result claim | block | block | projection/validation |
| MC-RS-002 uncertainty | stochastic claim | block | block | repetition |
| MC-CP-001 baseline | comparative claim | block | block | baseline 实验 |
| MC-CP-002 等价 protocol | comparator 存在 | block | block | validation |
| MC-AB-001 component ablation | multi-component claim | block | block | ablation |
| MC-CL-001 claim coverage | result claim | block | block | projection rebuild |
| MC-CL-002 数值可复现性 | numeric result | block | block | projection/validation |
| MC-NG-001 negative accounting | 始终 | report | block | projection/disclosure |
| MC-SL-001 selection accounting | candidate 有多个 | report | block | projection rebuild |
| MC-RW-001 已记录 related work | 始终 | block | block | 已记录 retrieval |
| MC-RW-002 novelty distinction | novelty claim | block | block | 已记录 retrieval/人工 |
| MC-LM-001 limitations | 始终 | block | block | disclosure |
| MC-LM-002 validity threats | empirical | report | block | disclosure |
| MC-RP-001 EAR/source/environment | empirical | block | block | artifact recovery |
| MC-RP-002 命令/lock | reproducibility claim | block | block | artifact recovery |
| MC-AS-001 当前 certification | assurance enforce | report | block | 固定 certification |
| MC-OM-001 omission accounting | manuscript 已启用 | block | block | projection rebuild |

`stochastic_claim`、`comparative_claim`、`multi_component_claim` 这类特性来自
已记录的测量、configuration、metric 词汇、contribution 结构与 node 标签，
不会从 reviewer 的散文中推断。将来更改 profile 需要新的 profile ID/version，
因此也需要新的 attempt identity。

## Profile 的解析

`generic_empirical_v1` 不只是默认的 profile，它是目前唯一能被解析出来的 profile。
`manuscript.profile`（`ari-core/ari/config/__init__.py:687`）在 pipeline 边界上
以 `ARI_MANUSCRIPT_PROFILE`（`ari-core/ari/cli/paper_dispatch.py:97`）导出，被
读回到 compile 调用（`ari-core/ari/manuscript/runtime.py:90`），并在构建任何
snapshot 之前交给 `resolve_profile`（`ari-core/ari/manuscript/coordinator.py:152`）。
对 `generic_empirical_v1`，`resolve_profile` 返回内置的 root
（`ari-core/ari/manuscript/profiles.py:333`）；其他任何 ID 都会到
`ari-core/ari/manuscript/venue_profiles/` 下的 venue profile 声明中去查找。该目录
只放着自己的 README，因此其余任何取值都会在 snapshot、context 与 readiness
report 都尚不存在时抛出 `unknown manuscript profile`
（`ari-core/ari/manuscript/profiles.py:345`）。在 `manuscript.mode: off` 下这个 ID
根本不会被解析——dispatcher 不导出该变量就 yield，`compile_manuscript` 返回
`disabled`——因此一个拼错的或出于期望而写下的 profile ID，会一直惰性地待到第一次
`audit` 或 `enforce` 的 run。

这套 lookup 背后的 composition 机制是完整的。一份 `ManuscriptVenueProfileV1`
声明会以它被写就时所针对的那个确切 `profile_digest` 指名每个 parent，只陈述自身
的 requirement 覆盖、新增与 `removed_requirement_ids`，并在读取时解析成一个普通
的 `ManuscriptRequirementProfileV1`——其 `profile_digest` 就是解析后的 digest；
version 或 digest 已经移动的 parent 是错误而非警告，而已存盘的声明必须 pin 住其
composition 所能复现的 `resolved_profile_digest`。缺的只是：没有任何一份实例随
代码一起发布。这是范围的划线而不是疏漏——venue 的词汇属于需要它的那个
deployment，而 `ari-core/ari/manuscript/venue_profiles/` 下的模块 README 载有编写
步骤。对读者而言，其后果范围很窄却很锋利：在 `manuscript.profile` 里写下一个
venue 并不是一步配置。在该目录里出现对应 ID 的声明文件之前，它会让这次 run 失败。

## 随机性与 uncertainty evidence

MC-RS-002 被判定所依据的，正是决定它是否适用的那同一个派生值。
`build_manuscript_context` 计算出单个 `uncertainty_evidence` 布尔值
（`ari-core/ari/manuscript/builder.py:392`）：当已记录的 measurement record 多于
已记录的 configuration 且不少于两条时，或者当 evidence record 上任一 metric
key——抑或 measurement record 上任一 key——含有 `std`、`variance`、`confidence`、
`stderr`、`error_bar` 时，为 true。正是这个布尔值使 claim 成为 stochastic
（`:407`），同时它也是被存为 `reproducibility.uncertainty_evidence` 的那个值
（`:461`），而评估器判定 satisfaction 时读的恰恰就是它
（`ari-core/ari/manuscript/readiness.py:100`）；applicability 读的则是
`claim_characteristics.stochastic_claim`
（`ari-core/ari/manuscript/readiness.py:20`）。

profile 没有规定任何最小值。检查的是有无，而不是重复次数、离散度阈值或 seed 的
条数，因此该 requirement 中自动检测的那一半无法打开缺口。在没有任何声明时，
MC-RS-002 只在 `uncertainty_evidence` 本就为 true 的 run 里才适用，而它随即就被
同一个 flag 满足；这样的 run——每个 configuration 只有一条 measurement、且没有
离散度 key——此时会被记为 `not_applicable` 而绝不会是 `missing`。
因此这条 requirement 只有在
claim 被*声明*为 stochastic 时才咬合——通过 `claim_characteristics` 的
`stochastic_claim`，或 idea record、research contract、带类型的 claim record 上的
`stochastic` / `aggregate` claim type（`ari-core/ari/manuscript/builder.py:166`，
调用点在 `:378`）——并且已记录的证据并不支撑它。一旦咬合，如上表所示，它同时阻断
authoring 与 publication。把 `not_applicable` 的 MC-RS-002 读作“没有人声明
stochastic claim，也没有记录任何离散度”，绝不要读作“重复性已被检查并判定为充分”。

## Evidence lane 的分配

`build_manuscript_context` 通过运行一份固定的有序检查列表
（`ari-core/ari/manuscript/builder.py` 中的 `_lane`），为 exploration snapshot
的每个 node 恰好分配一条 evidence lane。第一条命中的检查胜出，并给出该 lane
以及记录在 `EvidenceRecordV1.reason_codes` 上的 reason code。

检查 2–5 所读的 provenance status，是 `node_provenance_audit.json`（workflow
stage `audit_node_provenance`）中记录的逐 node status，与 snapshot projection
针对该 node 引用的每个 artifact 重新计算出的 status 的并集。

| # | 检查 | Lane | Reason code |
|---:|---|---|---|
| 1 | 终态 execution status：`failed`、`abandoned`、`cancelled`、`error`、`inconclusive`、`null` | contextual_negative | `execution_<status>` |
| 2 | 存在重新 hash 后与已记录 digest/size 不一致的被引用 artifact | excluded | `artifact_digest_mismatch` |
| 3 | 存在已从 checkpoint 消失的被引用 artifact | excluded | `artifact_missing` |
| 4 | 存在不安全的被引用 artifact：path escape、symlink 成分、不可读/不可解析，或指名其他 node 的 attestation | excluded | `artifact_invalid` |
| 5 | 存在 audit 无法对照已记录 baseline hash 校验的被引用 artifact，或存在完全未指名 path 的 node artifact 条目 | exploratory | `artifact_unhashed` |
| 6 | `valid_for_frontier` 为 false —— RQGM 的 selective erasure（`_valid_for_frontier: false`）或 `_stale` metric sentinel | excluded | `stale_or_erased` |
| 7 | 没有 real data，或没有 metric | contextual_negative | `no_real_measurement` |
| 8 | `frontier_class == "debug_frontier"` | exploratory | `debug_frontier` |
| 9 | `frontier_class == "uncertified_frontier"` | exploratory | `uncertified_frontier` |
| 10 | 存在 `fail` 或 `tampered` 的 property verdict | excluded | `assurance_property_failed` |
| 11 | `assurance.mode: enforce`，却未同时具备**全部四项**：assurance status 为 `pass`、assurance tier 为 `certify`、至少一条被 admit 的 certify attestation、一个已记录的 verified target digest | exploratory | `certification_required` |
| 12 | `assurance.mode: audit`，且*已记录的* assurance status 不是 `pass` | exploratory | `assurance_<status>` |
| 13 | 其余情况 | publishable | `typed_measurement` |

该顺序是规范的。provenance 完整性（2–5）先于 assurance（10–12）被检查，因此
一个无法对照已记录 identity 重新 hash 其 artifact 的 node，无论被 certify 得
多好都会 excluded。frontier class（8–9）先于依赖 mode 的检查被检查，因此 debug
或 uncertified 的 frontier node 在任何 mode 下都不会 publishable：RQGM 已经
记录该 node 的 harness verdict 为 `fail`（`debug_frontier`），或者根本没有确立
`pass` verdict —— inconclusive、infrastructure error，或被 KCA 拦下
（`uncertified_frontier`）。任何 assurance mode 都不得把它重新提升为 publication
的支撑。

### 对 mode 的依赖

检查 1–10 与 13 不依赖 mode。只有检查 11–12 读取 `assurance.mode`
（`off` | `audit` | `enforce`，`AssuranceRuntimeConfig`）：

| node 形态 | `off` | `audit` | `enforce` |
|---|---|---|---|
| typed measurement，无 attestation | publishable | publishable | exploratory |
| 只有 screen attestation，无 certify | publishable | publishable | exploratory |
| 对照已记录 target 被 admit 的 certify `pass` | publishable | publishable | publishable |
| 已记录的 assurance status 不是 `pass`，但 property 仍为 `pass` | publishable | exploratory | exploratory |
| 存在 `fail` 或 `tampered` 的 property | excluded | excluded | excluded |
| stale 或已被逻辑擦除 | excluded | excluded | excluded |
| 唯一的 certify attestation 绑定到另一个 target | publishable | publishable | exploratory |
| debug 或 uncertified 的 frontier | exploratory | exploratory | exploratory |

`audit` 刻意不降级那些仅仅缺少 certification 的证据。检查 12 只对*已记录的*
非 `pass` assurance status 触发；空的 `assurance_status` 会一路落到
`publishable`。没有 assurance record 意味着没有运行 assurance，这是 legacy
姿态，而拒绝把它当作 publication 支撑，正是 `enforce` 所增加的东西。

`target_digest` 与该 node 的 `verified_target_digest` 不匹配的 attestation，
会以 artifact status `stale` 被 project。`stale` 不属于会使 node 被 excluded
的那些 status（2–4），因此这样的 node 在 `off` 与 `audit` 下仍然 admissible；
只是该 attestation 不会被 admit 进 `certify_attestation_item_ids` —— 当它是唯一
一条 certify attestation 时，检查 11 便在 `enforce` 下降级该 node。

### lane 的后果

只有 `publishable` lane 的 record 会进入 section brief 中允许用于正面 claim 的
证据；`exploratory` 与 `excluded` 的 record 被列为 forbidden，
`contextual_negative` 的 record 被列为只可披露。另外，
`EvidenceRecordV1.claim_eligible_fact` 对 `publishable` 与 `exploratory` 为
true，对 `contextual_negative` 与 `excluded` 为 false；契约拒绝任何在
`publishable` lane 之外声称 publication eligibility 的 record，也拒绝任何在
negative/excluded lane 之内声称 claim eligibility 的 record。

## subject 的选择

MC-SL-001 与 MC-AS-001 都取决于 compiler 如何挑选论文的 subject。该决定被
project 到 `ManuscriptContextV1` 的两个 block 上：`subjects` 承载由不同 policy
计算出的两个 subject，`assurance` 则在 certification 证据旁重复这一结果。

`scientific_winner` 来自 snapshot 自己的 selection policy，其 payload 被 hash
进 `ExplorationSnapshotV1.selection_policy_digest`：

| Payload key | 值 |
|---|---|
| `policy` | `manuscript-scientific-winner-v1` |
| `validity` | `valid_for_frontier` |
| `eligibility` | `real_data_then_all` |
| `order` | `scientific_score_desc`，其次 `node_id_desc` |

`real_data_then_all` 的意思是：只要有任一 valid node 带有 real data，就取带
real data 的那些 valid node；否则取全部 valid node。node 的 score 是
`metrics["_scientific_score"]`（当该值为实数时），否则是 key 不以 `_` 开头的
numeric metric 中最大的那个，再否则就没有 score；boolean 从不计入，而没有
score 的 node 排在每个有 score 的 node 之后。metric 经由一道 JSON 安全处理
进入 snapshot——只要有任一值非有限，整个 mapping 就会被字符串化——因此一个
`NaN` 就会让该 node 没有 score。

`publication_candidate` 当且仅当 winner 自身的 evidence record 位于
`publishable` lane 时才是 scientific winner。否则 candidate 为 null，并由
`selection_reason` 记录属于哪种情况：

| `selection_reason` | 含义 |
|---|---|
| `scientific_winner_is_publishable` | candidate 即 winner |
| `certified_alternative_available:<node-id>` | candidate 为 null；被指名的 node 是同一排序下 score 最高的 publishable node |
| `no_publishable_candidate` | candidate 为 null；没有任何 node 是 publishable |

`certified_alternatives` 按 snapshot 顺序——先 depth，再 node ID——列出除
scientific winner 之外的每个 publishable node，而不是按 score 排序，因此
reason code 指名的那个 node 未必是第一条。该字段与 `assurance.certified_node_ids`
都说“certified”，但它们施加的谓词是 `publishable` lane；只有在
`assurance_mode=enforce` 下，该 lane 才要求一条 certify 层级的 attestation。

`assurance` block 在 `certified_node_ids`（每个 publishable node，含 winner）、
node 记录为自身 certify attestation 的那些 `present` harness-attestation item，
以及每个并非 `present` 的 harness-attestation item 旁边，重复
`publication_candidate`、`scientific_winner` 与 `selection_reason`。MC-AS-001
读的正是这个 block：只有当 candidate 非 null 且出现在 `certified_node_ids` 中
时才被满足；当完全没有 certify attestation item 时，它报告 `unavailable` 而不是
`missing`。在 `enforce` 下，null 的 candidate 还会额外添加一条自动 limitation，
声明 scientific winner 尚不具备可用于 publication 的 certification。MC-SL-001
读取 `node_count` 与 `selection_reason`，只有当 exploration history 对每个
snapshot node 恰有一条条目、且已记录 reason 时才被满足。

记录一个 alternative 不等于选择它。依据
[MC-ADR-007](../../adr/manuscript_complete/MC-ADR-007-runner-up.md)，compiler
绝不会用一个 publishable 的 runner-up 替换被 block 的 winner：没有任何代码把
`certified_alternatives` 读回来当作 subject，而一次静默替换会在不声明的情况下
改变论文讲的是什么。winner 保持 publication-blocked，直到一次明确的 selection
决定创建新的 attempt。整个 `subjects` block 还会作为 `subject-selection` item
抵达 abstract 的 section brief，因此写作者收到的是这处分歧及其原因，而不只是
幸存下来的那个 subject。

### 当不存在 publication candidate 时

MC-AS-001 仅在 `assurance.mode: enforce` 下适用——`assurance_enforce` 特性就是
`assurance_mode == "enforce"`，别无其他——并且它阻断 publication，但不阻断
authoring。因此 null 的 candidate 在不同 mode 下付出的代价不同：

| `assurance.mode` 与 attestation 状态 | MC-AS-001 的 status / reason | 对 authoring verdict 的影响 | 对 publication verdict 的影响 |
|---|---|---|---|
| `off` 或 `audit` | `not_applicable` / `applicability_rule_false` | 无 | 无 |
| `enforce`，`assurance.attestation_item_ids` 非空 | `missing` / `publication_certification_missing` | 无 | `blocked` |
| `enforce`，`assurance.attestation_item_ids` 为空 | `unavailable` / `publication_certification_unavailable` | 至多 `ready_with_disclosures` | `blocked` |

在 `off` 与 `audit` 下该 requirement 是惰性的：没有 evidence ref，没有
resolver，也不影响 verdict。此时 `PublicationDecisionV1` 的 `assurance`
子裁定是 `not_required` 而不是通过，因为 runtime 只在 mode 为 `enforce` 时才把
assurance 标记为 required。null 的 candidate 及其 `selection_reason` 仍然记录
在两个 block 中。

第三行只通过一条通用规则影响 authoring verdict：任何 `unavailable` 的
requirement 都会把 `ready` 的报告降级为 `ready_with_disclosures`。MC-AS-001 在
两种失败行中都从不阻断 authoring，也从不改善其他 requirement 已经压低的
authoring verdict。

这种不对称正是设计。因为 enforce lane 只在 assurance status 为 certify 层级
且通过、至少有一条被 admit 的 certify attestation、并存在 verified target
digest 时才把 node 认定为 `publishable`，所以 `enforce` 下非 null 的 candidate
总是 certified —— 于是那两种失败行恰好就是会拿到自动 certification limitation
的 run。带着 uncertified winner 的 enforce run 仍然会写作，而 limitation 把这处
缺口写进 manuscript。写明缺口的 draft 是正当的 artifact；把同一份 draft 呈现为
已 certified 则不是。只有 publication lock 仍然不可达，直到一份当前有效的
certification 覆盖该 subject。

### 保留：一次明确的 selection 决定

MC-ADR-007 只允许在具备带 version 的 selection policy 和强制披露时，才推翻
“不回退”的默认。**没有实现任何这样的 policy。** `ManuscriptRequirementProfileV1`
与 `RequirementSpecV1` 的任何字段、任何配置 key、任何代码路径都不会把
runner-up 提升为 subject；当 winner 不是 publishable 时，candidate 无条件为
null。上面的 `selection_policy_digest` 也不是那种 policy —— 它固定的是
scientific winner 如何排序，而不是 subject 是否可被替换。

如果将来真的加入这样的 policy，那么在 readiness 可以报告 `ready` 之前，subject
的改变必须针对新的 subject 重新计算 applicability、每一条 requirement result
以及 `limitations`：针对旧 subject 评估出的 requirement 集合并不描述新的
subject，而跨越 subject 变更被继承下来的 limitation，是对一个已不再是论文
subject 的 node 的披露。该义务属于保留的设计，而不是可用的行为。
