# Task 06: Paper RQGM Archive Integration

> **Status**: planned
> **Depends on**: 00, 01, 02, 03, 04
> **External references**: ARI-RQGM-paper Tasks 01–07
> **Gate**: G5 — common manuscript input across paper backends
> **Plan type**: temporary sub plan; see [INDEX.md](INDEX.md)

## 1. Purpose

`rqgm_archive` を linear と同じ `ManuscriptAuthoringBindingV1` / section brief consumer にし、
全 draft candidate が同じ固定 evidence/readiness を基に文章表現だけを探索するようにする。
archive utility と hard publication constraints を分離し、winner を共通 verification tail へ
渡す。

## 2. Scope

- `PaperBackend` facade and `RqgmArchivePaperBackend` adapter。
- Shared ready bundle input for every candidate。
- Candidate provenance binding to profile/context/readiness/brief digests。
- Manuscript-aware candidate diagnostics/utility inputs。
- Hard disqualification before winner eligibility。
- Winner materialization and common verification segment handoff。
- Resume/mode persistence interaction。
- Enforce-mode archive failure/fallback posture。
- `simple_bfts + rqgm_archive` isolation tests before full RQGM topology。

## 3. Non-goals

- paper archive search algorithm、epoch governance、writer/reviewer roles自体を再設計しない。
- Research RQGM/KCA adapterを所有しない。
- archive reviewerに readiness/evidence lane変更権限を与えない。
- archive loop内からBFTS/研究repairを起動しない。
- hard failureをutility penaltyへ変換して相殺しない。
- off-mode existing fail-open/fallback behaviorを無関係に変更しない。

## 4. Backend contract

Both backends implement a common conceptual interface:

```python
generate(
    authoring_binding,
    section_brief_bundle,
    checkpoint,
    model_runtime,
) -> PaperBackendResult
```

Result records:

- backend/mode/version。
- exact input digests。
- candidate/winner IDs and lineage where applicable。
- draft artifact refs/digests。
- model usage/cost provenance。
- hard-disqualification reasons。
- diagnostics for later verification/repair consideration。

Backend result does not contain a readiness override。

## 5. Candidate inputs

Every archive candidate and reviewer receives:

- same resolved requirement profile digest。
- same manuscript context/readiness digest。
- section-specific brief digest(s) used by that model call。
- allowed claim/evidence/reference IDs。
- mandatory negative evidence/disclosures。
- forbidden/non-publishable evidence IDs。
- omission counts and applicable caveats。

Candidate-specific prompt evolution may change writing instructions but cannot change these immutable
blocks。Prompt records bind both evolved prompt digest and fixed brief digest。

## 6. Candidate evaluation

Allowed additive utility/diagnostic axes:

- required section-item coverage。
- claim-evidence link coverage。
- citation suitability/coverage against recorded references。
- limitation/negative-result disclosure completeness。
- unsupported or forbidden-evidence claim count。
- existing rubric/reviewer/anchor utility。

Hard disqualifiers include:

- invented/unlinked objective numeric claim beyond allowed policy。
- use of excluded/non-publishable evidence as positive claim under enforce。
- missing mandatory disclosure or section requirement designated hard by profile。
- input digest mismatch or stale binding。
- invalid candidate artifact/provenance。

Disqualified candidates remain in archive audit history but cannot become winner regardless of score。

## 7. Verification handoff

Archive materializes exactly one winner to the canonical draft location and records its candidate
digest。The existing claim/compile/finalize/reproduction tail runs on that exact winner through Task
04's verification segment。

No separate weakened claim gate is implemented in archive。If archive performs preliminary checks,
they are diagnostics; final fixed verification remains authoritative。

## 8. Failure and fallback

### Off path

Existing `rqgm_archive` behavior/fallback remains governed by its existing plan and tests。

### Manuscript audit

Archive may fall back according to existing policy, but audit artifacts explicitly record whether
the result was manuscript-bound or legacy fallback。

### Manuscript enforce

An unbound linear fallback cannot be declared manuscript-complete。On archive failure:

- either invoke the linear backend with the same valid authoring binding, or
- stop with `authoring_backend_failed`。

The choice is fixed policy/config, not exception-dependent silent downgrade。

## 9. Research feedback boundary

Archive diagnostics may identify unsupported claims or apparent evidence gaps。They may emit typed
`paper_diagnostic` records, but:

- they do not create/execute research nodes。
- they do not mark readiness missing/satisfied directly。
- the outer coordinator may consume eligible diagnostics in a later Task 07/08 repair cycle after a
  fixed validator maps them to requirements。
- prose-quality issues stay inside archive refinement and never become research repair。

## 10. Tests

- Same bundle digest for all candidates/reviewers。
- Prompt evolution cannot mutate fixed evidence block。
- Disqualified high-utility candidate loses to admissible candidate or leaves no winner。
- Archive winner enters common verification tail exactly once。
- Unsupported numeric/forbidden evidence fixture is caught after co-evolution。
- Mandatory negative/limitation coverage diagnostics。
- Mode persistence/resume with unchanged and stale bundle。
- Enforce archive failure uses bound linear fallback or blocks; never unbound fallback。
- `simple_bfts + rqgm_archive` works without Research RQGM runtime。
- Existing off-mode archive contract remains compatible。
- No research executor invoked from archive code path。

## 11. Completion criteria

1. Linear and archive backends accept the same normative manuscript binding semantics。
2. Every archive candidate/model call binds identical context/readiness/profile inputs and exact
   section brief digests。
3. Hard violations cannot be compensated by utility score。
4. Archive winner is the exact draft verified by the common tail。
5. Enforce failure cannot silently produce an unbound manuscript-complete paper。
6. Archive cannot change readiness/evidence lanes or execute research repair。
7. `simple_bfts + rqgm_archive` passes independently of Task 05 RQGM exploration integration。
8. Resume detects stale manuscript bundle before candidate continuation。
9. Off-mode paper archive compatibility tests remain green。
10. G5 evidence is recorded for Task 08 full topology。

## 12. Deletion criteria

This plan may be deleted only when:

1. Completion criteria are satisfied, merged, and CI green。
2. PaperBackend/bundle integration is in permanent paper architecture docs。
3. Hard-disqualification versus utility semantics are permanent code/tests/docs。
4. Enforce fallback policy is documented for users/operators。
5. Archive resume/staleness behavior is maintained by permanent tests。
6. Tasks 08–09 no longer cite this prose as the only paper-backend contract。
7. External paper-plan decisions used here have permanent implementation references。
8. `INDEX.md` records deletion status and reason。

## 13. Delete-after checklist

- [ ] Common backend contract is permanently documented。
- [ ] Candidate input-binding tests are green。
- [ ] Hard-disqualification tests are green。
- [ ] Winner-to-verification identity test is permanent。
- [ ] Enforce fallback/runbook documentation is published。
- [ ] No archive-to-research nested execution exists。
- [ ] Main merge and CI revision are recorded。
- [ ] Downstream prose-only dependencies are removed。
- [ ] `INDEX.md` is updated before deletion。

## 14. Handoff

Task 08 combines this backend with Task 05 Research RQGM and Task 07 repair coordinator。Task 09
consumes the verified winner/build digest without needing archive-internal state to decide publication。
