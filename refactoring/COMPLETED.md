# Completed Refactoring Requirements

This file records refactoring requirements that have been fully implemented and whose requirement files have been deleted.

A requirement file under `refactoring/requirements/` may be deleted only after completion is recorded here.

## Completed Requirement: 00_repository_architecture_assessment.md

- Status: completed
- Summary: Produced the baseline architecture assessment in
  `refactoring/notes/00_architecture_assessment.md` — entrypoint list (`ari` CLI,
  `ari viz`→`viz/server.py`, `start.sh`/`shutdown.sh`/`setup.sh`, GUI port 8765),
  module-responsibility table for all `ari-core/ari/` subpackages + top-level
  modules, and a first-pass risky-coupling list (routes.py 1344 lines; state.py 19
  mutable globals; ResultsPage.tsx 3177 lines; 2 `core→ari.viz` imports). No
  production code changed.
- PR/Commit: branch `refactoring` (working-tree change; notes-only)
- Checks: section-8 existence check — all 17 section-4 paths present, no gaps.
  No functional tests (no code changed).
- Follow-up: none beyond the coupling items already owned by `02`–`14`; the
  `core(cli)→ari.viz` edge is recorded as a follow-up candidate in the `01` note.
- Requirement file deleted: yes
- Completed at: 2026-05-30

## Completed Requirement: 01_dependency_and_boundary_graph.md

- Status: completed
- Summary: Produced the dependency/boundary graph in
  `refactoring/notes/01_dependency_graph.md` — frontend raw-`fetch` map (7
  components, 17 calls), viz→core import map (incl. reaches into private
  internals), skill→`ari.*` classification (5 skills reach private internals),
  core-purity violations (2 `core(cli)→ari.viz` edges), side-effect origins,
  dynamic edges, and a prioritized coupling list routed to `02`/`05`/`06`/`09`/
  `11`/`12`. No production code changed.
- PR/Commit: branch `refactoring` (working-tree change; notes-only)
- Checks: reproducibility grep commands recorded and re-run cleanly; key counts
  verified directly (routes.py 1344, state.py 19 globals, 2 core→viz edges).
- Follow-up: boundary-enforcement lint (import-linter / eslint no-raw-fetch)
  proposed only; `core(cli)→ari.viz` edge recommended for `09`/`05` to own.
- Requirement file deleted: yes
- Completed at: 2026-05-30

## Completed Requirement: 13_testing_smoke_guards.md

- Status: completed
- Summary: Produced the test/smoke-guard matrix in
  `refactoring/notes/13_test_matrix.md` — how tests run today, recorded baseline,
  per-requirement check matrix (`02`–`14`), coverage gaps, and follow-ups.
- PR/Commit: branch `refactoring` (working-tree change; notes-only, no guard
  tests added this pass — see note §6 for the documented deferral rationale)
- Checks (baseline recorded 2026-05-30, login node): `pytest ari-core/tests` =
  2210 passed / 16 skipped / 0 failed; `npm run build` passes; `npm run typecheck`
  pre-existing test-file-only failures (missing jest-dom types); `npm test --run`
  4 passed / 2 failed (pre-existing brittle DOM queries); `run_all_tests.sh` 329
  passed / 19 failed / 8 skipped — all failures are missing optional deps
  (PIL/numpy/paramiko/chz/semanticscholar/structlog) or per-skill import isolation
  on the login node, no product-code regression. Environment-gated checks
  (start.sh/shutdown.sh/ari viz, remote SLURM, live Letta, GPU) documented, not
  silently skipped.
- Follow-up: WebSocket-shape, checkpoint-parse, and LLM-error/fallback guards
  deferred to `06`/`07`/`11` (pin behavior immediately before each refactor);
  jest-dom type fix + brittle-test rewrite + boundary lint + CI wiring listed.
- Requirement file deleted: yes
- Completed at: 2026-05-30

## Completed Requirement: 02_frontend_api_client_consolidation.md

- Status: completed
- Summary: Moved 14 of 16 component-level raw `fetch` calls into the existing
  `services/api.ts`. Added lenient PaperBench helpers (`fetchPaperbenchPapers`,
  `deletePaperbenchPaper`, `estimatePaperbenchCost`, `runPaperbench`,
  `fetchArxivMetadata`, `importPaperbenchPaper`, `fetchPaperbenchRun`,
  `fetchPaperbenchRunResults`, `requestPaperbenchReport`) that mirror the
  components' `fetch().then(r=>r.json())` behavior exactly (these endpoints
  return 200+{error}, and several call sites have no try/catch, so the helpers
  deliberately do NOT throw). Added `fetchCheckpointFiletree`; extended
  `fetchCheckpointFilecontent` with an optional `nodeId`. Updated FileExplorer
  (filetree, filecontent), PaperRegistryPage (papers, delete), PaperBenchWizard
  (papers, cost-estimate, run), PaperImportDialog (arxiv, import), ResultsView
  (run×2, results, report), ResultsPage FileViewer (filecontent). All existing
  `services/api.ts` exports preserved (additive only).
- PR/Commit: branch `refactoring` (per-requirement local commit)
- Checks: `npm run typecheck` — identical to baseline (only the pre-existing
  `__tests__` jest-dom errors; zero new errors from production changes);
  `npm run build` — passes (2.8s); `npm test -- --run` — 4 passed / 2 failed,
  the 2 failures byte-identical to the pre-existing brittle `getByDisplayValue`
  queries (the PaperBenchWizard test mocks `global.fetch`, which the new helpers
  still call internally; it fails at `getByDisplayValue('0')` before reaching the
  launch-POST assertion, so the launch flow is exercised unchanged). No regressions.
- Risks/known nuances documented: (1) two genuine direct-`fetch` exceptions
  left with code comments — MonitorPage `/api/logs` (SSE stream via
  `res.body.getReader()`) and PaperImportDialog `/api/upload` (multipart
  FormData, distinct from `uploadFile`'s octet-stream contract). (2) Two sites
  previously checked `res.ok` and showed `HTTP ${status}` (PaperRegistryPage
  papers, ResultsPage FileViewer); via the helpers the common 200 path is
  byte-identical, and only the error *text* on a rare hard-HTTP-status failure
  changes (no component reads a non-2xx body for data). URLs preserved verbatim
  (encoded params only where the originals encoded them).
- Follow-up: stronger typing for `any`-typed PaperBench payloads → routed to
  `06` (viz api schema contract); upload/streaming helper standardization is the
  req-02 §12 follow-up candidate (no new file needed).
- Requirement file deleted: yes
- Completed at: 2026-05-30

## Completed Requirement: 03_frontend_large_component_decomposition.md

- Status: completed (ResultsPage.tsx; remaining 5 components + finer splits moved
  to follow-up req 15, per 03 §11/§12 which permit incremental multi-PR splits)
- Summary: Decomposed `components/Results/ResultsPage.tsx` (3177 lines) into the
  container (`ResultsPage.tsx`, ~1857) plus two sibling files: `resultSections.tsx`
  (~1161 — all module-scope presentational subcomponents + pure helpers + types
  that lived below the container) and `PublishYamlEditor.tsx` (~162). Code moved
  VERBATIM via exact slices; only `export` keywords and minimal import headers
  added. The container body, the PublishYamlEditor block, and the sections block
  are each byte-identical to the original modulo export/import lines.
- PR/Commit: branch `refactoring` (per-requirement local commit)
- Checks: `npm run typecheck` 0 non-test errors (only the 11 pre-existing
  `__tests__` jest-dom errors); `npm run build` ✓ (~2.9s); `npm test -- --run`
  4 passed / 2 failed (pre-existing brittle PaperBench `getByDisplayValue`
  tests). Independently verified byte-for-byte verbatim of all three moved
  regions. Adversarial 2-lens review workflow returned behaviorPreserved=true
  (component identity stable — moved components stay module-scope, imported by
  reference, not recreated per render; no logic/JSX/default/ordering change).
- Risks/notes: pre-existing nits left untouched (a local `type RubricNode`
  structurally mirrors the one in RubricTreeVisualization; `fetchCheckpointFileContent`
  vs `fetchCheckpointFilecontent` are distinct and both used). The known
  `activeAbsPath` mid-body state-ordering smell is preserved verbatim (not "fixed").
  Analysis + safe seams recorded in `refactoring/notes/03_resultspage_decomposition.md`.
- Follow-up: moved to NEW req `15_frontend_remaining_large_components.md`
  (Workflow/StepResources/Settings/DetailPanel/Monitor pages; finer split of
  `resultSections.tsx`; low/medium-risk container seams + `useCheckpointResults`/
  `useEAR` hooks — coordinate the hooks with `04`).
- Requirement file deleted: yes
- Completed at: 2026-05-30

## Completed Requirement: 04_frontend_state_hooks_types_cleanup.md

- Status: completed
- Summary: A 3-agent audit found (a) `AppContext.tsx` already well-scoped (no
  over-broad mixed global state — left unchanged to avoid unrequested churn);
  (b) the `useApi` hook existed with ZERO consumers (dead code); (c)
  `types/index.ts` has zero `any` (already uses `unknown`). Made two minimal,
  behavior-preserving changes: adopted `useApi` in `PaperRegistryPage.tsx` (the
  single clean semantic twin per the audit — `refresh` aliased to `refetch`,
  `papers` kept `PaperEntry[]`); and extracted `ReviewReport.decision`'s inline
  union into a documentary `export type ReviewDecision = ... | string` (trailing
  `| string` kept, so the resolved type stays exactly `string` and all consumers
  compile unchanged). Details + audit in
  `refactoring/notes/04_state_hooks_types_cleanup.md`.
- PR/Commit: branch `refactoring` (per-requirement local commit)
- Checks: `npm run typecheck` 11 total / 0 non-test (pre-existing `__tests__`
  jest-dom errors only); `npm run build` exit 0; `npm test -- --run` 4 passed /
  2 failed (pre-existing brittle PaperBench tests), 0 resolve errors. Adversarial
  verification confirmed behavior preserved (PaperRegistryPage lens
  behaviorPreserved=true; types alias confirmed to resolve to `string`).
- Risks/notes: `ExperimentsPage.tsx` was NOT migrated — the audit flagged it
  `safeToAdoptSharedHook:false` (it builds a `subById` Record keyed by run_id and
  deliberately swallows fetch errors with no loading/error UI), so adopting
  `useApi` there would change observable behavior. Left unchanged. A transient
  harness output-capture outage mid-session also briefly corrupted
  `PaperBenchWizard.tsx` with stray imports; detected via vitest and restored to
  HEAD (it has no req-04 changes), re-verified green. Other deferred (would change
  behavior): `MonitorPage` (interval polling vs mount-only useApi), `SettingsPage`
  (multi-source load + save/dirty), `ResultsView` (poll loop), and extracting
  AppContext's inline poll to a `usePolling` hook — all routed to req 15 / a
  future `useApi` polling option.
- Follow-up: MonitorPage/SettingsPage/ResultsView useApi adoption + AppContext
  poll extraction → req 15 / a future useApi polling option.
- Requirement file deleted: yes
- Completed at: 2026-05-30

---

## Completed Requirement: 05_viz_routes_service_extraction.md

- Status: completed (first, lowest-risk slice of routes.py thinning; remaining
  fat handlers + helpers moved to a follow-up — see Follow-up)
- Summary: Extracted the experiment process-control concern out of the
  routes.py dispatch handlers into a new sibling service module
  ari/viz/api_process.py (consistent with the existing api_*.py layout):
  _api_gpu_monitor_status() (GET /api/gpu-monitor), _api_gpu_monitor_action()
  (POST /api/gpu-monitor start/stop), and _api_stop() (POST /api/stop). Logic
  moved verbatim (signal escalation, poll/sleep timing, report shape, response
  keys preserved). The three route branches are now thin: parse -> call service
  -> self._json (GET gpu-monitor keeps its manual no-CORS response to preserve
  exact wire bytes). routes.py dropped ~154 lines; the now-dead os/subprocess
  module imports it left were removed (pre-existing unused asyncio/argparse
  imports left untouched -- not in scope).
- PR/Commit: branch refactoring (per-requirement local commit)
- Checks: full pytest ari-core/tests = 2218 passed / 16 skipped / 0 failed
  (2210 baseline + 8 new). python -m ari.viz.server --help works (the real
  entrypoint, confirmed). Added tests/test_api_process.py (8 real
  characterization tests) since the pre-existing /api/stop and gpu-monitor tests
  re-implement the logic inline and never call the handler. _Handler and
  _write_access_log re-exports from server.py preserved; dispatch order
  untouched; 10MB/413 do_POST guard (asserted via inspect.getsource) untouched.
- Risks/notes: dispatch order is load-bearing (first-match-wins prefix/suffix
  matches + GET static fall-through) and was NOT reordered. The catalog of all
  96 routes + dispatch hazards + the deferred-handler plan is in
  refactoring/notes/05_routes_catalog.md.
- Follow-up: the larger fat handlers remain for a future pass -- the /state
  aggregate builder (~447 lines; has a no-ensure_ascii + no-CORS serialization
  quirk, must not switch to _json), /api/container/pull, the static-serving +
  access-log helpers, and the SSE scaffolding. Recorded in
  refactoring/notes/05_routes_catalog.md; route to a new follow-up requirement
  when picked up. Reducing ari.viz.state globals stays with 07.
- Requirement file deleted: yes
- Completed at: 2026-05-30

---

## Completed Requirement: 06_viz_api_schema_contract.md

- Status: completed (stable-endpoint contracts reconciled; the broad Settings
  reconcile + generated-types/OpenAPI deferred — see Follow-up)
- Summary: Reconciled frontend TS types in
  ari-core/ari/viz/frontend/src/types/index.ts against the backend's ACTUAL
  output for the four highest-traffic stable endpoints (captured by a 3-agent
  mapping of the real producers, not assumed shapes). All changes additive or
  corrective: Checkpoint += optional best_metric?/best_scientific_score?; new
  CostSummary type; AppState.cost corrected number -> CostSummary? (backend emits
  the parsed cost_summary.json object, already read via `as any`); AppState +=
  verified always/conditional optional fields (exit_code?, running?, pid?,
  llm_model?, phase_flags?, etc.); new ReproReport = string | Record<string,
  unknown>; CheckpointSummary += id?/path?/ors_*/vlm_review?, reproducibility_report
  corrected string|null -> ReproReport|null? (backend emits a dict; legacy=string),
  repro made optional. Documented the contract in docs/reference/rest_api.md
  (added checkpoint_api.py + api_settings.py sources, bumped last_verified to
  2026-05-30, added a Typed-contracts table) and added a machine-checkable guard
  test.
- PR/Commit: branch refactoring (per-requirement local commit)
- Checks: pytest ari-core/tests = 2223 passed / 16 skipped / 0 failed (2218 prior
  + 5 new contract guards in tests/test_api_schema_contract.py); npm run typecheck
  0 non-test errors; npm run build ok; npm test --run 4 passed / 2 failed
  (pre-existing brittle PaperBench getByDisplayValue tests). Adversarial 2-lens
  verification: behaviorPreserved=true AND contractCorrect=true (all findings nit;
  cost/repro corrections confirmed safe + matching real backend output).
- Risks/notes: no wire/path/method change — only frontend types + docs + a test.
  The two type CORRECTIONS (cost, reproducibility_report) target fields already
  consumed via `as any` / an any-typed render param, so they cannot break a call
  site. Did NOT flip existing required AppState/CheckpointSummary fields to
  optional despite conditional presence (read without null-guards across
  components -> strict-null risk); pinned the contract via the guard test instead.
- Follow-up: the broad Settings type <-> /api/settings divergence is only
  partially reconciled (frontend Settings carries ssh_*/model_*/slurm_partitions/
  language not in backend defaults; backend emits slurm_gpus/mcp_skills/nested
  ors/letta_deployment* not in the type) — deferred (wide consumer surface,
  tightening risk). A future generated-types/OpenAPI move (req-06 §12) remains a
  separate task. Both recorded in refactoring/notes/06_api_schema_contract.md.
- Requirement file deleted: yes
- Completed at: 2026-05-30

---

## Completed Requirement: 07_checkpoint_run_artifact_model.md

- Status: completed (documentation + ONE justified low-risk fix; broader helpers
  deferred per §5/§11 — see Follow-up)
- Summary: Assessment-first requirement. A 3-agent mapping of every
  filesystem-touching module vs the canonical PathManager produced: (1) a
  concept glossary (project/run/checkpoint/node/work_dir/artifact/log/file/
  result) mapped to the on-disk layout, folded additively into
  docs/reference/glossary.md (new terms workspace/run/node work_dir/artifact +
  expanded checkpoint; last_verified -> 2026-05-30; +paths.py/checkpoint.py
  sources); (2) refactoring/notes/07_checkpoint_model.md — the full model, the
  per-module path-assumption catalog, and the divergence analysis. The mapping
  found one REAL bug (divergence #1): checkpoint_api._api_checkpoints and
  _api_checkpoint_summary resolved the node tree with inline tree.json/
  nodes_tree.json probes that OMITTED the legacy node_*/tree.json fallback
  honored by the canonical ari.checkpoint.load_nodes_tree (and the live
  WebSocket path), so legacy checkpoints showed node_count=0 in the list/summary
  cards. Fixed by adding the canonical loader as a fallback (via a
  monkeypatch-friendly checkpoint_api._load_nodes_tree wrapper) — kept each
  inline flat-file probe verbatim and consult the loader ONLY when neither flat
  file exists, so the change is purely additive/symmetric and all corrupt-file
  corner cases stay byte-identical. No new model, no on-disk format change.
- PR/Commit: branch refactoring (per-requirement local commit)
- Checks: pytest ari-core/tests = 2226 passed / 16 skipped / 0 failed (2223 prior
  + 3 new legacy-tree guards in tests/test_checkpoint_legacy_tree.py).
  Adversarial 2-lens verification: behaviorPreserved=true AND
  legacyFixedCorrectly=true (the symmetric rewrite closed the two corrupt-file
  nits a wholesale replacement would have introduced). Real-environment
  dashboard smoke is compute-node-gated; the legacy-tree guard stands in on the
  login node.
- Risks/notes: existing + legacy checkpoints load unchanged; legacy
  reconstruction (migrations/v05_to_v07) untouched. The active-checkpoint global
  (ari.viz.state) was documented but NOT refactored (§11 high-risk).
- Follow-up: deferred (each touches a legacy variant or destructive path the
  duplicated code still handles): a checkpoint-discovery facade over
  checkpoint_finder's 7 search bases; a paper/ artifact-path helper; de-duping
  the run_id/slug regex + experiments-bucket scans (delete path); reducing the
  ari.viz.state active-checkpoint coupling (dedicated requirement); additive
  TreeNode doc-comments; a dedicated checkpoint migration if the format changes.
  Recorded in refactoring/notes/07_checkpoint_model.md §7.
- Requirement file deleted: yes
- Completed at: 2026-05-30

---

## Completed Requirement: 08_config_settings_workflow_unification.md

- Status: completed (documentation + ONE trivial behavior-neutral extraction;
  central loader + broader dedup deferred per §5/§11 — see Follow-up)
- Summary: Assessment-first. A 3-agent mapping of every config source produced:
  (1) docs/reference/configuration.md gains a "Configuration Precedence
  (observed)" section — the TWO precedence chains (runtime/core-CLI: ARI_* env >
  YAML > pydantic default, via load_config/_apply_*_env_overrides; vs GUI
  settings: saved settings.json > env > workflow.yaml > default, via
  _api_get_settings), the env-var hand-off bridge (GUI /api/launch writes ARI_*
  env + launch_config.json; CLI resolves via env, not by re-parsing
  launch_config.json), a per-setting table (llm_model runtime/display/settings,
  provider, language, port=8765, SLURM partition, checkpoint dir), and
  falsy-vs-missing handling; last_verified -> 2026-05-30. (2)
  refactoring/notes/08_config_precedence.md — source inventory, the three
  config-model layers (ari.config typed + finder; ari.configs lookup tables;
  ari.public.config_schema re-export), the duplication catalog with per-item
  verdicts, and the central-loader proposal. The ONE trivial+behavior-neutral
  extraction: the two near-identical .env-write blocks in api_settings.py ->
  a shared _upsert_env_key(name, value, *, quote) helper; the quote flag
  PRESERVES each caller's exact output (KEY="v" via _api_save_env_key vs KEY=v
  via _api_save_settings) — unifying would be a behavior change, so the
  difference is kept.
- PR/Commit: branch refactoring (per-requirement local commit)
- Checks: pytest ari-core/tests = 2229 passed / 16 skipped / 0 failed (2226 prior
  + 3 new .env-write quoting guards in tests/test_env_write_quoting.py, added
  BEFORE the extraction per §8). Adversarial verification: behaviorPreserved=true
  — confirmed the helper is byte-identical to both originals (6-step match, live
  env var set to the raw unquoted value in both paths, gate ordering preserved),
  and the 3 guards provably FAIL under a flipped-quote mutation (not vacuous).
- Risks/notes: no behavior/precedence change; .env/settings.json/start.sh/
  setup_env.sh semantics unchanged. Precedence documented as observed, locked by
  the existing config suite (test_config/default_provider/launch_config/
  settings_*) before the extraction.
- Follow-up: deferred (each needs guard tests first or is behavior-affecting):
  central ari.config resolver subsuming the workflow.yaml fallback +
  launch_config.json chain (8 sites, brittle source-string tests) + profile
  resolution; migrate viz workflow.yaml discovery to finder helpers; reduce
  config-related ari.viz.state fields (overlaps req-07 follow-up); re-derive
  ARI_PAPER_LANGUAGE from launch_config.json on the CLI path (a behavior fix).
  Recorded in refactoring/notes/08_config_precedence.md §7.
- Requirement file deleted: yes
- Completed at: 2026-05-30

---

## Completed Requirement: 09_core_skill_public_contract.md

- Status: completed (clean public-contract migrations + new re-export + guard
  test; 4 deeper edges explicitly deferred — see Follow-up)
- Summary: A 3-agent classification of every ari-skill-*/src import of ari.*
  (builds on req-01). Migrated all behavior-neutral private edges to the stable
  contract, keeping internal paths working (compatibility shims, §7):
  (1) 9 skills' `from ari import cost_tracker` -> the dual pattern
  `try: from ari.public import cost_tracker except ImportError: from ari import
  cost_tracker` (the form ari-skill-plot already shipped) — same module object,
  zero behavior change; (2) ari-skill-coding's `ari.container` (prod + test) ->
  `ari.public.container`; (3) NEW thin re-export `ari.public.run_env` for
  `capture_env`/`shell_capture_snippet`, migrating ari-skill-coding + ari-skill-hpc
  public-first. Added a guard test (ari-core/tests/test_skill_public_contract.py)
  that fails when a skill's production src imports a private ari.* path (allowing
  ari.public/protocols/mcp, an `except ImportError` fallback, and a documented
  deferred allowlist) plus a second test that fails if an allowlist entry rots.
- PR/Commit: branch refactoring (per-requirement local commit)
- Checks: bash scripts/run_all_tests.sh = 2843 passed / 0 failed / 26 skipped
  across all 13 suites (ari-core 2231 incl. 2 new guards; coding 24 incl. the
  repointed container test; every migrated skill green). Re-run after fixing a
  mid-edit indentation corruption in replicate/src/server.py (caught by syntax
  check + re-run, not shipped).
- Risks/notes: handled a real nuance — ari.public.container's `import *` BINDS
  run_shell_in_container at import time, so coding's test (which monkeypatched
  ari.container) would have silently taken the host fallback after the prod
  import moved; fixed by patching BOTH modules (verified empirically). No skill
  behavior, import path, or mcp.json changed; internal paths still resolve.
- Follow-up: deferred edges, each needing interface design or signature-stability
  confirmation before a public re-export (tracked by the guard allowlist):
  ari.publish (transform + paper-re), ari.clone (paper-re), ari.lineage (idea,
  virsci-specific), ari.orchestrator.node_selection (transform — wants a protocol,
  deepest break). Recorded in refactoring/notes/09_skill_public_contract.md.
- Requirement file deleted: yes
- Completed at: 2026-05-30

---

## Completed Requirement: 10_pipeline_workflow_phase_boundary.md

- Status: completed (documentation-only per §5; all seam proposals deferred to
  dedicated implementation requirements)
- Summary: A 3-agent map of the orchestration layer produced
  refactoring/notes/10_phase_boundary.md documenting: (1) the phase model — ARI
  runs TWO engines, not one linear pipeline: the BFTS loop (cli/bfts_loop.py:
  _run_loop, hardcoded; bfts_pipeline[] read only for enabled/disabled flags)
  and the post-BFTS linear stage loop (pipeline/orchestrator.py:run_pipeline,
  driving transform/figures/paper/review + ORS reproduction + publish as
  consecutive pipeline[] stages), bridged by core.py:generate_paper_section;
  (2) the single-stage state machine (depends_on / skip_if_exists / input
  resolution / react-vs-subprocess dispatch / output save / loop_back / failure);
  (3) the concrete side-effect seam candidates (the one direct litellm.completion
  in context_builder bypassing LLMClient; the subprocess-fork MCP boundary in
  stage_runner; direct filesystem I/O + env mutation in run_pipeline); (4) the
  BFTS/ReAct plug points (core.build_runtime construction, the _run_loop
  delegators, the four BFTS-method engine boundary); (5) the §11 concurrency
  hazards any seam must preserve (env-at-fork timing, the shared-process
  ARI_CURRENT_NODE_ID CoW race + cow_node_id serialization, shared tree.json
  committers — there is NO git worktree); (6) how viz/api_workflow.py drives the
  DAG; (7) four ranked PROPOSE-ONLY seams (FlowMapping; canonical Stage schema;
  StageRunner protocol; route context_builder through LLMClient).
- PR/Commit: branch refactoring (per-requirement local commit; notes-only)
- Checks: NO production code changed (only the note added). pytest ari-core/tests
  = 2231 passed / 16 skipped / 0 failed (unchanged from req 09); run_all_tests.sh
  green at 2843 (req-09 run, nothing changed since). Environment-sensitive phase
  transitions (real BFTS run, SLURM ORS) are compute-node-gated — documented,
  not skipped.
- Risks/notes: documented the concurrent-committer / env-at-fork / shared-tree
  hazards as hard constraints on any future seam. No workflow.yaml semantics or
  phase ordering changed.
- Follow-up: the four seam proposals are each a dedicated implementation
  requirement (FlowMapping overlaps the req-08 finder migration; Stage schema
  fixes the editor↔runtime field-loss bug class; StageRunner protocol +
  LLMClient-for-context_builder must preserve the concurrency hazards);
  WorkflowPage.tsx decomposition coordinates with req-03/15. Recorded in
  refactoring/notes/10_phase_boundary.md §9.
- Requirement file deleted: yes
- Completed at: 2026-05-30

---

## Completed Requirement: 11_llm_backend_boundary.md

- Status: completed (audit/documentation-only; the boundary is already sound and
  already guard-tested — no code change, and a new guard would be wrong, see below)
- Summary: A repo-wide audit of LLM/provider usage (refactoring/notes/
  11_llm_backend_boundary.md) found the boundary is NOT "everything routes
  through ari.public.llm.LLMClient" — it is a three-part pattern where direct
  litellm.{completion,acompletion} calls are the SANCTIONED shape: (1) litellm is
  the provider-abstraction layer; (2) ari.llm.routing.resolve_litellm_model
  normalises model ids (incl. the CLI-shim prefix); (3) cost_tracker's
  _install_litellm_metadata_injector monkey-patches litellm process-wide to apply
  routing + cost metadata at ONE point, installed via bootstrap_skill at every
  skill import. LLMClient is a convenience wrapper (ReAct path), not a mandatory
  chokepoint. Classified all usage: LLMClient + cli_server + api_ollama = infra;
  evaluator/lineage_decision/root_idea_selector/context_builder/api_tools +
  ~7 skills = acceptable litellm-direct (routed via the injector / own api_base);
  paper-re vendored PaperBench bridge = intentional, untouched. No call
  circumvents routing.
- PR/Commit: branch refactoring (per-requirement local commit; notes-only)
- Checks: NO production code changed (only the note). The boundary contract is
  ALREADY comprehensively guard-tested by tests/test_llm_routing.py
  (resolve_litellm_model rules + _apply_ari_routing cli-shim/openai/anthropic +
  injector) — re-ran test_llm_routing.py + test_llm.py = 29 passed. LLM behavior
  is env-sensitive (real backends/credentials/GPU) — representative live calls
  are compute-node-gated, documented not skipped.
- Risks/notes: documented the one real fragility — the injector must be installed
  before the first litellm call for cost capture (skills guarantee via
  bootstrap_skill; core CLI/pipeline pass api_base themselves so routing is
  unaffected). No model/routing/prompt/provider behavior changed; cli shim +
  ollama proxy untouched.
- Follow-up: DELIBERATELY did NOT add the §12-suggested "domain modules import
  only ari.public.llm" guard — it would flag the entire sanctioned litellm-direct
  pattern and pressure an out-of-scope LLMClient rewrite. PROPOSE-ONLY follow-up:
  route context_builder's one direct litellm call through resolve_litellm_model/
  LLMClient (behavior-neutral only if resolution proven identical first). The
  broad "everything via LLMClient" rewrite is explicitly out of scope. Recorded
  in refactoring/notes/11_llm_backend_boundary.md §6.
- Requirement file deleted: yes
- Completed at: 2026-05-30

---

## Completed Requirement: 12_hpc_container_subprocess_boundary.md

- Status: completed (audit/documentation-only; all execution-backend seams
  deferred per §5/§11 — no code change)
- Summary: A 3-agent audit (core/viz/skills+scripts) of every subprocess / SLURM
  / container / SSH side effect -> refactoring/notes/12_exec_boundary.md. Found
  the sanctioned boundary is sound: ari/container.py (the dedicated exec module
  with _sandbox_preexec setsid + group teardown; re-exported as
  ari.public.container), env_detect.py (read-only scheduler/runtime probes),
  mcp/client.py (MCP SDK stdio spawn), and ari-skill-hpc SlurmClient (canonical
  SLURM). Problematic sites identified (duplication, not bad execution):
  viz/api_memory start/stop-local re-deriving container runtime dispatch;
  ari-skill-paper-re re-implementing sbatch + apptainer-exec that SlurmClient /
  ari.public.container already own (with a real --export ALL vs clean-env
  divergence + a missing setsid/killpg on the local fallback);
  ari-skill-orchestrator detached child not process-group-reaped; gh.py
  clone/publish git shell-outs. Documented the ari.viz.state global
  process-handle coupling (_last_proc/_running_procs/_gpu_monitor_proc; gpu-monitor
  now in api_process.py per req-05) and 4 ranked PROPOSE-ONLY seams (probe runner;
  api_memory -> container facet; paper-re -> SlurmClient; managed-process Runner
  owning the handle registry) with the cwd/env/signal/orphan/start.sh-shutdown
  hazards each must preserve.
- PR/Commit: branch refactoring (per-requirement local commit; notes-only)
- Checks: NO production code changed (only the note). pytest ari-core/tests =
  2231 passed / 0 failed; run_all_tests.sh = 2843 passed / 0 failed (unchanged);
  re-ran test_container + test_run_env = 56 passed. ENVIRONMENT CAVEAT (§8/§11):
  the real validation (start.sh / start.sh gui / status / shutdown.sh + an actual
  container/SLURM op) is compute-node-gated and was NOT run on this login node —
  per §8 that is fine for a no-code-change documentation deliverable, but any
  future seam implementation MUST be verified on a real compute node before merge.
- Risks/notes: did not touch scripts/, containers/, HPC behavior, or the
  ari.viz.state handle store (§3 out of scope; §11 high-risk). Documented the
  orphan/status/shutdown nexus as a hard constraint.
- Follow-up: the 4 seams as dedicated requirements (api_memory->container facet =
  smallest win; paper-re->SlurmClient fixes the --export divergence; managed-proc
  Runner = the §12 headline, real-node verify mandatory, coordinates with the
  req-07 active-checkpoint-global follow-up). Recorded in
  refactoring/notes/12_exec_boundary.md §6.
- Requirement file deleted: yes
- Completed at: 2026-05-30

---

## Completed Requirement: 14_migration_and_requirement_deletion.md

- Status: completed (the meta-finalizer; governs all other requirements' lifecycle)
- Summary: Settled and recorded the migration/deletion policy in the DURABLE doc
  refactoring/GLOBAL_RULES.md (req-14 deletes itself, so the binding policy must
  live where it survives). Added three sections: (1) compatibility-wrapper
  removal policy (wrappers stay until all call sites migrate; removal needs its
  own requirement; never removed in the introducing PR — lists this sequence's
  live wrappers: ari.public.* re-exports, the skills' public-first cost_tracker
  fallback, the checkpoint_api->load_nodes_tree fallback); (2) package-move gate
  (ari.viz -> top-level ari-gui/ari-api forbidden in early refactoring; only via
  a dedicated migration requirement after 00/01 + the in-place refactors, with a
  wrapper plan — no move was performed; everything refactored in place); (3)
  sequence-completion + final-cleanup policy (remove refactoring/ only once
  requirements/ is empty, after folding durable notes/ into docs/). Confirmed
  consistency: README.md execution order matches the canonical 14-item list and
  the order executed; every prior requirement followed record-in-COMPLETED +
  same-PR-delete (all 14 carry "Requirement file deleted: yes"). Wrote
  refactoring/notes/14_migration_policy.md with the consistency check, the state
  of the sequence, and a consolidated deferred-work ledger across reqs 03-12.
- PR/Commit: branch refactoring (per-requirement local commit; policy/docs only)
- Checks: no production code changed. Full suites green from req 09-12
  (pytest ari-core/tests 2231 passed; run_all_tests.sh 2843 passed).
- Risks/notes: enforced the "same-PR record + delete" and wrapper/package gates
  in the durable doc so they outlive the deleted requirement files.
- Follow-up: ONE requirement remains in requirements/ — 15_frontend_remaining_
  large_components.md (a req-03 follow-up; was not in the original README order).
  The refactoring/ directory's final cleanup is therefore NOT yet due; it happens
  after 15 (and anything it spawns) completes. The full deferred-work backlog
  (reqs 03-12 follow-ups) is catalogued in refactoring/notes/14_migration_policy.md.
- Requirement file deleted: yes
- Completed at: 2026-05-30

---

## Progress: 15_frontend_remaining_large_components.md (PARTIAL — file retained)

req-15 is a multi-PR follow-up (one component per PR, §9). This entry records an
incremental slice; the requirement file STAYS until all listed components are
done (or the remainder is moved to a further follow-up).

- 2026-05-30 — **MonitorPage.tsx** decomposed (859 -> 505 lines). Extracted the
  module-scope presentational/helper layer (the `MetricDisplay` type,
  `computeBestMetrics` pure helper, and the `IdeaCardContent` Experiment-
  Configuration card) VERBATIM into a sibling `components/Monitor/monitorSections.tsx`;
  the container imports `computeBestMetrics` + `IdeaCardContent` from it. Moved
  code byte-identical (modulo `export` keywords); removed the now-dead
  ReactNode/AppState/TreeNode/fetchExperimentDetail imports from the container.
  Checks: typecheck 0 non-test errors; build ok; vitest 4 passed / 2 failed
  (pre-existing brittle PaperBench tests). PR/commit on branch refactoring.
- 2026-05-30 — **WorkflowPage.tsx** decomposed (1720 -> 968 lines). Extracted the
  React Flow node/modal layer (skillColor + SKILL_PALETTE, PhaseNode/ConditionNode/
  ParallelNode + the nodeTypes map, ConditionModal/SkillDrawer/NodeEditModal/
  SkillModal, the SkillMcpEntry type, inputStyle) VERBATIM into
  components/Workflow/workflowNodes.tsx; the container imports skillColor/nodeTypes/
  the four modals + SkillMcpEntry. Moved code byte-identical (modulo export kw);
  removed the now-dead reactflow Handle/Position/NodeTypes container imports.
  Checks: typecheck 0 non-test errors; build ok; vitest 4 passed / 2 failed
  (pre-existing brittle PaperBench tests). PR/commit on branch refactoring.
- 2026-05-30 — **StepResources.tsx** decomposed (1558 -> 1161 lines). Extracted
  the ORS provider model tables + inferOrsProvider helper (used only by the
  pickers) and the OrsModelPicker + FewshotManager subcomponents VERBATIM into
  components/Wizard/stepResourcesSections.tsx; container imports the two comps.
  Moved code byte-identical (modulo export kw); fixed the new file's
  useCallback import and dropped the now-dead React default import from the
  container. Checks: typecheck 0 non-test errors; build ok; vitest 4 passed /
  2 failed (pre-existing brittle PaperBench tests). PR/commit on branch refactoring.
- 2026-05-30 — **SettingsPage.tsx** decomposed (1123 -> 1053 lines). It is a
  heavy 38-useState form container, so NO state-bearing UI was extracted; instead
  the self-contained constants/types/helper block (DEFAULT_PROVIDER, PROVIDER_MODELS,
  PROVIDER_KEY_PLACEHOLDER, the Letta embedding tables + LettaModelEntry/
  LettaProviderTable types, CUSTOM_HANDLE_VALUE, and the pure _splitHandle helper)
  moved VERBATIM into components/Settings/settingsConstants.ts (pure data/logic,
  no JSX). Container imports them. Byte-identical (modulo export kw). Checks:
  typecheck 0 non-test errors; build ok; vitest 4 passed / 2 failed (pre-existing).
  PR/commit on branch refactoring.
- 2026-06-01 — **DetailPanel.tsx** decomposed (938 -> 794 lines). The monolith
  has NO module-scope presentational units, so extraction targeted the two
  behavior-isolatable seams: (1) the pure parent_id ancestor-chain walk moved to
  `components/Tree/detailPanelHelpers.ts` as `computeAncestorIds` (the useMemo
  now calls it); (2) the three fetch-effect clusters (checkpoint memory, lazy
  access-log, lazy node-report + availability probe) plus the ancestor-scoped
  `visibleMemory` derivation moved into a `components/Tree/useDetailPanelData.ts`
  hook. The hook is invoked at the EXACT position in the container's hook
  sequence the inline code occupied (after reset-tab effect, before onMouseDown/
  resize), so React effect run-order and the §11 fetch/abort timing are byte-for-
  byte unchanged; effect bodies + dep arrays moved verbatim. Two PRs/commits on
  branch refactoring. Checks: typecheck 0 non-test errors; build ok; vitest
  4 passed / 2 failed (pre-existing PaperBench).
- 2026-06-01 — **DetailPanel.tsx** per-tab decomposition completed (794 -> 425
  lines; 938 -> 425 over the full req-15 chain). The 5 substantial tab render
  blocks moved VERBATIM into `components/Tree/DetailPanelTabs/{Trace,Code,Memory,
  Access,Report}Tab.tsx` with explicit prop contracts; `t` sourced via `useI18n()`
  inside each (behavior-identical to the container's i18n closure), `node.id`
  passed as `currentNodeId`. The `activeTab === '...'` visibility guards stay in
  the container; overview (empty) and raw (trivial) left inline. Behavior-
  equivalence ADVERSARIALLY VERIFIED: a 6-agent workflow (one skeptic per tab +
  one for container wiring), each tasked to refute equivalence against the
  pre-extraction git HEAD — all returned equivalent=true, zero discrepancies.
  Checks: typecheck 0 non-test errors; build ok; vitest 4 passed / 2 failed
  (pre-existing PaperBench). DetailPanel is now a thin container (chrome + derived
  render data + tab dispatch). All 5 components listed in req-15 §2 are DONE.
- Optional remainder (req-15 §3, NOT done — deferred follow-up): finer split of
  resultSections.tsx + the low/med-risk ResultsPage container seams
  (per refactoring/notes/03_resultspage_decomposition.md). These were optional in
  the requirement, not part of the §2 listed components.

---

## Template

Copy this block when recording a completed requirement.

```markdown
## Completed Requirement: <file name>

- Status: completed
- Summary:
- PR/Commit:
- Checks:
- Follow-up:
- Requirement file deleted: yes
- Completed at:
```
