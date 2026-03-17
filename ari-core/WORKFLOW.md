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

## LLM Exceptions to P2

| Skill | Reason |
|---|---|
| `paper-skill` | Full paper writing requires LLM reasoning (AI Scientist v2 loop) |
| `plot-skill` | Figure code generation requires LLM (matplotlib code synthesis) |
| `paper-re-skill` | ReAct reproducibility requires LLM: extract config from paper + write verdict |

## Reproducibility Check (ReAct)

`paper-re-skill → reproduce_from_paper` implements a ReAct loop:

1. **Reason** — LLM reads paper text, extracts claimed compiler flags / thread count / expected metric
2. **Act** — Submits a new SLURM job with those exact settings (source_file from workflow.yaml)
3. **Observe** — Parses actual metric from job output
4. **Reason** — Compares actual vs. claimed → verdict (`REPRODUCED` / `PARTIAL` / `NOT_REPRODUCED`)

⚠️ **Must run on an Ollama-capable node**. The pipeline SLURM job handles this.

## Common Operations

| Task | How |
|---|---|
| Disable a stage | `enabled: false` |
| Force re-run | Delete the `skip_if_exists` file, resubmit |
| Add a figure | Increase `n_figures` in `generate_figures` inputs |
| Change venue | Edit `venue` in `write_paper` inputs |
| Change LLM model | Set `LLM_MODEL` env var in the SLURM script |
