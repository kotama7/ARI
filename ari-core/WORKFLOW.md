# ARI Workflow Developer Guide

## Overview

`workflow.yaml` is the **single configuration file** for the ARI post-BFTS pipeline.  
`ari-core` is a generic engine — all domain logic lives in skills and `workflow.yaml`.

## Architecture

```
ari-core/config/workflow.yaml   ← developer config (YOU EDIT THIS)
ari-core/ari/pipeline.py        ← generic DAG engine (no domain knowledge)
ari-skill-*/src/server.py       ← independent MCP skill servers
```

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
| `skip_if_exists` | — | Skip stage if this file already exists (caching) |
| `load_inputs` | — | Input keys to read as file content before calling |
| `description` | — | Human-readable note (ignored by engine) |

## Template Variables

| Variable | Value |
|---|---|
| `{{ckpt}}` | Checkpoint directory (absolute path) |
| `{{context}}` | Experiment summary text from BFTS |
| `{{keywords}}` | Auto-extracted search keywords |
| `{{stages.X.output}}` | Primary output path of stage X |
| `{{stages.X.outputs.key}}` | Named output `key` of stage X |

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
    path: /absolute/path/to/ari-skill-my
    description: What this skill does  # LLM exception if applicable

# Step 2: Add a pipeline stage:
pipeline:
  - stage: my_stage
    skill: my-skill
    tool: my_tool_function
    enabled: true
    depends_on: [write_paper]
    inputs:
      paper_path: '{{ckpt}}/full_paper.tex'
    outputs:
      file: '{{ckpt}}/my_output.json'
    load_inputs: []
```

**ari-core needs no code changes.**

## Design Principles

- **P1 — Domain-agnostic core**: `ari-core` has zero domain knowledge. No benchmark names, metric names, cluster names, or file formats hardcoded.
- **P2 — Deterministic skills**: Skills are pure MCP tools (same input → same output). Three **explicit LLM exceptions**: `plot-skill`, `paper-skill`, `paper-re-skill`.
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
| Force re-run | Delete the `skip_if_exists` file, resubmit |
| Add a figure | Increase `n_figures` in `generate_figures` inputs |
| Change venue | Edit `venue` in `write_paper` inputs |
| Change LLM model | Set `LLM_MODEL` env var in the SLURM script |
