# ARI Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        User Interface                        │
│                  experiment.md  /  CLI  /  MCP              │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                        ari-core                              │
│                                                              │
│  ┌─────────────┐   ┌──────────────┐   ┌──────────────────┐  │
│  │    BFTS     │   │  ReAct Loop  │   │  Post-BFTS       │  │
│  │  (search)   │──▶│  (per node)  │   │  Pipeline        │  │
│  └─────────────┘   └──────┬───────┘   └──────────────────┘  │
│                           │                                  │
│  ┌────────────────────────▼────────────────────────────────┐ │
│  │              MCP Client (tool dispatcher)               │ │
│  └────────────────────────┬────────────────────────────────┘ │
└───────────────────────────┼─────────────────────────────────┘
                            │ MCP protocol
        ┌───────────────────┼────────────────────────┐
        │                   │                        │
┌───────▼──────┐  ┌─────────▼──────┐  ┌─────────────▼──────┐
│ari-skill-hpc │  │ari-skill-idea  │  │ari-skill-evaluator │
│  slurm_submit│  │  survey        │  │  evaluate          │
│  job_status  │  │  make_metric.. │  │  make_artifact..   │
│  run_bash    │  │  generate_ideas│  │                    │
└──────────────┘  └────────────────┘  └────────────────────┘
        │
┌───────▼───────────────────────────────────────────────────┐
│                    your HPC cluster (SLURM)                       │
│   your_cpu_partition / your_gpu_partition partitions                    │
└───────────────────────────────────────────────────────────┘
```

## Module Reference

### ari-core

| Module | Description |
|--------|-------------|
| `ari/orchestrator/bfts.py` | Branch-and-Frontier Tree Search — manages node expansion, selection, and pruning |
| `ari/agent/loop.py` | ReAct agent loop — runs LLM + tool calls per node; auto-polls async jobs |
| `ari/agent/workflow.py` | WorkflowHints — auto-extracted domain config (tool sequence, metric extractor) |
| `ari/pipeline.py` | Post-BFTS pipeline driver — runs generate_paper → review → reproducibility |
| `ari/evaluator/llm_evaluator.py` | Metric extraction + has_real_data detection |
| `ari/memory/file_client.py` | Fallback file-based memory client |
| `ari/mcp/client.py` | Async MCP client (wraps FastMCP) |
| `ari/llm/client.py` | LLM routing via litellm (Ollama, OpenAI, Anthropic) |
| `ari/config.py` | Config dataclasses (BFTSConfig, LLMConfig, PipelineConfig) |
| `ari/core.py` | Top-level runtime builder — wires all components together |
| `ari/cli.py` | CLI entry point (`ari run`, `ari status`) |

### Data Flow

```
experiment.md
    │
    ▼
WorkflowHints (auto-extracted)
    │  tool_sequence, metric_keyword, min_expected_metric
    ▼
BFTS root node created
    │
    ▼ (for each node)
ReAct Loop:
    Step 1:  LLM selects tool → tool executes → result added to context
    Step 2:  If job submitted → auto-poll until COMPLETED (no step budget consumed)
    Step 3:  LLM reads output → extracts metrics → returns JSON
    │
    ▼
LLMEvaluator:
    - has_real_data?  (real numeric values in artifacts)
    - metrics dict    (extracted from artifacts)
    │
    ▼
BFTS selects best nodes → expands children
    │
    ▼ (after max_total_nodes reached)
Post-BFTS Pipeline (pipeline.yaml):
    generate_paper → review_section → reproducibility_check
```

## BFTS Algorithm

```python
# Simplified pseudocode
def bfts(experiment, config):
    root = Node(experiment, depth=0)
    frontier = [root]

    while len(all_nodes) < config.max_total_nodes:
        # Select up to max_parallel_nodes from frontier
        batch = select(frontier, config.max_parallel_nodes)

        # Run each node concurrently
        results = parallel_run(batch)

        # Expand successful nodes
        for node in results:
            if node.has_real_data:
                children = llm_propose_variations(node)
                frontier.extend(children)

    # Return best node
    return max(all_nodes, key=lambda n: n.metrics)
```

## Memory Architecture

Each node can access memories from its ancestor chain only:

```
root  ──stores──▶  memory["root"]
  │
  ├─ node_A  ──stores──▶  memory["node_A"]
  │    │  can read: root, node_A
  │    ├─ node_A1  (can read: root, node_A)
  │    └─ node_A2  (can read: root, node_A — NOT node_A1)
  │
  └─ node_B  ──stores──▶  memory["node_B"]
       │  can read: root, node_B  — NOT node_A or node_A1/A2
       └─ node_B1
```

This prevents cross-contamination between parallel search branches.

## Post-BFTS Pipeline

Configured in `config/pipeline.yaml`:

```yaml
pipeline:
  - stage: generate_paper
    skill: ari-skill-paper
    tool: generate_section
    args:
      venue: arxiv
      nodes_json_path: "{checkpoint_dir}/nodes_tree.json"

  - stage: review
    skill: ari-skill-paper
    tool: review_section

  - stage: reproducibility_check
    skill: ari-skill-paper-re
    tool: reproducibility_report
```

Output artifacts:
- `experiment_section.tex` — LaTeX paper section
- `review.json` — structured review feedback
- `reproducibility_report.json` — claim verification results
