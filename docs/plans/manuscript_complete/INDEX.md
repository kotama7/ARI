# Manuscript Complete Plan Index

## Purpose

このディレクトリは、ARI の探索成果を「不足が説明可能で、証拠に拘束され、公開可否を
検証できる原稿入力」へ変換する **Manuscript Complete** 計画だけを管理する。

この計画群は次の既存計画群とは別の ownership boundary を持つ。

- `docs/plans/ari_rqgm/` — 研究探索の governance / Knowledge–Capability–Assurance。
- `docs/plans/ari_rqgm_paper/` — paper draft archive と paper-role co-evolution。
- `docs/plans/gui_refresh/` — GUI の全面刷新。

既存計画の task ID、進捗表、削除手順へ Manuscript Complete の task を追加しない。
既存計画へのリンクは integration dependency または参照であって、同一計画への編入を
意味しない。このディレクトリの計画を変更するときは、この `INDEX.md` とこの
ディレクトリ内の計画だけを更新する。

## Isolation rules

1. Manuscript Complete 固有の要求、契約、状態、実装段階はこのディレクトリを正本とする。
2. RQGM、paper archive、GUI の既存計画本文へ Manuscript Complete の詳細設計を追記しない。
3. 外部計画が未完了でも、依存しない audit-only work package は進行できるように分割する。
4. RQGM の探索方式、paper の執筆方式、KCA の posture は入力軸であり、この計画の task
   hierarchy ではない。
5. 実装後に恒久仕様へ移管するまでは、このディレクトリ外に重複した計画本文を作らない。

## Active plans

| ID | Plan | Status | Internal dependency | External integration dependency | Deletion status |
|---|---|---|---|---|---|
| 00 | [Manuscript Complete program plan](00_manuscript_complete_program_plan.md) | planned | none | RQGM 18/19; paper 07 | not deletable |
| 01 | [Baseline and decision freeze](01_baseline_and_decision_freeze.md) | planned | 00 | none | not deletable |
| 02 | [Contracts and deterministic compiler core](02_contracts_and_compiler_core.md) | planned | 00, 01 | none | not deletable |
| 03 | [Audit-only simple BFTS + linear vertical slice](03_audit_vertical_slice.md) | planned | 00, 01, 02 | none | not deletable |
| 04 | [Segmented pipeline and enforce gate](04_segmented_pipeline_and_enforce_gate.md) | planned | 00–03 | none | not deletable |
| 05 | [Research RQGM and KCA integration](05_rqgm_kca_integration.md) | planned | 00–04 | RQGM 18/19 | not deletable |
| 06 | [Paper RQGM archive integration](06_paper_archive_integration.md) | planned | 00–04 | RQGM-paper 01–07 | not deletable |
| 07 | [Explicit repair and resume](07_explicit_repair_and_resume.md) | planned | 00–04 | Task 05 only for KCA repair | not deletable |
| 08 | [Automatic repair and full topology](08_auto_repair_and_full_topology.md) | planned | 00–07 | none beyond dependencies | not deletable |
| 09 | [Publication lock, evaluation, migration, and documentation](09_publication_evaluation_migration_docs.md) | planned | 00–08 | authentic RQGM 18/19 certification where applicable | not deletable |

Status legend:

- `planned` — 設計は記述済みだが、実装または実行可能な証拠がまだない。
- `in progress` — 一部実装済みだが completion criteria を満たしていない。
- `implemented` — completion criteria の全項目に実行可能な証拠があり、必要な suite が green。
- `blocked` — 外部依存または人手判断が必要で、依存しない作業も残っていない。

## Dependency graph

```text
00 program plan
  -> 01 baseline / decisions
      -> 02 contracts / compiler
          -> 03 audit vertical slice
              -> 04 segmented pipeline / enforce
                  ├──> 05 Research RQGM / KCA
                  ├──> 06 Paper RQGM archive
                  └──> 07 explicit repair
                          05 + 06 + 07 -> 08 auto repair / full topology
                                              -> 09 publication / release closure
```

Tasks 05–07 は同じ基盤から分岐する。05 の authentic external certification が未完でも、
06 と 07 の KCA 非依存部分を止めない。Task 08 は三経路の合流点、Task 09 は program-wide
release/deletion handoff である。

## Orthogonal execution axes

Manuscript Complete は次の軸を結合するが、いずれも暗黙には有効化しない。

| Axis | Values | Default | Owner |
|---|---|---|---|
| Research exploration | `simple_bfts`, `ari_rqgm` | `simple_bfts` | `ari_rqgm` plans / current core |
| Paper authoring | `linear`, `rqgm_archive` | `linear` | `ari_rqgm_paper` plans / current paper runtime |
| Manuscript posture | `off`, `audit`, `enforce` | `off` | this plan |
| Repair posture | `disabled`, `explicit`, `auto` | `disabled` | this plan |
| Knowledge posture | `off`, `audit`, `enforce` | `off` | RQGM Task 16 |
| Capability posture | `legacy`, `audit`, `enforce` | `legacy` | RQGM Task 17 |
| Assurance posture | `off`, `audit`, `enforce` | `off` | RQGM Tasks 18/19 |

全 activation combination の解決規則は Task 00 が所有する。特に、
`paper.mode` は `ari.mode` を読まず、`manuscript.mode` もどちらかを暗黙に変更しない。

## External references

- [ARI-RQGM index](../ari_rqgm/INDEX.md)
- [Scientific Assurance and Harness Registry](../ari_rqgm/18_scientific_assurance_and_harness_registry.md)
- [RQGM Governance Integration](../ari_rqgm/19_rqgm_governance_integration.md)
- [RQGM paper index](../ari_rqgm_paper/INDEX.md)
- [Claim-gate handoff and evaluation](../ari_rqgm_paper/07_claim_gate_handoff_and_evaluation.md)

これらの status はこの index へ複製しない。外部依存の現在状態は各正本で確認する。

## Plan deletion procedure

計画ファイルは次の全操作が可能になった場合だけ削除する。

1. plan 自身の completion criteria を満たす。
2. plan 自身の deletion criteria を満たす。
3. normative contract を schema、公開 API、恒久 architecture/reference docs へ移す。
4. migration、rollback、operational runbook の恒久保守先を確定する。
5. この index の status と deleted plans table を更新する。
6. 削除理由を commit message に記載する。

実装未完了、CI failure、未解決の publication safety issue、downstream がこの plan だけを
仕様として参照している、または恒久文書への移管が済んでいない場合は削除しない。

## Deleted plans

| ID | Former plan | Deleted in | Reason |
|---|---|---|---|
| — | — | — | — |

## Current focus

最初の実装対象は Task 01 の baseline/decision freeze、その後 Task 02 の compiler core で
ある。Task 03 で `simple_bfts + linear + manuscript.audit + repair.disabled` の vertical
slice を作り、既存挙動を止めずに writer へ届かない情報、本当に取得されていない情報、
公開上利用できない情報を分離する。その証拠を基準に Tasks 04–09 を gate 順に進める。
