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
