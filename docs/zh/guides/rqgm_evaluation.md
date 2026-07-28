---
sources:
  - path: ari-core/ari/rqgm/evaluation
    role: implementation
  - path: ari-core/ari/rqgm/paper_self_preference.py
    role: implementation
  - path: scripts/rqgm_eval
    role: implementation
  - path: ari-core/tests/test_rqgm_paper_eval.py
    role: test
last_verified: 2026-07-16
---

# RQGM 评估与消融

如何用代码库自带的评估工具链衡量 ARI-RQGM 的每个治理层是否配得上
它的成本。这套机制是内部的（`ari.rqgm.evaluation.*`，不在
`ari.public.*` 中），由一个独立脚本驱动 —— 没有 CLI 命令、没有 MCP
工具、零契约表面变化。

## 消融条件 B0–B8

`scripts/rqgm_eval/ablation_matrix.yaml` 中的九个具名预设，仅靠
配置即可切换。每个条件展开为一个具体的 `ari.mode` + 功能标志覆盖层
（`ari.rqgm.evaluation.conditions.condition_overlay`）；精确的展开
结果由 `ari-core/tests/test_rqgm_eval_conditions.py` 钉住。

| 条件 | 模式 | 增加项（自 B3 起逐层叠加） |
|---|---|---|
| B0 | `simple_bfts` | 对照组 —— 出厂默认配置，原样使用。 |
| B1 | `simple_bfts` | 仅 ProposalRecord 归档（`proposal_router.record_only`）。 |
| B2 | `ari_rqgm` | **带** VirSci 的 ProposalRouter（`proposal_router.generators.virsci.enabled`）。 |
| B3 | `ari_rqgm` | **不带** VirSci 的 ProposalRouter —— B2/B3 即 VirSci 对照。 |
| B4 | `ari_rqgm` | + 对抗者/辩护者/裁判循环（`rqgm.adversarial.enabled`）。 |
| B5 | `ari_rqgm` | + 治理纪元审计（`rqgm.governance.enabled`）。 |
| B6 | `ari_rqgm` | + 退役 + 选择性擦除（`rqgm.frontier_repair.enabled`）。 |
| B7 | `ari_rqgm` | + 提示词进化，含洁净室（`rqgm.prompt_evolution.enabled`）。 |
| B8 | `ari_rqgm` | + 元 agent 进化（`rqgm.meta_evolution.enabled`）—— 完整模式。 |

每一层的边际价值是配对差值：对抗 = B4−B3，治理 = B5−B4，
退役/擦除 = B6−B5，进化 = B7−B6，元层 = B8−B7；VirSci = B2−B3。

由于各层标志（`rqgm.{adversarial,governance,frontier_repair,
prompt_evolution,meta_evolution}.enabled`）在类型化配置中默认为
**true**，且 `load_config` 会用这些默认值填充缺失的键，每个
`ari_rqgm` 档位都要为其上方的各层显式设置 `enabled: false` ——
否则每档的生效配置会静默等同于 B8，边际差值将毫无意义。生效配置由
`test_rqgm_eval_conditions.py::test_effective_config_realizes_the_ladder`
钉住。

## 比较策略

**simple_bfts vs ari_rqgm（主比较）。**在同一实验集
（`scripts/rqgm_eval/experiments/`，或用 `--experiment` 挑选）上比较
B0 与 B8（以及每一档），固定模型、相同节点预算、≥ 3 个配对种子
（`eval_defaults.seeds`）。工具链在机制上强制这一点：
`eval_defaults.bfts`（`max_total_nodes` / `max_depth`）被合并到每个
条件覆盖层之下，`eval_defaults.models` 在活动开始时解析一次，写入
`ARI_MODEL_CODING` / `ARI_MODEL_BFTS` / `ARI_MODEL_EVAL` 环境变量并
盖印到每次派生的运行上。公平性以**节点预算**为准；token/美元/
挂钟时间只*报告*、从不拉平，因此 RQGM 的开销保持可见。每次运行都
使用全新检查点 —— 不 resume、不跨条件复用 `skip_if_exists`。

**VirSci 开/关（次比较）。**在匹配预算下比较 B2 与 B3。关闭条件
必须在 `prompt_trace.jsonl` 中不出现 VirSci 提示词，且没有 VirSci
转录文件（`virsci_logs/`、`virsci_snapshot/`）—— 工具链通过
`ari.rqgm.evaluation.conditions.virsci_absence_violations` 逐运行
强制这一点，并在污染时判该运行失败；Tier-1/2 在未安装 VirSci 的
机器上也能通过。

**回归护栏。**B0 兼作兼容性检查：在 RQGM 代码存在的情况下，它必须
产出 RQGM 之前的工件契约（文件集合、tree.json schema、保留指标
键）。由
`test_rqgm_eval_smoke.py::test_b0_smoke_checkpoint_has_no_rqgm_artifacts`
钉住。

## 故障注入

十个具有二元真值（注入 = 坏，对照 = 好）的确定性注入，在
`scripts/rqgm_eval/failure_injections.yaml` 中指定。两种机制，均不
使用 LLM：

- **fixture**（1 指标操纵、2 过度声称、3 幻觉先前工作、7 被污染的
  提示词、9 洁净室违规、10 过期记录泄漏）—— 精心构造的检查点片段，
  位于 `ari-core/tests/fixtures/rqgm_eval/`，在 CI 中直接跑过各
  确定性检测器（claim gate、Task 07 校验、内核检查）。
- **scripted_component**（4 对抗者越权、5 裁判偏倚、6 坏生成器、
  8 坏提示词变异器）—— 来自
  `ari.rqgm.evaluation.doubles.EVAL_DOUBLE_REGISTRY` 的确定性替身，
  通过 `rqgm.eval.scripted_components` 替换，且除非
  `rqgm.eval.enabled` 否则被拒绝（替身永远不可能泄漏进生产运行）。
  **仅限 smoke 层**：真实的 `ari run` 从不查询
  `rqgm.eval.scripted_components`，因此 `run_ablation.py` 在
  `--smoke` 之外拒绝 scripted 规格，而不是记录一个从未被注入的
  故障。

注入 id 使用保留的 `eval_*` 命名空间（与 `adv_*` / `anchor_*`
不相交）；每次被注入的运行都带有
`rqgm_injection_provenance.json`。

## 指标

十三个指标由
`ari.rqgm.evaluation.metrics.compute_metric_report` 事后计算 ——
它是对持久化检查点工件（tree.json、提案存储、对抗案例日志、
`rqgm_audit.jsonl`、注册表/擦除汇总、`cost_trace.jsonl`、
meta.json）的纯函数。每个条目形如 `{value, numerator, denominator,
evidence_refs, applicable}`；数据源缺失时产出
`applicable: false`，从不抛异常。结果落入
`rqgm_eval_metrics.json`（注册在 `PathManager.META_FILES` 中）。

1–3 科学/吞吐（最佳有效分数、提案→可执行率、下游成功率）；4–8
针对注入真值的检测质量（误接受/误拒绝、已验证攻击精确率、错误
弹劾、退役精确率）；9–10 擦除健康度（前沿污染、擦除后恢复 ——
序数度量，绝不用挂钟时间）；11–12 成本（每检出一个故障的成本、
分阶段 token 总量）；13 挂钟时间（仅元数据，从不参与哈希）。

## 论文归档评估（`paper.mode`）

论文写作轴有自己的、并行的评估轨道 —— 独立的 B 阶梯、独立的 P1–P5
指标、独立的 PI1–PI3 注入 —— 用于 `paper.mode: rqgm_archive` 路径（见
[执行模式 → paper.mode](execution_modes.md#the-paper-execution-axis-papermode)）。
它复用相同的工具链、`eval_*` 命名空间以及以节点预算为准的公平性。

### 论文条件（B0_paper_linear / B_archive_no_coevo / B_full）

`scripts/rqgm_eval/ablation_matrix.yaml` 的 `paper_conditions` 块中的
三个具名预设（`ari.rqgm.evaluation.conditions.PAPER_CONDITION_IDS`）。
与探索档位不同，它们是**配置路径原生的** —— 预设直接
（`conditions.paper_condition_overlay`）展开为 `paper.mode` +
`rqgm.paper.*` 覆盖层，因此展开结果就是生效配置。由
`ari-core/tests/test_rqgm_paper_eval.py` 钉住。

| 条件 | `paper.mode` | 增加项 |
|---|---|---|
| B0_paper_linear | `linear` | 对照组 —— 出厂默认论文流水线，原样使用 |
| B_archive_no_coevo | `rqgm_archive` | best-first 草稿归档（width 4、refine 2、depth 3、≤ 12 节点），`prompt_evolution.enabled: false` —— best-of-N 受审草稿，单个冻结的 writer/reviewer |
| B_full | `rqgm_archive` | + `prompt_evolution.enabled: true` + 锚点效用（`anchor.enabled: true`）+ `paper_self_preference` 对抗者 |

边际读法：**搜索价值** = B_archive_no_coevo − B0_paper_linear；
**协同进化价值** = B_full − B_archive_no_coevo。与此处各处一样，成本
只*报告*、从不拉平。

### 论文指标 P1–P5

由 `compute_metric_report(..., paper=True)`（`ari.rqgm.evaluation.metrics`、
`PAPER_METRIC_KEYS`）事后计算的五个指标，与探索指标形状相同
`{value, numerator, denominator, evidence_refs, applicable}`：

- **P1 接受率**（`paper_acceptance_rate`）—— 一个**固定的外部审稿人
  面板**在最终稿上的判定中落入 accept 集合的比例，事后计算。面板
  （`paper_eval_defaults.panel`：rubric `neurips/iclr/icml`、
  `num_reviews_ensemble: 3`、`seed: 41`）是一个应与协同进化的
  `paper_reviewer` 及锚点语料库**不相交**的钉定 rubric 集成，
  因此协同进化后的审稿人无法给自己的稿件抬分。对应 RQGM
  论文的接受率表。仅 Tier-3（真实 LLM）；绝不在 CI 中运行。
  > **尚未接线（截至 2026-07-17）。** 面板的**运行器尚未落地**：没有任何
  > 代码读取 `paper_eval_defaults.panel`，不相交性检查
  > （`conditions.panel_disjointness_violations`）也**没有生产调用方**，
  > 因此它目前**不是**"工具链的硬检查"。P1 只读取真实钉定面板运行所写的
  > 产物 `{ckpt}/panel_review_report.json`，缺失时返回 `applicable: false`
  > （今天的每一次运行都是如此）。此前它读取的是**循环内** `review_paper`
  > 的输出 `review_report.json`（对 *refine 前*草稿的评审，会被回送给
  > `paper_refine`），并把声明的面板规格盖在其上：这是把自我一致报告成
  > 不相交面板，正是 R1 指出的失效。该标记现在改为从面板文件自身记录的
  > provenance 推导，不一致则返回 `applicable: false`。
  > **在运行器落地前请勿报告 P1。**
- **P2 审稿人↔锚点一致度**（`reviewer_anchor_agreement`）—— 受治理审稿
  人与锚点真值在保留集上的一致度。**仅可观测**：事后计算，不读取任何
  运行状态，也永远不能提交任何东西（§5.8）。
- **P3 自偏好检测**（`paper_detection_rates`）—— 被注入的 AI 撰写论文中，
  审稿人拒绝或 `paper_self_preference` 对抗者标记（→
  `ValidatedAttackRecord`）的比例。
- **P4 声明门通过率**（`paper_gate_pass_rate`）—— 读取 Layer-0
  claim-evidence 门对最终稿自身的判定，不重算任何东西（该门是权威的，
  且永不被内核包裹）。
- **P5 论文成本**（`paper_cost`）—— 来自 `cost_trace.jsonl` 的论文阶段
  总 token/USD 及按纪元的明细。

### 论文故障注入 PI1–PI3

`scripts/rqgm_eval/failure_injections.yaml` 的增量 `paper_injections`
块中的三个确定性注入（经
`ari.rqgm.evaluation.injection.load_injection_specs` 加载），与探索集合
相同的 `FailureInjectionSpec` 形状与 `eval_*` 命名空间，另加一个增量的
`authorship` 字段：

- **PI1 —— 草稿过度声称**（`eval_pi1_draft_overclaim`，fixture，最小
  `B0_paper_linear`）。获胜的 `full_paper.tex` 断言一个既无 `% CLAIM`
  锚点又无证据节点的数字。确认确定性的 Layer-0 声明门在协同进化**之后**
  仍能捕获过度声称 —— 协同进化绝不软化该门。经
  `claim_gate.uncovered_numeric` / `claim_gate.missing_evidence` 以零延迟
  检出。
- **PI2 —— AI 撰写被接受**（`eval_pi2_ai_authored_acceptance`，fixture，
  `authorship: ai`，最小 `B_full`）。一篇冻结审稿人会接受的、带标签的
  AI 撰写论文；由 `paper_self_preference` 对抗者捕获（→
  `ValidatedAttackRecord`，`target_refs: [paper_reviewer_v1]`）。需要协同
  进化，故其最小条件为 `B_full`。
- **PI3 —— 审稿人纵容**（`eval_pi3_reviewer_leniency`，
  `scripted_component` `always_accept`，**仅 smoke 层**，最小 `B_full`）——
  **反共谋回归**，也是"对抗者本身就在审计网络之内、没有绝对统治者"这一
  支柱的直接实现。其通过条件是**控制**信号而非度量：其
  `target_component_id` 解析到现任 `paper_reviewer` 的
  `paper_self_preference` `ValidatedAttackRecord` ≥ `ATTACK_THRESHOLD`（2）
  → `classify_target` → 提交 → 一份 `impeachment_motion`（是攻击路径，经
  `governance.impeachment` / `adversary.paper_self_preference`，**而非**
  可靠度分数通道）。此处审稿人↔锚点一致度崩塌（P2）仅作可观测。

**诚实的限制 —— 请像读功能一样平实地读它们：**

- PI3 的目标绑定链之所以能触发，是因为真实的 `ValidatedAttackRecord`
  现在携带 `target_component_id`，而它在生产中**仅**为
  `paper_self_preference`（其目标 `paper_reviewer_v1` 是一个已注册的创始
  组件）解析。七个探索对抗者攻击的是 `generator` 撰写的工件，它们没有
  已注册组件，因此其弹劾链按设计保持惰性。
- 在默认 `rqgm.paper.epoch.rounds: 2` 下，边界**和**弹劾动议都会触发，但
  通往活跃审稿人哈希改变的 T1→T6 攀升**不会完成**（一次完整采用需要一个
  角色空位加约 5 个边界；协同进化 PROOF 测试把 `rounds` 提到 8）。默认的
  `B_full` 运行会行使该循环、对抗者与弹劾 —— 它不会见证活跃审稿人的
  改变。
- `B_full` 以锚点语料库为前提。即便开启 `anchor.enabled`，若未提供精选
  语料库，锚点会降级为"无门"，审稿人便未获锚点信任 —— 此时 `B_full`
  测量的是协同进化的*管道*，而非完全锚定的采用。
- 会降级一份真实过度接受归档草稿的相内惩罚被推迟；当前回合降级的是一个
  合成的问责节点。真正触发的是审稿人问责 / 协同进化通道。

## 运行方式

```bash
# Expand configs only (no runs):
python scripts/rqgm_eval/run_ablation.py --dry-run --conditions B0,B3,B8

# Paper-archive B-ladder (expands to paper.mode + rqgm.paper.* overlays;
# dry-run supported). --inject accepts the fixture PI1/PI2 here; PI3 is
# scripted_component and only loads under --smoke:
python scripts/rqgm_eval/run_ablation.py --dry-run \
    --paper-conditions B0_paper_linear,B_archive_no_coevo,B_full

# Offline smoke (stub components, seconds, no LLM) — the deletion-criteria
# smoke campaign:
python scripts/rqgm_eval/run_ablation.py --smoke --conditions B0,B3 --seeds 11

# Tier-3 real campaign (LLM cost; never in CI). Runs every benchmark in
# scripts/rqgm_eval/experiments/*.md per condition × seed; narrow the set
# with repeatable --experiment flags. --inject accepts FIXTURE ids only
# here (scripted_component specs are smoke-tier and refused outside
# --smoke):
python scripts/rqgm_eval/run_ablation.py --conditions B0,B3,B4,B6,B8 \
    --eval-id campaign_2026_07 \
    --experiment scripts/rqgm_eval/experiments/spmm_roofline.md \
    --inject "scripts/rqgm_eval/failure_injections.yaml:\
eval_inj_001_metric_gaming,eval_inj_002_overclaim,\
eval_inj_003_hallucinated_prior_art,eval_ctl_001_clean_baseline"
```

结果落入 `workspace/rqgm_eval/<eval_id>/`：每次运行的检查点位于
`runs/<condition>_s<seed>_<experiment>/`（合成 smoke 层不接受实验
文件，为 `runs/<condition>_s<seed>/`），展开后的配置位于
`configs/`，以及活动级的 `ablation_report.json` +
`ablation_report.md`（条件 × 指标中位数与配对差值）。

## 测试层级

- **Tier 1（CI 硬性）** —— `ari-core/tests/test_rqgm_eval_{conditions,metrics,
  injection,detection_fixture,doubles}.py`：纯 fixture，无 LLM。
- **Tier 2（CI 硬性，离线 smoke）** —— `test_rqgm_eval_smoke.py`：每个
  条件用合成的桩组件跑过真实的 Task 03/06/07 记录路径，数秒内完成。
- **Tier 3（手动）** —— 真实的 B0–B8 × 种子活动；缩减后的完成集合为
  {B0, B3, B4, B6, B8} 加上 B2-vs-B3 的 VirSci 对照。
