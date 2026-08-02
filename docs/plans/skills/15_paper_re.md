---
sources:
  - path: ari-skill-paper-re/src/server.py
    role: implementation
  - path: ari-skill-paper-re/src/_paperbench_bridge.py
    role: implementation
  - path: ari-skill-paper-re/REQUIREMENTS.md
    role: doc
  - path: ari-skill-hpc/ari_skill_hpc/scheduler.py
    role: implementation
last_verified: 2026-08-02
---

# C15: `ari-skill-paper-re` 実装計画

> 状態: Implemented — C15-01〜09完了。P6で残るupstream patchとV1 readerの削除gateのみ追跡する。マスター計画は [00_master_plan.md](00_master_plan.md)。本書は一時計画であり、末尾の削除要件を満たしたら削除する。

## 1. 責務

paper/code bundle/rubricから、隔離された再現環境を構築し、Phase 1の実行とPhase 2のPaperBench-compatible gradingを行う。code取得は`ari.clone`、scheduler lifecycleは`ari-skill-hpc`、rubric生成は`ari-skill-replicate`の契約を利用する。

## 2. 現状と課題

- `fetch_code_bundle`、`build_reproduce_sh`、`run_reproduce`、`grade_with_simplejudge`を提供する。
- local/containerは共通`ExecutionRequestV1`とprivate attempt executor、SLURMは共通HPC handoff/lifecycleを使う。
- vendored PaperBenchはexact commitと3件のpatch inventoryに固定し、恒久的なpath injectionとsource-mutating salvage wrapperを削除済みである。
- timeout/cancel、partial output、retry/idempotent replayはdigest-bound attempt state machineで記録する。
- generated `reproduce.sh`、network、credential、host path、resource requestはfail-closed policyで制御する。

## 3. 目標契約

`ReproductionPlanV1`、`ReproductionAttemptV1`、`ReproductionRunV1`、`GradeReportV1`を定義する。Phase 1はinput bundle/rubric/environment/command/resource/artifact digestを記録し、Phase 2はrubric leafごとのevidence、judge provenance、negative control、varianceを保持する。SLURM submitはC06 handle lifecycleを使い、外部run lifecycleはC16が所有する。

## 4. 実装作業

| ID | 作業 | 成果物 |
|---|---|---|
| C15-01 | 完了: manifest/schema/version同期 | 4 tool、permission、timeout metadata、v1.0.0 |
| C15-02 | 完了: execution owner統合 | `ari.clone`、共通execution request、C06 scheduler handoff |
| C15-03 | 完了: reproduction schema | plan/attempt/run/artifact JSON Schemaとdigest検証 |
| C15-04 | 完了: sandbox policy | read-only input、private bounded output、secret-free env、network default deny |
| C15-05 | 完了: state/idempotency | attempt lineage、verified replay、partial artifact、timeout/cancel reap |
| C15-06 | 完了: PaperBench adapter isolation | exact upstream pin、patch inventory、一時bootstrap、clean interpreter test |
| C15-07 | 完了: grading evidence | leaf result、judge/raw response、negative control、independence |
| C15-08 | 完了: artifact handoff | executed tree/log/environment/grade/tar digest |
| C15-09 | 完了: failure corpus | timeout、cancel、OOM、dependency、GPU/FS、malicious script |

## 5. 受け入れ基準

- [x] network/credentialなしを既定とし、必要能力はrubric/policyで明示する。
- [x] timeout/cancel後にlocal process、container、scheduler jobを残さない。
- [x] retryでpartial attemptを成功として誤認せず、attempt lineageを保持する。
- [x] input bundleをread-onlyにし、出力差分を別artifactとして保存する。
- [x] host/container/module/compiler/hardware/resource identityがrun recordに残る。
- [x] PaperBench patchごとにupstream symbol/versionとconformance testがある。
- [x] judge failure、negative control failure、schema mismatchをscoreから欠落させない。
- [x] paper-re + typed HPC consumer suiteがgreenである（259 passed, 3 skipped）。

## 6. 削除要件

### 6.1 実装から削除する対象

| ID | 削除対象 | 置換先 | 最早phase | 削除gate |
|---|---|---|---|---|
| C15-D1 (deleted) | `_run_reproduce_local/_docker/_apptainer/_slurm`の重複runner | common execution + C06 scheduler adapter | P3 |direct symbol/sbatch caller 0、全substrate fixture green |
| C15-D2 (deleted) |独自code bundle fetch/resolutionと危険なbroad overwrite | `ari.clone` + safe destination policy | P3 |file/registry fixture、digest/symlink/root拒否 |
| C15-D3 (deleted) | global `sys.path` vendor injection | exact-pin temporary package bootstrap | P3 |clean interpreterでbootstrap rootが`sys.path`に残らない |
| C15-D4 (retained) | upstream未対応の3 runtime adaptation | pinned narrow adapter | P6 |`paperbench_patches.json`でobsolete、target version suite green。owner=ARI maintainers、pin更新ごとに再評価 |
| C15-D5 (deleted) | unrestricted host fallback、mutable image/alias、source-mutating salvage | sandbox/immutable image/attempt policy | P2 |malicious/cancel corpus、unsafe opt-inなし |
| C15-D6 (deleted) | implicit successを返すpartial/idempotent-skip path | attempt state machine | P3 |retry/partial/tamper failure tests |
| C15-D7 (retained) | legacy rubric V1 reader | C14 V2 input + offline migration | P6 |workflow caller 0、v1.1でsupport usage再評価 |

### 6.2 削除の検証と復旧

各 deletion PR は `pytest ari-skill-paper-re/tests -q`、全substrate sandbox、timeout/cancel/retry、PaperBench conformance、対象referenceへの `rg` を実行する。旧runner/patch削除前commitとupstream pinをrollback基点にし、旧rubric/run artifact readerはsupport window中保持する。

### 6.3 計画書自身の削除

C15-01〜09と受け入れ基準は完了し、恒久仕様は
[`reproduction_contract.md`](../../reference/reproduction_contract.md)へ移した。
C15-D4/D7を客観gateで閉じるまで本計画はP6 ledgerとして保持する。
