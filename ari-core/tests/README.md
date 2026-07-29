# ari-core/tests

Pytest suite for ari-core (`test_*.py`), covering BFTS, the pipeline,
evaluator, viz API, CLI, and migration paths.

See `docs/guides/testing.md` for how to run & conventions; each `test_*.py`
targets the like-named module under `ari/`.

## Contents

- `README.md` — this file.
- `_arch_boundaries.py` — TODO
- `test_agent_smoke.py` — agent smoke test.
- `test_analyze_handoff.py` — TODO
- `test_api_lineage_decisions.py` — lineage-decisions API.
- `test_api_lineage_e2e.py` — lineage API end-to-end.
- `test_api_paperbench.py` — PaperBench API.
- `test_api_paperbench_worker.py` — PaperBench API worker.
- `test_api_process.py` — process-control service (stop-all + GPU monitor).
- `test_api_schema_contract.py` — stable viz endpoint response-shape contracts.
- `test_architecture_boundary_index.py` — TODO
- `test_artifact_store.py` — TODO
- `test_bfts.py` — BFTS loop.
- `test_bfts_allow_web.py` — `bfts.allow_web` / `ARI_BFTS_ALLOW_WEB` toggle: web-skill phase gating in/out of bfts + the `bfts_web_provenance.json` marker roundtrip.
- `test_bfts_deterministic_selector.py` — G9a deterministic selection: both selectors bypass the LLM and rank by the frontier scorer when `deterministic_selector` / `ARI_BFTS_DETERMINISTIC` is set (handoff study).
- `test_bfts_diversity.py` — BFTS diversity/fanout.
- `test_bfts_eval_config_integration.py` — BFTS + eval-config integration.
- `test_bfts_frontier_score.py` — BFTS frontier scoring.
- `test_bfts_prompt_builder.py` — TODO
- `test_bfts_prompt_selection.py` — BFTS prompt selection.
- `test_checkpoint_legacy_tree.py` — legacy node_*/tree.json resolution in list/summary.
- `test_checkpoint_store.py` — TODO
- `test_child_node_workflow.py` — child-node workflow.
- `test_child_workdir_inherit.py` — child workdir inheritance.
- `test_claim_evidence_hard_gate.py` — Story2Proposal Phase B deterministic gate: recompute, mismatch, operand resolution, coverage, blocking semantics.
- `test_claim_gate_contract.py` — declared-contract enforcement: `safe_eval` formula evaluator, `contract.check_contract`/`check_emission` (recompute mismatch, claim-evidence coverage, provenance/ceiling/correctness requirement flags, lexical near-miss hints) + gate blocking at final.
- `test_claim_gate_invariants.py` — concept→invariant registry (`classify_concept`, `CONCEPT_INVARIANTS`, `scan_science_data`): universal-math bounds (normalized≤1, probability in [0,1]) fire domain-neutrally, leave unbounded metrics alone, and block at final via `run_hard_gate`.
- `test_claude_code_command.py` — claude_code argv/env builder: isolation flags, native `--json-schema` profile, no session-reuse flags, env allowlist + forced memory-suppression vars.
- `test_claude_code_policy.py` — claude_code fail-loud policy validator (tools/deny-all/resume/memory/safe-mode/multi-turn rules).
- `test_claude_code_provenance.py` — per-call provenance sandbox: artifact set, SHA-256 hashes, call-id minting, checkpoint-root resolution.
- `test_claude_code_provider.py` — claude_code integration with mock runners: LLMClient backend dispatch, strict=subprocess vs low_overhead=SDK, one normalized `LLMResponse`, session ids never reused, schema validation + single repair retry, cost booking, env overrides.
- `test_claude_code_serializer.py` — deterministic messages→prompt serialization: role order, system folding, schema embedding, repair prompt.
- `test_claude_code_validation.py` — ARI-side JSON extraction (fences, prose braces before the JSON) + jsonschema validation outcomes.
- `test_cli.py` — CLI.
- `test_cli_extended.py` — extended CLI cases.
- `test_cli_shim_toolcalls.py` — CLI shim (`ari.llm.cli_server`) function-calling: `extract_tool_calls`/`render_prompt`/`complete` turn text-only `claude -p`/`codex exec` into OpenAI `tool_calls`, plus cost passthrough and MCP-direct mode vs. text-catalog fallback.
- `test_clone.py` — clone behaviour.
- `test_config.py` — config loading.
- `test_container.py` — container runtime.
- `test_context_budget.py` — asserts the conversation window and tool-output caps are BUDGET-conditional, not unconditional: `context_budget_chars()` = `max(4000, ARI_LLM_NUM_CTX-2048)*3`, and trimming/truncation only fires when the conversation actually exceeds it. Pins the study control that a fixed `keep_tail` silently discarded the parent's early reasoning on every node regardless of size.
- `test_contract_snapshots.py` — TODO
- `test_core_does_not_import_skills.py` — TODO
- `test_core_viz_direction.py` — TODO
- `test_cost_tracker.py` — cost tracker.
- `test_cost_tracker_failures.py` — token accounting must cover the calls that FAILED. Only litellm's `success_callback` was registered, so a run that burnt budget on timeouts/retries reported only the calls that came back — under-counting consumption and making a retry storm indistinguishable from a clean run. Pins: a failed call is booked with `status="failed"` and the prompt tokens it actually sent (counted from the request, since a failed call returns no `usage` — booking 0 would record a burnt call as free); provider-supplied partial usage wins over recounting; node/phase survive so per-arm consumption stays attributable; the handler never raises; and a re-init reloading the trace preserves `status` (a lossy reload resurrected failures as successful work).
- `test_curate.py` — curation.
- `test_dashboard_html.py` — dashboard HTML.
- `test_data_flow.py` — data flow.
- `test_default_provider.py` — default LLM provider.
- `test_delete_checkpoint_experiments.py` — checkpoint-experiment deletion.
- `test_deterministic_evaluator.py` — deterministic-evaluator scoring-contract tests (geomean / native `_scientific_score` ranking value / invalid-family rule; handoff study B2).
- `test_disabled_tools_flow.py` — disabled-tools flow.
- `test_dynamic_axes.py` — dynamic evaluation axes.
- `test_ear.py` — EAR (experiment/analysis/report).
- `test_edit_lineage.py` — pins the rewrite/refine measure (`workspace/edit_lineage.py`). Tokenizer is not fooled by comment markers inside string/char literals; multi-char operators are single tokens. The measure SEPARATES a refine (>0.85) from a rewrite (<0.6) with the default threshold falling between them — a measure that returned the same number for both would measure nothing. Similarity is symmetric (difflib's greedy ratio is order-dependent, so both directions are averaged). Checkpoint walk pairs children with parents, excludes roots/orphans, splits valid/invalid, and refuses cross-task pairs (mismatched `candidate_*.c`). Structural (tree-sitter) check degrades to a clear note when absent, never a crash.
- `test_env_write_quoting.py` — .env-write quoting guard (api_settings upsert).
- `test_evaluator_axis_mode.py` — evaluator axis mode.
- `test_evaluator_composite.py` — evaluator composite scoring.
- `test_evaluator_independence.py` — TODO
- `test_evaluator_protocol.py` — TODO
- `test_event_loop_and_csv.py` — event loop + CSV logging.
- `test_factory_registry.py` — TODO
- `test_file_explorer.py` — file explorer.
- `test_ground_environment.py` — pins which conversation roles the environment-grounding corpus reads (`tool` and `user`), so agent-authored notes are not deleted as ungrounded. Regression: 4 of 17 notes were wrongly dropped when the corpus omitted a role.
- `test_gui_env_propagation.py` — GUI env propagation.
- `test_gui_errors.py` — GUI error handling.
- `test_handoff_agent_injection.py` — agent-face handoff injection (`build_handoff_agent_messages` + parent report/log loaders): summary / full / truncated arms, no-op arms, child→parent workdir resolution (handoff study G4).
- `test_handoff_content_fix.py` — handoff channels carry real payload: `node_summary_view` surfaces the actionable `outcome` (self-assessment headline / eval reason, with eval_summary fallback; ablatable), and `_load_parent_log` falls back to the parent's tree.json `trace_log` when no run.log exists so code_plus_full_log is not silently empty (regression guard for the degenerate-channel finding).
- `test_handoff_driver.py` — TODO
- `test_handoff_stats.py` — analysis statistics core for the handoff study: geomean, bootstrap confidence intervals, two-sided permutation tests, Holm adjustment, and per-arm summaries.
- `test_harness_registry.py` — registry MECHANISM only, against synthetic harnesses built in `tmp_path` — ARI ships no task and the real ones live in an untracked workspace, so this must not load them. Pins: the per-task `[measure_kwargs]` declaration (a uniform `measure_node(work_dir, seed=seed)` type-checks against every harness and silently measures something else), sha256 tamper-refusal, unknown-task raising instead of falling through to a default benchmark, cwd-independent resolution via `RuntimePathResolver`, and that ARI core names no task.
- `test_i18n_consistency.py` — i18n consistency.
- `test_idea_integration.py` — idea integration.
- `test_include_ear_toggle.py` — include-EAR toggle.
- `test_integration.py` — integration.
- `test_labels_disabled.py` — pins `ARI_BFTS_NO_LABEL` as a REAL feature switch at all three sites the exploration label steers the search — the system prompt's NODE ROLE, the child's `Task:` line, and `diversity_bonus` in node selection — not a record-only suppression. A flag that hides a live variable from the record deletes the evidence, not the influence.
- `test_laptop_hpc_skill_drop.py` — laptop/HPC skill drop.
- `test_launch_config.py` — launch config.
- `test_letta_restart_live.py` — Letta restart (live).
- `test_letta_start_scripts.py` — Letta start scripts.
- `test_lineage_and_inherit.py` — lineage + inheritance.
- `test_lineage_decision.py` — lineage decision.
- `test_lineage_decision_persistence.py` — lineage-decision persistence.
- `test_llm.py` — LLM client.
- `test_llm_evaluator_axes.py` — LLM evaluator axes.
- `test_llm_routing.py` — single-source litellm provider-prefix routing: `resolve_litellm_model` prefix-by-backend (idempotent, env fallback) + `cost_tracker._apply_ari_routing`/metadata injector so a skill's bare `litellm.completion` reaches the shim.
- `test_loop_message_order.py` — `loop.repair_tool_message_order` defense-in-depth: restores contiguous tool-response blocks, moves interleaved user injections past them, and drops orphaned assistant/partial pairings the API would reject.
- `test_max_react_passthrough.py` — max-ReAct passthrough.
- `test_mcp_cow_concurrency.py` — MCP copy-on-write concurrency.
- `test_memory.py` — memory backend.
- `test_metric_contract_obligation.py` — `ari.agent.metric_contract` producer obligation: domain-neutral `build_contract_obligation`/`build_emission_nudge`, run-level claim coverage (`build_coverage_status`, `collect_run_measurement_names`), and lineage chaining (`collect_node_measurement_names`, `build_expand_coverage_hint`, `build_inherited_data_note`).
- `test_model_backend_independence.py` — TODO
- `test_model_backend_protocol.py` — TODO
- `test_model_passthrough.py` — model passthrough.
- `test_no_user_home_writes.py` — no-user-home-writes guard.
- `test_node.py` — Node data model.
- `test_node_report.py` — node_report builder.
- `test_node_selection.py` — node selection.
- `test_node_summary_view.py` — node_summary_view field ablation / known_failures derivation / failure_only form / machine-info leak guard (handoff study G3).
- `test_nodes_to_science_data_shrink.py` — nodes→science-data shrink.
- `test_ollama_gpu.py` — Ollama GPU.
- `test_orchestrator.py` — orchestrator.
- `test_page_requirements.py` — page requirements.
- `test_paths.py` — path resolution.
- `test_pidfile.py` — pidfile handling.
- `test_pipeline_e2e.py` — pipeline end-to-end.
- `test_pipeline_metric_parsing.py` — pipeline metric parsing.
- `test_pipeline_stage_architecture.py` — TODO
- `test_pipeline_verified_context.py` — verified-context building blocks (best-node selection, lineage scoping, grounded-block renderer).
- `test_plan_promote.py` — plan promotion.
- `test_prompt_extraction.py` — prompt extraction.
- `test_prompt_provenance.py` — TODO
- `test_prompt_registry.py` — TODO
- `test_prompt_snapshots.py` — TODO
- `test_public_api_boundary.py` — public-API boundary.
- `test_publish_and_registry.py` — publish + registry.
- `test_publish_yaml_api.py` — publish YAML API.
- `test_publish_zenodo_gh.py` — publish to Zenodo/GitHub.
- `test_react_driver.py` — ReAct driver.
- `test_resolve_node_work_dir.py` — resolve node work dir.
- `test_retrieval_backend.py` — retrieval backend.
- `test_root_idea_selector.py` — root-idea selector.
- `test_run_env.py` — run environment.
- `test_run_env_catalog.py` — asserts the run-environment catalog masks host identity (username paths, alternate filesystem mounts, MODULEPATH) before it reaches the agent, so a node reads as a self-contained container rather than a host account.
- `test_run_loop.py` — run loop.
- `test_run_provenance.py` — `<checkpoint>/provenance.json` — the record that lets a reader holding only the published workspace + this repo re-check a number: the harness's verified sha256 digests, its workspace-relative origin, target/scale/axis, the ARI commit, and the measurement env the (digest-pinned) harness source reads to build its compile command. Pins the two things that are easy to get wrong: REDACTION (the file ships inside a published artifact, so secret values and absolute paths must never appear, while the keys that determine the measurement must survive), and the round-trip (recompute every digest from the workspace and detect a tampered one). Also pins that the record is META: `_run_loop` copies every non-meta checkpoint-root file into each node, so a non-meta provenance.json handed every node the TARGET it is judged against — a leak only the real `_run_loop` exposed.
- `test_runtime_path_reconciliation_005.py` — TODO
- `test_sandbox_shim.py` — sandbox shim.
- `test_selection_contract.py` — selection contract.
- `test_server.py` — viz/API server.
- `test_settings_propagation.py` — settings propagation.
- `test_settings_roundtrip.py` — settings roundtrip.
- `test_setup_env.py` — setup_env.sh behaviour.
- `test_skill_public_contract.py` — skills import core via the public contract.
- `test_status_fallback.py` — status fallback.
- `test_system_prompt_memory.py` — system-prompt memory.
- `test_text_toolcall_recovery.py` — recovery of tool calls emitted as plain text by models that do not honour the tool-call protocol; keeps a weak model's turn usable instead of scoring it as a no-op.
- `test_tool_manager_workdir.py` — tool dispatch pins filesystem tools (`write_code`/`run_bash`/`run_code`/`emit_results`/`read_file`) to the node's work_dir when the model omits `work_dir`, so per-node edits land in the evaluated dir instead of the shared `/tmp/ari_work` fallback (regression guard for the BFTS bug where omitted-work_dir edits were scored on inherited parent code); explicit work_dir is not overridden and memory-tool CoW routing is preserved.
- `test_tool_timeout_tier.py` — MCP `_resolve_tool_timeout` tiering: LLM/compile paper stages (incl. `paper_refine`, `compile_paper`) get the slow timeout, plain tools the 300s default (regression guard for the paper_refine shim-congestion timeout).
- `test_trace_log_truncation.py` — trace-log truncation.
- `test_trace_store.py` — TODO
- `test_tree_view_adapter.py` — TODO
- `test_upload_to_node.py` — upload to compute node.
- `test_variable_passthrough.py` — variable passthrough.
- `test_verified_context_wiring.py` — orchestrator gating of verified_context.json on `ARI_MEMORY_CONSOLIDATE` (off→skip / on→build / build-failure→pipeline survives).
- `test_virsci_off.py` — VirSci-off path.
- `test_viz_dto_schema.py` — TODO
- `test_viz_fewshot_api.py` — viz few-shot API.
- `test_viz_file_service.py` — TODO
- `test_viz_memory_api.py` — viz memory API.
- `test_viz_node_report_api.py` — viz node_report API.
- `test_viz_repro_synth.py` — viz repro-synth.
- `test_wizard.py` — wizard.
- `test_workflow_contract.py` — workflow contract.
- `test_workflow_editor.py` — workflow editor.
- `test_workflow_template_resolution.py` — workflow template resolution.
- `test_working_context_injection.py` — `loop.build_working_context_messages` Tier-1/2 injection: experiment core + selected idea, deterministic per-entry-capped ancestor conclusions, deduped semantic supplement, persisted metric-contract obligation (with platform note) for every node, and pinned-window marker matching.
- `fixtures/` — test fixtures (not enumerated)
- `snapshots/` — TODO
  - `prompts/` — TODO
    - `agent/` — TODO
      - `system.md` — TODO
      - `system.rendered.txt` — TODO
    - `evaluator/` — TODO
      - `extract_metrics.md` — TODO
      - `extract_metrics.rendered.txt` — TODO
      - `peer_review.md` — TODO
      - `peer_review.rendered.txt` — TODO
    - `orchestrator/` — TODO
      - `bfts_expand.md` — TODO
      - `bfts_expand.rendered.txt` — TODO
      - `bfts_expand_select.md` — TODO
      - `bfts_expand_select.rendered.txt` — TODO
      - `bfts_select.md` — TODO
      - `bfts_select.rendered.txt` — TODO
      - `lineage_decision.md` — TODO
      - `lineage_decision.rendered.txt` — TODO
      - `root_idea_selector.md` — TODO
      - `root_idea_selector.rendered.txt` — TODO
    - `pipeline/` — TODO
      - `keyword_librarian.md` — TODO
      - `keyword_librarian.rendered.txt` — TODO
    - `viz/` — TODO
      - `wizard_chat_goal.md` — TODO
      - `wizard_chat_goal.rendered.txt` — TODO
      - `wizard_generate_config.md` — TODO
      - `wizard_generate_config.rendered.txt` — TODO

## Architecture-boundary guards

These guards (subtask 018) keep the layering in
`docs/refactoring/003_dependency_boundary_report.md` from silently eroding. That
report's §16 status table enumerates eleven boundary rules **B1–B11**, and each
is mapped to a live in-process `pytest` guard — or an explicit `waived:` reason
for the boundaries that are CI/scripts or frontend concerns (not
`pytest`-testable in-process) — by `test_architecture_boundary_index.py`, whose
`_BOUNDARY_GUARDS` dict is the single auditable coverage map:

| Boundary | Rule | Guard |
| --- | --- | --- |
| B1 | skill code imports only `ari.public.*` | `test_public_api_boundary.py` |
| B2 | `ari-core` must not import `ari_skill_*` except the sanctioned `ari_skill_memory` edge | `test_core_does_not_import_skills.py` |
| B3 | viz routes stay thin (in-process wire-shape contract) | `test_api_schema_contract.py` |
| B4 | frontend imports DTO/TS types only | *waived* — TS/npm concern (063/065) |
| B5 | evaluator independent of CLI/viz/file-layout, and routes LLM calls via `LLMClient` | `test_evaluator_independence.py` |
| B6 | model backend (`ari/llm`) must not depend "up" on viz/evaluator/CLI | `test_model_backend_independence.py` |
| B7 | no core→viz inversion | `test_core_viz_direction.py` |
| B8 | storage / runtime-path hygiene | `test_no_user_home_writes.py` |
| B9 | prompts externalized | `test_prompt_extraction.py` |
| B10 | scripts = quality/analysis/report only | *waived* — CI concern (026/032/046) |
| B11 | CI staged warning→regression→strict | *waived* — CI concern (026/032/046) |

`test_all_boundaries_covered` fails if report 003 gains or loses a boundary and
the map is not updated; `test_named_guard_files_exist` fails if a named guard
file is renamed or removed. Together they ensure a newly-added boundary can
never ship silently unguarded and an existing guard can never be quietly
deleted.

**Shared helper — `_arch_boundaries.py`.** The leading underscore keeps it out
of pytest collection (`python_files` defaults to `test_*.py`), so it is a
test-only library, not a test module. It is a standard-library-only (`ast` +
`pathlib`) AST/text scanner shared by the guard modules instead of each
re-implementing an `ari.*` import walker. Key helpers: `repo_root()` /
`core_root()` (locate `ari-core/ari`), `iter_py()` (sorted `*.py` walk),
`imports()` (every dotted import target with its 1-based line number, via
`ast.parse`), `ari_imports()` (that list filtered to `ari` / `ari.*` /
`ari_skill*` targets), `top_package()`, `matches_prefix()`, and
`in_except_importerror()` (treats an import whose closest preceding line opens an
`except` handler as a sanctioned compat shim, not a hard edge). Everything here
only *reads* source files — nothing imports a skill `src/server.py`, the
single-process hazard documented in the repo-root `pytest.ini`.

**The `xfail`→green ratchet.** A boundary that is *already* achieved is guarded
by a plain passing assertion (B2, B6, and the general-rule cases of B5 and B7
pass today). A boundary that is a *known-still-violated* end-state is guarded by
a test decorated `@pytest.mark.xfail(strict=False, reason=…)` whose `reason`
names the subtask that will fix it. Two live examples:

- `test_evaluator_does_not_call_litellm_directly` (B5/B6) —
  `ari/evaluator/llm_evaluator.py` still imports `litellm` directly
  (`llm_evaluator.py:24`) and calls `litellm.acompletion`, bypassing
  `LLMClient` / `resolve_litellm_model`; xfailed until subtask 008/009 routes it
  through the model backend.
- `test_lineage_does_not_import_viz` (B7) — `ari/cli/lineage.py` still imports
  `ari.viz.api_orchestrator._api_launch_sub_experiment` (`lineage.py:149`);
  xfailed until subtask 011/012 inverts the launcher behind an injected hook.

The ratchet only ever tightens. Because the marker is `strict=False`, the day
the real fix lands the guarded assertion starts passing and the case reports
**XPASS** (visible via `pytest -rX`) instead of failing — that XPASS is the
signal to delete the `xfail` marker so the now-achieved boundary is enforced
going forward. A guard starts life at `xfail`, flips to green when its boundary
is achieved, and is never loosened back to `xfail` afterward.

## Prompt snapshot tests

`test_prompt_snapshots.py` (subtask 042) pins the on-disk prompt templates so an
unintended edit to any LLM prompt fails CI. It complements — and does not
replace — the hand-maintained `sha256` pin in `test_prompt_extraction.py`: that
module lists prompts explicitly, whereas this one **auto-discovers** every
`ari/prompts/**/*.md` template (via `package_prompts_root()` /
`_discover_keys`, excluding `README.md`), so a newly-added or deleted prompt
that is not re-blessed fails the suite. There are 11 discovered core keys today
(`agent/system`, `evaluator/*`, `orchestrator/*`, `pipeline/keyword_librarian`,
`viz/wizard_*`).

Each key is pinned three ways against goldens under `snapshots/prompts/`:

- **Raw template bytes** — `test_prompt_raw_snapshot[key]` compares
  `Path.read_bytes()` of the live template to `snapshots/prompts/<key>.md`.
  Comparison is byte-for-byte with no newline translation, so a template that
  ends without a trailing newline (`pipeline/keyword_librarian.md`) and one that
  ends with one (`evaluator/extract_metrics.md`) are each preserved exactly.
- **Rendered bytes** — `test_prompt_rendered_snapshot[key]` pins
  `template.format(**FIXTURE_KWARGS[key])` (fixture kwargs copied from the real
  call sites) to `snapshots/prompts/<key>.rendered.txt`. The two JSON-schema
  orchestrator prompts (`orchestrator/lineage_decision`,
  `orchestrator/root_idea_selector`) are loaded raw at their call sites and never
  `.format`-ed, so their `FIXTURE_KWARGS` entry is `None` and their rendered
  golden equals the raw template.
- **Placeholder set** — `test_prompt_placeholders[key]` asserts the exact
  `{field}` set (`string.Formatter().parse`) matches `EXPECTED_FIELDS[key]`, so a
  renamed or added placeholder is caught even if the surrounding bytes are
  re-blessed. `test_all_prompts_have_snapshots` additionally enforces a
  one-to-one match between discovered keys and both golden families.

**Re-bless flow.** Intentional prompt changes regenerate the goldens with the
`ARI_UPDATE_PROMPT_SNAPSHOTS` env var — when set to `1`, `_assert_snapshot`
writes the current bytes instead of comparing:

```
ARI_UPDATE_PROMPT_SNAPSHOTS=1 pytest ari-core/tests/test_prompt_snapshots.py -q
```

then re-run *without* the flag to confirm green; a clean `git diff` on the
`snapshots/prompts/` goldens confirms nothing else drifted. New prompts added by
sibling extraction subtasks should be re-blessed the same way.
