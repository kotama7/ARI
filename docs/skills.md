# MCP Skills Reference

Skills are MCP servers that provide tools to the ARI agent. Tools are deterministic where possible; LLM-using tools are explicitly annotated. **14 skills total** (13 default, 1 additional) — `ari-skill-replicate` was added in v0.7.0 for the PaperBench-format reproducibility flow.

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
#   "metric_keyword": "GFLOP_per_s",
#   "expected_metrics": ["GFLOP_per_s", "GB_per_s"],   # MEASURED outputs
#   "expected_params":  ["M", "K", "nnz", "threads"],  # INPUT knobs
#   "min_expected_metric": 50000.0,
#   "scoring_guide": "..."
# }
```

`expected_metrics` and `expected_params` are strictly disjoint by contract — a name appears in one or the other, never both. The LLM-fallback path is the only one that fills `expected_params` (the regex path covers the experiment.md-format quick path, which has no consistent "## Parameters" header to mine). `loop.py` threads `expected_params` into `MetricSpec` so the LLM evaluator emits a typed `params` / `measurements` split on each node, which `transform-skill::nodes_to_science_data` then propagates to `configurations[*].parameters` (C contract — see also the D contract via `coding-skill::emit_results`).

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

#### `inject_code_availability(tex_path, checkpoint_dir)` — v0.7.0

Runs as the `finalize_paper` stage. Auto-loads the curated bundle's
`ref` / `bundle_sha256` / `doi` from `ear_published/manifest.lock` +
`publish_record.json` and injects machine-readable `\codeavailability{}`,
`\codedigest{}`, `\coderef{}` macros plus a human-readable Code
Availability section into `full_paper.tex`. The macros let downstream
tools (`ari clone`, third-party readers) recover the bundle without
trusting the registry — the digest is the trust anchor. Skips silently
when no curated bundle exists (so v0.6.0 checkpoints keep building).

#### `merge_reviews(review_report_path, vlm_review_path)` — v0.7.0

Post-hoc structural merge of `review_report.json` (text reviewer) and
`vlm_review.json` (VLM figure review). Purely deterministic — no LLM.
Attaches `vlm_figure_review` and `_review_composition` metadata so the
GUI / CLI can show both outputs with clear source attribution. The
upstream stages stay independent (matching AI Scientist v2's
`perform_review` contract) and are reconciled here.

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

Reproducibility grading via PaperBench (arXiv:2504.01848) **SimpleJudge**.
**LLM: Yes** (the judge is an LLM call inside the upstream
`SimpleJudge`; ARI itself adds no extra LLM calls in this skill).

v0.7.0 replaces the v0.6.0 LLM-driven verdict path
(`extract_repro_config` → `react_driver` → `build_repro_report`) with a
deterministic chain whose grading core is taken from PaperBench:

```
ors_generate_rubric  (replicate-skill)    → ors_rubric.json + ors_rubric.meta.json
ear_publish          (transform-skill)    → bundle.tar.gz + publish_record.json (local-tarball default)
ors_seed_sandbox     (paper-re-skill)     → repro_sandbox/{reproduce.sh, code/...}
                                              (deterministic; fetch_code_bundle ← publish_record.json)
ors_build_reproduce  (paper-re-skill)     → repro_sandbox/{reproduce.sh, source files}
                                              (LLM fallback; skipped if seed populated reproduce.sh)
ors_run_reproduce    (paper-re-skill)     → ors_phase1.json   (Phase 1: sandbox-execute reproduce.sh)
ors_grade            (paper-re-skill)     → ors_grade.json    (Phase 2: SimpleJudge over the rubric leaves)
```

EAR-on runs flow through `ors_seed_sandbox` (deterministic seed); the
LLM `ors_build_reproduce` skips when reproduce.sh is already present,
so it only fires on EAR-off runs (paper-only reproduction).

PaperBench is vendored as a git submodule under
`ari-skill-paper-re/vendor/paperbench`; the bridge module
`_paperbench_bridge.py` adapts the upstream `TaskNode` /
`SimpleJudge` API to ARI's rubric envelope. The main per-leaf grading
completer routes through LiteLLM (`_litellm_completer.py`) so any
provider works (`gpt-5-mini`, `anthropic/claude-...`, `gemini/...`,
`ollama/...`); the score-parsing structured completer stays on
`gpt-4o-2024-08-06` (within PaperBench's allow-list).

### Tools

#### `fetch_code_bundle(ref="", sha256="", dest, checkpoint_dir="", overwrite=False)`

Pre-populates the reproducibility sandbox with a curated EAR bundle
via `ari.clone` — deterministic, no LLM. Two ways to point at the
bundle:

- **Direct ref**: `ref="file:///path/to/bundle.tar.gz"` /
  `ref="ari://0ccabb16…"` / `ref="gh:owner/repo"` / `ref="https://…"`.
- **Auto-load from publish_record.json** (v0.7.0+): pass
  `checkpoint_dir={checkpoint}`; ref + sha256 are read from
  `{checkpoint_dir}/publish_record.json` (the file `ari ear publish`
  writes). Mirrors the convention `inject_code_availability` uses.

Skips with `populated=False, skipped_reason=...` when `dest/reproduce.sh`
already exists (composes after `ear` seed / a prior bundle); refuses to
clobber a non-empty dest unless `overwrite=True`.

```python
# Workflow stage: auto-load from the local-tarball backend's record.
result = fetch_code_bundle(
    checkpoint_dir="/path/to/checkpoint",
    dest="/path/to/checkpoint/repro_sandbox",
)
# Returns: {"populated": True, "dest": ..., "bundle_sha256": ..., "files": ...}
```

#### `build_reproduce_sh(paper_path, paper_text, rubric_path, output_dir, model="", temperature=0.0, timeout_sec=600, overwrite=False)`

**LLM-driven replicator** (v0.7.0+). Sibling of `fetch_code_bundle`:
both target `repro_sandbox/`. Reads the paper (and the rubric's
`reproduce_contract.expected_artifacts` when `rubric_path` is given)
and writes a self-contained `reproduce.sh` + supporting source files
into `output_dir`.

Routes through LiteLLM, so any provider works. Model resolves
`model` arg > `ARI_MODEL_REPLICATE` env > `ARI_LLM_MODEL` env >
`claude-opus-4-7`. Output JSON is sanity-checked (every file path is
filesystem-safe ASCII, no `..`, `reproduce.sh` is shebanged + has
`set -euo pipefail`, total content < 200 KB).

Skips with `populated=False, skipped_reason=...` when `output_dir/reproduce.sh`
is already present, so it composes cleanly after `fetch_code_bundle` /
EAR pre-populate. The workflow's `ors_build_reproduce` stage sets this
ordering — when `include_ear=true`, the EAR-seeded reproduce.sh wins;
when off, the LLM falls through.

```python
result = build_reproduce_sh(
    paper_path="full_paper.tex",
    rubric_path="ors_rubric.json",
    output_dir="repro_sandbox",
)
# Returns: {populated, output_dir, files, expected_artifacts,
#           max_runtime_sec, language, model, prompt_sha256, notes, warnings}
```

#### `run_reproduce(rubric_path, repo_dir, sandbox_kind="", timeout_global_sec=0, partition="", cpus=0, walltime="")`

**Phase 1**. Executes `repo_dir/reproduce.sh` in a sandbox; captures
`reproduce.log` and lists artefacts; reports any
`expected_artifacts` (from the rubric envelope) that did not appear.

Sandbox priority (`auto`, the default): `slurm` (when sbatch is on
PATH AND `ARI_SLURM_PARTITION` is set — the same partition BFTS used)
→ `docker` (when daemon usable and not on HPC) → `apptainer` →
`singularity` → `local`. Override with the `sandbox_kind` argument
or `ARI_PHASE1_SANDBOX`. The container image is `docker://ubuntu:24.04`
by default (`ARI_PHASE1_DOCKER_IMAGE` / `ARI_PHASE1_APPTAINER_IMAGE` /
`ARI_PHASE1_SINGULARITY_IMAGE` to customise).

**SLURM dispatch** (v0.7.0, restored from v0.5.0): submits via
`sbatch --wait` so the call blocks until the job finishes and
inherits the job's exit code. partition / cpus / walltime resolve
arg > env (`ARI_SLURM_PARTITION` / `ARI_SLURM_CPUS` /
`ARI_SLURM_WALLTIME`) > `{checkpoint_dir}/launch_config.json`. A tiny
wrapper script (`{repo_dir}/.slurm_wrap.sh`) is generated to bypass
sbatch's spool-relocation: it `exec bash`'s the user reproduce.sh by
absolute path so `$0`-relative `cd "$(dirname "$0")/code"` still works
inside the spooled job.

```python
result = run_reproduce(
    rubric_path="ors_rubric.json",
    repo_dir="repro_sandbox",
)
# Returns: {executed, exit_code, log_path, artifacts, missing,
#           elapsed_sec, sandbox_kind, [partition, cpus, walltime, timed_out]}
```

#### `grade_with_simplejudge(rubric_path, repo_dir, paper_path="", paper_text="", judge_model="", n_runs=3, skip_negative_control=False)`

**Phase 2**. Runs PaperBench `SimpleJudge` over the (post-Phase-1)
repo + reproduce.log + paper. `n_runs` (default 3) iterations are
averaged using PaperBench's weighted leaf aggregation; a one-off
**negative control** (empty repo + trivial `reproduce.sh`) verifies
the rubric does not reward absence of work — both controls must
score under 5% (`passed=true`).

```python
result = grade_with_simplejudge(
    rubric_path="ors_rubric.json",
    repo_dir="repro_sandbox",
    paper_path="full_paper.tex",
)
# Returns: {ors_score, raw_score, leaf_grades, judge_model, n_runs,
#           rubric_sha256, elapsed_sec, negative_control: {empty, boilerplate, passed}}
```

Model: `judge_model` arg > `ARI_MODEL_JUDGE` > `ARI_LLM_MODEL` > `gpt-5-mini`.

The main per-leaf grading completer routes through LiteLLM
(`_litellm_completer.py`), so any provider LiteLLM understands works
(`gpt-5-mini`, `anthropic/claude-opus-4-7`, `gemini/gemini-2.5-pro`,
`ollama/llama3.1`, etc.) — PaperBench's hand-maintained
`CONTEXT_WINDOW_LENGTHS` registry no longer constrains the choice.
The structured int/float score-parsing completer remains on
`gpt-4o-2024-08-06` (within the registry) since its task is small
and the upstream pydantic-schema integration is OpenAI-shaped.

---

## ari-skill-replicate

PaperBench-format **auto-rubric generator and auditor** introduced in
v0.7.0. Reads a paper and emits a frozen rubric (`replication_rubric.schema.json`,
a PaperBench `TaskNode` tree wrapped with provenance metadata: paper
sha256, generator model, prompt sha256, optional audit metadata).
**LLM: Yes**.

The rubric is consumed by `ari-skill-paper-re.grade_with_simplejudge`;
together they form the ORS reproducibility flow that replaced the
v0.6.0 `react_driver`-based check.

### Tools

#### `generate_rubric(paper_path, paper_text, output_path, target_leaf_count=0, model="", temperature=0.0, seed=0, two_stage=True)`

Produces a PaperBench-compatible rubric. When `target_leaf_count=0`,
the leaf count is auto-computed from paper length (~1 leaf / 75 words,
clamped to [50, 400]).

`two_stage=True` (default) generates the rubric in two passes — a
**skeleton pass** that defines the root + direct children (one node per
major contribution / experiment) with a per-child leaf budget, then
**parallel subtree passes** that recursively populate each direct
child's subtree with 4–6 additional levels. A merge step joins the
populated subtrees back into the skeleton; leaves whose `quote` or
`requirements` violate the schema's `minLength=10` are dropped (a
handful per run is normal). Compared to a single LLM call this produces
roughly 4× more leaves and 1–2 levels more depth on a representative
PaperBench reference paper, at the cost of ~5× more API tokens. Set
`two_stage=False` to use the legacy single-call path
(`prompts/adversarial_reviewer.md`).

#### `audit_rubric(rubric_path, paper_path, paper_text, auditor_model="")`

Independent auditor pass. Flags problematic leaves:
- `vague_qualifier` (e.g. "should improve", "is reasonable")
- `no_paper_evidence` (claim not anchored to paper text)
- `duplicate` (semantically equivalent to a sibling)
- `unverifiable` (no decidable test)

Recommends regeneration when more than 20% of leaves are flagged.

#### `suggest_target_leaf_count(paper_path, paper_text)`

Returns the auto-computed target and the paper's word count. Useful for
the GUI Wizard to pre-fill the "Target leaves" field.

### Environment

| Variable | Default | Purpose |
|---|---|---|
| `ARI_MODEL_RUBRIC_GEN` | `gemini/gemini-2.5-pro` | Generator LLM |
| `ARI_MODEL_RUBRIC_AUDIT` | `anthropic/claude-opus-4-7` | Auditor LLM (independent of generator) |
| `ARI_RUBRIC_GEN_TARGET_LEAVES` | (unset) | Override target leaf count (`0`/unset = auto). GUI Wizard "Target leaves" field. |
| `ARI_RUBRIC_GEN_TEMPERATURE` | (unset) | Override generator temperature. GUI Wizard "Temperature" field. |
| `ARI_RUBRIC_GEN_TWO_STAGE` | (unset) | Force two-stage on/off (`1`/`true`/`on` vs `0`/`false`/`off`). GUI Wizard "Two-stage generation" toggle. |

Env vars are resolved in `server.py` before the generator runs and win
over the kwarg defaults when the workflow stage doesn't pass an
explicit value (the bundled `ors_generate_rubric` stage does not, so
the GUI Wizard always controls these three knobs at runtime).

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

Return entries whose `node_id` is in `ancestor_ids`, **ranked by
semantic similarity to `query`** via Letta's embedding-based
`passages.search` route. Siblings and children are never returned.

Implementation note (verified against Letta 0.16.7, 2026-05-04): the
skill deliberately does NOT use `passages.list(search=q)` — that SDK
call hits `GET /archival-memory?search=q`, which is server-side **SQL
substring matching** (`WHERE LOWER(text) LIKE LOWER(%q%)`), not
semantic search. Long natural-language queries never substring-match
structured passages like `RESULT SUMMARY metrics=[...]`, so every
search would silently return 0 — exactly what was observed in
production runs with 84 valid passages. Instead the skill calls
`passages.search` (`GET /archival-memory/search`, `embed_query=True`)
with `top_k = max(letta_overfetch, limit*40)` to ensure the ancestor-
relevant entries land inside the ranked window, then post-filters
locally by `ancestor_ids`, `ari_checkpoint`, and
`kind == "node_scope"`. The embedding cost paid on every `add_memory`
insert is now actually consumed by retrieval. Order is the embedding
rank order itself — children see entries most relevant to their
`eval_summary` query first.

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

#### `nodes_to_science_data(nodes_json_path, llm_model="", llm_base_url="", primary_metric="", higher_is_better="true")`

LLM analyzes the full BFTS tree, extracting hardware specs, methodology, key findings, and comparisons. The pipeline passes `primary_metric` and `higher_is_better` from `evaluation_criteria.json` (resolved via `tpl_vars` — see `ari-core/ari/pipeline.py`) so direction-aware reductions can be performed without the consumer re-deriving them.

Returns:

```text
configurations[*]:
  rank, label, eval_summary
  parameters / measurements / predictions / scores  ← typed split (when populated)
  metrics                                           ← back-compat flat union
  _typed_source: "results.json" | "llm_evaluator" | (absent)
  _typed_schema_version
per_key_summary:                                    ← input-param keys & "_…" keys
                                                       are excluded
summary_stats:
  count
  primary_metric, direction, primary_metric_best, primary_metric_n  (when set)
  typed_split_coverage: {results.json, llm_evaluator, none}         ← adoption tracking
experiment_context:                                 ← LLM-extracted methodology /
                                                       hardware / findings
implementation_overview (optional):                 ← LLM-extracted architecture /
                                                       key_algorithms / optimizations
report_driven                                       ← true when node_report.json was
                                                       used as the LLM input substrate
```

**Source priority for the typed split** (D > C > legacy):

1. `experiments/{run_id}/{node_id}/results.json` — written by `coding-skill::emit_results` (D contract). Authoritative because the experiment script declared its own contract.
2. `node.metrics::_params_dict` and `_measurements_dict` — emitted by the LLM evaluator from artifact text when `MetricSpec.expected_params` is set (C contract).
3. Legacy: `parameters: {}` and the flat `metrics` dict carries everything as a single ambiguous bag.

**Robustness**: the LLM response parser strips `<think>…</think>` blocks and `` ```json `` fences, then walks balanced braces from each candidate `{` (handles `{...} prose {...}` shapes that the legacy greedy `\{.*\}` regex would have collapsed). On any parse failure the raw response is saved to `{checkpoint_dir}/science_data.debug.txt` for post-hoc audit.

Model: `llm_model` arg > `LLM_MODEL` env > `gpt-4o-mini`.

**Why it exists:** Ensures BFTS-internal terminology never leaks into generated papers or figures, and that input-size descriptors (`nnz`, `M`, `K`) cannot be confused with measured outputs (`GFlops_per_s`, accuracy) when computing best-of statistics.

#### `generate_ear(checkpoint_dir, llm_model="", llm_base_url="")`

Builds a structured **Experiment Artifact Repository (EAR)** under `<checkpoint>/ear/` for reproducibility. The layout is *node_report-driven* and shaped like a typical paper-companion code repo:

- `README.md` — deterministic, with optional `Architecture` section sourced from `science_data.json::implementation_overview.architecture`
- `reproduce.sh` — best node's literal `build_command` + `run_command` (from its `node_report.json`)
- `environment.json` — captured runtime environment (Python, platform, pip packages, hardware)
- `code/` — verbatim union of contributing chain nodes' `files_changed.added` ∪ `modified` (no per-node subdirs)
- `data/` — `checkpoint/uploads/` mirror (input data only; absent if uploads/ is empty). **Experiment outputs (CSV etc.) are NOT included** — `reproduce.sh` regenerates them
- `figures/` — top-level `*.{pdf,png,svg,jpg,jpeg}` from the checkpoint
- `LICENSE` — generated from `publish.yaml::license` (MIT / Apache-2.0 / BSD-3-Clause / GPL-3.0 / CC-BY-4.0)

Two ARI audit logs are kept at `<checkpoint>/` (outside `ear/`, so they are *not* bundled into the published artifact):

- `EVOLUTION.md` — per-step search trajectory with deltas and concerns; uses Step / Label only, never raw `node_id`
- `_provenance.json` — origin metadata (`from_node_id`, `introduced_by`, `excluded_nodes`); paths inside are checkpoint-relative (`ear/code/...`)

Other internal ARI metadata (`tree.json`, `science_data.json`, `raw_metrics.json`, `eval_scores.json`, `commands.md`) also stays at checkpoint root and never appears under `ear/`. `run_config.json` lives at `checkpoint/run_config.json`.

Returns: `{ear_dir, code_layout, verbatim_files, rendered_files, data_count, figure_count, top_node_id, best_chain_depth, excluded_count, has_readme, has_evolution, has_reproduce_sh, has_license, has_environment, ...}`.

#### `curate_ear(checkpoint_dir)` — v0.7.0

Curates `{checkpoint}/ear/` into `{checkpoint}/ear_published/` using
the author-supplied `ear/publish.yaml` allowlist + a built-in deny
list (`.env*`, `secrets/**`, `*.pem`, `*.key`, `id_rsa`,
`id_ed25519`). Writes `manifest.lock` with the canonical
`bundle_sha256` (sha256 of a sorted `{path, sha256, size}` JSON
payload) — this is the digest baked into the paper's
`\codedigest{...}` macro. **Deterministic, no LLM**. Skips silently
when `publish.yaml` is absent (back-compat for v0.6.0 checkpoints).

#### `publish_ear(checkpoint_dir, backend="ari-registry", visibility="staged", dry_run=False)` — v0.7.0

Thin MCP wrapper around `ari.publish.publish`. Builds a reproducible
tarball from `ear_published/` (sorted entries, normalised mtime/uid/gid),
hands it to the backend (`ari-registry` / `gh` / `zenodo` /
`local-tarball`), records `publish_record.json` at the checkpoint
root. Always starts at `visibility=staged` regardless of the argument
(FR-P5); `auto_promote=true` in `publish.yaml` plus a passing
reproducibility check is required to promote to `public`.

`ARI_PUBLISH_DRYRUN=1` forces dry-run mode for CI safety.

#### License templates — v0.7.0

When `publish.yaml::license` is set and `ear/LICENSE` does not already
exist, `generate_ear` emits one of: **MIT**, **Apache-2.0**,
**BSD-3-Clause**, **GPL-3.0**, **CC-BY-4.0** (templates under
`ari-skill-transform/src/licenses/`).

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

#### `emit_results(params, measurements, predictions={}, scores={}, file="results.json", work_dir="/tmp/ari_work")`

Write a typed `results.json` separating input parameters from measured outputs. Call this once at the **end** of an experiment run so downstream stages (`transform → science_data`, paper writing, summary stats) can tell apart "what we measured" from "what we ran on" — a best-of reduction never accidentally picks an input size (e.g. `nnz`, `M`, `K`, `threads`) over a real metric (e.g. `GFlops_per_s`).

```python
emit_results(
    params={"M": 120000, "K": 120000, "nnz": 3840000, "threads": 8},
    measurements={"GFlops_per_s": 26.864, "GB_per_s": 63.802},
    predictions={"peak_gflops_model": 686.45},
    scores={"parallel_efficiency": 0.81},
)
```

The file uses schema `1.0` and is overwritten on repeat calls; pass a different `file` name to keep multiple result variants. `params` and `measurements` must be disjoint — do NOT include input parameters in `measurements` and do NOT include measured outputs in `params`. Non-JSON-serializable values (e.g. `pathlib.Path`) are str-coerced rather than raising. `file` is normalised to `Path(file).name` so a malicious agent cannot escape `work_dir` via `../../...`.

The downstream `transform-skill::nodes_to_science_data` populates `configurations[*].parameters` from this file when present (D contract). When `emit_results` is not called, the LLM evaluator's typed split (C contract — see `ari-skill-evaluator::make_metric_spec` below) supplies the same information from artifact analysis.

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
