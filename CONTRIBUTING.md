# Contributing to ARI

## Repository Structure

```
ARI/
├── README.md / README.ja.md / README.zh.md
├── CHANGELOG.md
├── CONTRIBUTING.md                  ← you are here
├── setup.sh                         ← one-shot environment bootstrap
├── requirements.txt
├── pytest.ini
│
├── docs/                            ← full documentation (en + ja/ + zh/)
│   ├── PHILOSOPHY.md                ← design invariants (P1-P5)
│   ├── architecture.md              ← system design and data flow
│   ├── configuration.md             ← workflow.yaml reference
│   ├── skills.md                    ← MCP skill API reference
│   ├── cli_reference.md             ← `ari` CLI surface
│   ├── experiment_file.md           ← how to write experiment .md files
│   ├── extension_guide.md           ← adding skills / stages / phases
│   ├── hpc_setup.md
│   ├── quickstart.md
│   ├── docs.html                    ← rendered homepage
│   └── ja/, zh/                     ← translated mirrors (keep in sync)
│
├── ari-core/                        ← core engine (BFTS + ReAct + pipeline)
│   ├── ari/
│   │   ├── agent/                   ← AgentLoop (BFTS) + react_driver
│   │   ├── orchestrator/            ← BFTS, node tree, scheduler
│   │   ├── pipeline.py              ← paper-pipeline executor
│   │   ├── mcp/client.py            ← MCP client + phase filter
│   │   ├── viz/                     ← HTTP + SSE GUI backend
│   │   └── …
│   ├── config/workflow.yaml         ← default workflow definition
│   └── tests/                       ← 1,545 tests
│
├── ari-skill-hpc/                   ← SLURM / Singularity tools
├── ari-skill-idea/                  ← Survey + VirSci idea generation (LLM)
├── ari-skill-evaluator/             ← Metric spec extraction (LLM △)
├── ari-skill-paper/                 ← LaTeX generation + rubric review (LLM)
├── ari-skill-paper-re/              ← Reproducibility pre/post helpers (LLM)
│                                       The ReAct loop lives in
│                                       ari-core/ari/agent/react_driver.py
├── ari-skill-memory/                ← Letta-backed ancestor memory (LLM △)
├── ari-skill-transform/             ← Tree → science-facing data + EAR (LLM)
├── ari-skill-web/                   ← DuckDuckGo, arXiv, Semantic Scholar
├── ari-skill-plot/                  ← Figure generation (LLM; plot + SVG)
├── ari-skill-coding/                ← Code writing / reading / run_bash
├── ari-skill-benchmark/             ← Result analysis + scipy stats
├── ari-skill-vlm/                   ← Figure/table review via VLM (LLM)
├── ari-skill-orchestrator/          ← ARI as MCP server for external agents
│
├── ari-core/config/reviewer_rubrics/← 16 bundled review rubrics (NeurIPS, SC, …)
│                                       + fewshot_examples/ for static / dynamic
├── scripts/letta/                   ← Letta deployment recipes (compose / sif / pip)
├── scripts/fewshot/                 ← review fewshot corpus sync (manifest.yaml)
├── scripts/setup/                   ← modular setup helpers (install_letta.sh ...)
├── checkpoints/                     ← per-run state (not committed)
├── containers/                      ← Singularity / Docker recipes
└── workspace/                       ← default experiment workspace
```

As of v0.6.0 there are **13 skills** (12 wired into the default
pipeline + `ari-skill-orchestrator` for external MCP integration).
v0.6.0 retired two skills: `ari-skill-figure-router` was folded into
`ari-skill-plot` (one skill now owns both matplotlib plots and SVG
diagrams, both feeding the same VLM review loop), and
`ari-skill-review` (rebuttal generation) was deleted — the
rubric-driven review score is the final quality signal.

## Development Setup

`setup.sh` installs `ari-core` plus every skill in editable mode,
records the interpreter path in `.ari_python`, and prepares a local
virtualenv if requested. Run it once from the repo root:

```bash
git clone <repo> && cd ARI
./setup.sh                 # idempotent; re-run after dependency bumps
```

Need manual control? Install packages individually:

```bash
python -m pip install -e ari-core[dev]
for d in ari-skill-*; do python -m pip install -e "$d[dev]" 2>/dev/null || true; done
```

### Running tests

The full suite runs from the repo root. Viz-page tests require a
frontend build and are usually skipped in CI:

```bash
python -m pytest \
    ari-core/tests ari-skill-*/tests \
    --ignore=ari-core/tests/test_viz_pages.py \
    --ignore=ari-core/tests/test_page_requirements.py \
    -q
```

A tighter loop while editing `ari-core`:

```bash
python -m pytest ari-core/tests/test_workflow_contract.py -q
python -m pytest ari-core/tests/test_pipeline_e2e.py -q
python -m pytest ari-core/tests/test_react_driver.py -q
```

### TypeScript / frontend

The GUI frontend lives under `ari-core/ari/viz/frontend/`. Changes to
components must compile cleanly:

```bash
cd ari-core/ari/viz/frontend
npx tsc --noEmit        # type-check only; CI gate
npm run build           # full production bundle (outputs to dist/)
```

## Design Principles (docs/PHILOSOPHY.md)

The canonical statement lives in `docs/PHILOSOPHY.md`. The cliff notes:

### P1 — Generic Core

`ari-core` contains **zero experiment-domain knowledge**. Every domain
decision is delegated to an LLM at runtime via `experiment.md`,
`WorkflowHints`, and MCP tools.

```python
# ❌ Wrong: domain-specific keyword in ari-core
if "MFLOPS" in result: …

# ✅ Right: domain knowledge injected
metric_keyword = hints.metric_keyword   # from experiment.md
```

### P2 — Deterministic Where Possible

MCP skill tools should be deterministic by default. Any tool that calls
an LLM must be explicitly annotated in `docs/skills.md` (✓ full LLM, △
partial). The BFTS search loop remains deterministic-first:
`ari-skill-hpc`, `ari-skill-coding`, `ari-skill-benchmark` must not
call an LLM mid-loop.

```python
# ❌ Wrong: LLM in a BFTS-loop tool
@mcp.tool()
def run_bash(command: str) -> dict:
    return llm.complete(f"Interpret: {command}")

# ✅ Right
@mcp.tool()
def run_bash(command: str) -> dict:
    r = subprocess.run(command, …)
    return {"stdout": r.stdout, "exit_code": r.returncode}
```

**v0.6.0 exception**: `ari-skill-memory` is Letta-backed and uses
embedding retrieval, so its `search_memory` is not byte-deterministic.
This is the only skill where P2 is explicitly relaxed (see
`docs/PHILOSOPHY.md#memory-v060-p2-relaxed-for-one-skill-p5-scoped`).
Numerical experiment results remain reproducible; only BFTS trajectory
ordering may drift across re-runs.

### P3 — Multi-Objective Evaluation

Never reduce metrics to a single scalar score inside `ari-core`.
Return the full `metrics` dict; let the LLM evaluator judge fitness in
context and assign a `_scientific_score` ∈ [0, 1] holistically.

### P4 — Dependency Injection

Domain knowledge is always passed in at runtime — never hardcoded.
`WorkflowHints`, `MetricSpec`, and the MCP tool graph are the only
injection points.

### P5 — Reproducibility-First

Every run produces a self-contained checkpoint directory that can be
copied elsewhere and resumed (`cp -r checkpoints/foo /elsewhere/ &&
ari resume`). The pipeline ends with a reproducibility verification
stage that re-derives the paper's claimed metric from the paper text
alone. Since v0.6.0 that stage runs under
`ari-core/ari/agent/react_driver.py` with an explicit MCP tool
whitelist (`phase: reproduce`) so the agent cannot observe BFTS
artefacts.

## Adding a New Skill

1. Create the directory:

   ```
   ari-skill-yourskill/
   ├── src/server.py          ← FastMCP server
   ├── tests/test_server.py   ← ≥ 3 tests
   ├── pyproject.toml
   ├── mcp.json
   ├── README.md
   └── REQUIREMENTS.md
   ```

2. Implement the server. Every public tool needs a docstring — it is
   the description the LLM sees:

   ```python
   from mcp.server.fastmcp import FastMCP
   mcp = FastMCP("your-skill")

   @mcp.tool()
   def your_tool(param: str) -> dict:
       """One-sentence description of what this tool does."""
       return {"result": pure_computation(param)}

   if __name__ == "__main__":
       mcp.run()
   ```

3. Register in `ari-core/config/workflow.yaml`. `phase` scopes which
   pipeline-phase ReAct agents can see the skill. A single string
   opts into one phase; a list opts into several:

   ```yaml
   skills:
     - name: your-skill
       path: '{{ari_root}}/ari-skill-yourskill'
       phase: [paper, reproduce]   # see docs/configuration.md for values
   ```

   Valid phase values: `bfts` (BFTS ReAct), `paper` (paper pipeline),
   `reproduce` (reproducibility ReAct), `all` (every phase),
   `none` (disabled / direct-call only).

4. Write tests. All must pass in CI (`pytest ari-skill-yourskill/tests -q`).

## Adding a Post-BFTS Pipeline Stage

Most stages are one-shot MCP tool calls and need only a YAML entry:

```yaml
pipeline:
  - stage: my_stage
    skill: your-skill
    tool: your_tool
    enabled: true
    phase: paper
    depends_on: [write_paper]
    inputs:
      data: '{{ckpt}}/science_data.json'
    outputs:
      file: '{{ckpt}}/my_output.json'
```

### Stages that need a ReAct loop

Stages that must let an LLM iterate (read → write → run → observe →
repeat) declare a `react:` block and a pre/post tool pair. The loop
itself is driven by `ari.agent.react_driver` — no core code change:

```yaml
- stage: my_react_stage
  skill: your-skill
  pre_tool: extract_something      # one-shot LLM, prepares input
  post_tool: build_final_report    # one-shot LLM, interprets output
  phase: paper
  react:
    agent_phase: reproduce         # MCP tools in this phase are visible
    max_steps: 40
    final_tool: report_metric      # agent calls this to end the loop
    sandbox: '{{checkpoint_dir}}/my_sandbox'
    system_prompt: |
      …
    user_prompt: |
      Target: {{pre.some_field}}
  inputs:
    paper_path: '{{checkpoint_dir}}/full_paper.tex'
  outputs:
    file: '{{checkpoint_dir}}/my_report.json'
```

The sandbox directory is enforced at runtime: `react_driver` rejects
any tool argument that names an absolute path outside `sandbox` (plus
an allow-list for input files like `paper_path`). See
`docs/architecture.md#pipeline-driven-react-react_driver`.

## Testing

All PRs must keep the test suite green. Indicative counts as of v0.6.0:

| Package                | Tests |
|------------------------|------:|
| `ari-core`             | 1,545 |
| `ari-skill-idea`       |    61 |
| `ari-skill-paper`      |    44 |
| `ari-skill-web`        |    38 |
| `ari-skill-hpc`        |    30 |
| `ari-skill-memory`     |    24 |
| `ari-skill-coding`     |    19 |
| `ari-skill-benchmark`  |    18 |
| `ari-skill-vlm`        |    18 |
| `ari-skill-evaluator`  |     6 |
| `ari-skill-paper-re`   |     6 |
| `ari-skill-transform`  |     4 |
| **Total**              | **1,813** |

Run everything from the repo root:

```bash
python -m pytest \
    ari-core/tests ari-skill-*/tests \
    --ignore=ari-core/tests/test_viz_pages.py \
    --ignore=ari-core/tests/test_page_requirements.py \
    -q
```

`test_workflow_contract.py` is the guardrail for pipeline YAML
schema changes. If you edit `workflow.yaml` or any code that reads it,
re-run that file first.

## Code Style

- **Python 3.11+** (CI runs 3.13).
- **Type hints** on all public functions and MCP tool signatures.
- **Docstrings** on every `@mcp.tool()` — they become the LLM's tool
  descriptions, so "what" matters, not "how".
- **Comments**: only where the *why* is non-obvious. Don't narrate
  code that reads itself.
- **No non-English text inside Python/TypeScript source** (comments,
  identifiers, log messages). Translated prose belongs in
  `docs/ja/` and `docs/zh/`; UI strings belong in i18n bundles.
- When touching a doc file, update the `docs/ja/` and `docs/zh/`
  counterparts in the same PR.
