---
sources:
  - path: ari-core/ari/config/__init__.py
    role: implementation
  - path: ari-core/ari/cli/manuscript.py
    role: implementation
  - path: ari-core/ari/cli/manuscript_repair_runtime.py
    role: implementation
  - path: ari-core/ari/cli/paper_dispatch.py
    role: implementation
  - path: ari-core/ari/manuscript/runtime.py
    role: implementation
  - path: ari-core/ari/manuscript/state.py
    role: implementation
  - path: ari-core/ari/manuscript/repair.py
    role: implementation
  - path: ari-core/ari/manuscript/segments.py
    role: implementation
  - path: ari-core/ari/manuscript/evaluation.py
    role: implementation
  - path: ari-core/ari/manuscript/contracts.py
    role: schema
  - path: ari-core/ari/pipeline/driver.py
    role: implementation
  - path: ari-core/ari/rqgm/paper_runtime.py
    role: implementation
  - path: scripts/evaluate_manuscript_complete.py
    role: implementation
  - path: scripts/run_manuscript_complete_release.py
    role: implementation
  - path: scripts/manuscript_complete_release_gates.json
    role: config
  - path: .github/workflows/manuscript-complete.yml
    role: config
  - path: ari-core/tests/test_manuscript_complete.py
    role: test
  - path: ari-core/tests/fixtures/manuscript_complete/factory.py
    role: test
last_verified: 2026-08-09
---

# Manuscript Complete operator runbook

## Activation

The default is exact legacy identity:

```yaml
manuscript:
  mode: off
  profile: generic_empirical_v1
  repair:
    policy: disabled
```

Use `audit` to measure gaps without changing writer inputs. Use `enforce` to
stop before authoring. Automatic repair is valid only under enforce:

```yaml
manuscript:
  mode: enforce
  profile: generic_empirical_v1
  brief_character_budget: 24000
  repair:
    policy: auto
    max_rounds: 2
    max_new_nodes: 8
    max_experiment_runs: 12
    max_llm_calls: 8
    on_exhaustion: block
```

Environment overrides are `ARI_MANUSCRIPT_MODE` and
`ARI_MANUSCRIPT_REPAIR_POLICY`. Mid-attempt profile, mode, workflow, KCA lock,
or authority changes are not reconciled silently; compile a new attempt.

## Inspection and explicit repair

```bash
ari manuscript compile CHECKPOINT --mode audit
ari manuscript status CHECKPOINT --fail-if-blocked
ari manuscript inspect CHECKPOINT --requirement MC-RP-002
ari manuscript inspect CHECKPOINT --lane contextual_negative
ari manuscript plan-repair CHECKPOINT --config CHECKPOINT/workflow.yaml
ari manuscript repair CHECKPOINT --request REPAIR_ID
```

`plan-repair` performs no external action. `repair` records its exact admitted
scope first, then uses the resumable research runtime. Experiment requests
become one bounded node carrying request IDs, requirement IDs, source context,
fixed variables, and allowed changes. RQGM and KCA hooks run normally when
configured. Completion is decided only by a fresh context/readiness compile,
never by an executor exit code.

Projection/artifact rebuilds may consume zero experiment budget. Retrieval is
recorded in `related_refs.json`. Disclosure creates
`manuscript_disclosures.json` and remains a disclosure, not factual evidence.
Method and policy decisions that require a person remain `human_required`.

`ari paper` deliberately has no research executor. If an existing checkpoint
needs an experiment repair, use `ari resume` or the explicit command above.

## Resume and recovery

Segment records and request transactions are immutable. On restart, a fresh
completed segment is reused. An already committed repair request is not called
again; the coordinator first rebuilds evidence and reassesses it. Cumulative
node/run/call use is recovered from transaction records.

The automatic loop always stops, and it stops for exactly one reason. That
reason is the `termination_reason` on the loop's return value, and it is not
persisted. Only some stops also leave a record in the transition chain: the
terminating transition `automatic_repair_<reason>` is appended only when its
target state is a legal successor of the state the store currently holds. When
it is appended it references by digest the attempt's `readiness.json`, where
the outstanding requirements stay readable. Cumulative node/run/call/resource
use is carried in every committed round record under `auto-rounds/`.

| Termination reason | Condition | Target state | Appended to the chain |
|---|---|---|---|
| `authoring_ready` | readiness reached `ready` or `ready_with_disclosures` | none | no; authoring proceeds |
| `no_admitted_repair_request` | the compile produced no readiness report, no repair plan, or a plan with no requests | `blocked_unavailable` | yes, unless the compile had already written `blocked_unavailable` |
| `human_decision_required` | no request was executed or satisfied and at least one returned `human_required` | `blocked_unavailable` | yes |
| `required_resolver_unavailable` | no request was executed or satisfied, and none was `human_required` or `exhausted` | `blocked_unavailable` | yes |
| `cumulative_budget_exhausted`, after a round | no request was executed or satisfied and one reported `exhausted` | `repair_pending` | yes |
| `cumulative_budget_exhausted`, before a round | recovered use exceeds `max_new_nodes`, `max_experiment_runs`, `max_llm_calls`, or `max_resource_units` | `repair_pending` | no |
| `round_budget_exhausted` | committed round records reached `repair.max_rounds` | `repair_pending` | no |
| `no_progress_cycle` | the same source context digest and the same requirement-status vector recurred | `repair_pending` | no |

The last three rows are the common non-ready stops, and none of them is
recorded. They break at a point where the last compile has already written
`repair_pending`, and `repair_pending` is not a legal successor of itself, so
nothing is appended. Do not grep the chain for
`automatic_repair_no_progress_cycle` or
`automatic_repair_round_budget_exhausted`; they are never written. Read those
stops from the loop's return value, or reconstruct them from the committed
round records under `auto-rounds/` and the attempt's `readiness.json`.
Persisting the reason for them is designed but not implemented:
`ManuscriptAutoRepairRoundV1` carries the round, its plan and source context
digests, its request IDs and transaction digests, its per-request results, and
the used budget, but no termination-reason field, and no other artifact records
one.

No progress is decided on the source context digest and the
`(requirement_id, status)` vector alone. Reworded prose, a new draft, or a
differently phrased summary is not progress; only changed evidence is. Because
the terminating transition is appended only when it is legal from the current
state, a stopped loop never rewrites a state the compiler already owns.

A crash can land between a committed round and its evidence rebuild. On the
next invocation the loop recognises that the current plan digest already has a
committed round record and closes that round exactly once: it re-runs the
evidence rebuild and recompiles, and calls no resolver at all. If the
recompiled context digest and requirement-status vector are unchanged, that
reconciliation terminates as `no_progress_cycle` instead of starting a second
identical round.

The same rule holds one level down. A request whose transaction is already
committed is replayed from that record without calling the executor, charged no
fresh budget, and marked as an idempotent reuse carrying the originally charged
amounts. A literature retrieval already recorded in `related_refs.json` is
matched by request digest and reused, which is the idempotency boundary for a
crash after the provider call but before the transaction record: resuming needs
no provider call and issues no duplicate query.

If a run stops in `repair_pending`, inspect outstanding requirements and the
budget. `blocked_unavailable` requires an admitted capability, Harness, or human
decision; do not delete the state file. After `no_progress_cycle`, change source
evidence through an explicitly authorized operation, or remain blocked.

For a damaged transition chain or immutable artifact, preserve
`.ari-manuscript/` for audit and start a new checkpoint/attempt. Do not edit a
digest field or replace an attempt file in place.

For `paper.mode: rqgm_archive`, inspect
`paper_archive_state.json.manuscript_authoring` and the Manuscript fields on
`paper_draft_archive.jsonl`. `manuscript_bound_winner` means the archive winner
used the current fixed bundle. `bound_linear_fallback` means archive generation
failed but the linear backend consumed that same bundle.
`audit_legacy_archive_winner` and `audit_legacy_linear_fallback` are explicitly
not Manuscript Complete authoring. `stale_detected` or
`authoring_backend_failed` must not be cleared by editing state; compile a new
attempt or resume with the original immutable bundle. Staleness is decided
before the archive's first writer call, and it covers more than a changed
fingerprint: `stale_reasons` records `input_fingerprint_changed`,
`manuscript_mode_changed` when the same durable archive was previously driven
under a different `manuscript.mode`, `preexisting_archive_has_no_binding_state`
when drafts already exist but no `manuscript_authoring` block was ever written
for them, and `draft_binding_mismatch:<epoch_id>:<node_id>` for the first
archived draft carrying a different fingerprint. Under enforce any reason stops
the run before another writer call. Under audit the reasons are recorded,
archive continuation is skipped for that invocation, and the run degrades to
the linear pipeline, so the retained `stale_reasons` — not the status, which
then becomes `audit_legacy_linear_fallback` — is the audit surface. Switching
`manuscript.mode` from `audit` to `enforce` on a checkpoint whose archive has
already run is therefore a blocked resume, not a silent upgrade; compile a new
attempt. `verification_or_fallback_failed` means the bundle was consumed but the
shared verification tail — or the linear fallback itself — raised; read
`failure_reason`, plus `winner_id` and `winner_tex_sha256` when a best-belief
winner had already been recorded. `bound` and
`audit_legacy_authoring_observed` are not outcomes at all: they are written
before the archive generates anything, `bound` under enforce and
`audit_legacy_authoring_observed` under audit, so a checkpoint still holding one
of them stopped before its outcome was recorded — read it as an interrupted run,
not as a result. Which outcome an archive generation failure produces is fixed
by the manuscript mode and by the fallback the caller passed in, never by the
exception that caused the failure. Under `manuscript.mode: off` the archive
keeps its legacy fail-open posture: the error is logged, the run degrades to
the ordinary linear paper pipeline, and no `manuscript_authoring` block is
written at all. Under `audit` it degrades and records
`audit_legacy_linear_fallback`. Under `enforce` it may degrade only to a
fallback explicitly marked as consuming the same already-validated binding;
`ari run`, `ari resume`, and `ari paper` all pass a marked fallback whenever the
manuscript axis is on, so an enforce archive failure lands on
`bound_linear_fallback`, while `authoring_backend_failed` is the fail-closed
outcome when the archive runtime is driven directly with an unmarked fallback —
nothing is authored and the run stops. Within enforce no setting selects
between degrading and stopping — that is decided by the marker alone, and
`manuscript.mode`, `manuscript.profile`, `manuscript.brief_character_budget`,
and `manuscript.repair.*` are the entire manuscript configuration surface. An archive round that produced no admissible candidate is
itself an archive failure and takes that same path. A hard-disqualified draft is
retained for audit and can never be selected by raising its reviewer score.

## Publication

```bash
ari manuscript explain-publication CHECKPOINT
ari manuscript lock-publication CHECKPOINT
```

The lock command re-hashes all sources, bound manuscript inputs, PaperBuild
artifacts, reproduction evidence, and the final PDF. Any change after the
decision returns a non-zero result and writes no lock.

### Reading a decision

`explain-publication` prints the attempt ID, the decision and its digest, the
PaperBuild digest, and every sub-verdict — its gate, its
`pass`/`fail`/`not_required` status, its reason codes, and the artifact digests
it recorded. Reason codes are written only for a failed gate, and the
`freshness` gate carries no artifact digest at all. The command exits `2`
whenever the decision is not `publishable`, so it reads as a gate in a script.

An attempt with no `publication_decision.json` is reported as
`decision: not_evaluated`, `reason: publication_decision_missing`, plus the
attempt ID, and also exits `2`. That is not a blocked decision — nothing was
evaluated. The decision is written by the paper pipeline itself, at the tail of
a run whose manuscript axis is on and whose stage list contains
`lock_paper_build` or `ors_run_reproduce`; the finalizer also returns without
writing anything when `paper_build.json` is absent or the context, readiness,
or binding path variables are unset. A missing decision therefore means that
tail never ran. Re-run the pipeline under `audit` or `enforce`; do not
hand-write the file.

### Why a lock is refused

`lock-publication` writes no `publication_lock.json` and reports
`locked: false`, the attempt ID, and a single `reason` string, exiting `2`.
The checks run in the order below and the first one to fail is the reported
reason.

| `reason` | Cause |
|---|---|
| `publication lock requires an exposed authoring binding` | the attempt's `authoring_binding.json` is missing, or its path leaves the checkpoint or traverses a symlink |
| `blocked publication decision cannot be locked` | the recorded decision is `blocked` |
| `publication decision no longer names the current build` | the decision's PaperBuild digest, authoring-binding digest, run ID, or attempt ID disagrees with the current `paper_build.json` and binding |
| `publication attempt is not finalized` | the manuscript state file names a different attempt, or its state is not `finalized` |
| `publication inputs changed after decision` | a snapshotted source, a nested PaperBuild artifact, or a bound manuscript input no longer matches its recorded digest and size |
| `publication reproduction evidence is stale` | the `reproduction` sub-verdict is not `pass`, or `ors_phase1.json` is missing, is reached through a symlink, or no longer hashes to a digest that sub-verdict recorded |
| `publication build does not identify one final PDF` | the build's final artifacts contain zero or more than one `pdf` role — a single compile PDF artifact substitutes only when there is no final one at all |

The freshness row is the widest of the seven. It also fails when a source the
snapshot recorded as `missing` now exists, when a path-bearing source carries
no digest or size and so has no stable byte identity, when the build declares
two different identities for the same artifact role and path, or when the five
bound manuscript inputs — requirement profile, context, readiness, section
briefs, authoring binding — are not exactly the attempt-directory files the
build recorded under those roles, or their profile/context/readiness/brief
digest lineage no longer agrees, or the bound readiness report's authoring
verdict is neither `ready` nor `ready_with_disclosures`. Any of those paths
reached through a symlink fails the same way.

Malformed or unreadable contract files surface identically: the underlying
`OSError` or schema validation error becomes the `reason` and the exit stays
`2`.

Only `enforce` writes the `finalized` state, so a decision produced under
`audit` is a shadow decision: `explain-publication` reads it, and
`lock-publication` refuses it as not finalized. That is the intended audit
posture, not a defect.

No refusal here is cleared by editing a state field or a digest. Recompile a
new attempt, or resume with the original immutable bundle.

## Rollback, privacy, and retention

Set `manuscript.mode: off` to return future invocations to the legacy path. This
does not erase prior attempts. `.ari-manuscript` can contain research questions,
failed-result summaries, paths, provider identities, and model-bound briefs;
treat it with the checkpoint's data classification. Authority snapshots contain
identities and digests, never credential values. Redact or delete a checkpoint
only through the same retention process used for its research artifacts.

## Release evaluation

Labelled fixture campaigns can be reduced to the permanent report contract:

```bash
PYTHONPATH=ari-core python scripts/evaluate_manuscript_complete.py \
  evaluation-cases.json --output manuscript-evaluation.json
```

The input is a JSON list (or an object with `dataset_id` and `cases`). Ratios
with no applicable cases remain `not_applicable`; retain the report alongside
the topology, failure-injection, and authentic Harness evidence used for a
release decision.

For a bare JSON list, pass `--dataset-id DATASET_ID`. The seven synthetic
baseline classes are generated by
`ari-core/tests/fixtures/manuscript_complete/factory.py`; regenerate and verify
them with:

```bash
PYTHONPATH=ari-core pytest -q \
  ari-core/tests/test_manuscript_complete.py::test_baseline_fixture_classes_are_executable \
  ari-core/tests/test_manuscript_complete.py::test_executable_fixture_expectations
```

Generated values are test-only and carry `SYNTHETIC_FIXTURE.json`; they are not
retained scientific or Harness evidence.

## Release gate and retained CI evidence

Run the closed release manifest only from a clean committed revision. Keep the
output outside the worktree:

```bash
release_dir="$(mktemp -d)"
PYTHONPATH=ari-core python scripts/run_manuscript_complete_release.py \
  --output-dir "$release_dir" --require-clean --keep-going
```

The report is `release_evidence.json`; each check's stdout/stderr is retained
under `logs/` and named by a digest in the report. It covers the 4-topology
publication E2E, all 13 failure-injection families, additive legacy
migration/rollback, permanent schema/snapshot/docs checks, paper/tool-registry
integration, and the checked-in authentic native Harness publication chain.

Pull requests run the same manifest through
`.github/workflows/manuscript-complete.yml` with `--require-ci` and retain the
artifact for 90 days. A local report with a dirty source revision, or a report
outside GitHub Actions when `--require-ci` is used, is deliberately not
`release_eligible`. Synthetic topology fixtures prove wiring and failure
posture only; authentic certification remains the separately retained native
Harness evidence under `ari-core/config/harnesses/evidence/`.

### What `release_eligible` does and does not mean

`release_eligible` is true only when every manifest check ran and passed, the
source revision was clean, and — under `--require-ci` — the run happened inside
GitHub Actions. Those three conditions are the whole of it. It is a necessary
condition for a release, not the release decision.

Two criteria stay with a person and are encoded nowhere in the manifest or the
report: that no unresolved critical or high publication-safety issue is open,
and that an operator has reviewed the blocked, budget-exhaustion, and
human-decision flows. Record both answers next to the retained report so a
later reader can see they were asked.

Release scope is decided the same way, outside the report. A capability may be
described as supported only where authentic retained evidence exists for it. A
Harness scope without that evidence stays unsupported and blocked, and is
documented as unsupported; it does not veto releasing the scopes that are
covered, and it must not be advertised as implemented in release notes,
documentation, or a paper. Nothing in `release_evidence.json` checks any of
this — it binds whoever signs the release.

### Failure-injection blocking matrix

An injection counts as satisfied only when the defect *blocks*. A defect that is
recorded while the publication still locks is a test failure, not a warning. So
every injected fault names the sub-verdict that must read `fail` and the point
at which the flow stops.

| Injected fault | Failing sub-verdict |
|---|---|
| the final PDF is removed after the build record was written | `freshness` |
| `ors_phase1.json` is removed | `reproduction` |
| a required disclosure is absent from the final TeX | `claim_evidence` |
| a contextual-negative evidence ID is cited as support in the final TeX | `claim_evidence` |

The stop is identical in every row: the publication decision is `blocked`, the
named sub-verdict is `fail`, locking raises instead of writing anything, and no
`publication_lock.json` exists under the attempt directory. Through the CLI that
surfaces as `ari manuscript lock-publication` exiting `2` with `locked: false`
and the refusal reason. All four rows are owned by one parametrized test,
`ari-core/tests/test_manuscript_complete.py::test_publication_failure_injection_matrix_blocks_before_lock`,
which the `missing-finalizer-artifact` and
`contextual-negative-used-as-positive-support` injection families both name.

The full set of thirteen families, and the tests that own each one, is
`scripts/manuscript_complete_release_gates.json`. The release runner validates
that manifest before it executes anything: an unknown schema version, a
topology list that is not exactly four unique IDs, a family count other than
thirteen, a duplicate family or check ID, a check without `argv`, or a named
test whose function no longer exists in the tree aborts the run instead of
producing a report.
