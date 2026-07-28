---
sources:
  - path: ari-core/ari/rqgm/mode.py
    role: implementation
  - path: ari-core/ari/rqgm/state.py
    role: implementation
  - path: ari-core/ari/rqgm/proposals/records.py
    role: implementation
  - path: ari-core/ari/rqgm/proposals/store.py
    role: implementation
  - path: ari-core/ari/rqgm/paper_mode.py
    role: implementation
  - path: ari-core/ari/rqgm/paper_runtime.py
    role: implementation
  - path: ari-core/ari/rqgm/paper_anchor.py
    role: implementation
  - path: ari-core/ari/paths.py
    role: implementation
  - path: ari-core/tests/test_rqgm_mode.py
    role: test
  - path: ari-core/tests/test_rqgm_proposals.py
    role: test
  - path: ari-core/tests/test_paper_mode.py
    role: test
last_verified: 2026-07-16
---

# 在现有项目上采用 `ari_rqgm`

如何把一个现有的 ARI 项目迁移到可选启用的 `ari_rqgm` 治理模式 ——
以及如何迁回来。关于模式语义本身（激活键、联锁表、内核）见
[执行模式](execution_modes.md)；关于在不同检查点格式*版本*之间的迁移见
[迁移指南](migration.md)。本页只讨论同一版本内的模式切换。

## 第 0 步：无需迁移

RQGM 之前的配置照常工作。`simple_bfts` 是默认模式，一个没有
`ari:`/`rqgm:` 块的 `workflow.yaml`（即所有 RQGM 之前的配置）不构造
任何 RQGM 对象、不导入任何 `ari.rqgm` 模块、不写入任何新的检查点
文件 —— 默认检查点与 RQGM 之前的 ARI 保持逐字节一致。留在
`simple_bfts` 上不需要任何配置修改、检查点转换或重新运行。

两个兼容方向：

- **旧检查点，新 ari-core**：检查点没有 `rqgm_state.json`；
  `ari resume` 将其缺失视为 `simple_bfts`。
- **新配置，旧 ari-core**：部署在旧版 ari-core 上的 `rqgm:` 块会被
  静默忽略（最安全的失败方向）。

## 可选的第 1 阶段：仅记录双写（B1）

在切换模式之前，你可以在零行为变化的前提下试用提案记录存储：

```yaml
proposal_router:
  record_only: true    # honored in simple_bfts; default false
```

`record_only` 是唯一在 `simple_bfts` 下生效的 `proposal_router.*`
键。设置后，agent 循环的 `idea.json` 输出会被额外导入
`{checkpoint}/proposals/proposal_records.jsonl`，作为
`legacy_idea_json` 记录（`ideas[0]` —— 即当前指令 —— 记为
`selected`，其余记为 `candidate`；`epoch_id: null`，因为
`simple_bfts` 没有纪元）。`idea.json` 本身**不会**被重写，没有任何
消费方发生变化，且内容键去重使重复导入幂等。这就是
[评估阶梯](rqgm_evaluation.md)中的 B1 档。回滚 = 删除该标志；留下的
记录是惰性的
（`test_rqgm_proposals.py::test_simple_bfts_record_only_dual_writes`）。

## 将一次「新」运行切换到 `ari_rqgm`

```yaml
# workflow.yaml (or --config)
ari:
  mode: ari_rqgm
rqgm:
  enabled: true
```

或者按运行、以 GUI 兼容的方式：`ARI_MODE=ari_rqgm ARI_RQGM_ENABLED=1`。
两个键必须一致（[联锁表](execution_modes.md#turning-rqgm-on)）。

生效模式在**运行开始时解析一次**，并在第一个节点运行前持久化到
`{checkpoint}/rqgm_state.json`。该文件是这次运行的模式溯源；它的缺失
意味着一次纯 `simple_bfts` 运行。

**Resume 从不升级。**`ari resume` 通过
`ari.rqgm.state.reconcile_resume_mode` 以检查点优先的方式对账：

- **没有** `rqgm_state.json` 的检查点是以 `simple_bfts` 开始的，就
  保持 `simple_bfts` —— 在 resume 时请求 `ari.mode: ari_rqgm`（或对应
  的环境变量）只会记录一条警告并被忽略；`simple_bfts` 循环中不存在
  合法的运行中升级点。
- **有** `rqgm_state.json` 的检查点：持久化的模式优先于包配置和环境
  变量。不一致时只产生警告，绝不会在运行中途翻转模式。

因此，升级一个现有项目意味着启动一次**新运行**（或以
`ARI_MODE=ari_rqgm` 启动子运行）—— 通常通过现有的
`inherit_idea_index` / 固定 `idea.json` 机制继承上一次运行的方向，
RQGM 会在根构思阶段将其作为 `legacy_idea_json` 记录导入。

## `idea.json` ↔ ProposalRecord 兼容性

RQGM 不替换 `idea.json`；它把它降级为提案记录存储的一个**投影**
（`ari/rqgm/proposals/store.py`）：

- **9 键契约得到保留。**投影出的文档恰好保留每个现有消费方读取的
  顶层键：`gap_analysis`、`ideas`、`primary_metric`、
  `higher_is_better`、`metric_rationale`、`papers_analyzed`、
  `n_agents`、`discussion_rounds`、`virsci_integration_status`
  （`ari.rqgm.proposals.store.IDEA_JSON_KEYS`；由
  `test_rqgm_proposals.py::test_projection_nine_key_contract_and_plan_parse`
  钉住）。
- **单一写入方。**在 `ari_rqgm` 中，该存储是 `idea.json` 的唯一写入
  方，始终通过一个函数（`build_idea_projection`）从记录派生。
  `_pinned` / `_inherited_from` / `_root_choice` 一次性标记在重写中
  逐字保留，因此跨运行继承和根选择继续工作。
- **可追溯性。**投影出的每个 `ideas[i]` 条目都带一个下划线键
  `_proposal_record_id`，链接回 `proposals/proposal_records.jsonl`
  （与 `_pinned` / `_inherited_from` 相同的约定）。
- **逆映射。**现有的 `idea.json` 内容（固定的种子，或上面第 1 阶段的
  双写）能足够无损地导入，从而继续走遗留通道：`summary_from_idea`
  使用与遗留路径相同的 `_extract_plan_sections` 解析器，把拼接的
  `experiment_plan` 拆回有界的步骤。

## 新增的检查点文件

一次 `ari_rqgm` 运行会新增以下文件。新文件名注册在
`PathManager.META_FILES`（`ari/paths.py`）中，因此 ARI 将它们归类为
运行元数据 —— 绝不复制到节点工作目录 —— 且 `proposals/` 子树额外被
排除在节点文件报告之外（由
`test_rqgm_proposals.py::test_proposal_filenames_registered` /
`test_proposals_never_in_files_changed` 钉住）。**`simple_bfts`
运行不写入其中任何文件** —— 唯一例外是 `proposals/`，仅当你按上文
选择启用 `record_only` 时才会出现在 `simple_bfts` 下。

| 路径（相对 `{checkpoint}/`） | 是什么 |
|---|---|
| `rqgm_state.json` | 模式溯源：模式、联锁、`mode_source`、切换日志。缺失 == 纯 `simple_bfts` 运行。 |
| `constitution.yaml` | 仅复制一次、不可进化的人类可读宪法声明。 |
| `rqgm_transitions.jsonl`、`rqgm_audit.jsonl` | 追加式事件日志真相 + 治理审计日志。 |
| `epoch_state.json`、`rqgm_registry.json` | 派生快照：当前纪元冻结与组件/提示词注册表。 |
| `proposals/`（`proposal_records.jsonl`、`proposal_index.json`、`archive/…`） | 提案记录真相 + 派生索引 + 原始输出归档。 |
| `rqgm_adversarial_cases.jsonl`、`rqgm/adversarial_replay_pool.json` | 对抗循环记录真相 + 派生的重放池快照。 |
| `prompt_evolution.jsonl`、`prompt_specs.json`、`rqgm_prompts/` | 提示词进化记录真相、PromptSpec 汇总、进化后的模板正文。 |
| `rqgm_cleanroom.jsonl` | 洁净室再生成的请求/筛查/回退事件。 |
| `rqgm_erasure_state.json` | 选择性擦除产生的过期/无效集合的派生汇总。 |
| `rqgm_meta_outputs.jsonl` | 元 agent 输出记录。 |
| `rqgm_governance_cache.jsonl` | 治理结果缓存。 |
| `rqgm_eval_metrics.json`、`rqgm_injection_provenance.json` | 仅评估工具链 —— 正常运行绝不写入。 |

## 回滚

切回去意味着以 `simple_bfts` 启动下一次运行（或让一次 `ari_rqgm`
运行在纪元边界自我降级 —— 唯一的运行内切换，且只能降级）。两个性质
使回滚安全：

- **记录是惰性的。**`simple_bfts` 代码从不读取 `proposals/` 或任何
  `rqgm_*` 文件，因此旧检查点中残留的 RQGM 工件无需清理，也不改变
  任何行为。缺失门是结构性的：`ari.core.build_runtime` 中的惰性导入
  是唯一开关，而不是按功能标志。
- **先前被擦除的节点保持被排除。**选择性擦除是仅逻辑的 —— 什么都不
  删除；过期状态存在于审计日志、`rqgm_erasure_state.json` 汇总，以及
  通过 `tree.json` 持久化的增量 `Node.metrics` 哨兵键（`_stale`、
  `_valid_for_frontier`、…）中。`BFTS.should_prune` **无条件**读取
  `metrics['_valid_for_frontier'] is False`，因此在 `ari_rqgm` 下被
  擦除的节点在切回后依旧被剪枝 —— 污染不会因为切换模式而变干净。
  这些哨兵键只会由 `ari_rqgm` 的 `FrontierRepairEngine` 写入，因此在
  从未运行过 RQGM 的检查点上，该子句是惰性死代码（`_sterile`
  模式）。

## 采用 `paper.mode`

论文写作阶段（`ari paper`）拥有自己的可选启用轴 `paper.mode:
linear | rqgm_archive`，由 `ari.rqgm.paper_mode.resolve_paper_mode` 解析，
且**与 `ari.mode` 独立** —— 你可以在不触碰探索的情况下采用论文归档，也可以
用经典 linear 论文写作器运行纪元治理。`linear`（默认）与当前论文流水线
逐字节一致；没有 `{checkpoint}/paper_archive_state.json` 即意味着一次纯
linear 论文运行。让两个键一致以启用归档：

```yaml
# workflow.yaml
paper:
  mode: rqgm_archive
rqgm:
  paper:
    enabled: true
```

或按运行：`ARI_PAPER_MODE=rqgm_archive ARI_RQGM_PAPER_ENABLED=1`（`ari
paper` 命令通过 `apply_paper_env_overrides` 应用它们）。见
[联锁表](execution_modes.md#turning-the-paper-archive-on)。模式以 write-once
方式持久化到 `paper_archive_state.json`，`ari paper` 重新调用时以检查点
优先对账（`reconcile_paper_resume_mode`）—— 持久化的论文模式优先于配置和
环境变量，与探索的 `rqgm_state.json` 完全一致。

### 默认是一个降级 on-ramp

启用 `rqgm_archive` **并不会**立刻给你完整的协同进化循环。两个旋钮对它
门控，且都以保守值起步：

- **锚点默认关闭**（`rqgm.paper.anchor.enabled: false`）。没有锚点，审稿人
  就没有可据以赢得信任的真值，因此默认的 `rqgm_archive` 是**受审的
  best-of-N**：一棵由单个冻结审稿人打分的 best-first 草稿归档树。要让审稿人
  协同进化，请提供一份精选的 APReS 等价 accept/reject 语料库并启用它：

  ```yaml
  rqgm:
    paper:
      anchor:
        enabled: true
        corpus_path: paper_anchor_corpus.jsonl   # 相对于检查点
  ```

  每个语料案例都**必须**声明 `label_source`（`human_curated` |
  `gate_bootstrap`）；一个机器强制的 `max_bootstrap_label_fraction` 上限
  （默认 0.5，同时施加于整个语料库**与**保留子集）会拒绝过度依赖自生成
  `gate_bootstrap` 标签的语料库。任何违规 —— 或缺失/为空/被污染的语料库 ——
  加载器都会降级为"无锚点门"，且**从不抛异常**
  （`ari/rqgm/paper_anchor.py:load_anchor_corpus`）。拒绝锚定严格地比在
  自标签上锚定更安全。

- **默认纪元数被有意设置得廉价**（`rqgm.paper.epoch.rounds: 2`）。两轮时，
  边界与（在始终宽松的审稿人下）弹劾动议都会触发，但
  `candidate → validated → shadow → probationary_active` 的攀升需要一个角色
  空位加约 5 个边界，因此**一次完整的审稿人采用不会完成** —— 活跃审稿人
  哈希不会改变。必须见证一次完成采用的运行会提高 `rounds`（协同进化 PROOF
  驱动到 8）。

最廉价的姿态是 `rqgm.paper.prompt_evolution.enabled: false`，它完全抑制候选
生成：角色固定在其创始 v1 提示词上，你以约等于当前的成本得到受审的
best-of-N。

### 新增的论文归档检查点文件

一次生效 `rqgm_archive` 论文运行会在 `{checkpoint}/` 下新增：

| 路径 | 是什么 |
|---|---|
| `paper_archive_state.json` | 论文模式溯源：论文模式、联锁、`mode_source`、探索模式、种子节点。缺失 == linear 论文阶段。 |
| `paper_draft_archive.jsonl` | 打分后的草稿群体（每个草稿节点一条记录：framing、审稿分数、tex 哈希、best-belief/compiled 标志）。 |
| `paper_anchor_corpus.jsonl` | accept/reject 锚点语料库，仅当你提供时（只读；绝不由受治理角色撰写）。 |
| `rqgm/paper_self_preference_stat.json` | `paper_self_preference` 对抗者作为其预信号引用的确定性 AI-对-human 自偏好边际。 |

一次 `linear` 论文运行不写入其中任何一个。协同进化还会搭上与探索相同的
`rqgm_transitions.jsonl` / `rqgm_registry.json` / `prompt_evolution.jsonl`
文件，因为论文角色是通过同一个内部 RQGM 运行时治理的。

### 回滚论文归档

在下一次 `ari paper` 时设置 `paper.mode: linear`（或去掉
`rqgm.paper.enabled`）；linear 流水线逐字节一致，残留的 `paper_*` 文件是
惰性的 —— `linear` 代码从不读取它们。

### 诚实的限制

- **两个提示词都协同进化 —— 写作器只在**退化**时。**`paper_writer` 提示词
  锚定于第 0 层 claim-evidence 门的确定性忠实度，经由普通的制裁 → 角色开放
  → T6 路径协同进化。但写作器的后继会停在 `shadow`，直到在任者在该忠实度上
  退化：仅仅更好的挑战者永远不会置换一个忠实的在任者。写作器的*草稿*赢家
  仍然是纪元局部的（由纪元内冻结的审稿人排序）。
- **对写作器的制裁搭乘审稿人的回合。**针对写作器的已验证攻击由
  `paper_self_preference` 回合发出，而该回合仅在存在过度接受的锚案例时触发；
  一个专用的写作器对抗者类型是另一项决定。
- 锚点默认关闭 —— 由于写作器的忠实度案例也落在锚池上，这同样约束写作器 ——
  且默认 `rounds: 2` 不会完成一次采用（见上）。首次 `rqgm_archive` 采用是
  分阶段上线，而非一个开关。

## 限制（v1）

与[执行模式 → 限制](execution_modes.md#limitations-v1)相同：Profile
（`--profile`）不合并 RQGM 键，且没有 `--mode` CLI 标志或 GUI 开关
（环境变量激活在构造上即与 GUI 兼容）。论文轴也共享这些：没有
`--paper-mode` 标志（环境变量激活即与 GUI 兼容），且 profile 不合并
`rqgm.paper.*`。

另请参阅：[执行模式](execution_modes.md) ·
[VirSci 集成](virsci_integration.md) ·
[RQGM 评估](rqgm_evaluation.md) ·
[文件格式参考](../reference/file_formats.md)
