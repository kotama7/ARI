# MCP Skills Reference

Skills are MCP servers that provide tools to the ARI agent. Tools are deterministic where possible; LLM-using tools are explicitly annotated. 15 skills total (14 default, 1 additional).

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

#### `review_compiled_paper(tex_path, pdf_path, figures_manifest_json, paper_summary)`

PDF-based holistic paper review: text extraction, figure caption evaluation, structured quality report.

Model: `ARI_LLM_MODEL` env > `LLM_MODEL` env > `ollama_chat/qwen3:32b`.

---

## ari-skill-paper-re

Reproducibility verification via ReAct agent loop. **LLM: Yes**.

The agent reads the generated paper, extracts the experimental configuration, re-implements and runs the experiment from scratch, then compares results against claimed metrics.

### Tools

#### `extract_metric_from_output(output_text, metric_name)`

LLM extracts a specific metric value from raw output text.

#### `reproduce_from_paper(paper_path="", paper_text="", experiment_goal="", work_dir="", source_file="", executor="", cpus=64, timeout_minutes=15, tolerance_pct=5.0)`

Full ReAct reproducibility verification. Internally uses sub-tools: `write_file`, `run_bash`, `read_file`, `report_metric`, `submit_job` (for non-local executors).

Supports executors: `local`, `slurm`, `pbs`, `lsf`. Max ReAct steps: 40.

Verdict thresholds: ≥80% → REPRODUCED | 40–79% → PARTIAL | <40% → NOT_REPRODUCED

Model: `ARI_LLM_MODEL` env > `LLM_MODEL` env > `ollama_chat/qwen3:32b`.

---

## ari-skill-memory

Ancestor-scoped node memory. Prevents cross-branch contamination. **LLM: No** (deterministic keyword matching).

### Tools

#### `add_memory(node_id, text, metadata=None)`

Store a memory entry tagged with `node_id`.

#### `search_memory(query, ancestor_ids, limit=5)`

Only returns entries from nodes listed in `ancestor_ids` (the ancestor chain). Uses keyword matching.

#### `get_node_memory(node_id)`

Retrieve all memories for a specific node.

#### `clear_node_memory(node_id)`

Delete all memories for a specific node.

Storage: `{ARI_CHECKPOINT_DIR}/memory_store.jsonl` per experiment (append-only JSONL, override with `ARI_MEMORY_PATH`)

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

## ari-skill-figure-router

Figure type classification and generation routing. **LLM: Yes**.

Classifies requested figures into optimal rendering backends (SVG/matplotlib/LaTeX) and routes generation accordingly. Registered as a default skill with `phase: all`.

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

2. Register in your BFTS config YAML:

```yaml
skills:
  - name: your-skill
    path: /path/to/ari-skill-yourskill
```

3. Reference the tool name in `experiment.md`'s `## Required Workflow`.

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

## ari-skill-review

Peer-review parsing and rebuttal generation. **LLM: Yes**.

### Tools

#### `parse_review(review_text)`

LLM parses a free-text review into structured form: summary, concerns (id/severity/text), questions, suggestions.

#### `generate_rebuttal(concerns, paper_context, experiment_results)`

LLM generates a point-by-point rebuttal in LaTeX format.

#### `check_rebuttal(rebuttal, original_concerns)`

LLM checks rebuttal completeness: coverage (0-1), missing items, suggestions.

Model: `ARI_LLM_MODEL` env > `LLM_MODEL` env > `ollama/qwen3:8b`.

---

## ari-skill-vlm

Vision-Language model for figure and table quality review. **LLM: Yes** (VLM).

### Tools

#### `review_figure(image_path, context="", criteria=None)`

VLM reviews an experiment figure. Returns score (0-1), issues, suggestions.

#### `review_table(latex_or_path, context="")`

VLM reviews a table (LaTeX source or rendered image). Returns score, issues, suggestions.

Model: `VLM_MODEL` env > `openai/gpt-4o`.
