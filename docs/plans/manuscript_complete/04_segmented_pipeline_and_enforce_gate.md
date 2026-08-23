# Task 04: Segmented Pipeline and Enforce Gate

> **Status**: implemented — §12 re-checked at HEAD: segment freshness, brief
> binding without silent omission, and exact off-mode identity are all green
> (`test_segment_record_reuses_only_fresh_outputs`,
> `test_required_brief_items_split_without_omission`,
> `test_off_is_exact_no_artifact_identity`).
> **Depends on**: 00, 01, 02, 03
> **Gate**: G3 — pre-authoring readiness enforcement
> **Plan type**: temporary sub plan; see [INDEX.md](INDEX.md)

## 1. Purpose

post-BFTS paper workflow を evidence、authoring、verification の再開可能な segment に分け、
固定 `ManuscriptCoordinator` を evidence と authoring の間へ置く。`manuscript.mode=enforce`
では authoring-blocking な不足がある限り writer を起動せず、ready な場合だけ digest-bound
section briefs を linear backend へ渡す。

## 2. Scope

- Single workflow definitionへの additive segment metadata。
- Segment-aware pipeline execution/state/dependency validation。
- Fixed ManuscriptCoordinator before authoring。
- `enforce` activation semantics。
- `SectionBriefBundleV1` and deterministic section renderer。
- `ManuscriptAuthoringBindingV1`。
- LinearPaperBackend adapter。
- Existing verification tail handoff。
- Attempt state machine/staleness propagation/resume。
- Paper contract additive artifact roles/companion validation without legacy byte changes。

## 3. Non-goals

- RQGM assurance adapterを実装しない。
- Paper RQGM archiveを section brief consumerにしない。
- repairを実行しない。readiness failureは plan-ready diagnosticで停止する。
- claim gateやreview score式を変更しない。
- workflow YAMLを複製して manuscript専用版を維持しない。
- off/audit legacy behaviorを segmented pathへ強制移行しない。

## 4. Workflow segmentation

### 4.1 Segments

| Segment | Current stages |
|---|---|
| `evidence` | related-work search, provenance audit, transform, EAR/curation, figures/VLM |
| `authoring` | linear `write_paper`, later RQGM archive substitution point |
| `verification` | claim links/gates, reviews/refinement where backend permits, compile/finalize/reproduction |

Stage ordering remains the single YAML file order。Segment metadata is additive and ignored by the
legacy all-stages runner。

### 4.2 Segment state

Each segment execution records:

- resolved workflow digest。
- enabled/disabled stage set。
- input artifact digests。
- output artifact refs/digests。
- status and blocking reason。
- attempt/run identity。

A downstream segment starts only when required upstream outputs exist and match。A filename alone is
not sufficient。Resume reuses a segment only when its input and workflow digests are unchanged。

### 4.3 Driver behavior

The generic stage driver may execute a selected segment, but readiness is not an MCP stage and is not
subject to ordinary exception-swallow/fail-open behavior。Coordinator owns the transaction boundary。

## 5. Coordinator behavior

```text
research complete
  -> evidence segment
  -> compile source snapshot/context/readiness
       -> ready/ready_with_disclosures
            -> build section briefs + authoring binding
            -> linear backend
            -> verification segment
       -> repair_required/blocked
            -> persist result
            -> do not start authoring
```

Task 04 uses `repair.policy=disabled`; it may emit resolver suggestions but not a normative executable
repair plan owned by Task 07。

## 6. Section briefs

Initial sections:

- abstract/contribution summary。
- introduction。
- related work。
- method。
- experimental setup。
- results。
- negative results/analysis。
- limitations/threats。
- reproducibility/appendix instructions。

Each brief contains allowed positive evidence、required negative/contextual evidence、required
disclosures、forbidden evidence IDs、reference IDs、budget、included/omitted list。Required items that
do not fit cause deterministic split or build failure; they are never silently omitted。

## 7. Linear backend adapter

The adapter translates section briefs to the paper skill input without rebuilding context in
`ari-skill-paper/src/server.py`。All model calls record exact brief/profile/context/readiness digests。

During migration:

- off path keeps current `experiment_summary` assembly。
- audit path may compare legacy and brief inputs without changing output。
- enforce path uses briefs as the normative input。

The writer cannot request unrestricted node tree access。Any source dereference uses safe digest-bound
artifact reader and adds access provenance to the authoring record。

## 8. Paper binding

Add manuscript artifact roles without changing unconditional legacy requirements。Under enforce, a
fixed validator requires:

- requirement profile。
- manuscript context。
- readiness report。
- section brief bundle。
- authoring binding。

`ManuscriptAuthoringBindingV1` binds the target paper build ID/revision and backend。The final build
digest includes or is companion-bound to these exact inputs according to MC-ADR-004。

## 9. State and staleness

Implement legal transitions through `ready -> authoring -> authored` and blocked variants。Any change
to nodes/ScienceData/provenance/references/EAR/figures/profile invalidates relevant context/brief/build
artifacts。A stale ready report cannot authorize a writer call。

The state projection is rebuildable from immutable attempts/transitions。Illegal transition or hash
chain failure blocks enforce mode。

## 10. Failure posture

- Missing authoring-blocking requirement: stop before model call。
- Publication-only missing requirement: profile may permit draft with mandatory disclosure, but later
  publication remains blocked。
- Brief build failure: block authoring under enforce。
- Writer failure: preserve ready bundle and failed authoring attempt; do not recompute readiness。
- Verification failure: preserve draft, mark publication blocked。
- Segment failure: do not mark downstream dependency satisfied。
- Enforce path never silently falls back to unbound legacy authoring。

## 11. Tests

- Workflow segment membership and single-definition tests。
- Legacy all-stage ordering identity。
- Cross-segment dependency/digest tests。
- Ready versus blocking readiness model-call spy tests。
- Section brief deterministic ordering/budget/omission tests。
- Required item overflow test。
- Safe source dereference and digest mismatch test。
- Authoring binding validation/tamper test。
- Staleness propagation for each source class。
- Resume before/after every segment boundary。
- Linear backend output flows into existing verification tail。
- Off and audit behavior from Task 03 remains unchanged。

## 12. Completion criteria

1. One workflow definition supports all-stages legacy and segmented manuscript execution。
2. Evidence/authoring/verification dependencies are digest-validated and resumable。
3. Fixed coordinator runs readiness before any enforce-mode authoring model call。
4. Blocking `missing` prevents authoring; ready input starts it exactly once。
5. Every enforce model call binds a section brief/profile/context/readiness digest。
6. No required brief item is silently omitted。
7. Linear output enters the existing verification tail without weakening its gates。
8. Stale or corrupt readiness cannot authorize authoring。
9. Legacy PaperBuild/default paper bytes remain unchanged in off mode。
10. G3 evidence covers interrupted resume and failure posture。

## 13. Deletion criteria

This plan may be deleted only when:

1. Completion criteria are satisfied, merged, and CI green。
2. Workflow segment semantics and coordinator boundary are in permanent developer docs。
3. Section brief and authoring binding contracts are in schema/reference docs。
4. Temporary legacy-to-brief adapter code has an explicit permanent/removal status。
5. Resume/staleness behavior is maintained by permanent tests and operator docs。
6. Tasks 05–09 no longer cite this prose as their only handoff definition。
7. `INDEX.md` records deletion status and reason。

## 14. Delete-after checklist

- [ ] Segment metadata/runner contract is permanently documented。
- [ ] Coordinator fail-closed tests are green in CI。
- [ ] Section brief schema/reference is permanent。
- [ ] Authoring binding and PaperBuild relationship is permanent。
- [ ] Resume/staleness runbook is published。
- [ ] Temporary audit hook from Task 03 is removed or finalized。
- [ ] Main merge and CI revision are recorded。
- [ ] Downstream prose-only dependencies are removed。
- [ ] `INDEX.md` is updated before deletion。

## 15. Handoff

Task 05 adds RQGM/KCA source semantics before the same compiler。Task 06 adds another PaperBackend
after the same ready bundle。Task 07 wraps the coordinator's `repair_required` branch without putting
research execution inside the pipeline driver。
