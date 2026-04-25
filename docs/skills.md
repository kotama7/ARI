# MCP Skills Reference

Skills are MCP servers that provide tools to the ARI agent. Tools are deterministic where possible; LLM-using tools are explicitly annotated. 13 skills total (12 default, 1 additional).

## ari-skill-hpc

HPC job management via SLURM and Singularity. **LLM: No** (fully deterministic).

### Tools

#### `slurm_submit(script, job_name, partition, nodes=1, walltime="01:00:00", work_dir)`

Submit a SLURM batch job.

```python
result = slurm_submit(
    script="""
#!/bin/bash
#SBATCH --cpus-per-task=32
gcc -O3 -fopenmp -o ./bench ./bench.c
OMP_NUM_THREADS=32 ./bench
""",
    job_name="bench_test",
    partition="your_partition",
    work_dir="/abs/path/to/workdir"
)
# Returns: {"job_id": "12345", "status": "submitted"}
```

**Notes:**
- `--account` and `-A` headers are silently stripped
- Empty `job_id` returns ERROR immediately
- Never use `~` in paths inside scripts (not expanded in SBATCH)

#### `job_status(job_id)`

Poll SLURM job status.

```python
result = job_status("12345")
# Returns: {"status": "COMPLETED", "exit_code": 0, "stdout": "MFLOPS: 284172"}
# Status values: PENDING, RUNNING, COMPLETED, FAILED, ERROR
```

#### `job_cancel(job_id)`

Cancel a running or pending SLURM job.

#### `run_bash(command)`

Run a bash command on the login node.

```python
result = run_bash("cat /path/to/slurm_job_12345.out")
# Returns: {"stdout": "...", "exit_code": 0}
```

#### `singularity_build(definition_file, output_path, partition)`

Build a Singularity container from a definition file.

#### `singularity_run(image_path, command, work_dir, partition, nodes=1, walltime="01:00:00")`

Run a Singularity container as a SLURM job.

#### `singularity_pull(source, output_path, partition)`

Pull a Singularity image from a remote registry.

#### `singularity_build_fakeroot(definition_content, output_path, partition, walltime)`

Build a Singularity container using fakeroot mode.

#### `singularity_run_gpu(image_path, command, work_dir, partition, gres="gpu:1", cpus_per_task=8, walltime="01:00:00", bind_paths=[])`

Run a Singularity container with GPU access (`--nv` flag).

---

## ari-skill-idea

Literature survey and idea generation. **LLM: Yes** (generate_ideas uses VirSci multi-agent deliberation).

### Tools

#### `survey(topic, max_papers=8)`

Search Semantic Scholar for related papers. Deterministic (no LLM).

```python
result = survey("OpenMP compiler optimization HPC benchmarks")
# Returns: {"papers": [{"title": "...", "abstract": "...", "url": "..."}]}
```

Requires `S2_API_KEY` environment variable for higher Semantic Scholar rate limits.

#### `generate_ideas(topic, papers, experiment_context="", n_ideas=3, n_agents=4, max_discussion_rounds=2, max_recursion_depth=0)`

Generate research hypotheses using VirSci multi-agent LLM deliberation. Multiple AI personas (researcher, critic, expert, synthesizer) debate the research question. Called **once** before BFTS starts (pre-BFTS only).

Model: `ARI_LLM_MODEL` env > `LLM_MODEL` env > `ollama_chat/qwen3:32b`.

---

## ari-skill-evaluator

Metric spec extraction from experiment files. **LLM: Conditional** (fallback only when metric_keyword not found in text).

### Tools

#### `make_metric_spec(experiment_text)`

Parse experiment Markdown to extract evaluation criteria. Deterministic when `metric_keyword` and `min_expected_metric` are present in the text; falls back to LLM if not found.

```python
result = make_metric_spec(open("experiment.md").read())
# Returns: {
#   "metric_keyword": "MFLOPS",
#   "min_expected_metric": 50000.0,
#   "scoring_guide": "..."
# }
```

Model (fallback): `ARI_MODEL` env > `gpt-4o-mini`.

---

## ari-skill-paper

LaTeX paper generation, compilation, and review (post-BFTS only). **LLM: Yes**.

### Tools

#### `list_venues()`

Returns available venue configurations.

Supported venues: `neurips` (9 pages), `icpp` (10 pages), `sc` (12 pages), `isc` (12 pages), `arxiv` (unlimited), `acm` (10 pages).

#### `get_template(venue)`

Returns the LaTeX template for a venue.

#### `generate_section(section, context, venue="arxiv", refs_json="", nodes_json_path="")`

Generate a LaTeX section using LLM. Section types: `introduction`, `related_work`, `method`, `experiment`, `conclusion`.

#### `compile_paper(tex_dir, main_file="main.tex")`

Run pdflatex compilation. Returns success status and error messages.

#### `check_format(venue, pdf_path)`

Validate paper format against venue requirements (page count, etc.).

#### `review_section(latex, context, venue="arxiv")`

Review a LaTeX section. Returns strengths, weaknesses, and suggestions.

#### `revise_section(section, latex, feedback)`

Revise a LaTeX section based on review feedback.

#### `write_paper_iterative(experiment_summary, context, nodes_json_path, refs_json, figures_manifest_json, output_dir, max_revisions=2, venue="arxiv")`

Full paper generation with iterative draft → review → revise loop. Primary pipeline tool.

#### `review_compiled_paper(tex_path, pdf_path, figures_manifest_json, experiment_summary, rubric_id="", vlm_findings_json="", num_reflections=None, num_fs_examples=None)`

Rubric-driven paper review compatible with the **AI Scientist v1/v2** pipeline
(Nature / arXiv:2408.06292 Appendix A.4). Loads a YAML rubric from
`ari-core/config/reviewer_rubrics/<rubric_id>.yaml`, renders prompts from the
rubric's `score_dimensions` / `text_sections` / `decision` schema, injects VLM
per-figure findings as reviewer notes, optionally prepends few-shot example
reviews, runs a self-reflection loop, then normalises the output to a
rubric-stable JSON schema.

Bundled rubrics (16 YAMLs in `ari-core/config/reviewer_rubrics/`):

| Family | Rubric IDs |
|---|---|
| ML conferences | `neurips` (default, v2-compatible), `iclr`, `icml`, `cvpr`, `acl` |
| Systems / HPC | `sc`, `osdi`, `usenix_security` |
| Theory / graphics | `stoc`, `siggraph` |
| HCI / robotics | `chi`, `icra` |
| Journals / generic | `nature`, `journal_generic`, `workshop`, `generic_conference` |

Add a new venue by dropping `<id>.yaml` into `reviewer_rubrics/` — no code
changes required. Each rubric declares `score_dimensions`, `text_sections`,
`decision` rules, execution parameters, and a SHA256 hash for P2 determinism.

Rubric resolution order: explicit `rubric_id` arg → `ARI_RUBRIC` env →
`neurips` → built-in `legacy` fallback (v0.5 schema, used when neither
`rubric_id` nor any matching YAML resolves).

Nature Ablation defaults (best-config rationale):

- `num_reflections: 5` — +2% balanced accuracy
- `num_fs_examples: 1` — +2% balanced accuracy (1-shot from ICLR reviewer guidelines)
- `num_reviews_ensemble: 1` — ensemble does not improve accuracy, only variance
- `temperature: 0.75`

Model: `ARI_LLM_MODEL` env > `LLM_MODEL` env > `ollama_chat/qwen3:32b`.

**Ensemble + Area Chair meta-review (built in):** `review_compiled_paper` runs
N independent reviewer agents via the ensemble path (temperature jitter, AI
Scientist v1 best-config style). When N>1, it also runs the Area Chair
meta-review internally and attaches `ensemble_reviews: [...]` and
`meta_review: {...}` to the output. N resolves as: explicit arg >
`ARI_NUM_REVIEWS_ENSEMBLE` env > `rubric.params.num_reviews_ensemble`
(defaults to 1). N=1 is equivalent to a single reviewer.

#### `list_rubrics()`

Returns the list of available rubrics (id, venue, domain, version, SHA256
hash, path). Used by the viz API `/api/rubrics` and the New Experiment wizard
dropdown.

##### Few-shot corpus management

The files under `ari-core/config/reviewer_rubrics/fewshot_examples/<rubric>/`
can be managed from the **New Experiment Wizard → Paper Review → Few-shot
Examples** sub-panel (GUI) or with `scripts/fewshot/sync.py` (CLI).

GUI actions:

- **Auto-sync** — server-side runs `scripts/fewshot/sync.py --venue <rubric>`
  which pulls entries declared in `scripts/fewshot/manifest.yaml`. By default
  this includes the three AI Scientist v2 fewshot papers
  (`132_automated_relational`, `2_carpe_diem`, `attention`) downloaded from
  the Apache-2.0 `SakanaAI/AI-Scientist-v2` repo.
- **Upload** — accepts a rubric-shaped JSON review form plus an optional
  `.txt` excerpt and optional PDF (base64). The JSON is stamped with
  `_source: "GUI upload (rubric=<id>)"` for provenance.
- **Delete** — removes every sibling file of an example.

Backing REST endpoints:

- `GET  /api/fewshot/<rubric>`              list examples
- `POST /api/fewshot/<rubric>/sync`          sync from manifest
- `POST /api/fewshot/<rubric>/upload`        upload one example
- `POST /api/fewshot/<rubric>/<example>/delete` delete

All endpoints refuse any rubric not present in `reviewer_rubrics/` and strip
`../` sequences / slashes from both rubric and example ids.

---

## ari-skill-paper-re

Reproducibility verification helpers. **LLM: Yes** (two one-shot LLM
calls, no in-skill loop).

Starting from v0.6.0, the ReAct loop lives in
`ari-core/ari/agent/react_driver.py`. The driver is invoked by
`ari.pipeline._run_react_stage` whenever a stage declares a `react:`
block. The skill now contains only the deterministic edges of the
reproducibility flow:

```
pre_tool (extract_repro_config)  →  react_driver  →  post_tool (build_repro_report)
          one LLM call               MCP-whitelisted         one LLM call
          (paper-re)                 ReAct loop              (paper-re)
```

The ReAct loop sees only MCP tools whose `skills[].phase` list in
`workflow.yaml` includes `reproduce` (e.g. `web-skill`, `vlm-skill`,
`hpc-skill`, `coding-skill`). `memory-skill`, `transform-skill`, and
`evaluator-skill` are deliberately excluded so the agent cannot reach
BFTS-phase artefacts (`nodes_tree.json`, ancestor memories, etc.).

### Tools

#### `extract_repro_config(paper_path="", paper_text="")`

One-shot LLM call. Reads the paper text (or the file at `paper_path`;
`.pdf` is converted via `pdftotext`) and returns
`{metric_name, claimed_value, description, threads}` — the value the
authors advertise plus the exact experimental parameters stated nearby.

#### `build_repro_report(claimed_config, actual_value, actual_unit="", actual_notes="", tolerance_pct=5.0)`

One-shot LLM call that writes the 2–3 sentence interpretation. Called
by the pipeline *after* `react_driver` finishes; `actual_value` is the
number the ReAct agent passed to its `report_metric` final tool
(`None` if the agent never produced a reliable measurement).

Verdict thresholds: ≤`tolerance_pct` → REPRODUCED | ≤20% → PARTIAL |
else → NOT_REPRODUCED | `actual_value is None` → UNVERIFIABLE.

#### `extract_metric_from_output(output_text, metric_name)`

Helper the ReAct agent may call to parse a numeric metric from raw
benchmark stdout (LLM extraction with a regex fallback). Not used by
the pre/post pipeline endpoints.

Model: `ARI_MODEL_PAPER` > `ARI_LLM_MODEL` > `LLM_MODEL` >
`ollama_chat/qwen3:32b`.

---

## ari-skill-memory

Ancestor-scoped node memory, backed by [Letta](https://docs.letta.com)
in v0.6.0. Prevents cross-branch contamination and stores a separate
ReAct-trace collection for the agent loop. **LLM: △** (embedding-based
retrieval; see PHILOSOPHY.md for the P2/P5 relaxation note).

### Tools

#### `add_memory(node_id, text, metadata=None)`

Store an entry tagged with `node_id`. **Copy-on-Write**: rejects writes
whose `node_id` ≠ `$ARI_CURRENT_NODE_ID` so a child cannot mutate an
ancestor's entries.

#### `search_memory(query, ancestor_ids, limit=5)`

Return entries whose `node_id` is in `ancestor_ids`, ranked by Letta
relevance (`score` ∈ [0, 1]). Siblings and children are never returned.

#### `get_node_memory(node_id)`

All entries for a specific node (chronological, no scoring).

#### `clear_node_memory(node_id)`

Debug-only per-node clear. Same CoW rule as `add_memory`.

#### `get_experiment_context()`

Stable experiment facts read from Letta core memory — `experiment_goal`,
`primary_metric`, `hardware_spec`, etc. Seeded once after the first
node's `generate_ideas` completes (the moment `primary_metric` is
determined); safe to call repeatedly (60 s in-process cache). Returns
`{}` until that seed runs.

Storage: per-checkpoint Letta agent with two archival collections
(`ari_node_*`, `ari_react_*`). A snapshot at
`{ARI_CHECKPOINT_DIR}/memory_backup.jsonl.gz` keeps checkpoints
portable. v0.5.x JSONL stores (`memory_store.jsonl`,
`~/.ari/global_memory.jsonl`) are removed; use `ari memory migrate`
to import legacy data. Cross-experiment "global memory" is no longer
a feature — stable lessons belong in `experiment.md`, code, or prior
papers.

---

## ari-skill-orchestrator

Expose ARI as an MCP server for external agents and IDEs. Supports recursive sub-experiments. **LLM: No** (delegates to ARI CLI).

Dual transport: **stdio** (MCP for Claude Desktop / other MCP clients) + **HTTP** (REST + SSE on `ARI_ORCHESTRATOR_PORT`, default 9890).

### Tools

#### `run_experiment(experiment_md, max_nodes=10, model="qwen3:32b", parent_run_id="", recursion_depth=0, max_recursion_depth=0)`

Launch an ARI experiment asynchronously. Returns `run_id`. When `parent_run_id` is set, the experiment is tracked as a child of the parent (for recursive sub-experiment workflows).

#### `get_status(run_id)`

Return progress, current best metrics, and recursion metadata for a run.

#### `list_runs()`

List all past experiment runs.

#### `list_children(run_id)`

Return child runs of a parent experiment (for recursive sub-experiment tracking).

#### `get_paper(run_id)`

Return the generated paper (LaTeX).

Workspace: `ARI_WORKSPACE` env (default: `~/ARI`). Parent-child relationships persisted in `meta.json` per checkpoint.

---

## ari-skill-transform

Converts BFTS internal representation to publication-ready scientific data format. Strips all internal fields (`node_id`, `label`, `depth`, `parent_id`) and exposes only scientific content (`configurations`, `experiment_context`). **LLM: Yes**.

### Tools

#### `nodes_to_science_data(nodes_json_path, llm_model="", llm_base_url="")`

LLM analyzes the full BFTS tree, extracting hardware specs, methodology, key findings, and comparisons.

Returns: `{configurations, per_key_summary, experiment_context, summary_stats}`.

Model: `llm_model` arg > `LLM_MODEL` env > `gpt-4o-mini`.

**Why it exists:** Ensures BFTS-internal terminology never leaks into generated papers or figures.

#### `generate_ear(checkpoint_dir, llm_model="", llm_base_url="")`

Builds a structured **Experiment Artifact Repository (EAR)** under `<checkpoint>/ear/` for reproducibility. Contents:

- `README.md` and `RESULTS.md` (LLM-generated when available, deterministic fallback otherwise)
- `code/<node_id>/` — source files copied from each node's experiment directory
- `data/raw_metrics.json`, `data/science_data.json`, `data/figures/`
- `logs/bfts_tree.json`, `logs/eval_scores.json`
- `reproducibility/environment.json` (Python version, platform, pip packages, hardware)
- `reproducibility/run_config.json`, `reproducibility/commands.md`

Returns: `{ear_dir, manifest}` with paths to all generated files.

---

## ari-skill-web

Web search and academic literature retrieval with pluggable backends. **LLM: Partial** (only `collect_references_iterative` uses LLM).

### Tools

#### `web_search(query, n=5)`

DuckDuckGo web search. No API key required. Deterministic.

#### `fetch_url(url, max_chars=8000)`

Fetch and extract text from a URL via BeautifulSoup. Deterministic.

#### `search_arxiv(query, max_results=5)`

arXiv paper search. Deterministic.

#### `search_semantic_scholar(query, limit=8, extra_queries=None)`

Semantic Scholar API with fallback to arXiv. Deterministic.

#### `search_papers(query, limit=8)`

Dispatches to the configured retrieval backend (`ARI_RETRIEVAL_BACKEND`):
- `"semantic_scholar"` (default) — Semantic Scholar API
- `"alphaxiv"` — AlphaXiv via MCP JSON-RPC over HTTP
- `"both"` — parallel execution with deduplication

#### `set_retrieval_backend(backend)`

Dynamically switch the retrieval backend at runtime. Valid values: `"semantic_scholar"`, `"alphaxiv"`, `"both"`.

#### `collect_references_iterative(experiment_summary, keywords, max_rounds=20, min_papers=10)`

AI Scientist v2-style iterative citation collection. LLM generates search queries and selects relevant papers across multiple rounds.

Model: `ARI_LLM_MODEL` env > `LLM_MODEL` env > `ollama_chat/qwen3:32b`.

#### `list_uploaded_files()`

Lists user-uploaded files in the checkpoint directory. Deterministic.

#### `read_uploaded_file(filename, max_chars=8000)`

Reads text file content from uploaded files with binary detection. Deterministic.

---

## ari-skill-coding

Code generation, execution, and file reading. **LLM: No** (deterministic).

### Tools

#### `write_code(filename, code, work_dir="/tmp/ari_work")`

Write a source file to the work directory.

#### `run_code(filename, work_dir="/tmp/ari_work", timeout=60)`

Execute a source file (auto-detects language from extension). Output is truncated with an informative marker showing omitted character count and a hint to redirect to a file.

#### `run_bash(command, work_dir="/tmp/ari_work", timeout=60)`

Run a bash command in the work directory. Output truncation with `truncated` boolean flag in result.

#### `read_file(filepath, offset=0, limit=2000, work_dir="/tmp/ari_work")`

Read a text file with paginated access for large files. Returns content, `next_offset` for continuation, and total line count.

```python
result = read_file("results.csv", offset=0, limit=100)
# Returns: {"content": "...", "next_offset": 100, "total_lines": 5000}
```

Work directory: `work_dir` arg > `ARI_WORK_DIR` env > `/tmp/ari_work`.

---

## ari-skill-benchmark

Performance analysis, plotting, and statistical testing. **LLM: No** (deterministic).

### Tools

#### `analyze_results(result_path, metrics)`

Load and analyze CSV, JSON, or NPY result files. Returns summary statistics.

#### `plot(data, plot_type, output_path, title="", xlabel="", ylabel="")`

Generate matplotlib figures. Plot types: `bar`, `line`, `scatter`, `heatmap`.

#### `statistical_test(data_a, data_b, test)`

Run scipy statistical tests: `ttest`, `mannwhitney`, `wilcoxon`.

---

## ari-skill-vlm

Vision-Language model for figure and table quality review. **LLM: Yes** (VLM).

### Tools

#### `review_figure(image_path, context="", criteria=None)`

VLM reviews an experiment figure. Returns score (0-1), issues, suggestions.

#### `review_table(latex_or_path, context="")`

VLM reviews a table (LaTeX source or rendered image). Returns score, issues, suggestions.

Model: `VLM_MODEL` env > `openai/gpt-4o`.

---

## Writing a New Skill

1. Create `ari-skill-yourskill/src/server.py`:

```python
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("your-skill")

@mcp.tool()
def your_tool(param: str) -> dict:
    """Tool description."""
    # NO LLM calls here
    return {"result": process(param)}

if __name__ == "__main__":
    mcp.run()
```

2. Register in `ari-core/config/workflow.yaml`. `phase` scopes which
   pipeline-phase ReAct agents see the skill (string for one phase,
   list for several):

```yaml
skills:
  - name: your-skill
    path: '{{ari_root}}/ari-skill-yourskill'
    phase: [paper, reproduce]
```

   Valid phase values: `bfts`, `paper`, `reproduce`, `all`, `none`.

3. Reference the tool name in `experiment.md`'s `## Required Workflow`.
