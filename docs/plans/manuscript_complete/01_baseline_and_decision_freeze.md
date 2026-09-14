# Task 01: Baseline and Decision Freeze

> **Status**: implemented — §9 re-checked at HEAD: the seven fixture classes are
> manifest-bound and materialisable (`test_baseline_fixture_catalog_is_complete`,
> `test_baseline_fixture_classes_are_executable`) and MC-ADR-001–009 have permanent
> homes under `docs/adr/manuscript_complete/`.
> **Depends on**: 00
> **Gate**: G0 — baseline and normative decision freeze
> **Plan type**: temporary sub plan; see [INDEX.md](INDEX.md)

## 1. Purpose

Manuscript Complete の実装前に、現在の探索→paper handoff、writer 入力損失、既定経路の
identity、代表 checkpoint を再現可能な baseline として固定する。同時に、後続契約の bytes
や責任境界を左右する設計判断を ADR と contract fixture に落とし、Task 02 以降が別々の
解釈で実装を始めないようにする。

## 2. Scope

- 現行 `simple_bfts + linear` の config、import、artifact、paper output baseline。
- small、large、failed/null、legacy、RQGM-assured checkpoint fixture の定義。
- writer へ渡る／渡らない情報の inventory。
- 現行 10 configurations、20 candidate claims、12 references、48k context、source budget の
  観測 fixture。
- current workflow stage order と paper mode dispatch の call trace。
- Manuscript Complete 固有 namespace、attempt identity、workflow segmentation、PaperBuild
  binding、public API timing の ADR。
- `generic_empirical_v1` applicability のうち contract shape に影響する決定。

## 3. Non-goals

- production code path を変更しない。
- `manuscript` config をまだ追加しない。
- readiness、repair、section brief を実装しない。
- RQGM、paper archive、KCA の既存挙動を修正しない。
- fixture を「成功例だけ」に限定しない。

## 4. Required baseline fixtures

| Fixture | Required properties | Primary purpose |
|---|---|---|
| `mc_small_linear` | 3以下の成功 node、単一 metric、関連文献あり | deterministic minimum |
| `mc_large_context` | 10超 configurations、20超 claims、12超 references、大きな source | truncation/omission baseline |
| `mc_negative_tree` | failed、null、inconclusive、abandoned、off-lineage sibling | narrative visibility |
| `mc_tamper_stale` | missing file、digest mismatch、stale node | provenance/lane safety |
| `mc_rqgm_assured` | scientific/debug/uncertified frontier、screen/certify records | Task 05 handoff |
| `mc_legacy_checkpoint` | manuscript artifactなし、古い optional artifact欠落 | lazy audit/migration |
| `mc_repairable_gap` | baseline/uncertainty/ablation の既知欠落 | Tasks 07–08 handoff |

Fixture は synthetic/real-derived の区別、generator version、expected labels を manifest に
持つ。synthetic measurement が実研究結果として読まれないように provenance を固定する。

## 5. Baseline evidence

### 5.1 Identity baseline

次を記録する。

- resolved default config digest。
- import trace: legacy linear pathで `ari.manuscript` が存在しない現在状態。
- checkpoint 内の paper-related file inventory と SHA-256。
- `full_paper.tex`、`refs.bib`、PaperBuild、claim gate、reproduction artifact の digest。
- resume/re-invoked `ari paper` の effective paper mode。
- network/LLM unavailable 時の既存 failure posture。

Golden は環境依存 bytes を canonicalize する規則を明示する。canonicalize 不能な値を
都合よく削除せず、比較対象外 field とその理由を manifest に記録する。

### 5.2 Information-flow baseline

全 source item に stable fixture label を付け、次を比較する。

```text
all checkpoint inventory
  -> ScienceData projection
  -> verified_context projection
  -> writer experiment_summary
  -> paper claim links
```

各境界で included、omitted、unknown を数える。現行 code が omission reason を返さない場合は
test harness が observed reason を記録するが、それを production semantics として扱わない。

### 5.3 Call-order baseline

少なくとも次を spy/trace で固定する。

1. `_run_loop` completion。
2. `run_paper_phase` invocation。
3. paper preflight before/after behavior。
4. linear/archive branch resolution。
5. `generate_paper_section` workflow load。
6. claim/review/finalize/reproduction tail。

## 6. Decisions to freeze

G0 までに次の ADR を作る。

| ADR | Required decision |
|---|---|
| MC-ADR-001 | `.ari-manuscript/` namespace and ownership |
| MC-ADR-002 | digest-derived attempt identity and collision handling |
| MC-ADR-003 | single-workflow segmentation API; duplicate workflow files prohibited |
| MC-ADR-004 | legacy `PaperBuildV1` preservation and companion authoring binding |
| MC-ADR-005 | internal-first versus immediate `ari.public.manuscript` export |
| MC-ADR-006 | stochastic/comparative/ablation applicability inputs |
| MC-ADR-007 | certified runner-up fallback default and disclosure |
| MC-ADR-008 | explicit operations allowed from `ari paper` |
| MC-ADR-009 | audit shadow publication decision semantics |

ADR は parent plan を複製せず、decision、alternatives、compatibility consequence、reversal
condition、owning tests を持つ。

## 7. Expected files

- Test fixtures under the repository's existing fixture convention。
- Baseline manifest and expected-label files。
- Golden/snapshot test definitions。
- Permanent ADR directory selected by MC-ADR-001/005; temporary notes may start beside fixtures。
- No `.ari-manuscript` runtime production artifact yet。

## 8. Verification

- Golden capture command is repeatable from a clean test workspace。
- Two consecutive captures produce equal normative digests。
- Large fixture proves at least one item crosses every known current cap。
- Negative fixture labels survive the raw inventory even if current narrative omits them。
- RQGM fixture contains at least one high-scoring non-publishable candidate and one certification
  target mismatch case。
- Legacy fixture can execute current paper path without migration。
- Tests distinguish expected platform variance from unexplained drift。

## 9. Completion criteria

1. All seven required fixture classes exist with manifests and expected labels。
2. Default `simple_bfts + linear` artifact and call-order baseline is executable in tests。
3. Current writer projection loss is measured at every named boundary。
4. Known caps are exercised, not only documented from source inspection。
5. Negative/stale/tamper/RQGM assurance cases are represented。
6. MC-ADR-001 through MC-ADR-009 are accepted or have an explicit blocking owner。
7. No production behavior or existing plan file changed as part of this task。
8. G0 review records the exact revision/digests handed to Task 02。

## 10. Deletion criteria

This plan may be deleted only when:

1. All completion criteria are satisfied and merged。
2. Every baseline fixture is maintained by an executable permanent test, not by this prose alone。
3. All accepted decisions are in permanent ADRs or contract comments with stable links。
4. Current-state loss findings that remain operationally relevant are moved to permanent migration
   or architecture documentation。
5. Downstream tasks no longer cite this file as the only source of fixture labels or decisions。
6. Remote CI has executed the identity baseline on supported platforms。
7. `INDEX.md` records the deletion status and reason。

## 11. Delete-after checklist

- [ ] Required fixture manifests are checked in and test-owned。
- [ ] Golden regeneration command is documented permanently。
- [ ] Identity and call-order tests are green locally and in CI。
- [ ] MC-ADR-001–009 have permanent homes。
- [ ] Context-loss baseline is linked from migration/reference docs。
- [ ] No downstream plan depends only on prose in this file。
- [ ] Main merge and CI revision are recorded。
- [ ] `INDEX.md` is updated before deletion。

## 12. Handoff

Task 02 receives immutable fixture labels、golden digests、ADR decisions。Any later request to change
a frozen decision must update its ADR and the dependent contract tests; editing only a sub plan is
insufficient。
