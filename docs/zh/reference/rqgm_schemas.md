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
last_verified: 2026-07-28
---

# RQGM Schema 参考

可选启用的 `ari_rqgm` 执行模式所持久化的每种记录的正式 JSON
Schema。它们全部随 `ari-core/ari/schemas/` 一起发布，并可通过
`ari.schemas.load(name)` 按 basename 加载。这些记录在默认的
`simple_bfts` 检查点上一个也不存在 —— 每个读取方都把缺失视为
「RQGM 从未运行」。

这些 schema 是**参考契约，而不是运行时校验器。** `ari/rqgm/` 下没有任何
代码会打开它们：`jsonschema` 不是 `ari-core` 的依赖，任何 RQGM 写入方在
持久化之前都不会拿记录去比对 `.schema.json` 文件。记录类只是*镜像*这些
schema 文件的普通 dataclass（`ari/rqgm/proposals/records.py` 与
`ari/rqgm/adversarial/records.py` 的模块 docstring 正是这么写的）；它们背后
没有 Pydantic 模型，也没有任何快照测试断言所发布的 schema 等于生成的
`model_json_schema()`。Pydantic 的 `model_validate` 在 `ari/rqgm/` 内*确有*
使用，但仅用于单独门控的 Knowledge/Capability/Assurance 准入、harness、
capability-binding 与 manuscript 文档 —— 从不用于 `rqgm_record_base` 信封或
本页清单内的任何记录。

内核在写入时真正强制的是信封 + 形状检查，即
`ConstitutionalKernel.validate_record_schema`（`ari/rqgm/kernel.py`）：
`kernel_rules.ENVELOPE_FIELDS` 的八个字段必须存在，`record_id` /
`status` / `role` 在存在时必须非空，而 `proposal_record` 还会额外运行
proposal summary 的字段预算检查。违规对治理记录类型 `epoch_transition` /
`governance_report` 表现为 `CK-SCH-G01`（block），对其余所有记录类型表现为
`CK-SCH-N01`（warn），预算超限则为 `CK-SCH-N02`（warn）。因此下文所记录的
各字段类型、格式与封闭枚举，是由写入方和测试套件来保证的 ——
`ari-core/tests/test_rqgm_*.py` 中的若干模块会拿真实记录去校验这些 schema
文件，不过它们通过 `pytest.importorskip` 获取 `jsonschema`，缺失时即跳过
—— 而不是由持久化时刻的任何校验来保证。

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
  —— 提示词、策略、注册表和旧版 v1 事件使用的短内容标识。
- **v2 事件摘要** —— 对规范化的
  `{schema_version, event_id, event_type, transaction_id, payload,
  prev_event_hash}` 计算完整 SHA-256，绑定所有会改变重放语义的字段；
  时间戳仍在摘要之外。
- **纪元身份**（`ari/rqgm/state.py`）—— `policy_fingerprint` 摘要服务制度
  与已解析治理设置，`execution_fingerprint` 摘要声明的模型、解码、工具、
  环境与数据快照，`epoch_fingerprint` 合成两者。排除 `created_at`、
  `status` 和复合字段自身，因此 open→closed 不会改变冻结内容。

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

## 宪法违规码

内核的每一条发现都带有稳定的 `CK-<FAMILY>-<NNN>` 码，其严重度属于宪法本身，
而不是调用方的选择。严重度按码固定在 `ari.rqgm.kernel_rules.SEVERITY`
中（Knowledge/Capability/Harness 系列自 `ari/rqgm/kca_kernel_rules.py`
并入），**每一次** `Violation` 构造都经由这一张表解析
（`ari/rqgm/kernel.py` 的 `_v`、`ari/rqgm/kernel_kca_common.py` 的
`violation` —— 未知码抛 `KeyError`，绝不会以默认值补上严重度），并且整张表
位于 `constitution_hash` 之内，因此改动任一严重度都会改变这枚钉。码一经实现
即冻结，永不重新编号。

| 系列 | 所属检查 | 严重度 |
|---|---|---|
| `CK-SCH-G01` | `validate_record_schema` —— 治理记录类型（`epoch_transition`、`governance_report`）的信封 / 形状违规 | block |
| `CK-SCH-N01`、`CK-SCH-N02` | `validate_record_schema` —— 其他记录类型的同类违规；提案摘要超出字段预算 | warn |
| `CK-HSH-001`、`CK-HSH-002`、`CK-HSH-003` | `validate_hashes` —— 记录 `prompt_hash` 与该角色已注册 active 哈希不符；`artifact_hashes` 与重算 sha256 不符；无法解析的产物或 `source_ref` | warn |
| `CK-HSH-010` | `validate_hashes` —— 某个 **active** 注册表条目自身的 `prompt_sha256[:12]` 与其已注册 `prompt_hash` 不一致 | block |
| `CK-ACC-001`、`CK-ACC-002` | `validate_capability` —— `CAPABILITY_MATRIX` 未授予或 Task 11 元动作标志拒绝；访问退役提示词正文（对任何角色都不可读） | block |
| `CK-EPO-001` | `validate_epoch_invariance` —— `prompt_hash` 位于该纪元冻结 active set 之外的记录 | warn |
| `CK-EPO-002` | `validate_epoch_invariance` —— 纪元中途的非紧急状态变更事件 | block |
| `CK-REG-001`…`CK-REG-007` | `validate_transition` —— 边不在 T1–T21 表中、仅限边界的边在纪元中途打戳、声明的 `rule_id` 与表矛盾、`produced_by` 不是 RegistryTransitionEngine、缺少必需的佐证引用、紧急转换形状非法、`from_status` 与注册表矛盾 | block |
| `CK-REG-101` | `validate_authority_non_expansion` —— 候选声明的权限超过其现任（不变式 18） | block |
| `CK-ROL-001`、`CK-ROL-002`、`CK-ROL-003` | `validate_role_separation` —— 弹劾动议作者不是 Auditor、证据包作者不是 EvidenceClerk、同角色指控 | warn |
| `CK-ROL-901` | `validate_role_separation` / `validate_capability` —— RegistryTransitionEngine 以外的任何主体写注册表或激活候选（不变式 10） | block |
| `CK-ERA-001`…`CK-ERA-006` | `validate_selective_erasure` —— 前沿中出现 stale / 前沿无效 / 源自退役提示词的记录、退役提示词的依赖方未被置 stale、发生物理删除（不变式 13）、`prompt_trace.jsonl` 中带未映射退役哈希的行 | block |
| `CK-AUD-001`、`CK-AUD-002`、`CK-AUD-003` | `validate_audit_log_integrity` —— 序号回退、已检查点前缀被篡改、哈希链断裂 | block |
| `CK-CLN-001`、`CK-CLN-002` | `validate_clean_room_bundle` / `validate_contamination_free` | block |
| `CK-CTX-001` | `validate_context_scope` —— 渲染出的角色视图超出其字段白名单 | warn |
| `CK-UTL-001`…`CK-UTL-008` | `validate_utility_policy` —— 除 `CK-UTL-006`（轴键位于该纪元存活轴集合之外）为 warn 外，其余全部 block | block / warn |
| `CK-KNW-001`…`015`、`CK-CAP-001`…`018`、`CK-HAR-001`…`020` | `validate_knowledge_integrity` / `validate_capability_binding_integrity` / `validate_harness_integrity` | block |

`severity: block` 赋予判定在**执行路径查询它的地方**否决状态变更的资格；
这既不意味着每个上下文都会照办，也不意味着执行模式能触及每个上下文。尊重
[`rqgm.kernel.enforcement`](configuration.md#execution-mode-and-rqgm-governance-opt-in)
的执行点都经由辅助函数 `ari.rqgm.kernel.should_block`
（`ari/rqgm/runtime.py`、`transition_engine.py`、`frontier_repair.py`，以及
`kernel.py` 中带能力门的 MCP 包装器）；在 `audit_only` 下该辅助函数对所有
报告返回 false，同时不改动已记录的严重度，因此审计轨迹仍然如实。另一些
执行点直接读取 `report.blocking`，因而不受执行模式影响：洁净室的生成前 /
生成后筛查（`ari/rqgm/clean_room.py`）、元候选的准入门
（`ari/rqgm/meta_evolution.py`），以及治理自审的升级判定
（`ari/rqgm/governance/_self_audit.py`）。有意只做告警的上下文在两种模式下
都只告警：逐节点钩子（`per_node_warn_check`）执行 schema 与哈希检查且从不
抛出异常，`validate_context_scope` 也从不阻断节点执行。

有一条升级路径刻意独立于 `enforcement`：凡是码位于
`transition_engine.EMERGENCY_TRIGGER_CODES`（`CK-HSH-010`、`CK-EPO-002`、
`CK-AUD-001/002/003`、`CK-ACC-001/002`、`CK-ROL-901`）的 block 级违规，无论
处于哪种模式都会由 MCP 包装器交给 T16 紧急隔离路径 —— `audit_only` 降级的是
阻断，而非宪法事实，且该紧急转换本身在提交前也要经过内核校验。但这条路径
只能隔离**已注册的组件**：当行为角色没有注册表条目时（研究智能体的
`generator` 就是常见情形），升级只会被记入日志，不会组装任何转换。

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
| `schema_version` | 新事件为 `2`；旧版 `1` 仍可读取 |
| `event_id` | `evt_%06d`，按检查点单调 |
| `event_type` | 封闭集合：`epoch_transaction_prepare`、`component_registered`、`prompt_registered`、`component_status_change`、`prompt_status_change`、`epoch_close`、`epoch_open`、`epoch_transaction_commit`、`emergency_quarantine` |
| `transaction_id` | 边界事务成员标识；独立纪元开启/审计事件才为空 |
| `payload` | 事件正文 |
| `event_hash` | v2 为完整事件摘要；v1 使用 12 位载荷哈希 |
| `prev_event_hash` | 包含在 v2 摘要中；首行为 `""` |
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
| `policy_settings` / `policy_fingerprint` | 宪制、阈值、预算、治理设置及其12位摘要 |
| `execution_identity` / `execution_fingerprint` | 声明的模型/后端/温度、搜索与评估设置、技能、禁用工具，以及模型/工具/环境/数据修订固定值。缺失固定值存为 `unresolved`，并设置 `complete: false` |
| `epoch_fingerprint` | 合成政策与执行身份的12位摘要，排除 `created_at`、`status` 和自身 |
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

### 动议流水线的记录

除报告本身外，`audit_epoch` 还会向 `rqgm_audit.jsonl` 追加四类记录，
它们都携带上文的共享信封。**这四类没有独立的 schema 文件** ——
其形状由 `ari/rqgm/governance/_records.py` 中的 frozen dataclass 定义，
并由审计自身的自审步骤经内核重新校验（信封走
`validate_record_schema`，作者走 `validate_role_separation`，
即 CK-ROL-001/002/003）。

**`evidence_bundle`** —— 唯一合法的撰写者是 EvidenceClerk
（`build_evidence_bundle` 对其他作者抛出 `GovernanceRuleError`），
每个被阈值标记的对象一束，`prompt_hash` 恒为 `null`，因为 clerk 是
确定性的、不经提示词。clerk 的候选 ref 是点名该对象的记录 —— validated attack、
utility record、raw attack 以及 K/C/A 来历类型 —— 外加关于该对象的
同角色 `comparison_observation`；但后者只作为**线索**进入：观察自身的
`source_refs` 被拉进来做独立验证，而观察的 ref 本身也照样列出，
于是它的排除被记录下来，而不是被悄悄丢弃。

`items[]` 的每一项是 `{kind, ref, content_hash}`，其中 `content_hash`
是 `payload_hash(record)` —— 与本页其余部分同一套 `hash12` 方案，
不存在第二套哈希；`kind` 来自一张封闭的 `record_type → kind` 映射：

| 可采纳的 `record_type` | bundle 的 `kind` |
|---|---|
| `validated_attack` | `validated_attack` |
| `utility_record` | `utility_record` |
| `judgment_record` | `judgment_record` |
| `review_record` | `review_record` |
| `node_report` | `execution_provenance` |
| `harness_attestation` | `fixed_verifier_result` |
| `knowledge_skill_use` | `instruction_provenance` |
| `capability_binding` | `execution_authority` |

其余一律不可采纳。每一次拒收都以 `{ref, reason}` 记入
`excluded_items[]`，因此一个 bundle 既说明它携带了什么，也同样清楚地
说明它拒绝了什么。检查按固定顺序执行，记录的是第一个命中的理由：

| 顺序 | 理由 | 含义 |
|---|---|---|
| 1 | `unresolvable_ref` | 该 ref 在本纪元的记录切片中无法解析；同时把 `verification.all_refs_resolved` 翻为 `false` |
| 2 | `unadjudicated_raw_attack` | 该 ref 是一条 `raw_attack`。raw attack 永远不是证据，只有由它派生、并由裁决者撰写的 `validated_attack` 才是（不变式 8-9） |
| 3 | `same_role_source` | 该项的作者角色等于目标的角色。同角色输出是观察，绝非指控 —— 关于目标的 `comparison_observation` 与目标自身的 review record 正是因此被排除 |
| 4 | `inadmissible_record_type` | 记录类型不在上表映射内 |
| 5 | K/C/A 完整性理由 | 未通过自身检查的来历附件：工件层面（`missing_artifact_reference`、`invalid_artifact_reference`、`unsafe_artifact_reference`、`unresolvable_artifact_reference`、`artifact_digest_mismatch`），以及针对 attestation、knowledge use、capability binding 的分类型检查；完整集合见 `_evidence.py` |

组装只做排除、不做替换：既不填补，也不抛出。`verification` 为
`{checked_by: "evidence_audit_checker", all_refs_resolved}`。既然从不
填补，空 bundle 就无法支撑起诉 —— 被标记的对象若其 bundle 没有 `items`，
便不产生动议，而在 `self_audit.findings` 中留下一条
`no_admissible_evidence`。

**同角色观察是预留的，且尚未被产生。**设计上为“某组件与同角色同侪产生分歧”
的情形预留了一种治理 `comparison_observation` —— 例如某个 reviewer 给某节点
的打分不同于可能取代它的 reviewer。这种记录点名自己的
`subject_component_id` 与 `subject_role`，其构建器无条件设置
`admissible_as_evidence: false`：它是观察，绝不是指控。上文中 clerk 实现的
“只作线索、绝不作证据”规则正是它 —— 观察自身的 `source_refs` 被顺着追到一手
产物并独立核验，而观察的 ref 本身仍落入 `excluded_items`（其撰写者角色等于
目标角色时理由为 `same_role_source`，否则为 `inadmissible_record_type`），
使排除被记录而非悄然发生。

**这条路径目前是惰性的。**记录类型、其构造期不变量、证据组装中的线索追随、
以及按 subject 的可靠性聚合都已实现，但**没有任何已发布组件会把治理
`comparison_observation` 发射进 `rqgm_audit.jsonl`** —— 该构建器没有生产
调用方。因此在任何已发布运行中，报告的 `observations` 数组都是空的。请把它
当作预留设计，而不是运行会呈现的行为。相反，通用的同角色排除是活的：它适用
于撰写者角色等于目标角色的任何 bundle 候选，与记录类型无关。

该类型名与一个无关的形状同名。提示词进化的影子阶段会把它自己的
`comparison_observation`（候选与现任的输出哈希及分歧摘要）写入
`prompt_evolution.jsonl`，记载于下文的
`rqgm_prompt_evolution.schema.json`。区分二者靠的是文件与字段，而不是
`record_type`。

**`impeachment_motion`** —— 唯一合法的撰写者是 Auditor，因此 Reviewer v4
根本无法经由这条路径触及 Reviewer v3。它增加
`target_component_id`、`target_role`、`charge`、`evidence_bundle_id`、
`bond_units` 与 `requested_action`，而 `source_refs` 仅为该 bundle 的 id。
`requested_action` 是报告推荐词汇的严格**子集** ——
`demote` \| `warn` \| `quarantine` \| `retire` —— 因为动议从不提升；
超出该集合的取值在构造时即被拒绝，`target_role: auditor` 同样被拒
（Auditor 从不弹劾自己的角色）。

**`governance_defense`** —— Defender 为每个动议撰写一条，携带
`motion_id`、`defense_text` 与 `procedural_default`。走回退路径时
`prompt_hash` 为 `null`，正文即下表所引的固定程序性默认文本。

**`impeachment_outcome`** —— GovernanceJudge 为每个已裁决的动议撰写一条。
它以独立记录的形式存在，好让 Task 09 的 transition engine 无需解析整份
报告即可消费裁决结果。它镜像报告的 `adjudications[]` 条目，并额外持有
该条目只是指向的东西：`rationale` 正文（报告侧携带 `rationale_ref`，
其值正是本记录的 id），以及当确定性评分板推翻裁决者判断时置位的
`clamped_by_board`。`outcome` 是封闭集合 `upheld` \|
`partially_upheld` \| `dismissed` \| `inconclusive`。

**保证金账本。**对滥诉的抑制不经过 LLM。每提起一个动议，就按
`rqgm.governance.bond_units_per_motion` 向纪元级的起诉预算
`max_motions_per_epoch × bond_units_per_motion` 押入保证金。结算是裁决结果的
纯函数：`upheld` 与 `partially_upheld` 退还，`dismissed` 没收，
`inconclusive` 则继续押着 —— 既不退还也不没收。代码把这称作"顺延到下一
纪元"，但**并没有发布任何顺延机制**：步骤 1 只读取本纪元的记录切片，
未决动议不会被再次读入，下一纪元是从新的可靠性分类重新导出动议的。
预算一旦耗尽，无论阈值怎么说，本纪元都不再提起动议。有两点容易误读。`remaining_budget` 只计
*提起*所消耗的部分，因此退还并不会在本纪元内恢复提起额度。而账本在每次
`audit_epoch` 时新建，故每到边界即重置：它不跨纪元累积惩罚，这意味着对一个
纪元接一个纪元地滥诉的起诉者，其威慑力不足。其结果就是报告的
`bond_accounting` 块 —— `posted`、`refunded`、`forfeited`、
`remaining_budget`。它们是配额计数器而非货币：组件之间并没有价值转移。

**`self_audit` 块。**步骤 8 用衡量所有人的同一把尺去审计司法自身，而且在这里
拥有最终发言权的是**内核**而不是编排器。流水线刚刚产出的每一条
`evidence_bundle`、`impeachment_motion`、`governance_defense` 与
`impeachment_outcome` 都被回送给 `ConstitutionalKernel.validate_record_schema`
与 `validate_role_separation`。记录构建器自身的拒绝只是早期优化；保证在于
这次重跑，从而使一个有缺陷或已进化的治理组件无法把违规记录夹带进报告。
该块携带：

| 键 | 内容 |
|---|---|
| `checked_components` | 受检治理主体的排序列表：auditor、evidence clerk、defender、governance judge |
| `kernel_violations_found` | 重新校验得到的违规计数 |
| `findings` | 审计过程中立起的确定性发现 —— `judge_clamped_by_board`、`no_admissible_evidence`、`same_role_prosecution_skipped`、`motion_refused` 等 |
| `escalations` | 对每份**阻断性**内核报告中的各条违规给出 `{code}:{subject_ref}` |
| `ban_recommendations` | 被污染类代码牵连的主体 —— `CK-AUD-001`（审计日志只追加违规）、`CK-AUD-002`（审计日志前缀篡改）、`CK-AUD-003`（审计日志哈希链断裂）、`CK-ACC-002`（访问已退役提示词正文）、`CK-ROL-901`（伪造注册表写入权限）—— 以及任何 `contamination` / `clean_room_lineage_failure` 发现。RegistryTransitionEngine 读取此键；它仍只是建议，且封禁只施加于确实处于 retired 的组件 |
| `stats` | `auditor_motion_precision`、`judge_board_clamp_count`、`defender_substantive_rate`。若本纪元一个动议也没提起，这两个比率为 `null` —— 绝不插补 |

`governance_report.schema.json` 只声明了前四个键；`ban_recommendations` 与
`stats` 是增量的，作为未声明属性随记录一起传递。若没有可用的内核，或重新
校验自身抛出，该块降级，并向 `degradation_reasons` 加入
`self_audit_degraded`。

### 审计的确定性预算

审计恰好有三处 LLM 接缝 —— 步骤 4（起诉）、步骤 5（辩护）与步骤 6（裁决）
各自接受一个可选的 renderer。其余步骤都没有模型介入，只依据本纪元审计日志
切片与冻结注册表运行。每一处接缝都先由规则裁断，只有在边界处才去问模型。

**起诉是规则优先、LLM 其次。**`classify_target`
（`ari/rqgm/governance/_prosecution.py`）读入一条 ReliabilityMonitor 条目，
返回三种答案之一。当至少有 `ATTACK_THRESHOLD`（2）条 validated attack 绑定
到某组件，或其可靠性分数低于 `RELIABILITY_FLOOR`（0.4）时，该组件被**直接
提起**。当恰好有一条 validated attack 绑定到它，或其分数落在
`[RELIABILITY_FLOOR, RELIABILITY_FLOOR + BORDERLINE_MARGIN)` 即
`[0.4, 0.5)` 时，它处于**边界**—— 也只有此时才会运行 LLM Auditor 提示词。
其余一概不动。三个阈值都是模块常量，与内核的规则表一样固定在代码里；可配置
的只有 `rqgm.governance` 之下的预算。边界情形下若 auditor 回复缺失或无法
解析，则完全不提起动议 —— 这就是现任推定，与
`LineageDecision.fallback_continue` 同形。

有两类对象从不被起诉：

- **`tier: fixed` 的组件。**tier 检查是分类器的第一条语句，在读取任何阈值
  之前就返回“无案”，因此固定组件无论被多少攻击点名都不可起诉。固定程序是
  宪法机制而非制度上的现任者：它们的完整性发现会暂停或修复受影响的产物，
  而不进入弹劾竞争。
- **角色为 `auditor` 的目标。**唯一的 Auditor 无法对自己的角色提起，因此
  该目标被跳过，并作为 `same_role_prosecution_skipped` 记入
  `self_audit.findings`，而不是被悄悄丢弃。

`audit_epoch` 绝不因某一步失败而中止。九个步骤各有一个全域的确定性回退；
一旦取用，`degraded` 翻为 `true`，并向 `degradation_reasons` 追加一个记号。

| 步骤 | 失败时 |
|---|---|
| 1 收集观察 | 本纪元的记录切片为空，于是步骤 2-6 无事可做 |
| 2 可靠性评估 | 没有可靠性条目。与步骤失败无关地，本纪元未撰写任何内容的组件会得到 `reliability_score: null` 与 `insufficient_data: true` —— 分数绝不被杜撰，而该组件仍可凭其 validated attack 计数被起诉 |
| 3 证据组装 | 没有 bundle，因而没有动议。逐项失败到不了这一行：组装不抛出，只排除（见上） |
| 4 起诉决定 | 没有动议。处于**边界**分类、其 auditor 调用不可用或无法解析时同样不提起（现任推定）；明确越过阈值的分类是规则驱动的，完全不需要 LLM |
| 5 生成辩护 | 辩护变为固定的程序性默认文本 *"no substantive defense generated; incumbent presumption applies"*，并置 `procedural_default: true` |
| 6 裁决 | 裁决者不可用或回复无法解析时判 `dismissed`，即有利于现任 —— 下文所述的评分板钳制同样作用于这一回退。评分板打分失败则判 `inconclusive`，其保证金既不退还也不没收而是继续押着 —— 动议被留作未决，而不是被作出结论。以 governance judge 自身为目标的动议将被回避，不产生 outcome 记录。并行的候选评估失败则使 `candidate_evaluations` 为空 |
| 7 重放池更新 | 池更新被跳过并标记 |
| 8 治理自审 | 内核重新校验被跳过：`kernel_violations_found` 保持为 0，也不上报升级。若整个步骤失败，该块回退为 `checked_components` 与 `stats` 均为空的桩 |
| 9 产出报告 | **唯一**可能抛出的步骤。调用方的 fail-open 捕获（`ari/rqgm/runtime.py`）记录日志并返回空报告；由于外观层只在流水线返回之后才追加审计记录，该纪元便一条治理记录也不留下，而运行继续 |

schema 把 `degradation_reasons` 声明为普通字符串数组 —— 约束词汇的是
发射端而非枚举。已发布的流水线只发射以下形式：

| 记号 | 发射条件 |
|---|---|
| `step_failed:observe`、`step_failed:assess_reliability`、`step_failed:assemble_evidence`、`step_failed:prosecute`、`step_failed:defend`、`step_failed:adjudicate`、`step_failed:evaluate_candidates`、`step_failed:update_replay_pool` | 该步骤抛出并取用了上表的回退 |
| `auditor_llm_fallback:{component_id}` | 某个边界目标的 auditor 调用不可用或无法解析 |
| `defender_llm_fallback:{motion_id}` | 辩护回退到程序性默认 |
| `judge_llm_fallback:{motion_id}` | 没有可用的裁决样本，动议被驳回 |
| `board_failure:{motion_id}` | 评分板打分抛出，动议成为 `inconclusive` |
| `self_adjudication_recused:{judge_component_id}` | 动议以 governance judge 为目标，遂留作未决交由外部裁决 |
| `replay_pool_update_skipped` | 有 upheld 案例待加入，但池未暴露 `append_case` |
| `llm_budget_exhausted` | 触到 [`max_llm_calls_per_audit`](configuration.md#execution-mode-and-rqgm-governance-opt-in) 上限，或 Task 12 的预算管理器拒绝了调用 |
| `self_audit_degraded` | 自审的内核重新校验不可用或抛出 |

不存在 `step_failed:produce_report` 记号：步骤 9 是唯一不降级的步骤。

当 `llm=None` 时，审计完全走这些纯规则路径；对同一输入运行两次，
在剥离 `created_at` 后会产出逐字节相同的记录。

**即使 LLM 正常工作，裁决者依然被约束。** ReplayBoard 与 AnchorBoard 的
分数在 GovernanceJudge 裁决之前算出，裁决被它们约束 —— 这与节点
`results.json` 的 measurements 覆盖 LLM 对截断后 artifact 文本的读取，
是同一条优先关系。评分板分数是该对象已存案例结果的均值，按 case id 顺序
最多取 `rqgm.replay.max_cases_per_epoch` 个案例；当动议把 retirement 摆上
台面时（它请求 `retire`，或以已处于 quarantine 的组件为目标），上限升为
`rqgm.replay.max_cases_for_retirement`，而存在的 Task 12 预算管理器还可能
把它继续压低。没有任何匹配案例时分数为 `null` —— *不可用*，而绝不是编造
的数字。

随后裁决会与现任的*可用*评分板分数的均值比对。两个阈值是
`ari/rqgm/governance/_adjudication.py` 中的模块常量，固定在代码里而非
配置里：

| 现任的评分板均值 | 评分板拒绝的裁决 | 钳制为 |
|---|---|---|
| ≥ 0.8 (`BOARD_HIGH`) | `dismissed` 之外的任何结论 | `dismissed` |
| ≤ 0.2 (`BOARD_LOW`) | `dismissed` | `partially_upheld` |

两个评分板都不可用时不存在约束，裁决按原样保留。钳制在上表的步骤 6 回退
之后最后施加，因此回退同样被约束：裁决者不可用而判出的 `dismissed`，若
对象分数 ≤ 0.2 仍会变成 `partially_upheld`。一次钳制会在
`impeachment_outcome` 记录上置 `clamped_by_board: true`，并向
`self_audit.findings` 添加一条 `judge_clamped_by_board`，计入
`self_audit.stats.judge_board_clamp_count` —— 系统性偏袒现任或挑战者的
裁决者会显现在审计里，而不是悄悄生效。

候选提示词由同样的评分板打分，**绝不**经由裁决者：可用评分板分数的最小值
达到 0.6 (`CANDIDATE_PASS_THRESHOLD`) 即 `pass`，否则 `fail`；两个评分板
都没有分数时为 `inconclusive`。当 `rqgm.replay.use_cached_results`（默认
开启）时，已接入的 Task 12 治理缓存会先于池中已存案例结果被查询，并由其
回填；`candidate_evaluations[].cached` 报告的是该设置，而不是缓存是否存在
或某次查询是否命中。

启用 `rqgm.governance.jury_panel_enabled` 后，裁决者被采样三次并由多数
决定；平票按固定顺序 `dismissed` > `partially_upheld` > `upheld` 倒向
现任。默认为 `false`，由单次采样决定。

有两个报告字段受结构约束而非受失败约束，二者都不会立起降级记号。

**AnchorBoard 需要一份留出语料，而只有 paper 阶段提供它。**两块评分板都从
传给 `audit_epoch` 的池中读取案例：ReplayBoard 读 `pool.cases`，AnchorBoard
读 `pool.anchor_cases`。探索运行传入的池 `AdversarialReplayPool` 并未定义
`anchor_cases` 属性，因此在该路径上 AnchorBoard 报告*不可用*而不是给出分数：
`anchor_score` 在每一次裁决与每一次候选评估中都是 `null`，
`budget_usage.anchor_cases_used` 始终为 0，而能够钳制裁决者判断的现任侧
评分板均值与候选的通过判定都仅由 ReplayBoard 决定。留出锚定集合只在
paper-archive 阶段才抵达审计 —— 该阶段换入一个携带它的、池形状的适配器
（`ari/rqgm/paper_anchor.py`）—— 而那份语料本身默认也是关闭的（见下文
`paper_anchor_corpus.jsonl` 条目）。`null` 的锚定分数应读作“没有可用的留出
语料”，绝不可读作低分。

**`replay_pool_updates.retired` 是惰性的。**真正被填充的只有 `added`：本纪元
的 validated attack 被收录成的重放案例，加上任何 `upheld` /
`partially_upheld` 动议背后的 validated attack ref。`retired` 数组以空值
初始化，且没有任何代码向它追加：案例的退役是池内部的操作
（`evict_to_cap` 只在快照中把案例标记为 `evicted`，而 JSONL 保留曾经收录的
每一行），审计并不在此处将其暴露出来。由*已退役提示词*引发的陈旧化交由前沿
修复（Task 10）处理，不通过本字段报告。

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

在探索（`ari_rqgm`）侧，研究 `generator` 是已注册创始组件。节点只写一次
生成组件、提示词摘要和纪元。七种对抗者类型只有在该来源与纪元冻结现任一致时
才绑定 `generator_v1`；旧记录、缺失或不匹配来源保持无目标，不会让后继为前任
成果受罚。

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

这些字段描述的是过期已评分证据擦除后的重算。效用策略退役走另一条
Task-10 路径：在新策略下重新组合每个节点保存的 `_axis_scores`，并把节点
记入外层 `SelectiveErasureEvent.policy_rescored_node_ids`；缺少原始轴的
节点以 fail-closed 方式无效化。

### `rqgm_replay_pool.schema.json`

**用途：**AdversarialReplayPool 的派生字节固定快照
`rqgm/adversarial_replay_pool.json`；`rqgm_adversarial_cases.jsonl`
仍是真相源，并在加载时补齐任何崩溃尾部。**所属模块：**
`ari/rqgm/adversarial/pool.py`；经
`ari.checkpoint.save_adversarial_pool_json` 持久化。

| 字段 | 说明 |
|---|---|
| `case_seq` | 单调案例计数器 |
| `cases[]` | AdversarialReplayCase：`case_id`（`adv_case_%05d`）、`case_type`（随发布 schema 的七种探索类型；paper runtime 增加下文所述、阶段外 inert 的第八种）、`validated_attack_id`、`severity`、`admitted_epoch` / `last_confirmed_epoch`、`status` `active` \| `evicted`（逐出为仅逻辑）、`replay_view`（完整材料 —— 对角色 `clean_room_generator` 拒绝）与 `abstract_view`（污染安全的 FailureSummary —— 不含原始攻防文本） |

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
| `emergency` | `true` 表示在一个强制紧急边界中隔离并开启下一纪元的 T16 形状 |
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
| `invalidated_node_ids` / `recompute_node_ids` / `abandoned_pending_node_ids` | 对过期依赖闭包的节点处置 |
| `policy_rescored_node_ids` | 可选且增量式的 #77 字段：列出在新效用策略下由已存 `_axis_scores` 重新加权、因而未被无效化的节点 |
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
