# ari-core Requirements

## Overview

Core framework for Artificial Research Intelligence.
Accepts an experiment specification Markdown, runs autonomous research via
BFTS tree search × Agent loop, and outputs a paper section.

## Design Principles

- **P1 Generic core**: No experiment-domain knowledge in ari-core
- **P2 Deterministic skills**: No LLM calls inside MCP skill servers
- **P3 Multi-objective evaluation**: No scalar score; raw metrics dict drives selection
- **P4 Dependency injection**: Domain knowledge injected from experiment.md at runtime

## Tech Stack

- Python 3.11+
- litellm (LLM routing: Ollama, OpenAI, Anthropic)
- FastMCP (MCP client)
- pydantic (data models)
- pytest (tests)

## Key Interfaces

### BFTSConfig
```python
@dataclass
class BFTSConfig:
    max_nodes: int = 10
    max_depth: int = 3
    max_parallel: int = 2
    timeout_per_node: int = 1200
```

### WorkflowHints
Domain-specific workflow configuration auto-extracted from experiment.md.
Controls tool sequence, metric extraction, and validation behavior.

### NodeLabel
- `DRAFT`: Initial state
- `SUCCESS`: has_real_data=True
- `FAILED`: Evaluation failed or hallucination detected

## Post-BFTS Pipeline

Configured via `config/pipeline.yaml`.
Stages: `generate_paper` → `review` → `reproducibility_check`

Adding a stage requires only a YAML change — no core code modification.

## Pipeline Keyword Extraction

`pipeline.py` contains `_extract_keywords_from_nodes(nodes_json_path)`:
- Reads `nodes_tree.json` produced by BFTS
- Extracts compiler flags, optimization keywords from node memory/artifacts
- Returns a targeted arXiv query string
- Called before the `search_related_work` stage; query injected as `args["query"]`
- **No LLM. No MCP call.** Pure Python deterministic function.
