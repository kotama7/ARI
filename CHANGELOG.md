# Changelog

All notable changes to ARI are documented here. Versions follow `MAJOR.MINOR.PATCH`.

## v0.9.0 — Verified claims end-to-end: S2P gate + mint-once contract + lineage chaining + VirSci-live (2026-06-12)

- **Sample paper replaced with a gate-verified study.**
  `docs/assets/sample_paper.pdf` is now the 8-page CSR SpMM paper
  (store-policy selection across RHS widths + a loopline-guided
  performance model) produced by a run in which ALL declared
  falsifiable claims (12/12) carried machine-verified experiment
  evidence, the computed-evidence chain (model fitting -> held-out
  validation -> model-based selection) was executed via lineage-chained
  tree nodes, and the post-refine semantic review reports zero
  remaining overclaims. Prose hardware references are spec-level only
  (ISA/thread counts); page renders and all README/landing/quickstart
  descriptions updated to match (8 pages).

- **Semantic-review → refiner chain closed.** `merge_reviews` now
  forwards EVERY semantic-review warning to `paper_refine` as an
  advisory revision entry — previously warnings were only counted,
  never sent, so the refine pass could not reduce them. And
  `resolved_overclaim_count` is now the RAW previous−current delta
  (negative = the count GREW after refine); the old value was clamped
  to 0, hiding regressions.

- **`paper_refine` math safety.** The whole-document underscore
  escaping now skips math verbatim — `\( … \)`, `\[ … \]`, and math
  environments (`equation`/`align`/`gather`/…) are left untouched.
  Previously, whenever any edit landed, inline math such as `\(k_p\)`
  was corrupted into a literal-underscore form.

- **Claim-gate numeric parsing understands scientific notation.** The
  numeric-mention scanner (mirrored in
  `ari-skill-paper/src/claim_links.py` and ari-core
  `claim_gate/latex.py`) now parses mantissa × 10^exp forms
  (`x`/`\times`/`\cdot`) and attached e-notation (incl.
  sentence-final), keeps digit-bearing tokens, and treats `\(` / `\)`
  as math delimiters for unit detection — eliminating false
  `numeric_mismatch` findings on values like `4.44 x 10^-16` and on
  values whose unit follows a math delimiter. Overflow-safe: huge
  exponents are skipped instead of crashing the gate.

- **Writer-declaration robustness (parser-side normalization).**
  Instruction-only fixes proved unreliable across real runs, so the
  declaration parser now normalizes what the writer emits: formula
  synonyms (`value`/`raw`/`abs`/…) normalize to the registry name, an
  `operands=` label prefix before bare `k=v` tokens is stripped, and
  anchors that all share ONE id (e.g. every line `% CLAIM:Cw:NCw`)
  are disambiguated per line so each declaration is verified
  independently.

- **Mint-once metric-correctness contract.** `make_metric_spec` now
  returns the persisted claims-bearing
  `{checkpoint}/metric_contract.json` VERBATIM (the response carries
  `contract_frozen: true`) instead of re-extracting — LLM naming is
  not referentially stable, and a mid-run regeneration changed the
  evidence vocabulary, hiding sibling evidence from the exact-match
  gate. Per-node spec fields (scoring guide etc.) are still computed
  per call; scaffold-only contracts (no claims) do not freeze.

- **`check_emission` suggestion-only naming hints.** When an
  uncovered claim's required evidence name lines up lexically with an
  emitted key, the advisory warning adds "your 'X' looks like
  required 'Y' — verify before renaming". Vocabulary-free string
  geometry only (no domain synonym table), with a digit-conflict veto
  (fp32 evidence is never suggested for an fp64 requirement); nothing
  is auto-bound, and the gate never consumes the hint.

- **Lineage chaining** — a new BFTS capability. Claims whose evidence
  is COMPUTED from existing measurements (parameter fitting, held-out
  validation, model-based selection) used to be structurally
  unreachable: children expanded from data-less parents re-ran probes
  instead. Now (a) the expansion-selection hint names the node
  holding the most contract evidence and recommends expanding IT for
  computed-evidence claims (children inherit the parent's working
  directory), and (b) a node whose inherited `work_dir` already
  contains lineage measurements gets an INHERITED DATA note in its
  pinned obligation, listing the files and contract names present
  with the instruction to compute from them and emit under exact
  contract names. Names/files only — values and sibling conclusions
  never flow (fault containment preserved). New helper
  `collect_node_measurement_names` gives per-node attribution of
  emitted measurement names.

- **Platform-aware idea generation.** Verified platform-capability
  constraints (from the run-start probe cache) are folded into the
  idea-generation topic, so plans avoid measurements the platform
  cannot provide. (A private helper briefly exposed as an MCP tool
  was unexposed.)

- **VirSci-live (vendor-wrap) idea engine** in `ari-skill-idea`. An
  opt-in idea-generation path that, when ON, runs VirSci's REAL
  multi-agent mechanism — `Platform.select_coauthors` (freshness team
  formation) + `Team.generate_idea` (multi-agent deliberation) from the
  vendored, UNEDITED `vendor/virsci` — grounded on a LIVE Semantic
  Scholar snapshot (corpus + SPECTER2 cosine retrieval index + author
  profiles + co-author graph), in place of the lightweight re-implemented
  discussion loop. **Default OFF** = behaviour unchanged; on missing deps
  or any runtime error the skill DEGRADES back to the re-impl loop. The
  `idea.json` contract is identical either way; the path taken is
  reported in `idea.json` `virsci_integration_status`
  (`real_wrap` vs `reimpl: ...`). A single live snapshot only — no
  era-split / no paper-parity (those are VirSci's retrospective-benchmark
  artifacts, deliberately out of scope); freshness/diversity come from
  the S2 author profiles + co-author graph, and the LLM-selected metric
  is unchanged.
  - **Enable** via `ARI_IDEA_VIRSCI_REAL=1`, the CLI `--virsci-live`
    flag (`ari run`), or the GUI experiment-wizard "VirSci live" toggle.
  - **Env contract** (only the toggle is required; the rest are tunable,
    defaults in parentheses): `ARI_IDEA_VIRSCI_REAL` (unset/off) toggle
    the real vendor-wrap path; `ARI_IDEA_VIRSCI_K` (7) discussion turns
    (vendor `group_max_discuss_iteration`); `ARI_IDEA_VIRSCI_TEAM_SIZE`
    (3) max team members (vendor `max_teammember`);
    `ARI_IDEA_VIRSCI_N_AUTHORS` (16) author pool for `select_coauthors`;
    `ARI_IDEA_VIRSCI_N_PAPERS` (800) SPECTER2 retrieval corpus size;
    `ARI_IDEA_VIRSCI_MAX_TEAMS` (= `n_ideas`) cap on teams driven through
    `generate_idea`; `ARI_IDEA_VIRSCI_SPECTER2_MODEL`
    (`allenai/specter2_base`) local query embedder.
  - **CLI** (`ari run`): `--virsci-live` / `--no-virsci-live`,
    `--virsci-k`, `--virsci-team-size`, `--virsci-n-authors`,
    `--virsci-n-papers`.
  - **GUI**: experiment-wizard "VirSci live" toggle + numeric fields on
    the Scope/Resources step; the choice is persisted to
    `launch_config.json` and restored on GUI re-run.
  - **LLM**: the deliberation LLM follows the existing per-phase Idea
    model (`ARI_MODEL_IDEA`); engine calls route through litellm so
    ARI's cost_tracker captures them.
  - **Deps**: a new `virsci` pip extra (`faiss-cpu`, `transformers`,
    `torch`, `loguru`, `sqlalchemy`); SPECTER2 weights are fetched at
    runtime; needs `SEMANTIC_SCHOLAR_API_KEY` / `S2_API_KEY` (for
    `embedding.specter_v2`) and an OpenAI-compatible LLM endpoint (the
    ARI CLI shim). When the extra is absent the skill degrades to
    re-impl. Canonical spec: `ari-skill-idea/REQUIREMENTS.md`
    (§VirSci-live).
  - **Fail-loud snapshot grounding.** `build_snapshot` (`snapshot.py`)
    now raises on a 0-paper corpus so a throttled / empty Semantic
    Scholar fetch degrades visibly to the re-impl loop instead of
    silently writing a "successful" ungrounded `real_wrap`; it never
    reuses a cached `n_papers==0` manifest (a poisoned cache from a
    prior failed build), and it recovers an empty / throttled (`429`)
    topic search via a `/paper/batch` seed corpus, recorded as
    `seed_fallback` in `snapshot_manifest.json`.

- **Verifiable research-memory layer** (`ari-skill-memory`). A typed,
  sha256-provenanced, ancestor-scoped memory derived from
  `node_report.json`. Nine new MCP tools — `add_experiment_result`,
  `add_failure_case`, `add_procedure_memory`, `add_reflection`,
  `add_reproducibility_event`, `search_research_memory`,
  `get_verified_context`, `audit_memory`, `consolidate_node_memory`.
  Node-end typed consolidation + paper verified-context are now
  **DEFAULT-ON** (env `ARI_MEMORY_CONSOLIDATE`; `0`/`false`/`no`/`off`
  to disable), flipping the prior opt-in default. A deterministic
  per-ancestor working context is injected at node start (replacing the
  old 800-char one-shot semantic pre-seed), and a best-lineage
  `verified_context.json` grounds the paper's quantitative claims.
  `archival_list` is paginated (removes the 200-passage ceiling), the
  standalone auditor re-hashes referenced artifacts, and
  ancestor-inheritance reads are logged to `memory_access.jsonl`.

- **Story2Proposal (S2P) claim-evidence loop** wired into the paper
  pipeline, default-on in `warn` (report-only) mode. Adds a top-level
  `claim_gate_policy` block in `workflow.yaml` + env
  `ARI_CLAIM_GATE_MODE` (`off`/`warn`/`strict`) and
  `ARI_COMPARISON_SCOPE` (`any`/`same_environment`). Four new MCP tools
  — `claim_evidence_hard_gate`, `evidence_grounded_semantic_review`
  (`ari-skill-evaluator`), `link_paper_claims`, `paper_refine`
  (`ari-skill-paper`). `claims[]` / `numeric_assertions[]` are grafted
  onto `science_data.json`; the paper tail (`ear_publish` → `finalize`)
  is replaced by the full dependency-ordered generate-evaluate-adapt
  loop, and `finalize_paper` now depends on the FINAL hard gate. New
  `ari.public.claim_gate` / `ari.public.verified_context` re-exports.

- **Idea-owned metric-correctness contract** that BLOCKS the final
  paper on objectively-false / unverified / unmeasured-mechanism claims
  even in `warn` mode. A declared `metric_contract` is built and
  persisted to `{checkpoint}/metric_contract.json` by `make_metric_spec`,
  grafted onto `science_data.metric_contract` by
  `nodes_to_science_data`, and enforced by the deterministic hard gate.
  The finding types `placeholder_denominator`, `recompute_mismatch`,
  `invariant_violation`, `correctness_failed` / `correctness_uncovered`,
  `claim_evidence_missing`, and `ceiling_unmeasured` — plus a
  universal-invariant registry — are now in `always_block_on`.
  `emit_results` gains an optional `provenance` arg (→ `_provenance`);
  `configurations[*]._provenance` / `results.json` `_provenance` are
  unioned; and a new `evaluation_criteria.falsifiable_claims` idea field
  feeds the gate.

- **Exploration + lineage.** Opt-in live web search during BFTS via
  `bfts.allow_web` (env `ARI_BFTS_ALLOW_WEB`) — default-off keeps the
  trajectory reproducible; when on, ARI writes
  `bfts_web_provenance.json` (`trajectory_reproducible=false`) and
  surfaces a caveat. Lineage stagnation now DETERMINISTICALLY pivots
  (`switch_to_idea`) to the strongest unused runner-up idea, deferring
  to the LLM judge only when budget / recursion is exhausted or no
  unused alternative remains. The selected idea is seeded into root core
  memory + injected into every node's working context; the LLM
  evaluator merges `results.json` measurements directly (sets
  `has_real_data`).

- **Paper output quality.** `generate_figures_llm` (`ari-skill-plot`)
  now mandates layout quality in its prompt (`fig.tight_layout()`,
  `savefig(bbox_inches='tight')`, legend OUTSIDE the axes, rotated long
  tick labels — overlapping / truncated figures are REJECTED) and
  comparability (no juxtaposing values on different scales without an
  axis or annotation); instruction-only. `paper_refine`
  (`ari-skill-paper`) now applies suggested revisions in three steps —
  deterministic quoted substitutions, then a bounded 3-pass LLM
  find/replace loop, then a mechanical verify — and returns the new
  `refine_passes`, `deterministic_substitutions`, and
  `unaddressed_substitutions` fields.

## v0.8.1 — Structural refactor: frontend decomposition, stable skill contract, internal-boundary docs (2026-06-01)

A **behavior-preserving** refactoring release — the full 15-requirement
`refactoring/` task-control program, executed and then retired. No runtime
behavior, API, endpoint, MCP-tool, or rendered-output change: structure only.
Every moved unit is byte-identical modulo `export`/`import`/prop-sourcing, and
the high-risk frontend state extractions were adversarially verified by
multi-agent review (JSX byte-identity, hook/helper fidelity, container wiring).

- **Frontend dashboard decomposition.** The six largest React page components
  were split into thin containers + extracted presentational subcomponents,
  data hooks, and pure helpers — no visual or behavioral change:
  - `ResultsPage.tsx` **3177 → 462** lines — `EarSection` + `useEAR` hook,
    `PaperWorkspace`, `resultSections`/`resultTypes`/`resultHelpers`, and
    `renderContext`/`renderFigures`/`renderReviewScores`/`renderRepro`
    render-helpers.
  - `DetailPanel.tsx` **938 → 425** — `useDetailPanelData` hook, five per-tab
    subcomponents (`Trace`/`Code`/`Memory`/`Access`/`Report`Tab), and a pure
    `computeAncestorIds` helper.
  - `WorkflowPage`, `StepResources`, `SettingsPage`, `MonitorPage` similarly
    thinned into sibling section/constant modules.
- **Stable skill → core contract.** `ari-skill-*` packages now depend only on
  the stable `ari.public.*` surface (new `ari.public.run_env`); private-core
  imports were migrated to a public-first `try/except` pattern or explicitly
  allow-listed. Enforced by a new guard test
  (`ari-core/tests/test_skill_public_contract.py`).
- **viz server seams.** Experiment process-control extracted out of
  `routes.py`; the viz API ⇄ backend schema reconciled and pinned by a contract
  guard test; legacy node-tree resolution fixed
  (`tree.json → nodes_tree.json → node_*/tree.json`) so legacy checkpoints
  render node counts in the list + summary cards; `.env`-write upsert
  consolidated into one quote-preserving helper (guarded by
  `test_env_write_quoting.py`).
- **Documentation.** New
  [`docs/reference/internal_boundaries.md`](docs/reference/internal_boundaries.md)
  consolidates the LLM, OS/scheduler/container, and two-engine orchestration
  boundaries plus their concurrency hazards; durable findings from the refactor
  audits were folded into `docs/` (glossary, configuration, public_api,
  rest_api, architecture). The disposable `refactoring/` scaffold was removed in
  the final cleanup.

Tests: `bash scripts/run_all_tests.sh` green (incl. the new public-contract and
schema guards); the viz frontend typechecks, builds, and passes `vitest` at the
prior baseline (the 2 pre-existing brittle PaperBench `getByDisplayValue` tests
remain the only failures, unchanged).

## v0.8.0 — PaperBench env-truth + bridge contract + BFTS configurable evaluation (2026-05-21)

Major release that promotes the v0.7.3 "Unreleased" PaperBench work to
a numbered milestone and adds two follow-on streams: (1) **env-truth**
guardrails (verify-before-scaffold, language-choice counter-priming,
truthful ADDITIONAL NOTES, Phase-2 isolation + network claims) that
keep the Stage 1 agent honest about what the host actually provides,
and (2) **configurable BFTS evaluation layers** (composite formula,
axis-set source, frontier-score strategy, LLM selection prompts) that
let users swap any of four BFTS surfaces without forking the orchestrator.

Highlights:

- **PaperBench 3-stage bridge contract** (`rollout_submission` /
  `reproduce_submission` / `judge_submission`) — the protocol-faithful
  replacement for the retracted Step 4 reproduction-package generator.
- **`container_image` end-to-end** from wizard → API worker → MCP tools
  → sandbox runner, with `pb-env` / `pb-reproducer` aliases.
- **Fail-loud preconditions** on sandbox / GPU mismatches (four
  silent-downgrade sites now raise `RuntimeError` by default).
- **`code_only` Stage 1 ↔ Stage 3 consistency** so the judge stops
  zero-grading Code Execution / Result Analysis leaves the agent was
  never asked to attempt.
- **Env-truth follow-ons**: verify-before-scaffold (Stage 1 probes the
  host before claiming binaries exist), language-choice counter-prime
  (LLM is told *not* to default to one language without reason),
  truthful ADDITIONAL NOTES (Phase-2 isolation + Network claims
  auto-detected per host), orphan `tool_call` filter on the vendor
  Responses API converter, Stage 1 default `code_only=False` so the
  agent actually writes `reproduce.sh`.
- **Configurable BFTS evaluation layers** in `default.yaml`:
  `evaluator.composite` (harmonic / arithmetic / weighted_min /
  geometric), `evaluator.axis_mode` + `evaluator.custom_axes` (dynamic
  / legacy / custom), `bfts.frontier_score` (scientific_plus_diversity /
  scientific_only / depth_penalized / ucb_like), and
  `bfts.select_prompt` + `bfts.expand_select_prompt` keys for the
  selection LLM. Defaults reproduce the prior behaviour exactly.
- **Reviewer rubrics**: ships seven journal-/conference-style reviewer
  rubrics out of the box (`aer.yaml`, `ahr.yaml`, `apsr.yaml`,
  `econometrica.yaml`, `philreview.yaml`, `pmla.yaml`, `qje.yaml`)
  under `ari-core/config/reviewer_rubrics/`.
- **Documentation refresh**: `docs/howto/`, `docs/reference/`,
  `docs/index.html`, the `docs/i18n/` strings, the report chapters
  (en/ja/zh), and the three READMEs all updated for the v0.8.0
  surface.

### Added

- **PaperBench env-truth guardrails** (post-bridge follow-ons).
  Five complementary fixes prevent the Stage 1 agent from
  hallucinating host capabilities in the instruction prompt:
    - **Verify-first / probe-before-scaffold.** Stage 1's planning
      prompt now explicitly tells the agent *probe the environment
      with `which` / `ls` before claiming a binary exists*; the
      `reproduce.sh` scaffold begins with a `command -v` audit so
      missing dependencies surface as an early hard failure rather
      than a mid-run silent fallback.
    - **Counter-prime language choice (multi-lang).** The vendor
      Python-default bias is offset by an explicit instruction
      asking the agent to inspect the paper's repo for the
      *actually-used* language (R / Julia / C++ / Stata) and to
      avoid Python-bias when the artefacts are non-Python.
    - **Truthful ADDITIONAL NOTES with auto-detected env.** The
      `ADDITIONAL NOTES` block injected into the agent's prompt
      is now generated per-host from a live probe (binaries
      present, package managers, GPU, network reachability) rather
      than from a static template; what the agent reads matches
      what the host can do.
    - **Phase-2 isolation + Network claims.** The notes block adds
      a Network-reachability claim and a Phase 2 isolation contract
      (network-off / FS-read-only / no-host-mount) consistent with
      the vendor reproducer container.
    - **Stage 1 default `code_only=False`.** Promotes
      `reproduce.sh` from "nice to have" to "agent contract": the
      default mode now expects the agent to write the script, so
      Stage 2 has something to execute. Stage 1 code-only mode is
      still available via explicit opt-in.
    - **Orphan `tool_call` filter on vendor Responses API
      converter.** Prevents the converter from emitting a stray
      `tool_call` without a matching `tool_result`, a pattern that
      otherwise caused vendor PaperBench's Responses → ChatCompletions
      adapter to drop the next agent turn.

- **Vendor paper-codebase blacklist lifted to ARI surface + CLI gate
  hook.** The vendor `paperbench/data/papers/<id>/blacklist.txt`
  pattern is no longer per-paper-only; the bridge accepts an explicit
  `blacklist_urls` list, the CLI exposes a gate hook so callers can
  inject project-level rules, and the rule is enforced via two
  layers (Markdown `FORBIDDEN URLS / RESOURCES` block + the
  `ARI_BLACKLIST_URLS` env var read by downstream tool wrappers).

- **Seven journal/conference reviewer rubrics** shipped under
  `ari-core/config/reviewer_rubrics/`: `aer.yaml` (American Economic
  Review), `ahr.yaml` (American Historical Review), `apsr.yaml`
  (American Political Science Review), `econometrica.yaml`,
  `philreview.yaml` (Philosophical Review), `pmla.yaml` (PMLA),
  `qje.yaml` (Quarterly Journal of Economics). Selected via
  `reviewer_rubric: <slug>` in the launch config — same plumbing as
  the existing `sc`/`neurips`/`nature` rubrics.

- **PaperBench 3-stage bridge contract** in
  `ari-skill-paper-re/src/_paperbench_bridge.py`. Three keyword-only
  async callables (`rollout_submission` / `reproduce_submission` /
  `judge_submission`) expose vendor PaperBench's Agent Rollout →
  Reproduction → Grading protocol with a shared
  `(paper_md, work_dir-or-submission_dir, model, ...)` calling
  vocabulary so callers can sequence the three stages without
  translating between independent argument shapes. Stage 1 wraps
  the existing `_replicator_agent.run_replicator_agent` (vendor
  BasicAgent / IterativeAgent), Stage 2 wraps `server.run_reproduce`
  (host docker / apptainer / slurm / local dispatch), and Stage 3
  wraps vendor `SimpleJudge` directly. Exposed via the dogfood CLI
  (`scripts/sc_paper_dogfood.py --with-rollout / --with-reproduction`),
  mutually exclusive with `--paper-audit-mode`.

- **`container_image` end-to-end pipeline (wizard → API → worker →
  MCP tool → sandbox runner).** Wizard's Reproduce step gains a
  `container_image` field (SIF path, `docker://` URI, `image:tag`,
  or short alias `pb-env` / `pb-reproducer`); `api_paperbench_worker`
  threads it through both Stage 1 and Stage 2 args; both
  `build_reproduce_sh` and `run_reproduce` MCP tools accept it;
  `_run_reproduce_docker` and `_run_reproduce_apptainer` honour the
  explicit value over the legacy env-var fallback. The vendor
  `pb-env` / `pb-reproducer` aliases resolve to `image:latest`
  tags built by the new `scripts/build_pb_images.sh` wrapper around
  `vendor/.../scripts/build-docker-images.sh`.

- **Fail-loud preconditions for sandbox / GPU mismatches** in
  `ari-skill-paper-re/src/server.py`. Four sites previously silently
  downgraded user-requested isolation/resources to host-CPU
  execution:
    1. `sandbox_kind=docker` with no docker daemon
    2. `sandbox_kind=apptainer`/`singularity` with missing binary
    3. `sandbox_kind=slurm` with missing sbatch or no resolvable
       partition
    4. SLURM GPU request with GRES-less cluster
  All four now raise `RuntimeError` with an actionable message by
  default. Legacy silent-fallback paths are preserved behind two
  opt-in env vars (`ARI_PHASE1_ALLOW_FALLBACK=1` and
  `ARI_SLURM_ALLOW_NO_GRES=1`), both documented in
  `scripts/setup/setup_env.sh` and covered by the
  `test_setup_env` regression check. Stage 1 `sandbox_kind=slurm`
  emits a one-shot WARNING on `LocalComputer` construction making
  the host-filesystem execution contract explicit.

- **SLURM GPU dispatch correctness fixes** (real-cluster smoke
  findings on r340 / qc-a100 / ai-l40s):
    - `--gpus-per-task` now auto-pairs with `--ntasks 1` when
      neither `ntasks` nor `--gpus` is supplied (SLURM 24.05
      rejects the lone `--gpus-per-task` form).
    - Mixing typed and untyped GPU requests is now canonicalised
      to typed-only when `gpu_type` is set (vendor SLURM 24.05
      rejects the mixed form with `Invalid GRES specification
      (with and without type identification)`). Untyped
      `--gpus-per-task` / `--gpus-per-node` are dropped; only
      `--gres=gpu:TYPE:N` is emitted.

- **`code_only` consistency between Stage 1 and Stage 3**. ARI's
  Stage 1 instruction template defaults to `code_only=True` (per
  `_compute/local_pbtask.py:166-175`), but the Stage 3 judge was
  previously grading the full rubric, so the vendor SimpleJudge's
  `reproduce.sh failed to modify or create any files. All result
  analysis tasks will be graded as 0` safeguard fired on every
  Code Execution / Result Analysis leaf, penalising the agent for
  work it was never asked to do. `_paperbench_bridge.judge_submission`
  now accepts `code_only: bool = False` and applies vendor
  `TaskNode.code_only()` pruning when True (mirror of
  `paperbench/grade.py:109-112`). `server.grade_with_simplejudge`
  auto-enables `code_only` when `repo_dir` has no `reproduce.log`.
  Mutually exclusive with `paper_audit_mode`.

- **`web_search_preview` tool preservation** in the bridge's
  `OpenAIResponsesTurnCompleterConfig` construction. Previously,
  threading the caller's `agent_model` silently dropped the
  vendor `BasicAgentSolver.completer_config` default
  `tools=[WebSearchToolParam(type="web_search_preview")]`. Without
  this, IterativeAgent mode degraded to bash + read-file only
  (the vendor strips PythonTool / SearchFile in iterative mode
  per `solver.py:88-95`). Both `_paperbench_bridge.rollout_submission`
  and `server.build_reproduce_sh` now explicitly pass
  `tools=[WebSearchToolParam(...)]` to preserve the vendor default.

- **Vendor-fidelity gaps closed in `_paperbench_bridge.py`**:
    - **(a) Stage 2 salvage retries** —
      `reproduce_submission(salvage_retries: int = 0,
      retry_threshold_sec: int = 60)`. Mirrors
      vendor `paperbench/reproduce.py:252
      reproduce_on_computer_with_salvaging`: early-failure
      attempts (exit non-zero AND elapsed < threshold) are retried
      up to N times with a Python 3.11 venv prelude wrapping the
      original `reproduce.sh`. The salvage wrapper backs up the
      original to `reproduce.sh.pre_salvage` and restores it on
      cleanup. Total wall-clock budget is tracked across attempts
      (retry-time exclusion, mirror of vendor's `use_real_time_limit`
      at Stage 1) so a salvage chain never overshoots the user's
      `time_limit_sec`.
    - **(b) `submission_executed_<UTC>.tar.gz` capture** —
      `reproduce_submission(capture_tarball: bool = True,
      tarball_dir: Path | None = None)`. Per-attempt timestamped
      tarball alongside the submission dir mirrors vendor
      `reproduce.py:230-244`. The path is returned as
      `executed_tarball` in the result dict for downstream
      provenance / re-grading.
    - **(h) `agent.env` injection** —
      `rollout_submission(agent_env_path: Path | None = None)`.
      Loads a vendor-style `KEY=VALUE` file and merges into the
      agent's env (explicit `env=` kwarg wins). When unset,
      auto-discovers `$ARI_AGENT_ENV_PATH` then
      `~/.ari/agent.env`. The calling process's `HF_TOKEN` is
      automatically forwarded (mirror of vendor
      `nano/eval.py:172-179` well-known-credential pattern).
      `setup.sh` gains a 5th interactive prompt for `HF_TOKEN`
      and a commented `ARI_AGENT_ENV_PATH` placeholder; the
      regression test `test_prompts_only_for_critical_keys` is
      updated accordingly.
    - **(i) Stage 1 host-FS source-removal guard** —
      `rollout_submission(forbid_host_filesystem: bool = False)`.
      When True and the effective `sandbox_kind` resolves to
      `local` or `slurm` (both run the agent's bash/python
      directly on the host filesystem with no isolation), the
      call raises `RuntimeError` with an actionable message
      pointing at `sandbox_kind=apptainer` + `container_image`.
      Default False preserves dogfood / dev workflows.
    - **(g) Blacklist URL enforcement** —
      `rollout_submission(blacklist_urls: list[str] | None = None)`.
      Two-layer best-effort enforcement: (1) prepends a
      `FORBIDDEN URLS / RESOURCES` Markdown section to the agent's
      paper_md so the LLM's instruction prompt carries the rule,
      and (2) exports `ARI_BLACKLIST_URLS` env var (newline-joined)
      so downstream tool wrappers can refuse. Mirrors vendor
      `data/papers/<id>/blacklist.txt`. Apptainer + `no_network`
      remains the only hard guarantee; this is the agent-instruction
      / env-flag layer that lets the wizard / CLI surface the rule
      without per-paper registry plumbing.
    - **(e) pb-env / pb-reproducer image plumbing** —
      `scripts/build_pb_images.sh` (ARI-root wrapper around
      `vendor/paperbench/project/paperbench/paperbench/scripts/build-docker-images.sh`)
      with docker-daemon availability checks and actionable error
      messages; bridge `_resolve_container_image_alias` maps the
      short aliases `pb-env` / `pb-reproducer` to the canonical
      `image:latest` tags the build script produces (URIs / paths
      / arbitrary tags pass through verbatim, so user-supplied
      images keep working). Both rollout_submission and
      reproduce_submission resolve `container_image` through this
      helper.

- **Documentation refresh for v0.7.3 surface**. Updated
  `docs/howto/paperbench_quickstart.md`, `paperbench_gui.md`,
  `paperbench_troubleshooting.md` (+ ja/zh mirrors) and
  `docs/reference/api_paperbench.md`,
  `docs/reference/environment_variables.md`,
  `docs/reference/mcp_tools.md` with: container_image wizard
  field, fail-loud preconditions + opt-in env vars, Stage 1→2→3
  full CLI flow via the bridge, code_only auto-enable,
  HF_TOKEN / agent.env auto-discovery, salvage retries,
  executed-submission tarballs. `docs/index.html` + i18n
  descriptions refreshed to mention the 3-stage bridge contract
  (replacing stale `reproduce_plan + verification code + simulated
  log` text from the retracted Step 4 path). `report/{en,ja,zh}/
  chapters/04_paper_pipeline.tex` gains a `\subsubsection*{3-stage
  bridge contract (v0.7.3)}` enumerating the eight vendor-faithful
  design choices with vendor source-line citations; PDFs rebuilt
  (EN/JA 13 pages, ZH 14 pages).

### Fixed

- **Operational v0.8.0 dogfood pass (SC41406 cuSZ-i, lossy-compression
  kernel).** The deferred full-rollout PaperBench pass on a real
  Supercomputing-2024 target was run (Stage 1→2→3 against `gpt-5-mini` on
  an R-CCS L40S node) and surfaced + validated four bridge corrections.
  Mean replication score rose **1.2% → 11.1%** on the same target after
  the fixes.
    - **Reproduce / judge now run from the agent's real repository
      root.** The rollout workspace rewrites the vendor's absolute
      `/home/submission` to a relative `submission/`, so an agent whose
      cwd is the workspace builds its self-contained repo under
      `<workspace>/submission/`. The post-rollout promote step had copied
      only `reproduce.sh` up to the workspace root, orphaning it from its
      `src/`; Stage 2 then ran the orphan and every CUDA build failed with
      `src/…: No such file or directory`, zeroing all Code Execution /
      Result Analysis leaves. `reproduce_submission` / `judge_submission`
      now resolve the nested repository root (where `reproduce.sh` is
      co-located with the sources it references — matching the vendor
      reproducer's cd-into-submission semantics) and ignore the orphan
      copy.
    - **`apply_patch` / `applypatch` provided in the no-container
      sandbox.** The vendor Docker image installs `/bin/apply_patch`; the
      host-side `LocalComputer` builds no such image, so a gpt-5/codex
      agent's reflexive `apply_patch <<'PATCH' … PATCH` edits died with
      `command not found` and drained tool-call budget before falling back
      to heredoc. `LocalComputer` now mirrors the vendor setup, exposing
      the vendor's own `apply_patch.py` on PATH (both command names) for
      every agent command; degrades gracefully if the vendor module is
      unimportable.
    - **Paper-kind classifier prompt de-leaked.** The classifier's
      example values had seeded the dogfood paper's own names (`cuSZ`,
      `Miranda`, `SDRBench`), violating the paper-agnostic contract and
      self-fulfillingly biasing the classifier output. Replaced with
      neutral cross-domain examples so extractions are genuine
      paper-reading.
    - **Toy-example dependency line switches per detected environment.**
      The vendor toy `reproduce.sh` shows `apt-get install`; on a no-apt
      module cluster that primed a failing path. The env reconcile now
      rewrites it to `module load <NAME>` / `pip install` under the
      detected environment (left verbatim where apt is real; Docker
      grading untouched).
- **Documentation + report refresh for the v0.8.0 dogfood pass.** Updated
  `docs/guides/paperbench/paperbench_troubleshooting.md` (+ ja/zh mirrors)
  and `docs/reference/api_paperbench.md` (en bridge-contract section; the
  ja/zh reference files are abbreviated and carry no bridge section) with
  the nested repository-root resolution and the sandbox-provided
  `apply_patch` command; `report/{en,ja,zh}/chapters/05_evaluation.tex` records the
  lossy-compression replication result (real Miranda-slice fetch, native
  CUDA interpolation kernels on the L40S, PSNR 50–90 dB across an
  error-bound sweep) and notes two residual agent-behavioural limits —
  voluntary early submission well inside the time budget, and a
  compute-then-discard reporting gap in the agent's own code that omitted
  its GPU-predicted metric — as distinct from the (now-fixed) bridge
  bugs.

### Removed

- **Step 4 "reproduction-package generator" — RETRACTED as
  off-protocol** (also documented in the v0.7.2 retraction note
  below). An earlier entry in this release shipped
  `generate_reproduce_plan` (MCP tool +
  `reproduce_plan.py` + `prompts/reproduce_plan.md` +
  `--with-reproduce-plan` flag in `scripts/sc_paper_dogfood.py` +
  `prompt_overrides.reproduce_plan_hint` blocks in
  `paperbench_rubrics/{sc,neurips,nature}.yaml`). It asked an LLM
  to write a `reproduce.log` whose "observed" values were
  transcribed verbatim from the paper's own tables/figures and
  fed that to `SimpleJudge` as the submission, bypassing
  PaperBench's Stage 2 (executed submission via vendor
  agent + container runner). The previously-claimed audit score
  of **0.857** on the SC24 paper is retracted; an empty
  submission (the protocol-correct input when no reproduction is
  performed) scores far lower. The entire code path has been
  removed; the legitimate alternative is the bridge contract
  above (`rollout_submission → reproduce_submission → judge_submission`)
  driving a real Stage 1 agent + Stage 2 sandbox execution.

- **`workflow.yaml` `apptainer_image: ''` legacy alias** in the
  `ors_build_reproduce` stage. Replaced with the unified
  `container_image: ''` field. Symmetrically added
  `container_image: ''` to the `ors_run_reproduce` stage so the
  `ari paper` CLI path matches the wizard / worker dispatch
  shape. Runtime impact is zero (both stages still pass empty
  values for env-var fallback), but the YAML now documents the
  canonical parameter name.

- **Configurable BFTS evaluation layers (4 layers).** `default.yaml`
  now lets users pick from multiple options at each evaluation surface
  in the BFTS pipeline. Defaults reproduce the prior behaviour exactly,
  so unmodified configs are a no-op.
  - `evaluator.composite` — formula collapsing per-axis judge scores
    into `_scientific_score`: `harmonic_mean` (default), `arithmetic_mean`,
    `weighted_min` (bottleneck), or `geometric_mean`.
  - `evaluator.axis_mode` + `evaluator.custom_axes` — axis set sent
    to the judge LLM: `dynamic` (default; rubric + plan keywords),
    `legacy` (the canonical 5-axis set), or `custom` (verbatim list).
  - `bfts.frontier_score` — deterministic fallback ranking strategy:
    `scientific_plus_diversity` (default), `scientific_only`,
    `depth_penalized` (with `bfts.depth_penalty_lambda`), or
    `ucb_like` (with `bfts.ucb_c`).
  - `bfts.select_prompt` / `bfts.expand_select_prompt` —
    `FilesystemPromptLoader` keys for the two LLM selection prompts;
    user-supplied templates must keep the same placeholder set.
  - Full reference: `docs/configuration.md` § BFTS Evaluation Layers
    (mirrored under `docs/ja/` and `docs/zh/`).

## v0.7.3 — macOS local-dev compat + .env hierarchy alignment (2026-05-18)

Patch release that incorporates the external contributor work from
PR #25 (waka320, "macOS local-dev compat") with a documentation /
implementation alignment pass on top. No vendor changes; no behaviour
change for HPC / Linux deployments beyond the .env loading fix
described below.

### Added

- **Repo `.env` is now loaded by the `ari` CLI on import** following
  the 4-tier priority already documented in `docs/cli_reference.md`
  (and already implemented by the viz API in
  `ari/viz/api_settings.py` and `ari/viz/api_experiment.py`):
  `$ARI_CHECKPOINT_DIR/.env` → `$ARI_ROOT/.env` →
  `$ARI_ROOT/ari-core/.env` → `~/.env`. `override=False` keeps shell
  exports authoritative; higher-priority files win on conflicts
  (python-dotenv first-set-wins). Previously `ari run` silently fell
  through to packaged `workflow.yaml` defaults when users forgot to
  `source .env`, while `docker compose` was reading the same file
  for Letta.
- **PEP 668 / Homebrew-Python safe install path**: `scripts/setup/`
  now creates and uses `$ARI_ROOT/.venv` instead of relying on
  `pip install --user`. The PATH hint surfaced by `verify.sh` and
  `banner.sh` switched from `~/.local/bin` to `$ARI_ROOT/.venv/bin`
  (a comment for the `pip install --user` path is retained).
- **Letta Postgres ships pgvector by default**:
  `scripts/letta/docker-compose.yml` now uses
  `pgvector/pgvector:pg16` with `scripts/letta/pg-init/01-vector.sql`
  enabling the `vector` extension on first volume init. Adds a
  `pg_isready` healthcheck and `depends_on: condition: service_healthy`
  so `letta` does not race the DB. Fixes `type "vector" does not exist`
  on fresh `ari memory start-local`.
- **`install_letta.sh` waits up to 120 s** (was 60 s) for Letta
  readiness — first-boot Postgres init on slow disks routinely
  exceeded the old budget.
- **`install_paperbench.sh` survives a missing `git-lfs`** by
  injecting `filter.lfs.*=` overrides + `GIT_LFS_SKIP_SMUDGE=1` for
  the submodule checkout, and detects an incomplete prior checkout
  (`pyproject.toml` missing) before retrying.
- **`ari run` prints a docs pointer** when the experiment file
  argument doesn't exist (points to `docs/experiment_file.md`).

### Changed

- **`scripts/setup/`** is now portable across BSD `grep` / Bash 3.2
  (macOS default) and GNU `grep` / Bash 5.x (Linux):
  `detect_env.sh` swaps `grep -P` for POSIX `grep -oE`,
  `install_letta.sh` replaces `${PROMPT,,}` with `tr '[:upper:]' '[:lower:]'`,
  `spinner.sh` drops `local -n` (Bash 4.3+ nameref) in favour of
  `eval`-based array indirection.
- **`docs/reference/environment_variables.md`** now lists the
  actually supported `ARI_MEMORY_BACKEND` values (`letta` and
  `in_memory`). The previously documented `file` / `local` strings
  were never accepted by
  `ari-skill-memory/src/ari_skill_memory/config.py`'s validator.
- **`ari-skill-memory` skips `nest_asyncio.apply()` on Python 3.14+**
  to avoid an `AttributeError` in FastMCP/anyio's event-loop glue.
  The stdio FastMCP transport does not rely on nested-loop patching
  on 3.14.

### Removed

- **`examples/starter_experiment.md` and the `examples/` directory.**
  ARI has no `examples/` convention historically (templates live
  under `ari-skill-paper/templates/`, samples under
  `docs/images/sample_paper/`), and `docs/experiment_file.md`
  already carries a richer "Minimal Example" (the SpMM roofline
  prompt). The useful content has been folded into
  `docs/experiment_file.md` (en / ja / zh) as an explicit
  "smoke test" framing, and `scripts/setup/banner.sh` now points
  users at that doc. The starter's `ARI_MEMORY_BACKEND=in_memory`
  workaround was intentionally not migrated — `in_memory` is
  test-only per the validator in
  `ari-skill-memory/src/ari_skill_memory/config.py:82-86`.

### Version bumps

- `ari-core`: 0.7.2 → 0.7.3
- READMEs (en / ja / zh): badge v0.7.1 → v0.7.3 (had drifted two
  releases behind)
- `docs/i18n/{en,ja,zh}.js` footer: v0.7.2 → v0.7.3

### Credit

PR #25 by Waka.Y (waka320) — macOS local-dev compat groundwork
(cherry-picked verbatim as `chore(macos): bootstrap repo .env in CLI
+ local dev ergonomics`). Subsequent docs-alignment commits in
v0.7.3 are by the maintainer.

## v0.7.2 — Paper-audit extensions (2026-05-17)

This extends the original v0.7.2 release (2026-05-13, below) with the
**audit-side companion** to the agent-side execution_profile work.
The agent-side answers *"can an AI agent reproduce this paper?"*; the
audit-side, driven by an HPC PaperBench reproducibility-audit research
plan, inverts the framing to ask *"does this paper describe enough to
be reproducible?"*. Both pipelines share the same vendored PaperBench
rubric formalism (`\Rubric`, `score(P) = Σ wᵢ judgeᵢ(P)`); the audit
side is a pure ARI wrapper layer with **zero vendor changes**.

### Removed

- **Step 4 "reproduction-package generator" — RETRACTED as off-protocol.**
  An earlier entry in this release shipped `generate_reproduce_plan`
  (MCP tool + `reproduce_plan.py` + `prompts/reproduce_plan.md` +
  `--with-reproduce-plan` flag in `scripts/sc_paper_dogfood.py` +
  `prompt_overrides.reproduce_plan_hint` blocks in
  `paperbench_rubrics/{sc,neurips,nature}.yaml`). It asked an LLM to
  write a `reproduce.log` whose "observed" values were transcribed
  verbatim from the paper's own tables/figures, then fed that to
  `SimpleJudge` as the submission. PaperBench's 3-stage protocol
  (vendor README) requires Step 2 — actually executing the agent's
  submitted codebase in a GPU container to produce an _executed
  submission_ — before grading; skipping Step 2 and substituting
  paper-paraphrased text produces an inflated score that is not
  comparable to PaperBench leaderboard numbers. The previously-claimed
  audit score of **0.857** on the SC24 paper is hereby **retracted**;
  the same paper with an empty submission (the protocol-correct input
  for "no reproduction was performed") scores far lower. The entire
  code path has been removed. Re-introducing automated submission
  generation will require wiring vendor PaperBench's
  `IterativeAgent` / `BasicAgent` + Alcatraz container runner so the
  log comes from real execution.

### Added

- **3-stage PaperBench bridge contract** in
  `ari-skill-paper-re/src/_paperbench_bridge.py`. Adds two new
  keyword-only async functions —
  `rollout_submission(*, paper_md, work_dir, agent_model, sandbox_kind,
  container_image, iterative_agent, time_limit_sec, ...)` (Stage 1,
  agent rollout that writes reproduce.sh) and
  `reproduce_submission(*, submission_dir, sandbox_kind, container_image,
  partition, gpus_per_task, gpu_type, memory_gb_per_node, exclusive,
  extra_sbatch_args, time_limit_sec)` (Stage 2, executes reproduce.sh
  in the chosen sandbox and captures reproduce.log) — that mirror the
  call style of the existing `judge_submission` (Stage 3). All three
  share the same `(paper_md, work_dir-or-submission_dir, model, ...)`
  vocabulary so a caller can sequence the protocol-correct PaperBench
  3-stage pipeline (rollout → reproduce → judge) without translating
  between independent argument shapes. Internally, Stage 1 calls
  `_replicator_agent.run_replicator_agent` and Stage 2 calls
  `server.run_reproduce`; the bridge centralises completer-picking
  (OpenAI Responses for `gpt-*`/`o[1-5]-*`, LiteLLM otherwise) and
  adds `executed_submission_dir` / `reproduce_log_path` keys to the
  Stage 2 return dict so the Stage 3 judge can be chained directly.
  This is the legitimate counterpart to the retracted Step 4 "fake
  reproduce.log" generator (above) — the submission fed to the judge
  comes from REAL agent rollout + REAL reproduce.sh execution.
  Exposed via `scripts/sc_paper_dogfood.py --with-rollout` /
  `--with-reproduction` (mutually exclusive with `--paper-audit-mode`
  by construction). `server.run_reproduce` now tolerates `rubric_path=""`
  so the bridge wrapper can drive it without a rubric file when the
  caller supplies all hints via explicit args.

- **`container_image` field end-to-end** (wizard → API → worker →
  MCP tool → sandbox runner). Adds a unified container image
  parameter to the PaperBench wizard's Reproduce step
  (`ari-core/ari/viz/frontend/src/components/PaperBench/PaperBenchWizard.tsx`)
  with i18n labels for en/ja/zh. Propagates through
  `api_paperbench_worker.py` (`_build_reproduce_args` accepts both
  `container_image` and the legacy `apptainer_image` alias;
  `_run_reproduce_args` reads `container_image`),
  `server.build_reproduce_sh` (Stage 1; same dual-arg accept), and
  `server.run_reproduce` + `_run_reproduce_docker` /
  `_run_reproduce_apptainer` (Stage 2; explicit `image` arg replaces
  the previous env-var-only path). Image priority: explicit field →
  env (`ARI_PHASE1_DOCKER_IMAGE` / `ARI_PHASE1_APPTAINER_IMAGE`) →
  hardcoded fallback (`ubuntu:24.04`). Previously, a user picking
  `sandbox_kind=docker` or `apptainer` in the wizard always got
  `ubuntu:24.04` regardless of what they intended; the wizard had no
  UI for the field, the worker code looked for a key the wizard
  never populated, and Stage 2 ignored the (always-empty) value.
  `workflow.yaml` updated symmetrically for the `ari paper` CLI
  path (`ors_build_reproduce` / `ors_run_reproduce` inputs).

- **Fail-loud preconditions for sandbox / GPU mismatches** in
  `ari-skill-paper-re/src/server.py`. Four sites previously silently
  downgraded user-requested isolation/resources to host-CPU execution
  with only a warning log: (a) `sandbox_kind=docker` with no docker
  daemon → fell back to local; (b) `sandbox_kind=apptainer` /
  `singularity` with missing binary → same; (c) `sandbox_kind=slurm`
  with missing sbatch or no resolvable partition → same; (d) SLURM
  with GPU request but GRES-less cluster → dropped all
  `--gres` / `--gpus-per-task` / `--gpus-per-node` flags. All four
  now raise `RuntimeError` with an actionable message by default
  (the user explicitly picked the sandbox/GPU; silently running on
  host-CPU after a long queue wait is the worst possible failure
  mode). Legacy silent-fallback behaviour preserved behind two
  opt-in env vars documented in `scripts/setup/setup_env.sh`:
  `ARI_PHASE1_ALLOW_FALLBACK=1` for the docker/apptainer/sbatch
  cases, `ARI_SLURM_ALLOW_NO_GRES=1` for the GPU GRES case. Stage 1
  `sandbox_kind=slurm`/`local` additionally emits a one-shot WARNING
  at `LocalComputer` construction making the host-filesystem
  execution contract explicit (the agent's bash/python tools run as
  plain subprocesses against `work_dir` — pass `sandbox_kind=apptainer`
  with `container_image=...` for true Stage 1 isolation).

- **Multimodal markdown image expander** in
  `ari-skill-paper-re/src/_litellm_completer.py`. When `paper.md`
  is produced by `pymupdf4llm.to_markdown(write_images=True)` it carries
  `![](images/img-N.png)` references that point at PNG files on disk.
  The expander walks each outgoing message and, where these references
  appear in plain-string content, rewrites the content into OpenAI
  multimodal content blocks (`[{type:text}, {type:image_url}, ...]`)
  before the LiteLLM call. Vendor `SimpleJudge` is unchanged — it
  still sees `paper_md` as a text Path and embeds it verbatim into a
  text-only prompt; the multimodal translation happens at the LiteLLM
  boundary. Toggleable via `ARI_MULTIMODAL_PAPER` (default on) with a
  per-message image cap via `ARI_MULTIMODAL_MAX_IMAGES` (default 20)
  to bound token budget. Eliminates the need for AI-Scientist-v2's
  separate VLM-review pipeline by leveraging unified vision-capable
  judge models (Claude 4.6/4.7, GPT-5, Gemini 2.5).

- **pymupdf4llm-based PDF parser** in `scripts/sc_paper_dogfood.py`
  (with three-tier fallback: `pymupdf4llm → pymupdf → pdftotext`).
  Produces markdown that preserves table structure as Markdown tables
  and exports figures as PNGs with `![](path)` references that the
  multimodal expander above can resolve. `--image-size-limit` /
  `--image-dpi` / `--max-images` CLI flags expose the relevant knobs;
  `--paper-extras PATH [PATH ...]` concatenates additional PDFs
  (typically AD/AE Appendices) into the main paper.md so
  the audit research plan's hypothesis 2 (paper-only vs +AD+AE)
  can be tested directly. Added `pymupdf4llm>=0.0.10` to both
  `ari-skill-replicate` and `ari-skill-paper-re` dependencies.

- **paper_audit mode for `judge_submission`** in
  `ari-skill-paper-re/src/_paperbench_bridge.py`. When
  `paper_audit_mode=True`, the vendor PaperBench `TASK_CATEGORY_QUESTIONS`
  (which asks "did the submission do X?" — see
  `vendor/paperbench/.../judge/simple.py`) is monkey-patched at call
  scope to paper-audit-flavored questions ("does the paper describe X
  with concrete specificity?"). The override is restored on exit so
  agent-benchmark calls in the same process are unaffected. Removes
  the structural ceiling that capped paper_audit mean score around 0.3
  even with AD/AE concat. Vendor unchanged.

- **Symmetric author/reviewer venue conditioning for paper writing**
  (`ari-skill-paper`). The `Rubric` dataclass gains an `author_hint`
  field that mirrors the existing `system_hint`: where `system_hint`
  is injected into peer-review prompts by `review_engine.py:80`,
  `author_hint` is now injected into paper-drafting prompts by
  `server.py::generate_section` via a dedicated
  `══ VENUE-SPECIFIC AUTHOR GUIDANCE ══` block. The previous weak
  one-line "Target venue: X. Page limit: N pages" append remains as
  a baseline so venues without an `author_hint` (and ad-hoc venues
  like `arxiv`/`icpp`/`isc`/`acm` without a `reviewer_rubrics` YAML)
  are unchanged. SC's and NeurIPS's `reviewer_rubrics` YAMLs now
  ship calibrated `author_hint` blocks; the other 13 venues remain
  empty and can be filled in incrementally.

- **Venue-conditioned PaperBench rubric templates** mirroring the existing
  `ari-core/config/reviewer_rubrics/` pattern. Templates live as YAML
  files under `ari-core/config/paperbench_rubrics/<id>.yaml` and select
  either the original `agent_benchmark` framing (one direct child per
  contribution, leaves grade submission output) or a new `paper_audit`
  framing (fixed direct children declared in `top_level_axes`, leaves
  grade paper descriptiveness). `ari-skill-replicate/src/generator.py`
  gains an optional `paperbench_rubric_id` argument that loads the
  template and injects `prompt_overrides.system_hint` /
  `prompt_overrides.leaf_style` into the bundled skeleton and subtree
  prompts via new `{VENUE_HINT}` placeholders. ARI core remains
  domain-agnostic; venue knowledge lives in config-only YAML.
  Shipped templates:
    - `generic.yaml` (back-compat — bundled prompts verbatim);
    - `sc.yaml` — six audit axes from
      the HPC PaperBench audit research plan's §5 Step 3
      (environment / data / execution / figures / scaling / conclusion);
    - `neurips.yaml` — NeurIPS Reproducibility Checklist axes (claims /
      setup / code-data / statistics / ethics / figures);
    - `nature.yaml` — Nature Reporting Summary axes (materials / protocol
      / statistics / data / ethics) for wet-lab papers.
  `scripts/sc_paper_dogfood.py` gains `--rubric-template <id>` for the
  audit dogfood loop. Adding a new venue requires only a YAML file —
  no code change. Validated against cuSZ-i (sc24-00019.pdf): direct
  children come out as the exact six SC axes with calibrated weights
  (2/2/2/2/3/1), and leaf phrasing flips from "the implementation
  does X" (agent_benchmark) to "X is identifiable in the paper or AD"
  (paper_audit). Trilingual docs updated in lockstep:
  `docs/{reference/rubric_schema.md,reference/mcp_tools.md,reference/environment_variables.md,howto/paperbench_quickstart.md,skills.md,configuration.md}`
  with `docs/{ja,zh}/` mirrors, and `report/{en,ja,zh}/chapters/04_paper_pipeline.tex`
  §4.2 ("Rubric formalism") gains a "Venue-conditioned rubric templates"
  subsection describing the agent_benchmark / paper_audit dichotomy.

## v0.7.2 (2026-05-13)

### Acceptance keywords (PLAN deletion gates)

The five PLAN docs under
`{ari-skill-replicate,ari-skill-paper-re,ari-core,report,docs}/PLAN*.md`
each require a specific exact-phrase entry in this changelog before
they can be `git rm`'d. Recorded here verbatim:

- **v0.7.2 — rubric reproduce_contract.execution_profile added.**
  Schema, generator skeleton prompt, single-call adversarial prompt,
  generator code path, schema-validation tests, generator round-trip
  tests, real-LLM smoke against sc24-00052 (`kind:"mpi"`) and
  sc24-00079 (field omitted) — all main-merged.
- **v0.7.2 — paper-re agent prompt now consumes rubric.execution_profile.**
  Full LLM agent rollouts on SC24 papers (TS-SpGEMM /cuSZ-i / Parallax
  multi-node, smoke #2/#3/#5) require a 12 h budget per paper and
  remain operational follow-ups for v0.7.3; see
  `ari-skill-paper-re/PLAN_MPI_EXIT.md` §5 for that residue. The
  end-to-end prompt assembly is verified deterministically against the
  real sc24-00052 rubric (`/tmp/agent_prompt_smoke_result.json`,
  10/10 checks pass), the regression-free single-CPU rollout
  (sc24-00079, gpt-5-mini, 60 s) is recorded in
  `/tmp/agent_full_smoke_result.json`, and the real-SLURM 15-flag
  dispatch is recorded in `/tmp/slurm_smoke_result.json`.
- **v0.7.2 — GUI for paper import + PaperBench run.**
  Eleven HTTP endpoints in `ari-core/ari/viz/api_paperbench.py`,
  React surface under `frontend/src/components/PaperBench/`,
  trilingual i18n, vitest component tests, arXiv auto-fetch,
  Server-Sent Events log stream, audit-report download.
- **v0.7.2 — PaperBench audit report generator (trilingual).**
  `report/scripts/paperbench_report.py` renders per-paper and
  multi-paper audit reports as LaTeX → PDF (XeLaTeX with HaranoAji /
  Fandol for ja / zh) + HTML + Markdown via pandoc, with the
  rubric-tree, score-distribution and leaf-score-heatmap figures
  embedded.
- **v0.7.2 — PaperBench documentation suite (en/ja/zh).**
  Nine canonical English documents under `docs/howto/` and
  `docs/reference/`, each with ja and zh mirrors of equivalent length
  (quickstart + execution-profile-reference fully translated;
  remaining seven document pairs at parity).

Headline: **PaperBench BasicAgent gains full HPC execution access**.
A new `reproduce_contract.execution_profile` block carries parallel-
execution requirements (MPI ranks, GPU type, exclusivity, NUMA bindings,
module loads) from the rubric all the way through to the Phase 2 sbatch
command. `ari-skill-paper-re.run_reproduce` now emits 15 + escape-hatch
SLURM flags driven by that block, the BasicAgent prompt gains an
`EXECUTION PROFILE` + `CLUSTER SHAPE` + `COMPUTE-NODE EXECUTION
CONVENTIONS` appendix so the agent generates multi-node `srun` /
`mpirun` reproduce.sh scripts, and a GUI surface (`📚 PaperBench` /
paper registry / 5-step run wizard with execution_profile override) is
added to the dashboard. **No vendor changes.** Backward compatible:
legacy single-CPU papers without `execution_profile` produce the same
4-flag sbatch and same agent prompt as before.

### Backend — `ari-skill-replicate`

- `schemas/replication_rubric.schema.json` v3: `reproduce_contract`
  gains optional `execution_profile` with 21 fields covering kind
  (`cpu_single` / `gpu_single` / `gpu_multi` / `mpi` / `mpi_gpu`),
  rank/node counts, SLURM placement (`requested_nodes`,
  `ntasks_per_node`, `requested_nodelist`, `exclude_nodes`),
  exclusivity, GPU type, memory, NUMA bindings (`constraint`,
  `cpu_bind`, `mem_bind`, `hint`), `module_loads`, `metric_columns`,
  `result_aggregation`, `accepts_reduced_scale`, and an
  `extra_sbatch_args` escape hatch. Existing rubrics validate
  unchanged.
- `prompts/skeleton.md` extended with extraction guidance so the
  generator populates `execution_profile` when the paper specifies
  parallel-execution properties (HPC papers, large-ML training, sharded
  DB tests).
- README documents the new fields with HPC / GPU-single / single-CPU
  examples + the full SLURM flag mapping.

### Backend — `ari-skill-paper-re`

- `_replicator_agent.py::run_replicator_agent` accepts an
  `execution_profile` dict and forwards it through `LocalPBTask` so the
  agent's user message gains an `EXECUTION PROFILE` JSON block + a live
  `CLUSTER SHAPE` snapshot (`SLURM_JOB_NUM_NODES` / `SLURM_NTASKS` /
  `nvidia-smi`) + a `COMPUTE-NODE EXECUTION CONVENTIONS` footer (L1–L7
  from PLAN: shared FS, srun-first, conda activation, module loads,
  multi-node fan-out, timeout wrapping). The appendix builder
  (`_format_hpc_appendix`) returns the empty string when nothing
  applies — legacy papers retain byte-identical prompts.
- New `prompts/mpi_aggregate_skel.py`: a rank-0 CSV aggregation
  skeleton auto-copied into `submission/mpi_aggregate.py` whenever
  `execution_profile.kind ∈ {mpi, mpi_gpu}`.
- `server.py::run_reproduce` gains 15 + escape-hatch SLURM args:
  `nodes`, `ntasks`, `ntasks_per_node`, `nodelist`, `exclude_nodes`,
  `exclusive`, `gpus_per_task`, `gpus_per_node`, `gpu_type`,
  `memory_gb_per_node`, `memory_gb_per_cpu`, `constraint`, `cpu_bind`,
  `mem_bind`, `hint`, `extra_sbatch_args`. Caller args left at the
  default auto-resolve from the rubric's `execution_profile`
  (explicit caller arg always wins).
- New runtime safety probes: `_is_shared_fs(repo_dir)` warns when the
  checkpoint lives on a node-local FS, `_slurm_has_gres()` silently
  drops `--gres=gpu:<type>:N` when `sinfo` reports no GRES (keeping
  `--gpus-per-task`), preventing job rejection on GRES-less clusters.

### GUI — `ari-core/ari/viz`

- New `api_paperbench.py` (10 endpoints) backed by a paper registry at
  `~/.ari/paper_registry/` (`ARI_PAPER_REGISTRY_DIR` override). License
  classifier maps free-form license strings to a structured `usable /
  permissive / modifiable / redistributable` assessment so the import
  dialog can colour the badge green for MIT / Apache / BSD / CC0 / CC
  BY / CC BY-SA / arXiv non-exclusive.
- Dispatch wired into `routes.py` (GET `/api/paperbench/papers`,
  `/.../license`, `/run/<id>`, `/run/<id>/results`; POST
  `/.../import`, `/.../delete`, `/.../metadata`, `/run`,
  `/cost-estimate`).
- New React surface under `frontend/src/components/PaperBench/`:
  `PaperRegistryPage`, `PaperImportDialog`, `PaperBenchWizard` (5-step
  flow with the **execution_profile override** form exposing all 16
  SLURM fields). Sidebar gains a `📚 PaperBench` entry.
- i18n: full en/ja/zh keys for the new surface.

### Report — `report/scripts/paperbench_report.py`

- New `generate_paper_report` + `generate_summary_report` Python +
  CLI APIs that consume an ARI checkpoint and emit a per-paper
  audit report (LaTeX source + figures via matplotlib) plus a
  multi-paper summary. Templates live under
  `report/audit/.template/`; the Makefile gains `audit-report` and
  `audit-summary` targets. ja/zh mirrors are deferred to the
  existing `report/scripts/translate.py` lang-sync pass.

### Documentation

- New canonical English docs: `docs/howto/paperbench_quickstart.md`,
  `paper_import.md`, `paperbench_gui.md`, `multi_node_setup.md`,
  `compute_node_safety.md`, `paperbench_troubleshooting.md`;
  `docs/reference/execution_profile.md`, `rubric_schema.md`,
  `api_paperbench.md`. Each has a ja/zh mirror (quickstart +
  execution_profile are full translations; the rest are concise stubs
  with links back to the canonical English).
- `docs/skills.md` updated to reference the new `execution_profile`
  pathway in both paper-re and replicate sections.

### Tests

- `ari-skill-replicate`: +8 schema tests covering each new field +
  rejection cases; +3 generator tests verifying execution_profile
  round-trips through freeze.
- `ari-skill-paper-re`: +18 tests covering the HPC prompt appendix
  builder, cluster shape detection, MPI skeleton injection, 15 new
  sbatch flags (S1–S11), GRES gating, and shared-FS heuristic.
- `ari-skill-paper-re`: +1 new `tests/test_mpi_aggregate_skel.py`
  verifying the rank-0 CSV header + fallback path.
- `ari-core`: +29 tests in `tests/test_api_paperbench.py` covering
  license classification, paper_id normalization, registry CRUD, run
  launch, cost estimate, and manifest persistence.
- `report`: +10 tests in `report/scripts/test_paperbench_report.py`
  covering LaTeX escaping, harvest from synthetic checkpoint,
  recommendation heuristics, and per-paper + summary rendering.
- `ari-core/tests/test_setup_env.py` clean — new env vars
  (`ARI_PAPER_REGISTRY_DIR`, SLURM auto-set vars referenced by the
  agent) documented in `scripts/setup/setup_env.sh`.

### 4th sprint — full PDF + CJK + heatmap + glossary lang-sync (PLAN 4 closed)

- **Per-leaf pass/fail heatmap** (`_figure_leaf_score_heatmap`):
  matplotlib visualization with task_category rows and 0/1 pass/fail
  cells (red / green), grouped in canonical PaperBench order
  (Code Development / Code Execution / Result Analysis). Falls back to
  synthesizing cells from `category_pass` aggregate counts when
  per-leaf grade data is unavailable. Embedded in chapter 04 of every
  audit report. Three regression tests cover the active / fallback /
  empty paths.
- **CJK lang-sync without LLM** — replaces TR8's deferred
  LLM-translation pipeline with a deterministic glossary-substitution
  pass (`_apply_glossary`) that swaps every canonical English fixed
  string in the rendered LaTeX for the matching ja/zh entry from
  `report/shared/i18n.json`. Combined with a per-language XeLaTeX
  preamble injector (`_inject_lang_preamble`) that loads xeCJK +
  HaranoAji (ja) / Fandol (zh) from TinyTeX, the audit report now
  produces actual CJK-typeset PDFs without burning API spend on
  per-paragraph LLM translation.
- **Inlined audit-report templates**: the seven LaTeX templates that
  drive the audit report (`main.tex` + six chapter sources)
  previously lived under `report/audit/.template/`, leaking
  machine-generated helper files into `report/` (which is otherwise
  reserved for the hand-written ARI research paper). They are now
  inlined as Python string constants in `paperbench_report.py`
  (`_TMPL_MAIN`, `_CHAPTER_TEMPLATES`); the `.template/` directory is
  removed. `render_template()` accepts either a `Path` (legacy) or a
  raw string body so the rendering pipeline stays unchanged.
- **Real PDF build verification** against a synthetic checkpoint,
  2026-05-13 (TinyTeX + XeLaTeX, /home/t-kotama):
  - en: 7 pages, 90 KB, all 3 figures embedded.
  - ja: 7 pages, 134 KB, pdftohtml extracted 論文メタデータ /
    ルーブリック / カテゴリ内訳 / 実行プロファイル.
  - zh: 7 pages, 151 KB, pdftohtml extracted 论文元数据 / 评分单 /
    类别分布 / 执行配置 / 再现尝试 / 沙箱 / 审稿建议.
- **Fixed latent template bug discovered by the PDF smoke**: the
  hard-coded path `replication_rubric.schema.json` in
  `02_rubric.tex.tmpl` contained a literal `_` that XeLaTeX
  interpreted as a math subscript outside `\texttt{}`-protected
  scopes, causing build to bail with "Missing $ inserted" before the
  glossary or figures could render. Escaped to `replication\_rubric`.

### Real-smoke results + latent bugs fixed (3rd sprint)

- **Real-LLM rubric smoke** against sc24-00052 (TS-SpGEMM) and
  sc24-00079 (Parallax) via gpt-5-mini, 2026-05-13:
  - TS-SpGEMM rubric correctly populated
    `execution_profile = {kind: "mpi", paper_max_ranks: 65536,
    paper_max_nodes: 512, result_aggregation: "rank0_csv",
    metric_columns: ["method","nodes","processes","runtime_sec",
    "comm_bytes","nnz"], accepts_reduced_scale: true}`
    → PLAN_MPI_EXIT/replicate §5#3 acceptance verified.
  - Parallax (CPU-only paper) correctly omitted `execution_profile`
    entirely → PLAN_MPI_EXIT/replicate §5#4 acceptance verified.
  - **Fixed latent bug discovered by the smoke**: the
    single-call rubric prompt (`adversarial_reviewer.md`, used when
    `two_stage=False`) was missing the v0.7.2 `execution_profile`
    instructions, silently dropping the HPC pathway. Added the
    extraction guidance + a regression test
    (`test_single_call_prompt_also_includes_execution_profile_guidance`).
- **Real-SLURM sbatch smoke** against sx40 partition, 2026-05-13:
  sbatch accepted the new 15+1 flag invocation (`exit_code=0`,
  SLURM_NTASKS / SLURM_JOB_NUM_NODES surfaced to compute node),
  `extra_sbatch_args=['--no-requeue']` pass-through worked.
  - **Fixed 2 latent bugs discovered by the smoke**:
    1. `_slurm_has_gres()` was only dropping `--gres=gpu:<type>:N` on
       GRES-less clusters but `--gpus-per-task` / `--gpus-per-node`
       are equally GRES-bound and equally rejected with "Invalid
       generic resource specification". Extended the gating to drop
       all three. Regression test:
       `test_gpu_flags_all_dropped_when_cluster_has_no_gres`.
    2. `--cpu-bind` / `--mem-bind` are documented srun-only flags on
       many SLURM versions (incl. sx40) and produced
       "unrecognized option" errors at sbatch time. Added a new
       `_sbatch_supports()` runtime probe that reads
       `sbatch --help` once and silently drops these flags when
       unsupported, with a warning routing them to `extra_sbatch_args`
       or `srun --cpu-bind` inside reproduce.sh. Regression test:
       `test_cpu_bind_dropped_when_sbatch_does_not_support_it`.

### Additional GUI / report features landed in this release

- **arXiv DOI auto-fetch** (`GET /api/paperbench/arxiv/<id>`): paste an
  arXiv ID into the import dialog, click "↓ Fetch metadata" and the
  title / authors / year / license fields auto-populate from the public
  arXiv Atom API. Legacy (cs.LG/0102030) and new-style (2404.14193v2)
  identifiers both accepted.
- **SSE log streaming** (`GET /api/paperbench/run/<id>/logs`): the
  Results page subscribes to a Server-Sent Events stream and renders
  the live agent log (color-coded by level) while the job is in
  flight. Backed by an in-memory per-job log buffer (capped at 2000
  entries) populated via `api_paperbench.append_job_log()`.
- **Rubric tree figure** (`_figure_rubric_tree`): `paperbench_report.py`
  emits the rubric TaskNode tree as a graphviz-rendered PDF when `dot`
  is on PATH, with leaf nodes coloured green and a synthetic
  `(truncated, N more)` sink when the tree exceeds the configured
  `max_nodes` ceiling.
- **pandoc HTML / Markdown output**: when pandoc is available, the
  audit report renderer additionally emits `main.html` (mathjax + toc)
  and `main.md` per language alongside the LaTeX/PDF artifacts.
- **`GET /api/paperbench/run/<id>/report`**: triggers / re-fetches a
  paperbench_report run for the completed job and returns a
  `download_urls` map keyed by `<lang>/<fmt>`.
- **GUI Results page** (`PaperBench/results/ResultsView.tsx`):
  colour-coded rubric tree (pass = green, fail = red, weight badge),
  per-category pass-rate table, negative-control summary, live SSE
  logs while running, and a per-language "Download report" group
  (en/ja/zh × pdf/html/md).
- **`report/shared/i18n.json`**: trilingual glossary fixing terminology
  for report titles, field labels, category names, kind values, and
  recommendation phrases so the lang-sync pass produces consistent
  translations.
- **Frontend test infrastructure**: Vitest + @testing-library/react +
  jsdom configured under `ari-core/ari/viz/frontend/` with two
  PaperBench component tests covering the license badge,
  arXiv auto-fetch, and the Step 3 → launch round-trip for the
  execution_profile override form. Run via `npm install && npm test`.

### Deferred to v0.7.3 (out of scope for this release)

- End-to-end smoke against real PaperBench SC24 papers (TS-SpGEMM,
  cuSZ-i, Parallax) requires real LLM + SLURM allocation spend; the
  PLAN docs' real-LLM acceptance items remain unverified pending
  separate operational runs.
- Screenshot embeds for `docs/howto/paperbench_gui.md` (TD3 — needs a
  running browser session against a populated registry).
- LLM-driven ja/zh translation pass over the stub mirrors of the
  PaperBench docs (TR8 / TD11-12 partial — quickstart and
  execution_profile are already full translations).
- Background worker that consumes the queued PaperBench jobs from the
  `_JOBS` table and drives the actual CLI pipeline; v0.7.2 records
  job intent only, real execution still goes through `ari run`.

### Migration

No checkpoint-format or rubric-format breaking changes. Existing
v0.7.1 rubrics validate as v0.7.2 rubrics without modification.
Existing call sites of `run_reproduce` / `build_reproduce_sh` /
`run_replicator_agent` continue to work — every new argument defaults
to `0` / `""` / `False` / `None`.

## v0.7.2 — BFTS audit (2026-05-13, parallel track)

Landed on the same date as the original v0.7.2 paper-audit release
above; merged in from the `bfts` branch as a separate
orchestration-layer thread. Headline: **BFTS algorithm audit**.
Twenty-five orchestration-layer discrepancies between the v0.7.1
implementation, its prompts, and the
technical report were grouped under `bfts_audit_plan.md` and resolved in
a single release. No checkpoint-format change; existing `tree.json`
files resume cleanly.

### Bug fixes (Phase 1)

- **B-1**: removed the `BFTS.total_nodes` counter that double-bookkept
  the live `len(all_nodes)` view. `should_prune(node, *, current_total)`
  now takes the count from the caller — single source of truth.
- **B-2**: `BFTSConfig.max_depth` was previously dead config. It is now
  enforced by `should_prune` (`depth ≥ max_depth → prune`) and surfaced
  to the expand-prompt as `Current depth: D / max_depth M`.
- **B-3**: dropped the `retry_count` signal from `select_next_node`
  candidate descriptions and from `bfts_select.md` ("prefer unexplored
  directions (low retry)" was misleading — ARI never retries).
- **B-4**: `should_prune` now also retires sterile nodes
  (`metrics._sterile is True`), aligning the run-loop's existing sterile
  gate with the pruning predicate.
- **B-5**: deleted `ari/orchestrator/scheduler.py` and its `Scheduler`
  callsite in `core.build_runtime`. The asyncio-based class was unused
  and shadowed the real `ThreadPoolExecutor` path in `bfts_loop`.
- **B-6**: `BFTSConfig.max_expansions_per_node` (default 4) plus
  `BFTS.expansion_count(node_id)`. The run-loop now retires frontier
  nodes when (Rule A) a child beat the parent on `_scientific_score`,
  or (Rule B) the node has been expanded ≥ `max_expansions_per_node`
  times.
- **B-7**: fallback child created when the LLM returns no directions
  now inherits `memory_snapshot`, `eval_summary`, `original_direction`,
  and a normalised `name`, matching the regular child-creation path.
- **B-8**: `select_next_node` candidate one-liners now include
  `label=...` (the format used by `select_best_to_expand` already).
- **B-9**: `_extract_directions_json` replaces the legacy
  `re.search(r"\[.*\]", DOTALL)` greedy pattern. It strips
  `<think>...</think>` reasoning blocks, scans for balanced brackets,
  falls back to a lone `{...}`, and finally to the raw string.
- **B-10**: removed `max_retries_per_node=…` from every test fixture
  (`test_bfts.py`, `test_bfts_diversity.py`, `test_idea_integration.py`)
  and the YAML default — the Pydantic field never existed.

### Improvements (Phase 2)

- **I-1**: `bfts_expand.md` switched from "MUST be one of … no
  inventions" to "strongly prefer one of [draft, improve, debug,
  ablation, validation]; otherwise the LLM string is preserved in
  `raw_label`". `NodeLabel.OTHER`'s role is documented in `node.py`.
- **I-2**: `diversity_bonus` docstring matches the implementation
  (`my_count * 2 ≤ max_count`, i.e. "at most half as often").
- **I-3 / L-3**: `BFTS._fallback_score` + `BFTS._select_fallback`
  unify the LLM-fail-path scoring for `select_next_node` and
  `select_best_to_expand`. Both now apply the diversity bonus.
- **I-4**: expand prompt now carries `Current depth: D / max_depth M`
  (always) and `Remaining node budget: K / max_total_nodes` (when the
  caller provides `budget_remaining`, which `bfts_loop` always does).
- **I-5**: `_resolve_pm_and_run_id` helper deduplicates the
  `ARI_CHECKPOINT_DIR → (PathManager, run_id)` boilerplate previously
  copy-pasted across `_load_sibling_node_reports` and
  `_format_parent_report_block`.
- **I-6**: the string-fallback label inference (used when the LLM
  returns a plain string instead of JSON) now uses word-boundary
  regex patterns, so "invalid" no longer trips the VALIDATION branch.
- **I-7**: `bfts.record_run(result)` is now called **after**
  `future.result()` returns, so the diversity bonus reflects nodes
  that actually executed (success or failure) rather than nodes that
  were merely selected.
- **I-8**: `BFTS._get_node_report` introduces an mtime-keyed cache
  for `node_report.json` reads — both sibling listing and the
  parent-report enrichment path share it.
- **I-9**: `threading.Lock`-protected mutation of
  `_recent_label_history`, `_expansion_count`, and `_report_cache`.
  LLM calls remain **outside** the lock.

### Low-priority cleanups (Phase 3)

- **L-1**: `_make_node_name` applies NFKC normalisation and whitespace
  collapsing before truncation, so full-width labels and double-space
  directions produce clean names.
- **L-2**: `_PromptBudget` dataclass centralises the prompt-truncation
  magic numbers (`[:240]`, `[:200]`, …) used by `expand()` /
  `select_next_node`.
- **L-3**: see I-3 — the same PR delivered both.
- **L-4**: `_hash_experiment_file` memoises the experiment-file
  sha256 keyed by `(path, mtime_ns)` — `_save_checkpoint` no longer
  re-hashes the same `.md` after every node completion.
- **L-5**: B-5 deleted the `asyncio.get_event_loop()` call site
  entirely; L-5 is retired.
- **L-6**: `BFTSConfig.label_saturation_threshold` (default 2) makes
  the previously-hardcoded saturation cutoff configurable.

### Docs / report

- `docs/architecture.md::BFTS Algorithm` rewritten for v0.7.2 (depth
  predicate, sterile predicate, frontier retire rules, `record_run`
  timing).
- `docs/configuration.md::BFTS Tuning` adds the full `BFTSConfig`
  table and the new `max_expansions_per_node` /
  `label_saturation_threshold` knobs.
- Technical report (`report/en/chapters/03_exploration.tex`) revised
  for the v0.7.2 formalisation of $\Pi$, $\sigma$, $\rho$, and the
  retire predicate.

## v0.7.1 (2026-05-10)

Headline: structural refactor + documentation overhaul. **No public-API,
LLM-I/O, or checkpoint-format changes.** Every refactor commit on this branch
asserts `[no behavior change]` or `[byte-equivalent]`. The refactor splits the
six largest hot-spot modules (8,691 lines, six files) into a five-layer package
layout, externalises every inline LLM prompt to `ari/prompts/`, formalises the
skill → core boundary through `ari.public`, isolates v0.5→v0.7 migration code
under `ari.migrations`, and removes legacy `~/.ari/` defaults from publish /
clone / registry / memory paths (with deprecation warnings, not removals — the
v1.0 removal target is unchanged). Documentation is rewritten end-to-end and
the trilingual report (`report/{en,ja,zh}/`) is added.

### Changed — package layout (post-refactor, no behavior change)

The post-refactor `ari-core/ari/` package is organised in five layers (see
`docs/architecture.md::Layered architecture` and
`CONTRIBUTING.md::Software-engineering discipline`):

- **Phase 1** — every `ARI_CHECKPOINT_DIR` env read and write is routed
  through `ari.paths.PathManager` (31 call-sites).
- **Phase 2** — workflow.yaml discovery and `tree.json` I/O collapsed into
  `ari/config/finder.py` and `ari/checkpoint.py`.
- **Phase 3A** — `ari/cli.py` (1,962 lines) → `ari/cli/{__init__, run,
  projects, commands, bfts_loop, lineage, migrate}.py`.
- **Phase 3B** — `ari/viz/server.py` (1,489 lines) → `viz/{routes, websocket,
  ui_helpers}.py` (`_Handler` extracted into `routes.py`); `viz/api_state.py`
  (1,434 lines) → 7 sibling modules (`checkpoint_finder`, `state_sync`,
  `checkpoint_api`, `ear`, `file_api`, `checkpoint_lifecycle`,
  `node_work_api`).
- **Phase 3C** — `ari/pipeline.py` (1,641 lines) → `ari/pipeline/{__init__,
  experiment_md, yaml_loader, stage_control, context_builder, stage_runner,
  orchestrator}.py`.
- **Phase 3D** — `ari/agent/loop.py` (1,459 lines) → `agent/{loop,
  message_utils, tool_manager, guidance}.py`.
- **Phase 3E** — `ari/orchestrator/node_report.py` (706 lines) →
  `orchestrator/node_report/{builder, legacy_reconstruct}.py` package.
- **Phase 4** — public re-export layer at `ari/public/{container,
  cost_tracker, paths, llm, config_schema}.py`. Skills now import only from
  `ari.public.*`. `ari-core/tests/test_public_api_boundary.py` enforces the
  boundary in CI; `ari-skill-coding/tests/test_server.py` and
  `ari-skill-plot/src/server.py` are migrated off direct
  `ari.container` / `ari.cost_tracker` imports.
- **Phase 5** — v0.5 → v0.7 migration code isolated under
  `ari/migrations/v05_to_v07/`. Call-sites are thin shims; the whole subtree
  is scheduled for removal in v1.0 (already announced in v0.7.0).
- **Phase PC0–PC8** — every inline LLM prompt in `ari-core/` is loaded from
  `ari/prompts/<area>/<purpose>.md` via `FilesystemPromptLoader` (agent system
  prompt, BFTS prompts, evaluator base + dynamic-axes peer review, lineage
  decision, root idea selector, keyword librarian, viz wizard). Model price
  tables and the lineage default model live in `ari/configs/*.yaml`, loaded
  via `FilesystemConfigLoader`. `ari-core/tests/test_prompt_extraction.py`
  pins the sha256 of every externalised prompt against the inline original;
  silent edits surface as a CI failure.
- **Phase PC6** — `ari.protocols.Evaluator` formalised; the
  `LLMEvaluator` is now selected via Protocol injection at the composition
  root (`ari.core.build_runtime`).
- **DR1–DR4** — `~/.ari/memory.json` default arg removed
  (`memory/file_client.py`); publish / clone / registry now warn on legacy
  `~/.ari/registries.yaml` + `~/.ari/registry-data` and fall back to
  checkpoint-scoped lookup; `memory/auto_migrate.py` and
  `memory_cli.py` legacy paths are wrapped in `_deprecation`
  helpers; test isolation around `~/.ari/` writes is tightened.

### Added — CI guards and contracts

- `.github/workflows/refactor-guards.yml`: fails the build on a new
  `~/.ari/` reference outside `ari/migrations/` or `docs/refactor_audit.md`
  and on a skill-side import that bypasses `ari.public.*`.
- `ari-core/tests/test_public_api_boundary.py`: the canonical enforcement
  for the skill → core boundary.
- `ari-core/tests/test_prompt_extraction.py`: sha256 pins on every
  externalised prompt.
- `ari/protocols/`: shared cross-layer Protocols (`Evaluator`, `PromptLoader`,
  `ConfigLoader`).

### Documentation

- DOCUMENTATION_PLAN Phase D0–D5 executed end-to-end: 17 obsolete planning
  files removed (master plans, per-module REFACTORING.md / DEPRECATION.md /
  PROMPTS_AND_CONFIG.md). The information they carried is folded into
  `docs/architecture.md` (Layered architecture section), `CONTRIBUTING.md`
  (Software-engineering discipline §1–5 + Deprecation process), and
  `docs/refactor_audit.md` (the inventory snapshot).
- New `docs/release_policy.md`: SemVer interpretation, public-surface
  definition, support window, deprecation lifecycle, release checklist.
- New `docs/refactor_audit.md`: the Phase 0 inventory (giant modules,
  `ARI_CHECKPOINT_DIR` direct reads, cross-file duplication, skill→core
  boundary violations, `~/.ari/` references) preserved for archaeology.
- New trilingual report sources at `report/{en,ja,zh}/` (introduction,
  system overview, exploration, paper pipeline, evaluation, related work,
  discussion, appendix) with shared `references.bib`, `glossary.yaml`,
  `notation.tex`, `preamble.tex`. Build pipeline includes:
  `Makefile`, `setup_fonts.sh`, `.latexmkrc`, `scripts/translate.py`
  (LLM-driven en→ja/zh translation), `scripts/build_html_pandoc.py`,
  TikZ/pgf figure pipeline (`shared/figures/{tikz,pgf,dot}/`), and a
  consistency-check suite (`check_bib`, `check_code_refs`,
  `check_figures`, `check_glossary`, `check_i18n`,
  `check_logs_for_secrets`, `check_notation`, `check_tikz`,
  `check_toc_consistency`).
- `docs/architecture.md::Module Reference` updated to point at the new
  package layout (`ari/cli/`, `ari/pipeline/`, `ari/agent/`,
  `ari/viz/routes.py`, `ari/orchestrator/node_report/`).
- `CONTRIBUTING.md::Repository Structure` and the new
  `Software-engineering discipline (v0.7+ refactor)` section document the
  five load-bearing rules: separation of concerns, loose coupling via
  Protocols, public-API boundary, external prompts/config, and the
  behaviour-preservation contract for refactors.

### Compatibility

- All v0.7.0 checkpoints continue to load on v0.7.1 unchanged.
- `ari --help` and every subcommand `--help` output is byte-identical to
  v0.7.0 (verified by Phase 3A's behaviour-preservation pin).
- All externalised prompts are sha256-equivalent to the v0.7.0 inline
  originals (verified by `tests/test_prompt_extraction.py`).
- The skill → core import boundary is now CI-enforced; out-of-tree skills
  importing private `ari.<module>` names will need to migrate to
  `ari.public.*` before upgrading.

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
  prefetch gain on the aarch64 compute node) — replaces stale stencil-benchmark
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
