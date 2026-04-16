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
│ nodes_to_       │  │ _llm (LLM writes │  │ review_compiled  │
│ science_data    │  │  matplotlib)     │  │ reproduce_from   │
│ (LLM analysis)  │  │                  │  │  _paper          │
└─────────────────┘  └──────────────────┘  └──────────────────┘
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
    LLM writes complete matplotlib code → executes → saves PDF figures
    Figure types chosen autonomously from data (not prescribed)
    Output: figures_manifest.json

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
    PDF → pdftotext → LLM holistic review
    Output: review_report.json { score, verdict, citation_ok, feedback }

  Stage 7: respond_to_review  (ari-skill-review)  [after stage 6]
    Parse review concerns → generate point-by-point rebuttal
    Output: rebuttal.json

  Stage 8: reproducibility_check  (ari-skill-paper-re)  [after stage 5]
    Reads paper → extracts configuration → runs HPC job → compares claimed vs actual
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
├── review_report.json          # LLM peer-review output
├── rebuttal.json               # Point-by-point rebuttal
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
├── settings.json        # GUI settings (LLM model, provider, HPC defaults)
├── memory.json          # FileMemoryClient store (ancestor-chain)
├── memory_store.jsonl   # ari-skill-memory MCP server entries
└── ...                  # tree.json / launch_config.json / uploads / ari.log
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
| `ari/memory/file_client.py` | File-based memory client (ancestor-chain scoped) |
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
| `ari-skill-memory` | `add_memory`, `search_memory`, `get_node_memory`, `clear_node_memory` | Ancestor-chain experiment memory (JSONL) | ✗ |
| `ari-skill-idea` | `survey`, `generate_ideas` | Literature search (Semantic Scholar) + VirSci multi-agent hypothesis generation | ✓ |
| `ari-skill-evaluator` | `make_metric_spec` | Metric spec extraction from experiment file | △ |
| `ari-skill-transform` | `nodes_to_science_data`, `generate_ear` | BFTS tree → science-facing data + Experiment Artifact Repository | ✓ |
| `ari-skill-web` | `web_search`, `fetch_url`, `search_arxiv`, `search_semantic_scholar`, `search_papers`, `set_retrieval_backend`, `collect_references_iterative`, `list_uploaded_files`, `read_uploaded_file` | Web search, arXiv, pluggable retrieval (Semantic Scholar / AlphaXiv), uploaded file access | △ |
| `ari-skill-plot` | `generate_figures`, `generate_figures_llm` | Deterministic + LLM-based matplotlib figure generation | ✓ |
| `ari-skill-paper` | `list_venues`, `get_template`, `generate_section`, `compile_paper`, `check_format`, `review_section`, `revise_section`, `write_paper_iterative`, `review_compiled_paper` | LaTeX paper writing, compilation, peer review | ✓ |
| `ari-skill-paper-re` | `extract_metric_from_output`, `reproduce_from_paper` | ReAct reproducibility verification agent | ✓ |
| `ari-skill-figure-router` | (figure type classification) | Figure type classification and generation routing (SVG/matplotlib/LaTeX) | ✓ |
| `ari-skill-benchmark` | `analyze_results`, `plot`, `statistical_test` | CSV/JSON/NPY analysis, plotting, scipy stats (used in BFTS analyze stage) | ✗ |
| `ari-skill-review` | `parse_review`, `generate_rebuttal`, `check_rebuttal` | Peer-review parsing + rebuttal generation | ✓ |
| `ari-skill-vlm` | `review_figure`, `review_table` | VLM-based figure/table review (drives VLM review loop) | ✓ |

| `ari-skill-coding` | `write_code`, `run_code`, `read_file`, `run_bash` | Code generation + execution + paginated file read | ✗ |

**Additional skills** (available, not in default workflow):

| Skill | Tools | Role | LLM? |
|-------|-------|------|------|
| `ari-skill-orchestrator` | `run_experiment`, `get_status`, `list_runs`, `list_children`, `get_paper` | Expose ARI as MCP server, recursive sub-experiments, dual stdio+HTTP transport | ✗ |

✗ = no LLM, △ = LLM in some tools only, ✓ = primary tools use LLM. 15 skills total (14 default, 1 additional).

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
