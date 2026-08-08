---
sources:
  - path: ari-core/ari/public
    role: implementation
  - path: ari-core/ari/prompts
    role: prompt
  - path: ari-core/ari/configs
    role: config
  - path: ari-core/config/workflow.yaml
    role: config
last_verified: 2026-08-08
---

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

<!-- min_expected_metric: 500 -->
```

2. Run:

```bash
ari run your_experiment.md
```

That's it. ARI reads the goal, proposes hypotheses, and searches autonomously.
`--config` is optional — omitted, `ari run` auto-resolves the packaged
`ari-core/config/workflow.yaml`.

### Domain Customization via experiment.md

The following is what `from_experiment_text` (`ari/agent/workflow.py`) actually
parses; everything else is prose the LLM reads as its goal:

| Section | Purpose | Impact |
|---------|---------|--------|
| `## Research Goal` | What to optimize | Drives LLM hypothesis generation |
| `## Required Workflow` | Which tools, in what order | Becomes `WorkflowHints.post_survey_hint` ("Follow this workflow from the experiment spec: …"). `tool_sequence` is built from the tools MCP actually exposes, not from this section |
| `## Provided Files` (also `## 提供ファイル` / `## 提供文件` / `## Local Files`) | Local inputs | Absolute paths listed here are copied into each node's `work_dir` |
| `Partition: <name>` / `Max CPUs: <n>` | HPC placement | Read only when HPC is enabled; otherwise `ARI_SLURM_PARTITION` / `ARI_SLURM_CPUS` or a detected up partition fills in |
| A SLURM mention anywhere in the body (`slurm_submit`, `sbatch`, `srun`, …) | Picks the submit / poll / read trio | Switches to `slurm_submit` + `job_status` + `run_bash`; under the HPC profile, setting `ARI_SLURM_PARTITION` does the same without any keyword |
| `<!-- min_expected_metric: N -->` | Minimum acceptable value | Parses into `WorkflowHints.min_expected_metric`; a node whose extracted values are all below it is marked failed. **Digits only** — a negative threshold does not parse |

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
├── skill.yaml             ← Canonical manifest (required; the reviewed source)
├── mcp.json               ← Derived from skill.yaml. Never hand-edited
├── pyproject.toml         ← Package config
├── README.md              ← Tool descriptions and examples
└── REQUIREMENTS.md        ← Design spec
```

`skill.yaml` is the canonical manifest and `mcp.json` is its deterministic
derivative: after changing the manifest, regenerate with
`python3 scripts/sync_skill_metadata.py --write`.
`scripts/check_skill_manifests.py` fails a missing `skill.yaml`
(`manifest-missing`), an `mcp.json` that no longer matches
(`compat-metadata-drift`), a `version` that disagrees with `pyproject.toml`
(`version-drift`), and an `environment_policy` that is not `complete`
(`environment-policy-incomplete`). Every tool the server exposes must be
declared in `skill.yaml`.

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

In the `skills:` block of `ari-core/config/workflow.yaml`. `name` is the
registered skill name that pipeline stages reference (the shipped entries use
the `<area>-skill` convention, e.g. `paper-skill`), and it must match exactly —
stage dispatch filters `cfg.skills` by `s.name == stage.skill`:

```yaml
skills:
  - name: your-skill
    path: /abs/path/to/ari-skill-yourskill
    description: What this skill does
    phase: bfts          # bfts | paper | reproduce, or a list of them
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
Only edit the `pipeline:` block of `ari-core/config/workflow.yaml` (the legacy
`pipeline.yaml` filename is still accepted as a fallback). No core code changes
needed.

```yaml
pipeline:
  - stage: write_paper
    skill: paper-skill
    tool: write_paper_iterative
    depends_on: [transform_data]
    enabled: true
    phase: paper
    inputs:
      venue: arxiv

  - stage: my_new_stage            # ← Add here
    skill: your-skill              # must match a `skills:` entry name
    tool: your_analysis_tool
    depends_on: [write_paper]
    enabled: true
    phase: paper
    inputs:
      custom_param: value
      nodes_json_path: '{{checkpoint_dir}}/nodes_tree.json'
    outputs:
      file: '{{checkpoint_dir}}/my_new_stage.json'

  - stage: ors_grade
    skill: paper-re-skill
    tool: grade_with_simplejudge
    depends_on: [ors_run_reproduce]
    enabled: true
    phase: paper
```

Stage keys:
- `skill` / `tool` — the registered skill name and the MCP tool it calls.
- `inputs:` (alias `input:`) — the tool's keyword arguments, with `{{var}}`
  template substitution (`{{checkpoint_dir}}`, `{{run_id}}`, `{{ari_root}}`, …).
  `params:` is a second mapping merged into the same call arguments — string
  values are `{{var}}`-substituted too, but a `params:` key is never file-loaded
  and an `inputs:` key of the same name wins. A `<key>_from:` shorthand resolves
  a checkpoint-relative filename **and** loads its content (see also
  `load_inputs:`). There is no `args:` key.
- `depends_on:` — stages run in file order with no topological sort, so keep
  declarations in dependency order; a stage whose dependency was skipped is
  skipped too (unless the dependency is explicitly `enabled: false`).
- `phase:` — `bfts` / `paper` / `reproduce`; drives the GUI graph grouping.
- `segment:` — `evidence` / `authoring` / `verification`. A default full run
  ignores it, but segmented execution refuses to start when even one enabled
  stage carries no valid segment, so declare it on every new `pipeline:` stage.
- `skip_if_exists:` — a resolved path; the stage is skipped when it exists and
  is non-empty (and, for `.json`, carries no top-level `error` key).
  `skip_if_inputs_unchanged:` points at a sidecar contract that must still match
  disk, which stops a reusable output being reused after its inputs changed.
- `outputs.file` — where the driver persists the tool's return value.

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
  model: claude-sonnet-4-5

# Any OpenAI-compatible API (vLLM, LM Studio, etc.)
llm:
  backend: openai
  model: your-model-name
  base_url: http://your-server:8000/v1
```

There is no `tool_choice` config knob — `ari/llm/client.py` sets it itself
(`required` / `auto`). If the LLM does not support function/tool calling, route
it through the CLI-shim backend (`ARI_BACKEND=cli-shim`), whose OpenAI-compatible
server falls back to a text tool protocol, and make the experiment workflow use
`## Required Workflow` to guide step-by-step execution.

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
VENUES = [
    {"id": "neurips", "pages": 9},
    {"id": "icpp", "pages": 10},
    {"id": "sc", "pages": 12},
    {"id": "isc", "pages": 12},
    {"id": "arxiv", "pages": 0},     # unlimited
    {"id": "acm", "pages": 10},
    {"id": "your_venue", "pages": 8},  # ← Add
]
```

### Use in pipeline

```yaml
- stage: write_paper
  skill: paper-skill
  tool: write_paper_iterative
  inputs:
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

In `ari-core/config/default.yaml` (the shipped BFTS defaults) the per-node
timeout is `timeout_per_node: 7200` (2 hours). Raise it there for long MPI
jobs — or override it per run with `ARI_TIMEOUT_NODE`:

```yaml
bfts:
  timeout_per_node: 14400   # 4 hours for large MPI jobs
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
        "idempotency_key": "my-unique-key",   # required
        "max_nodes": 10
    })
    run_id = result["run_id"]
```

`idempotency_key` is a required argument: the same key does not submit a second
run, it replays the recorded handle.

### Recursive Sub-Experiments

The orchestrator supports parent-child experiment tracking. Child experiments can be launched from a parent:

```python
result = await session.call_tool("run_experiment", {
    "experiment_md": "...",
    "parent_run_id": "parent_20260414",
    "max_recursion_depth": 2
})
```

Use `list_children(parent_run_id)` to retrieve child runs. The GUI Sub-Experiments page visualizes the hierarchy.

### Over HTTP (for CI/CD)

The orchestrator is an MCP server with two transports selected by
`--transport`: **stdio** (the default) and **streamable-http** (MCP at
`http://{host}:{port}/mcp`, where host is `ARI_ORCHESTRATOR_HTTP_HOST` =
`127.0.0.1` and port is `ARI_ORCHESTRATOR_HTTP_PORT` = 9890). There is no
separate REST/SSE API with its own paths — HTTP calls the **same MCP tool
surface**. `streamable-http` refuses to start without
`ARI_ORCHESTRATOR_HTTP_TOKENS_FILE`; unauthenticated network control is not
offered.

---

## 8. Changing the BFTS Selection Strategy

Selection is `BFTS.select_next_node` in `ari/orchestrator/bfts.py`, and by
default it is an **LLM** decision over the candidate frontier. Two seams come
before touching code:

- `bfts.deterministic_selector: true` bypasses the LLM entirely and ranks with
  `_select_fallback` (the same path that runs when the LLM fails to pick).
  Preference order: nodes with `has_real_data=True` first, then the highest
  `_fallback_score`.
- `bfts.frontier_score` picks that fallback's scoring formula:
  `scientific_plus_diversity` (default), `scientific_only`, `depth_penalized`
  (subtracts `depth_penalty_lambda * depth`), and `ucb_like` (adds a UCB1-style
  term scaled by `ucb_c`).

For a genuinely new strategy — Pareto-optimal multi-objective selection, say —
edit `_fallback_score` / `_select_fallback` in the same file:

```python
def _select_fallback(self, candidates: list[Node]) -> Node:
    """Custom deterministic selection over the candidate frontier."""
    real = [n for n in candidates if n.has_real_data]
    pool = real or candidates
    # Example: Pareto-optimal selection for multi-objective
    return pareto_select(pool, objectives=["score", "energy"])
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

## Public API + Prompts / Configs (v0.7+)

### `ari.public.*` — the only stable surface for skills

ARI core is free to refactor its internal modules.  Skills must only
import via the re-export layer:

| Skill use case                 | Public import                       |
|--------------------------------|-------------------------------------|
| Cost-tracker integration       | `from ari.public import cost_tracker` |
| Container runtime helpers      | `from ari.public import container`    |
| Path / checkpoint resolution   | `from ari.public.paths import PathManager` |
| LLM client                     | `from ari.public.llm import LLMClient` |
| Pydantic config models         | `from ari.public.config_schema import ARIConfig, LLMConfig, ...` |
| Claim-evidence gate helpers    | `from ari.public import claim_gate`    |
| Per-`work_dir` run environment | `from ari.public import run_env`       |
| Verified research context      | `from ari.public import verified_context` |

`ari-core/tests/test_public_api_boundary.py` walks every
`ari-skill-*/{src,tests}/` Python file with AST and fails on imports
outside `ari.public.*`.

### `ari/prompts/` — every LLM prompt lives here

Each prompt is a Markdown file with `{var}` placeholders that the
call-site fills via `str.format()`.  Adding a new core LLM call means:

1. Drop the template in `ari-core/ari/prompts/<area>/<purpose>.md`
   (e.g. `ari/prompts/orchestrator/lineage_decision.md`).
2. Load it in the call-site:

   ```python
   from ari.prompts import FilesystemPromptLoader
   prompt = FilesystemPromptLoader().load("orchestrator/lineage_decision")
   ```

3. Pin a sha256 row in `ari-core/tests/test_prompt_extraction.py` so a
   silent edit surfaces as a CI failure.

Conventions:

- Use `str.format()` placeholders (`{var_name}`); no Jinja, no
  conditional / loop logic inside templates.
- Preserve every byte (newlines, leading spaces, trailing newline) of
  the original Python constant — the byte-equivalence is what makes
  the LLM output deterministic.
- Skills already follow the same pattern via their own `src/prompts/`
  directories (see `ari-skill-replicate`, `ari-skill-paper-re`); keep
  using that layout for new skills.

### `ari/configs/` — non-Pydantic lookup tables

Out-of-band tables that change without code changes live as YAML under
`ari-core/ari/configs/`:

| File                | Owner                                        |
|---------------------|----------------------------------------------|
| `model_prices.yaml` | LLM cost estimation (`ari/cost_tracker.py`). An unreadable/empty table sets `PRICING_TABLE_UNAVAILABLE`, which `cost_summary.json` reports — it is not silently a free run |
| `defaults.yaml`     | Model fall-backs (`models.lineage_decision_default`) **plus** the out-of-band RQGM defaults (`rqgm.epoch` / `kernel` / `governance` / `transition` / …), which mirror the typed `ari.config` pydantic defaults; the mirror is pinned by the `test_rqgm_*` tests. The same file also mirrors the Knowledge–Capability–Assurance (`knowledge` / `capability_binding` / `assurance`) and `manuscript` defaults, which are `off` / `legacy` / `off` / `off` |

Read via `from ari.configs import FilesystemConfigLoader; loader.load("model_prices")`.

### `ari/migrations/v05_to_v07/` — legacy compatibility

v0.5 → v0.7 migration helpers (legacy ``node_report.json``
reconstruction, the v0.5 global memory JSONL constant, etc.) are
isolated here.  v1.0 will drop the package; until then code in this
directory must NOT acquire new dependencies on the live runtime.

---

## Versioning and Compatibility

- All skill tool interfaces are versioned via their `pyproject.toml`
- Breaking changes to tool signatures require a minor version bump
- `ari-core` depends on skill interfaces, not implementations (loose coupling via MCP)
- Adding new optional parameters to tools is always backward-compatible
