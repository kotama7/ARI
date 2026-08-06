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

If a run stops in `repair_pending`, inspect outstanding requirements and the
budget. `blocked_unavailable` requires an admitted capability, Harness, or human
decision; do not delete the state file. `no_progress_cycle` means the same
context and requirement vector recurred. Change source evidence through an
explicitly authorized operation, or remain blocked.

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
attempt or resume with the original immutable bundle. A hard-disqualified draft
is retained for audit and can never be selected by raising its reviewer score.

## Publication

```bash
ari manuscript explain-publication CHECKPOINT
ari manuscript lock-publication CHECKPOINT
```

The lock command re-hashes all sources, bound manuscript inputs, PaperBuild
artifacts, reproduction evidence, and the final PDF. Any change after the
decision returns a non-zero result and writes no lock.

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
