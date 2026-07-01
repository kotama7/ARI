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
- `ruff check ari-core --statistics` → **661** findings (341 `F401`, 135 `E402`, 358 auto-fixable). *(frozen baseline)*
- `python -m compileall -q ari-core ari-skill-* scripts` → **exit 0** (pass).
- `pytest ari-core/tests -q` baseline → **2413 passed, 16 skipped** (111s, exit 0). *(clean green)*
- HEAD at start: `93d9662865fc5e97a1950a7ec19ac06ace32e562`.

## Hard gate

No **Runtime Code Change = Yes** subtask may start until all **nine inventories**
are DONE: **001, 002, 020, 036, 045, 053, 059, 060, 067**. (060 and 067 depend on 059.)

## Subtask ledger

Legend — Rt = Runtime Code Change (Yes/No). Phase per `007_subtask_index.md`.

| ID | Title | Phase | Risk | Rt | Depends On | Status | Commit |
|----|-------|-------|------|----|-----------|--------|--------|
| 001 | measure_complexity_and_dependencies | 1 | Low | No | — | DONE | e0662c7 |
| 002 | inventory_legacy_obsolete_and_duplicate_code | 1 | Low | No | — | DONE | d286dec |
| 003 | consolidate_config_configs_sonfigs | 2 | High | Yes | (gate) | TODO | — |
| 004 | define_runtime_path_policy | 2 | Low | No | — | TODO | — |
| 005 | consolidate_checkpoint_workspace_experiment_paths | 2 | High | Yes | 004 | TODO | — |
| 006 | introduce_runtime_path_resolver | 2 | Medium | Yes | 004 | TODO | — |
| 007 | define_core_interfaces_and_protocols | 3 | Low | No | — | TODO | — |
| 008 | extract_model_backend_interface | 3 | High | Yes | 007 | TODO | — |
| 009 | extract_evaluator_interface | 3 | Medium | Yes | 007 | TODO | — |
| 010 | extract_artifact_checkpoint_trace_store | 3 | High | Yes | 007 | TODO | — |
| 011 | separate_bfts_strategy_from_react_loop | 3 | High | Yes | 007 | TODO | — |
| 012 | refactor_pipeline_stage_architecture | 3 | High | Yes | 007 | TODO | — |
| 013 | refactor_memory_boundary | 3 | High | Yes | 007 | TODO | — |
| 014 | refactor_registry_and_factory_layer | 3 | High | Yes | 007 | TODO | — |
| 015 | refactor_dashboard_viz_api_services | 4 | High | Yes | (gate 020) | TODO | — |
| 016 | clean_merge_or_quarantine_legacy_code | 2 | High | Yes | 002 | TODO | — |
| 017 | update_docs_and_examples | 10 | Low | No | — | TODO | — |
| 018 | add_tests_for_architecture_boundaries | 10 | Low | No | — | TODO | — |
| 019 | final_quality_report | 11 | Low | No | — (LAST) | TODO | — |
| 020 | inventory_viz_dashboard_api_contracts | 4 | Low | No | — | TODO | — |
| 021 | extract_viz_services_from_routes | 4 | Medium | Yes | 020 | TODO | — |
| 022 | define_dashboard_dto_and_schema_tests | 4 | Low | No | 020 | TODO | — |
| 023 | separate_viz_file_io_from_route_handlers | 4 | Medium | Yes | 020 | TODO | — |
| 024 | refactor_bfts_tree_visualization_adapter | 4 | Medium | Yes | 020 | TODO | — |
| 025 | add_complexity_checker_script | 8 | Low | No | 001 | TODO | — |
| 026 | add_import_boundary_checker_script | 8 | Low | No | — | TODO | — |
| 027 | add_docs_source_sync_checker_script | 8 | Low | No | 003 | TODO | — |
| 028 | add_directory_policy_checker_script | 8 | Low | No | 003 | TODO | — |
| 029 | add_public_api_contract_checker_script | 8 | Low | No | — | TODO | — |
| 030 | add_viz_api_schema_checker_script | 4 | Low | No | 020 | TODO | — |
| 031 | add_quality_report_generator | 8 | Low | No | 001 | TODO | — |
| 032 | add_quality_script_ci_plan | 9 | Low | No | — | TODO | — |
| 033 | add_generated_files_gitignore_policy | 2 | Low | No | — | TODO | — |
| 034 | add_contract_snapshot_fixtures | 10 | Low | No | — | TODO | — |
| 035 | add_refactoring_progress_tracker | 10 | Low | No | — | TODO | — |
| 036 | inventory_hardcoded_prompts | 7 | Low | No | — | TODO | — |
| 037 | define_prompt_template_policy | 7 | Low | No | 036 | TODO | — |
| 038 | introduce_prompt_registry_and_loader | 7 | Medium | Yes | 036 | TODO | — |
| 039 | extract_agent_and_bfts_prompts | 7 | Medium | Yes | 036 | TODO | — |
| 040 | extract_evaluator_and_llm_judge_prompts | 7 | Medium | Yes | 036 | TODO | — |
| 041 | extract_pipeline_and_paper_generation_prompts | 7 | Medium | Yes | 036 | TODO | — |
| 042 | add_prompt_snapshot_tests | 7 | Low | No | 036 | TODO | — |
| 043 | add_prompt_checker_script | 7 | Low | No | 036 | TODO | — |
| 044 | add_prompt_version_tracking_to_run_metadata | 7 | Medium | Yes | 036 | TODO | — |
| 045 | inventory_github_workflows | 9 | Low | No | — | DONE | 8842a5f |
| 046 | design_quality_ci_integration | 9 | Low | No | 045 | TODO | — |
| 047 | add_pr_template_quality_checklist | 9 | Low | No | 045 | TODO | — |
| 048 | add_issue_templates_for_refactoring | 9 | Low | No | 045 | TODO | — |
| 049 | add_contract_check_workflows | 9 | Low | No | 045 | TODO | — |
| 050 | add_docs_sync_workflow | 9 | Low | No | 045 | TODO | — |
| 051 | add_prompt_change_review_workflow | 9 | Low | No | 045 | TODO | — |
| 052 | add_dependabot_and_actions_policy | 9 | Low | No | 045 | TODO | — |
| 053 | inventory_reference_roots | 1 | Low | No | — | TODO | — |
| 054 | add_reference_graph_analyzer | 1 | Low | No | 053 | TODO | — |
| 055 | add_dead_code_candidate_checker | 1 | Low | No | 054 | TODO | — |
| 056 | classify_unused_functions_and_files | 1 | Low | No | 055 | TODO | — |
| 057 | delete_safe_dead_code_candidates | 2 | High | Yes | 056 | TODO | — |
| 058 | add_dead_code_checker_to_quality_report | 8 | Low | No | 057 | TODO | — |
| 059 | inventory_dashboard_frontend_backend_structure | 5 | Low | No | — | TODO | — |
| 060 | inventory_dashboard_api_contracts | 5 | Low | No | 059 | TODO | — |
| 061 | define_dashboard_dto_and_schema_policy | 5 | Low | No | 059 | TODO | — |
| 062 | refactor_dashboard_backend_routes_to_services | 5 | High | Yes | 059 | TODO | — |
| 063 | refactor_dashboard_frontend_api_client_and_types | 5 | High | Yes | 059 | TODO | — |
| 064 | refactor_dashboard_state_and_component_boundaries | 5 | High | Yes | 059 | TODO | — |
| 065 | add_dashboard_contract_and_schema_tests | 5 | Low | No | 059 | TODO | — |
| 066 | add_dashboard_build_and_ci_plan | 5 | Low | No | 059 | TODO | — |
| 067 | inventory_dashboard_visible_settings | 6 | Low | No | 059 | TODO | — |
| 068 | define_dashboard_information_architecture | 6 | Low | No | 059 | TODO | — |
| 069 | design_dashboard_progressive_disclosure | 6 | Low | No | 059 | TODO | — |
| 070 | refactor_dashboard_settings_panel | 6 | High | Yes | 059 | TODO | — |
| 071 | add_dashboard_developer_mode | 6 | Medium | Yes | 059 | TODO | — |
| 072 | improve_dashboard_empty_loading_error_states | 6 | Medium | Yes | 059 | TODO | — |
| 073 | add_dashboard_ux_regression_checks | 6 | Low | No | 059 | TODO | — |

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

## Run log

- 2026-07-01: Orchestrator initialized. Read 000/007/010 + subtask 001. Baseline
  gates captured (ruff 661, compileall pass). Ledger created. Starting the nine
  inventories (hard gate).
