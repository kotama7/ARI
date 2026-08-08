---
sources:
  - path: ari-core/ari/rqgm/mode.py
    role: implementation
  - path: ari-core/ari/rqgm/state.py
    role: implementation
  - path: ari-core/ari/rqgm/proposals/records.py
    role: implementation
  - path: ari-core/ari/rqgm/proposals/store.py
    role: implementation
  - path: ari-core/ari/rqgm/paper_mode.py
    role: implementation
  - path: ari-core/ari/rqgm/paper_runtime.py
    role: implementation
  - path: ari-core/ari/rqgm/paper_anchor.py
    role: implementation
  - path: ari-core/ari/paths.py
    role: implementation
  - path: ari-core/tests/test_rqgm_mode.py
    role: test
  - path: ari-core/tests/test_rqgm_proposals.py
    role: test
  - path: ari-core/tests/test_paper_mode.py
    role: test
last_verified: 2026-08-08
---

# Adopting `ari_rqgm` on an Existing Project

How to move an existing ARI project onto the opt-in `ari_rqgm` governance
mode — and back. For the mode semantics themselves (activation keys,
interlock table, kernel) see [Execution Modes](execution_modes.md); for
moving between checkpoint-format *releases* see the
[Migration Guide](migration.md). This page is about switching modes within
one release.

## Step 0: nothing to migrate

Pre-RQGM configs keep working unchanged. `simple_bfts` is the default, and a
`workflow.yaml` with no `ari:`/`rqgm:` blocks (i.e. every pre-RQGM config)
constructs no RQGM object, imports no `ari.rqgm` module, and writes no new
checkpoint file — default checkpoints stay byte-identical to pre-RQGM ARI.
There is no config edit, checkpoint conversion, or re-run required to stay
on `simple_bfts`.

Two compatibility directions:

- **Old checkpoint, new ari-core**: the checkpoint has no `rqgm_state.json`;
  `ari resume` treats absence as `simple_bfts`.
- **New config, old ari-core**: an `rqgm:` block deployed on an older
  ari-core is silently ignored (the safest failure direction).

## Optional stage 1: record-only dual-write (B1)

Before switching modes, you can trial the proposal record store with zero
behavior change:

```yaml
proposal_router:
  record_only: true    # honored in simple_bfts; default false
```

`record_only` is the one `proposal_router.*` key honored under
`simple_bfts`. With it set, the agent-loop's `idea.json` output is
additionally imported into `{checkpoint}/proposals/proposal_records.jsonl`
as `legacy_idea_json` records (`ideas[0]` — today's directive — as
`selected`, the rest as `candidate`; `epoch_id: null` since `simple_bfts`
has no epochs). `idea.json` itself is **not** rewritten, no consumer
changes, and content-key dedup makes repeated imports idempotent. This is
the B1 rung of the [evaluation ladder](rqgm_evaluation.md). Rollback =
delete the flag; the records left behind are inert
(`test_rqgm_proposals.py::test_simple_bfts_record_only_dual_writes`).

## Switching a NEW run to `ari_rqgm`

```yaml
# workflow.yaml (or --config)
ari:
  mode: ari_rqgm
rqgm:
  enabled: true
```

or, per run and GUI-compatible, `ARI_MODE=ari_rqgm ARI_RQGM_ENABLED=1`.
Both keys must agree ([interlock table](execution_modes.md#turning-rqgm-on)).

The effective mode is resolved **once, at run start**, and persisted to
`{checkpoint}/rqgm_state.json` before the first node runs. That file is the
run's mode provenance; its absence means a pure `simple_bfts` run.

**Resume never upgrades.** `ari resume` reconciles through
`ari.rqgm.state.reconcile_resume_mode`, checkpoint-first:

- A checkpoint **without** `rqgm_state.json` started as `simple_bfts` and
  stays `simple_bfts` — requesting `ari.mode: ari_rqgm` (or the env vars) on
  resume logs a warning and the request is ignored; there is no legal
  mid-run upgrade point in the `simple_bfts` loop.
- A checkpoint **with** `rqgm_state.json`: the persisted mode wins over
  package config and env. A disagreement produces a warning, never a
  mid-run mode flip.

Upgrading an existing project therefore means launching a **new run** (or a
child run started with `ARI_MODE=ari_rqgm`) — typically inheriting the
previous run's direction via the existing `inherit_idea_index` /
pinned-`idea.json` mechanism, which RQGM imports as `legacy_idea_json`
records at root ideation.

## `idea.json` ↔ ProposalRecord compatibility

RQGM does not replace `idea.json`; it demotes it to a **projection** of the
proposal record store (`ari/rqgm/proposals/store.py`):

- **The 9-key contract is preserved.** The projected document always keeps
  the top-level keys every existing consumer reads: `gap_analysis`,
  `ideas`, `primary_metric`, `higher_is_better`, `metric_rationale`,
  `papers_analyzed`, `n_agents`, `discussion_rounds`,
  `virsci_integration_status` (`ari.rqgm.proposals.store.IDEA_JSON_KEYS`;
  pinned by
  `test_rqgm_proposals.py::test_projection_nine_key_contract_and_plan_parse`).
- **Single writer.** In `ari_rqgm` the store is the only writer of
  `idea.json`, always deriving it from the records through one function
  (`build_idea_projection`). The `_pinned` / `_inherited_from` /
  `_root_choice` one-shot markers are preserved verbatim across rewrites,
  so cross-run inheritance and root selection keep working.
- **Traceability.** Each projected `ideas[i]` entry carries an
  underscore-key `_proposal_record_id` linking back to
  `proposals/proposal_records.jsonl` (same convention as `_pinned` /
  `_inherited_from`).
- **Typed handoff passes through, title-bound.** When the selected generator
  emitted a typed research-contract document, the projection additionally
  carries its ten typed-handoff keys — `typed_schema_version`,
  `contract_status`, `survey_snapshot`(`_digest`/`_ref`), `idea_set`
  (`_digest`), `research_contract`(`_digest`), `rejected_candidates` — so the
  9 keys above are a floor, not a ceiling. The copy happens **only** when the
  contract's `title` equals the directive `ideas[0].title`, so a typed block
  can never end up describing a direction other than the one `idea.json`
  names.
- **Inverse mapping.** Existing `idea.json` content (a pinned seed, or the
  stage-1 dual-write above) imports losslessly enough to keep riding the
  legacy channels: `summary_from_idea` splits the joined `experiment_plan`
  back into bounded steps with the same `_extract_plan_sections` parser the
  legacy path uses.

## New checkpoint files

An `ari_rqgm` run adds the following. The new checkpoint-root file names are
registered in `PathManager.META_FILES` (`ari/paths.py`), so ARI classifies
them as run metadata — never copied into a node work dir — and the
`proposals/` subtree is additionally blocklisted from node file reports
(pinned by `test_rqgm_proposals.py::test_proposal_filenames_registered` /
`test_proposals_never_in_files_changed`). The subdirectory contents
(`proposals/archive/`, `rqgm_prompts/`, `rqgm/kca/admission-v1/`) are not
name-registered and do not need to be: that copy only iterates
checkpoint-root files. **A `simple_bfts` run writes none
of them** — the only exception is `proposals/`, which appears under
`simple_bfts` iff you opted into `record_only` above.

| Path (under `{checkpoint}/`) | What it is |
|---|---|
| `rqgm_state.json` | Mode provenance: mode, interlock, `mode_source`, switch journal. Absence == pure `simple_bfts` run. |
| `constitution.yaml` | Copy-once, non-evolving human-readable constitution statement. |
| `rqgm_transitions.jsonl`, `rqgm_audit.jsonl` | Append-only event-log truth + governance audit log. |
| `epoch_state.json`, `rqgm_registry.json` | Derived snapshots: current epoch freeze and component/prompt registry. |
| `proposals/` (`proposal_records.jsonl`, `proposal_index.json`, `archive/…`) | Proposal record truth + derived index + raw-output archive. |
| `rqgm_adversarial_cases.jsonl`, `rqgm/adversarial_replay_pool.json` | Adversarial-loop record truth + derived replay-pool snapshot. |
| `prompt_evolution.jsonl`, `prompt_specs.json`, `rqgm_prompts/` | Prompt-evolution record truth, PromptSpec rollup, evolved template bodies. |
| `rqgm_cleanroom.jsonl` | Clean-room regeneration request/screen/fallback events. |
| `rqgm_erasure_state.json` | Derived rollup of the stale/invalid sets from selective erasure. |
| `rqgm_meta_outputs.jsonl` | Meta-agent output records. |
| `rqgm_governance_cache.jsonl` | Governance result cache. |
| `rqgm/kca/admission-v1/` (`run_admission.json` + the pinned contract / catalog / lock set) | The Knowledge–Capability–Assurance run-admission baseline. Written only when the `knowledge` / `capability_binding` / `assurance` modes are off their legacy-inert defaults (`off` / `legacy` / `off`); published by a directory rename, so an interrupted admission can never leave a partial set a resume mistakes for authoritative state. |
| `rqgm_eval_metrics.json`, `rqgm_injection_provenance.json` | Evaluation harness only — never written by a normal run. |

## Rollback

Switching back means starting the next run as `simple_bfts` (or letting an
`ari_rqgm` run downgrade itself at an epoch boundary — the only in-run
switch, downgrade-only). Two properties make rollback safe:

- **Records are inert.** `simple_bfts` code never reads `proposals/` or any
  `rqgm_*` file, so leftover RQGM artifacts in old checkpoints need no
  cleanup and change nothing. The absence gate is structural: the lazy
  import in `ari.core.build_runtime` is the single switch, not per-feature
  flags.
- **Previously erased nodes stay excluded.** Selective erasure is
  logical-only — nothing is deleted; staleness lives in the audit log, the
  `rqgm_erasure_state.json` rollup, and additive `Node.metrics` sentinels
  (`_stale`, `_valid_for_frontier`, …) persisted through `tree.json`.
  `BFTS.should_prune` reads `metrics['_valid_for_frontier'] is False`
  **unconditionally**, and so does best-node selection
  (`verified_context.select_best_node` — the paper/report winner), so a
  node erased under `ari_rqgm` remains pruned and unselectable after a
  switch back — contamination does not become clean by switching modes.
  The sentinel keys are only ever written by RQGM machinery (the
  `ari_rqgm` `FrontierRepairEngine`, the KCA integrity check in
  `RQGMRuntime` — which also marks the node `assurance_status: tampered` /
  `frontier_class: uncertified_frontier` — plus the `rqgm_archive` paper
  runtime on draft nodes), so on a checkpoint that never ran RQGM the
  clauses are inert dead code (the `_sterile` pattern).

## Adopting `paper.mode`

The paper-writing phase (`ari paper`) has its own opt-in axis, `paper.mode:
linear | rqgm_archive`, resolved by `ari.rqgm.paper_mode.resolve_paper_mode`
and **independent of `ari.mode`** — you can adopt the paper archive without
touching exploration, or run epoch governance with the classic linear paper
writer. `linear` (the default) is byte-identical to today's paper pipeline;
absence of `{checkpoint}/paper_archive_state.json` means a pure linear paper
run. Turn the archive on with both keys agreeing:

```yaml
# workflow.yaml
paper:
  mode: rqgm_archive
rqgm:
  paper:
    enabled: true
```

or, per run, `ARI_PAPER_MODE=rqgm_archive ARI_RQGM_PAPER_ENABLED=1` (the `ari
paper` command applies these via `apply_paper_env_overrides`). See the
[interlock table](execution_modes.md#turning-the-paper-archive-on). The mode is
persisted write-once to `paper_archive_state.json`, and `ari paper`
re-invocation reconciles checkpoint-first
(`reconcile_paper_resume_mode`) — the persisted paper mode wins over config and
env, exactly like `rqgm_state.json` for exploration.

### The default is a degraded on-ramp

Turning `rqgm_archive` on does **not** immediately give you the full
co-evolution loop. Two knobs gate it, and both start conservative:

- **The anchor is OFF by default** (`rqgm.paper.anchor.enabled: false`). Without
  an anchor the reviewer has no ground truth to earn trust against, so the
  default `rqgm_archive` is **reviewed best-of-N**: a best-first draft archive
  scored by a single frozen reviewer. To make the reviewer co-evolve, supply a
  curated APReS-equivalent accept/reject corpus and enable it:

  ```yaml
  rqgm:
    paper:
      anchor:
        enabled: true
        corpus_path: paper_anchor_corpus.jsonl   # relative to the checkpoint
  ```

  Each corpus case MUST declare a `label_source` (`human_curated` |
  `gate_bootstrap`); a machine-enforced `max_bootstrap_label_fraction` cap
  (default 0.5, applied to the whole corpus AND the held-out subset) refuses a
  corpus that leans too hard on self-generated `gate_bootstrap` labels. On any
  breach — or a missing/empty/contaminated corpus — the loader degrades to "no
  anchor gate" and **never raises** (`ari/rqgm/paper_anchor.py:load_anchor_corpus`).
  Refusing to anchor is strictly safer than anchoring on self-labels.

- **The default epoch count is deliberately cheap** (`rqgm.paper.epoch.rounds:
  2`). At two rounds the boundary and (under an always-lenient reviewer) the
  impeachment motion FIRE, but the `candidate → validated → shadow →
  probationary_active` climb needs a role opening plus ~5 boundaries, so a
  **full reviewer adoption does not complete** — the active reviewer hash does
  not change. A run that must witness a completed adoption raises `rounds` (the
  co-evolution proof drives 8).

The cheapest posture of all is `rqgm.paper.prompt_evolution.enabled: false`,
which suppresses candidate minting entirely: the roles stay pinned at their
founding v1 prompts and you get reviewed best-of-N at ≈ today's cost.

### New paper-archive checkpoint files

An effective `rqgm_archive` paper run adds, under `{checkpoint}/`:

| Path | What it is |
|---|---|
| `paper_archive_state.json` | Paper-mode provenance: paper mode, interlock, `mode_source`, exploration mode, seed node. The seed records what the FIRST invocation started from; a later invocation that computes a different seed appends a `seed_changed` entry to `seed_journal` instead of rewriting it (`journal_seed_change`). Absence == linear paper phase. |
| `paper_draft_archive.jsonl` | The scored draft population (one record per draft node: framing, reviewer score, tex hash, best-belief/compiled flags). |
| `paper_anchor_corpus.jsonl` | The accept/reject anchor corpus, only if you supply one (read-only; never authored by a governed role). |
| `rqgm/paper_self_preference_stat.json` | The deterministic AI-vs-human self-preference margin the `paper_self_preference` adversary cites as its pre-signal. |

A `linear` paper run writes none of them. Co-evolution additionally rides the
same `rqgm_transitions.jsonl` / `rqgm_registry.json` / `prompt_evolution.jsonl`
files as exploration, since the paper roles are governed through the same inner
RQGM runtime.

### Rolling the paper archive back

Set `paper.mode: linear` (or drop `rqgm.paper.enabled`) on the next `ari
paper`; the linear pipeline is byte-identical and the leftover `paper_*` files
are inert — `linear` code never reads them.

### Honest limits

- **Both prompts co-evolve — the writer only when it REGRESSES.** The
  `paper_writer` prompt co-evolves through the ordinary sanction → role
  opening → T6 path, anchored to the Layer-0 claim-evidence gate's
  deterministic faithfulness. But a writer successor sits at `shadow` until
  the incumbent regresses on that faithfulness: a better challenger alone
  never displaces a faithful incumbent. The writer's *draft* winners remain
  epoch-local (ranked by the in-epoch-frozen reviewer).
- **A writer sanction rides the reviewer's round.** The writer-targeted
  validated attack is emitted by the `paper_self_preference` round, which
  fires only on an over-accepted anchor case; a dedicated writer-adversary
  type is a separate decision.
- The anchor is off by default — which gates the writer too, since its
  faithfulness case is landed on the anchor pool — and the default `rounds: 2`
  does not complete an adoption (above). A first `rqgm_archive` adoption is a
  staged rollout, not a one-flag switch.

## Limitations (v1)

Same as [Execution Modes → Limitations](execution_modes.md#limitations-v1):
profiles (`--profile`) do not merge RQGM keys, and there is no `--mode` CLI
flag. The paper axis shares these: no `--paper-mode` flag, and profiles do
not merge `rqgm.paper.*`. The dashboard can select both mode pairs for a
**new** run ([Execution modes → Selecting the mode from the
GUI](execution_modes.md#selecting-the-mode-from-the-gui)); every other
`rqgm.*` parameter on this page is configuration-file only, and no surface
can change the mode of a run that already started.

See also: [Execution Modes](execution_modes.md) ·
[VirSci Integration](virsci_integration.md) ·
[RQGM Evaluation](rqgm_evaluation.md) ·
[File Formats Reference](../reference/file_formats.md)
