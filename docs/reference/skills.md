---
sources:
  - path: ari-core/ari/skill_manifest.py
    role: implementation
  - path: scripts/check_skill_manifests.py
    role: test
  - path: ari-core/ari/result.py
    role: implementation
  - path: ari-core/ari/async_tools.py
    role: implementation
  - path: ari-core/ari/skill_lock.py
    role: implementation
  - path: ari-core/ari/mcp/child_environment.py
    role: implementation
  - path: ari-core/ari/mcp/secure_stdio_proxy.py
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
  - path: ari-skill-hpc/ari_skill_hpc/server.py
    role: implementation
  - path: ari-skill-hpc/mcp.json
    role: config
  - path: ari-skill-coding/src/server.py
    role: implementation
  - path: ari-skill-coding/mcp.json
    role: config
  - path: ari-skill-paper-re/src/server.py
    role: implementation
  - path: ari-skill-paper-re/mcp.json
    role: config
  - path: ari-skill-tool-registry/src/server.py
    role: implementation
  - path: ari-skill-tool-registry/skill.yaml
    role: config
last_verified: 2026-08-02
---

# MCP Skills Reference

Skills are MCP servers that provide tools to the ARI agent. Tools are deterministic where possible; LLM-using and live-data tools are explicitly annotated. **15 skills total** (13 default, 2 default-off: the external orchestrator and federated tool registry).

## Canonical `skill.yaml` contract

Every built-in Skill package has exactly one versioned `skill.yaml`. It is the
source of truth for package identity, safe entrypoint, environment declarations,
tool capability, phases, side effects, determinism, timeout class, permissions,
and result schema. The normative JSON Schema is
`ari-core/ari/schemas/skill_manifest_v1.schema.json`.

```yaml
schema_version: 1
name: coding-skill
package: ari-skill-coding
version: 0.2.0
environment_policy: complete
entrypoint:
  transport: stdio
  command_kind: python
  module: src/server.py
required_env: []
optional_env: [ARI_CHECKPOINT_DIR, ARI_WORK_DIR]
credential_scopes: []
tool_defaults:
  phases: [bfts, reproduce]
  side_effects: stateful
  determinism: conditional
  timeout_class: bounded
  permissions: [workspace-read, workspace-write, process]
  result_schema: ari.result-envelope/v1
tools:
  - name: run_code
    capability_ref: ari.execution.code
```

Package defaults avoid duplicating identical policy for every tool; a tool may
override any policy field. `mcp.json` is no longer hand-maintained source. It is
a generated compatibility view for existing dashboard and external consumers:

```bash
python scripts/sync_skill_metadata.py --write
python scripts/check_skill_manifests.py
```

The conformance gate rejects an unversioned/invalid manifest, package-version
drift, statically declared runtime tool-name drift, workflow reference or phase
drift, stale `mcp.json`, undeclared static environment reads, a dynamic
environment read whose names cannot be proven, an incomplete environment
policy, and name collisions among default-enabled Skills. A live
`tools/list` comparison is enforced for every locked run; moving the same check
into package-only CI remains a P1 follow-up. Runtime loading and discovery
reject unversioned manifests. The read-only
`ari.migrations.skill_manifest.load_legacy_skill_manifest()` utility can inspect
or convert old metadata in memory, but marks it default-off and is not an
admission path.

All built-in manifests use `environment_policy: complete`. `required_env` and
`optional_env` are the exhaustive ordinary-variable allowlist. Secret-like names
are rejected there and must instead belong to exactly one named
`credential_scopes` entry. Scope values are supplied only to the admitted Skill;
the manifest, HTTP bridge request, `SKILLS.lock`, result provenance, and traces
contain scope IDs and variable-name presence, never credential values.

At spawn, ari-core constructs a new environment rather than copying
`os.environ`: only a small platform/TLS baseline, manifest-declared names, and
core-owned isolated `HOME`/XDG/Python settings are present. The MCP SDK's
implicit `HOME`/`USER` baseline is explicitly overridden. Missing required
variables, credential classification errors, and credential-scope changes on
reconnect fail closed. Provider stdout, structured MCP results, exceptions, and
stderr are value-redacted. For Claude CLI direct MCP, a secure stdio proxy
applies the same exact environment and redaction after the CLI's own parent-env
merge; credential references are materialized only inside the local shim, in a
mode-0600 temporary config that is removed immediately. Claude debug logging is
disabled when credentials are active, while redacted stream events remain in
`tool_calls.jsonl`.

All built-in tools now declare `ari.result-envelope/v1`. The typed
`MCPClient.call_tool_envelope()` path normalizes MCP text/structured results,
classifies tool/transport/protocol/timeout/cancellation errors, and stores raw
responses over 4,000 characters content-addressably when a run artifact store is
available. `MCPClient.call_tool()` remains a lossless compatibility projection to
the historical `{"result": text}` / `{"error": message}` dictionary.

Timeout selection has no tool-name table. Each resolved tool receives a
manifest `timeout_class`; a caller-controlled wall-time field affects the outer
transport timeout only when `timeout_budget` explicitly names that argument,
buffer, unit, and maximum. Undeclared arguments cannot enlarge the budget.

An async submitter declares `async_lifecycle` with its handle field and semantic
status/result/cancel capabilities. Admission resolves those capabilities to
immutable runtime `tool_ref` values and returns an `AsyncToolHandleV1` in the
result envelope. `MCPClient.get_async_status()`, `get_async_result()`,
`cancel_async()`, and `wait_for_async()` use only those bound references. Provider
states are mapped by the reviewed manifest; missing handles and unknown states
fail as typed protocol errors. The normative portable-handle schema is
`ari-core/ari/schemas/async_tool_handle_v1.schema.json`. SLURM submit and the
external ARI orchestrator already use this same lifecycle contract.

`capability_ref` expresses semantic capability and may be shared by alternative
implementations. Runtime name is not evidence that two tools are equivalent.
`tools/list` entries now carry a runtime `tool_ref` bound to the normalized
manifest and live input/output schemas. Typed dispatch accepts that immutable
reference; a unique bare name remains migration-only. A duplicate bare tool name is an
admission error rather than last-writer-wins.

On first live discovery for a run, ari-core atomically writes
`{checkpoint}/SKILLS.lock`. The lock includes every configured provider's
manifest/provider digest, the exact input and output schemas returned by
`tools/list`, resolved tool policy, disabled tools, and the admitted immutable
`tool_ref` set for each runtime phase. A second process or resumed run must
produce the exact same registry digest before dispatch is allowed. Manifest,
schema, provider, phase, or disabled-tool drift fails closed; an enabled provider
that cannot start is also an admission error rather than a silently smaller
catalog. A stage subprocess may start only its owning provider, but must verify
that exact provider/tool subset against the already-created full lock and cannot
create or replace the authoritative snapshot. The lock contains ordinary
environment names plus value-free credential scope records (`scope_id`,
declared/present names, identity digest), but never credential values. The same
active scope IDs are copied into result provenance. Its normative schema is
`ari-core/ari/schemas/skills_lock_v1.schema.json`.

The external orchestrator is therefore default-off
and is not injected into the experiment agent's tool set.

To add a built-in Skill, add one package-level manifest and server, then regenerate
compatibility metadata. To add a large external collection, implement one
`CatalogSource`/provider adapter through the default-off federated tool registry;
do not add a core registration record per leaf tool. See
[Federated Scientific Tool Registry](tool_registry.md).

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

#### `survey(topic, max_papers=8, mode="record", snapshot_path="survey_snapshot_v1.json", provider="semantic-scholar")`

Search Semantic Scholar for related papers. No LLM, but classified as
`live-data` because upstream results can change over time.

```python
result = survey("OpenMP compiler optimization HPC benchmarks")
# Returns papers plus a digest-verified SurveySnapshotV1.
```

Requires `S2_API_KEY` environment variable for higher Semantic Scholar rate limits.

#### `generate_ideas(topic, papers, experiment_context="", n_ideas=3, n_agents=4, max_discussion_rounds=2, max_recursion_depth=0, survey_snapshot=null, seed=null, generation_mode="auto")`

Generate research hypotheses using VirSci multi-agent LLM deliberation. Multiple AI personas (researcher, critic, expert, synthesizer) debate the research question. Called **once** before BFTS starts (pre-BFTS only).

Model: `ARI_LLM_MODEL` env > `LLM_MODEL` env > `ollama_chat/qwen3:32b`.

#### VirSci-live (vendor-wrap) — opt-in real engine

`generate_ideas` has two interchangeable engines behind the same idea contract.
The default (**reimpl**) runs the lightweight re-implemented
discussion loop. The opt-in (**real_wrap**) instead runs VirSci's *actual*
mechanism — `Platform.select_coauthors` (freshness team formation) +
`Team.generate_idea` (multi-agent deliberation) from the vendored, **unedited**
`vendor/virsci` — grounded on a **live** Semantic Scholar snapshot (corpus +
SPECTER2 cosine retrieval index + author profiles + co-author graph).

- **Default OFF.** Enable with env
  `ARI_IDEA_VIRSCI_REAL=1`, the CLI flag `--virsci-live`, or the GUI experiment
  wizard "VirSci live" toggle (Scope/Resources step; persisted to
  `launch_config.json`).
- **Explicit fallback.** `generation_mode="auto"` may fall back to the default
  adapter, but records requested/actual adapters and the error in provenance.
  `generation_mode="virsci"` fails closed. Both engines pass through the same
  `IdeaSetV1` preflight. Beyond that, the live-snapshot build now **fails loud on an
  empty / 0-paper S2 fetch** (a 429 rate-limit, network failure, or no search hits):
  rather than silently writing a "successful" 0-paper manifest with placeholder
  authors — which would run VirSci fully ungrounded yet record it as a `real_wrap`
  success — it raises so `generate_ideas` degrades **visibly** to the reimpl loop. A
  cached manifest with `n_papers == 0` is treated as a poisoned cache and never reused
  (it is rebuilt). When the topic `/paper/search` is throttled (S2 429) but the survey
  already vetted paper ids, the build recovers by fetching a seed corpus through
  `/paper/batch` (keyed by id, so more targeted and less likely to be throttled),
  recorded as `seed_fallback` in `virsci_snapshot/snapshot_manifest.json`.
- **Path reporting.** `idea.json` carries `virsci_integration_status`:
  `"real_wrap"` when the vendor engine ran, or `"reimpl: …"` (with the reason)
  when the reimpl loop was used.
- **LLM:** deliberation follows the per-phase Idea model (`ARI_MODEL_IDEA`);
  engine calls route through litellm so ARI's cost tracker captures them.
- **Scope:** a single live snapshot — no era-split / no paper-parity (those are
  VirSci's retrospective-benchmark artifacts, out of scope). freshness/diversity
  come from the S2 author profiles + co-author graph.
- **Deps:** the `virsci` pip extra (faiss-cpu, transformers, torch, loguru,
  sqlalchemy); SPECTER2 weights are fetched at runtime; needs
  `SEMANTIC_SCHOLAR_API_KEY` / `S2_API_KEY` (for `embedding.specter_v2`) and an
  OpenAI-compatible LLM endpoint (the ARI CLI shim).

Env knobs (only the toggle is required; the rest are tunable — see
[Environment Variables](environment_variables.md)):

| Variable | Default | Purpose |
|---|---|---|
| `ARI_IDEA_VIRSCI_REAL` | unset (off) | toggle the real vendor-wrap path |
| `ARI_IDEA_VIRSCI_K` | `7` | discussion turns (vendor `group_max_discuss_iteration`) |
| `ARI_IDEA_VIRSCI_TEAM_SIZE` | `3` | max team members (vendor `max_teammember`) |
| `ARI_IDEA_VIRSCI_N_AUTHORS` | `16` | author pool for `select_coauthors` |
| `ARI_IDEA_VIRSCI_N_PAPERS` | `800` | SPECTER2 retrieval corpus size |
| `ARI_IDEA_VIRSCI_MAX_TEAMS` | `n_ideas` | cap on teams driven through `generate_idea` |
| `ARI_IDEA_VIRSCI_SPECTER2_MODEL` | `allenai/specter2_base` | local query embedder |

CLI flags on `ari run`: `--virsci-live` / `--no-virsci-live`, `--virsci-k`,
`--virsci-team-size`, `--virsci-n-authors`, `--virsci-n-papers`.

---

## ari-skill-evaluator

Immutable metric admission and evidence-grounded evaluation. Deterministic
parsing never invokes an LLM or silently becomes a scientific contract.

### Tools

#### `make_metric_spec(experiment_text)`

Parse experiment Markdown and consume an admitted `ResearchContractV1` or an
explicitly human-admitted proposal. The persisted `MetricGateContractV1` is
digest-bound and mint-once.

```python
result = make_metric_spec(open("experiment.md").read())
# Returns: {
#   "metric_keyword": "GFLOP_per_s",
#   "expected_metrics": ["GFLOP_per_s", "GB_per_s"],   # MEASURED outputs
#   "metric_unit": "GFLOP/s",
#   "metric_direction": "higher",
#   "min_expected_metric": 50000.0,
#   "scoring_guide": "..."
# }
```

If no admitted contract exists, parser fields remain evidence only and the
result says `human-review-required`.

#### `propose_metric_contract(idea_json, checkpoint_dir="", model="", model_revision="")`

Explicit LLM proposal for legacy ideas. It records complete provenance and
always returns `MetricContractProposalV1`; it never admits its own output. Pass
that proposal plus a named `reviewer` to `make_metric_spec` for explicit human
admission.

#### `claim_evidence_hard_gate(checkpoint_dir, paper_path, science_data_json="", paper_claim_links_path="", figures_manifest_json="", policy=None, phase="draft")`

Deterministic `GateReportV1` claim/evidence gate. **No LLM**. It recomputes
numbers from typed exact-run measurements, verifies artifact digests, applies a
closed unit registry, and rejects missing, changed, cross-run, or untyped
evidence. A blocking final result returns `{"error": ...}` so finalization is
skipped; `off` never blocks.

#### `evidence_grounded_semantic_review(checkpoint_dir, paper_path, science_data_json="", hard_gate_path="", paper_claim_links_path="", phase="initial")`

Non-blocking `SemanticReviewV1`. **LLM: Yes**. It records a dedicated model,
revision, prompt digest, evidence digest, and hard-gate digest. It cannot modify
the hard gate; failures are `status: unavailable` and never fabricate success.

---

## ari-skill-paper

LaTeX paper generation, compilation, and review (post-BFTS only). **LLM: Yes**.

### Tools

#### `list_venues()`

Returns available venue configurations.

Supported venues: `neurips` (9 pages), `icpp` (10 pages), `sc` (12 pages), `isc` (12 pages), `arxiv` (unlimited), `acm` (10 pages).

#### `get_template(venue)`

Returns the LaTeX template for a venue.

#### `compile_paper(tex_dir, main_file="main.tex", figures_manifest_path="")`

Compile through the common bounded execution contract. The compiler uses fixed
`pdflatex` / `bibtex` command profiles, disables shell escape, rejects undeclared
file/process access, imports only artifacts admitted by `FigureBatchV1`, kills the
whole process group on timeout, and records complete stdout/stderr plus environment
and PDF digests in `PaperCompileV1`.

#### `check_format(venue, pdf_path)`

Validate paper format against venue requirements (page count, etc.).

#### `write_paper_iterative(workspace_root, science_data_path, figures_manifest_path, references_path, ear_manifest_path, rubric_id, experiment_summary="", context="", verified_context_path="", venue="arxiv", max_revision_rounds=2, author_name="")`

Whole-document authoring from a closed workspace and native contracts only:
`ScienceDataV1`, `FigureBatchV1`, recorded retrieval result plus
`SurveySnapshotV1`, and the EAR evidence index. The explicit rubric and venue
template are hashed inputs. Every prompt, raw model response, model/revision,
sampling/usage record, immutable TeX/Bib revision, claim anchor, citation key,
figure ID, and math digest is retained in a draft `PaperBuildV1`. Generic node
JSON, inline references, and schema-less numeric fallbacks are not runtime inputs.

#### `review_compiled_paper(rubric_id, tex_path="", pdf_path="", figures_manifest_json="", experiment_summary="", vlm_findings_json="", num_reflections=None, num_fs_examples=None, num_reviews_ensemble=None)`

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

`rubric_id` is required. Runtime environment/default/legacy fallback resolution
was removed; old config can be converted offline with
`src.rubric_migration.migrate_legacy_rubric_selection` and then committed as an
explicit workflow field.

#### Symmetric author / reviewer venue conditioning

`prompt_overrides` carries two parallel fields:

- `system_hint` — injected into peer-review prompts by `review_engine`
  (existing behaviour).
- `author_hint` — injected into the whole-document authoring prompt as a
  dedicated `══ VENUE-SPECIFIC AUTHOR
  GUIDANCE ══` block. Tells the drafter what reviewers will look for,
  so the paper is written to make those signals easy to surface.

Empty `author_hint` contributes no venue-specific block. SC and NeurIPS ship calibrated
`author_hint` blocks; remaining venues are empty and can be filled in
incrementally without touching code.

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

#### `inject_code_availability(tex_path, ref="", sha256="", doi="", license_id="", checkpoint_dir="")` — v0.7.0

Runs as the `finalize_paper` stage. Auto-loads the curated bundle's
`ref` / `bundle_sha256` / `doi` from `ear_published/manifest.lock` +
`publish_record.json` and injects machine-readable `\codeavailability{}`,
`\codedigest{}`, `\coderef{}` macros plus a human-readable Code
Availability section into `full_paper.tex`. The macros let downstream
tools (`ari clone`, third-party readers) recover the bundle without
trusting the registry — the digest is the trust anchor. Skips silently
when no curated bundle exists (so v0.6.0 checkpoints keep building).

#### `merge_reviews(review_report_path, vlm_review_path="")` — v0.7.0

Post-hoc structural merge of `review_report.json` (text reviewer) and
`vlm_review.json` (VLM figure review). Purely deterministic — no LLM.
Attaches `vlm_figure_review` and `_review_composition` metadata so the
GUI / CLI can show both outputs with clear source attribution. The
upstream stages stay independent (matching AI Scientist v2's
`perform_review` contract) and are reconciled here.

The current signature also accepts `hard_gate_path` and
`semantic_review_path`. The merge output preserves text, visual, semantic, and
hard-gate inputs as independent records and emits a separate deterministic list
of proposed refinements; no source review file is mutated.

#### `link_paper_claims(tex_path="", science_data_json="", figures_manifest_json="", output_path="")` — v0.9.0

Reconciles `% CLAIM:Cx:NCx` anchors against science_data claims and builds
`paper_claim_links.json` (anchors / writer_assertions / numeric_mentions /
figure_refs / unresolved_anchors / uncovered_numeric_candidates) consumed by
the claim hard gate. **Deterministic, no LLM**. The transform-stage
`science_data.json` is never mutated; figure binding is recorded here. Run after
`write_paper` (draft) and again after `paper_refine` (final). Degrades to a
valid empty result on failure (never error-only) so it cannot cascade-skip the
finalize chain.

#### `paper_refine(tex_path="", suggested_revisions_json="", merged_review_path="", semantic_review_path="", venue="arxiv")` — v0.9.0

Anchor-preserving revision pass that applies `suggested_revisions` (from
`evidence_grounded_semantic_review` / the merged review). **LLM: Yes**. Explicit
`replace "X" with "Y"` substitutions are applied deterministically first, then a
bounded multi-pass LLM find/replace handles the remainder; every `% CLAIM`
anchor present in the draft must survive (anchor-dropping edits are rejected and
on net anchor loss the original paper is kept). Math-safe underscore escaping
skips `\( … \)` / `\[ … \]` and math environments. The refined LaTeX is returned
under `latex` (the draft is preserved as `full_paper.draft.tex`).

#### `finalize_paper_build(...)` — v0.3.0

Fail-closed final lock over the exact draft build, final TeX/Bib/PDF, compile
record and logs, figure batch, claim links, hard gate, independent text/VLM/
semantic reviews, and refinement model-call batch. It rereads every declared
artifact and rejects digest/size drift, cross-run evidence, dropped claim/
citation/figure identities, changed math, incomplete numeric coverage, disabled
or blocking hard gates, failed or below-threshold visual review, and mismatched
PDF output. A blocked record is still persisted for audit but the MCP call does
not claim success. See [PaperBuildV1](paper_build_contract.md).

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

**Typed HPC execution.** Both `build_reproduce_sh` and `run_reproduce`
consume the optional `reproduce_contract.execution_profile` block
([reference](execution_profile.md)):

- The agent prompt receives an `EXECUTION PROFILE` JSON block + a live
  `CLUSTER SHAPE` snapshot from `SLURM_JOB_NUM_NODES` / `SLURM_NTASKS`
  / `nvidia-smi`, plus a `COMPUTE-NODE EXECUTION CONVENTIONS` footer
  (shared FS, srun-first, conda activation, multi-node fan-out,
  timeout wrapping). The full appendix lives in
  `ari-skill-paper-re/src/_replicator_agent.py::_format_hpc_appendix`.
- For `kind ∈ {mpi, mpi_gpu}` an MPI aggregation skeleton
  (`prompts/mpi_aggregate_skel.py`) is auto-copied into
  `submission/mpi_aggregate.py`.
- `run_reproduce` compiles typed placement, GPU, memory, constraint, hint,
  account, QoS, reservation, and module fields into `JobRequestV1`. Arbitrary
  scheduler flags and contradictory resource shapes fail closed.
- CPU/memory binding remains an explicit `srun` job-step responsibility in
  `reproduce.sh`; requested GPU resources are never silently removed.

PaperBench is vendored as a git submodule under
`ari-skill-paper-re/vendor/paperbench`; the bridge module
`_paperbench_bridge.py` adapts the upstream `TaskNode` /
`SimpleJudge` API to ARI's rubric envelope. The main per-leaf grading
completer routes through LiteLLM (`_litellm_completer.py`) so any
provider works (`gpt-5-mini`, `anthropic/claude-...`, `gemini/...`,
`ollama/...`); the score-parsing structured completer stays on
`gpt-4o-2024-08-06` (within PaperBench's allow-list).

### Tools

#### `fetch_code_bundle(ref="", sha256="", dest="", checkpoint_dir="", overwrite=False)`

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

#### `build_reproduce_sh(paper_path="", paper_text="", rubric_path="", output_dir="", model="", time_limit_sec=43200, iterative_agent=False, max_steps=0, sandbox_kind="auto", container_image="", overwrite=False)`

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

#### `run_reproduce(rubric_path, repo_dir, sandbox_kind="", container_image="", timeout_global_sec=0, partition="", cpus=0, walltime="", …SLURM flags)`

**Phase 1**. Executes `repo_dir/reproduce.sh` in a sandbox; captures
`reproduce.log` and lists artefacts; reports any
`expected_artifacts` (from the rubric envelope) that did not appear.

Sandbox priority (`auto`, the default): `slurm` (when sbatch is on
PATH AND `ARI_SLURM_PARTITION` is set — the same partition BFTS used)
→ `docker` (when daemon usable and not on HPC) → `apptainer` →
`singularity` → `local`. Override with the `sandbox_kind` argument
or `ARI_PHASE1_SANDBOX`. Container sandboxes have no mutable default image.
Provide a full Docker `sha256:<image-id>` / `name@sha256:<digest>`, a local
non-symlink SIF, or a digest-pinned remote Apptainer reference through the
argument or `ARI_PHASE1_DOCKER_IMAGE` / `ARI_PHASE1_APPTAINER_IMAGE` (the
latter also applies to the Singularity runtime).

**SLURM dispatch**: constructs a digest-bound `JobRequestV1`, receives an
idempotent handle, then observes status/logs and cancels on timeout. The shared
HPC adapter alone invokes `sbatch --parsable --export=NIL`; paper-re does not
construct scheduler argv or inherit the parent environment. Partition / CPU /
walltime resolve
arg > env (`ARI_SLURM_PARTITION` / `ARI_SLURM_CPUS` /
`ARI_SLURM_WALLTIME`) > `{checkpoint_dir}/launch_config.json`. The absolute
`reproduce.sh` path is a pinned input; scheduler logs are digest-checked before
being materialized as `reproduce.log`.

```python
result = run_reproduce(
    rubric_path="ors_rubric.json",
    repo_dir="repro_sandbox",
)
# Returns: {executed, exit_code, log_path, artifacts, missing,
#           elapsed_sec, sandbox_kind, [partition, cpus, walltime, timed_out]}
```

#### `grade_with_simplejudge(rubric_path, repo_dir, paper_path="", paper_text="", judge_model="", n_runs=0, skip_negative_control=False, code_only=False)`

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

#### `generate_rubric(paper_path, paper_text, output_path, target_leaf_count=0, model="", temperature=0.0, seed=0, two_stage=True, paperbench_rubric_id="")`

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

`paperbench_rubric_id` (unreleased) selects a venue-conditioned template
from `ari-core/config/paperbench_rubrics/<id>.yaml`. Empty string =
bundled prompt verbatim (back-compat). Non-empty values load the YAML
and inject `prompt_overrides.system_hint` / `prompt_overrides.leaf_style`
into the skeleton + subtree prompts via `{VENUE_HINT}` placeholders.
This mirrors the `reviewer_rubrics/` venue pattern already used by
`ari-skill-paper` for peer review, so the same `venue → YAML → prompt`
flow is now available for the rubric generator. Shipped templates:
`generic` (back-compat), `sc` (HPC paper-audit, 6 axes), `neurips`
(ML reproducibility, 6 axes), `nature` (wet-lab, 5 axes). `paper_audit`
mode requires `two_stage=True`. See
[`docs/reference/rubric_schema.md`](rubric_schema.md#venue-conditioned-templates)
for the YAML schema.

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

### v0.7.2 — `reproduce_contract.execution_profile`

The skeleton + subtree prompts now instruct the generator to populate
`reproduce_contract.execution_profile` when the paper specifies parallel
execution properties (MPI rank counts, GPU type, exclusivity, memory,
NUMA bindings). Schema:
[`docs/reference/execution_profile.md`](execution_profile.md).
The field is optional and backward-compatible — single-CPU papers leave
it absent.

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

Store an entry tagged with `node_id`. **Copy-on-Write**: the manifest requires
an explicit node context, and the skill rejects a write unless the signed
`NodeContextV1.node_id` equals the target. A child cannot mutate an ancestor.

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

#### `get_experiment_context()`

Stable experiment facts read from Letta core memory — `experiment_goal`,
`primary_metric`, `hardware_spec`, etc. Seeded once after the first
node's `generate_ideas` completes (the moment `primary_metric` is
determined); safe to call repeatedly (60 s in-process cache). Returns
`{}` until that seed runs.

#### Typed verifiable-research-memory tools

Typed entries (Phase 1) carry structured provenance so the paper / figure
stages can ground claims on reproducible artifacts. Callers are loop/pipeline
hooks, not LLM pulls. Every write tool is **Copy-on-Write guarded** by a
tool-bound, signed `NodeContextV1`; reads additionally validate their requested
node set against its ordered lineage digest. ari-core injects this transport
context after model argument generation, so callers cannot promote themselves
to a sibling or ancestor.

#### `add_experiment_result(node_id, text, metric_ptr=None, artifact_refs=None, node_report_ref=None)`

Record a typed `experiment_result` (CoW: self node only).

#### `add_failure_case(node_id, text, artifact_refs=None, node_report_ref=None)`

Record a typed `failure_case` (CoW: self node only).

#### `add_procedure_memory(node_id, text, node_report_ref=None)`

Record a reusable procedure (CoW: self node only).

#### `add_reflection(node_id, text, confidence=None, node_report_ref=None)`

Record a reflection (CoW: self node only). Not usable for paper claims.

#### `add_reproducibility_event(node_id, target_memory_id, status, artifact_refs=None, text=None)`

Append an append-only reproducibility status event against an existing entry
(CoW: self node only).

#### `search_research_memory(query, ancestor_ids, kinds=None, require_artifacts=False, limit=5)`

Ancestor-scoped typed search, filtered by `kind` / artifact presence. Siblings
and children are never returned.

#### `get_verified_context(ancestor_ids, purpose="paper", limit=None)`

Artifact-grounded, reproducibility-aware context for paper / figure use.

#### `audit_memory(experiments_root, run_id=None)`

Verify recorded provenance (sha256) against disk for a checkpoint. Returns
`{summary, results}`.

#### `consolidate_node_memory(node_id, node_report, work_dir, run_id=None)`

Derive and write typed memory (`experiment_result` / `failure_case` /
`reflection`) from a `node_report` at node end via the typed writer (CoW: self
node only). Caller is the ari-core node-end hook.

Storage: per-checkpoint Letta agent with two archival collections
(`ari_node_*`, `ari_react_*`). A snapshot at
`{ARI_CHECKPOINT_DIR}/memory_backup.v1.json.gz` keeps checkpoints
portable. The v0.5.x JSONL stores were removed in v0.5.0
(checkpoint-scoped `memory_store.jsonl` and the legacy global JSONL that
once lived under `$HOME/.ari/`); use `ari memory migrate` to import
legacy data. Cross-experiment "global memory" is no longer a feature —
stable lessons belong in `experiment.md`, code, or prior papers.

Research records are content-addressed and append-only; no public or backend
per-node clear operation exists. Search includes explicit model/ranking/filter
provenance. See [Research memory contract](memory_contract.md).

---

## ari-skill-orchestrator

Expose ARI as an authenticated, durable MCP control plane for external agents and
IDEs. **LLM: No** (delegates to ARI CLI). Stdio is canonical; the optional network
transport is bearer-authenticated MCP Streamable HTTP. Both use one service and state
machine; there is no parallel REST/SSE API.

### Tools

#### `run_experiment(experiment_md, idempotency_key, ...)`

Idempotently launch a digest-bound experiment under declared depth, run, node, cost,
CPU, and timeout budgets. Returns `RunHandleV1`; no credential argument exists.

#### `get_status(run_id)`

Return authorized durable state and bounded scientific progress for an exact run ID.

#### `get_result(run_id)` / `stop_experiment(run_id)`

Return `RunResultV1` artifact references or propagate cancellation to the run's process
group.

#### `list_runs()`

List only runs visible to the authenticated principal.

#### `list_children(run_id)`

Return child runs of a parent experiment (for recursive sub-experiment tracking).

#### `get_paper(run_id)`

Return generated paper artifact references. `get_ear`, `list_artifacts`, and
`read_artifact` expose only verified SHA-256 identities, never checkpoint paths.

`list_skills(run_id)` and `get_workflow(run_id)` return only sanitized data from the
verified run-level `SKILLS.lock`. See [Orchestrator control plane](orchestrator.md).

---

## ari-skill-tool-registry

Default-off federation for large scientific MCP collections. It exposes only
`discover`, `describe`, `invoke`, `get_status`, and `get_result`; leaf tools are
generated into a reviewed immutable catalog. Execution requires an exact opaque
`tool_ref` and an admission decision. Provider output is normalized, and
record/replay evidence is retained in the EAR. See
[the dedicated registry reference](tool_registry.md).

OpenROAD profiles may execute either through a scoped local MCP session or as a
typed C06 SLURM job in a digest-pinned clean container. Both remain a single
virtual catalog leaf; scheduler resources, handles, logs, and provenance are
profile-locked and never become caller-supplied flags.

Qiskit profiles likewise expose one immutable async sampling experiment rather
than the upstream tool sets. Local ideal/noisy Aer, remote simulator, and IBM
hardware use distinct capabilities; QPY, target, transpilation, shots,
seeds/noise/mitigation, backend snapshot, evidence, and credential scope are
fixed. See [the Qiskit profile reference](qiskit_profiles.md).

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
  _provenance                                       ← union of emit_results
                                                       _provenance across the
                                                       node's results*.json
                                                       variants (when present)
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

It also reads back `{checkpoint}/metric_contract.json` (written by `evaluator-skill::make_metric_spec`, next to `tree.json`) and grafts it onto `science_data.metric_contract` so the deterministic hard gate enforces the declared contract (claims / correctness / `required_measured` / declared invariants) — without this graft the declared contract is inert and only the universal invariant registry reaches the gate.

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

#### `promote_ear(checkpoint_dir, target="public")` — v0.7.0

Promotes a previously-published EAR artefact to a wider visibility tier.
Thin MCP wrapper around `ari.publish.promote`. **Deterministic, no LLM**.
Returns `{ref, visibility, promoted_at, promote_failed_at}` (or
`{error, kind}` on a `PublishError`).

#### License templates — v0.7.0

When `publish.yaml::license` is set and `ear/LICENSE` does not already
exist, `generate_ear` emits one of: **MIT**, **Apache-2.0**,
**BSD-3-Clause**, **GPL-3.0**, **CC-BY-4.0** (templates under
`ari-skill-transform/src/licenses/`).

---

## ari-skill-web

Provenance-preserving web and academic retrieval. **LLM: No** for canonical
retrieval; the separate reranker and legacy iterative collector are stochastic.

### Tools

#### `search_papers(query, max_results=10, provider=null, mode="record", snapshot_ref="")`

Searches exactly one pinned `semantic-scholar`, `arxiv`, or `alphaxiv`
provider. It returns `RetrievalRecordV1`, a digest-bound survey snapshot, and a
content-addressed `snapshot_ref` in record mode. Provider failure is explicit;
there is no fallback or partially successful `both` mode.

#### `web_search(query, n=5, mode="record", snapshot_ref="")`

DuckDuckGo retrieval under the same live/record/replay contract.

#### `fetch_url(url, max_chars=8000, mode="record", snapshot_ref="", max_bytes=2097152)`

Fetches untrusted text through pinned-IP SSRF protection, redirect
revalidation, HTTPS-downgrade rejection, and byte/content-type limits.

#### `walk_citations(seed_ids, direction="references", max_depth=2, max_nodes=50, request_budget=20, mode="record", snapshot_ref="")`

Bounded Semantic Scholar graph traversal with cycle detection and explicit
partial results.

#### `rerank_retrieval_records(research_question, records, max_results=10)`

Explicit optional LLM reranking. Returns the selected typed records plus model,
API identity, temperature, and prompt/input/output digests.

#### Compatibility tools

`search_arxiv`, `search_semantic_scholar`, `set_retrieval_backend`, and
`collect_references_iterative` remain during the P6 deprecation window. New
workflows use `search_papers`; the default paper pipeline no longer calls the
combined LLM collector.

#### `list_uploaded_files()`

Lists user-uploaded files in the checkpoint directory. Deterministic.

#### `read_uploaded_file(filename, max_chars=50000)`

Reads text file content from uploaded files with binary detection. Deterministic.

Full wire and security semantics: [Retrieval contract](retrieval_contract.md).

---

## ari-skill-coding

Closed-workspace authoring, bounded execution, complete log evidence, and typed
measurement emission. **LLM: No** (user-code determinism is conditional).

### Tools

#### `write_code(filename, code, work_dir="/tmp/ari_work")`

Atomically write below the core-owned workspace. Traversal, absolute escape,
and symlink components are rejected.

#### `run_code(filename, work_dir="/tmp/ari_work", timeout=60)`

Execute an interpreted source file using structured argv. The source SHA-256 is
verified and bound to an immutable launch snapshot. Inline logs are bounded;
complete stdout/stderr are content-addressed artifacts.

#### `run_bash(command, work_dir="/tmp/ari_work", timeout=60)`

Run an explicitly shell-enabled command locally or through the configured clean
container adapter. Results include stable execution identity, unique attempt ID,
actual limit enforcement, network/container identity, and complete logs.

#### `read_file(path, offset=0, limit=8000, work_dir="/tmp/ari_work")`

Read a symlink-safe text file with bounded pagination. Returns content,
`next_offset`, and total character count.

```python
result = read_file("results.csv", offset=0, limit=100)
# Returns: {"content": "...", "next_offset": 100, "total_chars": 5000}
```

`ARI_WORK_DIR` owns the root; `work_dir` may only select a contained
subdirectory.

#### `emit_results(params, measurements, predictions={}, scores={}, provenance={}, units={}, execution=null, file="results.json", work_dir="/tmp/ari_work")`

Write a typed `results.json` separating input parameters from measured outputs. Call this once at the **end** of an experiment run so downstream stages (`transform → science_data`, paper writing, summary stats) can tell apart "what we measured" from "what we ran on" — a best-of reduction never accidentally picks an input size (e.g. `nnz`, `M`, `K`, `threads`) over a real metric (e.g. `GFlops_per_s`).

```python
emit_results(
    params={"M": 120000, "K": 120000, "nnz": 3840000, "threads": 8},
    measurements={"GFlops_per_s": 26.864, "GB_per_s": 63.802},
    predictions={"peak_gflops_model": 686.45},
    scores={"parallel_efficiency": 0.81},
    units={"GFlops_per_s": "GFLOP/s", "GB_per_s": "GB/s"},
    execution=run_result["measurement_execution"],
)
```

The canonical `ari.measurement-set/v1` object records finite numeric values,
explicit unit state, parameters, provenance, execution attempt/exit status, and
evidence artifact digests. The server-issued execution receipt and every log
digest are verified before writing. Parameter, measurement, prediction, and
score names must be disjoint. Path traversal is rejected. The flat `1.0` view
remains only as a P6 compatibility projection and is cross-checked by consumers.

The optional `provenance` arg is an `{operand: source}` map written verbatim into `results.json` as the `_provenance` key and consumed by the claim/metric-correctness gate. Tag an operand `"microbench"` or `"benchmark"` when its value is an empirically **MEASURED** ceiling/peak (so a normalized metric is not flagged as resting on a placeholder), and `"correctness"` or `"reference"` when it is a residual computed against an **independent** reference (so the output is not flagged as unverified). Best-effort; omitted entirely when empty.

`transform-skill` and the evaluator validate the common schema before use and
reject disagreement between canonical and compatibility views. See
[Execution and measurement contracts](execution_contract.md).

---

## ari-skill-benchmark

Typed summaries, statistical inference, and provenance-aware run comparison.
**LLM: No** (deterministic). Figure rendering is owned by `ari-skill-plot`.

### Tools

#### `analyze_results(request)`

Validate `AnalysisRequestV1` and return unit-bearing summaries, mean confidence
intervals, missing counts, source/input digests, and library versions.

#### `statistical_test(request)`

Validate `StatisticalTestRequestV1`; run paired/unpaired t or rank tests and
return effect size, confidence interval, assumptions, and corrected p-values.

#### `compare_runs(request)`

Rank compatible runs while retaining backend/environment groups, replicate
identity caveats, and provenance differences. See the
[deterministic analysis contract](analysis_contract.md).

---

## ari-skill-plot

Scientific figure generator. Two modes: **deterministic** (`generate_figures`, P2-safe matplotlib over a fixed schema) and **LLM-driven** (`generate_figures_llm`, an AI-Scientist-v2-style code-write-and-run path with optional VLM caption pass). **LLM: Mixed** (deterministic + P2-exception).

### Tools

#### `generate_figures(nodes_json_path, output_dir, figures=None, science_data_path="", vlm_captions=True, experiment_context="")`

Render canonical comparison figures from `nodes_tree.json` into `output_dir`.  Returns a manifest of every emitted figure with its caption and source node ids.  Byte-deterministic for a given matplotlib version.

#### `generate_figures_llm(nodes_json_path, output_dir, experiment_summary="", context="", n_figures=3, science_data_path="", vlm_feedback="")`

LLM examines the data shape + natural-language `intent`, writes matplotlib code, runs it in the same `_run_plot_code` sandbox, and (optionally) calls a VLM to caption the result.  P2 exception.

The `kind="plot"` system prompt now enforces a **LAYOUT** rule (call `fig.tight_layout()` and save with `bbox_inches='tight'`, put the legend outside the axes, rotate long tick labels; a figure with overlapping or truncated text is **REJECTED**) and a **COMPARABILITY** rule (do not juxtapose values measured on different scales/regimes without a clear axis or annotation). These are prompt-level guidance to the figure-writing LLM — no new mechanical gate is added.

### Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `VLM_MODEL` | Vision LLM for caption pass | `openai/gpt-4o` |
| `ARI_LLM_MODEL` | LLM that writes matplotlib code in `_llm` mode | (none — required for `_llm`) |
| `LLM_MODEL` | Cross-skill fallback | (none) |
| `ARI_LLM_API_BASE` | LiteLLM API base override | LiteLLM default |
| `OPENAI_API_KEY` | Required for OpenAI-hosted LLM/VLM | (none) |

### ari-core boundary

`src/server.py` imports `from ari import cost_tracker`; Phase 4 of the master refactor migrates this to `ari.public.cost_tracker`.

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
