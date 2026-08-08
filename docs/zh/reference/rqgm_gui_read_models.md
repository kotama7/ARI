---
sources:
  - path: ari-core/ari/viz/v1/rqgm.py
    role: implementation
  - path: ari-core/ari/viz/v1/dto.py
    role: implementation
  - path: ari-core/ari/viz/v1/router.py
    role: implementation
  - path: ari-core/tests/test_gui_v1_rqgm.py
    role: test
last_verified: 2026-08-09
---

# RQGM GUI 读模型

十二个 `GET /api/v1/runs/{run_id}/rqgm/*` 端点是一个覆盖检查点已提交 RQGM
工件的**离线投影器**。本页记录每个载荷的含义、它来自哪个工件，以及 API
强制执行的真实性规则 —— 有了这些规则，UI 就无法渲染出证据不支持的治理断言。

这些工件所包含的*记录形状*（schema、id 格式、哈希纪律）见
[RQGM Schema 参考](rqgm_schemas.md)。传输层面的问题（错误信封、游标、认证）见
[REST API → `/api/v1`](rest_api.md#apiv1规范接口)。治理机制本身见
[RQGM 架构](../concepts/rqgm_architecture.md)。

## 基本规则

读取器（`ari-core/ari/viz/v1/rqgm.py`）受五条约束支配，本页每一个载荷的形态
都源自它们：

1. **从不导入 `ari.rqgm`。** 读模型直接解析已提交的检查点工件，不重新执行
   任何内核或得分策略决策。唯一被复现的 RQGM 算术是带 schema 版本的事件摘要
   契约：旧的 schema-v1 记录仍使用只覆盖载荷的短哈希
   `hash12(canonical_json(payload))`，而 schema-v2 记录使用覆盖全部与重放相关
   的信封字段（`schema_version`、`event_id`、`event_type`、`transaction_id`、
   `payload`、`prev_event_hash`）的完整 SHA-256。这是有意重复实现的，因为
   viz → governance 的导入边是被禁止的；与生产辅助函数的一致性由
   `ari-core/tests/test_gui_v1_rqgm.py` 固定。
2. **只读已提交的记录。** JSONL 末尾的不完整行（撕裂的追加）会被静默忽略，
   而位于没有对应 commit 的 `epoch_transaction_prepare` 之后的转换事件永远
   不会被采纳进当前状态 —— 这是 `ari.rqgm.store.committed_events` 的镜像。
   「对应」以 `transaction_id` 判定：携带不同事务 id 的 commit（或中间事件）
   既不会关闭也不会并入待定事务。
3. **降级，而非损坏。** 断裂的哈希链或过期的 rollup 会翻转某个完整性标志并
   追加 `degraded_reasons`；损坏的工件会得到带诚实标志的 HTTP 200，而不是
   500。缺失的来源是 `None`，绝不会被展示为干净或零。
4. **只读。** 没有任何东西写文件、触碰 `viz.state` 或修改 `os.environ`，
   而且**不存在变更端点** —— GUI 无法执行治理动作，只能观察它们。
5. **没有为 GUI 新增任何运行时埋点。** 这些读模型所需的每一个逻辑事件，都早已
   以已提交记录的形式存在 —— 策略提案是 `UtilityPolicyCandidate`，策略采纳是
   一次 T20 转换，得分观测是一条 `UtilityRecord`，得分改写是
   `SelectiveErasureEvent` 加 `FrontierRebuildEvent`，注册表变更是
   `rqgm_transitions.jsonl` 中一条已提交的转换事件 —— 因此读取器是对 run 本来
   就会写出的工件的纯投影，没有为它引入任何新的事件类型。

**已知缺口 —— 不存在实时的治理进度。** 九步纪元审计在运行期间不发出任何东西：
流水线只是把记录**返回**出来，而编排器把它们全部追加进日志 —— 证据包、弹劾动议、
辩护、裁决，最后才是 `governance_report` —— 是在整个审计返回之后才发生的。因此
进行中的边界是不可见的，而不是被部分渲染出来。既没有阶段进度的事件类型，也没有
重算开始的信号；一次重算只能通过它留下的记录才变得可见。治理工作区同样只订阅
`run` 这一个主题，而 `run` 是在检查点切换时以及一次 v1 启动之后发布的 —— 纪元
边界本身不会推送任何失效通知。请把每一个治理载荷都当作「你发起请求那一刻已提交
内容的快照」，要推进就重新拉取。主题词汇表是冻结的，见
[REST API 参考](rest_api.md)的「实时：`GET /api/v1/events/stream`（SSE）」一节。

**已知缺口 —— 不做 schema 校验。** 读取器从不加载 `ari/schemas/` 下的 JSON
Schema。它防御式地逐字段读取：类型符合预期就保留该值，否则给出 `None`。因此一条
能作为 JSON 解析、但违反其 schema 的记录会在可读字段的范围内被投影出来，而不是
被拒绝 —— 这正是让旧检查点还能渲染出来的同一种宽容。该模块确实会拒绝的东西列在
下面「完整性标志与降级语义」一节中（链与哈希校验、闭合的 status 词汇表、
一次性写入的策略正文校验），而 schema 合规并不在其中。

## 能力门控

`GET .../rqgm/capabilities` 是唯一一个会为非 RQGM run 作答的 RQGM 端点。
能力检测完全依据工件存在性，别无其他：

| 信号 | 推导自 |
|---|---|
| `enabled` | `{ckpt}/rqgm_state.json` 存在**且**记录了 `rqgm_enabled`（默认取 `mode == "ari_rqgm"`）。文件不存在 ⇒ `enabled: false`，理由为 `"simple_bfts run"`。 |
| `mode` / `mode_source` | `rqgm_state.json` 中持久化的 `mode` 及其溯源。 |
| `paper_mode` | `{ckpt}/paper_archive_state.json` 是否存在。执行模式与论文模式是**独立的两个轴**：四种组合都有效。 |
| `reasons` | 该能力为何关闭 / 不可读 —— 绝不返回空洞的成功断言。 |

`reasons` 是自由文本，而不是一套分类法。该端点只会给出三种字符串之一 —— 这是一次
`simple_bfts` run、`rqgm_state.json` 不可读、或该文件记录了一个 `rqgm_enabled`
为 false 的模式 —— 并且没有可供程序分支的机器可读理由码。**已知缺口：**
`enabled: false` 从不区分「治理被配置为关闭」「治理预算已耗尽」与「该检查点早于
这项功能」。唯一的信号是工件是否存在，因此这三者都读作「缺失」；需要把它们区分
开的客户端必须去看 run 自身的配置。

对于没有 `rqgm_state.json` 的 run，其余十一个端点返回类型化的
`404 not_found` 信封（消息为「not an RQGM run … simple_bfts run」），这与
未知 run id 的 `404` 是不同的。

## 工件 → 端点映射

关键区分是**真相日志 vs 快照**：追加写入、哈希成链的日志才是事实来源，而
rollup / 快照文件只被读取*用于校验*它 —— 绝不会成为当前状态。

| 端点 | 真相来源（状态来自这里） | 快照（仅用于校验 / 溯源） |
|---|---|---|
| `…/capabilities` | — | `rqgm_state.json`、`paper_archive_state.json`（存在性 + 持久化模式） |
| `…/overview` | `rqgm_transitions.jsonl`（已提交重放）、`rqgm_audit.jsonl`（链） | `rqgm_registry.json`（rollup 校验）、`epoch_state.json`（交叉校验）、`meta.json`（`constitution_hash`） |
| `…/registry` | `rqgm_transitions.jsonl` 重放 | `rqgm_registry.json`（仅做 `as_of_event_hash` 比较） |
| `…/transitions` | `rqgm_transitions.jsonl` | — |
| `…/audit` | `rqgm_audit.jsonl` | — |
| `…/policies` | `rqgm_transitions.jsonl` 重放（`utility_policy` 角色的提示词） | 由该提示词 `source.path` 引用的已注册策略正文文件（提供前会做哈希校验） |
| `…/score-rewrites` | `rqgm_transitions.jsonl`（T20 取代）与 `rqgm_audit.jsonl`（`SelectiveErasureEvent` / `FrontierRebuildEvent`）的连接结果 | — |
| `…/nodes/{node_id}/lineage` | `rqgm_adversarial_cases.jsonl`、`rqgm_audit.jsonl`，以及通过树视图取得的节点 `metrics` 哨兵字段 | — |
| `…/epochs`、`…/epochs/{epoch_id}` | `rqgm_transitions.jsonl`（`epoch_open` 载荷 + 关闭边界条目）、`rqgm_audit.jsonl`（用于 `fallbacks` 的 `epoch_transition` 记录） | `epoch_state.json` **不**被用作状态 |
| `…/evolution` | `prompt_evolution.jsonl`、`rqgm_meta_outputs.jsonl`，外加用于采纳连接的注册表重放 | — |
| `…/paper-archive` | `paper_draft_archive.jsonl`、`paper_anchor_corpus.jsonl`、`rqgm/paper_self_preference_stat.json`、`full_paper.tex`（存在性） | `paper_archive_state.json`（持久化模式 + 冻结的论文策略） |

有三个后果值得内化：

- `rqgm_registry.json` 是一份 **rollup**，而不是注册表本身。`…/registry`
  通过重放已提交转换来重建组件与提示词，并且只通过 `verified` /
  `rollup_as_of_event_hash` / `replay_tail_event_hash` 报告该 rollup。
- `epoch_state.json` 永远不设置 `current_epoch`。`…/overview` 从最后一条
  已提交的 `epoch_open` 推导当前纪元；如果快照与之不符，就追加一条降级理由
  （「snapshot ahead of the truth log」）。
- **有若干治理工件完全没有读模型** —— 这是一个已知缺口。
  `proposals/proposal_records.jsonl` 与 `proposals/proposal_index.json`、
  `rqgm_cleanroom.jsonl`、`rqgm_erasure_state.json`、
  `rqgm_governance_cache.jsonl`、`rqgm/adversarial_replay_pool.json` 以及
  `prompt_specs.json`，在这个接口面上没有任何端点会打开它们；`rqgm_prompts/`
  也只是被间接触及 —— 通过某个已注册 `utility_policy` 提示词所指明的
  `source.path`，而且仅限该角色。因此提案路由、洁净室再生成、擦除台账、治理缓存
  与重放池至今仍要手工从磁盘读取；它们的格式见
  [文件格式参考](file_formats.md)的「RQGM 纪元治理文件（可选启用的
  `ari_rqgm` 模式）」一节。检查点里的 `constitution.yaml` 副本同样不被读取，但
  那一个是设计使然而非缺口：它是一个没有任何 ARI 代码会回读的溯源标记，而
  `…/overview` 报告的是来自 `meta.json` 的 `constitution_hash`。

## 完整性标志与降级语义

`…/overview` 携带三个**三态**标志；`…/transitions` 与 `…/audit` 会把其中
相关的那个作为 `chain_ok` 重复给出：

| 标志 | `true` | `false` | `null` |
|---|---|---|---|
| `transitions_chain_ok` | `rqgm_transitions.jsonl` 的每一行都校验通过：`event_hash` 覆盖该行声明的事件信封（只有旧的 schema-v1 行才只覆盖载荷），且 `prev_event_hash` 成链（首行从 `""` 开始）。 | 发现了哈希不匹配或链断裂；扫描仍继续，因此数据照常提供，但被打上标志。 | 文件不存在。 |
| `registry_verified` | `rqgm_registry.json` 的 `as_of_event_hash` 等于已提交转换的尾部。 | rollup 过期，或超前于日志。 | rollup 缺失/不可读，或没有可供比较的转换尾部。 |
| `audit_chain_ok` | `rqgm_audit.jsonl` 作为一条独立的链校验通过。 | 发现断裂。 | 文件不存在。 |

`null` 是一等答案：**缺失的来源绝不会被渲染成干净。** 与这些标志并列的
`degraded_reasons` 是一个有界的人类可读字符串列表（每个来源至多三条），会
指明出问题的事件 id 与字节偏移，例如
`"rqgm_transitions.jsonl: hash chain broken at evt_000117 (byte 40213)"`。
读取器还会在不让请求失败的前提下发出其他理由：无法解析但已终止的 JSONL 行
（跳过）、超出闭合注册表词汇表的状态值（该条目被排除在列表与计数之外）、
字节内容已不再哈希到其注册 `prompt_hash` 的策略正文（`body: null` ——
拒绝提供，绝不静默提供），以及 `meta.json` 中不含 `constitution_hash`。

## 两套词汇表，两台状态机

注册表生命周期状态与节点得分状态是**不同的状态机，绝不能混在同一个字段或
同一个图例中**。DTO 在结构上强制了这一点：两个字面量类型是不同的，因此任何
载荷都无法在应放注册表状态的位置携带节点得分状态。

**注册表组件 / 提示词生命周期 —— 10 个取值**（逐字照搬
`ari.rqgm.events.STATUS_VALUES`，这是一份冻结契约）：

| 状态 | 在读模型中的含义 |
|---|---|
| `candidate` | 已注册，尚未验证。 |
| `validated` | 已通过验证，尚未上线。 |
| `shadow` | 与活跃组件并行运行以作比较。 |
| `probationary_active` | 在察看期内上线。计入**活跃**。 |
| `active` | 已上线。计入**活跃**。 |
| `warning` | 制裁姿态。 |
| `probation` | 制裁姿态。 |
| `quarantine` | 制裁姿态（也是 `emergency_quarantine` 的目标）。 |
| `retired` | 已退出服务。 |
| `banned` | 被永久禁止。 |

`active` 与 `probationary_active` 构成 `active_components` /
`active_prompt_hashes` 所使用的冻结活跃集合（角色 → id/hash，在确定性重放
顺序下最新注册者胜出）。

**节点得分状态 —— 5 个取值**（`NodeScoreStateV1`）：

| 状态 | 该断言的来源 |
|---|---|
| `computed` | 该节点存在一条 `UtilityRecord`，或节点 metrics 中没有陈旧化哨兵字段。 |
| `recomputed` | 一条带 `recomputed_in_epoch` 的 `UtilityRecord`，或该节点出现在某个擦除事件的 `recompute_node_ids` 中。 |
| `stale` | 节点 metrics 带有 `_stale` 但没有失效理由。 |
| `invalidated` | `_stale_reason == "utility_invalidated"`，或该节点被列在某个 `SelectiveErasureEvent` 的 `invalidated_node_ids` 中。 |
| `removed` | 保留给从前沿中被逻辑移除的情形。当前读取器**不会**断言它：点名该节点的 `FrontierRebuildEvent` 会作为事实报告在 `values` 中（`frontier_removed` / `frontier_reinstated` / `recomputed_utility`），而 `state: null`，因为一个前沿事件并不是一个得分状态断言。 |

`stale` / `invalidated` / `removed` 都是**逻辑**状态：它们中没有任何一个意味
着该节点被物理删除，而「Deleted」对它们中的任何一个都不是有效标签。物理删除
是另一个独立的状态，这些载荷并不描述它。

## 两条得分改写通道

一个节点的得分可能因两种结构上完全不同的原因而变化。API 把它们保存在
**任何消费者都无法意外合并成同一条序列的独立列表**中
（`…/nodes/{node_id}/lineage` 并排返回 `penalty_channel` 与
`policy_channel`）。

两条通道都只报告源记录本身已经持有的内容，不多一分。`RqgmScoreObservationV1`
携带的是 `source`、`record_id`、`epoch_id`、`policy_hash`、`state`、
`validated_attack_ids`，以及一个把源字段逐字透传（哨兵键名也照搬）的 `values`
映射 —— 而不是一个带类型的 base/penalty/final 三元组。由此引出三个已知缺口，
期待看到排行榜的读者应当先知道它们：

- **没有名次。** 没有任何 RQGM 载荷携带节点的名次、名次变动或任何前后排序，也没
  有任何端点接受排序或比较参数（这个接口面的全部查询词汇就是 `cursor`、`limit`、
  `expand`、`record_type` 与 `epoch`）。排序留给调用方 —— 而跨策略哈希去排序，会
  破坏本页其余部分所强制的分面规则。
- **没有计算版本。** 策略身份只有 `policy_hash` 一项。读模型没有「打分代码版本」
  这个独立概念，因此无法把一次观测归属到产生它的那一次具体构建。
- **两条通道都不给自己的行加时间戳。** `RqgmScoreObservationV1` 与
  `RqgmScoreRewriteV1` 都没有时间字段，因此观测与改写是按它们在源日志中的位置
  排序的，而不是按记录下来的时刻 —— 尽管磁盘上的 `UtilityRecord` 是带
  `created_at` 的。这个接口面确实报告的时钟在别处：`…/transitions` 条目上的
  `committed_at`（该事务最后一行的 `ts_iso`）、`…/audit` 条目上的 `ts_iso`，
  以及 `…/overview` 上的 `last_committed_transition_at`。

### 通道 1 —— 对抗惩罚（纪元内部、节点作用域）

| 方面 | 详情 |
|---|---|
| 证据 | `rqgm_adversarial_cases.jsonl` 中的 `UtilityRecord`（`utl_*`）行，加上该节点的 `_pre_penalty_score` / `_validated_attack_penalty` metric 哨兵字段。 |
| 呈现的值 | `base_score`、`penalty`、`final_score`、`supersedes`、`recomputed_in_epoch` —— 逐字透传，绝不重新计算。 |
| 归因 | 来自该记录 `input_refs` 的 `validated_attack_ids`。 |
| 作用域 | 一个纪元内部，针对一个节点。 |

**一个字段名，两套策略。** 在这个格式的历史上，`utility_policy_hash` 先后指过两
样不同的东西：对抗引擎冻结的**惩罚**策略（`penalty_cap`、`severity_weights`、
`verdict_factors`），以及边界所采纳的**纪元**策略（`composite`、`axis_weights`、
`frontier_score`、`depth_penalty_lambda`、`ucb_c`）。两者的键集合互不相交，因此
它们的哈希永远不可能相等。在受治理的效用演化落地之后写下的记录携带纪元策略的
哈希；更早的记录携带惩罚策略的哈希。

**把两者归一化是一个已知缺口** —— 读取器并不归一化。一条 `utility_record` 观测
的 `policy_hash` 就是该记录 `utility_policy_hash` 的原样，而一条 `node_metrics`
观测的 `policy_hash` 来自节点的 `_utility_policy_hash` 哨兵字段，那个始终是纪元
策略。对旧检查点而言，这个后果值得直白说出来：一个旧的惩罚侧哈希会自成一个分面，
其取值是任何纪元都不曾用过、也不会出现在任何 `…/policies` 或 `…/epochs` 行里的。
那既不是数据错误，也不是这次运行采纳过的策略；它只是同一个字段名的旧含义。见
[RQGM Schema 参考](rqgm_schemas.md)的「`rqgm_utility_record.schema.json`」一节。

原始攻击与已验证惩罚的区分由类型而非约定强制：一条原始对抗断言（`atk_*`）
只能被表示为 `RqgmRawAttackV1`，而该类型**根本没有得分、惩罚或置信度字段**
—— 它的 `severity_claimed` 是攻击者的断言。只有经过裁决的
`validated_attack`（`vat_*`）才可以驱动惩罚，且只能通过一条引用其 id 的
`UtilityRecord`。因此，攻击数为零的运行会被报告为一种能力状态，绝不会被当作
健康的证据。

### 通道 2 —— 纪元效用策略改写（边界、全运行范围）

| 方面 | 详情 |
|---|---|
| 触发 | 一次已提交的 T20 转换，退役一个 `utility_policy` 角色的提示词并采纳另一个 —— 即 `utility_policy_hash` 在纪元边界处发生变化。 |
| 后果 | 审计日志中的 `SelectiveErasureEvent`（`erase_*`）与 `FrontierRebuildEvent`（`rebuild_*`）记录。 |
| 节点集合 | `invalidated_node_ids`、`recompute_node_ids`、`frontier_removed_node_ids`、`frontier_reinstated_node_ids` —— **从真实事件字段复制而来，读取器绝不重新计算**。 |
| 节点侧证据 | `_utility_policy_hash`、`_scientific_score`、`_stale`、`_stale_reason`、`_valid_for_frontier`、`_erasure_event_id` 这些 metric 哨兵字段。 |

`…/score-rewrites` 是该通道的运行级视图：每个条目把取代转换
（`from_policy_hash` → `to_policy_hash`）与其擦除/重建后果连接起来，并列出
它用到的每一个 `source_event_ids`。这个连接中内建的诚实性规则：

- 一次**无法**连接到采纳转换的擦除或重建，仍然会作为它自己的条目出现 ——
  没有对应转换的改写会被如实展示，绝不隐藏；
- 当某个边界退役或采纳了不止一个 `utility_policy` 提示词时，
  `from_policy_hash` / `to_policy_hash` 保持为 `null` 并给出一条降级理由，
  而不是去猜哪一个才是「那个」策略；
- 分页游标是指向确定性合并后列表的整数下标（先按转换顺序，再按文件顺序排列
  未连接的审计事件）—— 不是字节偏移，因为该列表是跨两个日志的连接结果。

## API 强制执行的呈现真实性规则

这些规则实现在读取器与 DTO 中，因此一个只是把载荷渲染出来的客户端不可能
违反它们。

| 规则 | 如何被强制 |
|---|---|
| 得分绝不脱离其策略身份单独展示。 | 每个 `RqgmScoreObservationV1` 都携带 `policy_hash`；每个纪元行都携带自己的 `utility_policy_hash`，因此不同 hash 下的得分绝不会成为一条连续序列。 |
| 原始攻击绝不携带得分。 | `RqgmRawAttackV1` 没有任何数值字段 —— 类型使之不可能。 |
| 治理状态 ≠ 研究状态。 | RQGM 载荷只描述治理；run/研究状态位于 `…/summary`。 |
| 开放中的纪元不等于零活动。 | 对仍处于开放状态的最新纪元，`transition_counts` 为 `None`；当没有 `epoch_transition` 审计记录携带该数组时，`fallbacks` 为 `None`。 |
| 采纳是一次连接，绝不是自我宣称。 | 在 `…/evolution` 中，`adopted` 只能通过把候选提出的 hash 与在已提交重放中进入活跃集合的同角色提示词相匹配而推导出来，并由 `adopted_via` 引用那次转换。元智能体输出是惰性溯源：它们的 `adopted` 为 `None`。 |
| 验证证据 ≠ 采纳。 | `validation_record_count` / `validation_passed_count` 统计 `prompt_candidate_validation` 记录，并与 `adopted` 分开报告。 |
| 只有字节仍能正确哈希的策略正文才会被提供。 | 当存储的文件不再与注册的 `prompt_hash` 匹配时，`…/policies` 返回 `body: null` 加一条降级理由（这是一次性写入规则在存储侧的体现）。 |
| 论文的胜出者是一次经过评审的选择。 | `…/paper-archive` 在 `winner` 下报告 `is_best_belief` 草稿，它既不是治理胜出者也不是研究结果；`materialized` 表示 `full_paper.tex` 是否存在。 |
| 缺失就报告为缺失。 | 每个可选来源都伴随存在性标志（`evolution_present`、`meta_outputs_present`、`state_present`、`archive_present`、`stat_present`、`corpus_present`），并且在工件缺失时计数保持为 `None` —— 绝不是 `0`。当没有冻结任何论文策略时，锚点的 `enabled` 为 `None`。 |
| 载荷保持有界。 | overview 不内嵌任何列表；审计条目把数组概括为 `<key>_count` 并截断过长字符串，原始载荷仅在 `?expand=1` 时可得；转换条目携带计数，原始事件同样仅在 `?expand=1` 时提供。唯一的例外是 `…/score-rewrites` 条目内部的节点 id 数组 —— 见下面的「分页」一节。 |

## 分页

`…/transitions` 与 `…/audit` 使用指向其 JSONL 源文件的字节偏移游标，带有
无空洞/无重复保证并且只读已提交内容；`…/score-rewrites` 使用下标游标。
这两个日志分页上的 `source_revision` 是源文件已解析的字节长度（不含撕裂的
尾部）。共享的游标契约只在
[REST API → 游标约定](rest_api.md#游标约定)记录一次。

有一处边界是缺失的，而它是这个接口面上唯一无界的载荷。一个 `…/score-rewrites`
条目会把 `invalidated_node_ids`、`recompute_node_ids`、
`frontier_removed_node_ids` 与 `frontier_reinstated_node_ids` 从事件字段整份复制
进来并完整内嵌；`invalidated_node_count` 是额外添上的便利项，而不是这些列表的
替代。`limit` 限制的是每页的条目数，而不是单个条目内的节点 id 数，因此一次让树
中很大一部分失效的边界会产出一个很大的条目。用于单独分页这些 id 的、按改写维度
的关联端点是一个**已知缺口** —— 需要它的客户端只能自己分页条目并处理这些数组。

## 另请参阅

- [RQGM Schema 参考](rqgm_schemas.md) —— 记录形状、id 格式、哈希纪律，以及
  检查点文件清单。
- [文件格式参考](file_formats.md) —— 这些读模型所解析的检查点文件。
- [REST API 参考](rest_api.md) —— 传输契约。
- [执行模式](../guides/execution_modes.md) —— 一次运行究竟何时才算是 RQGM
  运行。
