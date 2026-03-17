# ari-core

Core engine for ARI (Artificial Research Intelligence).
Implements the autonomous experiment loop using BFTS × ReAct.

## Overview

Accepts an experiment specification Markdown file and iteratively runs experiments
while searching for the best node in the BFTS tree.
On completion, automatically runs paper generation, review, and reproducibility
verification according to `pipeline.yaml`.

## Key Modules

| Module | Role |
|---|---|
| `ari/orchestrator/bfts.py` | Branch-and-Frontier Tree Search |
| `ari/agent/loop.py` | ReAct agent loop (per node) |
| `ari/pipeline.py` | Post-BFTS pipeline driver |
| `ari/evaluator/llm_evaluator.py` | Metric extraction and evaluation |
| `ari/agent/workflow.py` | WorkflowHints — domain knowledge injection |
| `ari/memory/` | Ancestor-scoped memory client |

## Tests

```bash
pytest tests/ -q
# 45 passed
```
