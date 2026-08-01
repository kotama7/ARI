---
sources:
  - path: ari-skill-paper-re/src/server.py
    role: implementation
  - path: ari-skill-paper-re/src/_paperbench_bridge.py
    role: implementation
  - path: ari-skill-paper-re/REQUIREMENTS.md
    role: doc
  - path: ari-skill-hpc/src/slurm.py
    role: implementation
last_verified: 2026-08-01
---

# C15: `ari-skill-paper-re` 実装計画

> 状態: Proposed。マスター計画は [00_master_plan.md](00_master_plan.md)。本書は一時計画であり、末尾の削除要件を満たしたら削除する。

## 1. 責務

paper/code bundle/rubricから、隔離された再現環境を構築し、Phase 1の実行とPhase 2のPaperBench-compatible gradingを行う。code取得は`ari.clone`、scheduler lifecycleは`ari-skill-hpc`、rubric生成は`ari-skill-replicate`の契約を利用する。

## 2. 現状と課題

- `fetch_code_bundle`、`build_reproduce_sh`、`run_reproduce`、`grade_with_simplejudge`を提供する。
- local、Docker、Apptainer、SLURM runnerを独自に実装し、core/coding/HPCのexecution boundaryと重複する。
- vendored PaperBenchへのpath injection、runtime monkey patch、instruction rewrite、salvage wrapperが多く、upstream versionとの対応表が必要である。
-長時間tool timeout、partial output、retry/idempotent skipが複雑である。
- generated `reproduce.sh`、network、credential、host path、resource requestをより強くpolicy制御する必要がある。

## 3. 目標契約

`ReproductionPlanV1`、`ReproductionRunV1`、`GradeReportV1`を定義する。Phase 1はinput bundle/rubric/environment/command/resource/artifact digestを記録し、Phase 2はrubric leafごとのevidence、judge provenance、negative control、varianceを保持する。submit型実行は短時間でhandleを返す。

## 4. 実装作業

| ID | 作業 | 成果物 |
|---|---|---|
| C15-01 | manifest/schema/version同期 | 4 tool、async、permission、timeout metadata |
| C15-02 | clone/execution/HPC adapterへ分離 | fetch、sandbox、schedulerの共通interface |
| C15-03 | reproduction plan schema | commands、dependencies、network、resources、expected artifacts |
| C15-04 | sandbox policy | read-only input、bounded writable output、secret-free env、network default deny |
| C15-05 | async state/idempotency | submit/poll/cancel、attempt ID、partial artifact |
| C15-06 | PaperBench adapter isolation | pinned upstream、patch inventory、conformance tests |
| C15-07 | grading evidence | leaf result、judge/raw response、negative control、independence |
| C15-08 | EAR/cassette handoff | executed bundle、logs、environment、grade report |
| C15-09 | failure corpus | timeout、OOM、missing dependency、GPU/FS mismatch、malicious script |

## 5. 受け入れ基準

- [ ] network/credentialなしを既定とし、必要能力はrubric/policyで明示する。
- [ ] timeout/cancel後にlocal process、container、scheduler jobを残さない。
- [ ] retryでpartial attemptを成功として誤認せず、attempt lineageを保持する。
- [ ] input bundleをread-onlyにし、出力差分を別artifactとして保存する。
- [ ] host/container/module/compiler/hardware/resource identityがrun recordに残る。
- [ ] PaperBench patchごとにupstream symbol/versionとconformance testがある。
- [ ] judge failure、negative control failure、schema mismatchをscoreから欠落させない。
- [ ] `pytest ari-skill-paper-re/tests -q` とsandbox/HPC integration fixtureがgreenである。

## 6. 削除要件

### 6.1 実装から削除する対象

| ID | 削除対象 | 置換先 | 最早phase | 削除gate |
|---|---|---|---|---|
| C15-D1 | `_run_reproduce_local/_docker/_apptainer/_slurm`の重複runner | common execution + C06 scheduler adapter | P3 |全substrate golden parity、direct process/sbatch caller 0 |
| C15-D2 |独自code bundle fetch/resolution | `ari.clone` resolver contract | P3 |GitHub/file/https fixture parity、digest一致 |
| C15-D3 | global `sys.path` vendor injection | isolated package/adapter loader | P3 |clean interpreter test、upstream import conformance |
| C15-D4 | upstream対応済みmonkey patch / instruction rewrite | pinned upstream APIまたはnarrow adapter | P6 |patch inventoryでobsolete、target version suite green |
| C15-D5 | `reproduce.sh`のhost unrestricted execution fallback | sandbox policy | P2 |malicious script corpus、explicit unsafe opt-inも禁止/承認化 |
| C15-D6 | implicit successを返すpartial/idempotent-skip path | attempt state machine | P3 |retry/partial failure tests |
| C15-D7 | legacy rubric runtime generation responsibility | C14 rubric input | P6 |workflow caller 0、V1 readerはsupport期間保持 |

### 6.2 削除の検証と復旧

各 deletion PR は `pytest ari-skill-paper-re/tests -q`、全substrate sandbox、timeout/cancel/retry、PaperBench conformance、対象referenceへの `rg` を実行する。旧runner/patch削除前commitとupstream pinをrollback基点にし、旧rubric/run artifact readerはsupport window中保持する。

### 6.3 計画書自身の削除

C15-01〜09、全受け入れ基準、C15-D1〜D7を閉じ、reproduction/sandbox/PaperBench patch inventoryを恒久文書へ移した後に削除する。
