# MCP Tools Reference

ARI ships 14 MCP servers (one per `ari-skill-*` package).  This page
is a flat catalogue of every tool the agent can call.  The deep dive
for each skill lives in its own `README.md`; the section
[skills.md](../skills.md) groups them by responsibility.

`mcp.json` (next to each skill's `pyproject.toml`) is the source of
truth for tool *names*; the function decorated with `@mcp.tool()` (or
the entry in `@server.list_tools()` for the older skills) defines the
arguments and return shape.

The "LLM" column marks tools that are **P2 exceptions** — they call
an LLM and therefore are not byte-deterministic.

## ari-skill-benchmark — statistics + plots (deterministic)

| Tool | Purpose | LLM |
|---|---|:---:|
| `analyze_results` | Summary stats from CSV / JSON / npy | ✗ |
| `plot` | Deterministic matplotlib figure from a fixed schema | ✗ |
| `statistical_test` | Hypothesis tests (t-test, Mann-Whitney, ...) | ✗ |

## ari-skill-coding — write + run code

`mcp.json` lists no tools; the actual tool list comes from
`@server.list_tools()` in `src/server.py`.

| Tool | Purpose | LLM |
|---|---|:---:|
| `write_code` | Write a file into the node work_dir | ✗ |
| `run_code` | Execute a script with timeout + capture | ✗ |
| `run_bash` | Ad-hoc bash command | ✗ |
| `emit_results` | Emit `metrics` + `has_real_data` for the evaluator | ✗ |
| `read_file` | Read a file the agent wrote earlier | ✗ |

## ari-skill-evaluator — LLM metric extraction

| Tool | Purpose | LLM |
|---|---|:---:|
| `make_metric_spec` | LLM extracts metric definitions from `experiment.md` | ✓ |
| (internal) `evaluate` | Score node artefacts against the spec | ✓ |

## ari-skill-hpc — SLURM + Singularity

`mcp.json` has an empty list; tools come from `@server.list_tools()`
in `src/server.py`.

| Tool | Purpose | LLM |
|---|---|:---:|
| `slurm_submit` | sbatch with explicit partition / time / cpus / nodes / GPUs | ✗ |
| `job_status` | squeue + sacct lookup | ✗ |
| `job_cancel` | scancel a running job | ✗ |
| `run_bash` | Direct bash command (local or via SSH) | ✗ |
| `singularity_build` | Build a SIF from a definition file | ✗ |
| `singularity_run` | Run a command inside a SIF | ✗ |
| `singularity_pull` | Pull a SIF from a remote URI | ✗ |
| `singularity_build_fakeroot` | Fakeroot build (no privileged daemon) | ✗ |
| `singularity_run_gpu` | GPU variant of `singularity_run` | ✗ |

## ari-skill-idea — literature survey + idea generation

| Tool | Purpose | LLM |
|---|---|:---:|
| `survey` | arXiv + Semantic Scholar search; pure HTTP | ✗ |
| `generate_ideas` | LLM generates ranked idea candidates from survey + context | ✓ |

## ari-skill-memory — ancestor-scoped node memory

| Tool | Purpose | LLM |
|---|---|:---:|
| `add_memory` | Append an entry to the current node's memory | ✗ |
| `search_memory` | Embedding-ranked search across the current node + ancestors | ✗ (server-side embedding) |
| `get_node_memory` | All entries for the current node | ✗ |
| `clear_node_memory` | Drop the current node's entries (CoW; ancestors untouched) | ✗ |

The skill explicitly declares "no LLM calls" in its design doc — see
`ari-skill-memory/README.md`.

## ari-skill-orchestrator — recursive ARI runner

| Tool | Purpose | LLM |
|---|---|:---:|
| `run_experiment` | Launch a child ARI run | ✗ |
| `get_status` | Status of a child run | ✗ |
| `list_runs` | All known runs | ✗ |
| `get_paper` | Generated LaTeX / PDF for a run | ✗ |

## ari-skill-paper — LaTeX paper writing

| Tool | Purpose | LLM |
|---|---|:---:|
| `list_venues` | Available LaTeX templates (ACM / NeurIPS / SC / ICPP / arXiv) | ✗ |
| `get_template` | Fetch a venue's template | ✗ |
| `generate_section` | LLM writes a section (intro, methods, ...) | ✓ |
| `compile_paper` | pdflatex compile | ✗ |
| `check_format` | LaTeX format validation | ✗ |
| `review_section` | LLM rubric review of one section | ✓ |
| `revise_section` | LLM rewrite using review feedback | ✓ |
| `write_paper_iterative` | Drive the generate / review / revise loop end-to-end | ✓ |
| `review_compiled_paper` | Final-pass review on compiled PDF (delegates to VLM for figures) | ✓ |
| `list_rubrics` | Available reviewer rubrics |  ✗ |
| `inject_code_availability` | v0.7.0 — append a `\codedigest{...}` block to the paper | ✗ |
| `merge_reviews` | v0.7.0 — combine rubric review + VLM review JSON | ✗ |

## ari-skill-paper-re — PaperBench reproducibility (v0.7.0)

| Tool | Purpose | LLM |
|---|---|:---:|
| `fetch_code_bundle` | Fetch + verify a code bundle by ref + sha256 | ✗ |
| `build_reproduce_sh` | LLM writes `reproduce.sh` from paper text + rubric | ✓ |
| `run_reproduce` | Run `reproduce.sh` in a SLURM / Docker / Apptainer sandbox | ✗ |
| `grade_with_simplejudge` | LLM grades reproduce outputs against the rubric leaves | ✓ |

## ari-skill-plot — figure generation

| Tool | Purpose | LLM |
|---|---|:---:|
| `generate_figures` | Deterministic matplotlib figures from `nodes_tree.json` | ✗ |
| `generate_figures_llm` | LLM writes matplotlib code, then runs it | ✓ |

## ari-skill-replicate — rubric auto-generation (v0.7.0)

| Tool | Purpose | LLM |
|---|---|:---:|
| `generate_rubric` | Two-stage (skeleton + subtree) PaperBench rubric synthesis | ✓ |
| `audit_rubric` | LLM audits leaves for vague / unverifiable / duplicate criteria | ✓ |

### `generate_rubric` — venue-conditioned templates (unreleased)

`generate_rubric` accepts an optional `paperbench_rubric_id` argument
that selects a venue-conditioned template from
`ari-core/config/paperbench_rubrics/<id>.yaml`. Mirrors the
`reviewer_rubrics/` venue pattern already used by `ari-skill-paper`'s
peer-review path.

| Argument | Type | Default | Effect |
|---|---|---|---|
| `paperbench_rubric_id` | `str` | `""` | Empty = bundled prompt verbatim (back-compat). Otherwise loads the YAML template and injects `prompt_overrides.system_hint` / `prompt_overrides.leaf_style` into the skeleton + subtree prompts. |

Shipped templates:

| `id` | `mode` | Top-level structure |
|---|---|---|
| `generic` | `agent_benchmark` | Decompose by scientific contribution (current default behaviour). |
| `sc` | `paper_audit` | Six fixed audit axes for HPC papers (env / data / execution / figures / scaling / conclusion). |
| `neurips` | `paper_audit` | Six axes per NeurIPS Reproducibility Checklist (claims / setup / code+data / statistics / ethics / figures). |
| `nature` | `paper_audit` | Five axes for wet-lab papers (materials / protocol / statistics / data / ethics). |

`paper_audit` mode requires `two_stage=True`; the generator returns an
error if the single-pass path is requested with a `paper_audit`
template (the single-pass prompt cannot honour the fixed-axis
constraint). See [`rubric_schema.md`](rubric_schema.md#venue-conditioned-templates)
for the YAML schema and authoring guide.

## ari-skill-transform — tree walk + EAR pipeline

`mcp.json` has no tools listed (the file is internal-only); the
`@mcp.tool()` decorators in `src/server.py` are authoritative.

| Tool | Purpose | LLM |
|---|---|:---:|
| `nodes_to_science_data` | Walk the BFTS tree, extract methodology + findings | ✓ |
| `generate_ear` | Build `{checkpoint}/ear/` from BFTS artefacts | ✗ |
| `curate_ear` | Promote `ear/` → `ear_published/` + manifest.lock | ✗ |
| `publish_ear` | Push to `local-tarball` / `ari-registry` / `zenodo` / `gh` | ✗ |
| `promote_ear` | `staged` → `unlisted` / `public` | ✗ |

## ari-skill-vlm — figure / table review (VLM)

`mcp.json` has no tools listed; the skill exposes internal review
helpers only.

| Tool | Purpose | LLM |
|---|---|:---:|
| `review_figure` | VLM reads an image + caption, returns critique | ✓ (vision) |
| `review_table` | VLM reviews a table | ✓ (vision) |
| `review_paper_figures` | Batch review of every figure in a paper dir | ✓ (vision) |

## ari-skill-web — search + fetch

| Tool | Purpose | LLM |
|---|---|:---:|
| `web_search` | DuckDuckGo (no API key) | ✗ |
| `fetch_url` | URL → readable text | ✗ |
| `search_arxiv` | arXiv API | ✗ |
| `search_semantic_scholar` | Semantic Scholar API | ✗ |
| `collect_references_iterative` | Walk the citation graph from a seed paper | ✗ |

## See also

- `docs/skills.md` — narrative description of each skill (responsibility, env vars, examples).
- `docs/reference/environment_variables.md` — env-var-by-env-var reference.
- The `mcp.json` in each skill for the canonical tool name list.
- `@mcp.tool()` / `@server.list_tools()` in each skill's `src/server.py`
  for the canonical argument signatures.
