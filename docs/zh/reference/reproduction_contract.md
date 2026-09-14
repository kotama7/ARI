---
sources:
  - path: ari-skill-paper-re/src/contracts.py
    role: implementation
  - path: ari-skill-paper-re/src/sandbox.py
    role: implementation
  - path: ari-skill-paper-re/src/server.py
    role: implementation
  - path: ari-skill-paper-re/paperbench_patches.json
    role: config
last_verified: 2026-08-16
---

# 复现实验与评分契约

`ari-skill-paper-re` v1.0 将不可变科学输入与每次 execution attempt 分离。只有当 score 绑定到已验证、
成功的 reproduction run，且请求的所有 judge run 均完成时，才能发布该 score。

检入的 JSON Schema 位于 `ari-skill-paper-re/schemas/`。运行
`python ari-skill-paper-re/scripts/sync_contracts.py` 可拒绝 schema drift。

## 记录与身份

| Record | 身份与用途 |
|---|---|
| `ReproductionPlanV1` | rubric、input tree、`reproduce.sh`、command、sandbox/image、timeout、resource request、expected artifact 与 policy 的 canonical digest。 |
| `ReproductionAttemptV1` | 一次 terminal execution，链接到 parent attempt 与 plan，包含 environment identity、确切 log/output-manifest digest、output-tree digest、missing artifact 和类型化 failure evidence。 |
| `ReproductionRunV1` | 有序且连续的 attempt lineage。只有成功 run 才选择一个成功 attempt。 |
| `GradeReportV1` | rubric/paper/run digest、judge identity 与 independence、全部 leaf evidence/raw response、run count、variance、negative control、call trace 和最终 validity。 |

每个 record 都拒绝未知字段，以及与 canonical finite-JSON payload 不匹配的 digest。artifact path 必须为
relative、不可 traversal，并在使用前验证 digest 与 byte count。

## Workspace 布局与 retry

对于 plan digest `<P>`，metadata 位于 caller 的 source tree 下：

```text
.ari-reproduction/
  <P>/
    plan.json
    input-manifest.json
    input/                         # content-addressed, read-only snapshot
    run.json
    attempts/
      0001-<attempt-id>/
        work/                      # private writable execution tree
        output-manifest.json
  latest.json                     # verified active run pointer
```

execution 绝不把结果写入 caller source file。symlink、non-regular output、超过 1 GiB 的文件及超过
8 GiB 的 tree 会从 private output 移除，并使 attempt 以 `filesystem-policy` 失败。
`reproduce.log` 采用原子写入。output manifest 记录每个新增、修改或删除的 path 及所有 policy incident。

重复执行成功 plan 时，会在重新验证 run、artifact 与 output tree 后进行 idempotent replay。重复执行
failed/timed-out/cancelled plan 会建立新 attempt，其 `parent_attempt_id` 指向前一个 attempt。修改
source、rubric、image、policy、resource 或 timeout 会建立不同 plan，而不会静默延长旧 lineage。

## Sandbox admission

| Substrate | Immutable identity | Default network denial |
|---|---|---|
| Docker | 完整本地 `sha256:<image-id>` 或 `name@sha256:<digest>` | `--network=none`；read-only root、受限 tmpfs、无 capabilities、no-new-privileges、PID limit |
| Apptainer/Singularity | 本地 regular non-symlink SIF（已 hash）或远程 `@sha256:<digest>` URI | isolated network namespace、clean environment、contained filesystem、无 home mount |
| Local | 记录 host/toolchain identity | 要求显式 administrator isolation attestation；否则必须显式选择 `network_policy=inherit` |
| SLURM | digest-bound 的公共 HPC handoff 加 scheduler/module/resource/runtime evidence | `deny` 要求 administrator isolation attestation；job 使用 `--export=NIL` 与显式 literal/module |

execution environment 从 minimal allowlist 构建，绝不复制 parent environment。
`network_policy=inherit` 记录为 unverified，不会表述为 isolation。timeout 与 cancellation 会终止完整的
local/container process group、强制移除 named Docker container，或在 terminalization 前取消 scheduler
handle。

`auto` 选择可用 substrate，但不会虚构 image 或弱化 policy。若所选 substrate 无法满足
immutable-image、network、GPU、scheduler 或 resource constraint，planning/execution 会显式失败。

## Grade validity

`grade_with_simplejudge` 要求以下各项全部成立：

- schema-valid rubric，且其 paper digest 与非空 supplied paper text 匹配；
- digest-verified 且状态为 `succeeded` 的 `ReproductionRunV1`；
- 请求的每个 judge run 完成；
- 原始 per-call 与 per-leaf response 已持久化；
- 完成的 negative control 低于配置 threshold。

judge/provider failure、schema mismatch、缺失/篡改/失败的 reproduction，或无法使用的 negative control
都会产生无科学 score 的 `status=failed`。若已完成 grade 的 negative control 超过 threshold，系统保留
observed score 供诊断，但标记为 `invalid-negative-control`，而不是 `valid`。跳过 control 也使用相同
invalid status。将 rubric generator model 复用为 judge 时报告 `not-independent`，不会冒充独立审计。

## PaperBench provenance 与 patch 删除

`paperbench_patches.json` 精确 pin 已审查的 upstream Git commit，并将每个剩余 runtime adaptation 映射到
upstream symbol、rationale 与 deletion gate。只有同时提供 `ARI_PAPERBENCH_PATH` 和匹配的
`ARI_PAPERBENCH_COMMIT`，且 Git 确认确切 identity 时才接受 override。package root 仅在 bootstrap 期间
暂时可见，随后从 `sys.path` 移除；pip-installed PaperBench 不是 fallback。

compatibility inventory 会有意持续缩小。v1.0 已删除：

- host-local sandbox fallback 与 `ARI_PHASE1_ALLOW_FALLBACK`；
- mutable default image 及 `pb-env` / `pb-reproducer` 的 `:latest` alias；
- `apptainer_image` tool argument 与 `ARI_PHASE1_SINGULARITY_IMAGE`；
- 修改 source 的 salvage wrapper 与 implicit `code_only` grading；
- 重复的 local/Docker/Apptainer/SLURM runner entry point。

剩余 PaperBench adaptation 会在其 inventory gate 针对 pinned upstream suite 通过后删除。没有 named owner、
removal release、migration test 与 fail-closed security review，不得重新引入 compatibility name 或 fallback。
