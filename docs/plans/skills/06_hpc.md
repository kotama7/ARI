---
sources:
  - path: ari-skill-hpc/ari_skill_hpc/server.py
    role: implementation
  - path: ari-skill-hpc/ari_skill_hpc/contracts.py
    role: schema
  - path: ari-skill-hpc/ari_skill_hpc/scheduler.py
    role: implementation
  - path: ari-skill-hpc/ari_skill_hpc/slurm.py
    role: implementation
  - path: ari-skill-hpc/ari_skill_hpc/singularity.py
    role: implementation
  - path: ari-skill-hpc/mcp.json
    role: config
  - path: ari-skill-tool-registry/src/openroad_adapter.py
    role: implementation
  - path: ari-skill-tool-registry/src/openroad_hpc.py
    role: implementation
  - path: ari-skill-tool-registry/src/openroad_hpc_workspace.py
    role: implementation
last_verified: 2026-08-02
---

# C06: `ari-skill-hpc` 実装計画

> 状態: Active — core、paper-re、OpenROAD consumer移行完了。deprecated aliasのP6 cleanupを残す。マスター計画は [00_master_plan.md](00_master_plan.md)。本書は一時計画であり、末尾の削除要件を満たしたら削除する。

## 1. 責務

SLURMを初期backendとするscheduler job、remote SSH transport、container build/run job、platform capability probeを所有する。長時間処理はsubmit/poll/cancel handleで表し、paper reproductionやOpenROAD等のdomain componentはこのAPIを再利用する。

## 2. 現状と課題

- local / SSH `SlurmClient`、job submit/status/cancel、複数Singularity tool、platform probeがある。
- README/REQUIREMENTSとruntime tool surfaceに`run_bash`等のdriftがある。
- `ari-skill-paper-re`がSLURM、Docker、Apptainer、local timeout処理を独自実装している。
- job state、scheduler output、environment、module、container digestのprovenance schemaが共通化されていない。
- SSH credential、host key、exported environmentのpolicyをmanifestで表していない。

## 3. 目標契約

`JobRequestV1`、`JobHandleV1`、`JobResultV1`を定義する。handleはscheduler、cluster identity、job ID、submission digest、workspace/artifact scopeを持つ。backendは`submit/status/cancel/logs/result` capabilityを実装し、domain側は`sbatch`を直接組み立てない。

## 4. 実装作業

| ID | 作業 | 成果物 |
|---|---|---|
| C06-01 | 完了: manifest / runtime / docs同期 | canonical tool list、async/permission metadata |
| C06-02 | 完了: scheduler protocol抽出 | argv+stdin local mock、SLURM local、strict SLURM SSH adapter |
| C06-03 | 完了: job request/handle/status/result schema | durable idempotency claim、state machine、artifact/provenance refs、checked-in JSON Schema |
| C06-04 | 完了: clean environment/export policy | `--export=NIL`、explicit non-secret vars、module snapshot、親env/source禁止 |
| C06-05 | 完了: SSH security | RejectPolicy、explicit known-host/key scope、timeout、agent/user-key禁止 |
| C06-06 | 完了: container job統合 | SIF digest/size、typed bind、cleanenv/containall、GPU/resource declaration |
| C06-07 | 完了: paper-re/OpenROAD移行 | duplicated executionをHPC APIへ移行 |
| C06-08 | 完了: heterogeneous platform fixtures | no-SLURM、A64FX profile、GPU、remote failure、shared FS、timeout/reap |

## 5. 受け入れ基準

- [x] submitが外側MCP timeout内にhandleを返し、poll/cancelがstate machineに従う。
- [x] retryした同一requestがprocess restart後も意図せずjobを二重submitしない。transport結果不明時はclaimを残してfail closedする。
- [x] job request/script digest、module snapshot、env allowlist、container、input/output/log/provenance digestがsubmission/result recordに残る。
- [x] SSH host key mismatchをfail closedし、secret key内容をidentity/logへ含めない。
- [x] local/remote adapterで同じnormalized stateとerror taxonomyを返す。
- [x] cancelとcontrol-command timeoutをboundedにし、timeout時local processをkill/waitする。scheduler jobはSLURM walltime/cancelがreapする。
- [x] paper-reが直接`sbatch`を呼ばず、typed request/handle/logのgolden resultを得る。
- [x] paper-re handoffがmodule list、network isolation attestation、execution identity、
  policy equivalence/unmapped policy、scheduler result provenanceを保持する。
- [x] OpenROADがdigest-pinned container jobをtyped requestでsubmitし、cancel/log/provenanceを共通handleで得る。
- [x] `pytest ari-skill-hpc/tests -q` とmock scheduler conformance suiteがgreenである（54 tests）。

## 6. 削除要件

### 6.1 実装から削除する対象

| ID | 削除対象 | 置換先 | 最早phase | 削除gate |
|---|---|---|---|---|
| C06-D1 (deleted) | docs/manifestの非実装`run_bash` declaration | `ari-skill-coding.run_bash`またはcanonical HPC lifecycle | P1 | runtime `tools/list`に不在、HPC docs/manifest caller 0、manifest conformance green |
| C06-D2 (deleted) |各Singularity tool内の重複submit/status構築 | scheduler protocol + typed container request | P3 |local/remote/GPU parity fixture green、aliasはthin compilerのみ |
| C06-D3 (deleted) | `--export ALL/NONE` override、親env/`.env`再注入fallback | fixed `--export=NIL` + explicit literals/modules | P2 |clean-env/injection integration test、setup env key削除 |
| C06-D4 (deleted) | paper-re内の独自SLURM execution | C06 API | P3 |paper-re golden parity、direct sbatch caller 0 |
| C06-D5 (deleted) | `AutoAddPolicy`等host-key verificationを迂回するSSH mode | strict known-host + RejectPolicy | P2 |negative SSH suite、migration guide、implicit agent/key禁止 |
| C06-D6 | deprecated container-specific public aliases | generic container job capability | P6 |deprecation release、workflow/tool caller 0 |

### 6.2 削除の検証と復旧

各 deletion PR は `pytest ari-skill-hpc/tests -q`、mock scheduler、local/SSH/container、cancel/timeout、clean-env、対象referenceへの `rg` を実行する。scheduler adapterの旧実装直前commitをrollback基点にし、公開tool aliasはdeprecation期間中adapterとして復旧可能にする。

### 6.3 計画書自身の削除

C06-01〜08、全受け入れ基準、C06-D1〜D6を閉じ、scheduler/SSH/container運用を恒久文書へ移した後に削除する。
