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
