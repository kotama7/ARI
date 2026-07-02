# Refactoring Progress Tracker

> **Living status ledger** for the ARI refactoring program (subtasks `001`–`073`).
> This is the deliverable of **subtask 035** (`add_refactoring_progress_tracker`).
> It records *execution status* on top of the immutable scope/dependency metadata
> in `docs/refactoring/007_subtask_index.md`.
>
> **Source of truth:** the identity columns below (ID / Name / Phase / Depends /
> Runtime) are a **read-only mirror** of `docs/refactoring/007_subtask_index.md`.
> **If they disagree, the index wins** — fix the index, then re-mirror here; never
> "correct" scope or dependencies in this tracker.
>
> **Not** a gate: this document is advisory. It records that a subtask is blocked
> by its dependencies; it never blocks anything itself. It carries no VitePress
> `sources:` front-matter and needs no `README.md` (`docs/refactoring/reports/` is
> outside readme-sync / VitePress-publish coverage).
>
> **Distinct from** `docs/refactoring/reports/orchestration_status.md` (the
> orchestrator's own run ledger). This file is the subtask-035 program tracker;
> the two are kept independently and may be cross-checked.
>
> Generated 2026-07-02, pinned to committed state at **HEAD `4f04da8`**. Statuses are
> **evidence-derived** (merged `git log` commit + deliverable-on-disk), never inferred
> (design principle P2 / §7.6), so this snapshot is reproducible from git history. A
> present `subtasks/NNN_*.md` plan means the *plan* was written, **not** that code
> landed. **Concurrency note:** at generation time other orchestrator agents had
> uncommitted, in-flight deliverables in the working tree (subtasks 022, 042, 056);
> because they were not yet committed at HEAD `4f04da8` they are recorded per their
> committed status with a re-sync flag in Notes — promote them when their PRs merge.

## Status legend (execution state)

Distinct from the code-classification vocabulary
(`KEEP / ADAPT / MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED`),
which describes what happens to a *code artifact*, not the *progress* of a subtask.

- `not-started` — no implementation work merged (default seed).
- `in-progress` — a branch/PR is open or partial work landed.
- `blocked` — a `Depends` predecessor or an inventory gate is not yet `done`.
- `in-review` — implementation complete, PR under review.
- `done` — merged **and** its deliverable is present/verified on disk.
- `deferred` — intentionally postponed (reason in Notes).

## Phase rollup

Phases 1–11 are populated. **Phases 12 and 13 do not exist** as populated phases in
this program (`007_subtask_index.md:382-390`); no subtask maps to them.

| Phase | Title | done | in-progress | blocked | not-started | done/total |
|---|---|---|---|---|---|---|
| 1 | Measurement & Inventory | 5 | 0 | 0 | 1 | 5/6 |
| 2 | Repository Hygiene | 2 | 0 | 1 | 4 | 2/7 |
| 3 | Core Architecture | 1 | 0 | 0 | 7 | 1/8 |
| 4 | Viz / Dashboard Backend | 2 | 0 | 0 | 5 | 2/7 |
| 5 | Dashboard Frontend | 4 | 0 | 0 | 4 | 4/8 |
| 6 | Dashboard UX | 3 | 0 | 0 | 4 | 3/7 |
| 7 | Prompt Management | 3 | 0 | 0 | 6 | 3/9 |
| 8 | Quality Scripts | 3 | 0 | 3 | 1 | 3/7 |
| 9 | GitHub Integration | 6 | 0 | 0 | 3 | 6/9 |
| 10 | Docs and Tests | 0 | 1 | 0 | 3 | 0/4 |
| 11 | Final Report | 0 | 0 | 0 | 1 | 0/1 |
| **All** | — | **29** | **1** | **4** | **39** | **29/73** |

**Program total: 29/73 done, 1 in-progress, 4 blocked, 39 not-started.**

## Inventory-gate status

The **nine inventory gates** (`001, 002, 020, 036, 045, 053, 059, 060, 067`;
`000_master_refactoring_plan.md:512-513`) must all be `done` before any
runtime-code-change subtask may begin. **All nine are DONE — the hard gate is OPEN.**

- `001` measure_complexity_and_dependencies — **DONE** (`e0662c7`)
- `002` inventory_legacy_obsolete_and_duplicate_code — **DONE** (`d286dec`)
- `020` inventory_viz_dashboard_api_contracts — **DONE** (`43b143a`)
- `036` inventory_hardcoded_prompts — **DONE** (`9619ebf`)
- `045` inventory_github_workflows — **DONE** (`8842a5f`)
- `053` inventory_reference_roots — **DONE** (`b4d7706`)
- `059` inventory_dashboard_frontend_backend_structure — **DONE** (`f43d9f1`)
- `060` inventory_dashboard_api_contracts — **DONE** (`dcb0389`)
- `067` inventory_dashboard_visible_settings — **DONE** (`4252a79`)

## Unblocked-next

Not-started subtasks whose `Depends` predecessor(s) **and** the nine inventory gates
are all `done` (i.e. ready to start now). Runtime-code-change subtasks additionally
require their own per-subtask `REVIEW_REQUIRED` rulings and must run sequentially /
worktree-isolated on shared runtime files (per `orchestration_status.md`).

- **Non-runtime (safe to start immediately):** 017, 018, 022, 031, 034, 042, 049, 050, 051, 056, 065, 073.
- **Runtime-code-change (eligible; gate open, honor per-subtask REVIEW_REQUIRED):** 003, 005, 006, 008, 009, 010, 011, 012, 013, 014, 015, 016, 021, 023, 024, 038, 039, 040, 041, 044, 062, 063, 064, 070, 071, 072.
- **Terminal:** `019` final_quality_report has no predecessor edge but is sequenced **LAST** (Phase 11); it aggregates all outputs and consumes this tracker.

Currently **blocked** (predecessor not yet done): 027, 028, 057, 058 — 027/028 wait on `003`; 057 waits on `056`; 058 waits on `057`.

## Subtask status table

Identity columns (ID / Name / Phase / Depends / Runtime) mirror
`007_subtask_index.md`; if they disagree, the index wins. The `Status`,
`Owner / PR`, `Last updated`, and `Notes` columns are this tracker's own state.

| ID | Name | Phase | Depends | Runtime | Status | Owner / PR | Last updated | Notes |
|---|---|---|---|---|---|---|---|---|
| 001 | measure_complexity_and_dependencies | 1 | — | No | done | `e0662c7` | 2026-07-01 | reports/001_complexity_baseline.md |
| 002 | inventory_legacy_obsolete_and_duplicate_code | 1 | — | No | done | `d286dec` | 2026-07-01 | reports/002_legacy_obsolete_duplicate_inventory.md |
| 003 | consolidate_config_configs_sonfigs | 2 | — | Yes | not-started | — | 2026-07-02 |  |
| 004 | define_runtime_path_policy | 2 | — | No | done | `93d9662` | 2026-07-01 | verify-only: deliverable is subtasks/004_*.md (planning commit); grounded-verified |
| 005 | consolidate_checkpoint_workspace_experiment_paths | 2 | 004 | Yes | not-started | — | 2026-07-02 |  |
| 006 | introduce_runtime_path_resolver | 2 | 004 | Yes | not-started | — | 2026-07-02 |  |
| 007 | define_core_interfaces_and_protocols | 3 | — | No | done | `93d9662` | 2026-07-01 | verify-only: deliverable is subtasks/007_*.md (planning commit); grounded-verified |
| 008 | extract_model_backend_interface | 3 | 007 | Yes | not-started | — | 2026-07-02 |  |
| 009 | extract_evaluator_interface | 3 | 007 | Yes | not-started | — | 2026-07-02 |  |
| 010 | extract_artifact_checkpoint_trace_store | 3 | 007 | Yes | not-started | — | 2026-07-02 |  |
| 011 | separate_bfts_strategy_from_react_loop | 3 | 007 | Yes | not-started | — | 2026-07-02 |  |
| 012 | refactor_pipeline_stage_architecture | 3 | 007 | Yes | not-started | — | 2026-07-02 |  |
| 013 | refactor_memory_boundary | 3 | 007 | Yes | not-started | — | 2026-07-02 |  |
| 014 | refactor_registry_and_factory_layer | 3 | 007 | Yes | not-started | — | 2026-07-02 |  |
| 015 | refactor_dashboard_viz_api_services | 4 | — (gate 020) | Yes | not-started | — | 2026-07-02 | unblocked (soft gate 020 done); High-risk runtime; run worktree-isolated |
| 016 | clean_merge_or_quarantine_legacy_code | 2 | 002 | Yes | not-started | — | 2026-07-02 |  |
| 017 | update_docs_and_examples | 10 | — | No | not-started | — | 2026-07-02 |  |
| 018 | add_tests_for_architecture_boundaries | 10 | — | No | not-started | — | 2026-07-02 |  |
| 019 | final_quality_report | 11 | — | No | not-started | — | 2026-07-02 | terminal (Phase 11, sequenced LAST); aggregates all outputs and consumes this tracker (035) |
| 020 | inventory_viz_dashboard_api_contracts | 4 | — | No | done | `43b143a` | 2026-07-01 | reports/viz_api_contract_inventory.{md,json} |
| 021 | extract_viz_services_from_routes | 4 | 020 | Yes | not-started | — | 2026-07-02 |  |
| 022 | define_dashboard_dto_and_schema_tests | 4 | 020 | No | not-started | — | 2026-07-02 | unblocked (020 done); concurrent uncommitted deliverable observed in working tree at generation (viz *.schema.json + test_api_schema_contract.py) — re-sync to in-progress/done when committed |
| 023 | separate_viz_file_io_from_route_handlers | 4 | 020 | Yes | not-started | — | 2026-07-02 |  |
| 024 | refactor_bfts_tree_visualization_adapter | 4 | 020 | Yes | not-started | — | 2026-07-02 |  |
| 025 | add_complexity_checker_script | 8 | 001 | No | done | `6720ca8` | 2026-07-01 | scripts/check_complexity.py + scripts/quality/ infra |
| 026 | add_import_boundary_checker_script | 8 | — | No | done | `fe34241` | 2026-07-01 | scripts/check_import_boundaries.py |
| 027 | add_docs_source_sync_checker_script | 8 | 003 | No | blocked | — | 2026-07-02 | blocked: Depends 003 (consolidate_config) not done |
| 028 | add_directory_policy_checker_script | 8 | 003 | No | blocked | — | 2026-07-02 | blocked: Depends 003 (consolidate_config) not done |
| 029 | add_public_api_contract_checker_script | 8 | — | No | done | `5c5c10a` | 2026-07-01 | scripts/check_public_api_contracts.py |
| 030 | add_viz_api_schema_checker_script | 4 | 020 | No | done | `7bd5654` | 2026-07-02 | scripts/check_viz_api_schema.py |
| 031 | add_quality_report_generator | 8 | 001 | No | not-started | — | 2026-07-02 |  |
| 032 | add_quality_script_ci_plan | 9 | — | No | done | `11cd088` | 2026-07-01 | reports/032_quality_script_ci_integration.md (authoritative CI-wiring plan) |
| 033 | add_generated_files_gitignore_policy | 2 | — | No | done | `0ad0b19` | 2026-07-01 | generated-files .gitignore policy + hygiene |
| 034 | add_contract_snapshot_fixtures | 10 | — | No | not-started | — | 2026-07-02 |  |
| 035 | add_refactoring_progress_tracker | 10 | — | No | in-progress | — | 2026-07-02 | This tracker IS the 035 deliverable, being created 2026-07-02; flips to done when merged. |
| 036 | inventory_hardcoded_prompts | 7 | — | No | done | `9619ebf` | 2026-07-01 | reports/hardcoded_prompt_inventory.{md,json} |
| 037 | define_prompt_template_policy | 7 | 036 | No | done | `93d9662` | 2026-07-01 | verify-only: deliverable is subtasks/037_*.md (planning commit); grounded-verified |
| 038 | introduce_prompt_registry_and_loader | 7 | 036 | Yes | not-started | — | 2026-07-02 |  |
| 039 | extract_agent_and_bfts_prompts | 7 | 036 | Yes | not-started | — | 2026-07-02 |  |
| 040 | extract_evaluator_and_llm_judge_prompts | 7 | 036 | Yes | not-started | — | 2026-07-02 |  |
| 041 | extract_pipeline_and_paper_generation_prompts | 7 | 036 | Yes | not-started | — | 2026-07-02 |  |
| 042 | add_prompt_snapshot_tests | 7 | 036 | No | not-started | — | 2026-07-02 | unblocked (036 done); concurrent uncommitted deliverable observed in working tree at generation (test_prompt_snapshots.py + snapshots/) — re-sync when committed |
| 043 | add_prompt_checker_script | 7 | 036 | No | done | `dffefdf` | 2026-07-02 | scripts/check_prompts.py |
| 044 | add_prompt_version_tracking_to_run_metadata | 7 | 036 | Yes | not-started | — | 2026-07-02 |  |
| 045 | inventory_github_workflows | 9 | — | No | done | `8842a5f` | 2026-07-01 | reports/045_github_workflow_inventory.md |
| 046 | design_quality_ci_integration | 9 | 045 | No | done | `93d9662` | 2026-07-01 | verify-only: deliverable is subtasks/046_*.md; 032 is authoritative CI plan |
| 047 | add_pr_template_quality_checklist | 9 | 045 | No | done | `78c9eea` | 2026-07-01 | .github/PULL_REQUEST_TEMPLATE.md |
| 048 | add_issue_templates_for_refactoring | 9 | 045 | No | done | `e869a90` | 2026-07-01 | .github/ISSUE_TEMPLATE/ (4 files) |
| 049 | add_contract_check_workflows | 9 | 045 | No | not-started | — | 2026-07-02 | unblocked (045 done) but orchestrator soft-deferred pending checkers 026/029/030/028/055 (per orchestration_status.md) |
| 050 | add_docs_sync_workflow | 9 | 045 | No | not-started | — | 2026-07-02 | unblocked (045 done) but orchestrator soft-deferred (append to docs-sync.yml) per orchestration_status.md |
| 051 | add_prompt_change_review_workflow | 9 | 045 | No | not-started | — | 2026-07-02 | unblocked (045 done) but orchestrator soft-deferred pending checker 043 per orchestration_status.md |
| 052 | add_dependabot_and_actions_policy | 9 | 045 | No | done | `a40ab08` | 2026-07-01 | .github/dependabot.yml + actions policy |
| 053 | inventory_reference_roots | 1 | — | No | done | `b4d7706` | 2026-07-01 | reports/053_reference_roots_inventory.{md,json} |
| 054 | add_reference_graph_analyzer | 1 | 053 | No | done | `d73dd9e` | 2026-07-01 | scripts/analyze_references.py + reference_graph.{json,md} |
| 055 | add_dead_code_candidate_checker | 1 | 054 | No | done | `d734d87` | 2026-07-02 | scripts/check_dead_code.py; SAFE_DELETE_CANDIDATE=0 |
| 056 | classify_unused_functions_and_files | 1 | 055 | No | not-started | — | 2026-07-02 | unblocked (055 done); consumes 055 dead-code classification (SAFE_DELETE_CANDIDATE=0); concurrent uncommitted deliverable observed in working tree at generation (dead_code_classification.md) — re-sync when committed |
| 057 | delete_safe_dead_code_candidates | 2 | 056 | Yes | blocked | — | 2026-07-02 | blocked: Depends 056 (classify) not done; per 055 SAFE_DELETE_CANDIDATE=0 this is expected to be a documented no-op |
| 058 | add_dead_code_checker_to_quality_report | 8 | 057 | No | blocked | — | 2026-07-02 | blocked: Depends 057 (delete_safe_dead_code) not done |
| 059 | inventory_dashboard_frontend_backend_structure | 5 | — | No | done | `f43d9f1` | 2026-07-01 | reports/dashboard_structure_inventory.{md,json} |
| 060 | inventory_dashboard_api_contracts | 5 | 059 | No | done | `dcb0389` | 2026-07-01 | reports/dashboard_fe_api_contract_inventory.{md,json} |
| 061 | define_dashboard_dto_and_schema_policy | 5 | 059 | No | done | `93d9662` | 2026-07-01 | verify-only: deliverable is subtasks/061_*.md; grounded-verified |
| 062 | refactor_dashboard_backend_routes_to_services | 5 | 059 | Yes | not-started | — | 2026-07-02 |  |
| 063 | refactor_dashboard_frontend_api_client_and_types | 5 | 059 | Yes | not-started | — | 2026-07-02 |  |
| 064 | refactor_dashboard_state_and_component_boundaries | 5 | 059 | Yes | not-started | — | 2026-07-02 |  |
| 065 | add_dashboard_contract_and_schema_tests | 5 | 059 | No | not-started | — | 2026-07-02 |  |
| 066 | add_dashboard_build_and_ci_plan | 5 | 059 | No | done | `0000cec` | 2026-07-01 | reports/066_dashboard_build_and_ci_plan.md |
| 067 | inventory_dashboard_visible_settings | 6 | 059 | No | done | `4252a79` | 2026-07-01 | reports/067_dashboard_visible_settings_inventory.{md,json} |
| 068 | define_dashboard_information_architecture | 6 | 059 | No | done | `93d9662` | 2026-07-01 | verify-only: deliverable is subtasks/068_*.md; grounded-verified |
| 069 | design_dashboard_progressive_disclosure | 6 | 059 | No | done | `f878986` | 2026-07-01 | reports/069_progressive_disclosure_design.md |
| 070 | refactor_dashboard_settings_panel | 6 | 059 | Yes | not-started | — | 2026-07-02 |  |
| 071 | add_dashboard_developer_mode | 6 | 059 | Yes | not-started | — | 2026-07-02 |  |
| 072 | improve_dashboard_empty_loading_error_states | 6 | 059 | Yes | not-started | — | 2026-07-02 |  |
| 073 | add_dashboard_ux_regression_checks | 6 | 059 | No | not-started | — | 2026-07-02 |  |

## Update protocol (keep this a living document)

1. When a subtask's implementation PR merges, flip its `Status` to `done`, set
   `Owner / PR` to the merge SHA / PR number, and stamp `Last updated`.
2. When a PR opens, set `in-progress` (or `in-review` once ready).
3. Re-evaluate every `blocked` row whose predecessor just went `done`; promote it to
   `not-started` / `in-progress` and refresh **Unblocked-next**.
4. Keep `progress.md` and `progress.json` in lock-step (both updated in the same
   commit) — same 73 IDs, same statuses.
5. **Determinism (P2):** all status values are derived from observable evidence
   (merged SHA, deliverable-on-disk), not inference; no LLM/network calls are
   involved in maintaining this tracker.
6. **Row-set invariant:** this tracker contains **exactly** the 73 subtask IDs in
   `007_subtask_index.md` — no more, no fewer. If the index gains/loses a subtask,
   update this tracker in the same change.

<!-- machine-readable mirror: docs/refactoring/reports/progress.json (same 73 IDs + statuses) -->
