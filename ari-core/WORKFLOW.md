# ARI Workflow Developer Guide

## Overview

`workflow.yaml` is the **single configuration file** for the ARI post-BFTS pipeline.  
`ari-core` is a generic engine — all domain logic lives in skills and `workflow.yaml`.

## Architecture

```
ari-core/config/workflow.yaml   ← developer config (YOU EDIT THIS)
ari-core/ari/pipeline/          ← generic DAG engine (no domain knowledge)
    orchestrator.py             ←   entry point, thin wrapper over the driver
    driver.py                   ←   pre-flight, template vars, cursor loop, rewind
    stages.py / stage_runner.py ←   per-stage lifecycle and invocation
ari-skill-*/src/server.py       ← independent MCP skill servers
```

The engine was a single `pipeline.py` until v0.7.1 split it into the package
above; that filename no longer exists.

## Stage Fields Reference

| Field | Required | Description |
|---|---|---|
| `stage` | ✅ | Unique stage name (used in `{{stages.<name>.*}}` references) |
| `skill` | ✅ | Skill name from `skills` registry |
| `tool` | ✅ | MCP tool function name inside that skill |
| `enabled` | ✅ | `true`/`false` — quick toggle without deleting |
| `depends_on` | ✅ | List of stage names that must complete first (DAG) |
| `inputs` | ✅ | Tool arguments; supports `{{templates}}` |
| `outputs` | ✅ | Named output paths; `file` = primary output |
| `segment` | ✅ | `evidence` / `authoring` / `verification` — the unit Manuscript Complete selects and records (`ManuscriptSegmentRecordV1`). Shipped split: 7 / 1 / 23 |
| `phase` | ✅ | Present on all 31 stages, all set to `paper`. Note that `phase` on a **skill** entry is what the MCP phase filter reads; the stage-level key is carried for symmetry and no pipeline module reads it |
| `description` | ✅ | Human-readable note (ignored by engine) |
| `skip_if_exists` | — | Skip stage if this file already exists (caching) |
| `skip_if_inputs_unchanged` | — | Skip when the declared inputs are byte-identical to the last run |
| `load_inputs` | — | Input keys to read as file content before calling |
| `params` | — | Extra non-tool parameters read by the stage lifecycle |
| `loop_back_to` + `loop_threshold` + `loop_max_iterations` | — | Rewind the cursor to an earlier stage while a score stays below threshold |

All 31 shipped stages carry `segment`, `phase` and `description`; a new stage that
omits `segment` is invisible to Manuscript Complete's segment selection.

## Template Variables

| Variable | Value |
|---|---|
| `{{checkpoint_dir}}` | Checkpoint directory (absolute path). **Use this one** — the shipped `workflow.yaml` uses it 130 times |
| `{{ckpt}}` | Alias for the same value, kept for older configs; used nowhere in the shipped file |
| `{{ari_root}}` | Repository root — `$ARI_ROOT`, else three parents up from `driver.py` |
| `{{run_id}}` / `{{experiments_root}}` | Resolved through `PathManager`; empty strings when it cannot resolve them |
| `{{context}}` / `{{experiment_summary}}` | Experiment summary text from BFTS (two names, one value) |
| `{{paper_context}}` / `{{idea_context}}` | Paper and idea context blocks |
| `{{keywords}}` | Auto-extracted search keywords |
| `{{primary_metric}}` / `{{higher_is_better}}` | From the run's evaluation criteria, as strings |
| `{{slurm_partition}}` | From `workflow.yaml`; resolved at runtime via `ARI_SLURM_PARTITION` |
| `{{experiment_source_file}}` | `$ARI_SOURCE_FILE`, else empty |
| `{{author_name}}` / `{{launch_config}}` | Defaults, overridable from `workflow.yaml` |
| `{{stages.X.output}}` | Primary output path of stage X |
| `{{stages.X.outputs.key}}` | Named output `key` of stage X |

The table is not a closed set. `driver.py` also exposes **every top-level
string/int/float key of `workflow.yaml`** under its own name, and **every
top-level dict section** (`resources`, `bfts`, …) for dot-notation access — so
adding a scalar to the top of `workflow.yaml` makes `{{that_key}}` usable
immediately, with no engine change.

## load_inputs

When a tool expects **file content** (not a path), declare it in `load_inputs`:

```yaml
load_inputs:
  - refs_json              # pipeline reads file and passes JSON string
  - figures_manifest_json  # same
```

All other inputs are passed as-is (path stays a path).

## Adding a New Skill

```yaml
# Step 1: Register under skills:
skills:
  - name: my-skill
    path: '{{ari_root}}/ari-skill-my'   # every shipped entry is templated, not absolute
    description: What this skill does   # say so here if it calls an LLM
    phase: paper                        # or bfts / reproduce, or a list of them —
                                        # this is what the MCP phase filter reads

# Step 2: Add a pipeline stage:
pipeline:
  - stage: my_stage
    segment: verification               # evidence / authoring / verification
    skill: my-skill
    tool: my_tool_function
    description: What this stage produces
    depends_on: [write_paper]
    enabled: true
    phase: paper
    inputs:
      paper_path: '{{checkpoint_dir}}/full_paper.tex'
    outputs:
      file: '{{checkpoint_dir}}/my_output.json'
    load_inputs: []
```

**ari-core needs no code changes.**

## Design Principles

- **P1 — Domain-agnostic core**: `ari-core` has zero domain knowledge. No benchmark names, metric names, cluster names, or file formats hardcoded.
- **P2 — Deterministic skills**: Skills are pure MCP tools (same input → same output), *where they can be*. The exception list is no longer three: **nine** of the thirteen registered skill packages reach an LLM from their server code — `paper`, `paper-re`, `plot`, `replicate`, `idea`, `transform`, `vlm`, `evaluator` and `web`. For the last two the call sits on a subset of tools, which is why the README's skill table marks them `△` rather than `✓`. `web-skill` is the sharpest case: its `workflow.yaml` description says "deterministic, no LLM", and its retrieval path is — but it also exposes `rerank_retrieval_records`, an explicitly stochastic reranker that deterministic retrieval never calls. Read `skill.yaml` and the README table for per-tool detail; determinism is a property of a tool here, not of a package.
- **Loose coupling**: Stages share data only via `outputs` declarations and `{{stages.*}}` templates.
- **Composability**: Reorder, disable, or add stages entirely in `workflow.yaml`.
- **Reproducibility principle**: Paper generation describes hardware via technical specs (architecture, core count, compiler version), not deployment identifiers.
- **Web access is phase-gated**: `web-skill` is exposed only in the `paper`/`reproduce` phases so the BFTS search loop stays reproducible (live search results are time-varying). `idea-skill`'s `survey` covers the one bounded literature lookup needed at idea time. Opt into web search *during* exploration with `ARI_BFTS_ALLOW_WEB=1` (or `bfts.allow_web: true`); ARI then records a non-reproducible-trajectory marker (`bfts_web_provenance.json`).

## LLM Exceptions to P2

| Skill | Reason |
|---|---|
| `paper-skill` | Full paper writing requires LLM reasoning (AI Scientist v2 loop) |
| `plot-skill` | Figure code generation requires LLM (matplotlib code synthesis) |
| `paper-re-skill` | Two LLM steps: the replicator agent in `build_reproduce_sh` and the SimpleJudge in `grade_with_simplejudge` |

## Reproducibility Check (ORS chain)

There is no single reproduce-from-paper tool. Reproducibility is a chain of
`workflow.yaml` stages, each bound to one real MCP tool:

| Stage | Skill → tool | Output |
|---|---|---|
| `ors_generate_rubric` | `replicate-skill → generate_rubric` | `ors_rubric.json` |
| `ors_audit_rubric` | `replicate-skill → audit_rubric` | a separate audit document; the rubric is never mutated |
| `ors_seed_sandbox` | `paper-re-skill → fetch_code_bundle` | `repro_sandbox/` seeded from the published EAR bundle (no LLM call) |
| `ors_build_reproduce` | `paper-re-skill → build_reproduce_sh` | `repro_sandbox/reproduce.sh` (LLM replicator; skipped when the seed already produced one) |
| `ors_run_reproduce` | `paper-re-skill → run_reproduce` | `ors_phase1.json` — sandboxed execution of `reproduce.sh`, network denied by default |
| `ors_grade` | `paper-re-skill → grade_with_simplejudge` | `ors_grade.json` — PaperBench SimpleJudge over the rubric leaves |

The LLM appears in exactly two places in this chain: the replicator inside
`build_reproduce_sh` and the judge inside `grade_with_simplejudge`.

## Common Operations

| Task | How |
|---|---|
| Disable a stage | `enabled: false` |
| Force re-run | Delete the stage's `skip_if_exists` file. Only 2 of the 31 stages declare one; a third uses `skip_if_inputs_unchanged`, which re-runs by itself once an input's bytes change |
| Add a figure | Increase `n_figures` in `generate_figures` inputs |
| Change venue | Edit `venue` in `write_paper` inputs |
| Change LLM model | Set `ARI_LLM_MODEL` (or `ARI_MODEL`). **Not `LLM_MODEL`** — that bare name is a cross-skill fallback read only by `ari-skill-transform` and `ari-skill-plot`, so setting it changes two skills and leaves the rest on the configured model. Per-role overrides (`ARI_MODEL_PAPER`, `ARI_MODEL_EVAL`, …) are in `docs/reference/environment_variables.md` |
