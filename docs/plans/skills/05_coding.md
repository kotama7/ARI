---
sources:
  - path: ari-skill-coding/src/server.py
    role: implementation
  - path: ari-skill-coding/mcp.json
    role: config
  - path: ari-core/ari/container.py
    role: implementation
  - path: ari-core/ari/public/container.py
    role: implementation
  - path: ari-core/ari/execution.py
    role: implementation
  - path: ari-skill-hpc/ari_skill_hpc/execution_adapter.py
    role: implementation
  - path: docs/reference/execution_contract.md
    role: doc
last_verified: 2026-08-02
---

# C05: `ari-skill-coding` 実装計画

> 状態: Implemented。P6 の C05-D4 compatibility removal のみ待機中。マスター計画は [00_master_plan.md](00_master_plan.md)。本書は一時計画であり、末尾の削除要件を満たしたら削除する。

## 1. 責務

node workspace内のsource作成、file read、bounded process実行、structured measurement emissionを所有する。host/scheduler固有job lifecycleは`ari-skill-hpc`、汎用process isolation primitiveは`ari.public.container`が所有する。

## 2. 現状と課題

- `write_code`、`run_code`、`run_bash`、`emit_results`、`read_file`を提供する。
- private `_sandbox_preexec` / subprocess処理と`ari-core/ari/container.py`に重複がある。
- path containment、symlink、argument/shell、resource limitを一つのExecutionPolicyとして記録していない。
- stdout/stderrはtruncateされるが、完全logとdigestをartifactとして必ず残す契約ではない。
- `emit_results`のmeasurement schemaをtransform/evaluatorとversion共有する必要がある。

## 3. 目標契約

- `WorkspaceRef`で許可rootを固定し、全pathをrealpath/symlink-awareに検証する。
- `ExecutionRequestV1`はargv、cwd、env allowlist、timeout、resource limits、container digestを持つ。
- shellは必要時のみ明示し、structured argvを既定とする。
- `MeasurementRecordV1`はvalue、unit、metric identity、parameters、artifact refs、exit statusを持つ。
-完全stdout/stderrはartifact、LLM向けにはbounded summaryを返す。

## 4. 実装作業

| ID | 作業 | 成果物 | 状態 |
|---|---|---|---|
| C05-01 | tool schema / manifest同期 | canonical manifest、permission宣言 | 完了 |
| C05-02 | common executorへ移行 | `ari.public.execution` adapter、process-group cleanup | 完了 |
| C05-03 | workspace path policy | traversal/symlink/race test、atomic write | 完了 |
| C05-04 | resource / network / env policy | CPU/memory/proc/time、minimal env、optional network deny | 完了 |
| C05-05 | result/artifact envelope | full logs、source/input digest、container identity | 完了 |
| C05-06 | measurement schema統一 | evaluator/transform consumer migration | 完了 |
| C05-07 | cancellation/idempotency | timeout後orphan 0、retry時duplicate execution識別 | 完了 |
| C05-08 | local/container/HPC handoff fixtures | same requestのsubstrate別provenance | 完了 |

## 5. 受け入れ基準

- [x] `..`、absolute escape、symlink escape、TOCTOU fixtureを拒否する。
- [x] timeout/cancel後にchild/grandchild processが残らない。
- [x] 未宣言secret envがuser codeから見えない。
- [x] full logはartifactとして取得でき、LLM返却はsize上限を守る。
- [x] `emit_results`のunit/parameter/measurement区分をschema validationする。
- [x] container tagではなくdigestまたは明示unresolved statusを記録する。
- [x] retryで同じexecution identityが分かり、結果を別実験として二重計上しない。
- [x] `pytest ari-skill-coding/tests -q` とexecutor conformance testがgreenである。

検証結果は core execution/container 58件、coding 34件、transform consumer 47件、
HPC handoff 59件。generated schema/manifest/HPC contract drift、public API/MCP snapshot、
targeted Ruff も green。`network` 要求と実施結果は別フィールドで記録し、外部実行は
`external-unverified` のまま扱う。恒久仕様は
[`docs/reference/execution_contract.md`](../../reference/execution_contract.md)へ移した。

## 6. 削除要件

### 6.1 実装から削除する対象

| ID | 削除対象 | 置換先 | 最早phase | 削除gate |
|---|---|---|---|---|
| C05-D1 | private `_sandbox_preexec` / timeout cleanupの重複 | `ari.public.execution` | P3 |process tree parity、container/local tests |
| C05-D2 | unrestricted shell-first execution path | structured argv + explicit shell permission | P3 |全internal caller migration、negative command tests |
| C05-D3 | stdout/stderrだけをtruncateして完全証跡を失うpath | artifact-backed log | P2 |oversize fixtureでdigest復元 |
| C05-D4 | ad-hoc `emit_results` coercion / legacy key alias | `MeasurementRecordV1` migration | P6 |old checkpoint reader、producer caller 0 |
| C05-D5 | workspace外pathを許す互換fallback | strict `WorkspaceRef` | P2 |security test、必要なread-only mountをmanifest化 |

実施状況: C05-D1/D2/D3/D5 は削除済み。C05-D4 は canonical reader telemetry が
zero になるP6まで維持する。したがって旧flat projection/coercionと本計画書は現時点で
削除しない。

### 6.2 削除の検証と復旧

各 deletion PR は `pytest ari-skill-coding/tests -q`、path/symlink escape、process cleanup、secret propagation、container/local parity、対象referenceへの `rg` を実行する。旧executorを消す直前commitをrollback基点にし、MeasurementRecord migration readerはsupport window中保持する。

### 6.3 計画書自身の削除

C05-01〜08、全受け入れ基準、C05-D1〜D5を完了し、execution/measurement仕様を恒久referenceへ移した後に削除する。
