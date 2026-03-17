# ari-skill-paper-re

MCP skill for **reproducibility verification** of research papers via ReAct.

## Design

This skill reads **only the paper text** — no access to internal experiment records or node data.  
It implements a full ReAct (Reason → Act → Observe → Reason) loop:

```
Reason  →  LLM extracts claimed configuration from paper
           (compiler flags, thread count, expected metric value)
Act     →  Submits a SLURM job with those exact settings
Observe →  Reads actual metric from job output
Reason  →  Compares actual vs. claimed → verdict + interpretation
```

## LLM Exception

This skill calls an LLM (P2 exception). Requires Ollama running on the same node.  
Set `LLM_API_BASE=http://127.0.0.1:11434` and `LLM_MODEL=ollama_chat/qwen3:32b`.

## Tool

### `reproduce_from_paper`

```python
reproduce_from_paper(
    paper_path: str = "",          # path to .tex file
    paper_text: str = "",          # or raw text
    source_file: str = "",         # HPC source file to compile
    work_dir: str = "",            # working directory on HPC
    slurm_partition: str = "your_partition",
    slurm_cpus: int = 64,
    timeout_minutes: int = 15,
    tolerance_pct: float = 5.0,
) -> dict
```

**Returns:**
```json
{
  "verdict": "REPRODUCED | PARTIAL | NOT_REPRODUCED | UNVERIFIABLE | TIMEOUT",
  "claimed_config": { "compiler": "gcc", "flags": "-O3 ...", "threads": 64, "claimed_value": 277573.1, "metric_name": "MFLOPS" },
  "claimed_value": 277573.1,
  "actual_value": 275000.0,
  "diff_pct": 0.93,
  "metric_name": "MFLOPS",
  "interpretation": "The paper's claimed 277,573 MFLOPS was reproduced within tolerance..."
}
```

## Requirements

- Ollama with `qwen3:32b` (or configured model)
- SLURM (`sbatch`, `squeue`) accessible from compute node
- Source file readable and compilable with GCC + OpenMP

## Installation

```bash
pip install -e .
```

## Usage in workflow.yaml

```yaml
- stage: reproducibility_check
  skill: paper-re-skill
  tool: reproduce_from_paper
  inputs:
    paper_path: '{{ckpt}}/full_paper.tex'
    source_file: /path/to/your/source.c
    work_dir: '{{ckpt}}'
    slurm_partition: your_partition
    slurm_cpus: 64
    timeout_minutes: 15
```
