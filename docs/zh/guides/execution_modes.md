---
sources:
  - path: ari-core/ari/rqgm
    role: implementation
  - path: ari-core/ari/rqgm/paper_mode.py
    role: implementation
  - path: ari-core/ari/config/__init__.py
    role: implementation
  - path: ari-core/ari/core.py
    role: implementation
  - path: ari-core/ari/cli/projects.py
    role: implementation
  - path: ari-core/ari/cli/paper_dispatch.py
    role: implementation
  - path: ari-core/ari/config/field_registry.py
    role: implementation
  - path: ari-core/ari/viz/v1/launch.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/ConfigStudio/ExecutionSection.tsx
    role: implementation
  - path: ari-core/tests/test_rqgm_mode.py
    role: test
  - path: ari-core/tests/test_paper_mode.py
    role: test
  - path: ari-core/tests/test_gui_v1_mode_selection.py
    role: test
last_verified: 2026-07-30
---

# 执行模式：`simple_bfts` 与 `ari_rqgm`

ARI 有两种执行模式：

- **`simple_bfts`**（默认）—— 即当前的 ARI，行为不变。当 workflow.yaml 中没有
  `ari:`/`rqgm:` 块时（即所有 RQGM 之前的配置），ARI 不构造任何 RQGM 对象、
  不导入任何 `ari.rqgm` 模块，也不写入任何新的检查点文件。
- **`ari_rqgm`**（可选启用）—— Constitutional ARI-RQGM 的纪元治理与协同
  进化。默认永不启用。没有 `--mode` CLI 标志；启用与否是一项配置决策，
  既可以在 `workflow.yaml` / 环境变量中做出（见下文 —— 这是权威说明），
  也可以**仅针对新建运行**在仪表盘的配置工作室中做出
  （[从 GUI 选择](#从-gui-选择模式)）。

## 启用 RQGM

```yaml
# workflow.yaml
ari:
  mode: ari_rqgm      # master switch (simple_bfts | ari_rqgm)
rqgm:
  enabled: true       # redundant safety interlock
```

两个键必须一致。生效模式由纯函数
`ari.rqgm.mode.resolve_effective_mode` 解析：

| `ari.mode` | `rqgm.enabled` | 生效模式 | 行为 |
|---|---|---|---|
| `simple_bfts` | `false` | `simple_bfts` | 默认；静默 |
| `simple_bfts` | `true` | `simple_bfts` | 警告：设置了联锁但模式为 simple_bfts |
| `ari_rqgm` | `false` | `simple_bfts` | 警告：请求了该模式但联锁未开启 |
| `ari_rqgm` | `true` | `ari_rqgm` | 构造 RQGM 运行时 |

环境变量覆盖（在 profile 之后应用，因此显式的环境变量选择优先）：
`ARI_MODE` ∈ {`simple_bfts`, `ari_rqgm`}，`ARI_RQGM_ENABLED` ∈
{`0`,`1`,`true`,`false`}。无效值会产生警告并被忽略
（validate-before-assign）。

当生效模式为 `ari_rqgm` 时，`ari run` 会在第一个节点运行之前写入
`{checkpoint}/rqgm_state.json`（模式、联锁、`mode_source` ∈
`config|env|resume`、切换日志），并把打包的 `constitution.yaml` 复制到
检查点中（仅复制一次，绝不覆盖，不可进化）。创始注册同样在启动时
运行：在 `epoch_000` 开启之前，创始提示词/组件集合就被提交到
`rqgm_transitions.jsonl`，因此 `rqgm_registry.json` 和
`epoch_state.json` 会在第一个节点完成之前出现（见
[RQGM 运行时演练](../concepts/rqgm_runtime_walkthrough.md)）。
**没有 `rqgm_state.json`
即意味着这是一次纯 `simple_bfts` 运行** —— 默认检查点与 RQGM 之前的
ARI 保持逐字节一致。

`mode_source` 记录的是**启动时模式是怎么定下来的**，而决定它的只有一条
规则：`ari run` 在启动时若进程环境中的 `ARI_MODE` 或 `ARI_RQGM_ENABLED`
被设为非空值就记 `env`，否则记 `config`。这个判断发生在
`export_resolved_config_to_skill_env` 把 `ARI_MODE` `setdefault` 为生效模式
**之前**，因此纯粹通过 YAML 配置的运行绝不会被误标成来自环境变量。关键
在于「是否存在」而不是「谁设置的」：从父进程继承来的值同样算作来自环境
变量；从 Configuration Studio 以非默认模式启动的运行也会记 `env`，因为该
启动路径除了把 `ari:`/`rqgm:` 块合并进检查点的 `workflow.yaml` 之外，还会把
`ARI_MODE`/`ARI_RQGM_ENABLED` 导出到所派生 CLI 的环境中。其他任何字符串
都会在告警后被归一为 `config`。

第三个可接受值 `resume` 是**保留值，从不被写入**。`rqgm_state.json` 只在
运行开始时由 `persist_run_start`（运行时中唯一调用 `write_rqgm_state`
的地方）写入一次，而
`ari resume` 只读取它（`reconcile_resume_mode`）。因此恢复的运行不会带有
`mode_source: resume`；该字段永远描述**最初**那次启动，读者不应期待它会
随恢复而改变。

两个访问器按契约都是非致命的。文件缺失、不可读，或不是一个 JSON 对象时，
`read_rqgm_state` 返回 `None` —— 缺失与损坏一样都被读作「没有 RQGM
状态」，也就是一次 `simple_bfts` 运行。`write_rqgm_state` 会捕获所有异常
并记录告警，因此溯源写入失败只会让记录退化，绝不会把异常抛进运行里。

## 模式切换时机策略

允许：

1. **运行开始时** —— 这是进入 `ari_rqgm` 的唯一入口。生效模式只解析一次，
   并在第一个节点运行前被持久化。
2. **纪元边界**（仅限 `ari_rqgm` 运行内部）—— 设计上预留了在纪元边界事务中
   将 `ari_rqgm → simple_bfts` **降级**的能力（成本 / 紧急回退）。**该能力
   尚未实现。** 系统从不发出降级事件，`rqgm_state.json` 只在运行开始时写入
   一次且此后不再改写，`ConstitutionalKernel.validate_epoch_invariance`
   也完全不检查模式 —— 它只产生 `CK-EPO-001`（`prompt_hash` 位于冻结
   active set 之外的记录）与 `CK-EPO-002`（纪元中途的非紧急 active set
   变更）。因此实际运行中，模式从开始到结束都是固定的；请将该降级视为
   预留设计，而非可用行为。

禁止 / 不可能：

- **运行中途** `simple_bfts → ari_rqgm`：`simple_bfts` 没有纪元边界，
  因此不存在合法的切换点。升级需要开启新的运行（或以
  `ARI_MODE=ari_rqgm` 启动子运行）。
- 在纪元中途、治理事务中途、注册表转换中途或前沿重建中途的任何切换。

恢复规则：`ari resume` 以检查点优先的方式读取 `rqgm_state.json`，且
**持久化的模式优先**于包配置和环境变量。不一致时只产生警告，绝不会在
运行中途翻转模式 —— 运行的模式在整个运行期间不可变（上文的纪元边界降级
属于预留设计，尚未实现）。

所有 RQGM 模式读取方的读取优先级：
`{checkpoint}/rqgm_state.json` → 类型化配置（`--config`/检查点/包
YAML + profile + 环境变量，按标准优先级）→ 默认值。任何 RQGM 代码都
不会直接重读包内的 workflow.yaml。

## VirSci 的独立性

`proposal_router.generators.virsci.enabled`（默认 `false`）与
`ari.mode` 正交：四种组合全部有效，模式解析代码从不读取
`proposal_router.*`，VirSci 门控也从不读取 `ari.mode`。VirSci 关闭时，
两种模式下都不会触碰任何 VirSci 运行时、vendored 路径、提示词或快照
语料库。

最后这条保证仅在 K/C/A 处于**默认**姿态时成立；缺口在那条轴上而不在
这条轴上：只要把 `knowledge.mode`、`capability_binding.mode` 或
`assurance.mode` 中任意一个移离默认值，
`ProposalRouter._typed_contract_required()` 即为 true，路由器便会
（只要存在 MCP 客户端）构造 `VirSciAdapter`，并且无论
`generators.virsci.enabled` 取何值都把 `virsci` 报告为已启用。参见
[VirSci 集成](virsci_integration.md)。

## 论文执行轴：`paper.mode`

论文写作阶段（`ari paper`）拥有自己的执行轴，与 `ari.mode` 完全
**正交**。它由一个独立的纯函数
`ari.rqgm.paper_mode.resolve_paper_mode`（`PaperMode` ∈ {`linear`,
`rqgm_archive`}）解析，只读取 `paper.mode` / `rqgm.paper.enabled`，从不
读取 `ari.mode` / `rqgm.enabled`：

- **`linear`**（默认）—— 即当前的论文流水线，在 `ari.mode: simple_bfts`
  下逐字节一致。三个入口（`ari paper` / `ari run` / `ari resume`）都经由
  共享调度（`ari/cli/paper_dispatch.py:run_paper_phase`），在该轴上调用
  `generate_paper_section`，且不导入任何 `ari.rqgm` 模块。没有
  `{checkpoint}/paper_archive_state.json` 即意味着一次纯 `linear` 论文
  运行。在 `ari.mode: ari_rqgm` 下，调度还会额外运行*探索*轴的
  paper-candidate 预检（详见
  [RQGM 运行时演练](../concepts/rqgm_runtime_walkthrough.md#_8-运行结束)），
  因此论文阶段仅在默认探索模式下才逐字节一致。
- **`rqgm_archive`**（可选启用）—— 宪法式论文归档：在草稿空间上的一棵
  浅层 best-first 树（`PaperArchiveStrategy`、`ari/rqgm/paper_archive.py`），
  由受治理的 `paper_writer` + `paper_reviewer` 驱动未受治理的
  `ari-skill-paper` 执行器（`ari/rqgm/paper_draft_executor.py`）作为
  "双手"。该层本身见
  [RQGM 架构](../concepts/rqgm_architecture.md)。

### 启用论文归档

```yaml
# workflow.yaml
paper:
  mode: rqgm_archive       # master switch (linear | rqgm_archive)
rqgm:
  paper:
    enabled: true          # redundant safety interlock
```

两个键必须一致。联锁在警告后向 `linear` 安全回退
（`resolve_paper_mode`）：

| `paper.mode` | `rqgm.paper.enabled` | 生效论文模式 | 行为 |
|---|---|---|---|
| `linear` | `false` | `linear` | 默认；静默 |
| `linear` | `true` | `linear` | 警告：设置了联锁但模式为 linear |
| `rqgm_archive` | `false` | `linear` | 警告：请求了该模式但联锁未开启 |
| `rqgm_archive` | `true` | `rqgm_archive` | 构造论文归档运行时 |

环境变量覆盖（由 `apply_paper_env_overrides` 应用，`ari paper` 命令会
显式调用它 —— 它们绝不搭 `load_config` 的便车）：`ARI_PAPER_MODE` ∈
{`linear`, `rqgm_archive`}，`ARI_RQGM_PAPER_ENABLED` ∈
{`0`,`1`,`true`,`false`}。无效值会产生警告并被忽略。

当生效论文模式为 `rqgm_archive` 时，`ari paper` 会在归档循环运行之前
一次性写入 `{checkpoint}/paper_archive_state.json`（论文模式、联锁、
`mode_source` ∈ `config|env|resume`、探索模式、种子节点；
`persist_paper_run_start`，仅写一次 —— 若后续调用算出的种子不同，会向文件的
`seed_journal` 追加一条 `seed_changed` 记录，而不是改写原记录）。
重新调用时以检查点优先对账
（`reconcile_paper_resume_mode`）：持久化的论文模式优先于配置和环境
变量，不一致时产生警告，而没有该状态文件的检查点在该阶段保持
`linear` —— 因此纯 linear 的重新调用绝不会加载任何 `ari.rqgm` 模块。
`resume` 在这条轴上同样是保留值：只有当 `paper_archive_state.json` 已经
存在时 `ari paper` 才会选择 `mode_source: resume`，而那恰恰就是仅写一次的
守卫跳过写入的情形，因此已持久化的文件永远记录的是首次调用时的
`config`/`env` 决定。

### agent-as-judge 草稿评分（可选启用）

`rqgm.paper.reviewer.agent_as_judge.enabled`（bool，**默认 `false`**；
`max_tokens` 默认为 `1024`）决定每份归档草稿如何评分。环境变量覆盖
`ARI_PAPER_AGENT_AS_JUDGE` ∈ {`0`,`1`,`true`,`false`} 由同一个
`apply_paper_env_overrides` 应用，采用与 `ARI_PAPER_MODE` /
`ARI_RQGM_PAPER_ENABLED` 完全相同的 validate-before-assign 姿态 —— 无效值
会产生警告并被忽略。与其余所有 `rqgm.paper.*` 键一样，它只在生效
`rqgm_archive` 论文模式下才有意义。

- **关闭**（默认）—— 确定性的、不使用 LLM 的会场评分表打分：即
  `GovernedPaperReviewer.score` 自身的 else 分支（`_rubric_draft_score`），
  也正是 `ari/rqgm/paper_judge.py:deterministic_rubric_score_fn` 作为裁判的
  回退目标所封装的同一套组合。草稿评分路径上不放置任何实时 LLM 调用，
  因此保持 P2 确定性。
- **开启** —— 共享的论文调度
  （`ari/cli/paper_dispatch.py:build_agent_as_judge`，`ari paper` / `ari run` /
  `ari resume` 一律使用它）注入一个由真实 `LLMClient` 支撑的
  `reviewer_score_fn`（`build_agent_as_judge_score_fn`），它沿**同一套**会场
  评分表轴给每份草稿打分，权重取自 ACTIVE 的受治理 `paper_reviewer` 提示词
  的侧重（因此进化审稿人会改变 best-belief 选择），并且能读取任何确定性读取器
  都读不到的轴 —— `novelty`、`significance` —— 这正是打破识别上限的关键：
  否则两份成熟草稿都会把结构评分表打满而并列。

评分是**失败开放的，绝不返回捏造的常数**：LLM 报错、无法解析的回复、未指名
任何评分表轴的回复，以及覆盖评分表总轴权重不足 50% 的回复，都会降级为确定性
评分表；非有限值会被拒绝，而不会传播进选择。由于对下游的每个消费者而言，
裁判分与回退分都是同一个 float，score_fn 携带 `judged` / `degraded` 计数器，
论文调度在归档之后将其记入日志（`log_agent_as_judge_provenance`）—— 否则
一次每个调用 LLM 都宕机的运行，
看起来会与完全由裁判打分的运行毫无区别。

### 与 `ari.mode` 的 2×2 独立性

两个轴相互独立 —— 四种组合全部有效：

| `ari.mode` | `paper.mode` | 探索 | 论文写作 |
|---|---|---|---|
| `simple_bfts` | `linear` | 经典 BFTS | 经典 linear 论文 |
| `simple_bfts` | `rqgm_archive` | 经典 BFTS | 受治理的草稿归档 |
| `ari_rqgm` | `linear` | 纪元治理 | 经典 linear 论文 |
| `ari_rqgm` | `rqgm_archive` | 纪元治理 | 受治理的草稿归档 |

`resolve_paper_mode` 从不读取 `ari.mode`，探索侧的
`resolve_effective_mode` 也从不读取 `paper.*`；`_effective_paper_mode_str`
以免导入的方式镜像论文激活单元，因此默认论文运行绝不加载
`ari.rqgm.paper_mode`（由 `tests/test_paper_mode.py` 钉住一致性）。受
治理的 `paper_writer` / `paper_reviewer` 角色是 **paper-mode-gated 的
创始行**（`ari/rqgm/events.py:EVOLVABLE_ROLES`）：它们只在生效
`rqgm_archive` 论文模式下才进入注册表，因此无论论文归档是否开启，探索
`ari_rqgm` 的启动都逐字节一致。

### 成本上界与降级 on-ramp

每纪元的草稿群体以 `node_budget =
min(width·(1+refine_rounds), max_expansions)`
（`paper_archive.archive_node_budget`）为界，它在**任意深度**都成为
BFTS 的 `max_total_nodes` —— 更深的树只是重新分配同一预算，绝不做
乘法（没有 `width^depth` 项）。在默认配置（`width: 4`、
`refine_rounds: 2`、`max_expansions: 12`、`depth: 3`）下为
`min(4·(1+2), 12) = 12` 个节点。两个 on-ramp 让默认保持廉价且诚实：

- `rqgm.paper.prompt_evolution.enabled: false` 把归档收缩为受审的
  best-of-N —— 抑制候选生成，角色固定在其创始 v1 提示词上，成本约等于
  当前论文阶段。
- `rqgm.paper.anchor.enabled: false`（**默认**）让审稿人没有真值锚点，
  因此即便 `prompt_evolution.enabled: true`，默认的 `rqgm_archive` 在提供
  一份精选语料库之前也表现为受审的 best-of-N
  （见[采用论文归档](rqgm_migration.md#采用-paper-mode)）。

论文阶段向治理预算那个封闭的 `ACTION_KINDS` 集合（`ari/rqgm/budget.py`）中
恰好只新增一种动作类型：`paper_anchor_scoring`，按当前生效的审稿人每被评分
一个 held-out 锚点用例计一个单位。它的每纪元上限是
`rqgm.paper.anchor.sample_size`（默认 `8`）；只要
`rqgm.paper.anchor.enabled` 为 false —— 也就是上文的默认值 —— 上限即为 `0`。
因此在默认 on-ramp 下，锚点一致度评分并非只是被跳过，而是预算本身就记为零
（与 `shadow_call`、`virsci_call` 既有的「禁用即返回 0」形态相同）。论文归档
所做的其他受预算动作，一律计入已经存在的上限：例如 self-preference 对手会把
每一轮攻击都通过 `adversary_call` /
`rqgm.adversarial.max_adversary_calls_per_epoch` 来把关。

这里的「每纪元」指的是每个*论文*纪元 —— 归档在 `current_paper_epoch`（若没有
打开的论文纪元对象，则为 `paper_epoch_000`）之上构建自己的
`GovernanceBudgetManager`。预算耗尽按惯常方式降级：用例循环停止，审稿人保留
其已评分前缀所得到的一致率，且不会有异常抛入论文循环。读取计数器时有两点值得
留意。预算是在审稿人给出判定*之前*就已计入的，因此一个没有产生判定的用例
——它也因此被排除在一致度覆盖之外 —— 同样消耗一个单位。另外，预算管理器对
`None` 是 fail-open 的，所以没有检查点目录的论文运行、或者管理器构造失败的
运行，会**在不受把关的情况下**完成锚点评分，而不是被阻断。每纪元的合计会以
尽力而为的方式镜像到 `{checkpoint}/paper_archive_state.json` 的
`budget_counters`（`anchor_scoring_calls`），它派生自 `rqgm_audit.jsonl` 中
持久的 `budget_consumed` 行，因此重复调用绝不会重复计数。

**已知缺口 —— 上限只覆盖两趟锚点评分中的一趟。**计入预算的只有当前生效
审稿人的那一趟：它对每个 held-out 用例先把关、再消耗一个单位，`sample_size`
与 `anchor_scoring_calls` 描述的正是这一趟。co-evolution 的候选评估器会为每个
待定的 `paper_reviewer` 候选，对*同一份* held-out 用例列表再走*第二趟* ——
它直接调用 `score_reviewer_on_anchor`（`ari/rqgm/paper_anchor.py`），而该函数
不持有预算管理器，既不把关也不消耗。因此
`rqgm.paper.anchor.sample_size` 界定的是每个论文纪元中当前生效审稿人的用例
数，而不是该纪元的锚点评分次数：若读者把它当作 O(候选数 × `sample_size`)
形状的成本模型，应当理解为它只界定了当前生效审稿人那一半 —— 因为有 C 个待定
审稿人候选时，语料库还会被完整地、无上限地再走 C 遍。`anchor_scoring_calls`
派生自 `budget_consumed` 行，因此正好少报了这一部分锚点工作量。这里关乎的是
成本与可观测性，而非治理 —— 没有任何候选的判定因此改变，也没有任何把关因此
放松。

在出厂默认下，有两个彼此独立的条件让两趟都保持静默。
`rqgm.paper.anchor.enabled: false` 时 `load_anchor_corpus` 不返回任何池，而
候选分支正是以该池为守卫，所以根本不会执行。另外，生产路径中任何地方都没有
接入 `reviewer_verdict_fn` —— `ari paper` 构建论文归档运行时时不传入它 ——
因此即使提供了语料库，`anchor_verdict` 对每个用例都返回 `None`，两趟都会弃权
而非评分。在该状态下当前生效的那一趟仍然消耗预算（原因同上：计入先于判定），
而不受把关的候选那一趟既不消耗预算，也不做实际评分工作。少计只有在这个上限
本来所针对的配置里才成为实际问题：一旦语料库就位且判定来源已接入，每个待定
审稿人候选都会额外带来一次完整的语料库遍历，没有任何上限会拦下它，也没有
任何计数器会记录它。

## 从 GUI 选择模式

上文所述才是权威说明：模式是一项配置决策，按标准优先级从 `workflow.yaml` +
profile + 环境变量解析而来；对于已经存在的运行，
`{checkpoint}/rqgm_state.json`（或 `{checkpoint}/paper_archive_state.json`）
才是权威来源。

自 **ADR-09**（2026-07-27 接受）起，仪表盘可以为**新建**运行做出这项决策，
而不必让你手工编辑两个互锁的键。它仅就这种情形 supersede 了此前「v1 中没有
GUI 开关」的表述 —— `--mode` CLI 标志依然不存在，也没有任何 GUI 路径能够
更改已经存在的运行的模式。

**控件在哪里。** 配置工作室（`#/studio`）的 *Execution* 分区，作用域为
**运行模板**或**运行草稿**。每个轴一个控件，共两个：

| 控件 | 写入的键 | 取值 |
|---|---|---|
| Execution mode | `ari.mode` **与** `rqgm.enabled` | `simple_bfts`（默认）/ `ari_rqgm` |
| Paper mode | `paper.mode` **与** `rqgm.paper.enabled` | `linear`（默认）/ `rqgm_archive` |

使用之前有四条性质值得了解：

1. **一个控件同时写入其互锁的两个键。** 选择 `ari_rqgm` 会在同一次保存中写入
   `ari.mode: ari_rqgm` *与* `rqgm.enabled: true`。GUI 无法构造出那种会让运行时
   静默降级的半边配对；若某个文档确实只带了一半而缺少与之一致的另一半，服务器
   会在模板 create/PATCH、草稿 create/PATCH 以及启动时以带类型的 400
   `mode_interlock_mismatch` 拒绝它。
2. **仅限新建运行。** 两个叶子都是 `mutability: new_run_only`。该选择作用于
   Studio 即将启动的那次运行。**恢复不受影响**：`ari resume` 仍然以检查点优先
   读取 `{checkpoint}/rqgm_state.json`，持久化的模式仍然优先于配置与环境变量，
   运行的模式在整个运行期间保持不变。没有任何 GUI 路径会写入
   该文件。
3. **project 作用域依然拒绝。** 这些模式路径是 `scope: run`，因此项目默认值
   文档会拒绝它们（`not_project_scope`）；在该作用域下这两个控件被禁用，并给出
   原因。
4. **开放的只有这四个叶子。** `Execution mode` 分类与 `rqgm.*` 树中其余 104 条
   路径（epoch、kernel、governance、adversarial、预算调优）在本次发布中**不能**
   从 GUI 编辑。它们仍以只读方式连同其生效值一起展示，携带其中任何一条的草稿
   在启动时仍会被以 `mode_locked` 拒绝 —— 要修改请编辑 `workflow.yaml`。选择
   模式并不是治理变更：RQGM 治理工作区及其
   `/api/v1/runs/{run_id}/rqgm/*` 路由依旧只读。

**GUI 选中的模式会对检查点做什么。** 非默认的选择会以两种方式落地，使检查点
自我描述：最小化的 `ari:` / `rqgm:` / `paper:` 块会被合并进该运行**自身的**
`workflow.yaml` 副本（绝不修改打包文件；当这些顶层键不存在时块会被追加，
现有的每一个字节与注释都原样保留），同时把已文档化的环境变量覆盖
`ARI_MODE`、`ARI_RQGM_ENABLED`、`ARI_PAPER_MODE`、`ARI_RQGM_PAPER_ENABLED`
导出给运行子进程。保持默认则**什么都不写、什么都不导出** —— 一次
`simple_bfts` + `linear` 的启动与 ADR-09 之前逐字节相同，包括那种显式重新
选中默认值的草稿（判定依据是解析后的*取值*，而不是你有没有动过控件）。

**运行时回退时 GUI 会显示什么。** 启动复核从不显示你请求的内容 —— 它显示从
该运行的预览清单读到的**解析后**模式，也就是 `resolve_effective_mode` /
`resolve_paper_mode` 应用其告警并回退的规则之后的取值。若某个 Studio 并不拥有
的层破坏了这个配对（例如草稿请求 `ari_rqgm`，而服务器环境中带有
`ARI_RQGM_ENABLED=0`），复核会逐字呈现请求值、解析值以及解析器的告警，并且
启动会以 `interlock_mismatch` 校验错误被**阻止**，而不是悄悄启动那次回退后的
运行。只有当解析后的模式为 `ari_rqgm` 时，运行才会显示为受治理。

## 宪法内核（Layer 0）

在 `ari_rqgm` 模式下，每一次治理状态变更都由
`ConstitutionalKernel`（`ari/rqgm/kernel.py`）校验。该内核是**确定性的、
不可进化的，且不是 LLM 裁判**：零 LLM 调用、零网络调用、零依赖挂钟的
决策（设计原则 P2）。它只裁决程序 —— 从不裁决研究的正确性。固定层整体
永远不是进化目标：内核、schema 检查器、哈希检查器、访问控制（能力
矩阵）、审计日志、转换规则、选择性擦除规则、固定校验器（results.json
合并）、指标重算器，以及 claim-evidence 硬门。

规则存在于代码中，永远不在配置里：`ari/rqgm/kernel_rules.py`（角色
规则、能力矩阵、严重度映射）和 `ari/rqgm/transition_rules.py`（固定的
T1–T21 转换表，与 RegistryTransitionEngine 共享 —— 单一事实来源）。
覆盖全部规则表的 `constitution_hash` 由
`ari-core/tests/test_rqgm_kernel.py` 钉住，并以增量方式记录在
`meta.json` 中，因此任何规则修改都是一次显式的、需评审的 diff 加上一次
哈希重钉。打包的 `constitution.yaml` 只是人类可读的声明 —— 编辑它不会
改变任何东西。

**为什么规则是代码。** 检查点目录是一个扁平的共享文件系统，任何一个 MCP
技能都能写入它。把角色规则、能力矩阵、严重度映射或转换表放进检查点作用域
的 YAML，等于把一条通往「审判自己的宪法」的进化 / 篡改通道交到任意组件
手里。因此它们是冻结的 Python 常量，内核中唯一可配置的部分只有数值：
`rqgm.kernel.enforcement`、`rqgm.kernel.audit_chain` 与
`rqgm.kernel.float_tolerance`。

`CAPABILITY_MATRIX` 中固化了三条常量，对每个层级的每个角色都成立：没有任何
`(role, tier)` 行授予 `read: retired_prompt_text`（受认可的读取路径是
`RetiredPromptAccessGuard`，其狭窄的 fixed 层豁免集合是绕过矩阵，而不是由
矩阵授予）；只有 `fixed` 层的 `registry_transition_engine` 持有
`write: registry` 与 `activate: candidates`；而每个可进化角色的 `meta`
层行两者皆无，无论候选自己声明了什么。

**被接受的代价。** 由于规则是被 `constitution_hash` 覆盖的代码，改动一条
规则就等于一次代码评审加上对 `ari-core/tests/test_rqgm_kernel.py` 中期望
哈希的手工重钉；并且有测试断言：编辑*被导入的*转换表同样会改变该哈希，
所以无法通过改另一个模块来绕开这枚钉子。实验进行中给规则打补丁的手段是被
刻意排除的 —— 紧急修复意味着一次新构建，而不是一次配置编辑。以这种方式
做出的修正会作为注释就地记录在 `ari/rqgm/kernel_rules.py` 中，每一条都写明
改了什么以及哈希钉已重新计算 —— 于是宪法的历史就是一份可评审的 diff。

阻断矩阵概要（"阻断制度，而非研究"）：

- **硬阻断集合**（否决 RQGM 状态变更 —— 纪元转换提交、注册表写入、
  前沿重建提交、候选晋升 —— 从不否决节点执行）：转换表违规、非引擎的
  注册表写入、来自过期/已退役提示词的记录进入前沿、治理记录 schema
  违规、活跃组件哈希不匹配、审计日志篡改、洁净室污染、权限扩张，以及
  预检能力拒绝（包括对已退役提示词文本的访问，在 MCP 门处以标准
  `{"error": ...}` 信封拒绝）。
- **警告并标记集合**（从不打断研究执行）：逐节点的记录 schema 与哈希
  异常、事后访问发现、创建时的角色分离发现、上下文范围发现。一条警告
  发现会作为 `kernel_report` 条目追加到 `rqgm_audit.jsonl`，并且对治理
  流水线自身产出的记录还会计入报告的 self-audit 块 —— 但它**不会**设置
  任何让该记录事后变得不可采信的标志。证据包的可采信性由记录类型、
  作者角色以及按类型的完整性检查（`ari/rqgm/governance/_evidence.py`）
  独立决定。

**内核在哪里被调用。** 内核是被动的 —— 它只返回裁决，自身从不变更治理
状态；所有写入与后果都归适配器所有。安装它的适配器共有六个，且全部只在
`ari_rqgm` 下构造：

| 执行点 | 运行的检查 | 阻断裁决的效果 |
|---|---|---|
| 纪元边界事务（`RegistryTransitionEngine.apply`） | `validate_transition` | 事务被标记为 `aborted`，任何已解析的状态变更（晋升、制裁、退役）都不会应用；上一纪元的活跃集合原样延续，运行继续 |
| 前沿重建提交（`FrontierRepairEngine.repair`） | `validate_selective_erasure` | 引擎改为保守修复（把每个被标记的节点整个丢弃）并重新校验；若第二次仍被阻断，运行降级为 drain-only（`halted_expansion`：完成待办工作，不再扩展） |
| MCP 工具派发（`CapabilityGatedMCPClient.call_tool`） | 对工具策略映射出的 `(actor, action, resource)` 三元组执行 `validate_capability` | 该调用不被派发，调用方收到标准的 `{"error": ...}` 信封。若违规码属于引擎的紧急触发集合，还会额外触发 T16 紧急隔离钩子 —— 这是运行中的 agent 唯一能在纪元中途触碰宪法的地方 |
| 逐节点钩子（`RQGMRuntime.run_per_node_kernel_check`） | 对该节点产出的记录执行 `validate_record_schema` 与 `validate_hashes`，外加 K/C/A 完整性检查 | 记录类发现仅警告并写入审计日志。一条阻断性的 K/C/A 完整性发现会把节点标记为 `assurance_status: tampered`、`frontier_class: uncertified_frontier` 与 `_valid_for_frontier: false` —— 节点仍然运行过，只是被排除在前沿之外 |
| 治理自审计（`GovernanceOrchestrator.audit_epoch`） | 对流水线自身产出的记录重跑 `validate_record_schema` 与 `validate_role_separation` | 此处不否决任何东西：发现被计入报告 self-audit 块的 `kernel_violations_found`、`escalations` 与 `ban_recommendations` |
| 恢复完整性检查（`RQGMRuntime.resume_integrity_check`） | 对恢复出的检查点执行 `validate_audit_log_integrity` 与 `validate_selective_erasure` | 运行仍会恢复，但进入治理挂起式延续（这是拒绝恢复之外的降级方案）。在该状态持续期间，纪元审计被跳过，每个边界解析出空转换，元进化也被跳过 |

每个适配器对自身的 bug 都是 fail-open 的：钩子内部的异常会被记录并吞掉，
绝不抛进运行循环。唯一刻意的例外是前沿修复的校验器 —— 它把自身的异常当作
失败裁决，因而在边界处以 fail-closed 的方向降级。

**已知缺口 —— 纪元不变性只做检测。** `CK-EPO-002`（纪元中途的非紧急活跃
集合变更）带有 block 严重度，但它唯一的生产调用点 —— 由运行循环驱动的
`RQGMRuntime.check_epoch_invariance` —— 只是把该发现作为 `kernel_report`
条目记入 `rqgm_audit.jsonl` 并告警。它从不查询 `should_block`，也不否决
任何东西：不会因为一条纪元不变性发现而拒绝任何采纳，也不会拒绝任何注册表
变更。`CK-EPO-002` 同时也被列在引擎的紧急触发集合中，但发出它的校验器只有
纪元不变性那一个，而该路径并不经过升级钩子 —— 所以这项列举同样从不触发。
请把 `CK-EPO-*` 读作该纪元治理审计的证据，而不是一道被执行的屏障。

当一次转换被阻断时，上一纪元的活跃集合原样延续，运行继续（绝不中止
运行）。`rqgm.kernel.enforcement: audit_only` 将
所有上下文降级为仅警告并记录，用于分阶段上线和消融实验。

## 兼容性保证

- `rqgm.enabled: false`（或 `ari.mode: simple_bfts`）使整个 RQGM 子树
  在结构上惰性 —— `ari.core.build_runtime` 中的惰性导入分支是唯一的
  门，而不是散落各处的按功能标志。
- `simple_bfts` 路径上唯一被触及的代码：两个带默认值的类型化配置字段、
  一次环境变量覆盖调用，以及少数几处鸭子类型的
  `getattr(bfts, "rqgm", None)` 探测（运行循环、运行时装配、论文调度的
  句柄传递）—— 在该路径上它们全都读到 `None`。
- 旧检查点没有 `rqgm_state.json`；`resume` 将其缺失视为
  `simple_bfts`。部署在旧版 ari-core 上的 `rqgm:` 块会被静默忽略
  （当前行为 —— 最安全的失败方向）。

## 限制（v1）

- Profile（`--profile`）不合并 RQGM 键。
- 没有 `--mode` CLI 标志。GUI 只为**新建**运行选择这两项模式意图
  （[见上文](#从-gui-选择模式)）；其余 `rqgm.*` 治理与调优参数仅能通过
  配置文件设置。
- 运行一旦开始，其模式无法从任何界面更改 —— 恢复采用持久化的模式，运行中
  运行期间不存在任何转换（纪元边界降级属于预留设计，尚未实现）。
