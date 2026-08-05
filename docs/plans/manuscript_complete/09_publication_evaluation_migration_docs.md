# Task 09: Publication Lock, Evaluation, Migration, and Documentation

> **Status**: planned
> **Depends on**: 00, 01, 02, 03, 04, 05, 06, 07, 08
> **External dependencies**: authentic ARI-RQGM Tasks 18/19 certification evidence where applicable; existing paper final gate/reproduction contracts
> **Gate**: G8 — release and permanent-spec closure
> **Plan type**: temporary sub plan; see [INDEX.md](INDEX.md)

## 1. Purpose

readiness、final claim gate、KCA certification、compile/reproduction の独立 verdict を
`PublicationDecisionV1` として exact paper buildへ結び、locked paper の最終 interlock を
完成させる。同時に program evaluation、failure injection、legacy migration、operator/release
docs、恒久仕様移管を完了し、Task 00/01–09 を削除可能な状態へ進める。

## 2. Scope

- `PublicationDecisionV1` schema/contract/evaluator。
- Final paper build and authoring binding verification。
- Readiness/claim/KCA/build/reproduction independent sub-verdicts。
- Publication lock manifest binding and stale re-check。
- Program metrics/evaluation fixtures and reports。
- Failure-injection suite across safety seams。
- Legacy checkpoint audit/enforce migration behavior。
- Release/rollback/operator runbooks。
- Permanent architecture、schema/reference、profile、integration documentation。
- Optional stable read API/GUI read model after core contract freeze。

## 3. Non-goals

- hard gateを一つのutility scoreへ統合しない。
- failed KCA/claim/reproductionをreview scoreで相殺しない。
- external Harness parityをmock結果で完了扱いしない。
- publication decisionから新しいresearch repairを直接実行しない。
- old manuscript attemptsやblocked draftsを物理削除しない。
- GUI完成をcore publication safetyの前提にしない。

## 4. Publication decision contract

Required bindings:

- run/checkpoint/attempt IDs。
- final paper build digest and revision。
- manuscript profile/context/readiness/brief/authoring-binding digests。
- final claim-link and hard-gate artifact digests。
- applicable KCA catalog/contract/attestation/target digests。
- compile/PDF artifacts。
- reproduction/code-bundle/EAR locks。
- evaluator/policy version and decision digest。

Sub-verdict shape:

```text
manuscript_readiness: pass | fail | not_required
claim_evidence:       pass | fail
assurance:            pass | fail | not_required
build_compile:        pass | fail
reproduction:         pass | fail
freshness:            pass | fail
decision:             publishable | blocked
```

Top-level publishable iff every applicable sub-verdict is pass。Reasons remain separate, ordered,
typed, and linked to artifacts。

## 5. Finalizer and lock integration

Before lock:

1. Re-read and validate all bound artifacts。
2. Recompute/verify their digests and safe paths。
3. Confirm readiness context/profile is the one used for authoring。
4. Confirm final draft/build is the one claim gate and compile evaluated。
5. Invoke exact-target current certification when required or validate its fresh result。
6. Verify reproduction/code-bundle/EAR locks。
7. Create PublicationDecision。
8. Only publishable decision may be referenced by locked paper manifest。

Any change between evaluation and lock invalidates the decision。No cached pass survives source/catalog/
attestation/build mutation。

## 6. Evaluation metrics

At minimum report:

- requirement accounting rate。
- missing detection precision/recall on labelled fixtures。
- silent omission count。
- headline publishable evidence coverage。
- negative-result visibility。
- unnecessary repair rate。
- repair success and marginal cost。
- attempts/rounds to finalization。
- blocked decision reason distribution。
- per-topology token/run/resource cost。
- legacy off-path identity result。

Metric definitions、numerator/denominator、applicability、evidence refs are versioned。No denominator-zero
case is silently reported as perfect。

## 7. Failure injection suite

Required injections:

- source tamper after report/context/authoring。
- missing artifact at finalizer。
- stale/target-mismatched/failed certification。
- high-score debug frontier chosen scientifically。
- unsupported numeric claim inserted after ready context。
- contextual-negative evidence used as positive claim。
- required item omitted by budget。
- related-work cache/provider absence。
- malformed/unknown manuscript schema。
- model/network unavailable at each optional/required stage。
- repair exhaustion/no-progress/human decision。
- archive high-utility hard-failing winner attempt。
- resume with config/profile/mode/lock disagreement。

Each injection states expected channel and blocking point。A test fails if the defect is only logged but
publication still locks。

## 8. Legacy migration

### Off

- No migration or `.ari-manuscript` artifact。
- Existing paper mode/resume remains authoritative。

### Audit

- Lazily construct attempts from available artifacts。
- Missing historical evidence is typed missing/unavailable。
- Existing paper is not retroactively labelled manuscript-complete。

### Enforce

- Requires current profile/evaluator and fresh readiness before new authoring/finalization。
- Historical unverifiable facts are not reconstructed as successful measurements。
- User may choose repair, disclosure where admissible, or remain blocked。
- Old final paper remains an old artifact; new lock status is not rewritten in place。

Migration is additive and rollback preserves attempts for audit。

## 9. Permanent documentation deliverables

- Manuscript Complete architecture and authority layers。
- Contract/schema reference for all V1 artifacts。
- `generic_empirical_v1` requirement/applicability guide。
- Evidence lane、subject selection、runner-up fallback policy。
- Workflow segmentation and backend integration guide。
- RQGM/KCA/paper archive adapter guide。
- Explicit/auto repair operator runbook。
- Resume/staleness/recovery troubleshooting。
- Publication decision and blocked-reason guide。
- Legacy migration/rollback/release notes。
- Security/privacy guidance for manuscript audit artifacts。

Temporary plan prose is not the final specification。Every normative decision must move to one of
these permanent homes or to a schema/code contract with a permanent reference。

## 10. API and optional GUI

After schema freeze, expose only stable read contracts through `ari.public.manuscript` if approved。
Mutable coordinator internals remain private。A GUI/read API may show requirement matrix、lanes、
omissions、repair budgets、attempt lineage、independent publication gates, but uses the same core read
model and never recalculates readiness。

GUI availability is not required to block unsafe publication; CLI/JSON must be sufficient。

## 11. Release gates

Release candidate requires:

- G0–G7 evidence linked by exact revisions。
- local suite green。
- remote CI green for generally available paths。
- authentic external Harness evidence for any capability advertised as supported。
- default/off identity confirmation。
- no critical/high unresolved publication safety issue。
- migration and rollback dry run on representative legacy checkpoints。
- operator review of blocked/exhaustion/human flows。
- documentation link checker/schema snapshot checker green。

Unsupported external Harness scope remains documented/blocked and does not prevent releasing other
clearly scoped paths, but cannot be advertised as implemented。

## 12. Tests

- PublicationDecision strict schema/digest/coherence tests。
- Logical-AND truth table across all applicable sub-verdicts。
- Exact build/context/attestation freshness tests。
- Finalizer TOCTOU mutation injection。
- Lock creation requires publishable decision digest。
- All §7 failure injections。
- Evaluation metric numerator/denominator/applicability tests。
- All four topology release E2E tests。
- Legacy off/audit/enforce migration tests。
- Rollback and old-attempt preservation tests。
- CLI/read API snapshot tests; optional GUI contract tests。
- Documentation relative links/schema examples validation。

## 13. Completion criteria

1. PublicationDecision binds the exact final build and all applicable fixed gates。
2. Top-level decision is the validated logical AND; all reasons remain independently visible。
3. Stale/tampered/mismatched input cannot survive finalizer/lock。
4. Locked paper manifest requires a publishable decision digest under enforce。
5. Evaluation reports all required metrics with valid denominators/evidence refs。
6. Every required failure injection blocks at the intended channel。
7. All four topologies meet their supported release gates。
8. Legacy off path remains identity-compatible and audit/enforce migration is honest/additive。
9. Authentic external certification evidence exists for every advertised enforce scope; unsupported
   scopes remain blocked and documented。
10. Permanent architecture/schema/profile/integration/operator/migration docs are complete。
11. No downstream production behavior relies only on temporary plan prose。
12. Task 00 §25 criteria and G8 review are satisfied。

## 14. Deletion criteria

This plan may be deleted only when:

1. All completion criteria are satisfied and merged to the release branch/main as required。
2. Required local/remote CI and authentic Harness evidence are green and retained outside this plan。
3. PublicationDecision/lock semantics are permanent schemas、code tests、reference docs。
4. All metrics/failure injections are maintained by permanent evaluation code/tests。
5. Migration、rollback、repair、blocked-publication runbooks are published permanently。
6. Every Task 00/01–08 normative decision needed in production has a permanent home。
7. No open safety、compatibility、authority、schema issue exists only in this plan。
8. Parent Task 00 and all subplan indexes are updated consistently before deletion。
9. `INDEX.md` records deletion status and reason。

## 15. Delete-after checklist

- [ ] PublicationDecision and lock schemas are permanent。
- [ ] Logical-AND/freshness/TOCTOU tests are green。
- [ ] All required failure injections run in CI。
- [ ] Program metrics are generated by permanent evaluation code。
- [ ] Four-topology release evidence is retained。
- [ ] Authentic advertised Harness evidence is retained。
- [ ] Legacy migration/rollback dry runs are recorded。
- [ ] Architecture/schema/profile/integration docs are published。
- [ ] Repair/resume/publication operator runbooks are published。
- [ ] Temporary-plan-only normative references are zero。
- [ ] Main/release merge and CI revisions are recorded。
- [ ] Task 00/01–08 deletion readiness has been reviewed。
- [ ] `INDEX.md` is updated before deletion。

## 16. Program handoff and deletion order

Task 09 is normally the last sub plan deleted。Recommended order:

1. Tasks 01–08 become deletable after their permanent handoffs and downstream proof。
2. Task 09 verifies program-wide permanent specification and release evidence。
3. Parent Task 00 is deleted only after its own deletion criteria and this task's permanent handoff。
4. `INDEX.md` remains until all active plans are removed or the plan set is formally archived。
