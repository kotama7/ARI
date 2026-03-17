# MCP Skills Reference

Skills are MCP servers that provide deterministic tools to the ARI agent.
No skill may contain LLM calls (except post-BFTS stages: paper generation and review).

## ari-skill-hpc

HPC job management via SLURM and Singularity.

### Tools

#### `slurm_submit(script, job_name, partition, nodes=1, walltime="01:00:00", work_dir="")`

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
- `--account` and `-A` headers are silently stripped (not valid on this cluster)
- Empty `job_id` returns ERROR immediately
- Never use `~` in paths inside scripts (not expanded in SBATCH)

#### `job_status(job_id)`

Poll SLURM job status.

```python
result = job_status("12345")
# Returns: {"status": "COMPLETED", "exit_code": 0, "stdout": "MFLOPS: 284172"}
# Status values: PENDING, RUNNING, COMPLETED, FAILED, ERROR
```

#### `run_bash(command)`

Run a read-only bash command on the login node.

```python
result = run_bash("cat /path/to/slurm_job_12345.out")
# Returns: {"stdout": "...", "exit_code": 0}
```

#### `singularity_run_gpu(image_path, command, partition, gres="gpu:1")`

Run a Singularity container with GPU access (`--nv` flag).

---

## ari-skill-idea

Literature survey and idea generation.

### Tools

#### `survey(topic, max_papers=5)`

Search arXiv and Semantic Scholar. Fully deterministic (no LLM).

```python
result = survey("OpenMP compiler optimization HPC benchmarks")
# Returns: {"papers": [{"title": "...", "abstract": "...", "url": "..."}]}
```

#### `make_metric_spec(experiment_text)`

Parse experiment Markdown to extract evaluation criteria. Deterministic.

```python
result = make_metric_spec(open("experiment.md").read())
# Returns: {
#   "metric_keyword": "MFLOPS",
#   "min_expected_metric": 50000.0,
#   "scoring_guide": "..."
# }
```

#### `generate_ideas(topic, papers, experiment_context="", n_ideas=3)`

Generate research hypotheses using LLM. Called **once** before BFTS starts (pre-BFTS only).

---

## ari-skill-evaluator

Metric extraction from experiment artifacts.

### Tools

#### `evaluate(artifacts, goal, metric_spec)`

Extract metrics from raw artifact text. Returns `has_real_data` and `metrics` dict.
No scalar score — multi-objective evaluation only.

#### `make_artifact_extractor(metric_keyword)`

Return Python code for extracting a specific metric from output text.

---

## ari-skill-paper

LaTeX paper generation and review (post-BFTS only).

### Tools

#### `generate_section(section, context, venue="arxiv", nodes_json_path="")`

Generate a LaTeX section using LLM. Searches `nodes_tree.json` for evidence.

Section types: `introduction`, `related_work`, `method`, `experiment`, `conclusion`

```python
result = generate_section(
    section="experiment",
    context="Best result: 284172 MFLOPS with -O3 -fopenmp -march=native, 32 threads",
    venue="arxiv",
    nodes_json_path="/path/to/nodes_tree.json"
)
```

#### `review_section(latex, context, venue="arxiv")`

Review a LaTeX section. Returns strengths, weaknesses, and suggestions.

---

## ari-skill-paper-re

Reproducibility verification. Fully deterministic (no LLM).

### Tools

#### `extract_claims(paper_text, max_claims=50)`

Extract numeric claims from paper using regex patterns.

#### `compare_with_results(claims, actual_metrics, tolerance_pct=10.0)`

Compare claims against measured metrics within a tolerance window.

#### `reproducibility_report(paper_text, actual_metrics, paper_title="", tolerance_pct=10.0)`

Generate a complete reproducibility report.

Verdict thresholds: ≥80% → REPRODUCED | 40–79% → PARTIAL | <40% → NOT_REPRODUCED

---

## ari-skill-memory

Ancestor-scoped node memory. Prevents cross-branch contamination.

### Tools

#### `add_memory(node_id, text, metadata=None)`
#### `search_memory(query, ancestor_ids, limit=5)`

Only returns entries from nodes listed in `ancestor_ids` (the ancestor chain).

#### `get_node_memory(node_id)`
#### `clear_node_memory(node_id)`

Storage: `~/.ari/memory_store.jsonl` (append-only JSONL)

---

## ari-skill-orchestrator

Expose ARI as an MCP server for external agents and IDEs.

### Tools

#### `run_experiment(experiment_md, max_nodes=10, model="qwen3:32b")`

Submit an experiment asynchronously. Returns `run_id`.

#### `get_status(run_id)`

Return progress and current best metrics for a run.

#### `get_paper(run_id)`

Return the generated `experiment_section.tex`.

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

Converts BFTS internal representation () to publication-ready scientific data format. Strips all internal fields (, , , ) and exposes only scientific content (, ).

**Tools:**
-  — returns ranked configurations with metrics only

**Why it exists:** Ensures BFTS-internal terminology never leaks into generated papers or figures.

---

## ari-skill-web

Web search and academic literature retrieval.

**Tools:**
-  — general web search
-  — arXiv paper search
-  — Semantic Scholar citation lookup
