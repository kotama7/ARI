# Changelog

All notable changes to ARI are documented here. Versions follow `MAJOR.MINOR.PATCH`.

## v0.7.0 (2026-05-08)

Headline: PaperBench-compatible reproducibility chain (ORS), BFTS lineage decisions
with dynamic axes, Letta semantic-search fix, typed `params` / `measurements`
split, and a sterile-child guard. The final 2026-05-08 polishing pass took the
ORS chain end-to-end on real hardware: an 18-minute agent rollout produced a
faithful CSR-SpMM replication (Numba + roofline + sweep) that scored 9/28
leaves (`ors_score=0.331`) versus 1/37 on the initial cut.

### Added

#### Reproducibility — PaperBench-compatible ORS chain
- New skill `ari-skill-replicate`: `generate_rubric`, `audit_rubric`. Two-stage
  generation (`prompts/skeleton.md` + `prompts/subtree.md`, parallel subtree fan-out
  with `asyncio.gather`, semaphore=4) replaces the single-call generator. Verified
  on PaperBench reference papers: leaves jump from 33–34 (single-call) to 71–149
  (two-stage); depth from 3–4 to 5; cost ~5× output tokens, ~140 s wall-clock at
  concurrency 4. Toggle via `ARI_RUBRIC_GEN_TWO_STAGE` (default on).
- PaperBench vendored at `ari-skill-paper-re/vendor/paperbench` (git submodule).
  Bridge `_paperbench_bridge.py`; setup `scripts/setup/install_paperbench.sh`.
  `_vendor_path.py` is the single source of truth for `sys.path` injection.
- ReAct Replicator: `AriPBSolver(BasicAgentSolver)` running PaperBench's
  `BasicAgentSolver` / `IterativeAgent` against ARI's HPC sandbox. Replaces the
  single-shot LLM Replicator. New: `LocalComputer` / `ApptainerComputer`
  (per-tool-call subprocess), `LocalPBTask` (bypasses `paperbench.paper_registry`).
  Configurable via wizard: time-limit-hours, max-steps, BasicAgent/IterativeAgent.
- New pipeline stages (replace `reproducibility_check`):
  ```
  ors_generate_rubric  → ors_rubric.json
  ear_publish          → bundle.tar.gz + publish_record.json
  ors_seed_sandbox     → repro_sandbox/ (deterministic seed, no LLM)
  ors_build_reproduce  → reproduce.sh (LLM, skipped when seed populates it)
  ors_run_reproduce    → ors_phase1.json (executes in sandbox)
  ors_grade            → ors_grade.json (PaperBench SimpleJudge)
  ```
- `ari-skill-paper-re` rewrite: removed `extract_repro_config`,
  `build_repro_report`, `extract_metric_from_output`. New: `fetch_code_bundle`,
  `run_reproduce`, `grade_with_simplejudge`, `build_reproduce_sh`. Sandbox
  priority `slurm → docker → apptainer → singularity → local` (override via
  `ARI_PHASE1_SANDBOX`).
- `LiteLLMTurnCompleter` for the per-leaf grading completer (provider-neutral;
  works with `gpt-5-mini`, `anthropic/...`, `gemini/...`, `ollama/...`). Replaces
  PaperBench's vendored `OpenAICompletionsTurnCompleter` for the main grader; the
  smaller score-parsing completers remain on OpenAI direct.
- `ARI_MODEL_JUDGE` default flipped to `gpt-5-mini` (the previous default
  `gpt-4o-2024-11-20` was paradoxically not in PaperBench's registry).

#### EAR lifecycle: curate · publish · promote · clone · registry
- `{checkpoint}/ear/publish.yaml` controls what enters the published bundle
  (`include` / `exclude` globs, `max_file_mb`, `visibility`, `license`,
  `backend`). Schema in `ari-core/ari/schemas/publish.schema.json`.
- Built-in deny list (always wins): `.env*`, `secrets/**`, `*.pem`, `*.key`,
  `id_rsa`, `id_ed25519`. Denied paths are not recorded in `manifest.lock`.
- New CLI: `ari ear curate` / `status` / `publish` / `promote`. Always starts
  `staged`; promotion is one-way upward (FR-P5).
- New CLI: `ari clone <ref>` — verify-by-digest fetcher. Resolvers: `file://`,
  `https://`, `ari://`, `gh:`, `doi:`. Recomputes per-file sha256 and the
  whole-bundle digest against `manifest.lock`. Atomic dest staging. **Never
  executes** (no `setup.sh`, no `curl|bash`).
- New CLI: `ari registry serve / token issue / token revoke / token list` —
  optional self-hosted backend (FastAPI + sqlite). Apptainer / docker-compose /
  pip deploy paths in `scripts/registry/`. Content-addressed
  (`sha256(bundle.tar.gz)[:16]`). Optional install via `./setup.sh --with-registry`.
- License templates (MIT / Apache-2.0 / BSD-3-Clause / GPL-3.0 / CC-BY-4.0)
  emitted from `publish.yaml::license` if no author-written `LICENSE` exists.
- `paper-skill:inject_code_availability` injects machine-readable
  `\codeavailability{}` / `\codedigest{}` / `\coderef{}` macros plus a Code
  Availability section into `full_paper.tex`, sourced from
  `manifest.lock` + `publish_record.json`.

#### `node_report.json` per BFTS node (foundational substrate)
Every BFTS node writes a structured self-report at
`experiments/{run_id}/{node_id}/node_report.json` on success/failure. Records:
`files_changed`, `original_direction` (preserved past evaluator overwrite),
`self_assessment`, `next_steps_hints`, literal `build_command` / `run_command`,
artifact metadata classified by role.

- New modules: `ari.orchestrator.node_report`, `ari.orchestrator.node_selection`
  (`filter_nodes` for `for_synthesis` / `for_code` / `for_narrative`).
- JSON Schema: `ari/schemas/node_report.schema.json` (draft-07).
- `node_report.json` lives in `META_FILES` so children never inherit a parent's
  report.
- New CLI: `ari migrate node-reports <checkpoint>` backfills legacy checkpoints.

#### `generate_ear` rewritten around `node_report`
The `ear/` layout now mirrors a paper-companion repo (README / reproduce.sh /
environment.json / code/ / data/ / figures/ / LICENSE). `EVOLUTION.md` and
`_provenance.json` are kept alongside the checkpoint, *outside* `ear/`, so they
never enter the published bundle.

- `code/` is collected via `select_source_files_for_publication` (deepest
  contributor wins per rel_path) — no size budget. Falls back to a whitelist
  scan of the best work_dir when reports are missing.
- Experiment outputs (CSVs, logs) are no longer published — `reproduce.sh`
  regenerates them. Internal ARI metadata (`tree.json`, `science_data.json`,
  `eval_scores.json`, `commands.md`, `logs/`, `reproducibility/`) is no longer
  copied into `ear/`. `run_config.json` moved to `checkpoint/run_config.json`.

#### `_run_env.json` per work_dir + reproducibility git shim
- `ari.agent.run_env.capture_env` writes `<work_dir>/_run_env.json` with
  hostname, SLURM job/partition/nodelist, CPU model/threads/MHz/arch, memory
  total, compiler versions — recorded *from inside the executing process* so
  SLURM jobs (running on a different node than the agent) get accurate hardware
  metadata. A portable bash version is auto-injected at the top of sbatch scripts.
- Git shim (`ari/agent/shims/git.sh`) wired into the reproducibility sandbox via
  `PATH=<sandbox>/.shims:<orig_path>`. Intercepts only `git clone` whose URL
  matches the paper's `code_availability_ref`; logs every clone attempt to
  `<sandbox>/repro_clone_log.jsonl`. Configurable via `ARI_REPRO_CLONE_POLICY`.

#### LLM lineage decisions (default on, stagnation-rule mode)
A judge LLM sees a `LineageState` (active idea, axis scores, recent composite
trajectory, alternatives pool, venue constraints, ancestor thread) and chooses
one of `{continue, switch_to_idea, fanout, terminate}`. Malformed outputs
silently degrade to `continue`.

- New: `ari.orchestrator.lineage_decision`, `ari.orchestrator.root_idea_selector`.
- BFTS hook reads `lineage_decision.mode` from `workflow.yaml`. `stagnation_rule`
  (default) calls the judge only when composite scores stay flat for
  `stagnation_window=5` nodes with delta below `stagnation_threshold=0.05`.
  `every_node` and `off` are alternative modes.
- Per-run rate limit: `rate_limit_per_run=5`, `min_nodes_before_decision=3`.
- Every fired decision (including `continue`) appended to
  `{checkpoint}/lineage_decisions.jsonl` for post-hoc analysis.
- New env vars: `ARI_MODEL_LINEAGE`, `ARI_MODEL_ROOT_SELECT` (both fall back
  through `ARI_MODEL_EVAL` → `ARI_MODEL` → `ARI_LLM_MODEL` → `gpt-4o-mini`).

#### Plan promote · lineage inheritance · dynamic axes
- `ari-core/ari/pipeline.py::_promote_plan_to_experiment_md` renders selected
  idea + plan §-tag titles + alternatives between HTML markers in the
  in-checkpoint `experiment.md` (idempotent). Configurable via
  `workflow.yaml::plan_promote` (`index_only` default | `full` | `off`). The
  user's source `experiment.md` is never touched.
- `ari-core/ari/lineage.py` — walks `meta.json:parent_run_id` to expose every
  ancestor checkpoint's `idea.json` to descendants. `inherit_idea_index` on
  `_api_launch_sub_experiment` materialises a chosen parent idea into the child's
  `experiment.md` and `idea.json` with `_pinned: True` provenance.
- `ari-core/ari/evaluator/dynamic_axes.py` — projects each
  `rubric.score_dimensions` entry into a BFTS axis, plus plan-derived axes
  (`model_calibration_present`, `scaling_study_present`, etc.) keyword-scanned
  from the VirSci plan. `LLMEvaluator` keys its axis cache on a content hash
  (sha1 of rubric YAML + plan §-tag titles), not mtime.

#### GUI
- New `LineageDecisionsPage` reads `lineage_decisions.jsonl` per run; surfaces
  every fired `continue` / `switch_to_idea` / `fanout` / `terminate` with
  rationale + state snapshot. Backed by `/api/lineage-decisions/<run_id>`.
- New "Lineage" column in `ExperimentsPage` shows the latest decision per run.
- CSS split into `tokens.css` / `layout.css` / `components.css` / `widgets.css` /
  `responsive.css`; `MemoryEntryCard` extracted as a standalone component.
- PaperBench-aware reproducibility section on `ResultsPage`: verdict badge,
  4-card ORS chain (Rubric → Replicator → Phase 1 → Phase 2), recursive grading
  tree (`<details>`-based, rebuilds the `TaskNode` hierarchy from
  `ors_rubric.json` + `ors_grade.json::leaf_grades`), provenance footer.
- Wizard: "Two-stage generation" checkbox (`ors.rubric_gen_two_stage`),
  "Replicator Agent" sub-section (BasicAgent/IterativeAgent dropdown,
  time-limit-hours, max-steps).

### Changed

#### Typed `params` / `measurements` split
Production diagnosis (CSR SpMM run): `science_data.json::summary_stats.best`
reported `3,840,000` — the input matrix `nnz` count, not any measurement. Root
cause: ARI had no contract for separating input knobs from measured outputs;
`nodes_to_science_data` reduced `summary_stats.best` via `max()` over every
`per_key_summary` entry, treating params and measurements as a single bag. Fix
spans five layers:

- `ari-skill-coding/src/server.py::emit_results` — new MCP tool with typed
  `params` / `measurements` / `predictions` / `scores` dicts. Writes
  `{work_dir}/results.json` (schema 1.0); refuses path traversal; coerces
  non-JSON-serializable values.
- `ari-core/ari/agent/loop.py::SYSTEM_PROMPT` — adds the rule that the agent
  must call `emit_results` after the final measurement run, separating params
  from measurements.
- `ari-core/ari/evaluator/llm_evaluator.py::MetricSpec` — adds
  `expected_params: list[str]`. Output parses both `params` / `measurements`
  / `metrics` (back-compat union); stores `_params_dict` / `_measurements_dict`
  on `Node.metrics`.
- `ari-skill-evaluator/src/server.py::make_metric_spec` — output schema gains
  `expected_params`; LLM-fallback prompt strict on the disjoint contract.
- `ari-skill-transform/src/server.py::nodes_to_science_data` — gains
  `primary_metric` + `higher_is_better` args. Source priority for the typed
  split: `results.json` → `node.metrics::_params_dict` → empty (legacy).
  `summary_stats.best` removed; replaced by `primary_metric_best` (max/min over
  the primary metric only) plus `typed_split_coverage` for adoption tracking.

#### BFTS plan-context truncation removed
`bfts.py::expand` was truncating the upstream `idea_context` to 800 chars before
injecting it into the planner prompt — the sender (`cli.py::_build_idea_ctx_for_expand`,
~10 KB §-tag-preserved) was upgraded but the receiver was not, so BFTS only
explored the generic `draft / validation / ablation / improve` operators and
never reached rubric axes like `scalability_evaluation`. Fix: drop the `[:800]`
slice.

#### Letta `search_memory`: substring → semantic
Production observation (84 successful `add_memory` writes): every child's
`search_memory` returned `[]`. The SDK call `passages.list(search=q)` maps to
`GET /v1/agents/{id}/archival-memory?search=q` which is a SQL substring filter
(`WHERE LOWER(text) LIKE LOWER(%q%)`), **not** semantic search. Long
natural-language queries never substring-match structured passages. Fix:

- `letta_client.py::archival_search` — replaced `passages.list(search=q)` with
  `passages.search(query=q, top_k=limit)` (route `/archival-memory/search`,
  `embed_query=True`).
- `letta_backend.py::search_memory` — fallback path now calls
  `archival_search(filter=None, query=q, limit=overfetch)` (semantic) instead
  of `archival_list(filter=None)` (chronological).

Live verification (4 distinct queries, Letta 0.16.7): all queries now return
all 3 ancestor entries in semantically-meaningful rank order; sibling entries
do not leak. The same fixture previously returned 0.

#### `science_data.json` robustness
- `_robust_extract_json` strips `<think>…</think>` blocks and ```json fences,
  then walks balanced braces from each candidate `{` and parses each in
  length-descending order. Replaces the legacy greedy `\{.*\}` regex that
  collapsed `{...} prose {...}` into one malformed string.
- On any parse failure, `nodes_to_science_data` writes
  `{checkpoint_dir}/science_data.debug.txt` containing the error and the raw
  LLM response.

#### Source-code budget integrity
- `_collect_source_files` detects binary content by magic bytes (ELF, PE,
  Mach-O, ZIP, gzip, bz2, xz, PNG, JPEG, PDF, numpy `.npy`, pickle), NUL bytes,
  and printable-ratio under 85%. Compiled outputs without an extension
  (e.g. `g++ -o spmm_envelope`) are now rejected before they consume the
  source-extraction budget.
- Source-extension whitelist (`.c .cc .cpp .py .cu .rs .go .ts .js .f90 ...`)
  sorts candidate files first.
- Per-file truncation 8 000 → 16 000 chars; default `max_total` 32 000 → 65 536
  chars; `experiment_summary` truncation 30 000 → 48 000.

#### Plan §-tag parser · stagnation threshold · DAG ordering
- `_extract_plan_sections` now recognises multi-level Markdown headers
  (`### 1) Implementation plan`, `## 2) ...`) with priority over bare-numbered
  prefixes. Falls back to bare numbering when no Markdown headers are present.
- `_run_loop` lineage-decision import (`import json as _json_idea`) lifted to
  function scope; the prior body-scoped import raised `UnboundLocalError` on
  every `root_idea_selection` call in production.
- `lineage_decision.stagnation_threshold` 0.02 → 0.05 (the 0.02 floor sat below
  the LLM-evaluator noise band, so `stagnation_rule` never fired).
- DAG: `finalize_paper` now declares `depends_on: ear_publish` so
  `\codedigest{}` is injected after the manifest digest is finalised.

#### Default workflow.yaml additions
```yaml
plan_promote: index_only          # NEW
lineage_decision:                 # NEW
  mode: stagnation_rule           # off | stagnation_rule | every_node
  stagnation_window: 5
  stagnation_threshold: 0.05
  min_nodes_before_decision: 3
  rate_limit_per_run: 5
root_idea_selection:              # NEW
  enabled: true
```

To revert lineage decisions: set `lineage_decision.mode: off` and
`root_idea_selection.enabled: false`.

### Fixed

#### BFTS child must run real experiments
Production diagnosis: all 9 children inherited their parent's `results.csv` /
`slurm-*.out` / `run.log` byte-for-byte and reported the same numbers from a
single SLURM job — the ReAct agent saw the result files already present and
treated the experiment as already done. Three layers of defense:

- Output-artifact blacklist (`_OUTPUT_BLACKLIST` in `cli.py`): when copying
  parent → child `work_dir`, files matching `results.csv`, `metrics.csv`,
  `run.log`, `slurm-*.out`, `node_report.json`, etc. are skipped. Source /
  scripts / configs / compiled binaries still inherit (no rebuild cost).
- Sterile-node detection: when `compute_files_changed(parent, child)` reports
  `added=0 ∧ modified=0 ∧ deleted=0`, the run loop sets `metrics["_sterile"]=True`,
  clamps `_scientific_score=0.0`, and flags `has_real_data=False`. BFTS prefers
  any non-sterile sibling; the parent-terminate cascade prunes inheritance
  chains where every child is sterile.
- Mandatory-new-artifacts message in the child's first user prompt.

#### `include_ear=False` toggle now actually disables EAR seeding
Production diagnosis: `launch_config.json::include_ear=false` was recorded but
the per-checkpoint `workflow.yaml` had all EAR stages still `enabled=true`, so
`ors_seed_sandbox` populated `repro_sandbox/reproduce.sh` from the EAR bundle
and the Replicator was skipped. Two coupled bugs:

- Bug A: `cli.py::run` did `shutil.copy2(SOURCE, checkpoint/workflow.yaml)`
  unconditionally on every CLI launch, overwriting the rewritten copy that
  `_api_launch` had just written. Fixed: copy only when destination does not
  yet exist.
- Bug B: `core.py::generate_paper_section` resolved `pipeline_yaml_candidates`
  from `Path(config_path).parent` first — `config_path` was the package-source
  `workflow.yaml`, so the per-checkpoint copy was never read. Fixed:
  candidates list now starts with `Path(checkpoint_dir) / workflow.yaml`.
- `_ear_stages` set extended with `ors_seed_sandbox`: when `include_ear=False`,
  the seed stage is also disabled and stripped from
  `ors_build_reproduce.depends_on`.

#### GUI env-var propagation (rubric gen)
`api_experiment.py` had long written wizard ORS settings
(`ARI_RUBRIC_GEN_TARGET_LEAVES`, `ARI_RUBRIC_GEN_TEMPERATURE`) into the
orchestrator's process env, but no consumer read them — the wizard's "Target
leaves" and "Temperature" fields were silent no-ops. `ari-skill-replicate`
now resolves these env vars (plus `ARI_RUBRIC_GEN_TWO_STAGE`) before invoking
the generator. Resolution order: explicit kwarg → env var → default.

#### PaperBench chain hardening (post-§4.1 fixes)
- `task_category` / `finegrained_task_category` hard-pinned to PaperBench's
  closed vocabulary. LLMs invented labels like "Result Visualization" which
  crashed `TaskNode.__post_init__`. Three layers: prompt enumeration,
  deterministic `categories.normalize_rubric_node()`, enum-only JSON schema.
- `generator._extract_json_object` gained a LaTeX-backslash sanitiser
  (`\(`, `\\(...\\)`, `\\texttt{...}` etc. that `json.loads` rejects as
  `Invalid \\escape` are dropped before parsing).
- `litellm.drop_params=True` lets gpt-5* models (which reject `temperature=0`)
  through transparently.
- `extract_build_run_commands` now treats bare variable assignments
  (`CXX=g++`, `CXXFLAGS="..."`) as directives, not build lines.
- `_render_reproduce_sh` falls back to wrapping `code/run_job.sh` when extracted
  build/run are non-substantive.
- Output promotion in fallback wrapper: `code/results.csv` and any
  `*.csv/.pdf/.png/.json/.log` are copied to repo root before `reproduce.sh`
  exits.
- Default `publish.yaml` fallback (`reproduce.sh`, `code/**`, `data/**`,
  `environment.json`) when none is present.
- `fetch_code_bundle` auto-loads `ref` / `sha256` from `publish_record.json`
  when `ref` is empty and `checkpoint_dir` is given.

#### SLURM submission for Phase 1
The v0.6.0 §4.1 rewrite accidentally dropped the v0.5.0 `Executor` abstraction.
Phase 1 was running on the login node — typically without AVX-512 or other
partition-specific ISA — so the BFTS-time binary failed to compile/execute.

- `_run_reproduce_slurm` restored. Submits via `sbatch --wait` using
  `ARI_SLURM_PARTITION` / `ARI_SLURM_CPUS` / `ARI_SLURM_WALLTIME`.
- Spool-relocation guard: writes a tiny wrapper (`{repo_dir}/.slurm_wrap.sh`)
  that `exec bash`'s the user `reproduce.sh` by absolute path so `$0` resolves
  correctly inside the job.
- `_phase1_sandbox_kind()` priority: `slurm → docker → apptainer → singularity
  → local`. SLURM auto-fires when `sbatch` is on PATH and `ARI_SLURM_PARTITION`
  is set.

#### End-to-end ORS chain reliability (2026-05-08 integration polish)
Six independent bugs — each one alone enough to abort the chain — were
discovered and fixed running the chain end-to-end on real hardware against a
CSR-format SpMM paper. The headline improvement: a real 18-minute agent
rollout (`gpt-5-mini`, BasicAgent, 7+ git commits including a Numba JIT
kernel, sweep experiments, roofline model, performance-model refinement) now
scores **9/28 leaves (`ors_score=0.331`, `raw_score=0.321`)** vs 1/37
(`ors_score=0.042`) on the original v0.7.0 cut. Phase 1 executes the produced
`reproduce.sh` on slurm (`exit 0`, all expected artifacts present); Phase 2
SimpleJudge grades against the produced CSV / log / figure outputs.

- **MCP-level timeout was 300 s for tools whose internal budget is
  hours.** ``MCPClient.call_tool``'s default 300 s killed the agent rollout
  mid-flight, then ``MAX_RETRIES=3`` retry hit the ``server.py:222`` skip
  path (because the partial first attempt had already written
  ``reproduce.sh``) and surfaced a misleading ``"skipped"`` envelope to the
  pipeline. Added ``_VERY_SLOW_TOOLS`` tier (13 h) covering
  ``build_reproduce_sh`` / ``run_reproduce`` / ``grade_with_simplejudge``,
  with explicit per-call ``time_limit_sec`` / ``timeout_global_sec`` /
  ``wall_time_sec`` overrides. See `ari-core/ari/mcp/client.py`.
- **`_bypass_docker_sanity_check` patched the wrong namespace.**
  PaperBench's ``solver.py`` does ``from paperbench.solvers.upload import
  upload_heavy_logs`` at module load — early-bound. Patching the source
  module's attribute left ``solver``'s local name untouched, so the
  post-rollout heavy-log upload still ran upstream's
  ``mkdir -p /home/submission`` against the host filesystem and exited 1.
  Bypass now also patches
  ``paperbench.solvers.basicagent.solver`` namespace.
- **Disabled upstream stages cascade-skipped every downstream consumer.**
  ``pipeline.py:1278``'s depends-on check could not distinguish
  "intentionally disabled" (e.g. EAR-off ⇒ ``generate_ear``) from "missing
  / not yet run". Result: a paper rerun with EAR off skipped
  ``write_paper`` → ``finalize_paper`` → ``review_paper`` → every ORS
  stage. Added ``load_disabled_stage_names()`` and threaded a
  ``_disabled_stages`` set through ``run_pipeline`` so disabled deps are
  treated as resolved.
- **`dynamic_axes.py` crashed on dict-shaped `experiment_plan`.** The
  newer ``generate_ideas`` emits structured plans (``{"Design Steps": [...],
  "Ideal Outcomes": "..."}``) but ``plan_to_axes`` ran ``re.search`` on the
  raw value. ``ari paper`` rerun on any project with a structured idea
  failed at ``LLMEvaluator.__init__`` with ``TypeError: expected string or
  bytes-like object, got 'dict'``. Now flattens to JSON when not a string.
- **Rubric tree had ungradeable single-child non-leaves and non-leaves
  carrying leaf-only metadata.** PaperBench's ``SimpleJudge`` only grades
  leaves and rejects non-leaves with ``task_category`` /
  ``finegrained_task_category`` / ``rationale_from_paper``.
  ``_collapse_single_child_chains`` now folds the parent's claim into the
  child (preserving the claim text via ``" — "`` concatenation, retiring
  the wrapper-only weighting layer) and ``_strip_leaf_fields_from_non_leaves``
  is a defensive second pass for LLM-generated violations. Both run before
  ``freeze`` so ``rubric_sha256`` reflects the post-normalization tree.
- **Ari overrode upstream's prompts with an ari-authored "5-minute
  proof-of-concept is fine" license.** That wording was nowhere in
  ``vendor/paperbench`` — it was a deliberate ari design choice that
  small models read as permission to early-submit. Replaced with vendor's
  ``get_instructions`` + ``get_system_message`` verbatim ("Use as much of
  the available time as possible", "Do not stop until you have replicated
  all results from the paper"); added ``_adapt_vendor_paths`` to rewrite
  upstream's ``/home/submission`` / ``/home/paper`` / ``/home/agent.env``
  / ``/home/logs`` references to ari's workspace-flat layout. Rubric-driven
  ``EXPECTED_ARTIFACTS`` is appended (vendor doesn't know about ari's
  rubric tree). The on-disk ``instructions.txt`` becomes a brief stub.
  See `ari-skill-paper-re/src/_replicator_agent.py`.
- **A single huge tool stdout (e.g. printing a NumPy array) tripped
  OpenAI's 10 MB per-string limit and aborted the rollout.** The agent
  occasionally emits multi-megabyte stdout (a 32 MB output observed in
  one rollout). New ``_BoundedOutputTool`` (``Tool`` subclass) caps every
  non-submit tool's ``execute()`` return at ``_MAX_TOOL_OUTPUT_BYTES = 200
  KB`` byte-wise (UTF-8-safe) with an explicit truncation marker that
  tells the agent the original size and suggests follow-up strategies
  (head/tail/grep, redirect to a file then ``read_file_chunk``).
  ``AriPBSolver._get_tools`` wraps the upstream tool list; submit is
  detected by name in ``handle_tool_call`` so its ``execute`` is never
  invoked and stays unwrapped.

### Removed

- `ari-skill-paper-re/src/_replicator.py` (single-shot v0.6 Replicator) —
  `ors_build_reproduce` now exclusively drives the agent solver.
- Dynamic per-run axis-weight tuning (initially proposed, ruled out): would
  break node-to-node score comparability inside the BFTS loop. If revisited,
  it must (a) freeze weights at root, (b) recompute every node's composite when
  weights change, (c) tag scores with a weights version.

### Notes

- `ARI_MODEL_REPLICATE` renamed to `ARI_MODEL_REPLICATOR` (no legacy alias —
  set the new name).
- `ORS_DEFAULTS.judge_n_runs` 3 → 1 (PaperBench paper §4.1 single-pass).
- `ORS_DEFAULTS.phase1_max_runtime_sec` 21 600 → 43 200 (paper §2.2 reproduction
  cap).
- ari-core suite total: 1 906 tests. New: `test_plan_promote.py`,
  `test_lineage_and_inherit.py`, `test_dynamic_axes.py`, `test_virsci_off.py`,
  `test_lineage_decision.py`, `test_root_idea_selector.py`,
  `test_lineage_decision_persistence.py`, `test_node_report.py`,
  `test_node_selection.py`, `test_child_workdir_inherit.py`,
  `test_include_ear_toggle.py`, plus tests in `test_ear.py` and
  `test_search_fallback.py`.


## v0.6.0 (2026-04-26)

Headline: Letta memory backend, rubric-driven paper review, pipeline-driven
`react_driver`, figure-skill consolidation.

### Added

#### Memory backend: Letta replaces the JSONL store
`ari-skill-memory` is now backed by [Letta](https://docs.letta.com)
(ex-MemGPT). The v0.5.x file-based stores — `memory_store.jsonl` and
`~/.ari/global_memory.jsonl` — are **removed entirely**. A portable
`memory_backup.jsonl.gz` snapshot is written inside each checkpoint so
`cp -r checkpoints/foo /elsewhere/ && ari resume` keeps working.

- `ari_skill_memory.backends`: `MemoryBackend` ABC with `LettaBackend` (prod)
  and `InMemoryBackend` (test fake). `server.py` is a thin dispatcher.
- New MCP tool `get_experiment_context()` returns seeded experiment-level
  facts (goal, primary metric, hardware spec) from Letta core memory.
- Removed MCP tools: `add_global_memory`, `search_global_memory`,
  `list_global_memory`. Cross-experiment global memory is no longer a feature
  — stable lessons belong in `experiment.md`, code, or prior papers.
- Copy-on-Write: write-side tools reject `node_id` ≠ `$ARI_CURRENT_NODE_ID`;
  Letta self-edit disabled by default
  (`ARI_MEMORY_LETTA_DISABLE_SELF_EDIT=true`).
- ReAct trace migrated: `FileMemoryClient` → `LettaMemoryClient` (one-line
  swap at `core.py:87`). No more `{checkpoint}/memory.json`.
- Access log: every write/read emits an event to
  `{checkpoint}/memory_access.jsonl` (rotated at
  `ARI_MEMORY_ACCESS_LOG_MAX_MB`, 100 MB default).
- Pipeline enrichment: `pipeline.py` injects each node's memory into
  `nodes_tree.json` (bounded by `ARI_TRANSFORM_MEMORY_MAX_ENTRIES` and
  `ARI_TRANSFORM_MEMORY_MAX_CHARS`).
- New CLI: `ari memory migrate / backup / restore / start-local / stop-local /
  prune-local / compact-access / health`.
- Deployment: `scripts/letta/docker-compose.yml`, `start_singularity.sh`,
  `start_pip.sh`, integrated via `scripts/setup/install_letta.sh`.
- Dashboard: new "Memory (Letta)" settings card; `/api/memory/{health, detect,
  start-local, stop-local}` endpoints; `/api/checkpoint/{id}/memory_access`
  for per-node provenance.
- Design-principle impact: **P2 relaxed for `ari-skill-memory`** (embedding
  retrieval is not bit-reproducible). **P5 scoped**: BFTS *trajectory* may
  differ across re-runs; numerical metrics still reproduce. See
  `docs/PHILOSOPHY.md`.

**Upgrade**: running `ari run` / `ari resume` / `ari viz` on a v0.5.x checkpoint
triggers automatic migration. Source JSONL/JSON files are renamed to
`*.migrated-<ts>` (never re-read). Any `~/.ari/global_memory.jsonl` is detected
at startup but not imported — entries must be manually promoted to
`experiment.md` Rules or committed code.

#### Rubric-driven paper review (AI Scientist v1/v2 compatibility)
- New rubric system (`ari-core/config/reviewer_rubrics/`): 16 bundled YAMLs
  covering ML conferences (`neurips` — default, v2-compatible — `iclr`,
  `icml`, `cvpr`, `acl`), systems/HPC (`sc`, `osdi`, `usenix_security`),
  theory/graphics (`stoc`, `siggraph`), HCI/robotics (`chi`, `icra`),
  and journals/generic (`nature`, `journal_generic`, `workshop`,
  `generic_conference`), plus a built-in `legacy` fallback. Each declares
  `score_dimensions`, `text_sections`, `decision` rules, execution params.
  SHA256 hash per rubric for P2 determinism.
- `ari_skill_paper.review_engine` builds prompts from the rubric, runs a
  self-reflection loop (default 5 rounds, +2% accuracy per Nature Ablation),
  loads few-shot examples (static / dynamic), and normalises output.
- Per-figure VLM feedback (score, issues, suggestions) injected into the
  review prompt as reviewer notes.
- Nature Ablation defaults: `num_reflections=5`, `num_fs_examples=1`,
  `num_reviews_ensemble=1`, `temperature=0.75`, `score_threshold_decision=6`.
- Phase 2 dynamic few-shot: `fewshot_mode: dynamic` triggers OpenReview-based
  similarity retrieval; cache key is `sha256(title+abstract+rubric_hash)`.
  Falls back to static when `openreview-py` is absent.
- CLI: `ari paper --rubric <id> --fewshot-mode static|dynamic
  --num-reviews-ensemble N --num-reflections N`. Env equivalents: `ARI_RUBRIC`,
  `ARI_FEWSHOT_MODE`, `ARI_NUM_REVIEWS_ENSEMBLE`, `ARI_NUM_REFLECTIONS`.
- Few-shot corpus scripts: `scripts/fewshot/sync.py` + `fetch_openreview.py` +
  `fetch_arxiv.py` + `manifest.yaml`.
- GUI: rubric dropdown (dynamically populated from `/api/rubrics`), few-shot
  mode toggle, ensemble size, reflection rounds. `FewshotManager` panel:
  auto-sync, upload (JSON + .txt + PDF), delete. Backed by
  `GET /api/fewshot/<rubric>`, `POST /api/fewshot/<rubric>/sync`,
  `POST /api/fewshot/<rubric>/upload`,
  `POST /api/fewshot/<rubric>/<example>/delete`. All endpoints require the
  rubric to exist in `reviewer_rubrics/`; inputs are stripped of `../` and
  slash characters.

**Breaking**: `review_compiled_paper` output now follows the rubric schema
(`scores`, `score_dimensions`, `decision`, `rubric_hash`, etc.). Set
`ARI_RUBRIC=legacy` or `--rubric legacy` to keep the pre-v0.6.0 JSON shape.

#### Reproducibility ReAct: pipeline-driven `react_driver`
The reproducibility stage no longer hides a private ReAct loop inside
`ari-skill-paper-re`. The loop is owned by `ari-core/ari/agent/react_driver.py`
and driven from `ari-core/ari/pipeline.py` when a stage declares a `react:`
block; the skill is reduced to `extract_repro_config` + `build_repro_report` +
`extract_metric_from_output`.

- `skills[].phase` accepts a list (e.g. `phase: [paper, reproduce]`).
- New phase value `reproduce` scopes the MCP tools exposed to the
  reproducibility agent. Default `workflow.yaml` opts `web-skill`, `vlm-skill`,
  `hpc-skill`, `coding-skill` into `reproduce`. `memory-skill`,
  `transform-skill`, `evaluator-skill` deliberately stay out.
- Sandbox: default `reproducibility_check` stage points at
  `{{checkpoint_dir}}/repro_sandbox/`. `react_driver` rejects tool calls whose
  arguments reference absolute paths outside the sandbox (plus an explicit
  allow-list for the paper `.tex`).
- GUI: Skill Inventory gains a third toggle column **Reproduce** alongside
  BFTS / Paper. React-driver stages render a read-only summary in the Node
  Edit modal (the `react:` block cannot be clobbered from the flow editor).

### Changed

#### Paper review: `review_paper` unified (ensemble + Area Chair folded in)
The separate `review_paper`, `review_paper_ensemble`, `area_chair_meta_review`,
`respond_to_review` stages are collapsed into a single `review_paper`.
`review_compiled_paper` always runs the ensemble path internally (N=1 is a
no-op wrapper; N>1 also runs the Area Chair meta-review). Fixes a pre-existing
bug where the GUI-set `ARI_NUM_REVIEWS_ENSEMBLE` was never read inside the
skill.

- Unified output: `review_report.json` contains `ensemble_reviews[]` and
  `meta_review{}` inline when N>1. `ensemble_reviews.json` and
  `meta_review.json` are no longer emitted.
- N resolution: explicit arg > `$ARI_NUM_REVIEWS_ENSEMBLE` >
  `rubric.params.num_reviews_ensemble` > 1.

#### Figure-skill consolidation: `ari-skill-figure-router` folded into `ari-skill-plot`
`ari-skill-figure-router` was registered as a default skill but never wired
into any pipeline stage; its matplotlib path duplicated
`ari-skill-plot:generate_figures_llm`. Its one unique feature — LLM-generated
SVG architecture diagrams — is merged into `ari-skill-plot`.

- New output contract: the LLM returns one JSON array; each element has
  `kind: "plot"` (matplotlib code) or `kind: "svg"` (self-contained SVG).
- Matplotlib snippets are executed per-figure in isolated subprocesses
  (previously concatenated, so one broken figure killed every output).
  Each snippet receives `output_dir` and `name` pre-defined and must save
  `<name>.pdf` (dpi=150) and `<name>.png` (dpi=200).
- SVG snippets are written to `<name>.svg` and rasterised to `.pdf` + `.png`
  via `cairosvg` (≥2.7, hard dep), with an Inkscape CLI fallback.
- Return shape gains `figure_kinds: {name: "plot"|"svg"}` and
  `errors: [str]` on partial failure. `figures` and `latex_snippets` keys
  preserved byte-compatibly.
- VLM loop drives both plot and svg regeneration via the existing
  `loop_back_to: generate_figures` + `vlm_feedback` mechanism.

**Skill counts**: 15 → 14 (figure-router removed) → 13 after `ari-skill-review`
removal below.

### Removed

- `ari-skill-figure-router/` directory and `figure-router-skill` registration.
- `ari-skill-review` (rebuttal generation): the rebuttal step was not
  load-bearing — the review score is the final quality signal, and a rebuttal
  to our own paper's review added no signal. Associated `ARI_MODEL_REVIEW`
  env var, default-registry entry, and tests removed.
- `letta_llm_config` field on `MemoryConfig`, `LETTA_LLM_CONFIG` env
  propagation, the `llm_config` key in `workflow.yaml`, and the Settings →
  Memory (Letta) "Agent LLM" picker. `ari-skill-memory` only invokes
  `archival_insert` / `archival_search` (embeddings); the chat/messages API is
  never used. `_SdkLettaAdapter._model` is hardcoded to `letta/letta-free`
  (the SDK requires `model=` on `agents.create`, but the value has no runtime
  effect). Embeddings remain configured via `LETTA_EMBEDDING_CONFIG`.

### Notes

Workflow stages removed: `review_paper_ensemble`, `area_chair_meta_review`,
`respond_to_review`. Tests: full new suite under `ari-skill-memory/tests/`
exercising ancestor scope, CoW, access log, ReAct, backup/restore, checkpoint
isolation. New `test_react_driver.py` (14 cases) for sandbox path validation,
ReAct loop final-tool termination, log persistence.


## v0.5.0 (2026-04-15)

Headline: project-scoped settings, container support, Experiment Artifact
Repository (EAR), LaTeX editor, VLM figure review, workflow editor, recursive
sub-experiments.

### Added

#### Container support
- Docker / Singularity / Apptainer auto-detection via `detect_runtime()`
  (prefers Singularity / Apptainer on HPC when `SLURM_JOB_ID` is set).
- New `container:` section in `workflow.yaml` with `mode`
  (`auto/docker/singularity/apptainer/none`), `image`, `pull`
  (`always/on_start/never`).
- Settings page: Container card with mode/image/pull-policy fields and a
  "Detect Runtime" button. Wizard StepResources: container image dropdown.

#### Experiment Artifact Repository (EAR)
- New `generate_ear` MCP tool in `ari-skill-transform` builds a structured
  repository under `<checkpoint>/ear/` with README, code, data, logs,
  reproducibility metadata.
- New pipeline stage `generate_ear` runs after `transform_data`.
- API `GET /api/ear/{run_id}` returns EAR contents.

#### Overleaf-like LaTeX editor (Results page)
- File browser sidebar listing all files in `checkpoint/paper/`.
- Text editor for `.tex` / `.bib` / `.sty` / `.cls`; file upload/delete.
- LaTeX compilation (`pdflatex → bibtex → pdflatex → pdflatex`) triggered from
  the GUI with compile log display. Inline PDF viewer.
- New endpoints: `GET /api/checkpoint/{id}/files`,
  `GET/POST /api/checkpoint/{id}/file`, `POST /api/checkpoint/compile`, etc.

#### VLM figure review loop
- New stage `vlm_review_figures` uses `vlm-skill:review_figure` to visually
  review generated figures.
- `loop_back_to` mechanism in `pipeline.py`: when VLM score < `loop_threshold`
  (0.7), the pipeline rewinds to `generate_figures` with VLM feedback injected
  via `{{vlm_feedback}}`.
- `loop_max_iterations` (default 2) caps regeneration attempts.
- `vlm_review_model` setting (default `openai/gpt-4o`) in Settings and Wizard.

#### Pluggable retrieval backend (AlphaXiv)
- `ARI_RETRIEVAL_BACKEND`: `"semantic_scholar"` (default), `"alphaxiv"`, or
  `"both"` (parallel with deduplication).
- New `search_papers()` and `set_retrieval_backend()` tools in `ari-skill-web`.
- New `retrieval:` section in `workflow.yaml` with `backend` and
  `alphaxiv_endpoint`.

#### React Flow visual workflow editor
- WorkflowPage rewritten using React Flow with draggable DAG nodes and edges.
- Custom `PhaseNode` component shows skill name, tool, available tools, and
  enable/disable toggle.
- Swim-lane layout: BFTS stages on top, paper stages below.
- New `api_workflow.py` with `workflow_yaml_to_flow()` /
  `flow_to_workflow_yaml()` converters.

#### Recursive sub-experiments (Orchestrator)
- `run_experiment` now supports `parent_run_id`, `recursion_depth`,
  `max_recursion_depth`.
- New `list_children` tool returns child runs of a parent.
- Dual transport: stdio (MCP for Claude Desktop) + HTTP (REST + SSE on
  `ARI_ORCHESTRATOR_PORT`, default 9890).
- GUI: `GET /api/sub-experiments`, `POST /api/sub-experiments/launch`. Wizard
  StepScope: `maxRecursionDepth`.

### Changed

#### Project-scoped settings & memory (no more `~/.ari/`)
ARI no longer maintains a global directory under `~/.ari/`. Every config and
memory file lives under the active checkpoint.

- `PathManager.project_settings_path(ckpt)` / `project_memory_path(ckpt)` —
  per-experiment paths. Removed `ari_home()`, `settings_path()`,
  `memory_path()`, `global_settings_path()`.
- `viz/state.set_active_checkpoint(path)` rebinds `_settings_path` to
  `{checkpoint}/settings.json`.
- `_api_save_settings` refuses to write when no project is selected (returns
  400 instead of touching `~/.ari/`).
- `core.build_runtime` requires `checkpoint_dir`; agent memory always goes to
  `{checkpoint}/memory.json`.
- `ari-skill-memory` requires `ARI_CHECKPOINT_DIR` (or explicit
  `ARI_MEMORY_PATH`); raises on startup otherwise.

#### BFTS improvements
- `expand()` now generates exactly **one child per call** (callers re-expand
  with `existing_children` to avoid duplicates).
- Expand prompt includes rich context: sibling scores, ancestor chain, tree
  diversity metrics, already-spawned children.
- New `NodeLabel.OTHER` for LLM-invented labels; `raw_label` preserved in JSON.
- Diversity bonus: `+0.05` for underrepresented labels in `select_next_node()`
  (last 20 runs tracked).
- Score calibration: `_score_history` (up to 15 recent scores) injected into
  evaluation prompt to prevent score collapse.
- Frontier nodes are no longer removed when expanded — stay available for
  re-expansion with `_touched_this_round` / `_failed_this_round` tracking.
- Plan B file copy: all user files from checkpoint dir copied into each node's
  `work_dir`.

#### Skills — new & updated
- New default skills registered: `figure-router-skill`, `benchmark-skill`,
  `review-skill`, `vlm-skill`, `coding-skill` (total 15 skills, 14 default).
- `ari-skill-coding`: new `read_file` with `offset`/`limit` for paginated reads;
  `run_code` / `run_bash` output truncation with informative markers.
- `ari-skill-web`: new `search_papers`, `set_retrieval_backend`,
  `list_uploaded_files`, `read_uploaded_file`.
- `ari-skill-orchestrator`: recursive sub-experiments, dual stdio+HTTP
  transport, `list_children`.

#### Dynamic MCP tool discovery
- `enrich_hints_from_mcp(hints, mcp_tools)` enriches WorkflowHints with
  dynamically discovered MCP tools after `MCPClient.list_tools(phase="bfts")`.
- Grouped "AVAILABLE TOOLS" descriptions injected into the LLM system prompt.

#### Dashboard API additions
- Checkpoint file tree: `GET /api/checkpoint/{id}/filetree`,
  `GET /api/checkpoint/{id}/filecontent`.
- Paper editor: file CRUD, compile, raw file serving with proper MIME types
  (PDF, PNG, JPEG, SVG, EPS) and 20MB limit.
- Upload management: `POST /api/upload/delete`, staging directory under
  `~/.ari/staging/`.
- Auto-append uploaded files to `## Provided Files` section (en/ja/zh
  headers).
- SLURM CPU auto-detection on launch via `sinfo -p <partition>`.

#### Agent loop enhancements
- System prompt lists files already present in `work_dir`
  ("Provided files (ready to use): ...").
- `_args_preview` truncation: 500 → 4000 chars.
- Chinese `提供文件` section header support.
- `ARI_SLURM_CPUS` env var fallback.

### Notes

- New stages: `respond_to_review` (review-skill:generate_rebuttal — outputs
  `rebuttal.json`), `analyze_results` BFTS stage
  (`benchmark-skill:analyze_results`).
- Tests: `test_workflow_contract.py` (867 lines), updated tests across BFTS,
  child node workflow, GUI errors, server, pipeline.


## v0.4.1 (2026-04-08)

### Homepage & docs
- New **Demo** section on the homepage with a top-nav link, hero CTA,
  auto-looping dashboard walkthrough video (en/ja/zh).
- Inline window-style sample paper viewer on the homepage (image-based;
  scroll all 11 PDF pages without leaving).
- New **Prior Work** nav link and `id="inspired"` anchor for the *Inspired By*
  section (AI Scientist v2 / HPC-AutoResearch / VirSci).
- `docs/movie/{en,ja,zh}/ari_dashboard_demo.mp4` and `docs/sample_paper.pdf`
  shipped, referenced from quickstart guides.
- `docs/docs.html` embeds the demo video; links to the sample paper from
  *First Run* / *Experiment Monitor*.

### README
- Language switcher (`README.md` / `README.ja.md` / `README.zh.md`) with a
  Languages bar at the top of each.
- Dashboard demo video embedded inline via `<video>` raw URLs (works on
  github.com).
- `<details>` collapsible scrollable sample paper preview (11 PNG pages).
- *Demonstrated Results* table updated to match the actual sample paper
  (CSR SpMM / *Stoch-Loopline*: 26.22 GFLOP/s, 105.18 GB/s, +3.53 GFLOP/s
  prefetch gain on the `fx700` node) — replaces stale stencil-benchmark
  numbers.
- Test count badge bumped from `60 passed` to `1200+`.

### i18n & assets
- New keys for Demo section, Prior Work nav, sample-paper viewer captions,
  watch-demo CTAs (en/ja/zh).
- `i18n.js` force-`load()` + `play()`s every `<video[autoplay]>` after each
  `innerHTML` replacement (with timed retries for slow preview iframes).
- `docs/images/sample_paper/page-01.png … page-11.png` (110 DPI).


## v0.4.0 (2026-03-31)

### GUI dashboard
- 9-page React/TypeScript SPA built with Vite (`ari/viz/frontend/`): Home,
  Experiments, Live Monitor, Tree + Code Viewer, Results + Paper, Experiment
  Wizard, VirSci Ideas, Workflow Editor, Settings.
- Modular backend API: `api_experiment.py`, `api_state.py`, `api_settings.py`,
  `api_ollama.py`, `api_tools.py`, `api_wizard.py`.
- Real-time experiment log streaming via SSE; WebSocket for live state
  updates; CORS preflight support for SSH tunnels and reverse proxies.
- Production build served from `ari/viz/static/dist/`.

### Environment auto-detection & profiles
- `ari/env_detect.py` auto-detects scheduler (SLURM, PBS, LSF, SGE,
  Kubernetes), container runtime, and SLURM partitions.
- Three profiles: `laptop.yaml`, `hpc.yaml`, `cloud.yaml`. Activated via
  `ari run experiment.md --profile hpc`.

### CLI expansion
- `ari projects` — list checkpoint directories with status.
- `ari show <checkpoint>` — display node tree and review report.
- `ari delete <checkpoint>` — remove a project (with confirmation).
- `ari settings` — view/modify config.
- Intelligent run ID generation: `YYYYMMDDHHMMSS_<semantic_slug>` (LLM-generated
  or content-derived).

### Configuration
- Per-phase model overrides (`ARI_MODEL_IDEA`, `ARI_MODEL_CODING`, ...).
- `phase` field in `SkillConfig` for controlling when skills run.
- Backend determination from `ARI_BACKEND` env var (no model-name guessing).
- Settings persistence to `~/.ari/settings.json`.

### Process management
- PID file management (`ari/pidfile.py`).
- Process group termination via `os.killpg()` with SIGTERM.
- Background checkpoint directory watcher.

### Skills, docs, infrastructure
- All skills now have `skill.yaml` metadata files.
- Full i18n (en/ja/zh) across homepage and docs. New `docs/cli_reference.md`,
  rewritten `docs/quickstart.md`, dashboard screenshots per language.
- `scripts/gpu_ollama_monitor.sh`, `scripts/run_ollama_gpu.sh`, modular
  `scripts/setup/`, `requirements.txt`. Cost tracking improvements
  (`ari/cost_tracker.py`).
- 12+ new test files.


## v0.3.0 (2026-03-21)

### Philosophy
- Removed all domain-specific keywords from production code (`_PERF_KEYWORDS`,
  `OMP_NUM_THREADS` regex, compiler flag regex).
- Node ranking now uses LLM-assigned `scientific_score` (0.0–1.0) instead of
  HPC performance keywords.
- BFTS expansion prompt passes `scientific_score` to child LLM — LLM
  autonomously determines how to improve.

### Evaluator
- `LLMEvaluator` now acts as peer reviewer: assigns `scientific_score` and
  `comparison_found`.
- LLM decides scoring criteria and weights autonomously (no fixed rubric).
- `_scientific_score` and `_comparison_found` stored in node metrics for BFTS
  ranking.

### Transform skill
- Replaced regex-based parameter extraction with LLM-powered full tree
  analysis.
- BFS traversal: all nodes (root → ablation → validation) passed to LLM.
- LLM decides what fields to extract (hardware, methodology, findings, etc.).
- `experiment_context` included in `science_data.json` for downstream skills.

### Plot skill
- Receives full `science_data` including `experiment_context`.
- Figure types chosen autonomously by LLM based on available data.
- Real metric units from data (no "a.u.").

### Pipeline
- `paper_context` = `experiment_context` (from transform) + `best_nodes_metrics`.
- `search_memory` query uses node's own `eval_summary` (not hardcoded HPC
  keywords).
- `eval_summary` now includes `scientific_score` for child node context.

### Docs
- `architecture.md`: updated data flow, design invariants table.
- `PHILOSOPHY.md`: new Zero Domain Knowledge Principle section.
- `configuration.md`: updated for `ARI_MAX_NODES`, template variables.
- `index.html`: added Analyze step, bumped to v0.3.0.
