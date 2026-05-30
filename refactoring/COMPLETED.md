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
