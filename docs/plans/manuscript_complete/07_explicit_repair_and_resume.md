# Task 07: Explicit Repair and Resume

> **Status**: in progress
> **Depends on**: 00, 01, 02, 03, 04
> **Optional integration dependencies**: 05 for KCA repair; existing research runtime for experiment repair
> **Gate**: G6 — bounded, authorized, idempotent repair
> **Plan type**: temporary sub plan; see [INDEX.md](INDEX.md)

## 1. Purpose

readiness の `missing|unavailable` を typed `ResearchRepairPlanV1` へ変換し、人が明示的に
選択した request だけを、元 run の authority と budget 内で実行する。projection、artifact、
literature、assurance、experiment、disclosure、human decision を別 resolver として扱い、
interrupt/resume 時も重複実行しない transaction を作る。

## 2. Scope

- `ResearchRepairPlanV1` and request lifecycle contracts/schemas。
- Fixed readiness-to-repair mapping registry。
- Stable request identity and deduplication。
- Run-level and request-level budget ledger。
- Projection/artifact recovery resolvers。
- Recorded literature resolver。
- Assurance certification resolver when Task 05 provider exists。
- Experiment repair adapter through normal BFTS/RQGM run/resume loop。
- Limitation disclosure and human-decision terminal handling。
- `ari manuscript plan-repair` and `ari manuscript repair` explicit commands。
- Append-only repair transitions and interruption-safe resume。

## 3. Non-goals

- automatic repair loopを有効化しない。
- paper archive内から repairを実行しない。
- LLMにresolver kind、authority、budget、success判定を自由決定させない。
- catalog/provider/Harnessを自動promotionしない。
- unavailable evidenceを文章修正だけで factual satisfactionにしない。
- failed repairを削除または成功に上書きしない。

## 4. Repair contract

Each request includes:

- stable request ID and parent context/readiness digests。
- requirement IDs and target claim/config/node IDs。
- action kind and fixed resolver ID/version。
- fixed variables and allowed changes。
- required semantic capabilities/Harness class。
- preconditions、success predicate、stop predicate。
- max nodes/runs/LLM calls/resource units。
- executor owner and authority snapshot digest。
- lifecycle state and immutable attempt records。

The plan aggregate validates that request budgets do not exceed run-level limits。A serialized plan
cannot claim success without an evaluator-produced closure record。

## 5. Readiness-to-repair mapping

| Requirement/gap | Resolver |
|---|---|
| fact exists but projection absent | `projection_rebuild` |
| source/config/EAR missing from index | `artifact_recovery` |
| related-work snapshot insufficient | `recorded_literature_search` |
| baseline absent | `baseline_comparison` |
| stochastic uncertainty absent | `repetition_or_uncertainty` |
| component contribution unsupported | `ablation` |
| contradictory measurement | `validation_experiment` |
| required certification absent/stale | `assurance_certification` |
| method cannot be recovered | `method_clarification` / `human_decision` |
| noncritical gap accepted transparently | `limitation_disclosure` |

Mapping is fixed by requirement/profile and evidence state。Paper reviewer free text is not sufficient
input unless a fixed parser/validator maps it to an existing requirement with evidence refs。

## 6. Request identity and deduplication

```text
request_id = sha256(
  source_context_digest,
  sorted requirement IDs,
  action kind,
  semantic target,
  fixed variables,
  success predicate version
)
```

Equivalent requests share identity。A new source context may produce a new request even when the
human label is the same。Retry creates a child execution attempt under the same request when policy
allows; it does not rewrite prior failure。

## 7. Authority and budget

Repair inherits and binds:

- Knowledge lock。
- Capability/Provider binding and tool allowlist。
- Harness catalog/contract selection policy。
- data/source access policy。
- runtime environment/resource policy。
- research contract and allowed experimental variable set。

No resolver may request a broader provider/tool/Harness by fallback。Unavailable capability yields a
typed unavailable/human outcome。

Initial budget fields:

```yaml
manuscript:
  repair:
    policy: explicit
    max_rounds: 2
    max_new_nodes: 8
    max_experiment_runs: 12
    max_llm_calls: 8
    on_exhaustion: block
```

Explicit mode does not automatically execute on `ari run`/`resume`; a command or already-authorized
invocation names requests。

## 8. Resolver behavior

### 8.1 Projection/artifact

Runs deterministic rebuild/re-index operations。It cannot alter measurement bytes。Recovered files
must match known digest or receive explicit new source identity and trigger a new context。

### 8.2 Literature

Records query、provider semantic ID、parameters、result order、document metadata/digests、cache
behavior。Resume reuses recorded results unless user explicitly starts a new retrieval revision。

### 8.3 Assurance

Invokes only admitted fixed Harness path。Certification closure is decided by recompiled readiness
against the new attestation, not by the command exit code alone。

### 8.4 Experiment

Materializes targeted pending nodes carrying request/requirement lineage, then uses the normal
research loop。Allowed change set examples:

- baseline: method varies; dataset/metric/environment fixed。
- repetition: seed/repetition varies; method/config fixed。
- ablation: only named component varies。
- validation: fixed contradiction target and comparison protocol。

### 8.5 Disclosure/human

Disclosure produces a mandatory brief item, not fabricated evidence。Human decision remains blocking
until an admitted decision record is supplied。

## 9. Transaction and resume

```text
planned
  -> admitted
  -> materialized
  -> executing
  -> evidence_ready
  -> reassessed
       -> satisfied
       -> failed
       -> exhausted
       -> still_missing
```

Each transition is append-only/hash-bound。On resume, coordinator verifies the last committed
transition and idempotency token before continuing。Work created after the last commit is reconciled
by artifact identity, never blindly repeated。

## 10. CLI behavior

### `ari manuscript plan-repair`

Read-only with respect to research/external systems; builds/persists a deterministic plan from current
readiness。Shows authority, budget, expected mutation, and human-required requests。

### `ari manuscript repair`

Requires checkpoint and optional request IDs。Before mutation it prints/records exact admitted scope。
Projection-only rebuild may run without research runtime; experiment repair requires a resumable run
context。`ari paper` cannot execute experiment requests。

Machine result distinguishes `satisfied|still_missing|failed|exhausted|human_required`。

## 11. Tests

- Request schema/digest/duplicate/coherence tests。
- Fixed mapping table coverage。
- Authority snapshot tamper and broader-tool denial。
- Per-request/run budget reservation and exhaustion。
- Projection recovery cannot change measurement bytes。
- Recorded literature cache/resume/no-network tests。
- Assurance unavailable and exact certification tests when provider exists。
- Baseline/repetition/ablation/validation allowed-change tests。
- Every transaction interruption point resume test。
- Same request executes at most once per admitted attempt。
- Reassessment, not executor return, closes a requirement。
- Human decision cannot auto-resolve。
- `ari paper` experiment repair denial。

## 12. Completion criteria

1. Every emitted repair request traces to typed requirements/evidence and stable source context。
2. Resolver mapping、success predicate、authority、budget are fixed and digest-bound。
3. No repair broadens run-frozen Knowledge/Capability/Harness/data authority。
4. Projection/literature/assurance/experiment/disclosure/human classes have explicit behavior。
5. Experiment repair uses normal research run/resume, not paper-stage direct tool execution。
6. All configured limits terminate execution and produce a typed outcome。
7. Interruption/resume is idempotent at every transaction boundary。
8. Closure is based on fresh context/readiness re-evaluation。
9. Explicit CLI surfaces exact mutation scope and machine-readable result。
10. G6 evidence is ready for Task 08 auto-loop composition。

## 13. Deletion criteria

This plan may be deleted only when:

1. Completion criteria are satisfied, merged, and CI green。
2. Repair contracts/mapping/authority semantics are in permanent reference docs。
3. CLI mutation and rollback/recovery behavior is in an operator runbook。
4. Budget and idempotence invariants are permanent tests。
5. Each resolver has a permanent owner and integration documentation。
6. Tasks 08–09 no longer rely on this prose as their only repair specification。
7. No unresolved repair safety issue remains only in temporary plan notes。
8. `INDEX.md` records deletion status and reason。

## 14. Delete-after checklist

- [ ] Repair schema/reference is permanent。
- [ ] Readiness-to-repair mapping is code/test-owned。
- [ ] Authority non-escalation tests are green。
- [ ] Budget termination tests are green。
- [ ] Interruption/resume matrix is green。
- [ ] CLI operator runbook is published。
- [ ] Resolver ownership is recorded permanently。
- [ ] Main merge and CI revision are recorded。
- [ ] Downstream prose-only dependencies are removed。
- [ ] `INDEX.md` is updated before deletion。

## 15. Handoff

Task 08 wraps this explicit transaction in an outer automatic policy without changing resolver
semantics。Task 09 reports all repair lineage/cost/exhaustion in evaluation and publication audit。
