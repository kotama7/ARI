# Orchestration Status — ARI Refactoring Program

> **Progress ledger** for the autonomous orchestrator (see
> `docs/refactoring/HANDOFF_PROMPTS.md` §Ⓐ). This file is the **source of truth**
> for progress and makes the run **resumable**: re-reading the handoff in a fresh
> session continues from here.
>
> Branch: `whole_refactoring` · Repo: `/home/t-kotama/workplace/ARI`
> Status vocabulary: `TODO → IN_PROGRESS → DONE` (or `BLOCKED:<reason>`).
> Started: 2026-07-01.

## Baseline (captured before any subtask)

- Python `3.13.2`, ruff `0.15.2`, node `v20.19.5`, npm `10.8.2`; `radon` NOT installed.
- `ruff check ari-core --statistics` → baseline **661**; **now 660** after 003 removed a dead import (ratchet: may only DECREASE — future subtasks keep it ≤660).
- `python -m compileall -q ari-core ari-skill-* scripts` → **exit 0** (pass).
- `pytest ari-core/tests -q` baseline → **2413 passed, 16 skipped** (111s, exit 0). *(clean green)*
- HEAD at start: `93d9662865fc5e97a1950a7ec19ac06ace32e562`.

## Hard gate — ✅ OPEN (all 9 inventories DONE, 2026-07-01)

All **nine inventories** are DONE: **001, 002, 020, 036, 045, 053, 059, 060, 067**.
Central verification: runtime tree unchanged (git clean outside reports/), ruff
`ari-core` still 661, compileall exit 0, pytest baseline trivially preserved (no
runtime `.py` touched). Runtime-code-change subtasks are now eligible (per their
own dependency edges + REVIEW_REQUIRED rulings).

**Operating directive (2026-07-01, from repo owner):** run **FULLY AUTONOMOUS** —
drive Wave 2 AND the runtime waves non-stop; resolve REVIEW_REQUIRED items from the
planning docs + primary sources where derivable; only stop for genuinely underivable
ones. Each runtime edit is a scoped, revertable commit. Do NOT push.

## Subtask ledger

Legend — Rt = Runtime Code Change (Yes/No). Phase per `007_subtask_index.md`.

| ID | Title | Phase | Risk | Rt | Depends On | Status | Commit |
|----|-------|-------|------|----|-----------|--------|--------|
| 001 | measure_complexity_and_dependencies | 1 | Low | No | — | DONE | e0662c7 |
| 002 | inventory_legacy_obsolete_and_duplicate_code | 1 | Low | No | — | DONE | d286dec |
| 003 | consolidate_config_configs_sonfigs | 2 | High | Yes | (gate) | DONE* | 617678e |
| 004 | define_runtime_path_policy | 2 | Low | No | — | DONE | 93d9662* |
| 005 | consolidate_checkpoint_workspace_experiment_paths | 2 | High | Yes | 004 | TODO | — |
| 006 | introduce_runtime_path_resolver | 2 | Medium | Yes | 004 | DONE | 2c8edd5 |
| 007 | define_core_interfaces_and_protocols | 3 | Low | No | — | DONE | 93d9662* |
| 008 | extract_model_backend_interface | 3 | High | Yes | 007 | DONE | a045649 |
| 009 | extract_evaluator_interface | 3 | Medium | Yes | 007 | DONE | 38977a7 |
| 010 | extract_artifact_checkpoint_trace_store | 3 | High | Yes | 007 | TODO | — |
| 011 | separate_bfts_strategy_from_react_loop | 3 | High | Yes | 007 | TODO | — |
| 012 | refactor_pipeline_stage_architecture | 3 | High | Yes | 007 | TODO | — |
| 013 | refactor_memory_boundary | 3 | High | Yes | 007 | TODO | — |
| 014 | refactor_registry_and_factory_layer | 3 | High | Yes | 007 | DONE | 6a75eb9 |
| 015 | refactor_dashboard_viz_api_services | 4 | High | Yes | (gate 020) | TODO | — |
| 016 | clean_merge_or_quarantine_legacy_code | 2 | High | Yes | 002 | TODO | — |
| 017 | update_docs_and_examples | 10 | Low | No | — | TODO | — |
| 018 | add_tests_for_architecture_boundaries | 10 | Low | No | — | DONE | 0319dae |
| 019 | final_quality_report | 11 | Low | No | — (LAST) | TODO | — |
| 020 | inventory_viz_dashboard_api_contracts | 4 | Low | No | — | DONE | 43b143a |
| 021 | extract_viz_services_from_routes | 4 | Medium | Yes | 020 | DONE* | baf2add |
| 022 | define_dashboard_dto_and_schema_tests | 4 | Low | No | 020 | DONE | 7d6ee50 |
| 023 | separate_viz_file_io_from_route_handlers | 4 | Medium | Yes | 020 | TODO | — |
| 024 | refactor_bfts_tree_visualization_adapter | 4 | Medium | Yes | 020 | DONE | b2071cd |
| 025 | add_complexity_checker_script | 8 | Low | No | 001 | DONE | 6720ca8 |
| 026 | add_import_boundary_checker_script | 8 | Low | No | — | DONE | fe34241 |
| 027 | add_docs_source_sync_checker_script | 8 | Low | No | 003 | DONE | d1902af |
| 028 | add_directory_policy_checker_script | 8 | Low | No | 003 | DONE | 9180503 |
| 029 | add_public_api_contract_checker_script | 8 | Low | No | — | DONE | 5c5c10a |
| 030 | add_viz_api_schema_checker_script | 4 | Low | No | 020 | DONE | 7bd5654 |
| 031 | add_quality_report_generator | 8 | Low | No | 001 | DONE | d7bbd29 |
| 032 | add_quality_script_ci_plan | 9 | Low | No | — | DONE | 11cd088 |
| 033 | add_generated_files_gitignore_policy | 2 | Low | No | — | DONE | 0ad0b19 |
| 034 | add_contract_snapshot_fixtures | 10 | Low | No | — | DONE | 7af9e0f |
| 035 | add_refactoring_progress_tracker | 10 | Low | No | — | DONE | 4be8796 |
| 036 | inventory_hardcoded_prompts | 7 | Low | No | — | DONE | 9619ebf |
| 037 | define_prompt_template_policy | 7 | Low | No | 036 | DONE | 93d9662* |
| 038 | introduce_prompt_registry_and_loader | 7 | Medium | Yes | 036 | DONE | ed6171e |
| 039 | extract_agent_and_bfts_prompts | 7 | Medium | Yes | 036 | DONE* | no-op |
| 040 | extract_evaluator_and_llm_judge_prompts | 7 | Medium | Yes | 036 | DONE | 5ce8c75 |
| 041 | extract_pipeline_and_paper_generation_prompts | 7 | Medium | Yes | 036 | DONE | f4a22cf |
| 042 | add_prompt_snapshot_tests | 7 | Low | No | 036 | DONE | 2bc2e94 |
| 043 | add_prompt_checker_script | 7 | Low | No | 036 | DONE | dffefdf |
| 044 | add_prompt_version_tracking_to_run_metadata | 7 | Medium | Yes | 036 | DONE | 8f59cf0 |
| 045 | inventory_github_workflows | 9 | Low | No | — | DONE | 8842a5f |
| 046 | design_quality_ci_integration | 9 | Low | No | 045 | DONE | 93d9662* |
| 047 | add_pr_template_quality_checklist | 9 | Low | No | 045 | DONE | 78c9eea |
| 048 | add_issue_templates_for_refactoring | 9 | Low | No | 045 | DONE | e869a90 |
| 049 | add_contract_check_workflows | 9 | Low | No | 045 | DONE | 89aef2f |
| 050 | add_docs_sync_workflow | 9 | Low | No | 045 | DONE | ae7bea1 |
| 051 | add_prompt_change_review_workflow | 9 | Low | No | 045 | DONE | 7b9b198 |
| 052 | add_dependabot_and_actions_policy | 9 | Low | No | 045 | DONE | a40ab08 |
| 053 | inventory_reference_roots | 1 | Low | No | — | DONE | b4d7706 |
| 054 | add_reference_graph_analyzer | 1 | Low | No | 053 | DONE | d73dd9e |
| 055 | add_dead_code_candidate_checker | 1 | Low | No | 054 | DONE | d734d87 |
| 056 | classify_unused_functions_and_files | 1 | Low | No | 055 | DONE | 48d40a0 |
| 057 | delete_safe_dead_code_candidates | 2 | High | Yes | 056 | DONE | 386090f |
| 058 | add_dead_code_checker_to_quality_report | 8 | Low | No | 057 | DONE | 2bae2dc |
| 059 | inventory_dashboard_frontend_backend_structure | 5 | Low | No | — | DONE | f43d9f1 |
| 060 | inventory_dashboard_api_contracts | 5 | Low | No | 059 | DONE | dcb0389 |
| 061 | define_dashboard_dto_and_schema_policy | 5 | Low | No | 059 | DONE | 93d9662* |
| 062 | refactor_dashboard_backend_routes_to_services | 5 | High | Yes | 059 | TODO | — |
| 063 | refactor_dashboard_frontend_api_client_and_types | 5 | High | Yes | 059 | TODO | — |
| 064 | refactor_dashboard_state_and_component_boundaries | 5 | High | Yes | 059 | TODO | — |
| 065 | add_dashboard_contract_and_schema_tests | 5 | Low | No | 059 | DONE | 0bca698 |
| 066 | add_dashboard_build_and_ci_plan | 5 | Low | No | 059 | DONE | 0000cec |
| 067 | inventory_dashboard_visible_settings | 6 | Low | No | 059 | DONE | 4252a79 |
| 068 | define_dashboard_information_architecture | 6 | Low | No | 059 | DONE | 93d9662* |
| 069 | design_dashboard_progressive_disclosure | 6 | Low | No | 059 | DONE | f878986 |
| 070 | refactor_dashboard_settings_panel | 6 | High | Yes | 059 | TODO | — |
| 071 | add_dashboard_developer_mode | 6 | Medium | Yes | 059 | TODO | — |
| 072 | improve_dashboard_empty_loading_error_states | 6 | Medium | Yes | 059 | TODO | — |
| 073 | add_dashboard_ux_regression_checks | 6 | Low | No | 059 | DONE | ecabd7c |

## Blocked / Human-decision notes

*(Record here: blockers, ambiguities requiring a human ruling, and any planning
doc whose Retirement Condition becomes satisfied — do NOT git rm planning docs;
leave that to a human per the Document Retirement Policy.)*

- **[002] Owner-routing drift (non-blocking):** `004_legacy_obsolete_inventory.md`
  routed the MCP-idiom and ReAct-loop seams to subtask **016**, but the live
  `007_subtask_index.md` assigns them to **010** (skill consistency) and **011**
  (BFTS/ReAct split). The 002 report followed the canonical 007 index and recorded
  the discrepancy. Human ruling optional; live index is authoritative here.
- **[002/013/017] `ARI_AGENT_ENV_PATH → ~/.ari/agent.env` fallback:** remains
  `REVIEW_REQUIRED` (docs vs v0.5.0 checkpoint-scoping). Code-path verification
  deferred to subtasks 013/017 per plan; do not edit docs before verifying against
  `config/__init__.py`/`paths.py`.
- **[045] Allow-list count 14 vs 13 (doc drift):** subtask 045 §1/§3/§13 and
  `012` say the `refactor-guards.yml` `~/.ari` allow-list has **14** entries; the
  live file has **13** `:!` exclude pathspecs + **1** include pathspec (`ari-core/ari/**.py`).
  "14" only if the include line is counted. Affects 049 reuse text — doc-owner ruling.
- **[045] `012` internal numbering vs 007 index:** `012_github_workflow_integration_plan.md`
  §15/§16 assigns checker ownership (e.g. check_complexity) to subtask 045; the
  canonical 007 index says 045 = inventory only. Reports follow 007. Also `012` §16
  is stale ("subtasks/ and reports/ empty" — both now populated). Reconciliation is
  a 046 / human decision.
- **[045] Two workflow REVIEW_REQUIRED items** for later CI subtasks (046/049/050):
  `pages.yml:21` README.md-only path filter; `refactor-guards.yml:82` uses
  `origin/<base_ref>` (movable mid-run) rather than `github.event.pull_request.base.sha`.
- **[053] New MCP tool-name collision:** `read_file` is registered by BOTH `coding`
  and `orchestrator` skills; the flat `_tool_registry` (last-skill-wins, `client.py:283`)
  silently clobbers. REVIEW_REQUIRED — relevant to subtasks 010/014.
- **[053] `publish.schema.json:51` enum lists `"s3"`** but there is no `s3` branch in
  `_load_backend` and no `backends/s3.py` — `"s3"` correctly excluded from the
  live-by-string allow-list. Enum-vs-impl drift; REVIEW_REQUIRED for subtask 014.
- **[053] `ARI_MEMORY_BACKEND`** is set (`config/__init__.py:316`) but has no core
  consumer (core hardcodes `LettaMemoryClient`, `core.py:130`) → dynamic-reference
  risk, not orphan; note for subtask 013.
- **[053] Numbering drift:** `013` §8.1/§10 assign `analyze_references.py` to 053;
  the canonical 007 index assigns it to 054. Report follows 007. REVIEW_REQUIRED.
- **[036] `replicator.md` appears unwired:** subtask 036 §5.3 and plan `011` §2.3 claim
  it loads at `ari-skill-paper-re/src/server.py:66`, but that line reads the *paper*
  file; no runtime `read_text()` of `replicator.md` exists (live prompt comes from
  vendored `paperbench...templates`). Orphaned/mirror-only → REVIEW_REQUIRED for 038
  (wire it, keep as explicit mirror, or retire).
- **[036] `011`-vs-`036` rubric-builder divergence:** `011` §5.x says
  `rubric.py`/`rubric_template.py` are "not prompt text — leave in place"; subtask
  036 §8.8 says `MOVE_TO_CONFIGURABLE_PROMPT`. Both recorded; 037/041 must reconcile.
- **[059] Minor plan-text imprecisions (non-blocking, corrected in report):** parent
  §2/§5.3 "12 feature folders + common/" → tree has 12 dirs *including* `common`;
  §7.1 Table-C `Settings/ → api_ollama` example is imprecise (container served inline
  via `ari.container`; SettingsPage calls neither api_process nor api_ollama).
- **[020] F6a — real method mismatch (candidate bug):** the frontend
  `requestPaperbenchReport` POSTs `/api/paperbench/run/<jid>/report`, but only a GET
  `/report` branch exists → the POST falls through to the `else` 404. For 021/023 to
  reconcile (do NOT fix during an inventory). Dashboard-API contract note.
- **[020] F2 — CORS-omit scaffold correction:** the 020 plan §6.4 lists
  `routes.py:710/740/815/905/967` as CORS-omit sites, but live source SETS
  `Access-Control-Allow-Origin: *` there; the genuine omissions are `GET /state`
  (662) and `GET /api/gpu-monitor` (668-672). Ground truth recorded.
- **[020] F7 — `_status` smuggling only partially wired:** `POST /api/settings`
  (`_api_save_settings`) sets `_status:400` but the router never pops it
  (`routes.py:1036`), so a 400 leaks into the JSON body while HTTP stays 200; 4 other
  pop-sites call handlers that never set `_status`. REVIEW_REQUIRED for 011/021.
- **[020] Other findings for later viz waves:** F6b (10 endpoints with no `api.ts`
  wrapper), F8 (GET-with-write via `_ensure_paper_dir`), F9 (two divergent traversal
  guards), F10 (restart-losing `_JOBS`), F11 (legacy `~/.ari/publish.yaml`), F12
  (`/api/env-keys` secret readback). `WIZARD_ROUTES` confirmed dead code.
- **[067] `Settings` type field count = 36, not 35:** subtask 067 §2/§5 and the 059
  report say 35; `types/index.ts:39-74` has 36 declarations (extra optional
  `llm_base_url?` at :44). Treat 36 as ground truth for 068/070.
- **[067] New plaintext-secret persistence:** `semantic_scholar_key` and
  `letta_api_key` persist to `settings.json` in cleartext (`_api_save_settings:230`);
  only `llm_api_key`/`api_key` are diverted to `.env`. Routed to 071. REVIEW_REQUIRED.
- **[067] FE/backend Letta-embedding default mismatch:** FE default
  `openai/text-embedding-3-small` (`SettingsPage:88`) vs backend `letta-default`
  (`api_settings.py:164-166`). Routed to 070.
- **[067] `letta_deployment` declared-but-unpersisted** (select never read/written to
  `/api/settings`; only sent to `restartLetta`); and 8 FE-written keys have no backend
  default (`llm_backend, llm_base_url, slurm_partitions, ssh_*`) — survive only via
  `{**defaults, **saved}` passthrough. Routed to 070; do not drop the passthrough.
- **STRUCTURAL: "verify-only" subtasks (commit marked `*`).** Some define/policy
  subtasks declare in their own §9 that the deliverable IS the subtask `.md` itself
  (authored in planning commit `93d9662`). For these the implementer's job is to
  VERIFY the doc is grounded against the live tree, not to re-create it. **004** is
  the first confirmed case (deliverable = `subtasks/004_define_runtime_path_policy.md`;
  verified fully grounded, no drift). Marked DONE with commit `93d9662*` (the `*` =
  pre-existing deliverable, verified this run — no new artifact commit). Watch for the
  same pattern in other design subtasks (007/037/046/061/068/069…); each agent reads
  its §9 and either creates a new reports/ doc or verifies the existing one.
- **[004] Minor grounding nuance (flagged, not edited):** §6 item 1 lists `cli/run.py:273`
  as an `ARI_CHECKPOINT_DIR` "bypass" example, but live `:273` is a comment and the
  adjacent `:280` uses the `PathManager.checkpoint_dir_from_env()` helper (not a
  bypass). Accurate as a region pointer; imprecise as a bypass example. For 006.
- **[032] Cross-workflow aggregation gap:** GitHub Actions `needs:` cannot span
  workflows, so a single `quality-report` job cannot directly aggregate gates hosted
  in a different workflow. 032 §8 records Option A (aggregator re-invokes checkers) vs
  Option B (`workflow_run` trigger) → REVIEW_REQUIRED for subtask 049.
- **[037] verify-only DONE:** §9 says the deliverable is `subtasks/037_*.md` itself
  ("the only file written"); it pre-exists (93d9662) and its groundings re-verified
  against the live tree. The agent mistakenly also created a redundant
  `reports/037_prompt_template_policy.md` (analogizing to inventory subtasks) — I
  DISCARDED it to keep a single canonical policy source. The two 036 open items
  (rubric divergence → 041; unwired replicator.md → 038) stay REVIEW_REQUIRED above.
- **[007] HIGH — `006` vs 007-index subtask-number divergence (affects Waves 3-8):**
  `006_target_architecture_plan.md` §3/§4 maps abstractions to subtask numbers
  DIFFERENTLY than the canonical `007_subtask_index.md`. E.g. `006` §4 says subtask
  007 = "BaseModelBackend, BaseCostTracker, BaseLogger" and 010 = "BasePipelineStage";
  the index says 007 = define_core_interfaces, 008 = extract_model_backend, 010 =
  extract_artifact_checkpoint_trace_store. **The 007 catalog + all my runtime-wave
  agents follow the canonical 007 INDEX numbering, NOT 006's §3/§4 headers.** Runtime
  agents for 008-014 must be told this explicitly. Pre-existing 006 doc drift.
- **[007] Optional protocol stubs NOT added:** 007 §7.3/§13.6 make the 8 behavior-
  neutral `ari/protocols/*.py` stub modules OPTIONAL. Skipped — each extraction
  subtask (008-014) adds its own Protocol as it lands (avoids empty scaffolding that
  008-014 would rewrite). `protocols/__init__.py __all__` unchanged.
- **[007/061] Minor doc citation drifts (verify-only, not edited):** run_pipeline
  `def` is at `orchestrator.py:155` (not `:548`, which is the inner while-loop);
  several line/LOC counts off by 1-2 in 006/007/061. Cosmetic; groundings otherwise
  hold. Downstream implementers should re-grep, not trust exact line numbers.
- **[046 vs 032] Two overlapping CI-integration plans — RESOLUTION for 049-052:**
  046 (subtask doc, planning) duplicates ~80% of `reports/032_quality_script_ci_integration.md`
  (topology, 4-stage table, allow-list, base.sha mandate, --json aggregation). 032 §11.3
  already said 046 should reference/MERGE into 032. **Decision (autonomous): treat 032
  as the AUTHORITATIVE CI-wiring plan; 046 is design rationale.** 049-052 agents will be
  told to follow 032 for actual workflow content. Doc-restructuring (thin-delta 046)
  deferred to a human (planning-corpus edit). Also: 046 repeats the "14-entry allow-list"
  miscount (really 13 excludes + 1 include) and assumes a nonexistent subtasks README.
- **[068] Pre-existing doc-gate reds (NOT mine; for docs/hygiene wave 017/013):** HARD
  gate `check_doc_links.py --html-only` = GREEN (0 broken). Advisory reds are pre-existing:
  ~60 broken plain-markdown links in `docs/zh/index.md` + `docs/017`; 2 invalid-role
  errors in `docs/refactoring/006_target_architecture_plan.md`; readme_sync's 4 frontend/
  report drifts. None introduced by this program's subtasks.
- **[048] Out-of-band repo labels needed (human/gh action):** the issue templates
  reference labels `refactoring` and `contract-regression` which don't exist as repo
  labels; GitHub Forms silently drops unknown labels. Create via `gh label create
  refactoring` / `gh label create contract-regression` (cannot be a tracked file).
- **[052] Deferred least-privilege `permissions:`** on the 4 read-only workflows
  (docs-change-coupling, docs-sync, readme-sync, refactor-guards) — skipped this pass
  to avoid parallel-write conflicts; additive follow-up (pages.yml keeps its elevated
  perms). Documented in CONTRIBUTING.md P4.
- **[055] CRITICAL de-risking — `SAFE_DELETE_CANDIDATE = 0`:** the dead-code checker,
  applying the 013 §7 hard-downgrade firewall over the (intentionally sparse) 054
  graph, finds **zero** safe-delete candidates (345 REVIEW_REQUIRED under-traced-seam,
  125 DYNAMIC, 192 PUBLIC_CONTRACT, 1324 LIVE). ⇒ subtask **057** (delete safe dead
  code, the only High-risk DELETE in the chain) will delete NOTHING — it becomes a
  documented no-op. 056 (classify) consumes this. Big risk reduction for Wave 3.
- **[043] killed mid-self-review but files were complete:** 043 was user-stopped during
  its final self-check; all 4 files were already written and verified correct by the
  orchestrator (runs --json exit 0, 11-in-40 tests pass, ruff-clean). Committed dffefdf.
- **ULTRACODE ON (2026-07-01):** remaining waves (esp. the 27 runtime subtasks) will be
  driven via the Workflow tool with adversarial verification, per the owner's ultracode
  directive. Runtime subtasks run sequentially / worktree-isolated (never parallel on
  shared runtime files) with full `pytest ari-core/tests` after each.
- **INCIDENT (2026-07-02) — concurrent runtime agents corrupted the tree; recovered.**
  A user-stopped 010 agent kept running (the stop didn't terminate it), re-applied
  its work after I reverted it, and raced the 044 agent on `checkpoint.py`/`paths.py`.
  Both were incomplete-to-attribute (overlapping edits). Recovery: `git reset --hard`
  to the 006-DONE HEAD (9244a78) + `git clean -fd` → clean green 43/73 (compileall 0,
  ruff 661). 010's + 044's uncommitted work discarded; both to be redone.
  **HARD RULE going forward: run runtime-code agents STRICTLY ONE AT A TIME** — never
  launch a second runtime agent until the previous is confirmed DONE (completion
  notification, not a stop) and committed. Verify no active agent (TaskList) before
  each launch. Non-overlapping non-runtime doc/report agents may still parallelize.
- **[039] verified NO-OP (already externalized).** Per the authoritative 036
  inventory, the 4 agent/BFTS templates (agent/system, orchestrator/bfts_*) are
  already externalized + byte-pinned (test_prompt_extraction hashes green); 036 §7
  routes ZERO inline strings to 039, and 039 §8.1 makes 036 the tiebreaker. Agent
  did NOT fabricate extractions. DIVERGENCE (REVIEW_REQUIRED): 039's plan text
  speculatively lists inner prose/scaffolding (loop.py _MEMORY_RULES_PER_NODE,
  user_content, bfts expand() scaffolds) that 036 deliberately did NOT sanction as
  EXTRACT (they're dynamic fills of already-externalized templates, tagged
  KEEP_INLINE). Whether to expand scope + extract them is a human/architect call;
  it would need new snapshot fixtures + README reconciliation. Marked DONE per 036.
- **DEFERRED CI subtasks (need checkers to exist first):** 049 (contracts.yml +
  refactor-guards jobs → needs 026/029/030 + 028/055), 050 (docs-sync.yml append),
  051 (prompt-change-review.yml → needs 043). Will run after their checkers land, on
  the "additive CI wired last" principle. NOT started yet.
- **LESSON — parallel-write hazard (Phase-8 checkers):** 025/026/029/054 share
  `scripts/quality/_common.py` + `scripts/README.md` + per-dir READMEs. Running them
  in parallel on the shared worktree created contested edits; `readme_sync --write` is
  harvest-based (collaborative-safe) but a **final repo-wide `readme_sync --write`
  reconciliation is required once all Phase-8 checkers land** (fills the `— TODO`
  README stubs). **For the RUNTIME waves (008-014 touch ari-core/ari/; 062-064 touch
  viz/) DO NOT run file-overlapping subtasks in parallel on the shared tree** — run
  them sequentially or with `isolation: worktree`.

## Run log

- 2026-07-01: Orchestrator initialized. Read 000/007/010 + subtask 001. Baseline
  gates captured (ruff 661, compileall pass, pytest 2413 passed / 16 skipped).
  Ledger created. Starting the nine inventories (hard gate).
- 2026-07-01: Inventories 001/002/045/053/059/036 DONE and committed (each a
  read-only report under reports/; tree clean, gates unchanged). 059 unblocked
  060+067 (dispatched). 020 still running. Grounding corrections + REVIEW_REQUIRED
  items from agents recorded above.
- 2026-07-01: Wave-2 batch 1 (checkers 025/026/029/054 + docs 032/033/037/004) and
  batch 2 (design docs 007/046/061/066/068/069) DONE. Robust "verify-or-create per §9"
  instruction adopted after 037 over-produced: agents now read their own §9 "In this
  subtask" table — verify-only (004/007/037/046/061/068) create nothing; new-artifact
  (066/069) create one reports/ doc. Minor grounding drifts recorded (066 .gitignore
  lines 108-110/128 not 113/114; server serve path is static/dist/ not dashboard.html;
  069 CostSummary :79-86). All committed; tree clean between commits.
- 2026-07-01: **All 9 inventories DONE** (020→43b143a, 067→4252a79, 060→dcb0389).
  HARD GATE OPEN. Central verification passed (runtime tree unchanged; ruff 661;
  compileall 0). Next: Wave 2 = non-runtime checkers/policy/design docs that only
  add new files (025, 031, 026, 029, 037, 042, 043, 046-052, 061, 065, 066, 068,
  069, 073, 004, 032, 033, 034, 035, 007, 022, 030) — none gated by the hard gate.
  Runtime waves (3-8) follow, gated per-subtask by REVIEW_REQUIRED rulings.
