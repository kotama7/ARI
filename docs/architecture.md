# ARI Architecture

## What ARI Does

ARI is an end-to-end autonomous research system. Given a plain-text research goal, it:

1. **Surveys** prior work (academic databases)
2. **Generates** a research hypothesis via multi-agent deliberation (VirSci)
3. **Searches** for the best experimental configuration using Branch-and-Frontier Tree Search (BFTS)
4. **Executes** real experiments on your hardware (laptop, SLURM, PBS, LSF)
5. **Evaluates** each experiment as a peer reviewer (LLM assigns scientific quality score)
6. **Analyzes** the full experiment tree: extracts hardware context, methodology, ablation findings
7. **Generates** publication-quality figures (LLM writes matplotlib code from data)
8. **Writes** a complete LaTeX paper with citations
9. **Reviews** the paper with an LLM acting as a referee
10. **Verifies** reproducibility: re-runs the experiment from the paper text alone

No domain knowledge is hardcoded. The same pipeline works for HPC benchmarking, ML hyperparameter tuning, chemistry optimization, or any measurable phenomenon.

---

## System Overview

```
┌────────────────────────────────────────────────────────────────┐
│                         User Interface                         │
│                   experiment.md  /  CLI  /  API                │
└────────────────────────────┬───────────────────────────────────┘
                             │
┌────────────────────────────▼───────────────────────────────────┐
│                          ari-core                              │
│                                                                │
│  ┌─────────────────┐   ┌─────────────────┐                    │
│  │  BFTS           │   │  ReAct Loop     │                    │
│  │  (tree search)  │──▶│  (per node)     │                    │
│  └─────────────────┘   └────────┬────────┘                    │
│                                 │                              │
│  ┌──────────────────────────────▼──────────────────────────┐  │
│  │            MCP Client (async tool dispatcher)           │  │
│  └──────────────────────────────┬──────────────────────────┘  │
└─────────────────────────────────┼──────────────────────────────┘
                                  │ MCP protocol (stdio/HTTP)
     ┌────────────────────────────┼──────────────────────────────┐
     │                            │                              │
┌────▼──────────┐  ┌─────────────▼──────┐  ┌───────────────────▼──┐
│ari-skill-hpc  │  │ari-skill-idea      │  │ari-skill-evaluator   │
│ slurm_submit  │  │ survey             │  │ make_metric_spec     │
│ job_status    │  │ generate_ideas     │  │ (scientific_score)   │
│ run_bash      │  │ (VirSci MCP)       │  │                      │
└───────────────┘  └────────────────────┘  └──────────────────────┘

Post-BFTS Pipeline (workflow.yaml):
┌─────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ari-skill-       │  │ari-skill-plot    │  │ari-skill-paper   │
│transform        │  │ generate_figures │  │ write_paper      │
│ nodes_to_       │  │ _llm (matplotlib │  │ review_compiled  │
│ science_data    │  │  plots + SVG     │  │  (rubric-driven, │
│ (LLM analysis)  │  │  diagrams)       │  │   ensemble+meta) │
└─────────────────┘  └──────────────────┘  └──────────────────┘
                                            ┌──────────────────┐
                                            │ari-skill-paper-re│
                                            │ extract_repro_   │
                                            │  config / build_ │
                                            │  repro_report    │
                                            │ + react_driver   │
                                            │  (ari-core)      │
                                            └──────────────────┘
```

---

## Full Data Flow

```
experiment.md
  (research goal only — 3 lines minimum)
    │
    ▼
[ari-skill-idea: survey]
  arXiv / Semantic Scholar keyword search
  Returns: related paper abstracts
    │
    ▼
[ari-skill-idea: generate_ideas]  ← VirSci multi-agent deliberation
  Multiple AI personas debate the research question
  Output: hypothesis, primary_metric, evaluation_criteria
    │
    ▼
BFTS root node created
    │
    ▼ (repeated for each node, up to ARI_MAX_NODES, ARI_PARALLEL concurrent)
┌──────────────────────────────────────────────────────────────────┐
│  ReAct Loop (ari/agent/loop.py)                                  │
│                                                                  │
│  1. LLM selects tool from MCP registry                           │
│  2. Tool executes (run_bash / slurm_submit / job_status / ...)   │
│  3. If SLURM job: auto-poll until COMPLETED (no step budget)     │
│  4. LLM reads stdout → generates experiment code → submits       │
│  5. LLM extracts metrics from output → returns JSON              │
│                                                                  │
│  Memory: result summaries saved to ancestor-chain memory         │
│  Child nodes: search ancestor memory for prior results           │
└──────────────────────────────────────────────────────────────────┘
    │
    ▼
[LLMEvaluator] (ari/evaluator/llm_evaluator.py)
  Input:  node artifacts (stdout, logs, scripts)
  Output: {
    has_real_data: bool,
    metrics: {key: value, ...},       ← extracted numeric values
    scientific_score: float 0.0-1.0,  ← LLM peer-review quality
    comparison_found: bool             ← compared against existing methods?
  }
  _scientific_score stored in metrics → drives BFTS ranking
    │
    ▼
BFTS expand() (ari/orchestrator/bfts.py)
  - Ranks nodes by _scientific_score
  - Passes score to child-proposal LLM
  - LLM proposes 1 child direction per expansion call (improve / ablation / validation / draft / debug / other)
  - No domain hints — LLM decides what "improvement" means
    │
    ▼ (after ARI_MAX_NODES reached)
nodes_tree.json  (all nodes: metrics, artifacts, memory, parent-child links)
    │
    ▼
[workflow.yaml Post-BFTS Pipeline]

  Stage 1: transform_data  (ari-skill-transform)
    BFS traversal of full tree (root → leaves)
    LLM reads all node artifacts (stdout, logs, generated code)
    LLM extracts: hardware specs, methodology, key findings, comparisons
    Output: science_data.json  { configurations, experiment_context, per_key_summary }

  Stage 2: search_related_work  (ari-skill-web)  [parallel with stage 1]
    LLM-generated keywords → pluggable retrieval (Semantic Scholar / AlphaXiv / both)
    Output: related_refs.json

  Stage 3: generate_figures  (ari-skill-plot)  [after stage 1]
    Input: full science_data.json (including experiment_context) + {{vlm_feedback}}
    LLM emits a JSON manifest where each figure has kind="plot" (matplotlib
    Python, executed → PDF+PNG) or kind="svg" (SVG code → rasterised via
    cairosvg/inkscape). Figure types and kinds chosen autonomously.
    Output: figures_manifest.json  {figures, latex_snippets, figure_kinds}

  Stage 3b: vlm_review_figures  (ari-skill-vlm)  [after stage 3]
    VLM visually reviews primary figure (fig_1.png)
    If score < 0.7: loop back to generate_figures with VLM feedback (max 2 iterations)
    Output: vlm_figure_review.json

  Stage 4: generate_ear  (ari-skill-transform)  [after stage 1]
    Builds Experiment Artifact Repository: code, data, logs, reproducibility metadata
    Output: ear_manifest.json, ear/ directory

  Stage 5: write_paper  (ari-skill-paper)  [after stages 2, 3, 4]
    paper_context = experiment_context + best_nodes_metrics
    Iterative section writing: draft → LLM review → revise (max 2 rounds)
    BibTeX citations from Semantic Scholar results
    Output: full_paper.tex, refs.bib

  Stage 6: review_paper  (ari-skill-paper)  [after stage 5]
    Rubric-driven review. Runs N independent reviewer agents (N from
    ARI_NUM_REVIEWS_ENSEMBLE / rubric default, N=1 = single reviewer).
    When N>1, also runs the Area Chair meta-review to aggregate scores.
    Output: review_report.json { score, verdict, citation_ok, feedback,
            ensemble_reviews[] (N>1), meta_review{} (N>1) }

  Stage 7: reproducibility_check  (ari-skill-paper-re + react_driver)  [after stage 5]
    pre_tool  (paper-re.extract_repro_config)
        Reads paper → extracts the advertised claim
        { metric_name, claimed_value, description, threads }
    react_driver  (ari-core/ari/agent/react_driver.py)
        Drives a ReAct loop over MCP skills opted into phase=reproduce
        (web / vlm / hpc / coding). memory-skill / transform-skill /
        evaluator-skill are excluded so the agent cannot reach
        BFTS-phase artefacts. Sandboxed to {{checkpoint_dir}}/repro_sandbox.
    post_tool (paper-re.build_repro_report)
        Compares actual vs. claimed, writes the verdict + interpretation.
    Output: reproducibility_report.json { verdict, claimed, actual, tolerance_pct }
```

---

## File Structure

### Checkpoint Directory Layout

Each ARI run produces a checkpoint directory under `{workspace}/checkpoints/{run_id}/`.
`run_id` has the form `YYYYMMDDHHMMSS_<slug>`. `PathManager` in `ari/paths.py` is the
single source of truth for directory construction.

```
checkpoints/{run_id}/
├── experiment.md               # Input: research goal (copied on launch)
├── launch_config.json          # Wizard/CLI launch parameters
├── meta.json                   # Sub-experiment metadata (parent/depth)
├── workflow.yaml               # Snapshot of pipeline config at launch
├── .ari_pid                    # PID file for liveness detection
├── tree.json                   # Full BFTS tree (written during BFTS)
├── nodes_tree.json             # Lightweight tree export (pipeline input)
├── results.json                # Per-node artifacts + metrics summary
├── idea.json                   # Generated hypothesis (VirSci output)
├── evaluation_criteria.json    # Primary metric + direction
├── cost_trace.jsonl            # Per-LLM-call cost/token log (streamed)
├── cost_summary.json           # Aggregated cost summary
├── ari.log                     # Structured JSON log
├── ari_run_*.log               # GUI-launched stdout/stderr log
├── .pipeline_started           # Marker: post-BFTS pipeline has begun
├── science_data.json           # Transform-skill output
├── related_refs.json           # Literature search results
├── figures_manifest.json       # Generated figure metadata
├── fig_*.{pdf,png,eps,svg}     # Generated figures
├── vlm_review.json             # VLM figure review output
├── full_paper.tex              # Generated LaTeX paper
├── refs.bib                    # BibTeX references
├── full_paper.pdf              # Compiled PDF
├── full_paper.bbl              # Bibliography output
├── review_report.json          # LLM peer-review output (incl. ensemble_reviews[] and meta_review{} when N>1)
├── reproducibility_report.json # Reproducibility verification
├── uploads/                    # User-uploaded files (copied to node work_dirs)
├── paper/                      # LaTeX editing workspace (Overleaf-like)
│   ├── full_paper.tex
│   ├── full_paper.pdf
│   ├── refs.bib
│   └── figures/
├── ear/                        # Experiment Artifact Repository
│   ├── README.md
│   ├── RESULTS.md
│   └── <artifacts>
└── repro/                      # Reproducibility run workspace
    ├── run/
    ├── reproducibility_report.json
    └── repro_output.log
```

### Node Work Directories

Per-node working directories are created as siblings of `checkpoints/`:

```
{workspace}/experiments/{slug}/{node_id}/
```

At node execution time, `_run_loop` copies user files into each node's work_dir:
- **Provided files**: paths listed under `## Provided Files` (or `## 提供ファイル` / `## 提供文件`) in `experiment.md`
- **Checkpoint root**: non-meta files directly in the checkpoint dir
- **Uploads subdir**: non-meta files in `checkpoint/uploads/`

`PathManager.META_FILES` defines files that must never be copied to node work dirs
(`experiment.md`, `tree.json`, `nodes_tree.json`, `launch_config.json`, `meta.json`,
`results.json`, `idea.json`, `cost_trace.jsonl`, `cost_summary.json`, `workflow.yaml`,
`ari.log`, `evaluation_criteria.json`, `.ari_pid`, `.pipeline_started`). Any file with
a `.log` extension is also treated as meta.

### tree.json vs nodes_tree.json

Both files contain the BFTS node tree, but are written at different lifecycle stages:

| File              | Writer                                                | Phase            | Schema                                                |
|-------------------|-------------------------------------------------------|------------------|-------------------------------------------------------|
| `tree.json`       | `_save_checkpoint()` in cli.py                        | During BFTS      | `{run_id, experiment_file, created_at, nodes}`        |
| `nodes_tree.json` | `_save_checkpoint()` + `generate_paper_section()`     | BFTS + post-BFTS | `{experiment_goal, nodes}` (lightweight)              |

**Reader convention**: All readers MUST prefer `tree.json` and fall back to
`nodes_tree.json`. This ensures up-to-date data during BFTS while remaining
compatible with pipeline stages that expect `nodes_tree.json`.

### Project-scoped state (per checkpoint)

ARI no longer maintains a global config directory.  Every settings file and
agent memory store lives under the active checkpoint, so each experiment
gets its own isolated state and `~/.ari/` is safe to remove:

```
checkpoints/{run_id}/
├── settings.json             # GUI settings (LLM model, provider, HPC defaults)
├── memory_backup.jsonl.gz    # Letta snapshot (portable; auto on stage boundary + exit)
├── memory_access.jsonl       # Append-only memory write/read telemetry
└── ...                       # tree.json / launch_config.json / uploads / ari.log
```

API keys are **never** stored in `settings.json`. They are read from `.env`
files (search order: checkpoint → ARI root → ari-core → home) or from
environment variables injected at launch.

---

## Module Reference

### ari-core

| Module | Description |
|--------|-------------|
| `ari/orchestrator/bfts.py` | Branch-and-Frontier Tree Search — node expansion, selection, pruning; ranks by `_scientific_score` |
| `ari/orchestrator/node.py` | Node dataclass — id, parent_id, depth, label, metrics, artifacts, memory |
| `ari/agent/loop.py` | ReAct agent loop — LLM + tool calls per node; auto-polls SLURM jobs; injects ancestor memory |
| `ari/agent/workflow.py` | WorkflowHints — auto-extracted from experiment text (tool sequence, metric keyword, partition) |
| `ari/pipeline.py` | Post-BFTS pipeline driver — template resolution, stage execution, output wiring |
| `ari/evaluator/llm_evaluator.py` | Metric extraction + peer-review scoring (`scientific_score`, `comparison_found`) |
| `ari/memory/letta_client.py` | `LettaMemoryClient` — ReAct-trace persistence backed by the `ari_react_*` Letta collection |
| `ari/memory/file_client.py` | Deprecated v0.5.x file-backed client; kept only for `ari memory migrate --react` |
| `ari/memory/auto_migrate.py` | First-launch v0.5.x JSONL → Letta importer |
| `ari/memory_cli.py` | `ari memory …` subcommand (migrate / backup / restore / start-local / …) |
| `ari/mcp/client.py` | Async MCP client — thread-safe, fresh event loops for parallel execution |
| `ari/llm/client.py` | LLM routing via litellm (Ollama, OpenAI, Anthropic, any OpenAI-compatible) |
| `ari/config.py` | Config dataclasses (BFTSConfig, LLMConfig, PipelineConfig) |
| `ari/core.py` | Top-level runtime builder — wires all components |
| `ari/cli.py` | CLI: `ari run`, `ari paper`, `ari status` |

### Skills (MCP servers)

**Default skills** (registered in `workflow.yaml`):

| Skill | Tools | Role | LLM? |
|-------|-------|------|------|
| `ari-skill-hpc` | `slurm_submit`, `job_status`, `job_cancel`, `run_bash`, `singularity_build`, `singularity_run`, `singularity_pull`, `singularity_build_fakeroot`, `singularity_run_gpu` | HPC job management + Singularity containers | ✗ |
| `ari-skill-memory` | `add_memory`, `search_memory`, `get_node_memory`, `clear_node_memory`, `get_experiment_context` | Ancestor-scoped node memory backed by Letta (Postgres / SQLite / Cloud) | △ |
| `ari-skill-idea` | `survey`, `generate_ideas` | Literature search (Semantic Scholar) + VirSci multi-agent hypothesis generation | ✓ |
| `ari-skill-evaluator` | `make_metric_spec` | Metric spec extraction from experiment file | △ |
| `ari-skill-transform` | `nodes_to_science_data`, `generate_ear` | BFTS tree → science-facing data + Experiment Artifact Repository | ✓ |
| `ari-skill-web` | `web_search`, `fetch_url`, `search_arxiv`, `search_semantic_scholar`, `search_papers`, `set_retrieval_backend`, `collect_references_iterative`, `list_uploaded_files`, `read_uploaded_file` | Web search, arXiv, pluggable retrieval (Semantic Scholar / AlphaXiv), uploaded file access | △ |
| `ari-skill-plot` | `generate_figures`, `generate_figures_llm` | Deterministic + LLM figure generation (matplotlib plots or SVG diagrams per-figure via `kind` field) | ✓ |
| `ari-skill-paper` | `list_venues`, `get_template`, `generate_section`, `compile_paper`, `check_format`, `review_section`, `revise_section`, `write_paper_iterative`, `review_compiled_paper`, `list_rubrics` | LaTeX paper writing, compilation, rubric-driven peer review (AI Scientist v1/v2-compatible). `review_compiled_paper` runs N independent reviewers via the ensemble path; when N>1 it also runs the Area Chair meta-review internally. | ✓ |
| `ari-skill-paper-re` | `extract_repro_config`, `build_repro_report`, `extract_metric_from_output` | Deterministic pre/post endpoints for the reproducibility ReAct (loop itself lives in `ari-core/ari/agent/react_driver.py`) | ✓ |
| `ari-skill-benchmark` | `analyze_results`, `plot`, `statistical_test` | CSV/JSON/NPY analysis, plotting, scipy stats (used in BFTS analyze stage) | ✗ |
| `ari-skill-vlm` | `review_figure`, `review_table` | VLM-based figure/table review (drives VLM review loop) | ✓ |
| `ari-skill-coding` | `write_code`, `run_code`, `read_file`, `run_bash` | Code generation + execution + paginated file read | ✗ |

**Additional skills** (available, not in default workflow):

| Skill | Tools | Role | LLM? |
|-------|-------|------|------|
| `ari-skill-orchestrator` | `run_experiment`, `get_status`, `list_runs`, `list_children`, `get_paper` | Expose ARI as MCP server, recursive sub-experiments, dual stdio+HTTP transport | ✗ |

✗ = no LLM, △ = LLM in some tools only, ✓ = primary tools use LLM. 13 skills total (12 default, 1 additional).

---

## BFTS Algorithm

ARI implements true Best-First Tree Search with a two-pool design:

- **`pending`**: nodes ready to run (already expanded from a parent)
- **`frontier`**: completed nodes not yet expanded

```python
def bfts(experiment, config):
    root = Node(experiment, depth=0)
    pending = [root]      # nodes ready to execute
    frontier = []         # completed nodes awaiting expansion
    all_nodes = [root]

    while len(all_nodes) < config.max_total_nodes:

        # --- BFTS STEP 1: expand the best frontier node ---
        # LLM reads metrics of all completed nodes and selects
        # the most promising one to expand (one child per call)
        while frontier and len(pending) < max_parallel:
            best = llm_select_best_to_expand(frontier)  # by _scientific_score + diversity_bonus
            # Frontier nodes stay available for re-expansion
            child = llm_propose_one_direction(best, existing_children=best.children)
            pending.append(child)
            all_nodes.append(child)

        # --- BFTS STEP 2: run a batch of pending nodes ---
        batch = llm_select_next_nodes(pending, max_parallel)
        record_run(batch)  # track label diversity
        results = parallel_run(batch)

        for node in results:
            memory.write(node.eval_summary)   # save to ancestor-chain memory
            frontier.append(node)             # will expand when selected

    return max(all_nodes, key=lambda n: n.metrics.get("_scientific_score", 0))
```

Key properties:
- **Single-child expansion**: `expand()` generates exactly one child per call with rich context (sibling scores, ancestor chain, tree diversity metrics, existing children) to avoid duplicates
- **Persistent frontier**: completed nodes stay in frontier after expansion, available for re-expansion with `_touched_this_round` / `_failed_this_round` tracking
- **Diversity bonus**: `+0.05` for underrepresented labels (last 20 runs tracked) encourages exploration variety
- **Score calibration**: evaluator injects recent score history into prompts to prevent score collapse (all scores clustering around the same value)
- **No retry**: failed nodes produce `debug` children via `expand()`, not re-executions
- **Strict budget**: `len(all_nodes) < max_total_nodes` prevents overshoot
- **`generate_ideas` called once**: suppressed after root node to prevent looping

### Node Labels

| Label | Meaning |
|-------|---------|
| `draft` | New implementation from scratch |
| `improve` | Tune parent's parameters or algorithm |
| `debug` | Fix parent's failure |
| `ablation` | Remove one component to measure its impact |
| `validation` | Re-run parent with different conditions |
| *(custom)* | Unknown labels fall back to `other`; `raw_label` preserves the original string |

---

## Pipeline-driven ReAct (react_driver)

BFTS owns its own ReAct loop (`ari.agent.AgentLoop`, tightly coupled to
the `Node` tree). A second, lighter ReAct driver lives in
`ari.agent.react_driver.run_react` for pipeline stages that need a ReAct
agent without the BFTS context. It is invoked from
`ari.pipeline._run_react_stage` whenever a stage declares a `react:`
block and is currently used by `reproducibility_check`.

```
pipeline.py ──▶ pre_tool (MCP)  → claimed config
             ─▶ react_driver.run_react
                   ├─ phase filter: MCPClient.list_tools(phase="reproduce")
                   ├─ sandbox enforcement on every tool call's args
                   └─ terminates when the agent calls `final_tool`
             ─▶ post_tool (MCP) → verdict + interpretation
```

Key properties:

- **Phase whitelist**: `skills[].phase` in `workflow.yaml` may be a
  single string or a list. Only skills whose phase list contains the
  stage's `react.agent_phase` value reach the agent. The default
  `workflow.yaml` opts `web-skill`, `vlm-skill`, `hpc-skill`, and
  `coding-skill` into `reproduce`; `memory-skill`, `transform-skill`,
  and `evaluator-skill` are deliberately excluded so the agent cannot
  observe BFTS state (`nodes_tree.json`, ancestor memories, science
  data).
- **Sandbox**: `react.sandbox` is a directory (default
  `{{checkpoint_dir}}/repro_sandbox/`). Tool-call arguments are
  scanned for absolute paths and `..` traversal; anything outside the
  sandbox (plus an allow-list for the paper `.tex`) is rejected with
  a `sandbox violation` tool reply instead of being dispatched.
  `ARI_WORK_DIR` is also set to the sandbox before MCP servers are
  spawned so `coding-skill.run_bash` naturally cwds there.
- **Termination**: the agent ends the loop by calling
  `react.final_tool` (default `report_metric`). That call is captured
  by the driver (never forwarded to MCP) and its arguments become the
  `actual_value` / `actual_unit` / `actual_notes` passed to the stage's
  `post_tool`.

This separation keeps `reproduce_from_paper`-style stages "only reads
the paper text" auditable in YAML instead of buried in skill Python.

---

## Memory Architecture

Each node reads only from its ancestor chain:

```
root ──▶ memory["root"]
  ├─ node_A ──▶ memory["node_A"]
  │    ├─ node_A1  (reads: root + node_A)
  │    └─ node_A2  (reads: root + node_A, NOT node_A1)
  └─ node_B  (reads: root only, NOT node_A branch)
```

`search_memory` query = node's own `eval_summary` text (not domain keywords).
This ensures retrieved memories are semantically relevant to the current node's work.

### v0.6.0: backed by Letta

Both layers live in the same per-checkpoint Letta agent:

- `ari_node_<ckpt_hash>` — node-scope archival collection with the
  ancestor-scope metadata filter above.
- `ari_react_<ckpt_hash>` — flat per-checkpoint ReAct trace
  (`LettaMemoryClient`, not ancestor-filtered).

The agent also seeds a core-memory block (`persona` + `human` +
`ari_context`) with experiment goal, primary metric, and hardware spec
once the first node's `generate_ideas` completes (the point at which
`primary_metric` is known). Skills can read it via
`get_experiment_context()` without paying for a search; the call
returns `{}` until that seed runs.

**Copy-on-Write**: write-side tools reject `node_id` ≠
`$ARI_CURRENT_NODE_ID` so ancestor entries are byte-stable across
siblings; Letta self-edit is disabled by default for the same reason.

**Portability**: each checkpoint carries a
`memory_backup.jsonl.gz` snapshot that is restored automatically on
`ari resume` when the target Letta is empty — keeping
`cp -r checkpoints/foo /elsewhere/` + `ari resume` working.

---

## Per-Node Prompt Composition

Every BFTS node is executed by a single entry point, `AgentLoop.run(node,
experiment)` in `ari/agent/loop.py:370`. The same loop handles root and
child nodes; the prompt it builds differs by `node.depth` and by the
state inherited from ancestors. This section is the source of truth for
*what an agent sees the moment it starts a node* — so changes here
require careful review.

### Inputs to `AgentLoop.run`

Two arguments arrive per call:

1. **`node: Node`** — created by `BFTS.expand` (`ari/orchestrator/bfts.py:431-441`). The fields that influence the prompt:
   - `id`, `depth`, `label` (`draft|improve|debug|ablation|validation|other`), `raw_label`
   - `ancestor_ids` — the strict CoW chain from root to parent (parent included), used as the `search_memory` filter
   - `eval_summary` — for a freshly-expanded child this holds the LLM-proposed direction (one sentence). After execution the same field is overwritten with the evaluator's summary.
   - `memory_snapshot` — a copy of the parent's snapshot; not currently used by the prompt builder, but persisted in `tree.json`.
2. **`experiment: dict`** — assembled per node by the scheduler:
   - `goal` — the entire `experiment.md` text (run-wide, identical for every node)
   - `work_dir` — node-private directory created by `PathManager`
   - `slurm_partition`, `slurm_max_cpus` — populated by `env_detect` when SLURM is enabled

### System prompt — `ari/agent/loop.py:41-58`

```
You are a research agent. You MUST use tools to execute experiments. ...

AVAILABLE TOOLS:
{tool_desc}                ← MCP tools enumerated for the active phase

RULES:
- Your FIRST action must be a tool call ...
- If `make_metric_spec` is available and this is a new experiment ...
- NEVER fabricate numeric values ...
- When all experiments are done, return JSON {...}
- Do NOT call gap_analysis or generate_hypothesis
- Ensure your experiment is reproducible: ...
{memory_rules}{extra}
```

The `{extra}` block (built at L448-453) appends:

| Sub-block | Source | Notes |
|-----------|--------|-------|
| `NODE ROLE: {label_hint}` | `node.label.system_hint()` | One-sentence behavioural cue keyed off the BFTS label |
| `EXPERIMENT ENVIRONMENT` | L433-442 | `work_dir` + provided files + SLURM partition/CPUs + container image (`ARI_CONTAINER_IMAGE`) |
| `RESOURCE BUDGET` | L443-447 | `max_react_steps`, `timeout_per_node // 60` minutes |
| `extra_system_prompt` | `WorkflowHints.extra_system_prompt` | Optional escape hatch set by `from_experiment_text` / pipeline configs |

The `{memory_rules}` block (L454-456) is appended only when the agent
actually has the `add_memory` tool available, and it inlines the active
node id so the LLM cannot accidentally write under a different scope:

```
- When available, save decisive intermediate findings with
  add_memory(node_id="<this node's id>", text=..., metadata=...)
- Use search_memory(query=..., ancestor_ids=[...], limit=5) ...
```

### Tool catalog (`tool_desc`)

`tools = self._available_tools_openai(suppress=..., phase="bfts")` at
L389 enumerates every tool MCP exposes for `phase="bfts"`, then drops
anything in `_suppress_tools`. The mutable suppression set lives on the
`AgentLoop` instance and is updated as the run progresses:

- After the first successful `generate_ideas` call, the loop sets
  `self._suppress_tools = {"generate_ideas"}` (L873-874) so subsequent
  nodes do not regenerate ideas.
- `survey` is **not** suppressed for child nodes; it is only discouraged
  in prose (see "User message #1 — child" below). A child that ignores
  the prose can still call `survey()`.

`_PINNED_TOOLS = {"survey", "generate_ideas", "make_metric_spec"}`
(L613) marks tool results that the message-window trimmer must keep,
even when the chat history is compressed; their content survives every
ReAct round.

### User message #1 — root node (`node.depth == 0`)

`loop.py:501-511`:

```
Experiment goal:
{goal_text(truncated to 1500 chars)}

Node: {node.id} depth={node.depth}

START NOW: call {first_tool}() immediately. Do NOT output any text or
plan — your first response must be a {first_tool}() tool call.

IMPORTANT: After make_metric_spec, call survey() to search related
literature. The survey results will be used to generate citations in
the paper. Without survey, the paper will have no references.
```

`first_tool` is `WorkflowHints.tool_sequence[0]`, which `enrich_hints_from_mcp`
defaults to `make_metric_spec` → `survey` → `generate_ideas` → executor
when the corresponding skills are present.

### User message #1 — child node (`node.depth > 0`)

`loop.py:477-500`:

```
Experiment goal:
{goal_text(truncated to 1500 chars)}

Node: {node.id} depth={node.depth} task={node.label}

Task: {label-specific one-line description from _label_desc}
The parent node already completed the survey and established a research
direction. Prior results are provided below. Implement and run your
specific experiment, then return JSON with measurements.

Workflow:
{WorkflowHints.post_survey_hint}        ← e.g. slurm_submit / run_bash steps
```

`_label_desc` (L479-485) is the only place where label semantics enter
the per-node prompt:

| Label | One-line task |
|-------|---------------|
| `improve` | Improve performance or accuracy beyond what the parent achieved. |
| `ablation` | Ablation study: remove or vary one component from the parent approach. |
| `validation` | Validate the parent result under different conditions or parameters. |
| `debug` | The parent experiment had issues. Diagnose and fix them. |
| `draft` | Try a new implementation approach for the same goal. |
| *(other / unknown)* | Extend or vary the parent experiment. |

Note that `node.eval_summary` (the specific direction the BFTS expander
LLM proposed for this child) is **not** written into this prompt
verbatim. The child only sees the generic label task; the proposed
direction reaches the agent indirectly via the prior-knowledge memory
search below.

### User message #2 — prior knowledge (children only)

`loop.py:522-549`. When `node.depth > 0` and `node.ancestor_ids` is
non-empty, the loop calls:

```python
search_memory(
    query        = (node.eval_summary or self.experiment_goal or "experiment result")[:200],
    ancestor_ids = node.ancestor_ids,
    limit        = 5,
)
```

then appends a single user message:

```
[Prior knowledge from ancestor nodes (N entries):]
{join(entry.text for entry in results)[:800]}
```

Three caps are hard-coded:

| Cap | Value | Where |
|-----|-------|-------|
| query length | 200 chars | L528 |
| number of entries | 5 | L532 |
| concatenated content | 800 chars | L545 |

Failures (memory backend down, malformed result) are swallowed at
`logger.debug` level so the node still runs.

The legacy `search_global_memory` injection block (L551-574) is dead
code in v0.6.0; the global-memory tool was removed (`CHANGELOG.md`
v0.6.0 §3) and the conditional never fires.

### Truncation summary

| Item | Limit | Code |
|------|-------|------|
| `goal_text` | 1500 chars | `loop.py:469-474` |
| Survey-result memory entry | first 5 papers, 200-char abstract each | `loop.py:830-833` |
| Prior-knowledge query | 200 chars | `loop.py:528` |
| Prior-knowledge entries | top 5 by relevance | `loop.py:532` |
| Prior-knowledge concatenation | 800 chars | `loop.py:545` |

### Information that is intentionally **not** injected

The following are reachable but never auto-added to the prompt; the
agent must call the relevant tool itself if it wants them:

- **`get_experiment_context()` payload** (`experiment_goal`,
  `primary_metric`, `hardware_spec`, `metric_rationale`,
  `higher_is_better`). Seeded after the first `generate_ideas` call;
  available via the MCP tool but not pasted into any prompt block.
- **`node.eval_summary` direction text for children**. Persisted on the
  Node object and visible to BFTS expansion / evaluation, but absent
  from the child agent's user prompt.
- **`memory_snapshot`**. Carried into the child Node from the parent
  but not consumed by the prompt builder; reserved for future use.
- **Sibling node metrics**. Visible to `BFTS.expand` when proposing the
  child (so the *expander LLM* sees them), but not to the *executing
  agent* of that child.

### CoW bridge — keeping the memory skill in sync

Right before the LLM round-trip starts, `loop.py:378-381` issues:

```python
self.mcp.call_tool("_set_current_node", {"node_id": node.id})
```

This is an internal tool exposed by `ari-skill-memory`; it updates
`$ARI_CURRENT_NODE_ID` inside the pooled skill subprocess so any
subsequent `add_memory(node_id=...)` call can be CoW-validated against
the active node. The agent never sees this tool; it is filtered out of
`tool_desc` by `_INTERNAL_MCP_TOOLS`.

### Soft vs hard enforcement

Some "rules" the agent appears to follow are enforced strictly in code,
others only in the prompt prose. Knowing which is which matters when
debugging unexpected agent behaviour:

| Rule | Enforcement |
|------|-------------|
| Cannot write memory for another node | **Hard** — backend rejects on `node_id` ≠ `$ARI_CURRENT_NODE_ID` |
| Cannot read sibling memories | **Hard** — `search_memory` filters by `ancestor_ids` |
| `generate_ideas` runs at most once | **Hard** — `_suppress_tools` after first call |
| Children should not call `survey` | **Soft** — prose only ("parent already completed the survey"); the tool stays in `tool_desc` |
| Children must implement, not plan | **Soft** — prose; relies on system-prompt `RULES` block |
| Resource budget | **Soft hint** in prompt + **hard** timeout/step cap in the loop |

---

## Design Invariants

ARI's production code contains **zero domain knowledge**. All domain decisions are delegated to LLMs at runtime.

| Decision | Who decides |
|----------|-------------|
| What metrics matter | LLM evaluator |
| What to compare against | LLM evaluator (`comparison_found`) |
| What experiments to run | ReAct agent (LLM) |
| What hardware was used | Transform skill LLM (reads lscpu/etc from artifacts) |
| What figures to draw | Plot skill LLM |
| What to extract from tree | Transform skill LLM |
| How to rank nodes | LLM-assigned `_scientific_score` |
| What citation keywords to use | LLM-generated from node summaries |
| Whether to collect env/setup info | ReAct agent LLM (guided by reproducibility principle in system prompt) |

---

## Extending ARI

To add a new capability, create a new MCP skill:

```bash
mkdir ari-skill-myskill/src
# Implement server.py with FastMCP tools
# Register in workflow.yaml skills section
```

```yaml
# workflow.yaml
skills:
  - name: myskill
    path: "{{ari_root}}/ari-skill-myskill"

pipeline:
  - stage: my_stage
    skill: myskill
    tool: my_tool
    inputs:
      data: "{{ckpt}}/science_data.json"
```

No changes to `ari-core` required.
