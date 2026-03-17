# Configuration Reference

## BFTS Config (`config/bfts.yaml`)

```yaml
llm:
  backend: ollama          # ollama | openai | anthropic
  model: qwen3:32b         # Model identifier
  base_url: http://127.0.0.1:11434  # Required for Ollama

memory:
  backend: local           # local | mcp

skills:
  - name: memory-skill
    path: /abs/path/to/ari-skill-memory
  - name: idea-skill
    path: /abs/path/to/ari-skill-idea
  - name: hpc-skill
    path: /abs/path/to/ari-skill-hpc
  - name: evaluator-skill
    path: /abs/path/to/ari-skill-evaluator
  - name: paper-skill
    path: /abs/path/to/ari-skill-paper

bfts:
  max_depth: 3             # Maximum tree depth
  max_retries_per_node: 2  # Retries before marking a node failed
  max_total_nodes: 15      # Total nodes to explore
  max_parallel_nodes: 2    # Concurrent node execution
  timeout_per_node: 1200   # Seconds per node (wall time)

checkpoint:
  dir: /path/to/logs/ckpt_{run_id}/

logging:
  level: DEBUG
  dir: /path/to/logs/log_{run_id}/
  format: json
```

## Pipeline Config (`config/pipeline.yaml`)

```yaml
pipeline:
  - stage: generate_paper
    skill: ari-skill-paper
    tool: generate_section
    enabled: true
    args:
      section: experiment
      venue: arxiv

  - stage: review
    skill: ari-skill-paper
    tool: review_section
    enabled: true

  - stage: reproducibility_check
    skill: ari-skill-paper-re
    tool: reproducibility_report
    enabled: true
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SLURM_DEFAULT_PARTITION` | Partition for sub-jobs submitted by ARI | (none) |
| `SLURM_DEFAULT_WORK_DIR` | Working directory for SLURM submissions | (none) |
| `SLURM_LOG_DIR` | Where SLURM output files go | (none) |
| `OLLAMA_HOST` | Ollama server address | `127.0.0.1:11434` |
| `OLLAMA_MODELS` | Path to Ollama model cache | `~/.ollama/models` |
| `OLLAMA_CONTEXT_LENGTH` | Context window size | `8192` |
| `OLLAMA_NUM_PARALLEL` | Parallel LLM requests | `1` |

## LLM Backends

### Ollama (local, recommended for HPC)

```yaml
llm:
  backend: ollama
  model: qwen3:32b         # or qwen3:8b, deepseek-r1:32b
  base_url: http://127.0.0.1:11434
```

### OpenAI

```yaml
llm:
  backend: openai
  model: gpt-4o
  # Set OPENAI_API_KEY environment variable
```

### Anthropic

```yaml
llm:
  backend: anthropic
  model: claude-3-5-sonnet-20241022
  # Set ANTHROPIC_API_KEY environment variable
```
