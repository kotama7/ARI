# Subtask 065: Add Dashboard Contract And Schema Tests

- **Subtask ID:** 065
- **Phase:** Phase 5 — Dashboard Frontend
- **Classification:** `KEEP` (test-only subtask — it *pins and documents* the existing dashboard wire contract; it does not restructure any endpoint, handler, client, or type)
- **Changes runtime code:** **No** (see Section 16). Only test files, and — at most — the frontend Vitest `include` glob, are touched.
- **Depends on (dependency graph edge):** **059** (`inventory_dashboard_frontend_backend_structure`).
- **Planning date:** 2026-07-01
- **Repo root:** `/home/t-kotama/workplace/ARI` (git branch `main`; `ari-core` version `0.9.0`)

> **Planning-phase notice.** This document is a plan for a *future* coding session. Authoring it changes no runtime code, imports, prompts, configs, workflows, frontend, or directory names — the only file the planning phase writes is this `.md`. Everything under Sections 8–9 describes what the **implementer of 065** will do later, and even then only test files (and possibly the Vitest test glob) are added.

> **Naming note carried through the whole program.** There is **no `sonfigs/`** directory anywhere in the repo. It is irrelevant to this subtask (which touches only `ari-core/ari/viz/` and `ari-core/tests/`); stated here only to head off the recurring typo.

---

## 1. Goal

Give the ARI dashboard an **executable, additive-contract regression suite on both sides of the wire** — Python tests over the backend `api_*.py` response builders and Vitest tests over the frontend `services/api.ts` client — so the sibling Phase-5 refactors can move code freely **without silently drifting the JSON shapes** that couple `ari-core/ari/viz/routes.py` + `api_*.py` to `ari-core/ari/viz/frontend/src/services/api.ts` (863 lines) and `.../src/types/index.ts` (264 lines).

Concretely, the downstream refactors this suite must guard are:

- **062** `refactor_dashboard_backend_routes_to_services` (routes → service layer; High risk, `Yes` runtime).
- **063** `refactor_dashboard_frontend_api_client_and_types` (rewrites `api.ts` + `types/index.ts`; High risk, `Yes` runtime).
- **064** `refactor_dashboard_state_and_component_boundaries` (decomposes god-components; High risk).

The deliverable is tests only. It neither changes wire behavior nor fixes the known contract hazards (two error regimes, unauth endpoints); it **pins them as-is** so any change becomes a visible, intentional test diff.

## 2. Background

The dashboard backend is Python `http.server` (no Flask/FastAPI). Routes are a single `if/elif` chain in `ari-core/ari/viz/routes.py` (`do_GET` ~lines 144–1026, `do_POST` ~1028–1188); handlers are plain module functions in the `api_*.py` files, each returning a `dict` serialized by `_json(data, status)` (`routes.py:1190-1197`). There is **no schema/validation/DTO layer** — POST bodies are `json.loads(body)` inside each handler, responses are ad-hoc dicts, and status is smuggled via `r.pop("_status", 200)`.

The frontend is Vite 5 + React 18.3 + TypeScript 5.5. `services/api.ts` has ~90 typed wrappers around same-origin `fetch` (`API_BASE = ''`). It runs **two incompatible error regimes** that any refactor could accidentally unify or break:

- `get<T>` / `post<T>` **throw** on non-2xx (`api.ts:18-32`).
- `pbGet<T>` / `pbPost<T>` (PaperBench) **never throw** and return `{error}` bodies verbatim (`api.ts:787-799`, with an explicit rationale comment at `api.ts:780-785`).

The **source of truth for shapes** is `types/index.ts`: `AppState`, `Settings`, `Checkpoint`, `CheckpointSummary`, `WorkflowData`, `WorkflowStage`, `ResourceMetrics`, `ReviewReport`, `CostSummary`, `TreeNode`. Several fields there carry inline comments that already document additive/optional wire policy (e.g. `Checkpoint.best_metric` is "always emitted … never reassigned from null"; `AppState.running/pid/llm_model` are "JS-compat aliases").

**Prior art that 065 extends, not duplicates.** A backend schema-contract test already exists: `ari-core/tests/test_api_schema_contract.py` (108 lines). It pins the *always-present* keys of exactly three endpoints — `/api/checkpoints`, `/api/checkpoint/<id>/summary` (base keys only), and `/api/settings` — using an **additive-subset doctrine** (extra keys allowed; only the not-found sentinel `{"error": "not found"}` is asserted by exact equality). 065's backend work is a **direct extension of this file's pattern and fixtures** (`isolated_state`, `_make_checkpoint`). 065's frontend work is new (no `api.ts` test exists today).

## 3. Scope

In scope:

1. **Extend backend schema-contract coverage** (`ari-core/tests/test_api_schema_contract.py`) to more of the FE-consumed endpoints whose handlers are callable as pure functions with monkeypatched module state: `/api/workflow` → `WorkflowData`, `/api/checkpoint/<id>/summary` full body (`nodes_tree`, `paper_tex`, `has_pdf`, `review_report`, `error`) → `CheckpointSummary`, `/api/resource-metrics` → `ResourceMetrics`, and the `/api/nodes/<rid>/<nid>/report` shape → `NodeReport`.
2. **Add a frontend `api.ts` contract test** (new file) that pins: `API_BASE === ''` (same-origin, no host prefix); `get/post` **throw** on non-2xx; `pbGet/pbPost` **do not throw** and pass `{error}` through; POST request-init shape (`method`, `Content-Type: application/json`, `body: JSON.stringify(body ?? {})`); and the exact endpoint path each representative wrapper hits (so 063 cannot silently rename a route).
3. **Add a frontend schema/shape test** that feeds fixtures conforming to `types/index.ts` through the wrappers and asserts the always-present keys survive the round-trip — the FE-side mirror of the Python additive-subset test.
4. **Keep `tsc --noEmit` green** as the compile-time half of the schema contract for `types/index.ts`.

## 4. Non-Goals

- **Not** changing any endpoint, handler, `_json` envelope, `api.ts` wrapper, or `types/index.ts` field. Behavior is pinned, not modified.
- **Not** unifying the two error regimes (that is a design decision owned by **063**), and **not** adding auth/CSRF (owned by the security/UX track; **070/071**).
- **Not** building a runtime JSON-Schema validator or DTO layer (policy owned by **061**; backend DTO artifacts by **022/034**).
- **Not** wiring these tests into CI — the Vitest suite is not run by any workflow today; CI integration is owned by **066** (`add_dashboard_build_and_ci_plan`).
- **Not** authoring a full `/state` payload contract test on the backend if it requires new production code — the `/state` builder is inlined in `routes.py:219-666` and is **not** an importable pure function today (see Section 6). Its full-payload contract is pinned FE-side now; a backend `/state` service test is deferred to after **062** extracts a `StateService`.
- **Not** restructuring `test_server.py` (1844) / `test_gui_errors.py` (1650) / `test_workflow_contract.py` (1606).

## 5. Current Files / Directories to Inspect

Backend (Python):
- `ari-core/tests/test_api_schema_contract.py` (108) — the file to extend; study `isolated_state`, `_make_checkpoint`, additive-subset doctrine.
- `ari-core/ari/viz/routes.py` (1197) — dispatch + inline `/state` builder (219–666), `_json` (1190–1197).
- `ari-core/ari/viz/checkpoint_api.py` (`_api_checkpoints`, `_api_checkpoint_summary`).
- `ari-core/ari/viz/api_settings.py` (`_api_get_settings`).
- `ari-core/ari/viz/api_workflow.py` (16 KB) — `/api/workflow`, `/api/workflow/default|flow`.
- `ari-core/ari/viz/api_state.py` (thin re-export facade; shows the callable surface) and `ari-core/ari/viz/state.py` (module globals monkeypatched by tests).
- `ari-core/ari/viz/ear.py` — `/api/nodes/<rid>/<nid>/report` (`NodeReport`).
- `ari-core/tests/test_server.py` (1844) — reference in-process harness (`from http.client import HTTPConnection`) and the existing inline `/state`-branch tests (`test_state_*`); do **not** modify.

Frontend (TypeScript):
- `ari-core/ari/viz/frontend/src/services/api.ts` (863) — client under test; error regimes at `18-32` and `787-799`.
- `ari-core/ari/viz/frontend/src/types/index.ts` (264) — shape source of truth.
- `ari-core/ari/viz/frontend/vitest.config.ts` — **read the `include` glob carefully** (see Section 6/17).
- `ari-core/ari/viz/frontend/vitest.setup.ts` — global `fetch`/`EventSource` stubbing pattern to reuse.
- `ari-core/ari/viz/frontend/package.json` — scripts: `test` (`vitest run`), `typecheck` (`tsc --noEmit`), `build` (`vite build`).
- `ari-core/ari/viz/frontend/src/components/PaperBench/__tests__/PaperBenchWizard.test.tsx` and `PaperImportDialog.test.tsx` — the only existing FE tests; copy their `vi.stubGlobal('fetch', vi.fn()...)` mocking style.

## 6. Current Problems

1. **Contract coverage is 3 endpoints out of ~90 FE wrappers.** `test_api_schema_contract.py` pins only `/api/checkpoints`, `/api/checkpoint/<id>/summary` (base keys), and `/api/settings`. High-traffic shapes consumed on the FE — `AppState` (`/state`), `WorkflowData` (`/api/workflow`), `ResourceMetrics`, `NodeReport`, and the full `CheckpointSummary` body — are unpinned. A 062/063 refactor could drop or rename a field and every existing test would still pass.
2. **The FE client is entirely untested.** No test exercises `services/api.ts`. The two-error-regime hazard, the `API_BASE=''` same-origin assumption, POST body encoding, and per-wrapper endpoint paths are unguarded; 063 rewrites this exact file with no safety net.
3. **`/state` is not unit-testable as a pure function.** The ~450-line builder is inlined in `routes.py:219-666`, so the existing `test_state_*` tests in `test_server.py` **re-implement the branch logic inline** rather than calling the real builder. A faithful backend `/state` contract test therefore needs either the `HTTPConnection` integration harness or waits for 062's `StateService` extraction. 065 pins `AppState` on the FE side to avoid coupling to that refactor.
4. **Vitest `include` glob only matches `*.test.tsx`.** `vitest.config.ts` sets `include: ['src/**/__tests__/**/*.test.tsx', 'src/**/*.test.tsx']`. A natural `api.test.ts` (the module under test is a `.ts`, not a component) would be **silently skipped**. This is the single most likely way for a well-intentioned test to be written and never run.
5. **No cross-language coupling between backend keys and FE types.** The Python test hard-codes contract keys and `types/index.ts` declares them independently; nothing asserts the two lists agree. (Fully unifying them is 022/034 territory; 065 at most documents the mapping.)

## 7. Proposed Design / Policy

- **Additive-subset doctrine (inherited).** Every shape test asserts a *subset* of always-present keys and allows extra keys, matching `test_api_schema_contract.py:6-10` and the wire's `{**defaults, **saved}` merge policy. Fixed error sentinels (e.g. `{"error": "not found"}`) may be asserted by exact equality; success payloads may not.
- **Backend: call handlers as pure functions.** Reuse `isolated_state` + `_make_checkpoint`; monkeypatch `ari.viz.state` globals and the `_resolve_checkpoint_dir` / `_checkpoint_search_bases` seams. **Never** bind a socket or spawn a subprocess in these tests. Where a handler is only reachable inline in `routes.py` (i.e. `/state`), do **not** add production code to make it testable — defer to 062 and note it.
- **Frontend: mock global `fetch`, assert request + response contract.** Reuse `vi.stubGlobal('fetch', vi.fn())` from the PaperBench tests and `vitest.setup.ts`. For each representative wrapper, assert (a) the URL passed to `fetch`, (b) for POST, the init object (`method`/headers/body), and (c) the returned value equals the mocked JSON. For the error regimes, drive a non-2xx (`{ ok: false, status: 500 }`) mock and assert `get/post` **reject** while `pbGet/pbPost` **resolve** with the `{error}` body.
- **Types are the source of truth.** Every fixture is annotated with the corresponding `types/index.ts` type (`const s: Settings = {...}`), so a field rename in 063 fails `tsc --noEmit` before it ever fails a runtime assertion. Cite the type name in the test name/comment.
- **File placement to satisfy the glob.** Put FE tests under an `__tests__/` dir next to the module and name them **`*.test.tsx`** (works with the current `include` even without JSX), e.g. `src/services/__tests__/api.test.tsx`. Preferred over broadening the glob so this subtask stays test-only. If a `.test.ts` name is strongly preferred, add `'src/**/*.test.ts'` to `include` and call it out explicitly (still config-only, no runtime change).
- **Representative, not exhaustive.** Pin the ~8 highest-value endpoints/wrappers rather than all ~90; exhaustive enumeration is the inventory job of **060**.

## 8. Concrete Work Items

1. **Extend `ari-core/tests/test_api_schema_contract.py`:**
   - `/api/checkpoint/<id>/summary` full body: assert `nodes_tree.nodes` (list), `paper_tex`, `has_pdf`, `review_report`, `error` keys present per `CheckpointSummary`.
   - `/api/workflow`: call the `api_workflow` builder with a temp workflow file; assert `ok`, `error`, `path`, and `workflow.pipeline` / `workflow.skills` keys per `WorkflowData`.
   - `/api/resource-metrics`: assert the `ResourceMetrics` keys (`process_count`, `memory_rss_mb`, `cpu_load_1m/5m/15m`, `cpu_count`, `experiment_pid`, `timestamp`).
   - `/api/nodes/<rid>/<nid>/report`: assert the `NodeReport` shape (per `api.ts:124-153`) via `ear.py`.
   - Add a docstring line noting each new test's `types/index.ts` counterpart.
2. **Add `ari-core/ari/viz/frontend/src/services/__tests__/api.test.tsx`:**
   - `API_BASE` same-origin: `fetchState()` calls `fetch('/state')` (no host).
   - `get` throw vs `pbGet` non-throw on `status: 500`.
   - `post` init: `method: 'POST'`, `headers['Content-Type'] === 'application/json'`, `body === JSON.stringify(body ?? {})`.
   - Endpoint-path pins for a representative set: `fetchState`→`/state`, `fetchCheckpoints`→`/api/checkpoints`, `getSettings`→`/api/settings`, `fetchWorkflow`→`/api/workflow`, `fetchResourceMetrics`→`/api/resource-metrics` (confirm exact exported names in `api.ts` before writing).
   - (Optional) assert no `Authorization`/CSRF header is added — pins the current same-origin unauth contract so 070/071 must change it deliberately.
3. **Add `ari-core/ari/viz/frontend/src/services/__tests__/schema.test.tsx`:**
   - Fixtures typed as `Settings`, `Checkpoint`, `CheckpointSummary`, `AppState`, `WorkflowData`, `ResourceMetrics`; feed each through its wrapper via mocked `fetch`; assert always-present keys survive. This is the FE mirror of the Python additive-subset suite and the pinning home for `AppState`/`/state`.
4. **Verify the Vitest glob** picks up the new `__tests__/*.test.tsx` files (`npm test` lists them); if a `.test.ts` name is chosen, update `vitest.config.ts` `include` and note it in the PR description.
5. Run the full Section 12 gate locally and record results in the PR body.

## 9. Files Expected to Change

Created (test files — no runtime effect):
- `ari-core/ari/viz/frontend/src/services/__tests__/api.test.tsx` — NEW; `api.ts` behavior/endpoint contract.
- `ari-core/ari/viz/frontend/src/services/__tests__/schema.test.tsx` — NEW; FE shape fixtures vs `types/index.ts`.

Modified (test file — extension only):
- `ari-core/tests/test_api_schema_contract.py` (108 → larger) — additional additive-subset tests for `/api/workflow`, full `/api/checkpoint/<id>/summary`, `/api/resource-metrics`, `/api/nodes/.../report`.

Modified only if the `.test.ts` naming path is taken (config-only, still `No` runtime code):
- `ari-core/ari/viz/frontend/vitest.config.ts` — add `'src/**/*.test.ts'` to `include`.

Must **not** be touched: `services/api.ts`, `types/index.ts`, any `ari-core/ari/viz/*.py` handler, `routes.py`, `vitest.setup.ts` (reuse as-is), any `.github/workflows/*`.

## 10. Files / APIs That Must Not Be Broken

- **Dashboard API endpoints/JSON shapes** — `routes.py` + `api_*.py` responses consumed by `services/api.ts` and the WebSocket. 065 only reads and asserts them.
- **The `ari.public.*` surface, CLI `ari`, MCP tool contracts, checkpoint/config formats** — untouched; not in this subtask's blast radius.
- **`services/api.ts` public wrapper names and `types/index.ts` exports** — imported by the new tests; the tests must adapt to the current names, never rename them.
- **Existing tests** — `test_api_schema_contract.py` existing cases, `test_server.py`, `test_gui_errors.py`, `test_workflow_contract.py`, `PaperBench/__tests__/*` must keep passing.

## 11. Compatibility Constraints

- **No compatibility adapter is required** — this subtask adds tests and (optionally) a test glob; it introduces no new import path, no changed signature, no wire change. It is a *guard for* the contracts, not a change *to* them.
- The Vitest suite is currently **not** executed by any workflow (the `npm`/`node` usage in `pages.yml`/`docs-sync.yml` builds the VitePress docs, not the viz frontend). Adding FE tests here changes no CI behavior until **066** wires them in. `.github/workflows/refactor-guards.yml` runs `pytest ari-core/tests/` (with `--ignore=...test_dashboard_html.py` etc.), so the extended Python test **will** run in that job automatically — it must therefore stay hermetic (no sockets, no network, no `$HOME/.ari/` writes, no real subprocess).

## 12. Tests to Run

Backend / repo-wide (from repo root):
- `python -m compileall .` — byte-compile guard.
- `pytest -q` — full suite; specifically `pytest -q ari-core/tests/test_api_schema_contract.py`.
- `ruff check .` — lint the extended Python test.

Frontend (from `ari-core/ari/viz/frontend/`; npm only — **no pnpm** in this repo):
- `npm ci` (or `npm install`) — install if `node_modules/` absent (it is git-ignored, present on disk as a normal install).
- `npm test` (`vitest run`) — must discover and pass the new `__tests__/*.test.tsx` files.
- `npm run typecheck` (`tsc --noEmit`) — the compile-time half of the schema contract.
- `npm run build` (`vite build`) — confirm the new test files don't break the production bundle build.

## 13. Acceptance Criteria

1. `pytest -q ari-core/tests/test_api_schema_contract.py` passes, now covering ≥4 additional endpoints (`/api/workflow`, full `/api/checkpoint/<id>/summary`, `/api/resource-metrics`, `/api/nodes/.../report`) with additive-subset assertions; `pytest -q` (full suite) stays green.
2. `npm test` discovers and passes `api.test.tsx` and `schema.test.tsx`; the run output lists them (proving the glob matched).
3. The FE tests pin, with explicit assertions: `API_BASE === ''`, `get/post` reject on non-2xx, `pbGet/pbPost` resolve with `{error}` on non-2xx, POST init shape, and the endpoint path of each representative wrapper.
4. Every fixture is annotated with its `types/index.ts` type and `npm run typecheck` + `npm run build` pass.
5. `python -m compileall .` and `ruff check .` pass. No production `.py`/`.ts`/`.tsx` under `ari-core/ari/viz/` (other than test files, and optionally `vitest.config.ts`) is modified.
6. The extended Python test remains hermetic under `refactor-guards.yml` (no `$HOME/.ari/` writes, no bound sockets, no subprocess).

## 14. Rollback Plan

Fully test-only and trivially reversible. To roll back: `git rm` the two new `__tests__/*.test.tsx` files, `git revert`/`git checkout` the extension to `test_api_schema_contract.py`, and (if changed) restore `vitest.config.ts`. No runtime code, checkpoint, config, or wire behavior is affected, so removal cannot regress any user-facing path. If a new test proves flaky, mark it `@pytest.mark.skip` / `it.skip` with a linked follow-up rather than reverting the whole set.

## 15. Dependencies

Per the program dependency graph, **065 depends only on 059** (`inventory_dashboard_frontend_backend_structure`), the Phase-5 inventory gate that everything in Phases 5–6 fans out from. That is the sole hard predecessor edge.

- **Hard (graph) predecessor:** **059** — establishes the FE/BE structure inventory these tests are written against.
- **Recommended soft predecessors (should precede so tests pin the *agreed* shapes, not just today's):** **060** `inventory_dashboard_api_contracts` (the FE-side ~90-wrapper contract inventory) and **061** `define_dashboard_dto_and_schema_policy` (the DTO/schema policy that grounds 062/063/065). If 060/061 land first, align key lists to them; if not, pin current behavior and leave a note.
- **Sibling/alignment (avoid duplication; do not re-own):** **022** `define_dashboard_dto_and_schema_tests` and **034** `add_contract_snapshot_fixtures` (Phase-4 backend DTO/schema-fixture work) and **030** `add_viz_api_schema_checker_script`. 065 is the Phase-5 **frontend-inclusive** counterpart of 022; reuse `test_api_schema_contract.py` rather than forking a parallel backend test.
- **Downstream consumers (these tests exist to guard them):** **062** (backend routes→services), **063** (FE api client + types), **064** (FE state/component boundaries). 065 does **not** depend on 062/063/064 — the tests are written against the *current* contract first, then act as the regression net while those refactors run.
- **CI wiring is out of scope and owned by 066** (`add_dashboard_build_and_ci_plan`); the extended Python test rides the existing `refactor-guards.yml` pytest job automatically.

## 16. Risk Level

**Low.** **Changes runtime code: No.** The subtask adds test files and, at most, a Vitest test-discovery glob — no runtime `.py`/`.ts`/`.tsx` handler, client, or type is modified, so it cannot alter wire behavior or user-facing paths. Residual risks are minor and test-local: (a) a mistaken *exact-equality* assertion on an additive success payload (mitigated by the inherited subset doctrine); (b) a new FE test that is silently not run due to the `*.test.tsx`-only glob (mitigated by Section 17 and by checking `npm test` output); (c) a non-hermetic Python test tripping `refactor-guards.yml` (mitigated by the pure-function/monkeypatch pattern already in `test_api_schema_contract.py`).

## 17. Notes for Implementer

- **Glob gotcha (read first).** `vitest.config.ts` `include` is `*.test.tsx`-only. Name FE tests `api.test.tsx` / `schema.test.tsx` (JSX not required) so they are discovered without touching config. If you insist on `.test.ts`, add `'src/**/*.test.ts'` to `include` and say so in the PR.
- **Pin, don't fix.** The two error regimes (`get/post` throw vs `pbGet/pbPost` swallow) are a *documented* contract (`api.ts:780-785`). Assert both as-is. Unifying them is 063's call.
- **`/state` is inline.** Do not add production code to make `routes.py:219-666` importable. Pin `AppState`/`/state` on the FE side (fixture typed `AppState`, mocked `fetch('/state')`). A backend `/state` service test is a follow-up after 062.
- **Reuse the existing seams.** Backend: `isolated_state` fixture + `monkeypatch.setattr(checkpoint_api, "_resolve_checkpoint_dir", ...)` / `_checkpoint_search_bases`, exactly as the current file does. Frontend: `vi.stubGlobal('fetch', vi.fn())` and the `afterEach(cleanup)` in `vitest.setup.ts`; `EventSource` is already stubbed there.
- **Confirm exported names.** Before pinning endpoint paths, grep `api.ts` for the actual exported wrapper names (`fetchState`, `fetchCheckpoints`, etc. — verify, don't assume) and use those.
- **Additive-subset only for success payloads.** Extra keys must be allowed (`{**defaults, **saved}` merges, conditional fields). Exact equality is fine only for fixed sentinels like `{"error": "not found"}`.
- **Hermetic backend tests.** No sockets, no `Popen`, no network, no `$HOME` writes — the extended file runs inside `refactor-guards.yml`.
- **Type annotate every fixture** (`const s: Settings = {...}`) so `tsc --noEmit` catches field renames from 063 at compile time.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **065** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
