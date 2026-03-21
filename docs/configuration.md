# Configuration Reference

## workflow.yaml (Canonical Developer Config)

`workflow.yaml` is the **single source of truth** for the full ARI pipeline.
Place it at `ari-core/config/workflow.yaml`.

Use `{{ari_root}}` in skill paths — it resolves to `$ARI_ROOT` env var or the project root.

```yaml
llm:
  backend: openai          # ollama | openai | anthropic
  model: gpt-4o            # Model identifier
  base_url: ""             # Leave empty for OpenAI; set for Ollama/vLLM

author_name: "Artificial Research Intelligence"

resources:
  cpus: 32                 # Default CPU count for reproducibility experiments
  timeout_minutes: 15      # Default job timeout

pipeline:
  - stage: transform_data
    skill: transform-skill
    tool: nodes_to_science_data
    inputs:
      nodes_json_path: '{{ckpt}}/nodes_tree.json'
      llm_model: '{{llm.model}}'
      llm_base_url: '{{llm.base_url}}'
    outputs:
      file: '{{ckpt}}/science_data.json'

  # ... additional stages (generate_figures, search_related_work, write_paper, ...)

skills:
  - name: memory-skill
    path: "{{ari_root}}/ari-skill-memory"
  - name: idea-skill
    path: "{{ari_root}}/ari-skill-idea"
  - name: hpc-skill
    path: "{{ari_root}}/ari-skill-hpc"
  - name: evaluator-skill
    path: "{{ari_root}}/ari-skill-evaluator"
  - name: transform-skill
    path: "{{ari_root}}/ari-skill-transform"
  - name: plot-skill
    path: "{{ari_root}}/ari-skill-plot"
  - name: paper-skill
    path: "{{ari_root}}/ari-skill-paper"
  - name: paper-re-skill
    path: "{{ari_root}}/ari-skill-paper-re"
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ARI_MAX_NODES` | Maximum BFTS nodes to explore | `50` |
| `ARI_PARALLEL` | Concurrent node execution | `1` |
| `ARI_EXECUTOR` | Execution backend: `local`, `slurm`, `pbs`, `lsf` | `local` |
| `ARI_SLURM_PARTITION` | SLURM partition name | (none) |
| `SLURM_LOG_DIR` | Where SLURM output files go | (none) |
| `OLLAMA_HOST` | Ollama server address | `127.0.0.1:11434` |
| `OPENAI_API_KEY` | OpenAI API key | (none) |
| `ANTHROPIC_API_KEY` | Anthropic API key | (none) |

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
  model: claude-opus-4-5
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
