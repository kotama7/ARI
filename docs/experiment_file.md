# Writing Experiment Files

Experiment files (`experiment.md`) describe what ARI should do.  They
live at the root of every checkpoint and are the single source of
domain knowledge for a run — no code changes are required to drive a
new experiment.

## Minimal Example

```markdown
We propose a CSR-format sparse-dense matrix multiplication (SpMM) for
CPUs that maintains high performance even when the right-hand side
matrix size varies.  Build a roofline model from theoretical compute
and memory bandwidth and compare measurements against it.

Metrics: GB/s, GFlops/s
```

That is it.  ARI parses the **`Metrics:`** line as a last-resort source
for `evaluation_criteria.json` (`primary_metric`); the prose body seeds
the LLM-driven `generate_ideas` flow, which fills in the rest of the
plan.

The example above is also a fine **smoke test** on a fresh install:
save it as `experiment.md` and run `ari run experiment.md` to verify
the CLI, `.env` loading, and memory backend end-to-end without
committing to a real research goal yet.

## Recognised Sections

ARI does not require any specific section structure — the file is read
as plain Markdown — but the following headings are conventional and
some are consumed by deterministic helpers:

### `Metrics:` line (required)

```markdown
Metrics: GB/s, GFlops/s
```

`parse_metric_from_experiment_md` (`ari-core/ari/pipeline/experiment_md.py:31`)
extracts the first token (`GB/s` here) and stores it as
`evaluation_criteria.json:primary_metric` when no idea has fixed one
yet.  Plain prose with the words "metric" or "metrics" works too.

### `## Research Goal` (optional, recommended)

A one-paragraph statement of intent, typed in plain English.  The LLM
reads this verbatim during `generate_ideas`; vagueness here propagates
into vague hypotheses.

### `## Required Workflow` (optional)

An ordered list of tool calls if you want to constrain the agent's
sequencing.  Most users let the agent decide and skip this section.

### `## Hardware Limits` / `## Rules` (optional)

Hard constraints in bullet form.  The agent reads these as part of the
system context; the planner respects them when choosing partitions,
compilers, etc.

### `## SLURM Script Template` (optional)

A baseline script the LLM is allowed to mutate.  Only useful if the
benchmark's launch protocol is unusual.

### Magic comments (parsed by helpers)

| Comment | Purpose |
|---------|---------|
| `<!-- min_expected_metric: N -->` | Soft floor used by reviewers |
| `<!-- metric_keyword: NAME -->`   | Hint for the metric extractor |

## v0.6 / v0.7 additions

### Rubric / venue selection (v0.6)

`experiment.md` is the **plan**; the **venue** lives in
`ari-core/config/reviewer_rubrics/<id>.yaml` and is selected via the
`ARI_RUBRIC` environment variable.  The rubric supplies the dimensions
the BFTS judge scores against and the criteria the published review
uses — switching `ARI_RUBRIC` changes both at once.  See
`docs/architecture.md#plan--venue-contract-v070` for the full
two-file contract.

### Auto-appended VirSci block (v0.6)

When `generate_ideas` runs, the pipeline writes a labelled block back
into the checkpoint's `experiment.md`:

```markdown
<!-- AUTO-APPENDED BY VirSci (idea.json) — DO NOT EDIT -->
## Selected idea
...
## Plan §-tags
...
## Alternatives considered
...
<!-- END AUTO-APPENDED -->
```

The block is idempotent (it is rewritten on every promote, never
duplicated).  Edit only the prose **above** the marker; everything
between `BEGIN`/`END` markers is owned by the auto-append helper.

### Lineage-decision recording (v0.7)

`stagnation_rule` watches the BFTS composite-score trajectory.  Once
it fires, the LLM judge picks one of `continue` / `switch_to_idea` /
`fanout` / `terminate` and the decision is appended (one record per
fired decision) to `{ckpt}/lineage_decisions.jsonl`.  No manual edits
to `experiment.md` are required — the catalog of alternative ideas
sits in `idea.json`, and the lineage walk reads `meta.json:parent_run_id`.

### Sub-experiment inheritance (v0.7)

| Channel | Direction | Mechanism |
|---|---|---|
| `venue.md` (rubric) | inherit | `ARI_RUBRIC` env propagates |
| `memory` | inherit | ancestor-scoped read (`ari-skill-memory`) |
| `idea.json` (catalog) | inherit (read-only) | `ari/lineage.py` walks `meta.json:parent_run_id` |
| `plan.md` / `experiment.md` (directive) | **NOT inherited** | child writes its own |

Children are free to pivot; only the catalog and the rubric flow down.

### ORS metadata (v0.7)

The reproducibility flow (`ari-skill-replicate` + `ari-skill-paper-re`)
does not require new fields in `experiment.md` itself — instead, the
checkpoint accumulates artefacts beside it (`ors_rubric.json`,
`ors_grade.json`, `repro_sandbox/`).  See
`docs/architecture.md#publication-lifecycle-v070` for the full
artefact list.

## Where to put `experiment.md`

ARI looks for the file in this order:

1. The active checkpoint's root: `$ARI_CHECKPOINT_DIR/experiment.md`.
2. The argument to `ari run experiment.md` (copied into the checkpoint
   on first launch).

There is no global default and no `$HOME/.ari/` lookup — the v0.5.0
refactor scoped every input file to the checkpoint.

## See also

- `docs/architecture.md#plan--venue-contract-v070` — full two-file
  contract.
- `docs/architecture.md#publication-lifecycle-v070` — what ARI emits
  alongside `experiment.md`.
- `docs/skills.md` — which skills consume which experiment-file
  sections.
