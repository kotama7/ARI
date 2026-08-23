---
sources:
  - path: ari-core/ari/config/__init__.py
    role: implementation
  - path: ari-core/ari/cli/manuscript.py
    role: implementation
  - path: ari-core/ari/cli/manuscript_repair_runtime.py
    role: implementation
  - path: ari-core/ari/cli/paper_dispatch.py
    role: implementation
  - path: ari-core/ari/manuscript/runtime.py
    role: implementation
  - path: ari-core/ari/manuscript/state.py
    role: implementation
  - path: ari-core/ari/manuscript/repair.py
    role: implementation
  - path: ari-core/ari/manuscript/segments.py
    role: implementation
  - path: ari-core/ari/manuscript/evaluation.py
    role: implementation
  - path: ari-core/ari/manuscript/contracts.py
    role: schema
  - path: ari-core/ari/pipeline/driver.py
    role: implementation
  - path: ari-core/ari/rqgm/paper_runtime.py
    role: implementation
  - path: scripts/evaluate_manuscript_complete.py
    role: implementation
  - path: scripts/run_manuscript_complete_release.py
    role: implementation
  - path: scripts/manuscript_complete_release_gates.json
    role: config
  - path: .github/workflows/manuscript-complete.yml
    role: config
  - path: ari-core/tests/test_manuscript_complete.py
    role: test
  - path: ari-core/tests/fixtures/manuscript_complete/factory.py
    role: test
last_verified: 2026-08-16
---

# Manuscript Complete 操作员运行手册

## 启用

默认行为与 legacy 完全一致：

```yaml
manuscript:
  mode: off
  profile: generic_empirical_v1
  repair:
    policy: disabled
```

用 `audit` 在不改变 writer 输入的前提下度量差距；用 `enforce` 在 authoring
之前停止。自动 repair 仅在 enforce 下有效：

```yaml
manuscript:
  mode: enforce
  profile: generic_empirical_v1
  brief_character_budget: 24000
  repair:
    policy: auto
    max_rounds: 2
    max_new_nodes: 8
    max_experiment_runs: 12
    max_llm_calls: 8
    on_exhaustion: block
```

环境变量覆盖项为 `ARI_MANUSCRIPT_MODE` 与 `ARI_MANUSCRIPT_REPAIR_POLICY`。
在 attempt 中途更改 profile、mode、workflow、KCA lock 或 authority 不会被
静默对账；请 compile 一次新的 attempt。

## 检查与显式 repair

```bash
ari manuscript compile CHECKPOINT --mode audit
ari manuscript status CHECKPOINT --fail-if-blocked
ari manuscript inspect CHECKPOINT --requirement MC-RP-002
ari manuscript inspect CHECKPOINT --lane contextual_negative
ari manuscript plan-repair CHECKPOINT --config CHECKPOINT/workflow.yaml
ari manuscript repair CHECKPOINT --request REPAIR_ID
```

`plan-repair` 不执行任何外部动作。`repair` 先记录它被 admit 的确切范围，
然后使用可 resume 的 research runtime。experiment 请求会变成一个 bounded
node，携带 request ID、requirement ID、source context、固定变量与允许的变更。
配置了 RQGM 与 KCA hook 时它们照常运行。完成与否只由一次全新的
context/readiness compile 判定，绝不由 executor 的 exit code 判定。

projection 与 artifact 的重建可能完全不消耗 experiment 预算。retrieval 记录在
`related_refs.json` 中。disclosure 会创建 `manuscript_disclosures.json`，但它
始终只是一份 disclosure，而不是事实性的证据。需要由人做出的 method 与 policy
决定保持为 `human_required`。

`ari paper` 有意不带 research executor。若某个已有检查点需要一次 experiment
repair，请使用 `ari resume` 或上面的显式命令。

## Resume 与恢复

segment 记录与 request transaction 是 immutable 的。重启时，fresh 的 completed
segment 会被复用。已经 commit 的 repair request 不会被再次调用；
协调器会先重建证据并重新评估。node/run/call 的累计用量从 transaction 记录
中恢复。

自动循环总会停止，而且恰好因为一个原因而停止。该原因是循环返回值上的
`termination_reason`，它不会被持久化。只有部分停止还会在 transition 链上
留下记录：终止 transition `automatic_repair_<reason>` 只有在其目标 state 是
存储当前所持 state 的合法后继时才会被追加。被追加时，它以 digest 引用该
attempt 的 `readiness.json`，未解决的 requirement 在那里仍可读。
node/run/call/resource 的累计用量由 `auto-rounds/` 下每一条已 commit 的
round 记录携带。

| Termination reason | 条件 | 目标 state | 是否追加到链上 |
|---|---|---|---|
| `authoring_ready` | readiness 达到 `ready` 或 `ready_with_disclosures` | 无 | 否；继续 authoring |
| `no_admitted_repair_request` | compile 没有产出 readiness 报告、没有产出 repair plan，或产出的 plan 没有 request | `blocked_unavailable` | 是，除非 compile 已经写入了 `blocked_unavailable` |
| `human_decision_required` | 没有 request 被执行或满足，且至少有一个返回 `human_required` | `blocked_unavailable` | 是 |
| `required_resolver_unavailable` | 没有 request 被执行或满足，且没有任何一个是 `human_required` 或 `exhausted` | `blocked_unavailable` | 是 |
| `cumulative_budget_exhausted`（一轮之后） | 没有 request 被执行或满足，且有一个报告 `exhausted` | `repair_pending` | 是 |
| `cumulative_budget_exhausted`（一轮之前） | 恢复出的用量超过 `max_new_nodes`、`max_experiment_runs`、`max_llm_calls` 或 `max_resource_units` | `repair_pending` | 否 |
| `round_budget_exhausted` | 已 commit 的 round 记录达到 `repair.max_rounds` | `repair_pending` | 否 |
| `no_progress_cycle` | 相同的 source context digest 与相同的 requirement-status 向量再次出现 | `repair_pending` | 否 |

最后三行是常见的非 ready 停止，而它们都不会被记录。它们中断的位置上，上一次
compile 已经写入了 `repair_pending`，而 `repair_pending` 不是它自身的合法
后继，所以什么都不会被追加。不要在链上 grep
`automatic_repair_no_progress_cycle` 或
`automatic_repair_round_budget_exhausted`；它们永远不会被写入。请从循环的
返回值读取这些停止，或者从 `auto-rounds/` 下已 commit 的 round 记录与该
attempt 的 `readiness.json` 重建它们。为它们持久化原因这件事已被设计但尚未
实现：`ManuscriptAutoRepairRoundV1` 携带 round、它的 plan 与 source context
digest、它的 request ID 与 transaction digest、每个 request 的结果，以及已用
预算，但没有 termination reason 字段，也没有任何其他 artifact 记录它。

「没有进展」只依据 source context digest 与 `(requirement_id, status)` 向量
来判定。改写措辞的正文、一份新 draft、换个说法的摘要都不算进展；只有变化了的
证据才算。由于终止 transition 只在从当前 state 出发合法时才追加，一个已停止的
循环绝不会改写 compiler 已经拥有的 state。

崩溃可能恰好落在一条已 commit 的 round 与它的证据重建之间。下一次调用时，
循环会认出当前 plan digest 已经有一条已 commit 的 round 记录，并且只把该轮
关闭一次：它重新执行证据重建并重新 compile，完全不调用任何 resolver。若重新
compile 得到的 context digest 与 requirement-status 向量没有变化，这次对账会
以 `no_progress_cycle` 终止，而不是开始第二个完全相同的 round。

同一条规则在下一层同样成立。transaction 已经 commit 的 request 会直接从那条
记录重放，不调用 executor，不计入新的预算，并被标记为携带原始计费额度的幂等
复用。已经记录在 `related_refs.json` 中的文献 retrieval 会按 request digest
匹配并复用，这正是「provider 调用之后、transaction 记录之前」发生崩溃时的
幂等边界：resume 不需要任何 provider 调用，也不会发出重复查询。

若一次运行停在 `repair_pending`，请检查未解决的 requirement 与预算。
`blocked_unavailable` 需要一个被 admit 的 capability、Harness 或人的决定；
不要删除 state 文件。出现 `no_progress_cycle` 之后，请通过一次被明确授权的
操作来改变 source 证据，否则将继续保持 block。

若 transition 链或 immutable artifact 受损，请为审计保留 `.ari-manuscript/`，
并开启一个新的检查点/attempt。不要编辑 digest 字段，也不要就地替换某个
attempt 文件。

对于 `paper.mode: rqgm_archive`，请检查
`paper_archive_state.json.manuscript_authoring` 以及
`paper_draft_archive.jsonl` 上的 Manuscript 字段。`manuscript_bound_winner`
表示 archive 的 winner 使用了当前的固定 bundle。`bound_linear_fallback` 表示
archive 生成失败，但 linear backend 消费了同一个 bundle。
`audit_legacy_archive_winner` 与 `audit_legacy_linear_fallback` 明确地不是
Manuscript Complete 的 authoring。`stale_detected` 或
`authoring_backend_failed` 不得通过编辑 state 来清除；请 compile 一次新的
attempt，或用原始的 immutable bundle 来 resume。是否 stale 在 archive 的第一次
writer 调用之前就已判定，且判定范围不止 fingerprint 变化：`stale_reasons` 会
记录 `input_fingerprint_changed`；当同一个 durable archive 之前是在不同的
`manuscript.mode` 下被驱动时记录 `manuscript_mode_changed`；当 draft 已经存在
却从未为它们写过 `manuscript_authoring` 块时记录
`preexisting_archive_has_no_binding_state`；并为第一个携带不同 fingerprint 的
已归档 draft 记录 `draft_binding_mismatch:<epoch_id>:<node_id>`。在 enforce 下，
任何一个原因都会让运行在下一次 writer 调用之前停止。在 audit 下，这些原因会
被记录，本次调用的 archive 续跑会被跳过，运行降级为 linear pipeline，因此审计
面是被保留的 `stale_reasons`，而不是 status —— status 此时会变成
`audit_legacy_linear_fallback`。所以，在 archive 已经跑过的检查点上把
`manuscript.mode` 从 `audit` 切到 `enforce`，是一次被 block 的 resume，而不是
静默升级；请 compile 一次新的 attempt。`verification_or_fallback_failed` 表示
bundle 已被消费，但共享的 verification 尾段（或 linear fallback 本身）抛出了
异常；请读取 `failure_reason`，以及在已经记录过 best-belief winner 时读取
`winner_id` 与 `winner_tex_sha256`。`bound` 与
`audit_legacy_authoring_observed` 根本不是 outcome：它们在 archive 生成任何
东西之前就已写入，enforce 下写 `bound`，audit 下写
`audit_legacy_authoring_observed`，所以仍然停留在其中之一的检查点，是在其
outcome 被记录之前就停止了 —— 应把它读作一次被中断的运行，而不是一个结果。
archive 生成失败会产生哪个 outcome，由 manuscript mode 与调用方传入的
fallback 固定，绝不由导致失败的异常决定。在 `manuscript.mode: off` 下，
archive 保持它 legacy 的 fail-open 姿态：错误被记录到日志，运行降级为普通的
linear paper pipeline，并且完全不写 `manuscript_authoring` 块。在 `audit` 下
它降级并记录 `audit_legacy_linear_fallback`。在 `enforce` 下，它只能降级到一个
被明确标记为「消费同一个已验证 binding」的 fallback；只要 manuscript 这一轴
开启，`ari run`、`ari resume` 与 `ari paper` 都会传入一个带标记的 fallback，
所以 enforce 下的 archive 失败会落在 `bound_linear_fallback` 上；而
`authoring_backend_failed` 是当 archive runtime 被直接以未标记的 fallback
驱动时的 fail-closed outcome —— 什么都不会被撰写，运行随即停止。在 enforce
之内，没有任何设置可以在「降级」与「停止」之间做选择 —— 那只由标记决定；而
`manuscript.mode`、`manuscript.profile`、`manuscript.brief_character_budget`
与 `manuscript.repair.*` 就是 manuscript 配置面的全部。一个没有产出任何
admissible 候选的 archive round，本身就是一次 archive 失败，走同一条路径。
被 hard-disqualify 的 draft 会为审计保留，并且绝不可能通过提高其 reviewer
分数而被选中。

## Publication

```bash
ari manuscript explain-publication CHECKPOINT
ari manuscript lock-publication CHECKPOINT
```

lock 命令会重新哈希所有 source、bound 的 manuscript 输入、PaperBuild artifact、
reproduction 证据以及最终 PDF。决定之后的任何变化都会返回非零结果，并且不写
任何 lock。

### 读取一次决定

`explain-publication` 会打印 attempt ID、决定及其 digest、PaperBuild digest，
以及每一个 sub-verdict —— 它的 gate、它的 `pass`/`fail`/`not_required`
status、它的 reason code，以及它记录的 artifact digest。reason code 只为失败的
gate 写入，而 `freshness` gate 根本不携带 artifact digest。只要决定不是
`publishable`，该命令就以 `2` 退出，因此在脚本中它可以当作一道闸门来读。

没有 `publication_decision.json` 的 attempt 会被报告为
`decision: not_evaluated`、`reason: publication_decision_missing` 并附上
attempt ID，同样以 `2` 退出。那不是一个被 block 的决定 —— 而是什么都没有被
评估。决定由 paper pipeline 自身写入，写在一次运行的尾段，该运行的 manuscript
轴处于开启状态，且其阶段列表包含 `lock_paper_build` 或 `ors_run_reproduce`；
此外，当 `paper_build.json` 不存在，或 context、readiness、binding 的路径变量
未设置时，finalizer 也会不写任何东西就返回。因此缺少决定意味着那段尾段从未
运行过。请在 `audit` 或 `enforce` 下重新运行 pipeline；不要手写该文件。

### lock 为何被拒绝

`lock-publication` 不写 `publication_lock.json`，而是报告 `locked: false`、
attempt ID 和一个 `reason` 字符串，并以 `2` 退出。各项检查按下表顺序执行，
第一个失败的即为被报告的 reason。

| `reason` | 原因 |
|---|---|
| `publication lock requires an exposed authoring binding` | 该 attempt 的 `authoring_binding.json` 缺失，或其路径离开了检查点、或经过了 symlink |
| `blocked publication decision cannot be locked` | 记录的决定是 `blocked` |
| `publication decision no longer names the current build` | 决定中的 PaperBuild digest、authoring-binding digest、run ID 或 attempt ID 与当前的 `paper_build.json` 及 binding 不一致 |
| `publication attempt is not finalized` | manuscript state 文件指向了另一个 attempt，或其 state 不是 `finalized` |
| `publication inputs changed after decision` | 某个被 snapshot 的 source、某个嵌套的 PaperBuild artifact，或某个 bound 的 manuscript 输入不再与其记录的 digest 和大小相符 |
| `publication reproduction evidence is stale` | `reproduction` sub-verdict 不是 `pass`，或 `ors_phase1.json` 缺失、经由 symlink 到达、或不再哈希成该 sub-verdict 记录的 digest |
| `publication build does not identify one final PDF` | build 的 final artifact 中 `pdf` role 为零个或多于一个 —— 只有在完全没有 final PDF 时，单个 compile PDF artifact 才可替代 |

freshness 这一行是七项中覆盖面最广的。以下情形同样会失败：snapshot 记录为
`missing` 的 source 现在却存在；带路径的 source 既无 digest 也无大小，因而没有
稳定的字节身份；build 为同一个 artifact role 与路径声明了两个不同的身份；或者
那五个 bound 的 manuscript 输入 —— requirement profile、context、readiness、
section brief、authoring binding —— 并不恰好是 build 在这些 role 下记录的
attempt 目录文件；或者它们的 profile/context/readiness/brief digest 谱系不再
一致；或者被 bound 的 readiness 报告的 authoring verdict 既不是 `ready` 也不是
`ready_with_disclosures`。上述任一路径若经由 symlink 到达，同样会以相同方式
失败。

格式错误或读不出的 contract 文件会以完全相同的方式呈现：底层的 `OSError` 或
schema 校验错误成为 `reason`，退出码仍为 `2`。

只有 `enforce` 会写入 `finalized` state，因此在 `audit` 下产生的决定是一个
shadow decision：`explain-publication` 会读取它，而 `lock-publication` 会以
未 finalized 为由拒绝它。这是刻意为之的 audit 姿态，而不是缺陷。

这里的任何拒绝都不会因为编辑某个 state 字段或某个 digest 而被清除。请重新
compile 一个新的 attempt，或用原始的 immutable bundle 来 resume。

## 回滚、隐私与留存

把 `manuscript.mode: off` 设上，即可让后续调用回到 legacy 路径。这并不会抹除
先前的 attempt。`.ari-manuscript` 可能包含研究问题、失败结果摘要、路径、
provider 身份以及绑定到模型的 brief；请按该检查点的数据密级来对待它。
authority 快照包含身份与 digest，绝不包含凭据值；`ari-core/ari/manuscript/authority.py`
中的 `capture_repair_authority` 记录的是相对路径、digest、大小与 mode 名称，其
校验器会拒绝任何没有声明自身不含凭据材料的快照。这是今天在代码中被强制执行的
唯一一处实例。规则本身更宽，它约束今后的代码可以写入什么：不得把原始 secret、
provider 凭据、没有边界的源字节区间，或未脱敏的环境值放进 `.ari-manuscript/`
命名空间，该命名空间只承载身份、digest 与有边界的 brief。对某个检查点做脱敏或
删除，只能走与其 research artifact 相同的留存流程。

## 发布评估

带标注的 fixture campaign 可以归约为那份永久的报告契约：

```bash
PYTHONPATH=ari-core python scripts/evaluate_manuscript_complete.py \
  evaluation-cases.json --output manuscript-evaluation.json
```

输入是一个 JSON 列表（或一个带 `dataset_id` 与 `cases` 的对象）。没有适用
case 的比率保持为 `not_applicable`；请把该报告与用于发布决定的 topology、
failure-injection 以及真实 Harness 证据一并留存。

对于裸 JSON 列表，请传入 `--dataset-id DATASET_ID`。七个合成 baseline 类由
`ari-core/tests/fixtures/manuscript_complete/factory.py` 生成；用下面的命令
重新生成并校验它们：

```bash
PYTHONPATH=ari-core pytest -q \
  ari-core/tests/test_manuscript_complete.py::test_baseline_fixture_classes_are_executable \
  ari-core/tests/test_manuscript_complete.py::test_executable_fixture_expectations
```

生成出的值仅供测试使用，并带有 `SYNTHETIC_FIXTURE.json`；它们不是留存的科学
证据或 Harness 证据。

## 发布闸门与留存的 CI 证据

只能从一个干净的、已提交的修订上运行这份封闭的发布清单。请把输出放在
worktree 之外：

```bash
release_dir="$(mktemp -d)"
PYTHONPATH=ari-core python scripts/run_manuscript_complete_release.py \
  --output-dir "$release_dir" --require-clean --keep-going
```

报告是 `release_evidence.json`；每项检查的 stdout/stderr 留存在 `logs/` 下，
并以报告中的某个 digest 命名。它覆盖 4 种 topology 的 publication E2E、全部
13 个 failure-injection 族、追加式的 legacy migration/rollback、永久的
schema/snapshot/docs 检查、paper/tool-registry 集成，以及已签入的真实 native
Harness publication 链。

Pull request 通过 `.github/workflows/manuscript-complete.yml` 以
`--require-ci` 运行同一份清单，并把 artifact 留存 90 天。源修订不干净的本地
报告，或使用 `--require-ci` 时产生于 GitHub Actions 之外的报告，都被刻意判定
为不满足 `release_eligible`。合成 topology fixture 只能证明接线与失败姿态；
真实的 certification 仍然是单独留存在 `ari-core/config/harnesses/evidence/`
下的 native Harness 证据。

### `release_eligible` 意味着什么、不意味着什么

只有当清单中的每一项检查都运行并通过、源修订是干净的，并且 —— 在
`--require-ci` 下 —— 该次运行发生在 GitHub Actions 内部时，`release_eligible`
才为真。这三个条件就是它的全部。它是发布的必要条件，而不是发布决定本身。

有两条判据留给人，并且在清单与报告中都没有任何编码：没有任何未解决的
critical 或 high 级 publication-safety issue 处于打开状态；以及某位操作员已
评审过 blocked、预算耗尽与人工决定这几条流程。请把两个答案记录在留存报告
旁边，好让后来的读者看到它们确实被问过。

发布范围也以同样的方式、在报告之外决定。只有在存在与之对应的真实留存证据
的范围内，才可以把某项 capability 描述为 supported。缺少该证据的 Harness
范围保持 unsupported 且 blocked，并被记录为 unsupported；它不会否决那些已被
覆盖范围的发布，但也绝不能在发布说明、文档或论文中被宣传为已实现。
`release_evidence.json` 中没有任何东西会检查上述任何一条 —— 约束的是为这次
发布签字的人。

### 故障注入阻断矩阵

只有当缺陷确实*阻断*时，一次注入才算被满足。若缺陷被记录下来而 publication
仍然能够 lock，那是一次测试失败，而不是一条警告。因此每个被注入的故障都要
指明必须读作 `fail` 的那个 sub-verdict，以及流程停止的位置。

| 被注入的故障 | 失败的 sub-verdict |
|---|---|
| 在 build 记录写入之后移除最终 PDF | `freshness` |
| 移除 `ors_phase1.json` | `reproduction` |
| 最终 TeX 中缺少一条必需的 disclosure | `claim_evidence` |
| 最终 TeX 中把某个 contextual-negative 证据 ID 当作支持来引用 | `claim_evidence` |

每一行的停止方式都完全相同：publication 决定为 `blocked`，被指明的
sub-verdict 为 `fail`，lock 会抛出异常而不写入任何东西，且 attempt 目录下不
存在 `publication_lock.json`。在 CLI 上，这表现为
`ari manuscript lock-publication` 以 `locked: false` 和拒绝原因、退出码 `2`
结束。这四行由一个参数化测试统一负责，即
`ari-core/tests/test_manuscript_complete.py::test_publication_failure_injection_matrix_blocks_before_lock`，
`missing-finalizer-artifact` 与
`contextual-negative-used-as-positive-support` 这两个注入族都指名了它。

十三个族的完整集合，以及负责每一个族的测试，都在
`scripts/manuscript_complete_release_gates.json` 中。发布 runner 会在执行任何
东西之前先校验这份清单：未知的 schema 版本、不恰好是四个唯一 ID 的 topology
列表、不等于十三的族数量、重复的族 ID 或 check ID、缺少 `argv` 的 check，或者
某个指名的测试其函数已不再存在于代码树中，都会中止本次运行，而不是产出一份
报告。
