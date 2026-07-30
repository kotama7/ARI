# ari-core/tests

Pytest suite for ari-core (`test_*.py`), covering BFTS, the pipeline,
evaluator, viz API, CLI, and migration paths.

See `docs/guides/testing.md` for how to run & conventions; each `test_*.py`
targets the like-named module under `ari/`.

## Contents

- `README.md` — this file.
- `_arch_boundaries.py` — shared AST/text scanners behind the architecture-boundary guards (`imports`/`ari_imports`, `top_package`, `matches_prefix`, `in_except_importerror`); underscore-prefixed to stay out of pytest collection, stdlib-only, and it never imports a skill `src/server.py`.
- `test_agent_smoke.py` — agent smoke test.
- `test_api_lineage_decisions.py` — lineage-decisions API.
- `test_api_lineage_e2e.py` — lineage API end-to-end.
- `test_api_paperbench.py` — PaperBench API (incl. durable job records: atomic `{registry}/jobs/{id}.json` mirror of every `_JOBS` mutation, restart-simulation disk fallback with the additive `interrupted` status, traversal-safe job-id grammar).
- `test_api_paperbench_worker.py` — PaperBench API worker.
- `test_api_process.py` — process-control service (stop-all + GPU monitor).
- `test_api_schema_contract.py` — stable viz endpoint response-shape contracts.
- `test_architecture_boundary_index.py` — boundary coverage map (report `003` §16): every boundary B1-B11 must name a live guard file under `ari-core/tests/` or an explicit `waived:` reason, so a new or renamed boundary can never ship silently unguarded.
- `test_artifact_store.py` — `CheckpointArtifactStore` by-logical-name artefact access over the flat checkpoint layout: `ArtifactStore` ABC non-instantiability + structural conformance, text/bytes/source-path `put` with subdir creation, `exists`/`get` on misses, prefix listing.
- `test_bfts.py` — BFTS loop.
- `test_bfts_allow_web.py` — `bfts.allow_web` / `ARI_BFTS_ALLOW_WEB` toggle: web-skill phase gating in/out of bfts + the `bfts_web_provenance.json` marker roundtrip.
- `test_bfts_diversity.py` — BFTS diversity/fanout.
- `test_bfts_eval_config_integration.py` — BFTS + eval-config integration.
- `test_bfts_frontier_score.py` — BFTS frontier scoring.
- `test_bfts_prompt_builder.py` — byte-exact goldens for the pure `bfts_prompt_builder` context builders (`build_select_candidate_descriptions`, `build_expand_select_candidate_descriptions`, `build_expand_context`, `_BUDGET` re-export) pinning the extraction out of `BFTS` as behaviour-identical (P2 determinism).
- `test_bfts_prompt_selection.py` — BFTS prompt selection.
- `test_checkpoint_legacy_tree.py` — legacy node_*/tree.json resolution in list/summary.
- `test_checkpoint_store.py` — `JsonCheckpointStore` + module back-compat shims: byte-identical JSON writes, 3-tier `load_nodes_tree` precedence (incl. legacy `node_*` glob), the 1.0 s incremental throttle with per-instance isolation and loud forced-flush failures, and the `_INCR_LAST_SAVE_MONO` monkeypatch surface `test_gui_errors.py` relies on.
- `test_child_node_workflow.py` — child-node workflow.
- `test_child_workdir_inherit.py` — child workdir inheritance.
- `test_claim_evidence_hard_gate.py` — Story2Proposal Phase B deterministic gate: recompute, mismatch, operand resolution, coverage, blocking semantics.
- `test_claim_gate_contract.py` — declared-contract enforcement: `safe_eval` formula evaluator, `contract.check_contract`/`check_emission` (recompute mismatch, claim-evidence coverage, provenance/ceiling/correctness requirement flags, lexical near-miss hints) + gate blocking at final.
- `test_claim_gate_invariants.py` — concept→invariant registry (`classify_concept`, `CONCEPT_INVARIANTS`, `scan_science_data`): universal-math bounds (normalized≤1, probability in [0,1]) fire domain-neutrally, leave unbounded metrics alone, and block at final via `run_hard_gate`.
- `test_cli.py` — CLI.
- `test_cli_extended.py` — extended CLI cases.
- `test_cli_shim_toolcalls.py` — CLI shim (`ari.llm.cli_server`) function-calling: `extract_tool_calls`/`render_prompt`/`complete` turn text-only `claude -p`/`codex exec` into OpenAI `tool_calls`, plus cost passthrough and MCP-direct mode vs. text-catalog fallback.
- `test_clone.py` — clone behaviour.
- `test_config.py` — config loading.
- `test_container.py` — container runtime.
- `test_contract_snapshots.py` — golden-snapshot drift guard for the four stable contract surfaces — `ari.public.*` exports, the Typer CLI tree, the 14-skill MCP tool catalog captured by AST (incl. cross-skill name collisions), and the viz REST inventory/response keys — sharing `scripts/snapshot_contracts.py` helpers so pytest and `--check` can never disagree.
- `test_core_does_not_import_skills.py` — B2 guard: nothing under `ari-core/ari/**` may `import ari_skill_*` except the sanctioned `ari_skill_memory` edge, plus an anti-rot assertion that that edge is still real so the allow-list cannot pass vacuously.
- `test_core_viz_direction.py` — B7 core->viz direction guard: non-viz `ari-core` code must not import `ari.viz.*`, allow-listed by file to the dashboard-launching `ari/cli/commands.py`, with the known `ari/cli/lineage.py` inversion held as `xfail(strict=False)` until it is routed through an injected launcher hook.
- `test_cost_tracker.py` — cost tracker.
- `test_curate.py` — curation.
- `test_dashboard_html.py` — dashboard HTML.
- `test_data_flow.py` — data flow.
- `test_default_provider.py` — default LLM provider.
- `test_delegated_cli_terminal.py` — `AgentLoop.run` terminal-protocol handling for the cli-shim MCP-direct backend: one bounded nudge for the terminal JSON, acceptance from `results*.json` the delegated run verifiably wrote (`result_source="delegated_cli_artifacts"`, inherited files excluded), and strict inertness unless `last_request_delegated` is literally `True`.
- `test_delete_checkpoint_experiments.py` — checkpoint-experiment deletion.
- `test_disabled_tools_flow.py` — disabled-tools flow.
- `test_dynamic_axes.py` — dynamic evaluation axes.
- `test_ear.py` — EAR (experiment/analysis/report).
- `test_env_write_quoting.py` — .env-write quoting guard (api_settings upsert).
- `test_evaluator_axis_mode.py` — evaluator axis mode.
- `test_evaluator_composite.py` — evaluator composite scoring.
- `test_evaluator_independence.py` — B5 guard: `ari/evaluator/**` must not import `ari.cli`/`ari.viz`/`ari.paths`/`ari.checkpoint` (except-`ImportError` compat shims ignored), with the direct `litellm` import/`acompletion` call in `llm_evaluator.py` that bypasses `LLMClient` held as `xfail(strict=False)`.
- `test_evaluator_protocol.py` — conformance for the extended `ari.protocols.Evaluator`: `LLMEvaluator` satisfies it structurally without subclassing, the Protocol stays `runtime_checkable`, an evaluator lacking `evaluate_sync`/`metric_spec` is rejected (the extension is not vacuous), and the `AgentLoop` injection seam still defaults to `None`.
- `test_event_loop_and_csv.py` — event loop + CSV logging.
- `test_factory_registry.py` — unified factory layer: `ari._factory.BaseRegistry` eager/lazy registration with a uniform unknown-key error, composite-registry keys vs the `EvaluatorConfig.composite` `Literal`, publish backends vs the `publish.schema.json` enum (the schema-only `s3` gap must raise, not resolve), and the `_COMPOSITES`/`_load_backend` back-compat shims.
- `test_file_explorer.py` — file explorer.
- `test_gui_baseline_run_fixtures.py` — gui_refresh Wave 0 / G0 deterministic reference run fixtures: `fixtures/gui_refresh/run_fixture_factory.py` output loadable via `ari.checkpoint.load_nodes_tree` (small/medium), same-seed byte-identity, corrupt modes (`truncated_jsonl`/`invalid_json`/`partial_write`) pinned to current loader behaviour, large(10k) generation.
- `test_gui_baseline_settings_contract.py` — gui_refresh Wave 0 / G0 frozen legacy Settings contract: GET 27-key default shape (+10-key `ors`), shallow `{**defaults, **saved}` merge, POST whole-file replace, api-key pop/.env upsert/silent drops, `letta_api_key` plaintext-persist defect, no-checkpoint 400 refusal, and the 24-key frontend Save body (pinned against `SettingsContract.test.tsx`).
- `test_gui_bind_cors.py` — gui_refresh Wave 5a (task 09) RR-P0-3/MN-4 bind + CORS: `resolve_bind_hosts` loopback default + `ARI_GUI_BIND` override forms (pure, no sockets), `_make_http_server` AF_INET vs dual-stack class selection (loopback port-0 only), `_origin_allowed` same-origin matrix (Host match / loopback:port aliases / scheme + opaque-origin rejection), `_json`/`do_OPTIONS`/SSE (`/api/logs`, `/api/v1/events/stream`) Origin echo vs ACAO omission via socketless handlers, `ARI_GUI_CORS_ANY=1` wildcard kill-switch.
- `test_gui_capabilities.py` — gui_refresh Wave 1 `GET /api/capabilities`: ARI_GUI_V2 flag default ON, `'0'`/`'false'` kill-switch, frozen `{gui_v2, server_version}` payload (handler called directly, no server).
- `test_gui_config_field_registry.py` — gui_refresh Wave 3a canonical config field registry: 144-leaf walk of `ARIConfig`, FIELD_META overlay coverage invariant (`get_uncovered()==[]`), env-override map, metadata spot checks, determinism, `GET /api/v1/config/schema` (secret fields metadata-only).
- `test_gui_config_precedence_matrix.py` — gui_refresh Wave 3b precedence matrix goldens: per-layer new-run chain (defaults<workflow<profile 4-key<project<template<draft<env), ignored-profile-key warnings, rejected-type retention, RQGM interlock warn+fallback, resume-mode immutability.
- `test_gui_config_resolver.py` — gui_refresh Wave 3a legacy-compatible resolver: existing-checkpoint manifest (values/provenance/confidence/digest), rqgm_state mode priority, secret redaction from payload+digest, silent-drop warnings, golden parity vs the real `load_config`+env-override chain, `GET /api/v1/runs/{run_id}/resolved-config`.
- `test_gui_config_shadow_legacy.py` — gui_refresh Wave 3b legacy shadow diff: legacy 24-key Settings save+launch env chain vs canonical `resolve_new_run_config` per-leaf equality with an explicit known-divergence allowlist (G0 known-mismatch table).
- `test_gui_confirmation_challenges.py` — gui_refresh Wave 5a (task 09) RR-P0-6/RR-P0-9/MN-6 server-issued confirmation challenges: `POST /api/v1/challenges` issuance shape (`chg-<12hex>`, action/target echo, 60s TTL) + body validation 400s + deque cap-100 eviction, single-use/monotonic-expiry/action+target-binding consumption, MN-6 enforcement on `POST /api/delete-checkpoint`/`POST /api/stop`/`POST /api/gpu-monitor` stop (frozen `{ok:false}` + 428, no destructive work, no process touched), happy-path delete of a tmp checkpoint with a valid grant + replay refusal, `ARI_GUI_CHALLENGES=0` kill-switch, `viz_access.jsonl` `challenge_*` audit lines.
- `test_gui_csp_headers.py` — gui_refresh Wave 5a (task 09) RR-P0-10/MN-7 browser security headers: pure `_csp_policy` directive set ('self'-based; style-src 'unsafe-inline' accepted residual; ws/wss connect-src on HTTP port+1 from the Host header with loopback fallback + IPv6 re-bracketing + no-port omission; frame-src 'self'; frame-ancestors 'none'), CSP/nosniff/Referrer-Policy emission on `GET /` + SPA fallback + `/static/...` via socketless handlers, `_json` API responses out of scope, `ARI_GUI_CSP=0` kill-switch restoring the pre-MN-7 header set.
- `test_gui_env_propagation.py` — GUI env propagation.
- `test_gui_errors.py` — GUI error handling.
- `test_gui_health_diagnostics.py` — gui_refresh Wave 5b (task 09) plan 09 §Operational visibility/MN-9 health probes + bounded diagnostics: `GET /health/live` constant `{"status": "ok"}` (no dependency consulted — still ok when every readiness check raises), `GET /health/ready` check map (http/websocket/watcher/event_bus/active_checkpoint; all-green => ok, dead watcher thread => degraded with HTTP 200 — never a 500, crashing check reads as false), MN-8 interplay (`/health/*` auth-exempt in remote mode while `GET /api/v1/diagnostics` requires the Bearer token), diagnostics shape (sse subscribers/buffer_len/last_event_id via `events.bus_stats`, watcher alive/last_scan_age_s, process tracked_runs count, `cache: false`, schema/openapi versions) with zero secret/checkpoint-path leakage, `stream_events` live subscriber counting, `state_sync._watcher_thread` handle self-registration + heartbeat stamping, `ARI_GUI_HEALTH=0` kill-switch (SPA fallback restored, diagnostics typed 404).
- `test_gui_path_proxy_hardening.py` — gui_refresh Wave 5a (task 09) RR-P0-5/RR-P0-7/MN-5: `_codefile_resolve` canonical boundary (active checkpoint + checkpoint search bases; negative: `../` traversal, symlink escape, `/etc/passwd`, crafted `*/checkpoints/*` outside bases, directory/missing), `GET /codefile` end-to-end via socketless handler + run fixture factory, Ollama proxy gate (`_ollama_proxy_refusal` five-path allowlist, 403 with no upstream connection when no host configured and backend is not ollama, settings/`OLLAMA_HOST` opt-in incl. cli-shim).
- `test_gui_remote_auth.py` — gui_refresh Wave 5b (task 09) RR-P0-3 auth sub-scope/MN-8/ADR-13 remote bearer-token auth: pure `is_remote_bind` bind classification + `resolve_token` matrix (local => no auth even with a token exported, remote + `ARI_GUI_TOKEN` => that token, remote unset => fail-secure generated 32-hex, `ARI_GUI_AUTH=0` kill-switch) + `check_authorization` Bearer-header/query-token acceptance with `hmac.compare_digest` pinned by source, `_Handler` gate via socketless handlers (loopback default unauthenticated; remote 401 typed body + `WWW-Authenticate` without echoing the token across GET/POST/PUT/PATCH/DELETE; 200 with the token; `/health/*` exemption; SSE query token on the EventSource-consumed streams `/api/v1/events/stream` + paperbench run logs, header auth on the fetch-consumed legacy `/api/logs`), `_ws_process_request` handshake 401 vs query/header token, `viz_access.jsonl` `token=***` redaction, one-time generated-token stderr banner.
- `test_gui_rqgm_fixtures.py` — gui_refresh Wave 4a deterministic RQGM checkpoint fixtures: `fixtures/gui_refresh/rqgm_fixture_factory.py` layered on the base run factory — per-artifact `ari/schemas` validation, hash12 chain integrity + utility-policy seal parity, `RqgmStateStore.replay` snapshot consistency, same-seed byte-identity, corrupt modes (`broken_chain`/`truncated_transitions`/`registry_mismatch`), penalty/erasure sentinel truth rules (raw attack never scores), base `simple_bfts` fixture byte-untouched.
- `test_gui_secret_readiness.py` — gui_refresh Wave 3a/3b secret readiness + RR-P0-2/RR-P0-4: `GET /api/v1/secrets/status` (configured/source_class/mtime, structurally value-free), legacy env-keys redaction, POST name allowlist, atomic 0o600 `.env` upsert hardening.
- `test_gui_state_facade_freeze.py` — gui_refresh G2 tail (plan 04 §Caching and polling policy) `/state` legacy-facade freeze: the exact top-level key set of `services.state_service.build_app_state` pinned as frozen literals for the no-checkpoint (7-key) and fully-populated-checkpoint (35-key) scenarios — additive growth fails with a pointer to run-explicit `/api/v1` endpoints, key removal fails as a legacy-parity break; plus the FROZEN source-header marker guard.
- `test_gui_v1_api.py` — gui_refresh Wave 2a `/api/v1` read-only platform: router matching/params, frozen 404 envelope, request_id, projects/runs/detail/summary/tree over `run_fixture_factory` checkpoints, tree byte-parity, the Wave 4c `runs/{run_id}/idea` read model (pure `idea.json` read; absent file => `present=false`, never fabricated empties), GET side-effect-freeness, OpenAPI drift guard.
- `test_gui_v1_config_crud.py` — gui_refresh Wave 3b config CRUD: project config GET/PATCH, run-templates CRUD, run-drafts, If-Match optimistic concurrency (frozen 409 `revision_conflict`), `validate_patch` closed-vocabulary rejections, mtime-derived `updated_at`.
- `test_gui_v1_events.py` — gui_refresh Wave 2b SSE: event bus (ring buffer/replay/`Last-Event-ID`/filtering), `GET /api/v1/events/stream` framing/heartbeat/disconnect, watcher + switch-checkpoint publication hooks.
- `test_gui_v1_launch.py` — gui_refresh tasks 04/06 Wave 4e (MN-10) `POST /api/v1/runs` idempotent launch (`subprocess.Popen` always mocked): validation-first (typed 400 with `details.errors`, NO dir / NO spawn / NO idempotency record on rejection; `mode_locked` for governance/tuning `rqgm.*` draft fields — the four ADR-09 mode leaves are carved out and covered by `test_gui_v1_mode_selection.py`; `missing_goal`), server-minted `<UTC ts>_<slug>-<6hex>` run identity, checkpoint materialization before spawn (experiment.md from the draft goal, bundled workflow.yaml CoW seed, legacy-compatible launch_config.json, resolved_config.json digest parity with the resolve-config preview, `launch_events.jsonl` draft→validating→accepted→spawned monotonic lifecycle), GUI-layer `ARI_*` env translation + `ARI_CHECKPOINT_DIR` pinning, `gui_store/launches/{key}.json` replay (same run_id + `idempotent_replay: true`, Popen called once, restart-survivable), parallel/no-key distinct runs, spawn-failure typed 500 + claim release, `run` bus event, and the additive draft `goal` round-trip.
- `test_gui_v1_logs.py` — gui_refresh task 07 tail `GET /api/v1/runs/{run_id}/logs` cursor log explorer (plan 07 §Artifacts, logs, and diagnostics): raw byte-offset cursor pagination over `{ckpt}/ari.log` (3-page chain no-gap/no-duplicate, stable under concurrent appends), case-insensitive `grep` that filters returned lines while cursors stay filter-independent raw offsets, committed-only reads (partial trailing line never emitted, served after later completion), bounded ≤1 MiB scan window per request (early return with `eof=false` + advanced cursor on a big synthetic log — never one whole-file read), honest absence (missing `ari.log` ⇒ 200 `present=false`, unknown run ⇒ typed 404, bad cursor/limit ⇒ typed 400), default-200/cap-1000 limits, GET side-effect-freeness/determinism, non-UTF-8 bytes degrade to replacement.
- `test_gui_v1_mode_selection.py` — ADR-09 (accepted 2026-07-27) GUI mode selection for a NEW run (`subprocess.Popen` always mocked): the default `simple_bfts` + `linear` path stays byte-identical to a pre-ADR-09 baseline draft (checkpoint `workflow.yaml` byte-equal to the bundled CoW seed — no `ari:`/`rqgm:`/`paper:` block —, none of `ARI_MODE`/`ARI_RQGM_ENABLED`/`ARI_PAPER_MODE`/`ARI_RQGM_PAPER_ENABLED` exported, unchanged artifact set, identical values/digest, provenance the only difference), a non-default intent materialized BOTH ways (minimal blocks merged into the per-checkpoint copy — bundled file never written, unknown keys kept — plus the documented env vars and `draft`/`template` provenance in `resolved_config.json`), the two axes orthogonal (2×2 matrix), the pair as ONE intent (half-set/disagreeing → 400 `mode_interlock_mismatch` at create/PATCH/launch with zero filesystem mutation, closed `PATCH_REASONS` vocabulary pinned), the carve-out bounded (non-mode `rqgm.*` still 400 `mode_locked`, mode paths in the project config still 400 `not_project_scope`, locked set = registry governance minus the four), both materialization channels resolving to the same effective modes through the real authorities (`load_config` + `resolve_effective_mode`/`resolve_paper_mode`, and `apply_rqgm_env_overrides`/`apply_paper_env_overrides` over the exported env), a template-carried pair honored at launch, the resolver's interlock warn+fallback surfaced (env-broken twin → resolved value + warning in the preview, launch refuses), and resume untouched (`reconcile_resume_mode`: persisted `rqgm_state.json` wins, downgrade-only; no launch path writes it).
- `test_gui_v1_results.py` — gui_refresh task 07 Wave 4d `runs/{run_id}/results` + `runs/{run_id}/ear` read models (plan 07 §Evidence, Results, and PaperBench): fixture variants bare/reviewed/ORS-graded/EAR-published (`run_fixture_factory` paper/review/ors/ear layers), review score fallback chain, ORS verdict parity with the legacy `ear._synth_repro_report_from_ors` synthesis, EAR curate→publish→promote lineage scalars + bounded listing, corrupt artifacts → 200 + `degraded_reasons`, GET side-effect-freeness/determinism.
- `test_gui_v1_rqgm.py` — gui_refresh Wave 4a `/api/v1/runs/{run_id}/rqgm/*` read models (task 08, plan 08): all 8 GET endpoints over the RQGM fixture factory — two-channel score lineage separation (penalty vs epoch-policy, raw attacks structurally scoreless), committed-only reads (torn append / uncommitted prepare tail never adopted), byte-offset cursor paging (no gap/duplicate), corrupt fixtures → 200 + integrity flags + `degraded_reasons`, registry/status vocabulary parity with `ari.rqgm.events`, non-RQGM 404 envelopes, GET side-effect-freeness, GET-only surface.
- `test_gui_v1_secret_put_and_catalogs.py` — gui_refresh task 06 Wave 4d (ADR-05): `PUT /api/v1/secrets/{secret_id}` write-only assignment (SECRET_NAMES allowlist → 404, value validation → 400, hardened `_upsert_env_key` delegation, readiness flip, value never echoed in any response) + `GET /api/v1/config/catalogs/models` (legacy `/api/models` parity single-source, per-provider env-key join, `PROVIDER_ENV_KEYS ⊆ SECRET_NAMES`).
- `test_gui_v1_store.py` — gui_refresh Wave 3b `gui_store/` document store (ADR-12): atomic write/crash safety, monotonic revisions + RevisionConflict, 0o600/0o700 modes, deterministic listing, ID validation, corrupt-document semantics.
- `test_gui_workflow_revision.py` — gui_refresh Wave 4d (plan 07 §Workflow Studio): weak `revision` (sha256[:12]) on `GET /api/workflow`, optional `base_revision` on the four workflow write endpoints — stale → frozen 409 without writing (CoW seed skipped), match → write + new revision returned, absent → legacy last-write-wins; the Wave-2a 400 guard keeps precedence.
- `test_gui_workflow_write_guard.py` — gui_refresh Wave 2 ADR-10/RR-P0-1: workflow write endpoints refuse without an active checkpoint (frozen 400, bundled `workflow.yaml` byte-untouched) and copy-on-write seed the per-checkpoint copy.
- `test_i18n_consistency.py` — i18n consistency.
- `test_idea_integration.py` — idea integration.
- `test_include_ear_toggle.py` — include-EAR toggle.
- `test_integration.py` — integration.
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
- `test_model_backend_independence.py` — B6 layering guard (report `003` §8): the model-backend layer `ari/llm/**` imports none of `ari.viz` / `ari.evaluator` / `ari.cli` (litellm stays allowed — that is where the provider dependency belongs).
- `test_model_backend_protocol.py` — subtask 008 `BaseModelBackend` Protocol conformance: `LLMClient` structurally satisfies the `runtime_checkable` Protocol without subclassing, and the `LiteLLMBackend` alias plus `ari.public.llm.LLMClient` still resolve to it.
- `test_model_passthrough.py` — model passthrough.
- `test_no_user_home_writes.py` — no-user-home-writes guard.
- `test_node.py` — Node data model.
- `test_node_report.py` — node_report builder.
- `test_node_selection.py` — node selection.
- `test_nodes_to_science_data_shrink.py` — nodes→science-data shrink.
- `test_ollama_gpu.py` — Ollama GPU.
- `test_orchestrator.py` — orchestrator.
- `test_page_requirements.py` — page requirements.
- `test_paper_agent_as_judge.py` — paper-archive Task 03 §5.8 agent-as-judge `reviewer_score_fn`: reads the venue rubric axes (novelty/significance) so it discriminates two drafts the LLM-free rubric ties at the ceiling, threads the ACTIVE reviewer prompt as emphasis, and fails open to `deterministic_rubric_score_fn` on any LLM error or unparseable score (scripted LLM double).
- `test_paper_anchor.py` — paper-archive Task 04 `ari.rqgm.paper_anchor`: accept/reject binarization + agreement metric, run-fixed held-out split, machine-enforced bootstrap-label cap and self-label bar, `PaperAnchorPool` board interop, the `paper_utility_policy` freeze, and the writer's claim-gate faithfulness anchor made OPERATIVE through `adjudicate_motion`'s `board_score`.
- `test_paper_archive_search.py` — paper-archive Task 02 draft-archive search substrate: best-first draft TREE with `bfts.py` cutoff reuse, the real `select_best_to_expand` + framing-keyed `diversity_bonus`, per-epoch `max_expansions` cap, `PaperDraftExecutor` (one generative call per node), lazy compile, `paper_draft_archive.jsonl` schema/registration, Protocol conformance and determinism, plus the `rqgm_archive` startup smoke and resume over `PaperArchiveRuntime.run_archive`.
- `test_paper_mode.py` — paper-archive Task 01 paper execution-mode switch: `paper.mode` / `rqgm.paper.enabled` config parsing, the four-cell `resolve_paper_mode` table with both warning paths, `apply_paper_env_overrides`, `paper_archive_state.json` round-trip + META_FILES registration, the linear identity regression (no `ari.rqgm` imports/objects/files on a default run), independence from `ari.mode`, and the persisted-mode-wins re-invocation rule.
- `test_paper_self_preference.py` — paper-archive Task 05 `paper_self_preference` adversary: deterministic pre-signal, AI-vs-human margin statistic + audit artifact, record vocabulary and Task-15 target binding to `paper_reviewer_v1`, paper-mode-gated founding rows, exploration/linear byte-identity, and the anti-inertness proof — organic impeachment of an always-accept reviewer through the real adversary→Defender→ArtifactJudge round, with anchor-removed / no-governance negative controls.
- `test_paths.py` — path resolution.
- `test_pidfile.py` — pidfile handling.
- `test_pipeline_e2e.py` — pipeline end-to-end.
- `test_pipeline_metric_parsing.py` — pipeline metric parsing.
- `test_pipeline_stage_architecture.py` — subtask-012 stage-architecture characterization: `BasePipelineStage` / `SubprocessMCPStage` / `ReActStage` / `WorkflowDriver` / `StageContext` importable from `ari.pipeline`, `make_stage` dispatch by `react` key, stage identity fields, and dispatch through the `ari.pipeline._run_stage_subprocess` monkeypatch surface — structure only, no real MCP subprocess or LLM call.
- `test_pipeline_verified_context.py` — verified-context building blocks (best-node selection, lineage scoping, grounded-block renderer).
- `test_plan_promote.py` — plan promotion.
- `test_prompt_extraction.py` — prompt extraction.
- `test_prompt_provenance.py` — subtask 044 prompt-provenance recorder + run rollup: `hash12` determinism matching `load_versioned`, the additive-schema JSONL record, no-op without a checkpoint dir, env-pin resolution, `build_prompt_versions_rollup`, and ARI-metadata registration of the new artifact filenames.
- `test_prompt_registry.py` — subtask 038 `PromptRegistry`: discovery of exactly the 28 core keys (READMEs excluded), byte-/hash-identical delegation to the wrapped `FilesystemPromptLoader`, placeholder parsing tolerant of `{{`/`}}` JSON escapes, the config-injected-key tolerance policy, and loader dependency injection.
- `test_prompt_snapshots.py` — subtask 042 auto-discovered prompt snapshots: every `ari/prompts/**/*.md` pinned as raw bytes plus its `str.format`-rendered output and placeholder set, so an added/deleted/edited template that was not re-blessed (`ARI_UPDATE_PROMPT_SNAPSHOTS=1`) fails.
- `test_public_api_boundary.py` — public-API boundary.
- `test_publish_and_registry.py` — publish + registry.
- `test_publish_yaml_api.py` — publish YAML API.
- `test_publish_zenodo_gh.py` — publish to Zenodo/GitHub.
- `test_react_driver.py` — ReAct driver.
- `test_resolve_node_work_dir.py` — resolve node work dir.
- `test_retrieval_backend.py` — retrieval backend.
- `test_root_idea_selector.py` — root-idea selector.
- `test_rqgm_adversarial.py` — RQGM Task 06 adversarial evolution loop: schema round-trip/validation for all six record types, `UtilityPenaltyPolicy.compute` arithmetic + `apply_utility_penalty` guards, the AdversarialReplayPool (admission/dedup/eviction, contamination-safe `abstract_view`, capability-checked `replay_view`), the §5.5 trigger predicate, the raw-attacks-never-score regression, resume idempotency, the `simple_bfts` zero-file regression, plus Task 15's `target_component_id` accountability binding (self-binding refusal, frozen-not-live resolution, fail-open matrix).
- `test_rqgm_clean_room.py` — RQGM Task 08 clean-room regeneration: the `CleanRoomGenerationRequest` schema, deterministic closed-field bundle assembler (planted forbidden material never enters a bundle), the §5.5 contamination screen, Layer-B retired-text capability denial (kernel CK-ACC-002), the never-instantly-active rule, per-epoch generation budget, the retirement→request→generation→candidate chain over a deterministic fake generator, contaminated-output fail-open, and the `simple_bfts` zero-import/zero-file regression.
- `test_rqgm_context_views.py` — RQGM Task 12 role-specific context views: three-layer ProposalSummaryView-only enforcement for BFTS (typed renderer input → `TypeError`, kernel `validate_context_scope` sharing the same whitelist constant, archive-only-field leak regression) plus the §5.7 visibility exclusions — the Judge never sees frontier scores, governance never sees retired prompt text, same-role isolation is constructive.
- `test_rqgm_cost_budget.py` — Task 12 cost control: golden `cache_key` composition (timestamps excluded), the `assign_level` §5.2 trigger table, hash-based shadow sampling, budget-counter exhaustion + audit-log round-trip, and the replay cache-lookup rule.
- `test_rqgm_epoch_state.py` — Task 02 structures, vocabulary and hash discipline: `canonical_json` byte goldens, `hash12` as the single provenance scheme, closed event/status vocabularies, frozen `EpochState`, wall-clock-free `epoch_fingerprint`.
- `test_rqgm_eval_conditions.py` — Task 13 ablation matrix: pins each B0-B8 preset to its exact overlay AND to the effective config `ari run --config` resolves, the additive-ladder property, and typed-field coverage of every overlay key.
- `test_rqgm_eval_detection_fixture.py` — Task 13 Tier-1 fixtures: the committed injection checkpoints are caught by the EXISTING deterministic detectors (claim gate, Task 07 candidate validation, `validate_clean_room_bundle`, `validate_selective_erasure`) and the control fixture passes clean.
- `test_rqgm_eval_doubles.py` — Task 13 scripted component doubles: the documented key set, LLM-free determinism, `resolve_double` refusing substitution unless `rqgm.eval.enabled`, and each double's failure caught by the same checks production faces.
- `test_rqgm_eval_injection.py` — Task 13 failure-injection machinery: the ten specs in `failure_injections.yaml`, `eval_*` namespace disjointness from governance's `adv_*`/`anchor_*`, deterministic idempotent `apply_injection`, and the provenance-marker round-trip.
- `test_rqgm_eval_metrics.py` — Task 13's thirteen evaluation metrics against known-answer fixtures: absence tolerance (missing records ⇒ `applicable: false`, never an exception), byte-determinism, sterile/stale exclusion, and the `rqgm_eval_metrics.json` envelope.
- `test_rqgm_eval_smoke.py` — Task 13 offline smoke runner: `run_smoke` writes per-run metrics + `ablation_report.{json,md}` with no LLM/network/subprocess, keeps the B0 checkpoint RQGM-artifact-free, and degrades rather than crashes on a misbehaving double.
- `test_rqgm_founding_bootstrap.py` — GAP-1/GAP-3 regression: `RQGMRuntime._register_founding` actually fires at boot (registry no longer empty), is byte-stable across identical boots, replays instead of re-registering on resume, and governance resolves real registered actor ids instead of `*_v0`.
- `test_rqgm_frontier_repair.py` — Task 10 FrontierRepair and selective erasure: the pure `trace_dependents` closure and `rebuild_frontier`, the per-role invalidate-vs-recompute policy, the no-physical-deletion byte compare, and the conservative → drain-only failure ladder.
- `test_rqgm_governance.py` — Task 05 GovernanceOrchestrator: reliability aggregation, evidence admissibility and the same-role accusation prohibition, prosecution thresholds / bond ledger / motion caps, the `llm=None` fallback floor, and the Task 15 producer→consumer chain driven from real `make_validated_attack_record` output.
- `test_rqgm_kernel.py` — Task 04 ConstitutionalKernel: a trigger/pass fixture per violation code over all twelve entry points, the T1-T19 transition table, audit-chain integrity, the pinned `constitution_hash`, and the enforcement adapters (blocked transitions, MCP pre-flight denial, fail-open per-node hook).
- `test_rqgm_meta_evolution.py` — Task 11 meta-agent evolution: the tier + capability-flag schema with hard-denied flags const-false, invariant-18 authority non-expansion, no-handle containment (frozen views, retired stubs), the outputs-are-candidates rule, and the `MetaSandboxMCPProxy`.
- `test_rqgm_mode.py` — Task 01 execution-mode switch: `ari.mode`/`rqgm.enabled` parsing, the four-cell `resolve_effective_mode` table, env overrides, `rqgm_state.json` round-trip, the simple_bfts identity regression, and the resume rule (persisted mode wins, no mid-run upgrade).
- `test_rqgm_paper_candidate.py` — The three paper-phase hooks: `ari paper` pre-flight escalating the best node through one adversarial round + the L3 ladder, `build_artifact_bundle` populated from real checkpoint artifacts, and the constitution-pinned `paper_writer` context view.
- `test_rqgm_paper_cost.py` — Paper-archive Task 06 budget: the single additive `PAPER_ANCHOR_SCORING` cap, verbatim reuse of every existing cap, the depth-independent `paper_expansion_budget` and `should_prune` total-node cutoff, and the resume-safe `budget_counters` mirror.
- `test_rqgm_paper_eval.py` — Paper-archive Task 07: the pure idempotent `materialize_winner` handoff to `full_paper.tex`, the winner reaching the existing Layer-0 claim gate unchanged, metrics P1-P5, the B-baseline ladder, and the PI3 impeachment of an always-accept reviewer through the real adversary.
- `test_rqgm_paper_roles.py` — Paper-archive Task 03 writer/reviewer roles: `paper_writer` promoted to a full evolvable role, `paper_reviewer` added, paper-mode-gated founding registration (exploration boot byte-identical), and the co-evolution smoke proving the active reviewer `prompt_hash` really changes at a boundary.
- `test_rqgm_prompt_boundary_evolution.py` — The live-path wiring fixes: the boundary window now mints PromptMutator candidates for every evolvable role (was a hardcoded `candidate_prompts=()`), every boundary leaves a `meta_evolution` audit line, and `RQGMRuntime` wires deterministic meta invokers with cross-channel dedup.
- `test_rqgm_prompt_evolution_records.py` — Task 07 persistence: the fail-open append-only JSONL writer, schema round-trip for the three record shapes, deterministic `prompt_specs.json` rollup derivation, and META_FILES / _TRACE_FILES / node-report blocklist registration.
- `test_rqgm_prompt_lifecycle.py` — Task 07 candidate lifecycle: monotonic six-stage order with no skipping, terminal dry-run failure, founding specs as the sole active-on-creation path, PromptMutator's registry-free write surface, per-epoch budgets, shadow sampling, and the `ari_rqgm` bootstrap→adoption smoke.
- `test_rqgm_prompt_loader.py` — Task 07 `GovernedPromptLoader`: Protocol conformance, byte-identical delegation for ungoverned keys, checkpoint-scoped `template_ref` resolution, hash-mismatch refusal, and the write-once evolved-body store.
- `test_rqgm_prompt_spec.py` — Task 07 `PromptSpec`: schema round-trip, the founding bootstrap whose `prompt_hash` equals `load_versioned(key)[1]` (one hash scheme, no migration), the role/evolvable assignment table, and `prompt_registry_version` stamping parity with Task 02.
- `test_rqgm_prompt_validation.py` — Task 07 deterministic stages 1-3: static validation (placeholder drift, forbidden placeholders, size, dead-parent lineage, in-place mutation), constitutional validation (mandatory constraints, clean-room contamination, no instant activation, same-role generation), and `check_output_against_schema`.
- `test_rqgm_proposals.py` — Task 03 `ProposalRecord` / `ProposalStore` / `ProposalRouter`: schema + summary-budget validation, the 9-key `idea.json` projection golden, the deterministic routing policy table, Stage-1 record-only dual-write, and the simple_bfts identity regression.
- `test_rqgm_state_store.py` — Task 02 persistence: event append/replay round-trip, hash-chain discipline over canonical payloads, prepare-without-commit crash recovery, snapshot rebuild on mismatch, the `EpochTransaction`/emergency write paths, and the two-epoch boundary smoke.
- `test_rqgm_transition_engine.py` — Task 09 `RegistryTransitionEngine`: the exhaustive 21-row edge matrix through the kernel, per-rule T1-T19 trigger/guard fixtures, boundary-only vs. the single emergency shape, prepare/commit crash recovery and double-apply no-op, and actor separation via epoch invariance.
- `test_rqgm_utility_boundary.py` — THE P1 test — a real `ari_rqgm` runtime driven through natural boundaries (no hand-built transition) rewrites `utility_policy_hash` and `epoch_fingerprint`, retires the incumbent under the old hash, and leaves every node scored under it flagged `utility_invalidated` with no recompute.
- `test_rqgm_utility_evolution.py` — Task 14's cause half: closing the `utility_policy`/`policy_mutator` role limbo, capability-matrix parity, `capture_utility_policy`'s precedence over static cfg, the one-value-three-names identity bridge, and `PolicyMutator`'s candidates-only deterministic contract.
- `test_rqgm_virsci_adapter.py` — Task 03 `VirSciAdapter`: normalization of the canned 9-key `generate_ideas` payload, the archive/summary split (no transcript text in any expand context), MCP retry idempotency, and the `virsci.enabled=false` never-constructed guarantee.
- `test_run_env.py` — run environment.
- `test_run_integrity.py` — the run-integrity aggregate: a check that did not run is `null` not clean; unverified assertions counted apart from wrong ones; an unrequested verification claim reaches the summary.
- `test_run_loop.py` — run loop.
- `test_runtime_path_reconciliation_005.py` — workspace-root reconciliation: `auto_config()`, the Pydantic field defaults and shipped `config/default.yaml` all spell the same canonical workspace root, while legacy relative `./checkpoints/{run_id}/` stays resolvable.
- `test_sandbox_shim.py` — sandbox shim.
- `test_selection_contract.py` — selection contract.
- `test_server.py` — viz/API server.
- `test_settings_propagation.py` — settings propagation.
- `test_settings_roundtrip.py` — settings roundtrip.
- `test_setup_env.py` — setup_env.sh behaviour.
- `test_skill_public_contract.py` — skills import core via the public contract.
- `test_status_fallback.py` — status fallback.
- `test_system_prompt_memory.py` — system-prompt memory.
- `test_tool_timeout_tier.py` — MCP `_resolve_tool_timeout` tiering: LLM/compile paper stages (incl. `paper_refine`, `compile_paper`) get the slow timeout, plain tools the 300s default (regression guard for the paper_refine shim-congestion timeout).
- `test_trace_log_truncation.py` — trace-log truncation.
- `test_trace_store.py` — `JsonlTraceStore`: node reports byte-identical to `node_report.write_node_report`, missing/corrupt reads returning `None`, sibling-report lookup by id or object, and the append-only per-node trace over the flat node-work-dir layout.
- `test_tree_view_adapter.py` — `ari.viz.tree_view.build_tree_view` as the single tree-view backend: the WS `update`, watcher broadcast and `/state` all route through it, and its output stays byte-identical to `load_nodes_tree` across empty/single/multi/legacy layouts.
- `test_upload_to_node.py` — upload to compute node.
- `test_variable_passthrough.py` — variable passthrough.
- `test_verified_context_wiring.py` — orchestrator gating of verified_context.json on `ARI_MEMORY_CONSOLIDATE` (off→skip / on→build / build-failure→pipeline survives).
- `test_virsci_off.py` — VirSci-off path.
- `test_viz_dto_schema.py` — viz dashboard wire contract: real handler payloads validated against the committed `viz_*.schema.json` files (dependency-free required-key checks) with each schema's required keys cross-checked against the frontend `types/index.ts`.
- `test_viz_fewshot_api.py` — viz few-shot API.
- `test_viz_file_service.py` — viz `FileService` primitives: the single path-traversal validator, the named byte-size limits, the file-classification sets, the canonical content-type table, and the read/write/delete helpers.
- `test_viz_memory_api.py` — viz memory API.
- `test_viz_node_report_api.py` — viz node_report API.
- `test_viz_repro_synth.py` — viz repro-synth.
- `test_wizard.py` — wizard.
- `test_workflow_contract.py` — workflow contract.
- `test_workflow_editor.py` — workflow editor.
- `test_workflow_template_resolution.py` — workflow template resolution.
- `test_working_context_injection.py` — `loop.build_working_context_messages` Tier-1/2 injection: experiment core + selected idea, deterministic per-entry-capped ancestor conclusions, deduped semantic supplement, persisted metric-contract obligation (with platform note) for every node, and pinned-window marker matching.
- `fixtures/` — test fixtures (not enumerated)
- `snapshots/` — committed goldens for the snapshot suites; currently only `prompts/`.
  - `prompts/` — raw `.md` + `.rendered.txt` golden pair per auto-discovered `ari/prompts/**/*.md` key, pinned by `test_prompt_snapshots.py`.
    - `agent/` — golden pair for the agent ReAct system prompt.
      - `system.md` — byte golden of the tool-first research-agent system prompt.
      - `system.rendered.txt` — that template rendered with the `{tool_desc}` / `{memory_rules}` / `{extra}` call-site kwargs.
    - `evaluator/` — golden pairs for the metric-extraction and peer-review evaluator prompts.
      - `extract_metrics.md` — byte golden of the extractor/peer-reviewer prompt (`has_real_data`, params-vs-measurements split), trailing newline included.
      - `extract_metrics.rendered.txt` — its rendered form — no placeholders, so only the literal `{{…}}` JSON braces unescape.
      - `peer_review.md` — byte golden of the rubric-driven peer-review prompt keyed on `{axes_block}`.
      - `peer_review.rendered.txt` — the same template rendered with the `{axes_block}` fixture.
    - `governance/` — golden pairs for the Task 05 governance actors: auditor, defender, governance judge.
      - `auditor.md` — byte golden of the impeachment-motion Auditor prompt (the only role allowed to file, never against another auditor).
      - `auditor.rendered.txt` — rendered with `{target_component_id}` / `{target_role}` / `{reliability_block}` / `{evidence_block}`.
      - `defender.md` — byte golden of the governance Defender prompt that rebuts an impeachment motion.
      - `defender.rendered.txt` — rendered with `{motion_block}` / `{evidence_block}` / `{target_outputs_block}`.
      - `governance_judge.md` — byte golden of the GovernanceJudge prompt whose verdict is bounded by the deterministic board scores.
      - `governance_judge.rendered.txt` — rendered with `{motion_block}` / `{defense_block}` / `{board_scores_block}`.
    - `llm/` — golden pair for the MCP tool-name resolution preamble.
      - `mcp_name_resolution.md` — byte golden of the bare→namespaced MCP tool-name translation preamble.
      - `mcp_name_resolution.rendered.txt` — rendered with the `{rows}` name-mapping table fixture.
    - `orchestrator/` — golden pairs for the five BFTS expand/select, lineage-decision and root-idea prompts.
      - `bfts_expand.md` — byte golden of the leaf-expansion prompt with its fifteen context placeholders (parent, siblings, ancestors, diversity, budget).
      - `bfts_expand.rendered.txt` — rendered with all fifteen block fixtures substituted.
      - `bfts_expand_select.md` — byte golden of the combined "pick the completed node to expand next" prompt.
      - `bfts_expand_select.rendered.txt` — rendered with `{experiment_goal}` / `{candidates}`.
      - `bfts_select.md` — byte golden of the next-node selection prompt (goal, memory context, candidates, selection criteria).
      - `bfts_select.rendered.txt` — rendered with `{experiment_goal}` / `{memory_context}` / `{candidates}`.
      - `lineage_decision.md` — byte golden of the continue / switch_to_idea / fanout / terminate lineage-action prompt.
      - `lineage_decision.rendered.txt` — identical to the raw golden — the call site loads this template raw and never `.format`s it (`FIXTURE_KWARGS` is `None`).
      - `root_idea_selector.md` — byte golden of the run-start root-idea picker over the VirSci-scored pool.
      - `root_idea_selector.rendered.txt` — identical to the raw golden — loaded raw at the call site, never formatted.
    - `pipeline/` — golden pair for the keyword-librarian pipeline prompt.
      - `keyword_librarian.md` — byte golden of the 3-6 word Semantic Scholar query prompt, preserved without its trailing newline.
      - `keyword_librarian.rendered.txt` — identical to the raw golden (no placeholders, no escaped braces).
    - `rqgm/` — golden pairs for the ARI-RQGM actor prompts: eight artifact adversaries, artifact defender/judge, the meta components, the three proposal generators, and the paper writer/reviewer.
      - `adversary_cost_explosion.md` — byte golden of the CostExplosionAdversary prompt (the plan cannot execute inside the remaining budget).
      - `adversary_cost_explosion.rendered.txt` — rendered with `{target_block}` / `{evidence_block}`.
      - `adversary_evidence_gap.md` — byte golden of the EvidenceGapAdversary prompt (a supported claim whose required evidence never appears in the checkpoint).
      - `adversary_evidence_gap.rendered.txt` — rendered with `{target_block}` / `{evidence_block}`.
      - `adversary_metric_gaming.md` — byte golden of the MetricGamingAdversary prompt (weakened baseline, cherry-picked config, divergence from `results.json`).
      - `adversary_metric_gaming.rendered.txt` — rendered with `{target_block}` / `{evidence_block}`.
      - `adversary_overclaim.md` — byte golden of the OverclaimAdversary prompt (a claim asserting more than its recorded evidence supports).
      - `adversary_overclaim.rendered.txt` — rendered with `{target_block}` / `{evidence_block}`.
      - `adversary_paper_self_preference.md` — byte golden of the PaperSelfPreferenceAdversary prompt (a draft the reviewer over-accepted that a human-anchor-calibrated reviewer would reject).
      - `adversary_paper_self_preference.rendered.txt` — rendered with `{target_block}` / `{evidence_block}`.
      - `adversary_prior_art.md` — byte golden of the PriorArtAdversary prompt (an undifferentiated novelty claim, judged only against the supplied references).
      - `adversary_prior_art.rendered.txt` — rendered with `{target_block}` / `{evidence_block}`.
      - `adversary_prompt_injection.md` — byte golden of the PromptInjectionAdversary prompt (embedded text instructing a downstream evaluator, reviewer or judge).
      - `adversary_prompt_injection.rendered.txt` — rendered with `{target_block}` / `{evidence_block}`.
      - `adversary_reproducibility.md` — byte golden of the ReproducibilityAdversary prompt (host-local paths, missing seeds, undeclared deps, commands that do not match the claimed procedure).
      - `adversary_reproducibility.rendered.txt` — rendered with `{target_block}` / `{evidence_block}`.
      - `clean_room_generator.md` — byte golden of the CleanRoomPromptGenerator prompt: write a retired role's successor from the closed input bundle alone, never reconstructing the predecessor.
      - `clean_room_generator.rendered.txt` — rendered with `{target_role}` / `{bundle_json}`.
      - `defender.md` — byte golden of the artifact Defender prompt (rebut / concede / propose_fix on one adversary attack, citing only in-checkpoint material).
      - `defender.rendered.txt` — rendered with `{attack_block}` / `{artifact_block}`.
      - `failure_summary_compressor.md` — byte golden of the FailureSummaryCompressor prompt: emit the abstract shape of a failure, never raw attack, defense or prompt text.
      - `failure_summary_compressor.rendered.txt` — rendered with the `{bundle_json}` fixture.
      - `judge_adjudication.md` — byte golden of the ArtifactJudge prompt (verdict + severity on cited evidence; an unanswered attack is not automatically valid).
      - `judge_adjudication.rendered.txt` — rendered with `{attack_block}` / `{defense_block}` / `{evidence_block}`.
      - `paper_reviewer.md` — byte golden of the venue-scoped paper reviewer prompt (strengths / weaknesses / suggestions / `accept_recommendation` JSON).
      - `paper_reviewer.rendered.txt` — rendered with the `{venue_upper}` fixture.
      - `paper_writer.md` — byte golden of the LaTeX repair prompt (fix reflection-identified errors, hallucinate no results or citations, return the whole document).
      - `paper_writer.rendered.txt` — identical to the raw golden (no placeholders, no escaped braces).
      - `policy_mutator.md` — byte golden of the PolicyMutator prompt: one candidate utility policy inside the composite/frontier/axis-weight bounds, blind to the frontier's current scores.
      - `policy_mutator.rendered.txt` — rendered with the mutation kind, incumbent policy, evidence block and the numeric weight/λ/UCB bound fixtures.
      - `prompt_mutator.md` — byte golden of the PromptMutator prompt: one candidate template per role, placeholders unchanged and constitutional constraint lines kept verbatim.
      - `prompt_mutator.rendered.txt` — rendered with `{role}` / `{mutation_kind}` / `{incumbent_instruction}` / `{failure_summaries_block}` / `{required_constraints_block}`.
      - `proposal_cheap.md` — byte golden of the cheap-tier proposal generator prompt with its per-field character budgets and `### N)` plan-step rule.
      - `proposal_cheap.rendered.txt` — rendered with `{goal}` / `{idea_context}`.
      - `proposal_mutation.md` — byte golden of the single-facet mutation prompt (hypothesis | plan_step | success_metric | scope, every other facet unchanged).
      - `proposal_mutation.rendered.txt` — rendered with `{goal}` / `{facet}` / `{parent_summary}`.
      - `proposal_prior_art.md` — byte golden of the prior-art differentiation proposal prompt (one proposal explicitly differentiated from the listed prior work).
      - `proposal_prior_art.rendered.txt` — rendered with `{goal}` / `{prior_art_block}`.
      - `replay_selector.md` — byte golden of the ReplayCaseSelector prompt: non-binding replay recommendations that cannot suppress the constitutionally mandated minimum set.
      - `replay_selector.rendered.txt` — rendered with the `{bundle_json}` fixture.
    - `viz/` — golden pairs for the two launch-wizard prompts.
      - `wizard_chat_goal.md` — byte golden of the goal-elicitation wizard chat prompt (one focused question at a time).
      - `wizard_chat_goal.rendered.txt` — identical to the raw golden (placeholder-free, no escaped braces).
      - `wizard_generate_config.md` — byte golden of the goal→`experiment.md` config-generation prompt.
      - `wizard_generate_config.rendered.txt` — rendered with the `{goal}` fixture.

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
