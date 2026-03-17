# Extension Guide

This document describes how to extend ARI for new use cases, domains, and capabilities.
ARI is designed for zero-core-code changes when adding new experiments, skills, or pipeline stages.

---

## 1. Adding a New Experiment Domain

The most common extension. Requires **no code changes**.

### Steps

1. Write `your_experiment.md`:

```markdown
# Protein Folding Optimization

## Research Goal
Minimize energy score of protein folding simulation using different force field parameters.

## Required Workflow
1. Call `survey` to find related literature
2. Submit a SLURM job with `slurm_submit`
3. Poll until completion with `job_status`
4. Read results with `run_bash`

<!-- min_expected_metric: -500 -->
<!-- metric_keyword: energy_score -->
```

2. Run:

```bash
ari run your_experiment.md --config config/bfts.yaml
```

That's it. ARI reads the goal, proposes hypotheses, and searches autonomously.

### Domain Customization via experiment.md

| Section | Purpose | Impact |
|---------|---------|--------|
| `## Research Goal` | What to optimize | Drives LLM hypothesis generation |
| `## Required Workflow` | Which tools, in what order | Sets `tool_sequence` in WorkflowHints |
| `## Hardware Limits` | Hard constraints | Injected into every agent step as system hint |
| `## SLURM Script Template` | Starting point for experiments | LLM modifies this for each hypothesis |
| `<!-- metric_keyword: X -->` | What metric to extract | Used by evaluator and evaluator-skill |
| `<!-- min_expected_metric: N -->` | Minimum acceptable value | Triggers validation check |

---

## 2. Adding a New MCP Skill

Add capabilities (new tools) to the agent without touching ari-core.

### Skill Structure

```
ari-skill-yourskill/
├── src/
│   └── server.py          ← FastMCP server (required)
├── tests/
│   └── test_server.py     ← Tests (minimum 3)
├── pyproject.toml         ← Package config
├── README.md              ← Tool descriptions and examples
└── REQUIREMENTS.md        ← Design spec
```

### Server Template

```python
# src/server.py
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("your-skill")

@mcp.tool()
def your_tool(param: str, option: int = 10) -> dict:
    """
    Clear description that appears in the LLM's tool list.

    Args:
        param: What this parameter does
        option: What this option controls (default: 10)

    Returns:
        result: The computed output
    """
    # RULE: No LLM calls here. Pure function.
    processed = pure_computation(param, option)
    return {"result": processed}

if __name__ == "__main__":
    mcp.run()
```

### Registration

In your BFTS config YAML:

```yaml
skills:
  - name: your-skill
    path: /abs/path/to/ari-skill-yourskill
```

In your `experiment.md`:

```markdown
## Required Workflow
1. Call `your_tool` with the experiment parameters
```

### Skill Design Checklist

- [ ] No LLM calls inside tool functions (P2)
- [ ] Returns a `dict` with clear keys
- [ ] Tool docstring clearly explains inputs, outputs, and side effects
- [ ] At least 3 tests covering normal, edge, and error cases
- [ ] README.md with usage examples
- [ ] REQUIREMENTS.md with design spec

---

## 3. Adding a Post-BFTS Pipeline Stage

Add automated post-processing after the BFTS search completes.
Only edit `config/pipeline.yaml`. No core code changes needed.

```yaml
pipeline:
  - stage: generate_paper
    skill: ari-skill-paper
    tool: generate_section
    enabled: true
    args:
      venue: arxiv

  - stage: review
    skill: ari-skill-paper
    tool: review_section
    enabled: true

  - stage: my_new_stage            # ← Add here
    skill: ari-skill-yourskill
    tool: your_analysis_tool
    enabled: true
    args:
      custom_param: value

  - stage: reproducibility_check
    skill: ari-skill-paper-re
    tool: reproducibility_report
    enabled: true
```

Each stage receives:
- `best_node`: The highest-scoring node from BFTS
- `all_nodes`: All explored nodes
- `nodes_json_path`: Path to `nodes_tree.json`
- Any `args` specified in the YAML

---

## 4. Supporting a New LLM Backend

Supported via litellm. In most cases, only the config changes.

```yaml
# OpenAI
llm:
  backend: openai
  model: gpt-4o

# Anthropic
llm:
  backend: anthropic
  model: claude-3-5-sonnet-20241022

# Any OpenAI-compatible API (vLLM, LM Studio, etc.)
llm:
  backend: openai
  model: your-model-name
  base_url: http://your-server:8000/v1
```

If the LLM does not support function/tool calling, set `tool_choice="none"` in `config/bfts.yaml`
and ensure the experiment workflow uses `## Required Workflow` to guide step-by-step execution.

---

## 5. Adding a New Venue for Paper Generation

Paper generation supports multiple academic venues via templates.

### Add a template

```
ari-skill-paper/templates/
├── arxiv/
│   └── main.tex          ← Already exists
├── neurips/
│   └── main.tex          ← Already exists
└── your_venue/
    └── main.tex          ← Add here
```

### Register in venue list

In `ari-skill-paper/src/server.py`, add to `VENUES`:

```python
VENUES = {
    "arxiv": {"page_limit": None, "template": "arxiv/main.tex"},
    "neurips": {"page_limit": 9, "template": "neurips/main.tex"},
    "your_venue": {"page_limit": 8, "template": "your_venue/main.tex"},  # ← Add
}
```

### Use in pipeline

```yaml
- stage: generate_paper
  skill: ari-skill-paper
  tool: generate_section
  args:
    venue: your_venue   # ← Specify here
```

---

## 6. Adding Multi-Node / Distributed Experiments

For experiments that need multiple compute nodes simultaneously.

In `experiment.md`:

```markdown
## SLURM Script Template
```bash
#!/bin/bash
#SBATCH --nodes=4
#SBATCH --ntasks-per-node=32
#SBATCH --cpus-per-task=2

mpirun -np 128 ./my_parallel_program
```
```

In `config/bfts.yaml`, increase timeout:

```yaml
bfts:
  timeout_per_node: 3600   # 1 hour for large MPI jobs
```

---

## 7. Exposing ARI to External Systems

Use `ari-skill-orchestrator` to trigger ARI from other agents, IDEs, or scripts.

### From Claude Desktop

```json
{
  "mcpServers": {
    "ari": {
      "command": "python",
      "args": ["/path/to/ari-skill-orchestrator/src/server.py"]
    }
  }
}
```

Then in Claude Desktop:
> "Run a matrix benchmark and report the best GFLOPS"

### From another agent

```python
from mcp import ClientSession
async with ClientSession(...) as session:
    result = await session.call_tool("run_experiment", {
        "experiment_md": open("experiment.md").read(),
        "max_nodes": 10
    })
    run_id = result["run_id"]
```

### As a REST API (via orchestrator)

The orchestrator MCP server can be proxied via an HTTP gateway for CI/CD integration.

---

## 8. Changing the BFTS Selection Strategy

The current strategy selects nodes with `has_real_data=True` and the highest metric values.
To change this, modify `ari/orchestrator/bfts.py`:

```python
def _select_best_node(self, nodes: list[Node]) -> Node:
    """
    Custom selection strategy.
    Default: highest metric among nodes with real data.
    """
    candidates = [n for n in nodes if n.has_real_data]
    if not candidates:
        return nodes[0]

    # Example: Pareto-optimal selection for multi-objective
    return pareto_select(candidates, objectives=["MFLOPS", "energy"])
```

---

## Extension Anti-Patterns

| Anti-Pattern | Why it's Wrong | Correct Approach |
|---|---|---|
| Add domain logic to `ari-core` | Breaks P1 (generic core) | Put it in `experiment.md` |
| Call LLM inside a skill tool | Breaks P2 (deterministic tools) | Call only in post-BFTS pipeline |
| Return a scalar score from evaluator | Breaks P3 (multi-objective) | Return full `metrics` dict |
| Hardcode model name in skill | Breaks P4 (DI) | Pass via config or tool argument |
| Use relative paths in SBATCH | Causes path errors on compute nodes | Always use absolute paths |

---

## Versioning and Compatibility

- All skill tool interfaces are versioned via their `pyproject.toml`
- Breaking changes to tool signatures require a minor version bump
- `ari-core` depends on skill interfaces, not implementations (loose coupling via MCP)
- Adding new optional parameters to tools is always backward-compatible
