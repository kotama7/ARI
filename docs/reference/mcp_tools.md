---
sources:
  - path: ari-skill-benchmark
    role: implementation
  - path: ari-skill-coding
    role: implementation
  - path: ari-skill-evaluator
    role: implementation
  - path: ari-skill-hpc
    role: implementation
  - path: ari-skill-idea
    role: implementation
  - path: ari-skill-memory
    role: implementation
  - path: ari-skill-orchestrator
    role: implementation
  - path: ari-skill-paper
    role: implementation
  - path: ari-skill-paper-re
    role: implementation
  - path: ari-skill-plot
    role: implementation
  - path: ari-skill-replicate
    role: implementation
  - path: ari-skill-transform
    role: implementation
  - path: ari-skill-tool-registry
    role: implementation
  - path: ari-skill-vlm
    role: implementation
  - path: ari-skill-web
    role: implementation
last_verified: 2026-08-02
---

# MCP Tools Reference

ARI ships 15 MCP servers (one per `ari-skill-*` package).  This page
is a flat catalogue of every tool the agent can call.  The deep dive
for each skill lives in its own `README.md`; the section
[skills.md](skills.md) groups them by responsibility.

`skill.yaml` is the canonical source of truth for admitted tool names and
runtime policy. `mcp.json` is a generated compatibility projection. The
function decorated with `@mcp.tool()` (or the entry in
`@server.list_tools()` for older skills) defines the arguments and return
shape; repository conformance checks require that live and manifest names
match.

The "LLM" column marks tools that are **P2 exceptions** — they call
an LLM and therefore are not byte-deterministic.

## ari-skill-benchmark — statistics + plots (deterministic)

| Tool | Purpose | LLM |
|---|---|:---:|
| `analyze_results` | Summary stats from CSV / JSON / npy | ✗ |
| `plot` | Deterministic matplotlib figure from a fixed schema | ✗ |
| `statistical_test` | Hypothesis tests (t-test, Mann-Whitney, ...) | ✗ |

## ari-skill-coding — write + run code

| Tool | Purpose | LLM |
|---|---|:---:|
| `write_code` | Atomic, traversal/symlink-safe workspace write with source digest | ✗ |
| `run_code` | Digest-bound immutable script snapshot, bounded execution, complete log artifacts | ✗ |
| `run_bash` | Explicit shell execution with local/container identity and complete log artifacts | ✗ |
| `emit_results` | Emit canonical `ari.measurement-set/v1`: finite values, units, provenance, verified execution attempt/receipt, and re-hashed artifact digests; returns advisory claim-contract warnings | ✗ |
| `read_file` | Symlink-safe bounded/paginated workspace read | ✗ |

## ari-skill-evaluator — LLM metric extraction

| Tool | Purpose | LLM |
|---|---|:---:|
| `make_metric_spec` | LLM extracts metric definitions from `experiment.md`; also emits a run-level `metric_contract` → `{checkpoint}/metric_contract.json`. Mint-once: when a persisted claims-bearing contract already exists, the call returns it verbatim with `contract_frozen: true` instead of re-extracting (per-node spec fields like the scoring guide stay per-call) | ✓ |
| `claim_evidence_hard_gate` | Deterministic claim/evidence hard gate (execution data fidelity); strict mode blocks finalize on the final phase | ✗ |
| `evidence_grounded_semantic_review` | Non-blocking, evidence-grounded semantic review; emits `suggested_revisions` for `paper_refine` | ✓ |

## ari-skill-hpc — SLURM + Singularity

| Tool | Purpose | LLM |
|---|---|:---:|
| `slurm_submit` | sbatch with explicit partition / time / cpus / nodes / GPUs | ✗ |
| `job_status` | squeue + sacct lookup | ✗ |
| `job_cancel` | scancel a running job | ✗ |
| `probe_platform_capabilities` | Probe compute-partition architecture and command availability, with checkpoint caching | ✗ |
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

`generate_ideas` has two engines behind one stable output contract.
The default is the lightweight re-implemented discussion loop; the
opt-in real VirSci vendor-wrap engine (`ARI_IDEA_VIRSCI_REAL=1`) runs
VirSci's actual multi-agent mechanism on a live Semantic Scholar
snapshot, degrading to the re-impl loop on missing deps / any runtime
error. The `idea.json` contract is identical either way; the path taken
is reported in `virsci_integration_status` (`real_wrap` vs `reimpl: ...`).

## ari-skill-memory — ancestor-scoped node memory

This skill uses FastMCP `@mcp.tool()` decorators in `src/server.py`.

| Tool | Purpose | LLM |
|---|---|:---:|
| `add_memory` | Append an entry to the current node's memory | ✗ |
| `search_memory` | Embedding-ranked search across the current node + ancestors | ✗ (server-side embedding) |
| `get_node_memory` | All entries for the current node | ✗ |
| `clear_node_memory` | Drop the current node's entries (CoW; ancestors untouched) | ✗ |
| `get_experiment_context` | Stable, experiment-level facts from Letta core memory | ✗ |
| `add_experiment_result` | Record a typed experiment_result (CoW: self node only) | ✗ |
| `add_failure_case` | Record a typed failure_case (CoW: self node only) | ✗ |
| `add_procedure_memory` | Record a reusable procedure (CoW: self node only) | ✗ |
| `add_reflection` | Record a reflection (CoW: self node only; not usable for paper claims) | ✗ |
| `add_reproducibility_event` | Append an append-only reproducibility status event (CoW: self node only) | ✗ |
| `search_research_memory` | Ancestor-scoped typed search, filtered by kind / artifact presence | ✗ |
| `get_verified_context` | Artifact-grounded, reproducibility-aware context for paper / figure use | ✗ |
| `audit_memory` | Verify recorded provenance (sha256) against disk for a checkpoint | ✗ |
| `consolidate_node_memory` | Derive + write typed memory from a node_report at node end (CoW: self) | ✗ |

The skill explicitly declares "no LLM calls" in its design doc — see
`ari-skill-memory/README.md`.

## ari-skill-orchestrator — recursive ARI runner

| Tool | Purpose | LLM |
|---|---|:---:|
| `run_experiment` | Launch a child ARI run | ✗ |
| `get_status` | Status of a child run | ✗ |
| `list_runs` | All known runs | ✗ |
| `get_paper` | Generated LaTeX / PDF for a run | ✗ |
| `list_children` | Child runs for a parent run | ✗ |
| `list_files` | Files available in a run checkpoint | ✗ |
| `read_file` | Read a text file in a run checkpoint | ✗ |
| `get_ear` | Retrieve the run's Experiment Analysis Report | ✗ |
| `stop_experiment` | Stop a running experiment | ✗ |
| `list_skills` | Sanitized view of available skills and tools | ✗ |
| `get_workflow` | Current workflow configuration | ✗ |

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
| `link_paper_claims` | Reconcile `% CLAIM:Cx:NCx` anchors against science_data claims, build `paper_claim_links` (deterministic) | ✗ |
| `paper_refine` | Apply suggested revisions while preserving `% CLAIM:Cx:NCx` anchors (deterministic subs + bounded LLM find/replace) | ✓ |
| `list_rubrics` | Available reviewer rubrics |  ✗ |
| `inject_code_availability` | v0.7.0 — append a `\codedigest{...}` block to the paper | ✗ |
| `merge_reviews` | v0.7.0 — combine rubric review + VLM review JSON | ✗ |

## ari-skill-paper-re — PaperBench reproducibility (v0.7.0)

| Tool | Purpose | LLM |
|---|---|:---:|
| `fetch_code_bundle` | Fetch + verify a code bundle by ref + sha256 | ✗ |
| `build_reproduce_sh` | Stage 1 — vendor BasicAgent / IterativeAgent rollout writes `reproduce.sh` | ✓ |
| `run_reproduce` | Stage 2 — execute `reproduce.sh` in a `local` / `docker` / `apptainer` / `singularity` / `slurm` sandbox | ✗ |
| `grade_with_simplejudge` | Stage 3 — LLM grades the executed submission against the rubric leaves | ✓ |

### v0.8.0 new fields (Stage 1)

| Tool | New args |
|---|---|
| `build_reproduce_sh` | `container_image` (replaces / supersedes legacy `apptainer_image`; both accepted for back-compat) |

### v0.8.0 new fields (Stage 2)

| Tool | New args |
|---|---|
| `run_reproduce` | `container_image` (honoured by docker / apptainer / singularity sandboxes; alias `pb-env` / `pb-reproducer` resolves to vendor `image:latest` tags built by `scripts/build_pb_images.sh`) |

Fail-loud preconditions: missing docker daemon / apptainer binary /
sbatch / partition raise `RuntimeError` rather than silently falling
back to local CPU. Opt back into legacy fallback via
`ARI_PHASE1_ALLOW_FALLBACK=1`. Typed GPU requests are never silently dropped;
unsupported or contradictory resource requests fail before execution. See
[environment_variables.md](environment_variables.md#paperbench-reproduction-phase-stage-2).
The SLURM path uses the shared `JobRequestV1` submit/status/log/cancel lifecycle
and a clean `--export=NIL` job environment.

### v0.8.0 new fields (Stage 3)

| Tool | New args |
|---|---|
| `grade_with_simplejudge` | `code_only` (prune rubric to Code Development leaves only, mirrors vendor `paperbench/grade.py:109-112`; auto-enables when no `reproduce.log` is present so Stage 1-only runs aren't systematically zeroed) |

For an in-process Python surface that chains all three stages with a
single calling vocabulary, see
[`api_paperbench.md` § Bridge contract](api_paperbench.md#bridge-contract-in-process-python-surface).

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
| `suggest_target_leaf_count` | Compute a target rubric leaf count from paper length | ✗ |

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

| Tool | Purpose | LLM |
|---|---|:---:|
| `nodes_to_science_data` | Walk the BFTS tree, extract methodology + findings | ✓ |
| `generate_ear` | Build `{checkpoint}/ear/` from BFTS artefacts | ✗ |
| `curate_ear` | Promote `ear/` → `ear_published/` + manifest.lock | ✗ |
| `publish_ear` | Push to `local-tarball` / `ari-registry` / `zenodo` / `gh` | ✗ |
| `promote_ear` | `staged` → `unlisted` / `public` | ✗ |

## ari-skill-tool-registry — federated scientific tools (default-off)

The server exposes only broker operations; imported leaf schemas remain in the
reviewed catalog and are disclosed progressively.

| Tool | Purpose | LLM |
|---|---|:---:|
| `discover` | Search the immutable catalog with bounded pagination | ✗ |
| `describe` | Read paginated schema, provenance, admission, and limitations | ✗ |
| `invoke` | Invoke one exact admitted `tool_ref` in live/record/replay mode | ✗ |
| `get_status` | Poll a descriptor-bound asynchronous provider handle | ✗ |
| `get_result` | Fetch and normalize the final asynchronous result | ✗ |

See [tool_registry.md](tool_registry.md) for source sync, admission, overlap,
record/replay, and adapter requirements.

## ari-skill-vlm — figure / table review (VLM)

| Tool | Purpose | LLM |
|---|---|:---:|
| `review_figure` | VLM reads an image + caption, returns critique | ✓ (vision) |
| `review_table` | VLM reviews a table | ✓ (vision) |
| `review_figures_all` | Batch review of every figure in a figure manifest | ✓ (vision) |

## ari-skill-web — search + fetch

| Tool | Purpose | LLM |
|---|---|:---:|
| `search_papers` | One pinned provider; typed record/live/replay result | ✗ |
| `web_search` | DuckDuckGo under the retrieval snapshot contract | ✗ |
| `fetch_url` | SSRF-controlled URL → untrusted readable text | ✗ |
| `walk_citations` | Bounded citation graph with partial-result provenance | ✗ |
| `rerank_retrieval_records` | Explicit typed-record reranker | ✓ |
| `search_arxiv` | Deprecated narrow arXiv alias | ✗ |
| `search_semantic_scholar` | Deprecated narrow Semantic Scholar alias | ✗ |
| `collect_references_iterative` | Deprecated stochastic query/selection loop | ✓ |
| `set_retrieval_backend` | Deprecated pinned-provider default selector | ✗ |
| `list_uploaded_files` | List files in the checkpoint upload area | ✗ |
| `read_uploaded_file` | Read one upload with traversal protection and output bounds | ✗ |

See [Retrieval contract and network policy](retrieval_contract.md).

## See also

- `docs/reference/skills.md` — narrative description of each skill (responsibility, env vars, examples).
- `docs/reference/environment_variables.md` — env-var-by-env-var reference.
- The `skill.yaml` in each skill for the canonical admitted tool name list and policy.
- The generated `mcp.json` in each skill for legacy discovery compatibility.
- `@mcp.tool()` / `@server.list_tools()` in each skill's `src/server.py`
  for the canonical argument signatures.
