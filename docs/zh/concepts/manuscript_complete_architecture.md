---
sources:
  - path: ari-core/ari/manuscript
    role: implementation
  - path: ari-core/ari/core.py
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
  - path: ari-core/ari/cli/paper_dispatch.py
    role: implementation
  - path: ari-core/ari/cli/manuscript.py
    role: implementation
  - path: ari-core/ari/cli/manuscript_repair_runtime.py
    role: implementation
  - path: ari-core/ari/cli/run.py
    role: implementation
  - path: ari-core/ari/cli/projects.py
    role: implementation
  - path: ari-core/ari/rqgm/paper_runtime.py
    role: implementation
  - path: ari-core/ari/rqgm/paper_archive.py
    role: implementation
  - path: ari-core/ari/rqgm/runtime.py
    role: implementation
  - path: ari-core/ari/rqgm/adversarial/round.py
    role: implementation
  - path: ari-core/ari/science_data_contract.py
    role: schema
  - path: ari-core/ari/viz/v1/openapi.json
    role: schema
  - path: docs/reference/rest_api.md
    role: doc
  - path: docs/concepts/gui_architecture.md
    role: doc
last_verified: 2026-08-09
---

# Manuscript Complete 架构

Manuscript Complete 是研究探索与论文撰写之间那道固定的边界。它并不意味着每一个
可能的事实都已知晓，而是意味着：在 writer 收到输入之前，所选 profile 中的每一条
requirement 都已具备明确的 status、理由、证据引用与修复姿态。

```text
simple BFTS or ARI-RQGM
        │
        ▼
evidence segment ── provenance / ScienceData / retrieval / EAR / figures / KCA
        │
        ▼
fixed compiler ── snapshot → context + omissions → readiness → section briefs
        │                         │
        │ ready                   └─ gap → bounded repair → research runtime
        ▼
linear writer or RQGM archive
        │
        ▼
verification segment
        │
        ▼
readiness ∧ claim gate ∧ assurance ∧ compile ∧ reproduction ∧ freshness
        │
        ▼
PublicationDecisionV1 → PublicationLockV1 or an explicit block
```

三个彼此独立的轴是 `ari.mode`（`simple_bfts|ari_rqgm`）、`paper.mode`
（`linear|rqgm_archive`）与 `manuscript.mode`（`off|audit|enforce`）。没有任何一个轴
会启用另一个。四种研究／论文拓扑全部消费同一套 context 契约与 readiness 契约。

## 权限分层

- 编译器拥有 inventory、适用性、evidence lane、omission 与 readiness。这些是确定性
  事实，而不是模型的判断。
- writer 与 reviewer 只拥有对正文的注记。它们既不能改变一条 requirement 的 status，
  也不能提升证据。
- RQGM 在启用时治理修复提案的谱系；修复 envelope 固定 requirement ID、变量、
  被允许的改动、预算与 source context。
- KCA 提供 Knowledge lock、Provider binding 以及精确指定 target 的 Harness
  attestation。修复继承这些 identity，绝不提升新的 Provider 或 Harness。
- assurance 的权限止步于事实层之上。`ScienceData` 契约不携带任何 attestation、tier
  或 certification 状态；编译器把 `science_data.json` 当作一件普通的检查点工件清点
  —— 它对其取 digest，但绝不改写。因此 `assurance.mode` 只能让一个节点的测量在
  `publishable` 与 `exploratory` 之间移动，而两者都是可用于主张的事实；降级为
  `contextual_negative` 或 `excluded` 只来自与 mode 无关的信号 —— 执行结果、工件
  溯源、陈旧、测量缺失，或一条已记录的 failed / tampered property 裁定。提高
  assurance mode 所改变的是哪些证据可被一个肯定性主张采纳，而不是哪些测量被记录了
  下来。
- Knowledge 记录与 Capability 记录是溯源，而不是提升。二者都不是 evidence lane 决策
  的输入；该决策只读取节点的执行 status、它是否携带真实测量、它的工件溯源、它在前沿
  上的有效性与类别、它的 property 裁定，以及它的 assurance 与 attestation 状态。因此
  一个没有记录到 Knowledge 覆盖的节点并不是一次失败的测量，只是一次记录到的上下文
  较少的测量。
- 在 `enforce` 之下，缺失 Harness attestation 会使 current-certification 的
  requirement 变为 `unavailable`，而一个已有 attestation 但未认证的候选会使它变为
  `missing`。两者都带有 `assurance_certification` resolver，因此在发布保持被阻塞的
  同时，该 gap 仍然可修复。两者都不是对 legacy 访问的隐式授予。随后的修复 request
  会点名它所需要的 capability 与 Harness identity；manuscript 层只记录这些 identity，
  本身并不授予它们。
- publication evaluator 让各条 hard gate 彼此独立。一个评审得分无法补偿一条失败的
  claim / certification / compile / reproduction / freshness gate。

## Evidence lane 与主题选择

`publishable` 的证据可以支撑肯定性主张。`exploratory` 的证据可以被讨论，但禁止作为
主打论据。`contextual_negative` 的证据必须作为失败、null、放弃或无定论的历史保持
可见，且不能支撑一个肯定性事实。`excluded` 的证据是陈旧的、已擦除的、被篡改的，
或因其他原因不可采纳的。

科学胜者在发布资格被评估之前就已冻结。一个已认证的次优候选会作为可用的替代方案被
报告，但它不会悄悄取代一个未认证的胜者。这样的改变需要一次明确的选择策略决定，
以及一个新的、被绑定的 attempt。

## 工作流与状态

唯一的 `ari-core/config/workflow.yaml` 携带增量式的
`evidence|authoring|verification` 元数据。被选中的运行派生出临时的禁用阶段视图；
不存在第二份 manuscript 工作流。每个 segment 都记录自己的 workflow digest、已解析
阶段、逻辑输入、发生变化的输出、status 与 source attempt。一条 completed 记录只有在
每一个输入与输出 digest 都仍然 fresh 时才可复用。

attempt 由 snapshot 与 profile 的 digest 派生，存放在
`.ari-manuscript/attempts/<attempt-id>/` 之下。状态变更构成一条仅追加、以 digest
相连的转换日志。新的源字节会创建一个新的 attempt；旧 attempt 与被阻塞的草稿为审计
而保留。

## 后端集成

在 `audit` 下，legacy writer 的输入与输出行为仍然具有权威性，同时编译器发出一份
影子 bundle 与一份影子 publication decision。在 `enforce` 下，linear writer 收到的是
渲染好的 section brief，而不是没有边界的 legacy context。RQGM archive 的候选收到
同一份 brief 与 authoring binding；archive 失败时只能回退到那个被绑定的 linear
writer。两个后端都不会收到 research executor。

不存在共享的后端接口对象。两个后端消费同一份 authoring binding 与 section brief
bundle，但走的是彼此分开的调用路径：linear authoring 运行工作流的 `authoring`
segment，而 archive 运行 `PaperArchiveRuntime.run_archive`，后者把 linear 流水线
作为一个显式的 fallback callable 接收。一个公共的 `PaperBackend` 类型 —— 即一个
`generate` 入口，在单条记录中返回后端、mode、输入 digest、候选与胜者谱系、草稿工件
digest、模型用量与成本，以及 hard-disqualification 理由 —— 属于保留设计，尚未实现。
archive 实际的结果面是 `paper_archive_state.json` 上的 `manuscript_authoring`：
status、被绑定的 manuscript 输入及其 fingerprint、`stale_reasons`、`failure_reason`、
`winner_id` 与 `winner_tex_sha256`。模型用量与成本不在其中；每个纪元的 expansion、
adversary、anchor 评分、prompt candidate 与 compile 计数被单独镜像到同一文件的
`budget_counters`。一次 fallback 在 enforce 下是否可被接受，由设置在 fallback
callable 自身上的 `_ari_manuscript_bound` 属性承载，而不是由某个接口承载。

在一次 RQGM archive 启动或恢复之前，它会校验精确的 attempt 本地 profile、snapshot、
omission、context、readiness、brief 与 binding 链。一份规范的 archive 输入
fingerprint 还额外覆盖每一个 section brief digest、allowed / contextual-negative /
forbidden evidence ID、必需披露与 omission 数量。该 fingerprint 保存在
`paper_archive_state.json`、每一条草稿记录，以及受治理 reviewer 的评审记录上。
已进化的 writer 或 reviewer 提示词哈希仍是彼此独立的 identity：提示词进化无法改变
那个固定的 manuscript 块。

在 enforce 模式下，每个候选在 best-belief 选择之前都会经过一次只读的初步 claim
gate、工件／溯源检查、contextual-negative / forbidden evidence ID 检查以及强制披露
检查。每个候选还会针对那份被冻结的 bundle 本身重新受检，而不只是就内容受检：它在
该节点与该纪元上的草稿记录，必须携带该 bundle 自己的输入 fingerprint，连同它的
binding、profile、context、readiness 与 brief-bundle digest；在 `enforce` 下，该记录
还必须被标记为 manuscript-bound。一个在当前纪元没有匹配草稿记录的候选，同样以相同
方式过不了这些检查。这种不匹配本身就是一条 hard 理由，因此一份在较早 bundle 下写成
的草稿，即使正文干净，也无法在较晚的 bundle 下胜出。一个 hard 失败的候选仍留在
archive 历史中，但带有 `_valid_for_frontier=false`；reviewer 效用无法补偿它。最终的
publication evaluator 会针对 linear 与 archive 两种 authoring 的精确最终 TeX 重复
一遍 evidence lane 与披露检查，因此候选筛查从来不是唯一的联锁。audit 模式记录同样的
诊断，但不改变 authoring 资格，并把结果标注为 legacy authoring。一次未发生变化的
恢复会复用已绑定的记录，而一个发生变化的 fingerprint 会在进入胜者跳过路径或新的
模型调用之前被检出。若 archive 生成在 enforce 下失败，只有被明确标记为消费同一份
binding 的 fallback 才被允许。

manuscript binding 不会为 archive 选择贡献任何加性的 utility 项。一个候选的
manuscript 评估写下的是诊断，以及在 `enforce` 下那个不可补偿的
`_valid_for_frontier=false` 哨兵；草稿的 `_scientific_score` 仍是 archive 的
reviewer 给它的分数，manuscript 这一趟绝不改写它。分级的 manuscript 轴 —— 必需
section 条目覆盖、claim–evidence 链接覆盖、相对已记录参考文献的引用适当性，以及以
分数而非 pass/fail 表达的披露完整性 —— 属于保留设计，尚未实现；而且 brief 也不携带
为它们评分所需要的东西：它的 evidence lane 绑定的是 evidence ID 而不是参考文献，
参考文献只作为普通的 `related-work` 内容条目抵达 writer，brief 中也没有任何结构把
某一条具体主张与支撑它的证据或参考文献连起来。真正存在的是三值且不可补偿的判定：
一个候选要么是 `admissible`，要么携带 `audit_findings`，要么在 `enforce` 下是
`hard_disqualified`。

archive 的发现留在 archive 内部。它们被持久化在草稿记录与 archive 状态上，而
archive 之外没有任何东西读取它们：不存在有类型的 `paper_diagnostic` 记录，不存在把
一条撰写期发现映射到某个 requirement ID 的 validator，也不存在从一条 archive 发现
通往修复 request 的路径。一份修复 plan 只从 status 为 `missing` 或 `unavailable`
且点名了某个 resolver 种类的 readiness requirement 行派生，而每个 request 都被绑定
到它所回答的那些 requirement ID。通过一个固定 validator 把符合条件的 archive 诊断
准入到后续修复轮次，属于保留设计而非当前行为；必须治理它的那条规则也一样：任何从
诊断到修复的映射，都必须把出问题的草稿、构建、主张与证据 digest 绑定到它所提出的
request 上，并且必须针对同一个 gap 的 readiness 与 pre-flight 信号做去重。两半都
没有实现。`ResearchRepairRequestV1` 声明了 `target_claim_ids` 与 `target_node_ids`，
但唯一的生产者把两者都留空，除了契约自身的重复 identity validator 之外没有任何
东西读取它们；草稿记录确实携带的那些 digest —— 它的 TeX 哈希、它的初步 claim gate
报告 digest，以及它写作时所依据的 manuscript 输入、binding、profile、context、
readiness 与 brief-bundle digest —— 是针对那一个候选的筛查证据，不为任何 request
充当键。正文质量方面的发现根本没有离开 archive 的路径：这条边界在今天是靠构造成立
的，而不是靠某项检查。

### RQGM paper-candidate pre-flight

在 `ari.mode: ari_rqgm` 之下，共享的 paper dispatch 会*先*运行 RQGM 的
paper-candidate pre-flight，然后才解析 manuscript 轴或编译任何东西。该轮次中一次经
judge 校验的攻击会施加有界的 utility 惩罚，它就地改写该节点的 `_scientific_score`；
而探索 snapshot 在给候选排序并确定 `scientific_winner_id` 时读取的正是这个键。因此
pre-flight 处的一次降级可以移动 manuscript 的科学胜者，而这正是意图所在：论文所讲述
的主题，应当是最后一轮治理之后的胜者，而不是之前的。

该轮次攻击的是论文自己的工件，因此它以其中至少已有一件存在为门控条件。当一件都没有
时，pre-flight 推迟执行，dispatch 会在 linear 与 archive 两条分支上于论文阶段之后
重新调用它一次，并加以守卫，使其在一次 dispatch 中绝不运行两次。那次较晚的轮次运行
在流水线结束之后 —— 当 manuscript 轴开启时，也在本次 attempt 的 snapshot、readiness
报告、brief 与 verification 之后 —— 而其后没有任何东西会重建 snapshot，因此它的惩罚
是在下一次调用时通过 replay 抵达选择，而不是在产生它的那次运行中抵达。

在这道接缝上，全部的分工就是顺序。requirement 的 status 只由 readiness evaluator
赋予，而它是 requirement profile、已编译 context 与 omission 清单的纯函数；它绝不
读取对抗案例日志。升级轮次只改变内存中的节点，而 snapshot 清点的是一份已知检查点
工件的固定清单，其中不含任何治理日志，因此 pre-flight 通往 manuscript 编译器的唯一
通道，就是 snapshot 所读取的节点得分。因此一次流水线之后的轮次无法把一条已经记录为
`missing` 或 `unavailable` 的 requirement 变成 `satisfied`。

阻止重复施加的是记录 identity，而不是某个 bundle digest。每一次惩罚都是对抗案例日志
中的一行 `utility_record`，按值携带它的 base、penalty 与 final 得分。重新加载时，
一条记录只有在该节点当前得分仍等于该记录所存 base 得分时才会被重放到节点上；已经
处于 final 值的得分，或此后被重算、重评过的得分，会被原样保留；而被后一条记录的
`supersedes` 点名的记录绝不会被再次施加，因此一次为节点开脱的前沿修复不会被撤销。
轮次标记按节点、按轮次种类各只一次，因此 paper-candidate 轮次对某个给定节点在所有
调用中至多运行一次。每一步都是 fail-open：失败只记日志，绝不阻塞论文流水线。

pre-flight 坐落在探索这条轴上。`manuscript.mode: off` 移除 manuscript 编译与
readiness gate，但不移除 pre-flight；而且 `manuscript.mode` 的任何取值都不改变该
轮次是否触发。

## 自动修复轮次

自动研究修复只存在于 `ari run` 与 `ari resume` 中，且仅当 `manuscript.mode` 为
`enforce` 且 `manuscript.repair.policy` 为 `auto` 时。只有这两个入口会构建 research
executor 并把它们交给 paper dispatch，因此 `ari paper` 能报告一份修复 plan，却无法
启动实验。修复至多创建被准入的那些节点，使用正常的 BFTS/RQGM 执行循环，并运行正常的
RQGM/KCA 钩子。

在该姿态下，论文阶段会在 evidence segment 与第一次 authoring 调用之间运行一个有界的
外层循环。一轮是：

```text
evidence segment
        │
        ▼
compile ── context / omissions / readiness
        │
        ├─ authoring-ready ────────► leave the loop and author
        ├─ no admitted request ────► stop, blocked
        ▼
admit the ordered plan → execute each admitted request once
        │
        ▼
commit the round record → rebuild evidence → recompile as the next round
```

轮次从零开始编号，且必须保持连续。轮次预算限定的是该检查点总共提交多少轮，按已持久
化的轮次记录计数，而不是按调用或按 attempt 计数。这些记录存放在唯一一个不带 attempt
成分的 `.ari-manuscript/auto-rounds/` 目录中，守卫会把其中的每一条记录与上限比较；
由于 attempt ID 由 snapshot 与 profile 的 digest 派生，而每一轮都会重建证据从而移动
snapshot，同一个循环的相继轮次可以属于不同的 attempt，却仍在消耗同一个计数器。

该循环绝不会赶在 readiness 之前撰写。linear 与 archive 两个后端都会在任何 authoring
模型调用之前运行 evidence segment、编译并进入循环。若循环返回未就绪，该阶段会抛出
一次 authoring 阻塞而不是写出草稿；在 archive 分支上，它会在状态转入 `authoring`
之前抛出。audit 模式绝不进入该循环。

request 按 resolver 种类分组，并按固定的 resolver 优先级排序 —— 派生式重建与
retrieval 先于新实验，人类决定排在最后 —— 因此同样的 readiness 总是产出同样的 plan。
执行不断言任何科学内容。协调器不做任何测量，也没有任何 executor 结果能关闭一条
requirement：一条 requirement 之所以关闭，只因为重建后的证据与重新编译后的 readiness
这样说。

每个 request 在它的 resolver 一返回就提交一笔不可变事务，而轮次记录在整份 plan 跑完
之后、证据重建之前提交。因此一次中断带来的是重放而不是重做：一个已被记录的 request
会以零额外预算开销从它的事务中复用，而不是被再次调用；一个已被记录的轮次则直接跳到
重建与重新编译。

自动化可以花预算，但绝不拓宽权限。每个被准入的 request 都会在它的 resolver 运行之前
立即重新受检，检查针对的是当前的 source context digest，以及在该 plan 被准入时捕获
的权限 digest。一个陈旧的 context 或一个已变更的权限，会让该 request 失败，而不是让
它在旧 envelope 下执行。被拿来比较的权限快照是一份工件 identity 与 mode 名称的清单，
带有明确的无凭据标记，因此重新校验它只能确认 envelope 未变；它自身绝不构成一次授予。

一个被准入的实验 request 恰好实体化一个节点。该节点的 identity 由 request digest
派生，而 request ID、requirement ID、source context digest 与被允许的改动都是该节点
自身的字段。它在进入研究循环之前就被写入检查点，因此一次被中断的轮次会恢复到同一个
受谱系绑定的节点上，而不是为同一个 request 再开一个。当 RQGM 启用时，该节点会走过与
一次普通 expansion 相同的两个钩子，并以相同的参数被调用：生产者印戳 —— 在当前纪元
携带这些信息时，把该纪元的组件、提示词哈希与纪元 ID 写到节点上 —— 以及针对
parent → 修复节点这一对的 expansion 提案记录。因此修复是从正门而不是从旁边进入
谱系的。

随后该节点由普通的研究循环执行，在此期间该运行自己的节点上限被保持在当前树规模。
循环只在树小于该上限时才展开，因此修复节点会运行到完成，却无法接着展开出属于它自己
的前沿。该运行原本的上限随后会被恢复，包括循环抛出异常时也会恢复。正是这一点让一轮
修复保持加性：它消耗被准入的预算，并留下一个被绑定的节点，而不是一次新的探索。

停止与阻塞不是一回事。耗尽轮次预算或累计预算，或者完成了一轮既没有改变 context
digest、也没有改变任何 requirement status 的轮次，都会让该 attempt 停在
`repair_pending`。而一份空 plan、一个缺失的 resolver，或一个 `human_required` 结果，
则改为记录 `blocked_unavailable`。这两种转换都只有在从该 attempt 当前状态出发是合法
时才会被写入，因此重复停止不会追加第二次一模一样的跳转。

该循环每次调用至多进入一次，就在 authoring 之前那一个点上。一条在 authoring 期间、
verification 期间或 publication decision 处才首次显现的诊断不会让它被重新进入：在
`enforce` 下，publication evaluator 记录 `finalized` 或 `publication_blocked`，
流水线返回该 decision，此后没有任何东西再调用该循环。循环自身的准入步骤只把
`blocked_unavailable` 提升为 `repair_pending`，绝不提升 `publication_blocked`。因此，
为了进一步修复而离开 `publication_blocked` 是一次操作员行为 —— 显式的
`ari manuscript repair` 是唯一发出该转换的代码路径，它会执行选定的、被准入的
request 并重新编译。相反，重新运行 `ari run` 或 `ari resume` 会重新绑定当前的源
字节，并且只有当那次新的编译再一次不是 authoring-ready 时，才会重新进入自动循环。
从一条 authoring 之后的诊断在同一次调用内返回到一个新的编号轮次、并自动作废草稿，
属于保留设计，尚未实现。

## 读取面

Manuscript Complete 既没有 GUI，也没有 REST 面。已提交的
`ari-core/ari/viz/v1/openapi.json` 没有声明任何 manuscript 端点，
[REST API 参考](../reference/rest_api.md)与[仪表盘架构](gui_architecture.md)也都
没有描述过一个。

操作员实际读取的是 `ari manuscript` 命令组，以及 `.ari-manuscript/` 之下的 attempt
工件。每个子命令都打印 JSON，而其中会做决定的那四个在答案为否时以 `2` 退出：
`status --fail-if-blocked` 在 `repair_required` 或 `blocked` 的 authoring verdict、
或 `blocked` 的 publication verdict 时；`repair` 在它执行完 request 之后的重新编译
仍让任何一个被准入 request 的 requirement 未闭合时；`explain-publication` 在任何非
`publishable` 的 decision 时；`lock-publication` 在 lock 被拒绝时 —— 一个非
publishable 的 decision、一个不再指向当前构建的 decision、一个未 finalize 的
attempt、发生变化的输入、陈旧的 reproduction 证据，或者没有唯一的最终 PDF。正是这条
性质让缺席的查看器无害：任何发布安全性保证都不得依赖某个查看器的存在，因此一个不可
用的仪表盘绝不可能成为一份不安全构建被发布的理由。

一个读模型属于保留设计，尚未实现。若要新增一个，它必须读取同样的
`ari.public.manuscript` 契约，只展示这些契约已经携带的内容 —— requirement 矩阵、
evidence lane、omission、修复预算、attempt 谱系，以及那些彼此独立的 publication
gate —— 并且绝不重算 readiness，也绝不导出属于它自己的 gate verdict。readiness
规则的第二份实现就会是第二个真实来源。

参见[契约](../reference/manuscript_complete_contracts.md)、
[profile 指南](../reference/manuscript_complete_profile.md)与
[操作员运行手册](../guides/manuscript_complete_operations.md)。
