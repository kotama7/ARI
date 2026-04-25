# Configuration Reference

## workflow.yaml (Canonical Developer Config)

`workflow.yaml` is the **single source of truth** for the full ARI pipeline.
Place it at `ari-core/config/workflow.yaml`.

Use `{{ari_root}}` in skill paths — it resolves to `$ARI_ROOT` env var or the project root.

```yaml
llm:
  backend: openai          # ollama | openai | anthropic
  model: gpt-5.2           # Model identifier
  base_url: ""             # Leave empty for OpenAI; set for Ollama/vLLM

author_name: "Artificial Research Intelligence"

resources:
  cpus: 48                 # Default CPU count for reproducibility experiments
  timeout_minutes: 60      # Default job timeout
  executor: slurm          # Job executor: slurm / local / pbs / lsf

# BFTS phase stages (executed in order during tree search)
bfts_pipeline:
  - stage: generate_idea
    skill: idea-skill
    tool: generate_ideas
    phase: bfts
  - stage: select_and_run
    skill: hpc-skill
    phase: bfts
  - stage: evaluate
    skill: evaluator-skill
    tool: evaluate_node
    phase: bfts
  - stage: frontier_expand
    skill: idea-skill
    tool: generate_ideas
    phase: bfts
    loop_back_to: select_and_run

# Post-BFTS pipeline stages
pipeline:
  - stage: search_related_work
    skill: web-skill
    tool: collect_references_iterative
    skip_if_exists: '{{ckpt}}/related_refs.json'
    # ...
  - stage: transform_data
    skill: transform-skill
    tool: nodes_to_science_data
    inputs:
      nodes_json_path: '{{ckpt}}/nodes_tree.json'
      llm_model: '{{llm.model}}'
      llm_base_url: '{{llm.base_url}}'
    outputs:
      file: '{{ckpt}}/science_data.json'
    skip_if_exists: '{{ckpt}}/science_data.json'
  - stage: generate_figures
    skill: plot-skill
    tool: generate_figures_llm
    depends_on: [transform_data]
    # ...
  - stage: write_paper
    skill: paper-skill
    tool: write_paper_iterative
    depends_on: [search_related_work, generate_figures]
    # ...
  - stage: review_paper
    skill: paper-skill
    tool: review_compiled_paper
    depends_on: [write_paper]
    # ...
  - stage: reproducibility_check
    skill: paper-re-skill
    # Driven by ari-core/ari/agent/react_driver.py, not a single tool.
    # paper-re provides the deterministic bookends; the ReAct loop runs
    # over MCP skills whose phase list contains `reproduce`.
    pre_tool: extract_repro_config
    post_tool: build_repro_report
    depends_on: [write_paper]
    react:
      agent_phase: reproduce
      max_steps: 40
      final_tool: report_metric
      # Keep the agent out of the checkpoint root; path validation rejects
      # any tool argument that references files outside this directory
      # (plus an allow-list for the paper .tex).
      sandbox: '{{checkpoint_dir}}/repro_sandbox'
      system_prompt: |
        You are a reproducibility engineer...
      user_prompt: |
        Target: reproduce {{pre.metric_name}} = {{pre.claimed_value}}
        ...

retrieval:
  backend: semantic_scholar    # semantic_scholar | alphaxiv | both
  alphaxiv_endpoint: https://api.alphaxiv.org/mcp/v1

# ── Paper review (rubric-driven, AI Scientist v1/v2-compatible) ────────
# Override via CLI (--rubric, --fewshot-mode, --num-reviews-ensemble,
# --num-reflections) or environment variables (ARI_RUBRIC,
# ARI_FEWSHOT_MODE, ARI_NUM_REVIEWS_ENSEMBLE, ARI_NUM_REFLECTIONS).
# Bundled rubrics (16 YAMLs in ari-core/config/reviewer_rubrics/):
#   neurips (default, v2-compatible) | iclr | icml | cvpr | acl | sc | osdi
#   | usenix_security | stoc | siggraph | chi | icra | nature
#   | journal_generic | workshop | generic_conference
# Plus the built-in `legacy` fallback (v0.5 schema). Add new venues by
# dropping <id>.yaml into reviewer_rubrics/ — no code changes required.
#
# Few-shot corpus management
# --------------------------
# Files under reviewer_rubrics/fewshot_examples/<rubric>/ may be managed
# from the GUI (New Experiment Wizard → Paper Review → Few-shot Examples)
# or scripts/fewshot/sync.py. REST endpoints exposed by the viz server:
#   GET  /api/rubrics                         list rubrics (Wizard dropdown)
#   GET  /api/fewshot/<rubric>                list fewshot examples
#   POST /api/fewshot/<rubric>/sync           pull entries from manifest.yaml
#   POST /api/fewshot/<rubric>/upload         upload one example (JSON body)
#   POST /api/fewshot/<rubric>/<example>/delete  remove one example
# All four endpoints reject unknown rubrics and strip ../ sequences.

memory:
  # v0.6.0: Letta is the sole production backend; values here are
  # exported into the skill subprocess env at load time. The agent's
  # chat LLM handle is hardcoded to `letta/letta-free` because
  # ari-skill-memory only ever calls archival_insert / archival_search
  # — no chat messages — so the picker had no runtime effect.
  backend: letta
  letta:
    base_url: http://localhost:8283
    collection_prefix: ari_
    embedding_config: letta-default

container:
  mode: auto                   # auto | docker | singularity | apptainer | none
  image: ""                    # Container image name (empty = no container)
  pull: on_start               # always | on_start | never

skills:
  # `phase` controls which pipeline-phase ReAct agents see the skill's
  # MCP tools. A single string opts the skill into exactly one phase;
  # a list opts it into several. Skills tagged `reproduce` are exposed
  # to the reproducibility ReAct (see `reproducibility_check` stage
  # above). `memory-skill`, `transform-skill`, and `evaluator-skill`
  # are deliberately left out of `reproduce` so the agent cannot reach
  # BFTS-phase artefacts.
  - name: web-skill
    path: "{{ari_root}}/ari-skill-web"
    phase: [paper, reproduce]
  - name: plot-skill
    path: "{{ari_root}}/ari-skill-plot"
    phase: paper
  - name: paper-skill
    path: "{{ari_root}}/ari-skill-paper"
    phase: paper
  - name: paper-re-skill
    path: "{{ari_root}}/ari-skill-paper-re"
    phase: paper
  - name: memory-skill
    path: "{{ari_root}}/ari-skill-memory"
    phase: bfts
  - name: evaluator-skill
    path: "{{ari_root}}/ari-skill-evaluator"
    phase: bfts
  - name: idea-skill
    path: "{{ari_root}}/ari-skill-idea"
    phase: none
  - name: hpc-skill
    path: "{{ari_root}}/ari-skill-hpc"
    phase: [bfts, reproduce]
  - name: coding-skill
    path: "{{ari_root}}/ari-skill-coding"
    phase: [bfts, reproduce]
  - name: transform-skill
    path: "{{ari_root}}/ari-skill-transform"
    phase: paper
  - name: benchmark-skill
    path: "{{ari_root}}/ari-skill-benchmark"
    phase: bfts
  - name: vlm-skill
    path: "{{ari_root}}/ari-skill-vlm"
    phase: [paper, reproduce]
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ARI_MAX_NODES` | Maximum BFTS nodes to explore | `50` |
| `ARI_PARALLEL` | Concurrent node execution | `1` |
| `ARI_EXECUTOR` | Execution backend: `local`, `slurm`, `pbs`, `lsf` | `local` |
| `ARI_SLURM_PARTITION` | SLURM partition name | (none) |
| `ARI_SLURM_CPUS` | Override CPU count for SLURM jobs | (auto-detected) |
| `SLURM_LOG_DIR` | Where SLURM output files go | (none) |
| `OLLAMA_HOST` | Ollama server address | `127.0.0.1:11434` |
| `OPENAI_API_KEY` | OpenAI API key | (none) |
| `ANTHROPIC_API_KEY` | Anthropic API key | (none) |
| `ARI_RETRIEVAL_BACKEND` | Paper search backend: `semantic_scholar`, `alphaxiv`, `both` | `semantic_scholar` |
| `VLM_MODEL` | VLM model for figure review | `openai/gpt-4o` |
| `ARI_ORCHESTRATOR_PORT` | HTTP port for orchestrator skill | `9890` |
| `LETTA_BASE_URL` | Letta server endpoint | `http://localhost:8283` |
| `LETTA_API_KEY` | Required for Letta Cloud; optional for self-hosted | (none) |
| `LETTA_EMBEDDING_CONFIG` | Embedding handle Letta uses for archival memory (the agent's chat LLM is hardcoded to `letta/letta-free` since ARI never invokes it) | `letta-default` |
| `ARI_MEMORY_BOOTSTRAP_LOCAL_LETTA` | `auto` / `pip` / `docker` / `singularity` / `none` | `auto` |
| `ARI_MEMORY_LETTA_TIMEOUT_S` | Per-call timeout (viz + skill) | `10` |
| `ARI_MEMORY_LETTA_OVERFETCH` | Over-fetch size for the post-filter ancestor-scope fallback | `200` |
| `ARI_MEMORY_LETTA_DISABLE_SELF_EDIT` | Keep Letta self-edit off so CoW holds | `true` |
| `ARI_MEMORY_ACCESS_LOG` | `on` / `off` — enable `{checkpoint}/memory_access.jsonl` | `on` |
| `ARI_MEMORY_AUTO_RESTORE` | Auto-restore `memory_backup.jsonl.gz` on `ari resume` | `true` |
| `ARI_CURRENT_NODE_ID` | Runtime-only; set by ari-core per-node to enforce write-side CoW | (runtime) |

## Memory backend (Letta)

v0.6.0 replaces the deterministic JSONL memory store with
[Letta](https://docs.letta.com). Letta runs in one of four modes:

| Mode | Requirement | Store | Notes |
|------|-------------|-------|-------|
| Docker Compose | `docker` + `docker compose` | Postgres | Laptop default, pre-filter supported |
| Singularity / Apptainer | `singularity` / `apptainer` | Postgres | HPC default; SLURM-aware data dir |
| pip (container-less) | Python 3.10+ | SQLite | Falls back to over-fetch + post-filter ancestor scoping |
| Letta Cloud | API key | Managed | `LETTA_BASE_URL=https://api.letta.com` |

`ari setup` auto-detects the best mode; you can force one via
`ARI_MEMORY_BOOTSTRAP_LOCAL_LETTA`. Start/stop/health/backup/restore
are handled by the `ari memory` subcommand — see
`docs/cli_reference.md`.

One-shot migration for a v0.5.x checkpoint:

```bash
ari memory migrate --checkpoint /path/to/ckpt --react
```

## LLM Backends

### Ollama (local, recommended for offline HPC)

```yaml
llm:
  backend: ollama
  model: qwen3:32b
  base_url: http://127.0.0.1:11434
```

### OpenAI

```yaml
llm:
  backend: openai
  model: gpt-4o
```

### Anthropic

```yaml
llm:
  backend: anthropic
  model: claude-sonnet-4-5
```

### Any OpenAI-compatible API (vLLM, LM Studio, etc.)

```yaml
llm:
  backend: openai
  model: your-model-name
  base_url: http://your-server:8000/v1
```

---

## Template Variables in workflow.yaml

Any value in `inputs:` supports `{{variable}}` substitution:

| Variable | Value |
|----------|-------|
| `{{ckpt}}` | Checkpoint directory path |
| `{{ari_root}}` | ARI project root (`$ARI_ROOT` or auto-detected) |
| `{{llm.model}}` | LLM model name from `llm:` section |
| `{{llm.base_url}}` | LLM base URL from `llm:` section |
| `{{resources.cpus}}` | CPU count from `resources:` section |
| `{{resources.timeout_minutes}}` | Timeout from `resources:` section |
| `{{stages.<name>.outputs.file}}` | Output file path of a completed stage |
| `{{author_name}}` | Author name from top-level config |
| `{{vlm_feedback}}` | VLM review feedback (injected on loop-back from `vlm_review_figures`) |
| `{{paper_context}}` | Science-facing experiment summary |
| `{{keywords}}` | LLM-generated search keywords |

---

## skip_if_exists Validation

Stages with `skip_if_exists` will **re-run** if the output file:
- Does not exist
- Is empty
- Is a JSON file containing an `"error"` key at the top level

This prevents broken outputs from silently blocking downstream stages.

---

## BFTS Tuning

Control BFTS behavior via environment variables:

```bash
export ARI_MAX_NODES=12      # Explore up to 12 nodes (small run)
export ARI_PARALLEL=4        # Run 4 nodes concurrently
export ARI_EXECUTOR=slurm    # Submit each node as a SLURM job
```

Or set defaults in `workflow.yaml` `bfts:` section (if supported by your version).
