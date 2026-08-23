---
sources:
  - path: ari-core/ari/pipeline/experiment_md.py
    role: implementation
  - path: ari-skill-evaluator
    role: implementation
  - path: ari-core/ari/agent/workflow.py
    role: implementation
  - path: ari-core/ari/agent/guidance.py
    role: implementation
  - path: ari-core/ari/orchestrator/lineage_decision.py
    role: implementation
  - path: ari-core/ari/lineage.py
    role: implementation
  - path: ari-core/ari/cli/run.py
    role: implementation
  - path: ari-core/ari/core.py
    role: implementation
  - path: ari-skill-paper/src/rubric.py
    role: implementation
  - path: ari-core/ari/cli/bfts_loop.py
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
last_verified: 2026-08-16
---

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

### `Metrics:` line (optional, recommended)

```markdown
Metrics: GB/s, GFlops/s
```

`parse_metric_from_experiment_md` (`ari-core/ari/pipeline/experiment_md.py:30`)
extracts the first token (`GB/s` here) and stores it as
`evaluation_criteria.json:primary_metric` when no idea has fixed one
yet.  Nothing enforces it: with no such line the function returns `""`
and the run proceeds.  The line must *start* with `Metric` or `Metrics`
(case-insensitive) followed by `:` or `-` — the word buried in a prose
sentence does not match.

### `## Success Metrics` section (optional)

```markdown
## Success Metrics
- gflops_per_second: sustained throughput
- l2_hit_rate: cache behaviour
```

The evaluator skill's `_parse_success_metrics` reads this section
**before** the inline `Metrics:` line and takes every `- name:` bullet as
a declared metric, so a `## Success Metrics` section overrides the
`Metrics:` line rather than adding to it.

### `## Research Goal` (optional, recommended)

A one-paragraph statement of intent, typed in plain English.  The LLM
reads this verbatim during `generate_ideas`; vagueness here propagates
into vague hypotheses.

### `## Required Workflow` (optional)

An ordered list of tool calls if you want to constrain the agent's
sequencing.  Most users let the agent decide and skip this section.

### `## Hardware Limits` / `## Rules` (optional)

Hard constraints in bullet form.  No helper parses these *headings* —
they reach the LLM as prose like the rest of the file.  What **is**
parsed deterministically, from anywhere in the document and only when
HPC is enabled, are two free-standing patterns picked up by
`ari/agent/workflow.py`:

```markdown
Partition: <partition-name>
Max CPUs: 64
```

`Partition:` sets `hints.slurm_partition` (otherwise
`ARI_SLURM_PARTITION`, otherwise the first `up` partition `sinfo`
reports); `Max CPUs:` sets the CPU ceiling shown to the LLM (otherwise
`ARI_SLURM_CPUS`).

### `## Provided Files` / `## Local Files` (optional)

Paths, one per line or as a bullet list, are copied by basename into
**every** node's work dir at batch start.  `## 提供ファイル`,
`## 提供文件` and a bare `## Files` are accepted as aliases; a line only
counts when it contains a path separator, and a trailing `# comment` is
stripped.  Two silent skips: a file whose basename is a checkpoint
meta-file (e.g. `results.json`) is never copied, and an existing
destination is never overwritten.

### `## SLURM Script Template` (optional)

A baseline script the LLM is allowed to mutate.  Only useful if the
benchmark's launch protocol is unusual.  Like `## Rules`, no
deterministic helper reads it — it is context for the LLM.

### Magic comments (parsed by helpers)

| Comment | Purpose |
|---------|---------|
| `<!-- min_expected_metric: N -->` | **Hard** floor in the agent loop, not a reviewer hint: when more than one value is extracted and `max(values) < N`, `guidance.py` calls `node.mark_failed()`. Watch the parse — `ari/agent/workflow.py` matches `([\d]+)`, so `2.5` is read as `2`, while the evaluator skill's own parser accepts the decimal. |
| `<!-- metric_keyword: NAME -->`   | Hint for the metric extractor; also the fallback source of `expected_metrics` when no `Metrics:` line or `## Success Metrics` section is present |

## v0.6 / v0.7 additions

### Rubric / venue selection (v0.6)

`experiment.md` is the **plan**; the **venue** lives in
`ari-core/config/reviewer_rubrics/<id>.yaml` and is selected via the
`ARI_RUBRIC` environment variable (default `neurips`).  The rubric
supplies the dimensions the BFTS judge scores against.  The **published
review** is a separate knob: `review_paper` takes its `rubric_id` from
`paper_rubric` in `workflow.yaml` (default `generic_conference`) and
never reads `ARI_RUBRIC`, so switching `ARI_RUBRIC` alone leaves the
review on the generic rubric — set both to judge search and review
against the same venue.  See
`docs/concepts/architecture.md#plan--venue-contract-v070` for the full
two-file contract.

### Auto-appended VirSci block (v0.6)

When `generate_ideas` runs, the pipeline writes a labelled block back
into the checkpoint's `experiment.md`:

```markdown
<!-- AUTO-APPENDED BY VirSci (idea.json) — DO NOT EDIT -->
## Selected research idea
...
## Plan sections (full text in idea.json)
...
## Alternatives considered (not pursued in this run)
...
<!-- END AUTO-APPENDED -->
```

The middle heading follows `workflow.yaml:plan_promote` (default
`index_only`, as shown); `full` emits `## Detailed experiment plan` with
the §-bodies inline, and `off` writes nothing.

The block is written **once**: `_promote_plan_to_experiment_md` returns
immediately when the `AUTO-APPENDED` marker is already present, so a
later promote does not refresh a stale block — delete the marker if you
want it regenerated.  Edit only the prose **above** the marker;
everything between the begin/end markers is owned by the auto-append
helper.

### Lineage-decision recording (v0.7)

`stagnation_rule` watches the BFTS composite-score trajectory.  On
CONFIRMED stagnation ARI first pivots **deterministically** to the
strongest **unused** runner-up idea from `idea.json`
(`switch_to_idea`, tie-broken toward the lower index, with
`disable_generate_ideas`) — so a runner-up is actually tried instead
of dying unused.  The LLM judge (`continue` / `switch_to_idea` /
`fanout` / `terminate`) is consulted only as a **fallback** when no
deterministic pivot is available (budget exhausted, recursion limit
reached, or no unused alternative remains).  The decision is appended
(one record per fired decision) to `{ckpt}/lineage_decisions.jsonl`.
No manual edits to `experiment.md` are required — the catalog of
alternative ideas sits in `idea.json`, and the lineage walk reads
`meta.json:parent_run_id`.

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
`docs/concepts/publication-lifecycle.md#publication-lifecycle-v070` for the full
artefact list.

## Where to put `experiment.md`

ARI looks for the file in this order:

1. The active checkpoint's root: `$ARI_CHECKPOINT_DIR/experiment.md` —
   preferred on resume, because the path recorded in `tree.json` may be
   stale.
2. The argument to `ari run experiment.md` (copied into the checkpoint
   on first launch).  It is a required positional argument: `ari run`
   exits 1 when the path is not a file, so a fresh run never falls back
   to (1).

There is no global default and no `$HOME/.ari/` lookup — the v0.5.0
refactor scoped every input file to the checkpoint.

## See also

- `docs/concepts/architecture.md#plan--venue-contract-v070` — full two-file
  contract.
- `docs/concepts/publication-lifecycle.md#publication-lifecycle-v070` — what ARI emits
  alongside `experiment.md`.
- `docs/reference/skills.md` — which skills consume which experiment-file
  sections.
