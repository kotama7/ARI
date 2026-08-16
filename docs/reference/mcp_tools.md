---
sources:
  - path: ari-skill-benchmark/src/server.py
    role: implementation
  - path: ari-skill-benchmark/mcp.json
    role: config
  - path: ari-skill-coding/src/server.py
    role: implementation
  - path: ari-skill-coding/mcp.json
    role: config
  - path: ari-skill-evaluator/src/server.py
    role: implementation
  - path: ari-skill-evaluator/mcp.json
    role: config
  - path: ari-skill-harness/src/server.py
    role: implementation
  - path: ari-skill-harness/mcp.json
    role: config
  - path: ari-skill-hpc/ari_skill_hpc/server.py
    role: implementation
  - path: ari-skill-hpc/mcp.json
    role: config
  - path: ari-skill-idea/src/server.py
    role: implementation
  - path: ari-skill-idea/mcp.json
    role: config
  - path: ari-skill-knowledge/src/server.py
    role: implementation
  - path: ari-skill-knowledge/mcp.json
    role: config
  - path: ari-skill-memory/src/server.py
    role: implementation
  - path: ari-skill-memory/mcp.json
    role: config
  - path: ari-skill-orchestrator/src/server.py
    role: implementation
  - path: ari-skill-orchestrator/mcp.json
    role: config
  - path: ari-skill-paper-re/src/server.py
    role: implementation
  - path: ari-skill-paper-re/mcp.json
    role: config
  - path: ari-skill-paper/src/server.py
    role: implementation
  - path: ari-skill-paper/mcp.json
    role: config
  - path: ari-skill-plot/src/server.py
    role: implementation
  - path: ari-skill-plot/mcp.json
    role: config
  - path: ari-skill-replicate/src/server.py
    role: implementation
  - path: ari-skill-replicate/mcp.json
    role: config
  - path: ari-skill-tool-registry/src/server.py
    role: implementation
  - path: ari-skill-tool-registry/mcp.json
    role: config
  - path: ari-skill-transform/src/server.py
    role: implementation
  - path: ari-skill-transform/mcp.json
    role: config
  - path: ari-skill-vlm/src/server.py
    role: implementation
  - path: ari-skill-vlm/mcp.json
    role: config
  - path: ari-skill-web/src/server.py
    role: implementation
  - path: ari-skill-web/mcp.json
    role: config
  - path: ari-core/tests/fixtures/contracts/mcp_tools.json
    role: test
last_verified: 2026-08-16
---

# MCP Tools Reference

ARI's `ari-skill-*` packages are executable **Capability Providers**, not
Knowledge Skills. MCP is their transport/discovery protocol. This page is a
flat catalogue of Provider operations; [skills.md](skills.md) groups the
legacy-named packages by responsibility. Non-executable procedural knowledge,
capability binding, and independent verification are separate contracts in
[Knowledge, Capability, and Scientific Assurance](knowledge_capability_assurance.md).

For v1 Provider packages, `skill.yaml` plus live `tools/list` is the locked
source for tool identity/schema. Legacy `mcp.json` files remain package-local
compatibility metadata. The function decorated with `@mcp.tool()` (or the
entry in `@server.list_tools()`) defines the live arguments and result shape.

The "LLM" column marks tools that are **P2 exceptions** — they call
an LLM and therefore are not byte-deterministic.

## ari-skill-benchmark — typed analysis (deterministic)

All three tools take exactly one `request` object and return an
`AnalysisResultV1`. Figures are not this skill's job — `ari-skill-plot`
renders them.

| Tool | Purpose | LLM |
|---|---|:---:|
| `analyze_results` | Summary stats over unit-bearing `MetricSampleSetV1` datasets — observations inline, or a digest-bound CSV / JSON / npy column in a closed workspace | ✗ |
| `statistical_test` | A pre-declared family of comparisons (`auto`, `welch_t`, `student_t`, `paired_t`, `mann_whitney`, `wilcoxon`) with effect sizes; more than one comparison is refused unless `correction` is set to something other than `none` | ✗ |
| `compare_runs` | Rank scalar `RunRecordV1` runs against a baseline and report environment compatibility, provenance differences, and whether replicate independence is `declared` or `not-established` | ✗ |

## ari-skill-coding — write + run code

`mcp.json` carries the tool NAMES, generated from `skill.yaml` by
`scripts/sync_skill_metadata.py --write`; the full schemas still come from
`@server.list_tools()` in `src/server.py`. The three must agree —
`scripts/check_skill_manifests.py` fails on drift between them.

| Tool | Purpose | LLM |
|---|---|:---:|
| `write_code` | Write a file into the node work_dir | ✗ |
| `edit_code` | Replace an exact snippet in an existing file, leaving the rest untouched. Preferred over `write_code` when the file already exists: `old_string` must match exactly once unless `replace_all` is set, so an ambiguous edit fails instead of silently changing the wrong place | ✗ |
| `run_code` | Execute a script with timeout + capture | ✗ |
| `run_bash` | Ad-hoc bash command | ✗ |
| `describe_environment` | Report this cluster's environment catalog (arch, CPU, GPUs, compilers on PATH, `module avail`, and the NAMES of set toolchain env vars). On a login node it also covers each configured compute partition; on a compute node, only that node | ✗ |
| `emit_results` | Write a typed `results.json` (`MeasurementSetV1`) that separates `params` from `measurements` (optional `provenance` arg → recorded on each measurement record, and surfaced to the claim-evidence gate as the `_provenance` map). The response's `contract_warnings` may include suggestion-only "POSSIBLE name matches" hints when an emitted key lexically resembles a required evidence name — advisory only: nothing is auto-bound and the gate never consumes them | ✗ |
| `read_file` | Read a file the agent wrote earlier | ✗ |

## ari-skill-evaluator — metric contracts + claim gates

| Tool | Purpose | LLM |
|---|---|:---:|
| `make_metric_spec` | Materialize the run-level metric contract from an immutable idea-owned `ResearchContractV1`, or from a proposal a named `reviewer` has admitted, and persist the projection to `{checkpoint}/metric_contract.json`. Mint-once: a persisted projection whose `projection_digest` differs from the new one is a refusal, not an overwrite. With no admitted contract the call still returns the `experiment.md` parser output, but as evidence only — `contract_frozen: false`, `admission_status: "human-review-required"` | ✗ |
| `propose_metric_contract` | The explicitly requested LLM proposal step: reads the idea (`idea_json`, or `{checkpoint}/idea.json`) and emits a `MetricContractProposalV1` with `requires_human_review: true` to `metric_contract_proposal.json`. It never admits its own output, and it refuses an idea that already carries a typed `ari.research-contract/v1` contract | ✓ |
| `claim_evidence_hard_gate` | Deterministic claim/evidence hard gate (execution data fidelity); strict mode blocks finalize on the final phase | ✗ |
| `evidence_grounded_semantic_review` | Non-blocking, evidence-grounded semantic review; emits `suggested_revisions` for `paper_refine` | ✓ |

## ari-skill-hpc — SLURM + Singularity

`mcp.json` carries the tool NAMES, generated from `skill.yaml`; the full
schemas come from `@server.list_tools()` in `ari_skill_hpc/server.py`.

| Tool | Purpose | LLM |
|---|---|:---:|
| `job_submit` | Submit an immutable `JobRequestV1` and return an idempotent `JobHandleV1`; commands are argv arrays and the login-node shell is never used | ✗ |
| `container_submit` | The same lifecycle, requiring a digest-pinned Apptainer/Singularity container declaration on the request | ✗ |
| `job_status` | Provider-neutral `JobStatusV1` for an ARI handle or a raw SLURM ID (squeue + sacct lookup) | ✗ |
| `job_result` | Collect a terminal `JobResultV1`, rehashing declared inputs, outputs, and logs | ✗ |
| `job_logs` | Bounded, digest-bound stdout / stderr for an ARI job handle | ✗ |
| `job_cancel` | Request cancellation of an ARI or SLURM job | ✗ |
| `slurm_submit` | Compatibility bridge for the core agent's batch-script workflow: sbatch with explicit partition / time / nodes / tasks / cpus / modules and an explicit `launcher`. New programmatic callers use `job_submit` | ✗ |
| `probe_platform_capabilities` | Probe tool availability (`command -v`) **on the compute partition** and cache it to `{checkpoint}/platform_capabilities.json`; best-effort (any probe failure is reported as skipped and writes nothing) | ✗ |
| `counter_support` | Report whether this node grants hardware counters, established by opening one rather than by looking for a profiler binary | ✗ |
| `measure_counters` | Count reviewed hardware events on an existing process over a bounded window; creates no process and writes nothing | ✗ |

`launcher` says how the script is started inside its allocation, and it is
declared rather than inferred from `tasks > 1`: `auto` (the default) binds a
single-task, single-node payload with `srun --ntasks=1` and starts any larger
shape directly, leaving the parallel launch to the script; `srun` starts the
script itself with the declared `nodes` / `tasks` / `cpus_per_task`, which is
what an MPI or SPMD binary needs; `none` never wraps. The launch mode is part
of the request digest. See [skills.md](skills.md#ari-skill-hpc) for the full
argument list.

`measure_counters` declares `context_requirement: node`, so its input schema
declares an `ari_context` object property. The transport injects the authorized
call context under that name for any tool with a context requirement; a schema
with `additionalProperties: false` that omits it refuses every authorized call.
The proxy strips the property back out of `tools/list`, so it is never an
argument the agent supplies.

## ari-skill-idea — literature survey + idea generation

| Tool | Purpose | LLM |
|---|---|:---:|
| `survey` | Prior-work survey against **one pinned** provider — `semantic-scholar` (the default) or `virsci-snapshot`; `record` / `live` never switch backends, `replay` performs no network access, and an unsupported provider is refused rather than substituted | ✗ |
| `generate_ideas` | LLM generates ranked idea candidates from survey + context | ✓ |
| `mint_contract_for_proposal` | Mint a typed `ari.research-contract/v1` contract for a proposal this skill did **not** generate — the path by which an RQGM proposal-router candidate reaches KCA admission. Refuses rather than inventing: no `ARI_CHECKPOINT_DIR`, an unavailable survey snapshot, or a proposal with no title each return `contract_status: "rejected"` | ✓ |

`_load_virsci_snapshot_papers` is a plain helper `survey` calls directly, never
agent-visible; `ari-skill-idea/tests/test_server.py` pins via `mcp.list_tools()`
that `survey` and `generate_ideas` are registered and that the helper is not.
`mint_contract_for_proposal` is declared in both `skill.yaml` and `mcp.json`
alongside the other two, so `scripts/check_skill_manifests.py` reports no
`tool-drift` for this package.
There is no cross-provider fallback: a `virsci-snapshot` survey whose corpus is
absent raises `FileNotFoundError`, and a Semantic Scholar survey raises on the
HTTP error, so an outage produces a refusal rather than a silently different
corpus. `survey` and `generate_ideas` are also
the MCP surface behind the RQGM `VirSciAdapter`: in the opt-in `ari_rqgm`
mode with `proposal_router.generators.virsci.enabled: true`, the core-side
ProposalRouter routes ideation events to `survey` + `generate_ideas` under a
per-epoch call budget — see
[VirSci Integration](../guides/virsci_integration.md).

`generate_ideas` has two engines behind one stable output contract.
The default is the lightweight re-implemented discussion loop; the
opt-in real VirSci vendor-wrap engine (`ARI_IDEA_VIRSCI_REAL=1`) runs
VirSci's actual multi-agent mechanism on a live Semantic Scholar
snapshot, degrading to the re-impl loop on missing deps / any runtime
error. The `idea.json` contract is identical either way; the path taken
is reported in `virsci_integration_status` (`real_wrap` vs `reimpl: ...`).

## ari-skill-memory — ancestor-scoped node memory

This skill uses FastMCP `@mcp.tool()` decorators in `src/server.py`; its
`mcp.json` lists the same thirteen names, and every decorated function below
**is** exposed at runtime.

| Tool | Purpose | LLM |
|---|---|:---:|
| `add_memory` | Append an entry to the current node's memory | ✗ |
| `search_memory` | Embedding-ranked search across the current node + ancestors | ✗ (server-side embedding) |
| `get_node_memory` | All entries for the current node | ✗ |
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

No tool here calls an LLM. `ari-skill-memory/README.md` § Determinism (P2)
records that v0.5.x's "no LLM calls, fully deterministic" claim was relaxed in
v0.6.0 anyway: Letta embedding search is not bit-reproducible across versions,
so stored `text` bytes are CoW-protected instead.

There is no destructive clear. Entries are never dropped by an agent-visible
operation, and `ari-skill-memory/tests/test_cow.py` pins the absence
(`assert not hasattr(server, "clear_node_memory")`). To reduce a node's memory,
write a consolidated typed entry with `consolidate_node_memory`, which derives
from the node's `node_report` and is itself CoW-guarded to the current node.

## ari-skill-orchestrator — recursive ARI runner

Every tool is authorized against the calling principal; the read tools return
digest-addressed references rather than filesystem paths.

| Tool | Purpose | LLM |
|---|---|:---:|
| `run_experiment` | Idempotently submit a child ARI run under an explicit `idempotency_key` and quota block (`max_nodes`, `max_total_nodes`, `max_descendant_runs`, `max_cost_usd`, `timeout_minutes`), returning its durable handle | ✗ |
| `get_status` | Durable state and bounded scientific progress for a run | ✗ |
| `get_result` | Terminal metadata plus digest-addressed artifacts for a run | ✗ |
| `stop_experiment` | Cancel a run, propagate termination to descendants, and settle one terminal state | ✗ |
| `list_runs` | Runs owned by the authenticated principal (admins may list all) | ✗ |
| `list_children` | Authorized direct descendants of one exact parent run ID | ✗ |
| `list_artifacts` | Allowlisted, digest-verified artifacts for a run — no paths are exposed | ✗ |
| `read_artifact` | Read one bounded admitted artifact by its exact SHA-256 identity | ✗ |
| `get_paper` | Paper artifact references for an authorized run | ✗ |
| `get_ear` | Verified EAR and evidence artifact references for an authorized run | ✗ |
| `list_skills` | The sanitized, immutable `SKILLS.lock` view for one run | ✗ |
| `get_workflow` | Locked phase / tool membership, without raw workflow or secret config | ✗ |

## ari-skill-paper — LaTeX paper writing

| Tool | Purpose | LLM |
|---|---|:---:|
| `list_venues` | Available LaTeX templates (ACM / NeurIPS / SC / ICPP / ISC / arXiv) | ✗ |
| `get_template` | Fetch a venue's template | ✗ |
| `compile_paper` | pdflatex compile | ✗ |
| `check_format` | LaTeX format validation | ✗ |
| `write_paper_iterative` | Fill the whole venue template in one call, then run `max_revision_rounds` reflection rounds over the same message history. There is no per-section tool: drafting and revision are stages inside this one, and it returns `latex` / `sections` / `reviews` / `revision_counts` / `paper_build` | ✓ |
| `review_compiled_paper` | Final-pass review on compiled PDF (delegates to VLM for figures) | ✓ |
| `finalize_paper_build` | Lock the exact evidence set — tex, bib, PDF, compile record, figures manifest, claim links, hard gate, text / visual / semantic reviews — into a `PaperBuildV1` at `output_path`. Raises when the build is not `finalized`, listing `blocking_reasons` | ✗ |
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
| `build_reproduce_sh` | `container_image` (replaces the legacy `apptainer_image`, which has been deleted from the signature — `container_image` is now the only image argument, and it is honoured only by the `apptainer` rollout) |

### v0.8.0 new fields (Stage 2)

| Tool | New args |
|---|---|
| `run_reproduce` | `container_image` (required by the docker / apptainer / singularity sandboxes, refused by the others). v1.0 admits only an immutable reference: a local non-symlink SIF, a full `sha256:<image-id>`, or a `name@sha256:<digest>` URI — the mutable `pb-env` / `pb-reproducer` `:latest` aliases were removed |

Fail-loud preconditions: `sandbox_kind=slurm` without `sbatch` on PATH,
or with no partition resolvable from the argument, `ARI_SLURM_PARTITION`
or `launch_config.json`, raises `RuntimeError` rather than silently
falling back to local execution; a container sandbox whose runtime
binary is absent, or whose `container_image` is empty or mutable, raises
`ReproductionContractError`. v1.0 removed the host-local fallback, so
there is no opt-back-in switch. See
[environment_variables.md](environment_variables.md#paperbench-reproduction-phase-stage-2).
A GPU request cannot mix its two shapes either: per-node and per-task GPU
counts are mutually exclusive. A `gpu_type` carrying no count is *not* refused
on this surface, though — the SLURM execution path fills in one GPU per node
before it builds the resource request, so the underlying "gpu_type requires an
explicit GPU count" rule never fires through `run_reproduce`.

### v0.8.0 new fields (Stage 3)

| Tool | New args |
|---|---|
| `grade_with_simplejudge` | `code_only` (prune rubric to Code Development leaves only, mirrors vendor `paperbench/grade.py:109-112`). It defaults to `False` and is never turned on for you — v1.0 removed the implicit `code_only` grading that used to switch itself on when no `reproduce.log` was present |

For an in-process Python surface that chains all three stages with a
single calling vocabulary, see
[`api_paperbench.md` § Bridge contract](api_paperbench.md#bridge-contract-in-process-python-surface).

## ari-skill-plot — figure generation

| Tool | Purpose | LLM |
|---|---|:---:|
| `render_figure` | Render one canonical `FigureSpecV1` into a closed workspace and return its manifest. The request object is exactly `spec` + `workspace` + `relative_directory`; no caller code is executed | ✗ |
| `generate_figures` | Derive deterministic default specs from a native `ScienceDataV1` and render them. `revision` must be `0` — the deterministic path has no feedback round | ✗ |
| `generate_figures_llm` | The LLM chooses only `metric_id`, `chart_type` and `x_mode`; numeric values, units, captions, paths and artifact bytes all come from the verified science record through the same fixed renderer. `revision > 0` requires both a `vlm_feedback` document and the `previous_batch_path` it binds | ✓ |

## ari-skill-replicate — rubric auto-generation (v0.7.0)

| Tool | Purpose | LLM |
|---|---|:---:|
| `generate_rubric` | Two-stage (skeleton + subtree) PaperBench rubric synthesis | ✓ |
| `audit_rubric` | LLM audits leaves for vague / unverifiable / duplicate criteria | ✓ |
| `suggest_target_leaf_count` | Return `{target, word_count}` — the leaf count `generate_rubric` would auto-compute for a paper, so a caller can pre-fill it instead of guessing | ✗ |

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

A `paper_audit` template must declare a non-empty `top_level_axes`;
loading one that does not is refused. There is no single-pass path to
opt out of — generation is always the two-stage skeleton + subtree walk,
and `system_hint` frames the skeleton pass while `leaf_style` frames the
subtree pass. See [`rubric_schema.md`](rubric_schema.md#venue-conditioned-templates)
for the YAML schema and authoring guide.

## ari-skill-transform — tree walk + EAR pipeline

`mcp.json` lists the same five names, generated from `skill.yaml`; the
`@mcp.tool()` decorators in `src/server.py` carry the argument shapes.

| Tool | Purpose | LLM |
|---|---|:---:|
| `nodes_to_science_data` | Walk the BFTS tree, extract methodology + findings | ✓ |
| `generate_ear` | Build `{checkpoint}/ear/` from BFTS artefacts | ✗ |
| `curate_ear` | Promote `ear/` → `ear_published/` + manifest.lock | ✗ |
| `publish_ear` | Push to `local-tarball` / `ari-registry` / `zenodo` / `gh` | ✗ |
| `promote_ear` | `staged` → `unlisted` / `public` | ✗ |

## ari-skill-vlm — figure / table review (VLM)

Reviews are artifact-bound: the target is selected out of a verified
`FigureBatchV1` or named by content-addressed artifact reference, never by a
loose path, and the criteria profile is versioned (`figure-publication/v1` by
default).

| Tool | Purpose | LLM |
|---|---|:---:|
| `review_figure` | Review one figure picked out of a `FigureBatchV1` by `figure_id`; an ID the batch does not carry is refused | ✓ (vision) |
| `review_figures_all` | Review every figure in one batch under a `ReviewBudgetV1` (`max_figures`, `max_concurrency`, `max_output_tokens`); a figure that fails individually is recorded as a failed review rather than sinking the batch | ✓ (vision) |
| `review_table` | Review one content-addressed table artifact under a closed workspace. The request schema is exact — `workspace`, `target_id`, `artifact`, `context`, `criteria_profile_id`, `iteration` (0–2), `max_output_tokens` — and an unsupported media type comes back as an `artifact-error` review | ✓ (vision) |

## ari-skill-web — search + fetch

Retrieval is one contract, not one tool per provider. Every network tool takes
`mode` — `record` (fetch and snapshot), `live` (fetch, no snapshot), or
`replay` (no network at all; requires the checkpoint-relative `snapshot_ref` a
previous record returned) — and returns `RetrievalRecordV1` rows.

| Tool | Purpose | LLM |
|---|---|:---:|
| `web_search` | DuckDuckGo (no API key), `n` clamped to 10 | ✗ |
| `fetch_url` | URL → readable text, through pinned-IP SSRF and redirect controls | ✗ |
| `search_papers` | Search **one** pinned academic provider — `semantic-scholar` (the default), `arxiv` or `alphaxiv`, from the `provider` argument or `ARI_RETRIEVAL_BACKEND`. There is no per-provider tool and no composite: `provider="both"` is refused, with the instruction to issue two pinned calls and merge by aliases | ✗ |
| `walk_citations` | Bounded Semantic Scholar citation walk with cycle detection, `direction` `references` or `citations`, capped by `max_depth` (≤5), `max_nodes` (≤500) and `request_budget` | ✗ |
| `rerank_retrieval_records` | Reorder already-retrieved `RetrievalRecordV1` rows against a research question. Explicitly stochastic and separate: the deterministic retrieval path never calls it, and the result carries the model, prompt digest, input digest and output digest that produced the order | ✓ |
| `list_uploaded_files` | List `{name, size_bytes}` under the checkpoint's `uploads/` | ✗ |
| `read_uploaded_file` | Read one uploaded text file, with binary detection | ✗ |

The retrieval backend is chosen per call or by environment; there is no tool
that mutates it for the process, so two concurrent callers cannot change each
other's provider (`ari-core/tests/test_retrieval_backend.py` pins that absence).

## ari-skill-knowledge — read-only Knowledge surface

This compatibility-named package is a Capability Provider exposing only
queries and non-authoritative requests against the ARI Knowledge Skill
Registry. It cannot register, promote, revoke, rewrite a lock, or activate a
Knowledge Skill. The fixed `knowledge_binder_v1` remains authoritative.

| Tool | Purpose | Authoritative |
|---|---|:---:|
| `search_knowledge_skills` | Search the frozen catalog projection | No |
| `describe_knowledge_skill` | Read one manifest/body description | No |
| `list_active_knowledge_skills` | Read the active epoch/node projection | No |
| `request_knowledge_skill` | Emit a selection proposal for fixed admission | No |

## ari-skill-harness — read-only Assurance surface

This package exposes discovery, evidence reading, and auxiliary-verification
requests. It is not the Harness Resolver or Fixed Verifier. Agent tool choice
cannot select the authoritative suite or execute a locked verification run.

| Tool | Purpose | Authoritative |
|---|---|:---:|
| `search_harnesses` | Search the frozen Harness catalog projection | No |
| `describe_harness` | Read one Harness description | No |
| `request_auxiliary_verification` | Propose an additive verification requirement | No |
| `read_attestation` | Read a persisted attestation | No |
| `list_verification_requirements` | Read admitted requirements | No |

Neither package exposes registration, promotion, revocation, lock rewrite,
tolerance/oracle replacement, or `force_pass`. Catalog administration is a
human-authenticated CLI/PR workflow. See
[Knowledge, Capability, and Scientific Assurance](knowledge_capability_assurance.md).

## ari-skill-tool-registry — brokered access to large MCP collections

Six federation operations stand in for an entire upstream collection, so a
collection of thousands of leaves costs the agent six tool slots rather than
thousands. Leaf provider schemas are never exposed through `tools/list`.

| Tool | Purpose | LLM |
|---|---|:---:|
| `discover` | Search the immutable federated catalog under `lexical` / `exact` / `diverse` strategy. Returns bounded summaries and opaque `tool_ref` values, at most 25 per page; it executes nothing | ✗ |
| `describe` | Read one paginated descriptor `section` (`summary`, `schema`, `provenance`, `admission`, `limitations`, `all`) for one exact `tool_ref`. Provider text and schemas are handled as untrusted data | ✗ |
| `invoke` | Invoke one admitted leaf by immutable `tool_ref` in `live`, `record` or `replay` mode. A bare or unqualified name is refused | ✗ |
| `invoke_scheduled` | The same operation for a leaf that submits work to a scheduler. It is a separate surface because a Provider's side-effect class follows its permissions, so carrying scheduler authority on the shared surface would raise the envelope of every leaf dispatched through it | ✗ |
| `get_status` | Poll an asynchronous registry `handle` through the lifecycle operations bound into its immutable descriptor | ✗ |
| `get_result` | Fetch the final normalized result for an asynchronous registry `handle` | ✗ |

`invoke`, `invoke_scheduled`, `get_status` and `get_result` declare a run-scope
context requirement, so their input schemas declare `ari_context` for the
transport to fill — the same injection rule as `measure_counters` above. This
package's `mcp.json` has been regenerated from `skill.yaml` and lists all six
names, `invoke_scheduled` included, so `scripts/check_skill_manifests.py`
reports no `compat-metadata-drift` for it. For catalog
identity, admission levels, and the provider adapters, see
[Federated Scientific Tool Registry](tool_registry.md).

## See also

- `docs/reference/skills.md` — narrative description of each skill (responsibility, env vars, examples).
- `docs/reference/knowledge_capability_assurance.md` — normative three-layer
  identities, admission, locks, security, and extension gates.
- `docs/reference/environment_variables.md` — env-var-by-env-var reference.
- The `mcp.json` in each skill for the canonical tool name list.
- `@mcp.tool()` / `@server.list_tools()` in each skill's `src/server.py`
  for the canonical argument signatures.
