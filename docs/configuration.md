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
    tool: reproduce_from_paper
    depends_on: [write_paper]
    # ...

retrieval:
  backend: semantic_scholar    # semantic_scholar | alphaxiv | both
  alphaxiv_endpoint: https://api.alphaxiv.org/mcp/v1

container:
  mode: auto                   # auto | docker | singularity | apptainer | none
  image: ""                    # Container image name (empty = no container)
  pull: on_start               # always | on_start | never

skills:
  - name: web-skill
    path: "{{ari_root}}/ari-skill-web"
    phase: all
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
    phase: bfts
  - name: hpc-skill
    path: "{{ari_root}}/ari-skill-hpc"
    phase: bfts
  - name: transform-skill
    path: "{{ari_root}}/ari-skill-transform"
    phase: paper
  - name: figure-router-skill
    path: "{{ari_root}}/ari-skill-figure-router"
    phase: all
  - name: benchmark-skill
    path: "{{ari_root}}/ari-skill-benchmark"
    phase: bfts
  - name: review-skill
    path: "{{ari_root}}/ari-skill-review"
    phase: paper
  - name: vlm-skill
    path: "{{ari_root}}/ari-skill-vlm"
    phase: paper
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
