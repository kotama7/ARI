# Task 00: Current ARI Investigation

> **Status**: active · **Depends on**: none · **This is a temporary task plan** — see [INDEX.md](INDEX.md). It will be deleted once its deletion criteria are met.

## 1. Purpose

Constitutional ARI-RQGM adds an epoch-based, institution-style co-evolution layer
(governance / prompt evolution / selective erasure) on top of ARI's existing BFTS
research loop. Before any of that can be designed safely, we need a shared, verified
picture of what ARI actually is today: where the BFTS loop's control flow lives, how
ideas (`idea.json` / VirSci) enter the search, how the evaluator and the deterministic
gates interact, how state is persisted, which prompts exist and how they are pinned,
what the Story2Proposal paper pipeline enforces, and which behaviors are contractual.

This plan **is** that picture. Unlike Tasks 01–13, its deliverable is not a design to
implement later — it is the investigation itself, organized so that every downstream
task plan can cite exact attachment points instead of re-discovering them. It doubles
as the investigation report until its content is migrated to permanent docs and to the
downstream plans (sections 4 and 5 contain the findings, not proposals).

All findings below were verified against the working tree at branch `RQGM`
(ari-core v0.9.1). All paths are repo-relative.

## 2. Scope

Investigation and organization only:

- Subsystem map of ari-core and the relevant skills, with real file paths and symbols.
- The BFTS run lifecycle and the exact RQGM attachment points (epoch boundary,
  proposal generation, utility computation, frontier update, governance hooks).
- The `idea.json` / VirSci pipeline as it exists today, and the migration map toward
  ProposalRecord / ProposalSummaryView / ProposalRouter (Task 03's input).
- The relationship between RQGM concepts and the Story2Proposal (S2P) paper pipeline,
  including the existing deterministic-verifier vs LLM-judge split.
- The state/persistence layer patterns new RQGM records must follow.
- The prompt infrastructure and its four snapshot/gating layers (Task 07's input).
- The config/CLI surface and where `ari.mode` / `rqgm.*` / `proposal_router.*` would
  be read (Task 01's input).
- An enumerated register of existing behaviors that MUST NOT break under
  `simple_bfts` (the compatibility contract every downstream task inherits).
- An open-questions table assigning each unresolved question to the downstream task
  plan (01–13) that owns it.
- Known defects discovered during investigation (notably the `ari-skill-idea` MCP
  tool-registration regression) recorded as prerequisites for downstream tasks.

## 3. Non-goals

- No implementation. No code, config, schema, prompt, or CI change is made by this
  task (the sole exception discussed in §10/§12: the plan-directory CI hygiene needed
  to commit these plan files at all, which is a repo-hygiene prerequisite, not RQGM
  implementation).
- No design decisions that belong to Tasks 01–13. Where this document sketches a
  migration direction (e.g. §5.3 on `idea.json` compatibility), it records the
  *constraint landscape* and the owning task decides.
- No fixing of pre-existing defects (e.g. the `@mcp.tool()` regression in
  `ari-skill-idea/src/server.py`) — they are recorded and assigned.
- No changes to BFTS behavior, no deletion of VirSci, no enabling of RQGM anywhere.
  `simple_bfts` keeps current ARI behavior verbatim; `ari_rqgm` will be opt-in via
  config; VirSci remains fully removable via config (`virsci.enabled=false`).
- No master plan. Cross-task sequencing lives in INDEX.md only.

## 4. Existing ARI touchpoints

This section is the subsystem map. Every downstream plan's own "§4 Existing ARI
touchpoints" should be a subset of (or a refinement of) this section.

### 4.1 Composition root and protocol seams

- `ari-core/ari/core.py` — `build_runtime(cfg, experiment_text, checkpoint_dir)`
  constructs the whole runtime: per-phase `LLMClient`s (env overrides
  `ARI_MODEL_CODING` / `ARI_MODEL_BFTS` / `ARI_MODEL_EVAL`), `LettaMemoryClient`,
  one shared `MCPClient`, `BFTS(cfg.bfts, bfts_llm)`, `LLMEvaluator`, `AgentLoop`.
  Returns a 6-tuple `(llm, memory, mcp, bfts, agent, metric_spec)` relied on
  **positionally by 4 call sites** — downstream tasks must wrap returned objects,
  never extend the tuple. Requires `checkpoint_dir` (no `~/.ari` since v0.5.0).
  Two precedents for config-conditional wiring already exist here: the
  `hpc_enabled` skill drop and the `evaluator.axis_mode` dispatch.
  `generate_paper_section(...)` in the same file drives the post-BFTS pipeline.
- `ari-core/ari/protocols/search.py` — `SearchStrategy` (7 methods:
  `select_next_node`, `select_best_to_expand`, `should_prune`, `expand`,
  `record_run`, `expansion_count`, `diversity_bonus`) and `NodeExecutor`
  (`run(node, experiment) -> Node`). Structural `@runtime_checkable` Protocols;
  `_run_loop` and `build_runtime` bind to them, so an RQGM decorator around `BFTS`
  or `AgentLoop` plugs in at `core.py` with zero changes elsewhere.
- `ari-core/ari/protocols/evaluator.py` — `Evaluator` Protocol (`metric_spec`
  mutable attribute, `evaluate`, `evaluate_sync`); the sanctioned swap point for a
  `GovernedEvaluator`.
- `ari-core/ari/protocols/stores.py` — `CheckpointStore` / `TraceStore` Protocols +
  `ArtifactStore` ABC; the file where RQGM `EpochStore` / `AuditStore` Protocols
  belong (Task 02).
- `ari-core/ari/protocols/model_backend.py` — `BaseModelBackend`; the evaluator's
  direct-litellm call is slated to migrate here (xfail in
  `ari-core/tests/test_evaluator_independence.py`), so RQGM hooks must target the
  Protocol seams, not litellm.
- **No `MCPClient` Protocol exists yet** — explicitly deferred in
  `ari-core/ari/protocols/__init__.py`. A governance proxy over MCP must duck-type
  `list_tools`, `call_tool`, `close_all`, `to_claude_mcp_config`, `_COW_TOOLS`
  (Task 11 open question).

### 4.2 BFTS core (search policy + loop driver)

- `ari-core/ari/orchestrator/bfts.py` — the `BFTS` class (policy half): LLM
  select/expand with total deterministic fallbacks (`_select_fallback`,
  fallback child), `should_prune` hard cutoffs (`max_total_nodes`, `max_depth`,
  `metrics["_sterile"]`), `diversity_bonus`, and 4 `frontier_score` strategies in
  `_fallback_score` (`scientific_plus_diversity` default, `scientific_only`,
  `depth_penalized`, `ucb_like`). `expand` hard-caps to ONE child and hard-codes
  prompt key `orchestrator/bfts_expand`; the two selector prompts are
  config-swappable (`BFTSConfig.select_prompt`, `expand_select_prompt`).
- `ari-core/ari/cli/bfts_loop.py` — `_run_loop(...)` (~925-line driver): expansion,
  batch selection, work-dir staging (parent copy minus `_OUTPUT_BLACKLIST`),
  parallel execution (`ThreadPoolExecutor`, workers hard-clamped to ≤4), frontier
  retirement Rules A/B, the sterile gate, per-node checkpointing
  (`_save_tree_incremental(force=True)`), and the lineage-decision hook.
  `_save_checkpoint` writes the contractual `tree.json` / `nodes_tree.json` /
  `results.json` triple plus the `prompt_versions.json` rollup.
- `ari-core/ari/orchestrator/node.py` — the `Node` dataclass. `ancestor_ids`
  defines memory visibility; sentinel metrics keys `_scientific_score`,
  `_axis_scores`, `_sterile`, `_comparison_found`, `_params_dict`,
  `_measurements_dict` are read by ≥7 modules. `work_dir` is a dynamic attribute
  not serialized by `to_dict()`.
- `ari-core/ari/orchestrator/bfts_prompt_builder.py` — pure, byte-deterministic
  prompt-context serialization (P2); no I/O, no LLM.
- `ari-core/ari/orchestrator/node_report/builder.py` — per-node self-report
  (`node_report.json`, `SCHEMA_VERSION = 1`, sha256 file diffs via
  `compute_files_changed`); `write_node_report` never raises. Schema at
  `ari-core/ari/schemas/node_report.schema.json`.
- `ari-core/ari/orchestrator/node_selection.py` — downstream "which nodes
  contribute" predicates used by the paper pipeline.
- `ari-core/ari/orchestrator/web_provenance.py` — the P5 pattern: opt-in
  non-reproducibility writes a durable marker (`bfts_web_provenance.json`);
  absence == reproducible trajectory.

### 4.3 Governance precedent: the lineage layer

The closest existing analogue to RQGM epoch governance, and the template to mirror:

- `ari-core/ari/orchestrator/lineage_decision.py` — closed action set
  `VALID_ACTIONS = {continue, switch_to_idea, fanout, terminate}`;
  `detect_stagnation` (pure rule); `deterministic_stagnation_pivot` (deterministic
  rule tried FIRST); `decide_lineage_action` (LLM judge with total fallback to
  `continue`); `append_decision_log` / `read_decision_log` over append-only
  `{ckpt}/lineage_decisions.jsonl` (shared with root-selection records,
  disambiguated by `trigger`).
- `ari-core/ari/cli/lineage.py` — `_load_lineage_decision_config` (reads the
  **package** `workflow.yaml` + rubric overlay — note the package-vs-checkpoint
  inconsistency, §5.6), `_execute_lineage_decision` (terminate / child-run spawn via
  `ari-core/ari/viz/api_orchestrator.py:_api_launch_sub_experiment`),
  `_mark_parent_terminated` (additive `meta.json` flag read back as a launch gate),
  `_build_idea_ctx_for_expand` (the ~6000-char idea serialization for expand).
- `ari-core/ari/orchestrator/root_idea_selector.py` — one-shot run-start re-ranking
  of `idea.json` (`apply_root_choice` swap + `_root_choice` provenance marker;
  malformed output → index 0). The "run once, leave a marker" idempotency pattern.

### 4.4 Agent loop (node executor)

- `ari-core/ari/agent/loop.py` — `AgentLoop.run` executes one node: deterministic
  context injection (`build_working_context_messages` reads
  `{ckpt}/metric_contract.json`, ancestor conclusions; pinned via
  `_PINNED_USER_MARKERS` so windowing never drops them), the ReAct tool loop,
  anti-fabrication chain (`_FAKE_PATTERNS` → `validate_metrics` → real-output
  substitution), evaluator call on finish, `result_summary` memory write. The
  `generate_ideas` result handler here (not the skill) persists `{ckpt}/idea.json`.
  The `make_metric_spec` handler reassigns `self.evaluator.metric_spec` mid-run —
  a self-determination of evaluation criteria that Task 11 must constitutionally cap.
- `ari-core/ari/agent/tool_manager.py` — `execute_tool_calls` is the single choke
  point for every LLM-initiated tool call (CoW routing via `cow_node_id`);
  `available_tools_openai(suppress=...)` controls tool exposure and always hides
  `_set_current_node`.
- `ari-core/ari/agent/guidance.py`, `ari-core/ari/agent/metric_contract.py` —
  deterministic nudges and the metric-correctness contract producer
  (`build_expand_coverage_hint` is the precedent for selector-side steering).
- `ari-core/ari/agent/react_driver.py` — a second, separate ReAct loop
  (`run_react`) for post-BFTS `react:` pipeline stages, with sandbox path
  enforcement and git shims; the natural harness for agentic adversary/defender/
  judge rollouts (Tasks 05/06/08).
- `ari-core/ari/agent/workflow.py` — `WorkflowHints` DI container (the declared
  home for experiment-specific settings; governance-epoch parameters fit its
  contract).

### 4.5 Evaluator (LLM judge + deterministic overrides)

- `ari-core/ari/evaluator/llm_evaluator.py` — per-axis LLM judge; composite from
  `_COMPOSITE_REGISTRY` (a `ari-core/ari/_factory.py:BaseRegistry`); authoritative
  `results.json` merge overrides LLM extraction; never raises into the loop;
  `_resolve_axis_weights` precedence MetricSpec > ctor > AxisDef > equal;
  `_refresh_axes_if_needed` is the "watch a checkpoint file, rebuild
  deterministically" pattern (content-hash keyed on `idea.json`).
- `ari-core/ari/evaluator/dynamic_axes.py` — axis set is a deterministic function
  of `(rubric, idea.json)` (P2): generic floor + rubric layer + plan-keyword layer.
- ARI already has a de-facto **fixed-verifier vs LLM-judge split** (the seed of
  RQGM Layer 0): results.json merge, the sterile gate in `bfts_loop.py`,
  `validate_metrics` / `_FAKE_PATTERNS`, `should_prune` hard cutoffs, and the
  paper-phase `claim_evidence_hard_gate` (deterministic, blocking) vs
  `evidence_grounded_semantic_review` (LLM, advisory). See §5.4.

### 4.6 Idea generation / VirSci

- `ari-skill-idea/src/server.py` — the VirSci adapter skill: `survey()` and
  `generate_ideas()` (re-implemented discussion loop by default; real vendored
  engine behind `ARI_IDEA_VIRSCI_REAL` via `ari-skill-idea/src/virsci_runtime.py`;
  frozen Semantic Scholar corpus via `ari-skill-idea/src/snapshot.py` under
  `{ckpt}/virsci_snapshot/`). Three never-block degradation tiers exist.
  **CRITICAL regression at HEAD**: `survey` and `generate_ideas` are NOT registered
  as MCP tools (decorator capture by helpers inserted in commits
  `711dad0`/`0625d2d`/`3707fd6` — only `_load_virsci_snapshot_papers` is
  decorated); runs currently proceed idea-less. Task 03 must fix this first.
- `idea.json` writers: the agent loop (`ari-core/ari/agent/loop.py`, generate_ideas
  handler), `ari-core/ari/orchestrator/root_idea_selector.py:apply_root_choice`,
  and child-launch pinning in `ari-core/ari/viz/api_orchestrator.py`
  (`_pinned` / `_inherited_from`).
- `ari-core/ari/lineage.py` — read-only ancestor **catalog** path
  (`walk_ancestor_ckpts`, `get_idea_pool_for_ckpt`,
  `format_ancestor_pool_for_virsci`); strictly separated from the **directive**
  path (`ideas[0]` of the current checkpoint only). See §5.3.

### 4.7 Paper pipeline (Story2Proposal) and claim gate

- `ari-core/ari/pipeline/driver.py` — `WorkflowDriver` runs YAML-declared stages in
  **file order (no topological sort)**; pre-flight writes `evaluation_criteria.json`,
  memory-enriched `nodes_tree.json`, `verified_context.json`; `loop_back_to` is the
  only bounded generate→verify→regenerate primitive.
- `ari-core/ari/pipeline/stage_runner.py` — `_run_stage_subprocess` (fresh
  subprocess per MCP stage; **an error-only dict `{"error": ...}` fails the stage**,
  which is exactly how blocking works) and `_run_react_stage`.
- `ari-core/ari/pipeline/stages.py` (`should_skip` / `depends_on` /
  `skip_if_exists` semantics, `make_stage` dispatch fork),
  `ari-core/ari/pipeline/stage_control.py` (`_should_loop_back`).
- `ari-core/ari/pipeline/claim_gate/` — the deterministic hard gate
  (`gate.py:run_hard_gate`, `policy.py`, `numeric.py`, `resolve.py`,
  `invariants.py`, `contract.py`, `formula_eval.py`, `latex.py`); public surface
  `ari-core/ari/public/claim_gate.py`. Blocking matrix: draft never blocks;
  `always_block_on` (objective falsehoods) blocks at final in ANY mode; gate fails
  **open** on infrastructure errors. The gate report's `metrics` block is a
  ready-made per-run scorecard for Task 13.
- `ari-core/ari/pipeline/verified_context.py` — typed-memory grounded claims
  injected into the paper writer's prompt (`render_grounded_block`); an artifact,
  not a stage.
- `ari-skill-paper/src/server.py` (`write_paper_iterative` with `% CLAIM:Cx:NCx`
  forward-declaration anchors, `paper_refine` anchor-preservation contract,
  `merge_reviews` structural merge) and `ari-skill-paper/src/claim_links.py`
  (mirrors `claim_gate/latex.py`); `ari-skill-transform/src/claims.py` (mirrors
  `claim_gate/numeric.py`). Mirrored registries must stay in sync.
- Gate MCP wrapper: `ari-skill-evaluator/src/server.py`
  (`_tool_claim_evidence_hard_gate`, `_tool_evidence_grounded_semantic_review`).

### 4.8 MCP layer

- `ari-core/ari/mcp/client.py` — `MCPClient`: stdio subprocess per skill, **flat
  tool namespace with last-skill-wins on collision**, phase filtering (free-string
  phases), CoW lock (`_COW_TOOLS`) for memory writes, hardcoded timeout tiers
  (`_SLOW_TOOLS` 1 h / `_VERY_SLOW_TOOLS` 13 h / default 300 s), 3 retries with
  reconnect (**tools must be idempotent**), `to_claude_mcp_config` for the
  cli-shim path (which currently leaks `_set_current_node` into the shim allowlist
  — known gap).
- `ari-core/ari/registry/` is an EAR HTTP artifact registry, **not** a skill or
  component registry — a false friend for RQGM naming.

### 4.9 State layer (persistence & provenance)

- `ari-core/ari/paths.py` — `PathManager` / `RuntimePathResolver`;
  `ARI_CHECKPOINT_DIR` is the single run pin; `META_FILES` + `_TRACE_FILES`
  registries: **every new checkpoint-root filename must be registered** or it
  contaminates node work dirs and `node_report.files_changed`.
- `ari-core/ari/checkpoint.py` — the tree/nodes_tree/results triple with byte-fixed
  formatting (`indent=2, ensure_ascii=False`), 1 s-throttled incremental save.
- `ari-core/ari/trace_store.py` — per-node `trace.jsonl` **dormant seam with no
  production writer** — a ready-made per-node audit attach point.
- `ari-core/ari/cost_tracker.py` — global litellm callback → `cost_trace.jsonl`;
  passive accounting, **no budget enforcement**; additive default-None fields on
  `CallRecord` + `set_default_metadata(...)` are the per-epoch attribution path
  (Task 12).
- `ari-core/ari/lineage.py` + `meta.json` `parent_run_id` chain — cross-run
  provenance; launch gates (recursion depth, `parent_terminated`) in
  `ari-core/ari/viz/api_orchestrator.py`.
- `ari-core/ari/memory/` + `ari-skill-memory` — Letta backend, ancestor-scoped
  search, CoW writes, `memory_access.jsonl`; append-only by design, so selective
  erasure must be read-time filtering/staling (matches SPEC invariant 13).
- Three established persistence patterns (all new RQGM records must pick one):
  (1) rewrite-whole-JSON snapshots; (2) append-only JSONL under a lock, best-effort,
  absence-tolerant (`ari-core/ari/prompts/_provenance.py:record_prompt_use` is the
  cleanest template); (3) content-addressed sha256 provenance.

### 4.10 Prompts

- `ari-core/ari/prompts/` — exactly 11 committed `.md` templates;
  `FilesystemPromptLoader.load_versioned(key) -> (text, sha256[:12])` (`_loader.py`);
  `PromptRegistry` / `PromptEntry` (`registry.py`) — structurally a proto-PromptSpec
  (identity + hash + placeholder interface); `record_prompt_use` →
  `prompt_trace.jsonl` + end-of-run `prompt_versions.json` rollup
  (`_provenance.py`). `PromptUseRecord` has two reserved always-None fields
  (`prompt_version`, `prompt_registry_version`) explicitly waiting for a registry
  layer — Task 07's zero-schema-break attach point.
- Four snapshot/gating layers pin every core prompt byte-exactly:
  (1) hand-pinned sha256 rows in `ari-core/tests/test_prompt_extraction.py`;
  (2) raw+rendered byte goldens in `ari-core/tests/test_prompt_snapshots.py`
  (re-bless via `ARI_UPDATE_PROMPT_SNAPSHOTS=1`); (3) Gate 10 report-appendix
  snapshots (`report/scripts/check_prompt_snapshots.py`, hard CI in
  `.github/workflows/prompt-change-review.yml`); (4) runtime provenance.
  `scripts/check_prompts.py` flags any new inline prompt string — RQGM prompts must
  be externalized `.md` from day one.

### 4.11 Config / CLI

- `ari-core/ari/config/__init__.py` — Pydantic `ARIConfig`; `extra: allow` **but**
  `load_config` filters unknown top-level keys out of the typed cfg, so an `rqgm:`
  YAML block is silently dropped unless a first-class `rqgm: RQGMConfig` field is
  added (Task 01's recommended route) or the raw YAML is re-read at the consumption
  site (the pattern that produced the live package-vs-checkpoint inconsistency).
  Env-override helpers (`apply_bfts_env_overrides`, `apply_evaluator_env_overrides`)
  run **after** profile application; `export_resolved_config_to_skill_env` uses
  setdefault so explicit env always wins.
- `ari-core/ari/config/finder.py` — `package_config_root()` = `ari-core/config/`.
  Three distinct config locations: `ari-core/ari/config/` (Pydantic models),
  `ari-core/ari/configs/` (data tables: `defaults.yaml`, `model_prices.yaml`),
  `ari-core/config/` (user-facing `workflow.yaml`, profiles, rubrics).
- `ari-core/ari/cli/run.py` — `ari run` / `ari resume` lifecycle; the workflow.yaml
  copy-into-checkpoint with don't-clobber-GUI-copy guard is the pattern a bundled
  `constitution.yaml` would follow. CLI command tree, env side-effects, and
  `ari.public.*` symbols are contract-snapshotted
  (`ari-core/tests/test_contract_snapshots.py`, `scripts/snapshot_contracts.py`) —
  keeping RQGM config-only (no CLI-surface change) for v1 is the cheap path.
- **Verified: no `ari.mode` or `rqgm.*` key exists anywhere in the tree today.**
  Nearest mode switches: `lineage_decision.mode`, `claim_gate_policy.mode`,
  `evaluator.axis_mode`, `container.mode`.

### 4.12 Docs / CI

- Diátaxis docs tree with tri-language mirrors and hard gates
  (`.github/workflows/docs-sync.yml`); `sources:` front-matter existence gate
  (`scripts/docs/check_doc_sources.py`); readme-sync Contents rows; documenting an
  env var / checkpoint file in `docs/reference/` SemVer-freezes it.
- `docs/plans/ari_rqgm/` exists (untracked, empty at investigation time) but is
  **neither** exempt in `check_doc_sources.py` `EXEMPT_DIR_SEGMENTS` **nor**
  excluded from the VitePress build (`docs/.vitepress/config.ts` `srcExclude`) —
  see §10 Risks.
- Plan retirement discipline: plans carry their own deletion clauses; exact-phrase
  acceptance keywords are recorded in `CHANGELOG.md` before `git rm`
  (v0.7.2 precedent); the canonical "Document Retirement Policy" text was deleted
  with `docs/refactoring/`, so this plan set is self-contained on deletion rules.

## 5. Proposed design

Here, "design" = the organized findings: the attachment-point map, the migration
map, and the compatibility register that all downstream designs build on.

### 5.1 BFTS run lifecycle and RQGM attachment points

`ari run experiment.md` (`ari-core/ari/cli/run.py:run`): `.env` chain →
`_resolve_cfg` → `--profile` overlay → env overrides (env wins, applied after
profile) → skill-env export → run_id minting (adopts `ARI_CHECKPOINT_DIR` basename
when the GUI pre-created it) → `build_runtime` → root `Node` → copy `experiment.md`
+ `workflow.yaml` into the checkpoint → `_run_loop(...)` → `generate_paper_section`.

`_run_loop` (`ari-core/ari/cli/bfts_loop.py`), outer loop
`while pending or (_expand_enabled and frontier and len(all_nodes) < max_total_nodes)`:

1. **Expansion**: `bfts.select_best_to_expand` on the frontier (goal augmented with
   `build_expand_coverage_hint`) → `should_prune` → `bfts.expand` → exactly ONE
   child appended to `pending`. First appearance of `idea.json` triggers the
   one-shot root idea selection (marker-guarded).
2. **Batch selection**: up to `min(max_parallel_nodes, 4)` nodes via
   `bfts.select_next_node`.
3. **Staging**: parent work-dir copied excluding `_OUTPUT_BLACKLIST`.
4. **Execution**: `ThreadPoolExecutor` → `agent.run(node, exp)`; on ReAct finish
   `evaluator.evaluate_sync` sets `_scientific_score` / `_axis_scores` /
   `has_real_data` / `eval_summary`, writes a `result_summary` memory entry.
5. **Per-completion post-processing** (main thread): `bfts.record_run`; SUCCESS and
   FAILED nodes both join the frontier; Retire Rule A (child beats parent) and B
   (`max_expansions_per_node`); the **sterile gate** (zero file delta →
   `_sterile=True`, score clamped 0.0 — a fixed verifier overriding the LLM judge);
   `write_node_report`; optional memory consolidation;
   `_save_tree_incremental(force=True)`; the **lineage-decision hook**
   (deterministic pivot first, LLM judge second, JSONL audit).

**Attachment-point table** (the canonical reference for Tasks 01–12):

| RQGM concept | Attachment point (today's code) | Owner task |
|---|---|---|
| Epoch boundary | Head of the outer `while` in `_run_loop` — the only natural round boundary; sees `all_nodes` / `frontier` / `pending` / `cfg` / `checkpoint_dir` on the main thread. Decided 2026-07-28 (`c050ebf`): epoch = N new BFTS nodes — `RqgmRuntime.ensure_epoch` fires the boundary once `node_count - ep.node_count_at_open >= rqgm.epoch.nodes_per_epoch`, called from this outer-loop head via `_rqgm_epoch_tick`. | 01, 02, 05 |
| Governance hook template | The per-node lineage hook block in `_run_loop`: config-gated, rate-limited, deterministic-rule-first, best-effort try/except, append-only JSONL audit. Mirror this shape exactly. | 05 |
| Proposal generation | Two sites: (i) root ideation = `generate_ideas` MCP tool + persistence handler in `ari-core/ari/agent/loop.py` (→ `idea.json`); (ii) tree expansion = `BFTS.expand` consuming `idea_context` from `ari-core/ari/cli/lineage.py:_build_idea_ctx_for_expand`. A ProposalRouter replaces/wraps (i) and feeds (ii) via a summary-view string; `SearchStrategy.expand` + the `idea_context` parameter are the interception points. | 03 |
| Utility computation | `Evaluator` protocol seam, constructed once in `build_runtime`. Deterministic overrides that must survive any wrapper: results.json merge, sterile gate, `validate_metrics`. Epoch weights slot into `_resolve_axis_weights`; new composites into `_COMPOSITE_REGISTRY` (+ config Literal in lockstep). | 04, 05 |
| Frontier update / repair | Retire Rules A/B + sterile gate + `should_prune`, all in `_run_loop` step 5. Least-invasive veto channel: a `Node.metrics` convention like `_sterile` (already read by `should_prune`). `BFTS._fallback_score` / `frontier_score` is the pluggable deterministic ranking switch. FrontierRepair maps onto these rules plus tree.json reload on resume. | 10 |
| New governance verbs | `lineage_decision.py:VALID_ACTIONS` / `_parse_decision` — unknown actions degrade to `continue` on old checkpoints (safe extension). | 05, 09 |
| Object-level tool policy | `MCPClient.call_tool` wrapper (single choke point for every skill invocation) and `tool_manager.execute_tool_calls` / `available_tools_openai(suppress=...)` for per-epoch tool exposure. | 04, 09, 12 |
| Per-node charter injection | `build_working_context_messages` + a new `_PINNED_USER_MARKERS` entry — the metric-contract precedent: read a JSON artifact from the checkpoint, emit a capped deterministic user message. | 05 |
| Agentic adversary/defender/judge rollouts | `ari-core/ari/agent/react_driver.py:run_react` (sandboxed, final-tool-terminated) or a new MCP skill following `ari-skill-evaluator`'s server pattern. | 06, 08 |
| Paper-phase blocking | The error-only-dict + `depends_on` convention (§4.7). | 04, 13 |
| Cross-run propagation | Child-launch gates in `ari-core/ari/viz/api_orchestrator.py` (recursion depth, `parent_terminated`) via additive `meta.json` fields. | 02, 05 |

**Resume caveat**: `resume` reconstructs only a subset of `Node` state from
`tree.json`; BFTS in-memory state (`_expansion_count`, `_recent_label_history`,
lineage counters) starts empty. Any epoch state must be persisted checkpoint-side
in a NEW file (tree.json is contract-frozen) to survive resume (Tasks 01/02).

### 5.2 idea.json / VirSci today → ProposalRecord / ProposalSummaryView (Task 03 input)

**Today**: the root node's first tool call is `generate_ideas` (idea-skill; re-impl
VirSci loop by default, real vendored engine behind `ARI_IDEA_VIRSCI_REAL` with a
frozen `virsci_snapshot/`). The **agent loop**, not the skill, persists the result
to `{ckpt}/idea.json` — a 9-key contract (`gap_analysis`, `ideas[]` sorted by
`2*novelty+feasibility+clarity`, `primary_metric`, `higher_is_better`,
`metric_rationale`, `papers_analyzed`, `n_agents`, `discussion_rounds`,
`virsci_integration_status`), plus provenance markers `_root_choice` /
`_inherited_from` / per-idea `_pinned`.

**`ideas[0]` is the run directive** for four consumers: expand context
(`_build_idea_ctx_for_expand`), evaluator plan-derived axes
(`dynamic_axes.plan_to_axes`, content-hash refresh), paper `idea_context` + plan
promotion (`ari-core/ari/pipeline/driver.py` + `experiment_md.py`), and the Letta
core-memory seed. One-shot LLM root selection may swap `ideas[chosen] ↔ ideas[0]`.
Lineage decisions pivot among runner-up ideas; child runs get a pinned copy.
Three degradation tiers exist; nothing blocks when VirSci or the whole tool is
absent — which is exactly the guarantee `virsci.enabled=false` must formalize.

**Migration map** (constraints recorded for Task 03; decisions belong there):

1. **Fix first**: restore `@mcp.tool()` on `survey` and `generate_ideas` in
   `ari-skill-idea/src/server.py` (regression documented in §4.6); decide the fate
   of the accidentally-exposed `_load_virsci_snapshot_papers`.
2. **ProposalRecord archive** ("store everything") = a new checkpoint-scoped record
   store following the §5.5 persistence playbook. Full transcripts, discussion
   logs, prompt_hashes, generator config, retrieval snapshot refs live there —
   never in anything BFTS reads.
3. **`idea.json` stays as a compatibility projection of ProposalSummaryView**: the
   ProposalRouter writes ProposalRecords AND continues writing a conforming
   `idea.json` (preserving `_pinned` / `_root_choice` / `_inherited_from` semantics
   and the pinned-ideas-in-front merge), then consumers migrate one by one. This
   keeps all four `ideas[0]` consumers and the GUI working untouched under both
   modes during migration.
4. **"BFTS never sees full transcripts" already matches reality**: only the
   ~6000-char `_build_idea_ctx_for_expand` serialization reaches expand prompts
   today. ProposalSummaryView formalizes that boundary.
5. **VirSciAdapter** = today's `ari-skill-idea` server + `virsci_runtime`;
   `virsci.enabled=false` maps to the existing tier-2/3 degradation but must
   additionally guarantee: no snapshot build, no VirSci prompt registration, no
   VirSci transcripts, adapter never initialized, tests pass without VirSci deps.
6. **Cross-run inheritance** rides `_api_launch_sub_experiment`
   (`inherit_idea_index`); the catalog path (`ari-core/ari/lineage.py`) stays
   opt-in per the directive-vs-catalog contract.
7. **Single-writer discipline**: `idea.json` writes are not file-locked; today this
   is safe only because `generate_ideas` is root-only + suppressed after first
   call. More writers (router, epoch re-ideation) need locking or a strict
   single-writer rule.

### 5.3 Relationship to Story2Proposal (S2P)

RQGM's constitutional concepts have direct S2P counterparts — the paper phase is
where ARI already practices "deterministic law over LLM judgment":

- **ClaimEvidenceGate (Layer 0, never-evolving)** already exists as
  `ari-core/ari/pipeline/claim_gate/` + `ari-core/ari/public/claim_gate.py`. Its
  blocking matrix (draft never blocks; `always_block_on` objective falsehoods block
  at final in any mode; fails open on infrastructure errors) is the calibration
  reference for the ConstitutionalKernel's fail-open/fail-closed policy (Task 04).
- **Forward declaration** (`% CLAIM:Cx:NCx` anchors, writer assertions parsed by
  `ari-skill-paper/src/claim_links.py`, recomputed by `claim_gate/numeric.py`) is
  the existing precedent for "claims must be declared before they are asserted" —
  the same shape as ProposalRecord's claim registry (Task 03) and the
  claim-evidence hard gate invariant (SPEC invariant 16).
- **Two grounding substrates coexist**: `science_data.json` `claims[]`
  (deterministic, transform-seeded, gate-verified) and
  `verified_context.usable_for_claims` (typed-memory, lineage-scoped,
  prompt-injected). Whether RQGM unifies or ranks them is a Task 03/13 question.
- **Reviewer independence** (`review_compiled_paper` sees paper text only;
  `merge_reviews` is purely structural) is the existing embodiment of role
  separation — the same-role-accusation prohibition (SPEC invariants 4–7)
  generalizes this.
- **Epoch-wrapping the paper pipeline** is constrained by fixed output paths
  (`full_paper.tex` overwritten in place) and `skip_if_exists` short-circuits
  (a skipped stage re-registers its OLD output) — per-epoch output versioning is a
  Task 13 decision.
- RQGM verifiers that want blocking power reuse the error-only-dict +
  `depends_on` convention; verifiers that must never block must never return a
  bare `{"error": ...}` (the `link_paper_claims` precedent).

### 5.4 The existing two-tier verifier split (ConstitutionalKernel seed, Task 04 input)

Deterministic tier (no LLM; already overrides the judge today):

1. `results.json` merge inside `LLMEvaluator.evaluate` (measured data beats LLM
   re-extraction).
2. Sterile gate in `_run_loop` (file-diff evidence clamps score to 0.0).
3. `validate_metrics` + `_FAKE_PATTERNS` (hallucination checks before the judge).
4. `should_prune` hard cutoffs.
5. Axis-set derivation (`dynamic_axes.py`, pure function of rubric + idea.json).
6. Paper-phase `claim_evidence_hard_gate` (blocking) vs semantic review (advisory).

LLM tier: per-axis scoring, BFTS selectors, lineage judge, root selector — every
one with a total deterministic fallback. **The repo-wide precedent is
deterministic-rule-first, LLM-second, fail-open**; a fail-closed constitutional
check would be a deliberate, documented deviation with only the paper-phase gate
as precedent (Task 04 decision, per check class).

### 5.5 Persistence playbook for new RQGM records (Tasks 02/05/06/09/10 input)

New records follow the subtask-044 pattern exactly:

- Snapshot files: new `ari-core/ari/checkpoint.py` store method + module shim
  (mirroring `save_prompt_versions_json`), byte-fixed formatting.
- Append-only logs: model on `ari-core/ari/prompts/_provenance.py:record_prompt_use`
  (lock, run-pin no-op, never raises, additive dataclass). Repo precedent favors
  "JSONL is truth, snapshot is derived rollup".
- **Register every new filename** in `ari-core/ari/paths.py:PathManager.META_FILES`
  (+ `_TRACE_FILES` for JSONL, + node_report blocklists in
  `ari-core/ari/orchestrator/node_report/builder.py`).
- Protocols: `EpochStore` / `AuditStore` next to
  `ari-core/ari/protocols/stores.py:TraceStore`.
- Schemas: new `epoch_state.schema.json` beside
  `ari-core/ari/schemas/node_report.schema.json`; extending `node_report.schema.json`
  means optional-only fields under `schema_version: const 1`, or a version bump
  with migration.
- Natural homes: ImmutableAuditLog → a new `{ckpt}/rqgm_audit.jsonl` (or new
  `trigger` values in `lineage_decisions.jsonl`); per-node audit → the dormant
  `ari-core/ari/trace_store.py:JsonlTraceStore.append_trace` seam; epoch flags on
  child runs → additive `meta.json` keys; per-epoch cost attribution → additive
  `epoch` field on `cost_tracker.CallRecord` + `set_default_metadata(epoch=...)`.
- Existing JSONL logs are append-only **by convention, not tamper-evident**;
  hash-chaining would be new machinery and needs a P2-safe canonicalization
  (no wall-clock in hashes) — Task 02 decision.
- Memory is ancestor-scoped, CoW-guarded, append-only — selective erasure must be
  read-time filtering/staling, never physical deletion (Task 10; matches SPEC).

### 5.6 Config surface findings (Task 01 input)

- `rqgm:` / `ari.mode` must become a typed `RQGMConfig` field on `ARIConfig`
  (auto-picked-up from workflow.yaml, mirrored by a new `apply_rqgm_env_overrides`
  called from `run`/`resume` after profile application). The raw-YAML re-read
  alternative already produced a live inconsistency: `bfts_pipeline` flags prefer
  the **checkpoint** workflow.yaml copy while `root_idea_selection` and
  `lineage_decision` read only the **package** copy. RQGM readers must be
  checkpoint-first and must not extend the package-only pattern.
- Numeric defaults (epoch length, thresholds, budgets) →
  `ari-core/ari/configs/defaults.yaml` via `FilesystemConfigLoader`; string-keyed
  policies → `ari-core/ari/_factory.py:BaseRegistry` with a
  Literal↔`registry.keys()` parity test.
- A bundled `constitution.yaml` would follow the workflow.yaml pattern: default
  under `ari-core/config/`, copied to the checkpoint at launch with the
  don't-clobber guard, read checkpoint-first.
- Precedence to preserve: env (after profile, validate-before-assign) > profile >
  YAML > `.env` chain.
- Contract-snapshot budget: any new CLI command/flag/env side-effect or
  `ari.public.*` symbol forces golden regeneration; config-only activation for v1
  avoids all of it.

### 5.7 Prompt layer findings (Task 07/08 input)

- `prompt_hash` should **be** the existing `hash12 = sha256(text)[:12]` value —
  do not introduce a second scheme (asserted in three test files and mirrored in
  skill-local loaders).
- `PromptEntry` is structurally a PromptSpec already; extend it with
  role/status/constraints fields, keeping it **out of `ari.public.*`** (no
  public-API snapshot churn).
- `BFTSConfig.select_prompt` / `expand_select_prompt` are the tested precedent for
  per-run prompt swaps; `orchestrator/bfts_expand` is hardcoded and needs an
  `expand_prompt` knob. `FilesystemPromptLoader(base=...)` accepts an alternative
  root, so epoch-mutated prompts can live under the checkpoint dir
  (checkpoint-scoped, v0.5.0-compliant).
- The main tension: a runtime-generated (evolved) prompt would be the first
  managed prompt whose bytes are not a committed `.md`, breaking the Gate 10
  "every prompt in the appendix verbatim" doctrine and the inline-prompt ban —
  Task 07 must design an explicit carve-out (e.g. per-epoch prompt dump under the
  checkpoint, registered in `META_FILES`, with `rendered_prompt_hash` provenance).
- Clean-room enforcement ("cannot read retired prompt text") must contend with the
  flat checkpoint filesystem readable by any skill via `ARI_CHECKPOINT_DIR` —
  Task 08 owns the access-guard design.

### 5.8 Register of existing behaviors that MUST NOT break

This is the compatibility contract. Everything below holds verbatim under
`simple_bfts`; `ari_rqgm` is additive and config-gated; VirSci is fully removable
via config. Downstream plans cite these by number (B-1 … B-19).

**Loop and search semantics**

- B-1 One-child-per-expand; `expand` always returns ≥1 child; slot-filling math
  depends on it.
- B-2 No node retry: FAILED nodes go to the frontier for DEBUG expansion, never
  re-run.
- B-3 Retire Rules A/B, the sterile gate (`_sterile=True` ⇒ score 0.0,
  authoritative over the LLM judge), and the `_OUTPUT_BLACKLIST` parent→child copy
  exclusion — weakening any resurrects the duplicate-results incident.
- B-4 `frontier_expand` disabled ⇒ drain-pending-only; workers hard-clamped to ≤4
  in code.
- B-5 Every LLM decision has a total deterministic fallback (select →
  `_select_fallback`; expand → fallback child; lineage → `continue`; root select →
  index 0). New LLM decisions need the same.
- B-6 Hooks never kill the run: every optional path in `_run_loop` is
  try/except + warn. Governance failure degrades, never crashes (fail-closed is a
  deliberate, documented deviation — Task 04).

**Contracts and formats**

- B-7 Checkpoint triple `tree.json` / `nodes_tree.json` / `results.json`: names,
  key order, `indent=2, ensure_ascii=False` are a GUI + paper-pipeline contract;
  `Node.to_dict()` keys likewise; additive only. Per-node
  `_save_tree_incremental(force=True)` is the SIGTERM-resume guarantee; the 1 s
  throttle + lock are pinned by tests.
- B-8 Reserved metrics keys (`_scientific_score` — written only when composite > 0,
  `_axis_scores`, `_sterile`, `_comparison_found`, `_params_dict`,
  `_measurements_dict`) are read by ≥7 modules.
- B-9 `node_report.schema.json` `schema_version: const 1` + its required set;
  `build_node_report` / `write_node_report` never raise.
- B-10 Paper pipeline: `run_pipeline` signature/return; `ari.pipeline` monkeypatch
  surfaces; file-order stage execution (no topo sort); `depends_on` /
  `skip_if_exists` semantics; error-only-dict ⇒ stage failure; the gate blocking
  matrix (draft never blocks; `always_block_on` blocks at final in any mode; gate
  fails open on infrastructure errors); `% CLAIM` anchors survive
  write→refine→final gate; the mirrored registries
  (`claim_gate/numeric.py` ↔ `ari-skill-transform/src/claims.py`;
  `claim_gate/latex.py` ↔ `ari-skill-paper/src/claim_links.py`) stay in sync;
  `science_data.json` never mutated downstream; reviewer independence of
  `review_compiled_paper`.
- B-11 MCP: `call_tool` returns exactly `{"result": str}` or `{"error": str}`;
  `_set_current_node` never LLM-visible; the CoW pair atomic under `_cow_lock`;
  one shared client per run; retries re-execute tools (idempotency required);
  `phase: none` skills never spawned; PYTHONPATH/interpreter ordering.
- B-12 Agent loop: OpenAI message-pairing (assistant-with-tool_calls followed by
  its contiguous tool block) — injections must use the deferred-user-message
  pattern; pinned-marker survival for always-present context; the LLM can only
  self-finish as success; holds must have bounded expiry so force-finish backstops
  still terminate.

**Determinism, provenance, scoping**

- B-13 P2: `bfts_prompt_builder`, axis derivation, the claim gate,
  `link_paper_claims`, `merge_reviews`, prompt/config loaders stay LLM-free and
  deterministic; no wall-clock/git-SHA/host in any hash; `hash12 = sha256[:12]` is
  the single prompt-hash scheme; byte-identical loader semantics.
- B-14 P5: default runs leave no `bfts_web_provenance.json`; any RQGM time-varying
  input needs an analogous durable marker (or deterministic derivation).
- B-15 `ARI_CHECKPOINT_DIR` is the single run pin; no `~/.ari` writes/refs (hard CI
  gates); all new state checkpoint-scoped; new checkpoint-root filenames
  registered in `META_FILES` / `_TRACE_FILES` / node-report blocklists.
- B-16 Memory: ancestor scoping (no sibling recall), CoW writes (`cow_node_id`),
  names-only cross-branch leakage discipline, core→skill import funnel confined to
  `ari/memory/**`; skills import only `ari.public.*`.
- B-17 Score comparability within a run: axes are deliberately frozen at run start
  (root_idea_selector docstring). Epoch re-weighting invalidates cross-epoch
  `_scientific_score` comparisons used by Rule A, stagnation detection, and
  fallback ranking — an explicit design decision (Task 10), never a silent change.

**Idea/lineage layer**

- B-18 `ideas[0]` is the directive; pinned ideas stay in front; one-shot markers
  (`_root_choice`, `_inherited_from`) respected; rewrites content-visible (the
  evaluator axis refresh is content-hash keyed); single-writer discipline on
  `idea.json`; degrade-never-block at every tier; `ari-skill-idea/vendor/virsci`
  never edited;
  MCP stdio hygiene (no stdout prints in skills); `lineage_decisions.jsonl` as the
  shared audit log (new `trigger` values preferred over new files);
  directive-vs-catalog two-path separation; launch gates (recursion depth,
  `parent_terminated`), `rate_limit_per_run`, `ARI_MAX_RECURSION_DEPTH` bound
  autonomous escalation.

**Test/CI/docs surfaces**

- B-19 Contract snapshots (public API set, CLI tree, MCP tool names)
  regenerate-or-red; `ari --help` byte order; test-mockability indirection
  (`ari.cli` late-bound lookups); the 4 prompt snapshot layers + the new-prompt
  checklist; readme-sync Contents rows; tri-language doc co-change + `sources:`
  front-matter gates; deprecations via `DEPRECATION_REMOVAL.md` +
  `ari-core/ari/_deprecation.py`; documenting an env var / checkpoint file in
  `docs/reference/` SemVer-freezes it.

### 5.9 Open questions table (each assigned to its owning downstream plan)

| # | Open question | Owner |
|---|---|---|
| Q-1 | `ari.mode`/`rqgm.enabled` home: typed `RQGMConfig` (recommended) vs raw-YAML re-read; env override name; GUI toggle on day one? | Task 01 |
| Q-2 | Which workflow.yaml copy RQGM reads (checkpoint-first); unify or avoid the package-only readers; which knobs become hot-reloadable at epoch boundaries (flags are read once at loop start today)? | Task 01 |
| Q-3 | `build_runtime`: wrap returned objects vs extend the 6-tuple (4 positional call sites say wrap). | Task 01 |
| Q-4 | Constitution file distribution: bundled + copied-at-launch vs per-experiment; mid-run mutability protocol vs copy-once convention. | Task 01 |
| Q-5 | Resume: where mode/epoch state is restored from (tree.json is contract-frozen ⇒ new checkpoint-root file). | Task 01 |
| Q-6 | Contract-snapshot budget: zero CLI-surface change for v1? | Task 01 |
| Q-7 | Epoch state home: `epoch_state.json` + `rqgm_audit.jsonl` vs `meta.json` extension vs tree.json keys (contract risk); snapshot-only vs JSONL-truth + derived rollup. | Task 02 |
| Q-8 | Epoch scope: per-checkpoint or spanning parent/fanout children (epoch-root checkpoint vs workspace-level registry vs replicated `meta.json` fields). | Task 02 |
| Q-9 | Audit-log integrity: hash-chained records (new; needs P2-safe canonicalization) or append-only-by-convention? | Task 02 |
| Q-10 | Schema policy: optional-only additions under node_report v1 vs version bump + migration; bucketed-layout (subtask 005) awareness. | Task 02 |
| Q-11 | Who writes epoch transitions when multiple concurrent runs are in scope; throttle/lock sharing with `save_tree_incremental`. | Task 02 |
| Q-12 | Fix the `@mcp.tool()` regression on `survey`/`generate_ideas` first; fate of the exposed `_load_virsci_snapshot_papers`. | Task 03 |
| Q-13 | Staged `idea.json` compatibility: which consumers migrate to ProposalSummaryView in which order; single-writer/locking discipline once more writers exist. | Task 03 |
| Q-14 | Mid-run re-ideation at epoch boundaries? Today `generate_ideas` runs exactly once at root; workflow.yaml's `frontier_expand` declaring `tool: generate_ideas` is fiction. | Task 03 |
| Q-15 | `ARI_DISABLED_TOOLS_FOR_CHILD` is a stub — needed for "run inherited idea verbatim". | Task 03 |
| Q-16 | Map epoch exploration width onto `ARI_IDEA_VIRSCI_K/TEAM_SIZE/MAX_TEAMS` (already env-plumbed). | Task 03 |
| Q-17 | Determinism budget: which kernel decisions are pure rules vs logged-LLM with total fallback (precedent: deterministic-rule-first). | Task 04 |
| Q-18 | Fail-open vs fail-closed per check class (run-loop hooks fail open; only the paper gate blocks). | Task 04 |
| Q-19 | Who owns `_sterile`-style clamps if RQGM wraps the loop — they live in `bfts_loop.py`, not BFTS or the evaluator. | Task 04 |
| Q-20 | Fixed-verifier placement: wrapping `Evaluator` (protocol-clean but lacks tree/file-diff access) vs the run loop (current pattern). | Task 04 |
| Q-21 | **Resolved 2026-07-28 (`c050ebf`)** — granularity is N new BFTS nodes (`rqgm.epoch.boundary: node_count` / `nodes_per_epoch`; fired by `RqgmRuntime.ensure_epoch` in `ari-core/ari/rqgm/runtime.py`). The epoch layer **coexists** with the lineage-decision hook in `_run_loop` (`ari-core/ari/cli/bfts_loop.py`) — it neither subsumes nor vetoes it — with **separate** rate limits (lineage `rate_limit_per_run`; the epoch tick is node-count-driven) and **separate** audit logs (`rqgm_audit.jsonl` vs `lineage_decisions.jsonl`). Richer trigger policy (stagnation events) stays deferred to Task 05. | Task 05 |
| Q-22 | Hook mechanism: `epoch_hook` callback in `_run_loop` vs `SearchStrategy`/`NodeExecutor` decorators vs loop split (decorators miss staging/sterile gating/checkpointing). | Task 05 |
| Q-23 | Mid-node verdict channel: reuse the `emit_results`-warning + `contract_pending` hold vs a new pinned-marker deferred message; combined hold-expiry policy. | Task 05 |
| Q-24 | `_progress_cb` payload extension vs `_execute_tool_calls` wrapping for per-tool observation; thread-safety of per-node state on shared `AgentLoop` self. | Task 05 |
| Q-25 | Do both ReAct loops (AgentLoop + `react_driver.run_react`) get governed, via a shared hook interface? | Task 05 |
| Q-26 | Does the constitution span parent/child lineages (via `meta.json`/`_inherited_from`); do RQGM-initiated launches respect `rate_limit_per_run` + `ARI_MAX_RECURSION_DEPTH`? | Task 05 |
| Q-27 | Define ARI's adversarial pool ("artifacts accepted by the displaced evaluator") per role/skill. | Task 06 |
| Q-28 | Idempotency of adversary/defender/judge tools under the MCP 3-retry policy; timeout tier vs `time_limit_sec` args. | Task 06 |
| Q-29 | Judge placement: `Evaluator`-seam wrapper vs a separate governance judge with its own cost `phase`/`skill` labels. | Task 06 |
| Q-30 | On-disk home of epoch-scoped PromptSpecs: checkpoint META files vs committed `ari/prompts/rqgm/*` (all four snapshot layers apply) vs runtime-generated prompts (needs a Gate-10 carve-out + per-epoch dump + `rendered_prompt_hash` provenance). | Task 07 |
| Q-31 | Add the missing `expand_prompt` config key; use `load_versioned`'s unused `version` parameter as the pin mechanism? | Task 07 |
| Q-32 | How `prompt_version`/`prompt_registry_version` in `PromptUseRecord` get populated (epoch counter? hash-of-hashes?). | Task 07 |
| Q-33 | Loader injection: the 11 call sites construct `FilesystemPromptLoader()` directly — module-attribute patching vs config plumbing for a governed loader. | Task 07 |
| Q-34 | CI placement (extend `prompt-change-review.yml` vs new workflow, Stage-1 advisory first); skill-side prompt coverage (Gate 10 covers core only); CI hook for `scripts/tests/`? | Task 07 |
| Q-35 | Enforcing "cannot read retired prompt text" against the flat checkpoint filesystem readable by any skill via `ARI_CHECKPOINT_DIR` — access-guard design. | Task 08 |
| Q-36 | Clean-room generation as a `run_react` sandboxed rollout or a one-shot MCP tool? | Task 08 |
| Q-37 | Extending closed action/Literal sets in lockstep (`VALID_ACTIONS`; composite/frontier_score Literals ↔ registries + env allowlists) — or accept dynamic registry-keyed values? | Task 09 |
| Q-38 | Per-epoch tool-set changes: new phase strings (cache-compatible) vs mutating `disabled_tools` vs fresh MCPClient per epoch; does a `governance` phase break viz/docs consumers? | Task 09 |
| Q-39 | Flat MCP tool namespace: `rqgm_` prefix convention and/or collision detection. | Task 09 |
| Q-40 | Score comparability across epochs (B-17): freeze axes per run vs epoch-tagging scores vs per-epoch normalization; evaluator `_score_history` reset/persist on weight changes. | Task 10 |
| Q-41 | Erasure vs append-only stores: tombstoning vs epoch-tagged read-time filtering vs a separate utility ledger; a concrete staling mechanism for tree.json-derived frontier state. | Task 10 |
| Q-42 | Safe mutation of `pending`/`frontier` at boundaries (plain lists, mid-batch nodes) — the `Node.metrics` veto convention is the least-invasive channel into `should_prune`. | Task 10 |
| Q-43 | Bound `make_metric_spec` authority: the node agent self-determines evaluation criteria mid-run and MetricSpec weights outrank all others — a constitutional cap is a prerequisite to trustworthy meta-evolution. | Task 11 |
| Q-44 | Introduce a duck-typed `MCPClient` Protocol so governance proxies are type-checkable? | Task 11 |
| Q-45 | Where per-epoch token/cost ceilings are enforced — `LLMClient.complete` (global), a `NodeExecutor` wrapper (per node), or `_run_loop` between batches (per epoch); `cost_tracker` is passive and `LineageState.budget_remaining` is node-count, not dollars. | Task 12 |
| Q-46 | The ≤4 worker clamp is code, not config; timeout tiers for slow RQGM tools; cli-shim exposure of governance tools (`to_claude_mcp_config` currently leaks `_set_current_node`). | Task 12 |
| Q-47 | Which signals define epoch fitness: hard-gate report `metrics`, semantic-review `score_delta`, `review_report.json`, `ors_grade.json` — and cross-epoch comparability given `skip_if_exists` short-circuits. | Task 13 |
| Q-48 | Binary outcomes: RQGM theory uses o ∈ {0,1} Beta posteriors; ARI signals are scalar/rubric — binarize or redesign? | Task 13 |
| Q-49 | ARI's ground-truth anchor definition and curation; per-epoch output versioning for the paper pipeline (fixed paths overwritten in place). | Task 13 |
| Q-50 | RQGM budget caps must be authored, not copied — the paper's B̄ values were not extracted. | Task 13 |
| Q-51 | Which RQGM env vars / checkpoint files / config keys get documented in `docs/reference/` immediately (SemVer freeze) vs kept plan-internal until stabilized. | Task 01 (config), Task 02 (files), final call at Task 13 wrap-up |

Pre-existing warts to decide on only when touched (no owner until then): the dead
`self.experiment_goal` block at `ari-core/ari/agent/loop.py` (~line 668); the
evaluator's direct-litellm xfail (target the Protocol seam); the README v0.9.0
badge vs CHANGELOG v0.9.1 drift.

## 6. Data structures / schema changes

**None introduced by this task.** For downstream reference, the existing data
contracts that new RQGM schemas must respect (details in §4/§5):

- `idea.json` 9-key contract + `_pinned` / `_root_choice` / `_inherited_from`
  markers (§5.2) — the compatibility projection target for ProposalSummaryView.
- `node_report.schema.json` (`schema_version: const 1`, required set, sha256 file
  diffs) — extension policy in Q-10.
- The checkpoint triple + `meta.json` additive-fields convention (B-7).
- Reserved `Node.metrics` keys (B-8) — the `_sterile` convention is the model for
  any new frontier-veto flag (e.g. a future `stale` / `valid_for_frontier`
  marking, Task 10).
- Append-only JSONL record shapes (`PromptUseRecord`, `CallRecord`,
  lineage-decision records): additive-defaulted fields, absence-tolerant readers.
- The SPEC's universal record envelope (record_id, epoch_id, component_id,
  prompt_hash, role, created_at, source_refs, status) is DESIGNED in Task 02+;
  this task only notes that `prompt_hash` must be the existing `hash12` scheme
  (§5.7) and `epoch_id` flows through reserved provenance fields (Q-32).

## 7. API / class changes

**None introduced by this task.** The seam inventory downstream tasks will use
(all existing, verified):

- `SearchStrategy` / `NodeExecutor` / `Evaluator` Protocols — decorator/wrapper
  installation point is `ari-core/ari/core.py:build_runtime`.
- `MCPClient.call_tool` / `tool_manager.execute_tool_calls` /
  `available_tools_openai(suppress=...)` — tool policy and exposure.
- `build_working_context_messages` + `_PINNED_USER_MARKERS` — per-node charter
  injection.
- `lineage_decision.VALID_ACTIONS` + `_execute_lineage_decision` — governance verb
  extension.
- `_COMPOSITE_REGISTRY` / `BaseRegistry` / `_resolve_axis_weights` /
  `build_axes_for_run` — utility-policy surface.
- `JsonlTraceStore.append_trace` (dormant), `record_prompt_use`,
  `CostTracker.set_default_metadata` — provenance/audit attach points.
- `run_react` — agentic rollout harness for governance roles.
- `PromptRegistry` / `PromptEntry` / `FilesystemPromptLoader(base=...)` —
  PromptSpec substrate.

## 8. Migration / compatibility

- This task changes nothing at runtime; there is nothing to migrate.
- The compatibility posture it establishes for all downstream tasks:
  **`simple_bfts` = current ARI, byte- and behavior-identical** (the B-register in
  §5.8 is the checklist); **`ari_rqgm` = additive, config-gated, off by default**;
  **VirSci = independently toggleable, absent-safe** (its three existing
  degradation tiers are the proof that ARI already runs without it).
- The B-register is the input to Task 01's `simple_bfts` preservation policy and
  to Task 13's B0 baseline condition; each downstream plan's §8 must state which
  B-items its feature touches and how it preserves them.
- Findings in §5 are snapshots of a moving tree: if the underlying code changes
  before a downstream task consumes a finding, the downstream plan re-verifies the
  specific claim (paths + symbols are given precisely to make that cheap).

## 9. Tests

No new tests are produced by this task. Two testing outputs it does contribute:

1. **Verification performed during the investigation** (repeatable):
   - Grep verification that no `ari.mode` / `rqgm.` config key exists in the tree
     (basis of §4.11).
   - Runtime verification that `ari-skill-idea/src/server.py` registers only
     `_load_virsci_snapshot_papers` as an MCP tool (basis of the Q-12 regression;
     `python3 -c "... server.mcp.list_tools() ..."`).
   - Existence check of every file path cited in §4/§5 against the working tree.
2. **The test-surface inventory downstream tasks must keep green** (they cite it
   from here rather than re-derive it):
   - Contract snapshots: `ari-core/tests/test_contract_snapshots.py` +
     `scripts/snapshot_contracts.py` goldens (public API, CLI tree, MCP tool
     names).
   - Prompt layers: `ari-core/tests/test_prompt_extraction.py`,
     `test_prompt_snapshots.py`, `test_prompt_registry.py`,
     `test_prompt_provenance.py`, `test_bfts_prompt_selection.py`, plus Gate 10
     (`report/scripts/check_prompt_snapshots.py`).
   - Behavior pins: `test_evaluator_composite.py` (registry↔Literal parity),
     `test_evaluator_protocol.py`, `test_dynamic_axes.py`,
     `test_gui_errors.py` (incremental-save throttle), `test_no_user_home_writes.py`
     and the `refactor-guards.yml` HOME-redirect job, `_arch_boundaries.py`
     consumers (core↔skill import direction).
   - Suite topology: `pytest.ini` runs `ari-core/tests` only; skill suites run
     isolated via `scripts/run_all_tests.sh`; never import two skills' `src.server`
     in one process.

## 10. Risks

1. **Findings staleness.** This document describes HEAD of branch `RQGM` at
   investigation time. The tree moves (Dependabot merges land regularly); line
   numbers are approximate by design. Mitigation: downstream plans re-verify the
   specific symbols they touch; this plan is deleted once it is no longer the sole
   source.
2. **The idea-skill regression masks integration reality.** With `generate_ideas`
   unregistered, current runs exercise the tier-3 idea-less path — manual testing
   of anything idea-dependent will silently test the degraded path. Task 03 must
   fix registration before evaluating ProposalRouter behavior.
3. **Plan-directory CI hazards.** `docs/plans/**` is neither exempt in
   `scripts/docs/check_doc_sources.py` (`EXEMPT_DIR_SEGMENTS`) nor excluded from
   the VitePress build (`docs/.vitepress/config.ts` `srcExclude`) — committed plans
   would be published to the docs site and front-matter-checked at release.
   The PR that commits this plan set must add the `plans` exemption segment and a
   `plans/**` srcExclude entry (repo hygiene, precedent: the still-present
   `refactoring` exemption added for the now-deleted `docs/refactoring/`
   directory, and the `PLAN_homepage_redesign.md` exclusion). This is
   the one repo change coupled to Task 00.
4. **Premature SemVer freeze.** Documenting any RQGM env var / checkpoint file /
   config key in `docs/reference/` makes it public surface (release policy). All
   RQGM knobs stay plan-internal until the owning task decides otherwise (Q-51).
5. **Over-reliance on this memo.** If downstream tasks copy conclusions without
   the cited paths, deleting this plan strands them. Mitigation: every downstream
   plan's §4 must carry its own path citations (deletion criterion below).
6. **Scope creep.** The attachment-point map invites "small fixes while we're
   here" (dead code at `loop.py:668`, the cli-shim `_set_current_node` leak, the
   package-vs-checkpoint config asymmetry). None are Task 00's to fix; each is
   assigned or explicitly deferred in §5.9.

## 11. Completion criteria

This task is complete when all of the following hold (each maps to a Task 00
criterion in the spec, made concrete):

1. **Main structure of existing ARI is organized**: §4 covers all mandated
   investigation targets — BFTS loop, AgentLoop, LLMEvaluator, ari-core
   composition root, MCPClient, workflow config, idea generation, VirSci
   adapter/runtime, Story2Proposal/paper pipeline, memory/lineage/checkpoint,
   node_report, artifact structure, existing tests — each with real, verified
   repo-relative paths and key symbols. ✔ (this document)
2. **BFTS loop attachment points are clear**: §5.1 names the exact code location
   for each RQGM concept (epoch boundary, proposal generation, utility
   computation, frontier update, governance hooks) and its owning task. ✔
3. **idea.json / VirSci / ProposalRecord migration attachment points organized**:
   §5.2 records the current contract (writers, consumers, markers, degradation
   tiers), the compatibility-projection strategy, and the blocking regression. ✔
4. **Relationship to Story2Proposal organized**: §5.3 maps RQGM concepts to S2P
   mechanisms (hard gate, forward declaration, reviewer independence, blocking
   convention) and flags the epoch-wrapping constraints. ✔
5. **Existing behaviors that must not break are enumerated**: §5.8's B-register
   (B-1…B-19) is complete enough that Task 01 can define the `simple_bfts`
   preservation policy and Task 13 can define the B0 baseline from it alone. ✔
6. **Every open question is assigned**: §5.9 assigns each question found during
   investigation to exactly one owning task plan 01–13 (or records it as a
   touch-only wart). ✔
7. This file is committed under `docs/plans/ari_rqgm/` with the plan-directory CI
   accommodations of §10.3 in place, and INDEX.md lists Task 00 with its status
   and dependents.

Criteria 1–6 are satisfied by the content of this document; criterion 7 is
satisfied at commit time.

## 12. Deletion criteria

This plan file may be deleted only when all of the following hold:

- The target feature/design is merged into the main branch. *(For Task 00 this
  reads: the investigation findings have been consumed — the downstream plans
  01–13 that depend on them exist and are merged, or superseded implementations
  have landed.)*
- Corresponding tests have been added. *(For Task 00: the behaviors in the
  B-register that downstream tasks rely on are protected by the tests inventoried
  in §9, and any B-item newly relied upon by RQGM code has a regression test.)*
- CI is green.
- Key design decisions have been moved to permanent docs or code comments.
- No unresolved open questions remain, or they have been moved to another task
  plan.
- No downstream task depends solely on this plan file.
- INDEX.md task status has been updated to completed/deleted.
- Developers will not be confused by this file's absence.
- The deleted content remains available in git history.

Task-specific criteria (in addition to the above):

- Investigation results are reflected in the downstream task plans: each of
  Tasks 01–13 carries its own §4 touchpoints (with path citations) covering
  everything it consumes from this document.
- The existing-ARI touchpoint summary has been migrated to INDEX.md or to
  permanent docs (`docs/concepts/architecture.md`, `docs/concepts/bfts.md`, or a
  new concepts doc per the docs conventions in §4.12).
- Every open question in §5.9 has been resolved or moved into its owning task
  plan's own open-questions/§10 section.
- This memo is no longer the sole source of any information it contains (spot
  check: the attachment-point table §5.1, the B-register §5.8, and the migration
  map §5.2 each have a surviving home).

## 13. Delete-after checklist

Verify before deleting this file:

- [ ] Implementation is complete.
- [ ] Tests exist.
- [ ] CI is green.
- [ ] Key design decisions have been moved to permanent docs.
- [ ] Unfinished items have been moved to another task plan.
- [ ] INDEX.md has been updated.
- [ ] Deleting this plan file will not strand any developer.
- [ ] The deletion reason can be stated in the commit message.

Task-specific items:

- [ ] Each downstream plan 01–13 (or its successor implementation/doc) cites its
      own ARI touchpoints and does not link back to this file for them.
- [ ] The B-register (§5.8) content lives on in permanent docs or in the
      downstream plans' §8 sections.
- [ ] All Q-1…Q-51 rows are closed or re-homed.
- [ ] The `ari-skill-idea` tool-registration regression (Q-12) is fixed or
      tracked in Task 03 / an issue — not only here.
- [ ] The plan-directory CI accommodations (§10.3) either remain valid for the
      remaining plans or are reverted with the last plan's deletion.
