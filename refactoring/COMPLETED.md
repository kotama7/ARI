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
