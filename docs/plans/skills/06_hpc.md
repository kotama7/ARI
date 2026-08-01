---
sources:
  - path: ari-skill-hpc/src/server.py
    role: implementation
  - path: ari-skill-hpc/src/slurm.py
    role: implementation
  - path: ari-skill-hpc/src/singularity.py
    role: implementation
  - path: ari-skill-hpc/mcp.json
    role: config
last_verified: 2026-08-01
---

# C06: `ari-skill-hpc` 実装計画

> 状態: Proposed。マスター計画は [00_master_plan.md](00_master_plan.md)。本書は一時計画であり、末尾の削除要件を満たしたら削除する。

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
| C06-01 | manifest / runtime / docs同期 | canonical tool list、async/permission metadata |
| C06-02 | scheduler protocol抽出 | local mock、SLURM local、SLURM SSH adapter |
| C06-03 | job request/handle/result schema | idempotency key、state machine、artifact refs |
| C06-04 | clean environment/export policy | explicit vars、module snapshot、secret redaction |
| C06-05 | SSH security | host-key verification、key scope、timeout、known-host policy |
| C06-06 | container job統合 | OCI/SIF digest、bind list、GPU/resource declaration |
| C06-07 | paper-re / OpenROAD consumer migration | duplicated executionをHPC APIへ移行 |
| C06-08 | heterogeneous platform fixtures | no-SLURM、A64FX、GPU、remote failure、shared FS |

## 5. 受け入れ基準

- [ ] submitが外側MCP timeout内にhandleを返し、poll/cancelがstate machineに従う。
- [ ] retryした同一requestが意図せずjobを二重submitしない。
- [ ] job script、module、env allowlist、container、input/output digestがEARに残る。
- [ ] SSH host key mismatchをfail closedし、secret key内容をlogしない。
- [ ] local/remote adapterで同じnormalized stateとerror taxonomyを返す。
- [ ] cancel/timeout後のscheduler jobとlocal processをreapする。
- [ ] paper-reが直接`sbatch`を呼ばずに同じgolden resultを得る。
- [ ] `pytest ari-skill-hpc/tests -q` とmock scheduler conformance suiteがgreenである。

## 6. 削除要件

### 6.1 実装から削除する対象

| ID | 削除対象 | 置換先 | 最早phase | 削除gate |
|---|---|---|---|---|
| C06-D1 | docs/manifestの非実装`run_bash` declaration | canonical runtime manifestまたは実在tool | P1 | tools/list conformance、consumer 0 |
| C06-D2 |各Singularity tool内の重複submit/status構築 | scheduler protocol + container request | P3 |local/remote/GPU parity fixture |
| C06-D3 | `--export ALL` または親env継承のfallback | explicit export policy | P2 |clean-env integration test |
| C06-D4 | paper-re内の独自SLURM execution | C06 API | P3 |paper-re golden parity、direct sbatch caller 0 |
| C06-D5 | host-key verificationを迂回するSSH mode | strict known-host policy | P2 |negative SSH suite、migration guide |
| C06-D6 | deprecated container-specific public aliases | generic container job capability | P6 |deprecation release、workflow/tool caller 0 |

### 6.2 削除の検証と復旧

各 deletion PR は `pytest ari-skill-hpc/tests -q`、mock scheduler、local/SSH/container、cancel/timeout、clean-env、対象referenceへの `rg` を実行する。scheduler adapterの旧実装直前commitをrollback基点にし、公開tool aliasはdeprecation期間中adapterとして復旧可能にする。

### 6.3 計画書自身の削除

C06-01〜08、全受け入れ基準、C06-D1〜D6を閉じ、scheduler/SSH/container運用を恒久文書へ移した後に削除する。
