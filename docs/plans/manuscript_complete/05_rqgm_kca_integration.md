# Task 05: Research RQGM and KCA Integration

> **Status**: in progress
> **Depends on**: 00, 01, 02, 03, 04
> **External dependencies**: ARI-RQGM Tasks 18/19 for authentic certify/publication closure
> **Gate**: G4 — assurance-aware evidence and publication subject binding
> **Plan type**: temporary sub plan; see [INDEX.md](INDEX.md)

## 1. Purpose

Research `ari_rqgm` の epoch/frontier/erasure/assurance evidence を topology-neutral manuscript
snapshotへ投影し、科学的最良ノードと publication candidate を明示的に分ける。KCA screen
と certify の意味を混同せず、`assurance.mode=enforce` では exact target への current
certification がない限り publication を阻止する。

## 2. Scope

- `RqgmSnapshotProvider` adapter。
- RQGM node/frontier/epoch/erasure/stale projection。
- assurance status and attestation references。
- evidence lane final classification。
- scientific winner/publication candidate subject set。
- certified runner-up policy from MC-ADR-007。
- audit/enforce assurance readiness behavior。
- production publication-intent integrity call when external prerequisites exist。
- existing paper-candidate preflight signal deduplication boundary。
- RQGM-specific tests without reverse imports into core manuscript contracts。

## 3. Non-goals

- Harness/Knowledge/Provider catalogを作成・promotionしない。
- fixed verifier verdictを再計算・上書きしない。
- RQGM frontier score/utility/best-node semanticsを manuscript都合で変更しない。
- ScienceData fact eligibilityに assuranceを埋め込まない。
- paper archive integrationを行わない。
- external Harness unavailableをfake passやalways-pass fixtureで埋めない。

## 4. Adapter boundary

`ari.manuscript` core must not import `ari.rqgm`。The RQGM integration module constructs the common
typed optional block and passes it to the snapshot/compiler facade。

Required projection:

- run/epoch IDs and frozen policy/catalog lock digests。
- node `assurance_status` and `frontier_class`。
- logical erasure and stale state。
- screen/certify attestation IDs/digests/status。
- attestation target subject/source/measurement/Harness bindings。
- governance/adversarial findings that make an artifact inadmissible。
- existing scientific best selection result and policy digest。

Missing optional fields are explicit absence, not legacy success。

## 5. Evidence lane policy

| Condition | Lane under assurance off | Lane under audit | Lane under enforce |
|---|---|---|---|
| valid typed measurement, no attestation | publishable by legacy policy | exploratory + audit finding | exploratory; publication requirement missing |
| screen pass, no certify | publishable by legacy policy | exploratory | exploratory; publication blocked |
| current certify pass exact target | publishable | publishable | publishable |
| certify fail | contextual/excluded by existing integrity | exploratory/contextual with finding | non-publishable; blocked |
| stale/erased/target mismatch | excluded | excluded | excluded/blocked |
| debug frontier | legacy context only | exploratory | non-publishable |

Exact handling of failure versus excluded follows fixed KCA contracts。The manuscript layer records,
but does not reinterpret, the verifier reason code。

## 6. Subject selection

Always record:

- `scientific_winner` from the scientific selection policy。
- `publication_candidate` from manuscript publication admissibility policy。
- ordered certified alternatives。
- reasons for every divergence/exclusion。

No silent substitution。Default MC-ADR-007 posture is expected to be no fallback unless profile and
contribution identity permit it。When fallback is allowed, comparisons and limitations are
re-evaluated against the new subject before readiness becomes ready。

If no admissible publication candidate exists:

- audit mode reports a shadow block and existing authoring behavior continues according to Task 03。
- enforce may allow a disclosure-bound draft only if `MC-AS-001` is publication-only。
- publication lock is blocked until a current certification or admitted policy resolution exists。

## 7. Publication certification binding

When Task 18/19 production surfaces are ready, Manuscript publication evaluation passes
`publication=True` and the exact target contract/attestation to the fixed integrity check。Required
binding includes:

- publication subject node/configuration ID。
- selected source/code digest set。
- covered ScienceData measurements/deterministic digest。
- Harness ID/version/runner/container/dataset locks as applicable。
- environment/Provider binding required by Harness contract。
- current catalog lock and attestation revision。

Any mismatch, missing required certification, failed block-publication finding, or stale binding is a
separate publication failure。

## 8. Knowledge and Capability interaction

- Knowledge records may enrich context provenance but do not promote evidence lanes。
- Capability binding determines allowed future repair operations; Task 05 only records current
  execution/provider bindings relevant to reproducibility。
- Missing Knowledge coverage is not equivalent to failed measurement。
- Missing Capability/Harness under enforce is `unavailable`/repairable, not implicit legacy access。

## 9. Existing preflight interaction

Current paper-candidate preflight can persist RQGM penalty after paper artifacts exist。In manuscript
mode:

- current-run readiness owns typed evidence gaps before authoring。
- preflight remains a governance signal, not a requirement evaluator。
- signals and repair diagnostics carry a digest to avoid double application。
- post-pipeline preflight cannot retroactively mark the already-used readiness report satisfied。
- off-mode behavior remains byte/call compatible。

## 10. Tests

- RQGM adapter projection and no reverse import tests。
- high-score debug frontier versus lower-score certified node fixture。
- scientific winner/publication candidate divergence record。
- no-candidate behavior under off/audit/enforce assurance。
- certify pass/fail/stale/target mismatch/catalog mismatch cases。
- logical erasure and retired policy exclusion。
- Knowledge/Capability absence does not fabricate evidence status。
- `publication=True` integrity call and exact target arguments when provider available。
- preflight/repair signal deduplication。
- off/simple path imports and artifacts unchanged。
- authentic external Harness parity tests are conditional on admitted dependencies and fail closed
  otherwise; no always-pass substitute。

## 11. Completion criteria

1. RQGM snapshot adapter emits the common contract without core reverse import。
2. Every RQGM fixture node receives a deterministic evidence lane and reason。
3. Scientific winner and publication candidate are independently recorded。
4. Debug/uncertified/stale/erased/tampered/target-mismatch evidence cannot support enforce publication。
5. Exact-target current certification can promote only covered evidence。
6. Missing external Harness remains explicit and blocks applicable publication rather than passing。
7. Existing preflight does not duplicate readiness/repair effects。
8. Simple/off behavior remains unchanged。
9. Task 18/19 authentic certify/publication evidence is linked when available; until then this task
   remains `in progress`, not `implemented`。
10. G4 review records the production assurance provider boundary handed to Task 09。

## 12. Deletion criteria

This plan may be deleted only when:

1. Completion criteria, including authentic applicable external certification evidence, are satisfied。
2. RQGM adapter and evidence-lane semantics are in permanent integration/reference docs。
3. Subject fallback/divergence policy is in permanent policy documentation and tests。
4. Publication target binding is maintained by fixed integrity tests and Task 18/19 permanent docs。
5. Preflight interaction/deduplication is documented at its implementation seam。
6. Tasks 08–09 no longer rely on this prose as the only assurance definition。
7. Main merge and required local/remote CI evidence are green。
8. `INDEX.md` records deletion status and reason。

## 13. Delete-after checklist

- [ ] RQGM adapter contract tests are permanent。
- [ ] Evidence lane and subject-selection docs are permanent。
- [ ] No-silent-fallback tests are green。
- [ ] Authentic certification parity evidence is linked。
- [ ] Publication target mismatch/stale tests are green。
- [ ] Preflight deduplication behavior is permanently documented。
- [ ] No fake/always-pass Harness remains。
- [ ] Main merge and remote CI revision are recorded。
- [ ] Downstream prose-only dependencies are removed。
- [ ] `INDEX.md` is updated before deletion。

## 14. Handoff

Task 08 consumes the RQGM adapter during full topology auto repair。Task 09 consumes the exact
certification provider and subject binding to build the final independent PublicationDecision。
