---
sources:
  - path: ari-skill-replicate/src/generator.py
    role: implementation
  - path: ari-skill-replicate/src/auditor.py
    role: implementation
  - path: ari-skill-replicate/schemas/replication_rubric.schema.json
    role: schema
  - path: ari-skill-replicate/skill.yaml
    role: config
last_verified: 2026-08-01
---

# C14: `ari-skill-replicate` 実装計画

> 状態: Proposed。マスター計画は [00_master_plan.md](00_master_plan.md)。本書は一時計画であり、末尾の削除要件を満たしたら削除する。

## 1. 責務

paperからPaperBench-compatible reproducibility rubricを生成し、rubricの具体性、paper evidence、重複、検証可能性を独立auditする。実際の再現実行と採点は`ari-skill-paper-re`が所有する。

## 2. 現状と課題

- two-stage生成と低cost single-call互換pathがある。
- generatorとauditorを別modelにできるが、独立性とmodel fallbackをmachine-readableに保証していない。
- `execution_profile.extra_sbatch_args`は任意flag pass-throughであり、execution policyを迂回し得る。
- schema repair、LaTeX-in-JSON sanitize、invalid leaf pruneがあり、修復で意味が変わった範囲を明示する必要がある。
- manifest versionとpackage/runtime tool surfaceにdriftがある。

## 3. 目標契約

`ReplicationRubricV2`はpaper/input digest、prompt/model、generation strategy、node-level quote/evidence span、weight、verification command/artifact、execution requirementを持つ。auditはgeneratorとindependent groupを分け、修復・prune・warningをprovenanceへ残す。execution requestはtyped fieldだけを許可する。

## 4. 実装作業

| ID | 作業 | 成果物 |
|---|---|---|
| C14-01 | manifest/schema/version同期 | 3 toolとcanonical package version |
| C14-02 | Rubric V2 schema | evidence span、verification target、typed execution |
| C14-03 | generation provenance | prompt/model/seed/strategy/parallel subtree digests |
| C14-04 | independent audit contract | deterministic checks + separate LLM reviewer identity |
| C14-05 | repair transparency | original/raw、repair actions、dropped leaves artifact |
| C14-06 | resource request validation | scheduler policyに対応するtyped bounds |
| C14-07 | quality calibration | known papers、negative rubrics、coverage/precision metrics |
| C14-08 | paper-re handoff/version negotiation | supported rubric versions、migration fixture |

## 5. 受け入れ基準

- [ ] 全leafがpaper evidence spanまたは明示external prerequisiteを持つ。
- [ ] unverifiable、duplicate、vague leafをdeterministic auditが検出する。
- [ ] generator/auditorが同一backend/modelの場合、independent evidenceと表示しない。
- [ ] schema repair前後とdrop理由をartifactから監査できる。
- [ ] arbitrary scheduler flag、path、shell fragmentをrubricから注入できない。
- [ ] two-stage concurrencyがbudgetを守り、partial failureを欠落として記録する。
- [ ] paper-reがV1/V2 negotiationに失敗した場合fail closedする。
- [ ] `pytest ari-skill-replicate/tests -q` とcalibration corpusがgreenである。

## 6. 削除要件

### 6.1 実装から削除する対象

| ID | 削除対象 | 置換先 | 最早phase | 削除gate |
|---|---|---|---|---|
| C14-D1 | `execution_profile.extra_sbatch_args`の任意pass-through | typed scheduler fields / reviewed extension | P3 |allfixtures migrated、injection negative tests |
| C14-D2 |意味変更を記録しないsilent schema repair/prune | repair ledger + strict schema | P3 |raw/repaired/dropped artifact tests |
| C14-D3 |品質基準を満たさない`two_stage=False` public path | calibrated strategyまたは明示low-coverage profile | P6 |cost/quality gate、deprecation、consumer 0 |
| C14-D4 |V2移行後のV1 runtime generator | V2 generator + V1 reader | P6 |paper-re compatibility、support window |
| C14-D5 |manifest/packageのstale version declarations | canonical manifest | P1 |version/tools conformance |
| C14-D6 |同一modelを独立auditorとして扱うfallback | explicit independence policy | P3 |model outage test、honest status |

### 6.2 削除の検証と復旧

各 deletion PR は `pytest ari-skill-replicate/tests -q`、schema/calibration/injection corpus、paper-re version negotiation、対象referenceへの `rg` を実行する。旧rubric strategy/schema削除前commitをrollback基点にし、V1 readerはsupport window中保持する。

### 6.3 計画書自身の削除

C14-01〜08、全受け入れ基準、C14-D1〜D6を閉じ、rubric schema、calibration、migrationを恒久資産へ移した後に削除する。
