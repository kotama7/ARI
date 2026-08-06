# Task 08: Automatic Repair and Full Topology

> **Status**: in progress
> **Depends on**: 00, 01, 02, 03, 04, 05, 06, 07
> **Gate**: G7 — bounded automatic composition across all execution topologies
> **Plan type**: temporary sub plan; see [INDEX.md](INDEX.md)

## 1. Purpose

Task 07 の明示 repair transaction を outer `ManuscriptCoordinator` が policy に従って自動実行
できるようにし、`simple_bfts|ari_rqgm × linear|rqgm_archive` の全4 topology を同一
completeness semanticsで完結させる。自動化は権限を広げず、paper searchとresearch searchを
再帰させず、設定された上限内で必ず停止する。

## 2. Scope

- `repair.policy=auto` activation and validation。
- Deterministic repair request admission/order policy。
- Outer compile→assess→repair→rebuild loop。
- Run-level cumulative budget and termination reason。
- All four research×paper topology composition。
- Research RQGM request-seed adapter and lineage。
- Paper archive diagnostic-to-requirement validation boundary。
- Existing paper-candidate preflight deduplication in current-run loops。
- Exhaustion/human/unavailable outcomes and resume。
- Automatic-mode cost/trace observability。

## 3. Non-goals

- Task 07 resolver semanticsを変更しない。
- repair budgetを最適化するためにhard requirementを無視しない。
- paper reviewer scoreだけで研究実験を起動しない。
- paper archive loop内にresearch loopをnestしない。
- auto modeを既定にしない。
- `ari paper`にresearch executorを合成しない。
- human decisionを自動選択しない。

## 4. Activation

```yaml
manuscript:
  mode: enforce
  repair:
    policy: auto
    max_rounds: 2
    max_new_nodes: 8
    max_experiment_runs: 12
    max_llm_calls: 8
    on_exhaustion: block
```

Rules:

- auto requires `manuscript.mode=enforce` unless a future explicit shadow-evaluation mode is versioned。
- `ari run`/`resume` may provide research executor。
- `ari paper` returns `repair_required` and never auto-executes experiment repair。
- capability/assurance enforce absence blocks or yields human/unavailable; it never falls back to
  legacy authority。
- default remains `off + disabled`。

## 5. Outer loop

```text
round 0 evidence -> compile -> assess
  ready -> author backend -> verify
  missing -> build plan -> fixed admission
                -> no admitted requests: blocked
                -> execute admitted requests
                -> invalidate affected evidence segments
                -> rebuild evidence/context/readiness (round 1)
repeat until ready, human/unavailable block, or budget exhaustion
```

The loop never authors a draft before readiness。Paper-backend diagnostics discovered after
authoring may create a future validated repair signal, but do not recursively re-enter research from
inside archive/verification。If configured to continue automatically, control returns to the outer
coordinator, invalidates the draft, and starts a new numbered round within remaining budget。

## 6. Admission and ordering

Admission priority:

1. projection/artifact recovery that may close gaps without new research。
2. current required certification with already available evidence。
3. recorded literature retrieval when authorized。
4. validation of contradictory or integrity-critical result。
5. minimal baseline/repetition/ablation experiments needed for blocking claims。
6. optional/nonblocking improvements only if profile and budget explicitly allow。

Within priority, stable requirement/request ID order applies。The coordinator may group compatible
requests when one bounded experiment satisfies several requirements, but grouping must preserve each
request's success predicate and budget attribution。

## 7. RQGM research composition

Typed requests become governed proposal seeds with:

- request/requirement IDs。
- fixed/variable experimental fields。
- semantic capability/Harness needs。
- success and stop predicates。
- remaining budget。

RQGM may explore alternatives inside this envelope。It cannot mutate profile severity、admit new
providers/Harnesses、or mark success。Generated nodes inherit request lineage and remain subject to
normal RQGM governance/frontier/KCA checks。

## 8. Paper archive composition

Paper archive consumes only a ready bundle。Candidate diagnostics are separated:

- prose/rubric issues -> archive refinement only。
- unsupported draft claim with existing evidence -> authoring/claim correction。
- verified evidence gap -> fixed diagnostic mapper may propose a repair request for the outer next
  round。
- certification/integrity failure -> KCA/validation resolver, never prose repair。

Any diagnostic-to-repair mapping binds the offending draft/build/claim/evidence digests and is
deduplicated against readiness/preflight signals。

## 9. Topology matrix

| Research | Paper | Required proof before full enablement |
|---|---|---|
| simple BFTS | linear | reference auto repair and termination |
| ARI-RQGM | linear | governed repair seed, KCA lane/certification |
| simple BFTS | RQGM archive | shared ready bundle, no nested research |
| ARI-RQGM | RQGM archive | full Layer 0/1/2/3 separation and signal deduplication |

The fourth cell remains disabled until Tasks 05–07 gates pass。Configuration resolver does not infer
one axis from another。

## 10. Termination and exhaustion

Stop when any condition holds:

- readiness authoring-ready。
- no admissible request exists。
- human decision required。
- required capability/Harness unavailable。
- max rounds reached。
- max nodes/runs/LLM calls/resource units reached。
- repeated context digest/no-progress cycle detected。
- integrity/tamper failure requires external intervention。

No-progress detection compares requirement status vector and source context digest。Repeated writer
wording is irrelevant。Termination records exact outstanding requirements and consumed budget。

## 11. Resume

Persist:

- coordinator round and source attempt digest。
- admitted request set/order。
- cumulative/reserved/used budget。
- completed transaction IDs。
- invalidated/reusable evidence segments。
- authoring attempts invalidated by later repair。
- final termination reason。

Resume recomputes effective locks/config consistency and continues from last committed transaction。
Mode/profile/authority disagreement blocks mid-run mutation; user starts a new attempt explicitly。

## 12. Tests

- Activation matrix and invalid combinations exhaustive tests。
- Priority/order/grouping determinism。
- Projection-first avoids unnecessary experiment fixture。
- Multi-requirement single-experiment budget attribution。
- Each termination condition and no-progress cycle。
- Cumulative budget never exceeded across resume。
- Four topology E2E matrix。
- Research RQGM constraint/lineage/non-escalation。
- Paper archive no nested research spy。
- Diagnostic/readiness/preflight deduplication。
- Draft invalidation after repair/new context。
- `ari paper` auto experiment denial。
- off/audit/default identity and no implicit activation。
- crash/resume at every outer-loop boundary。

## 13. Completion criteria

1. Auto mode is opt-in and accepted only under valid enforce/runtime conditions。
2. Outer loop executes only Task 07 admitted transactions and always terminates。
3. Projection/recovery is attempted before avoidable new experiments。
4. Cumulative budget/authority cannot be exceeded or broadened across rounds/resume。
5. All four topologies use identical context/readiness contract semantics。
6. Research RQGM obeys request envelope and retains lineage。
7. Paper archive never owns/nests research execution or rewrites readiness。
8. Diagnostics/readiness/preflight signals are applied once。
9. New evidence invalidates old briefs/drafts/builds before re-authoring。
10. Human/unavailable/exhausted results remain explicit and publication-blocking as required。
11. `ari paper` never auto-starts research experiments。
12. G7 full-topology evidence is ready for Task 09 release evaluation。

## 14. Deletion criteria

This plan may be deleted only when:

1. Completion criteria are satisfied, merged, and CI green for all generally available topologies。
2. Auto-loop activation、ordering、termination、budget semantics are in permanent docs/tests。
3. Four-topology compatibility matrix is maintained by permanent CI coverage。
4. RQGM/Archive integration boundaries are documented at implementation seams。
5. Operator docs cover exhaustion、human block、resume、rollback。
6. Task 09 no longer relies on this prose as its only full-topology specification。
7. No unresolved auto-repair safety issue remains in temporary notes。
8. `INDEX.md` records deletion status and reason。

## 15. Delete-after checklist

- [ ] Auto activation/invalid-combination tests are permanent。
- [ ] Termination/no-progress tests are green。
- [ ] Cumulative budget/non-escalation tests are green。
- [ ] Four topology E2E matrix is in CI。
- [ ] RQGM constraint and archive no-nesting tests are permanent。
- [ ] Signal deduplication tests are green。
- [ ] Exhaustion/resume/rollback runbook is published。
- [ ] Main merge and CI revision are recorded。
- [ ] Downstream prose-only dependencies are removed。
- [ ] `INDEX.md` is updated before deletion。

## 16. Handoff

Task 09 receives final attempt/build/repair lineages and the full topology evidence。It adds the final
publication decision/lock、program metrics、migration/release documentation without changing the
auto-loop semantics。
