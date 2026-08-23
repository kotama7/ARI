# Manuscript Complete Plan Index

## Purpose

このディレクトリは、ARI の探索成果を「不足が説明可能で、証拠に拘束され、公開可否を
検証できる原稿入力」へ変換する **Manuscript Complete** 計画だけを管理する。

この計画群は次の既存計画群とは別の ownership boundary を持つ。

- `ari_rqgm` 実行モードの governance / Knowledge–Capability–Assurance。恒久仕様は
  [Constitutional ARI-RQGM Architecture](../../concepts/rqgm_architecture.md) と
  [Knowledge, Capability, and Scientific Assurance](../../reference/knowledge_capability_assurance.md)。
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

Status column re-checked against the tree on 2026-08-16 (229 commits after the
2026-08-06 revision cited below), by re-running each plan's own completion criteria
rather than by re-reading the 2026-08-06 record.

| ID | Plan | Status | What settled it | Internal dependency | External integration dependency | Deletion status |
|---|---|---|---|---|---|---|
| 00 | [Manuscript Complete program plan](00_manuscript_complete_program_plan.md) | in progress | §25.20/§25.23 want every applicable Harness suite green, and `test_production_harness_evidence.py::test_production_native_harness_catalog_is_verified_and_closed` fails at HEAD | none | RQGM 18/19; paper 07 | not deletable |
| 01 | [Baseline and decision freeze](01_baseline_and_decision_freeze.md) | implemented | all seven fixture classes materialise from checked-in manifests and MC-ADR-001–009 live in `docs/adr/manuscript_complete/` | 00 | none | not deletable |
| 02 | [Contracts and deterministic compiler core](02_contracts_and_compiler_core.md) | implemented | determinism/tamper and omission-conservation tests green, and both the schema-sync and contract-snapshot checks report in sync | 00, 01 | none | not deletable |
| 03 | [Audit-only simple BFTS + linear vertical slice](03_audit_vertical_slice.md) | implemented | `manuscript.mode` still defaults to `off` in code, and the off-identity, idempotence and read-only CLI tests are green | 00, 01, 02 | none | not deletable |
| 04 | [Segmented pipeline and enforce gate](04_segmented_pipeline_and_enforce_gate.md) | implemented | segment freshness, brief binding without silent omission, and exact off-mode identity are green | 00–03 | none | not deletable |
| 05 | [Research RQGM and KCA integration](05_rqgm_kca_integration.md) | in progress | §11.9 keeps this task open until authentic 18/19 evidence stands; the live catalog will not load and the persisted certify→publication chain is pinned to a superseded `hpc/gemm-performance` report digest | 00–04 | RQGM 18/19 | not deletable |
| 06 | [Paper RQGM archive integration](06_paper_archive_integration.md) | implemented | one-bundle input, hard disqualification before utility, unbound-fallback rejection, and the off-mode paper suite are green | 00–04 | RQGM-paper 01–07 | not deletable |
| 07 | [Explicit repair and resume](07_explicit_repair_and_resume.md) | implemented | fixed identity/budget, digest-bound commits, non-repeating resume, and no-progress/human-stop termination are green | 00–04 | Task 05 only for KCA repair | not deletable |
| 08 | [Automatic repair and full topology](08_auto_repair_and_full_topology.md) | implemented | auto mode is refused outside `enforce` and the four-topology E2E is green; none of its criteria rests on the certification that holds 05 open | 00–07 | none beyond dependencies | not deletable |
| 09 | [Publication lock, evaluation, migration, and documentation](09_publication_evaluation_migration_docs.md) | in progress | §13.7/§13.9 want authentic certification for every advertised enforce scope, and the `authentic-production-harness` release check is red at HEAD (8 of 9 pass) | 00–08 | authentic RQGM 18/19 certification where applicable | not deletable |

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

- [Constitutional ARI-RQGM Architecture](../../concepts/rqgm_architecture.md) — RQGM の三層構造、
  epoch cycle、fixed kernel、Registry Transition Engine、および
  "Knowledge, Capability, and Assurance separation" 節が持つ Research Contract から
  certification-bound publication までの連鎖。
- [Knowledge, Capability, and Scientific Assurance](../../reference/knowledge_capability_assurance.md) —
  "Run admission and frozen identities" 節の admission 順序と凍結される identity、
  "Verification, Harnesses, and Attestations" 節の Verification Contract、Harness kind、
  Resolver、Fixed Verifier、Attestation、native/external Harness の registration、
  "Surfaces and administration" 節の CLI / dashboard / MCP surface。
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

2026-08-06 時点で Tasks 00–09 の completion criteria に実行可能な証拠があり、
closed release manifest、4 topology E2E、13 failure-injection family、legacy
migration/rollback dry run、authentic native Harness publication evidence は PR head
`5f413c73d6f9c94cbf3135871325623cc7805631` に commit されている。GitHub Actions の
retained release artifact も `release_eligible=true` であった。

2026-08-16 に同じ criteria を HEAD で再実行した結果、この評価は全 task には
もう当てはまらない。release manifest の 9 checks のうち 8 つは green だが、
`authentic-production-harness` だけが red である。`hpc/gemm-performance` の
registration report が、tree にある manifest の digest を bind していないため
live catalog が load できない。この 1 点に status が依存する Tasks 00、05、09 は
`in progress` へ戻し、依存しない Tasks 01–04、06–08 は `implemented` のままとする。
現在の焦点はこの catalog の不一致の解消、続いて merge/release review と post-merge の
deletion-readiness review である。authentic Harness は synthetic fixture で代用しない。

## Implementation evidence (2026-08-06)

| Gate | Executable evidence | Remaining before deletion |
|---|---|---|
| G0–G2 | seven generated fixture classes; digest-bound compiler/readiness/omission contracts; off/audit CLI and idempotence tests | main/release merge and post-merge deletion review |
| G3 | additive evidence/authoring/verification segments; stale-safe records; enforce pre-authoring gate; exact off identity tests | main/release merge and post-merge deletion review |
| G4 | RQGM node/frontier/attestation projection plus checked-in verified native GEMM/SpMM/Stencil registration, parity, negative controls, and certify→publication chain | main/release merge and post-merge deletion review |
| G5 | common archive fingerprint; writer/reviewer/draft provenance; contextual-negative/forbidden/disclosure hard disqualification; exact winner handoff; stale/bound fallback tests | main/release merge and post-merge deletion review |
| G6 | typed repair authority/budgets; recorded retrieval; normal BFTS/RQGM repair nodes; transaction, interruption, exhaustion, no-progress, and human-stop tests | main/release merge and post-merge deletion review |
| G7 | opt-in outer auto loop; cumulative budgets; full four-topology compile→bound build→decision→lock E2E | main/release merge and post-merge deletion review |
| G8 | independent decision/lock; final content/freshness recheck; evaluation; all 13 failure families; additive migration/rollback; permanent docs | main/release merge, release review, and post-merge deletion review |

The closed policy is `scripts/manuscript_complete_release_gates.json`; the permanent runner is
`scripts/run_manuscript_complete_release.py`; and `.github/workflows/manuscript-complete.yml`
retains the revision-bound report/log artifact. The clean local run for revision
`712ea52bbbab4081d97ab1793608fdfb73b6340a` passed all nine checks with
`release_eligible=true` and report digest
`sha256:dce4924ee33eeea7163c1049411725a809543db027223924f176c6ba64353a58`.
[GitHub Actions run 31077892535](https://github.com/kotama7/ARI/actions/runs/31077892535)
then passed the same nine gates for PR head
`5f413c73d6f9c94cbf3135871325623cc7805631` via merge revision
`dcbe214d05fb12c727b2b5df699242f29a291fc2` and tree
`d53f8c0f6c91fd05af3a91d08f1f9f4567e5ff72`. Its report digest is
`sha256:db7492aeb36c2d1c2e7e8425da521da8888fa6205467fe9aaf9ebd901f515bbc`.
The retained artifact is `manuscript-complete-release-dcbe214d05fb12c727b2b5df699242f29a291fc2-1`
(artifact ID `8958284666`, artifact digest
`sha256:2b3840cb4876a3874c9a108f2fb13f8bafca3c826becc3dc0064bfb5a492a3c6`,
expiry `2026-11-04T06:37:10Z`).

## Current deletion assessment

All plans remain **not deletable**. The retained remote CI artifact requirement is satisfied; the
shared blockers are merge/release review and post-merge deletion-readiness review.
On top of those, as of 2026-08-16 the advertised verified native HPC Harness scope no longer
verifies at HEAD: `catalog.yaml` still lists `hpc/gemm-performance` as `verified`, but its
registration report binds a manifest digest that the manifest in the tree no longer has, so
`load_harness_catalog` refuses the catalog and the persisted certify→publication chain is pinned to
a superseded report digest for that Harness. Until that is settled, authentic evidence covers the
three correctness Harnesses but not the advertised performance one. Unavailable external
PaperBench/other Harness scopes remain explicitly unsupported rather than mocked. Permanent documents
now carry the architecture, contracts, release policy, migration, rollback, and operator semantics.
