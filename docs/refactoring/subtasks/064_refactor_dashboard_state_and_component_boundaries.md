# Subtask 064: Refactor Dashboard State And Component Boundaries

> Phase 5: Dashboard Frontend
> Classification: **ADAPT** (frontend state architecture + component decomposition behind an unchanged REST/WS wire contract and unchanged visible UX)
> Inventory gates: **059** (`inventory_dashboard_frontend_backend_structure`), **060** (`inventory_dashboard_api_contracts`)
> Coordinates with: **061** (dto/schema policy), **063** (FE api client + types), **065** (contract/schema tests), **066** (build/CI), and Phase-6 **070** (settings panel UX)
> Runtime code change: **YES** (frontend TypeScript under `ari-core/ari/viz/frontend/src/`)

This document is a PLANNING artifact. It changes no runtime code. It is
self-contained: a fresh coding session should be able to execute it after
reading Sections 5, 8, 9, and 10, and after gates 059/060 exist.

---

## 1. Goal

Give the ARI dashboard frontend a **coherent state architecture** and **clean
component boundaries** so that:

1. Shared application state (the `/state` poll, the checkpoints list, the
   WebSocket node stream, and the current route) lives behind small,
   single-responsibility hooks/contexts instead of one catch-all
   `AppContext` plus a *second, independent* route-state copy in `App.tsx`.
2. The god-components (`Results/resultSections.tsx` 1590, `Wizard/StepResources.tsx`
   1160, `Settings/SettingsPage.tsx` 1049, `Workflow/WorkflowPage.tsx` 964,
   `Workflow/workflowNodes.tsx` 770) are decomposed into presentational +
   container units with explicit props boundaries and colocated local state,
   following the pattern already proven by `Tree/DetailPanel.tsx` (425) →
   `Tree/DetailPanelTabs/*` and by the extracted hooks
   `Tree/useDetailPanelData.ts` (204) and `Results/useEAR.ts` (38).
3. Large ad-hoc local-state clusters (`Wizard/WizardPage.tsx` and
   `Settings/SettingsPage.tsx` each carry ~38 `useState` references,
   `Results/ResultsPage.tsx` ~23, `Wizard/StepResources.tsx` ~18) are
   consolidated into reducers or purpose-built hooks so a reader can reason
   about each component's state transitions.

**Without** changing any dashboard REST/WS wire contract, any visible page,
route, section, label, or user-facing behavior, and **without** touching the
API client `services/api.ts` (owned by 063), the TS type surface `types/index.ts`
(owned by 063), or the Settings panel's information architecture / UX (owned by
Phase-6 070). This subtask is **structural**: same pixels, same network traffic,
better internal seams.

## 2. Background

The dashboard is a self-contained SPA served by the stdlib viz backend
(`ari-core/ari/viz/`) from a Vite production bundle. Verified stack (from
`ari-core/ari/viz/frontend/package.json` and configs, 2026-07-01):

- **Vite 5 + React 18.3 + TypeScript 5.5**, ESM (`"type":"module"`). Runtime
  deps are minimal: `react`, `react-dom`, `d3@7.9`, `reactflow@11.11`. No CSS
  framework — styling is `src/styles/*.css` (7 files) plus pervasive inline
  `style={{}}`. No Redux / Zustand / react-query / react-router. Tests via
  Vitest 2 + Testing Library + jsdom (`vitest.config.ts`).
- **Routing is a hand-rolled hash router.** `App.tsx:32` `parseHash()` +
  `App.tsx:41` `PAGE_MAP` (12 routes incl. 3 `paperbench/*` sub-routes; legacy
  `new`→`wizard` alias at `App.tsx:37`). All pages are `lazy()` + `<Suspense>`
  (`App.tsx:8-28`). The nav mirror is a second hardcoded list `NAV_ITEMS` in
  `Layout/Sidebar.tsx:12-23`.
- **State is one React Context.** `context/AppContext.tsx` (120 lines) holds
  `state` (from `/state`), `nodesData` (WebSocket via `hooks/useWebSocket.ts`,
  falling back to `state.nodes` at `AppContext.tsx:96`), `checkpoints`, and
  `currentPage`. It **polls `/state` + `/checkpoints` every 5s**
  (`AppContext.tsx:34,83-93`). A generic fetch hook `hooks/useApi.ts` (43)
  exists but is used in only one place (`PaperBench/PaperRegistryPage.tsx`).
- **Consumers of the context** (9 files): `Home/HomePage.tsx`,
  `Experiments/ExperimentsPage.tsx`, `Monitor/MonitorPage.tsx`,
  `Monitor/PhaseStepper.tsx`, `Tree/TreePage.tsx`, `Results/ResultsPage.tsx`,
  `Idea/IdeaPage.tsx`, `Settings/SettingsPage.tsx`, `Layout/Sidebar.tsx`.

Where this sits in the plan: **059** inventories the whole FE/BE structure and
is the fan-out gate for Phase 5; **060** inventories the API contract on the FE
side (`services/api.ts`, ~90 wrappers, two error regimes). **063** refactors the
API client + TS types. **064** (this doc) owns the state layer and component
decomposition that sit *on top of* the 063 client. Per
`docs/refactoring/007_subtask_index.md:111,269`, 064 is **High** risk with
**Runtime Code Change = Yes**, gated by 059 (and the cross-cutting inventory
gates 059/060/067 per the footnote at `007_subtask_index.md:113-115`).

Note: the "sonfigs" directory referenced in some planning prompts **does not
exist** anywhere in the repo; it is irrelevant to the frontend and is not
referenced here.

## 3. Scope

In scope (frontend TypeScript, executed AFTER gates 059/060 exist):

- **State architecture** under `ari-core/ari/viz/frontend/src/`:
  - `context/AppContext.tsx` (120) — split the catch-all provider into focused
    concerns (app-state/polling, checkpoints, route, ws-nodes) so consumers
    subscribe to only what they use.
  - `hooks/useWebSocket.ts` (97), `hooks/useApi.ts` (43) — keep/extend; adopt
    `useApi` (or an equivalent) broadly instead of bespoke `useState` +
    `useEffect` fetch blocks.
  - The **duplicated route state**: `App.tsx:60-67` `Router` keeps its own
    `useState(parseHash)` + `hashchange` listener, while `AppContext.tsx:40-43,
    70-78` keeps a *separate* `currentPage` + `hashchange` listener. Two
    sources of truth for the current route → unify into one route hook.
  - The two hardcoded route tables (`App.tsx:41` `PAGE_MAP` vs
    `Layout/Sidebar.tsx:12-23` `NAV_ITEMS`) — consolidate to a single route
    manifest to remove drift risk.
- **Component-boundary decomposition** of the worst god-components (see
  Section 6 for the ranked list), splitting each into a thin container +
  presentational children + colocated hooks, mirroring the existing good
  pattern in `Tree/`.
- Large **local-state clusters** → reducers / purpose-built hooks
  (`Wizard/WizardPage.tsx` ~38, `Results/ResultsPage.tsx` ~23,
  `Wizard/StepResources.tsx` ~18 `useState`).

Explicitly delegated (touched by sibling subtasks, NOT by 064):

- `services/api.ts` (863) request/response wrappers and the two error regimes
  (`get/post` throw vs `pbGet/pbPost` return `{error}`) → **063**. 064 consumes
  the client's public functions and may add a thin FE-side error-normalization
  hook, but must not change `api.ts` signatures.
- `types/index.ts` DTO shapes (`AppState`, `Settings`, `Checkpoint`, …) → **063**.
- **Settings panel UX / information architecture** (tabs, search, progressive
  disclosure, dangerous-surface gating, the 9 `<Card>` sections and their
  order) → Phase-6 **067–070**. 064 may *structurally* extract
  `SettingsPage.tsx` section sub-components and lift its ~38 `useState` into a
  reducer/hook **only if visible output and the `/api/settings` flat-object save
  are unchanged**; if that risks colliding with 070, defer SettingsPage
  decomposition to 070 and limit 064 to its state-clustering (see Section 17).

## 4. Non-Goals

- **NOT** changing any dashboard REST endpoint path, HTTP method, request body,
  response JSON shape, status code, or the single WebSocket message
  `{"type":"update","data":<tree>,"timestamp":...}` on `port+1`. 064 is
  frontend-only and consumes the contract unchanged.
- **NOT** editing `services/api.ts` or `types/index.ts` (both are 063's).
- **NOT** redesigning the Settings panel's IA/UX or the dangerous-surface
  gating (Raw JSON tab at `Tree/DetailPanel.tsx`, `/api/env-keys` secret
  exposure, GPU-monitor SLURM auto-resubmit) — those are Phase-6 (067–072).
- **NOT** adding a routing library (react-router), a state library
  (Redux/Zustand/react-query), or a CSS framework. Stay within the current
  minimal dependency set unless 059/061 explicitly authorize a new dep.
- **NOT** changing i18n copy or keys (`i18n/en.ts`/`ja.ts`/`zh.ts`); keep the
  `check_i18n_js.py` gate green. If a route manifest touches label keys, keep
  all three locale files in parity.
- **NOT** touching any Python (`ari-core/ari/viz/*.py`), `docs/`, `report/`, or
  `.github/workflows/`. No directory renames.
- **NOT** vendoring/committing `node_modules/` — it is correctly git-ignored
  (`.gitignore:113`) and must stay untracked.

## 5. Current Files / Directories to Inspect

All paths absolute-from-repo-root (`/home/t-kotama/workplace/ARI`). Root of the
frontend: `ari-core/ari/viz/frontend/`. Verified LOC (2026-07-01).

State / routing / entry:

| File | LOC | Role |
| --- | --- | --- |
| `.../frontend/src/context/AppContext.tsx` | 120 | Single `AppProvider`: `/state` + `/checkpoints` 5s polling, WS nodes fallback, `currentPage`, `checkpoints`. Exposes `useAppContext()`. |
| `.../frontend/src/App.tsx` | 94 | Hash router: `parseHash()` (32), `PAGE_MAP` (41), inner `Router` with its **own** `currentPage` state + `hashchange` listener (60-67). |
| `.../frontend/src/main.tsx` | 40 | ReactDOM entry + top-level ErrorBoundary (prints stack to page). |
| `.../frontend/src/hooks/useWebSocket.ts` | 97 | WS on `port+1`, exponential-backoff reconnect, `{nodesData, connected}`. |
| `.../frontend/src/hooks/useApi.ts` | 43 | Generic `{data, loading, error, refetch}` fetch hook — **under-used** (1 consumer). |
| `.../frontend/src/components/Layout/Sidebar.tsx` | 191 | Second hardcoded route list `NAV_ITEMS` (12-23); consumes `useAppContext`; local sidebar-resize + project-switch state. |
| `.../frontend/src/components/Layout/Layout.tsx` | — | Shell wrapper. |

God-components / decomposition targets (ranked by LOC):

| File | LOC | ~`useState` | Note |
| --- | --- | --- | --- |
| `.../frontend/src/components/Results/resultSections.tsx` | 1590 | ~6 | 6 exported render-fns incl. ~460-line `renderReviewScores`. |
| `.../frontend/src/components/Wizard/StepResources.tsx` | 1160 | ~18 | Single component + ORS config block. |
| `.../frontend/src/components/Settings/SettingsPage.tsx` | 1049 | ~38 | God-component; 9 inline `<Card>` sections. **UX = 070; state-clustering only here.** |
| `.../frontend/src/components/Workflow/WorkflowPage.tsx` | 964 | ~14 | React Flow editor page. |
| `.../frontend/src/components/Workflow/workflowNodes.tsx` | 770 | ~12 | Node type components. |
| `.../frontend/src/components/Wizard/StepGoal.tsx` | 528 | ~5 | — |
| `.../frontend/src/components/Results/PaperWorkspace.tsx` | 519 | — | — |
| `.../frontend/src/components/Monitor/MonitorPage.tsx` | 502 | ~7 | Consumes context. |
| `.../frontend/src/components/Idea/IdeaPage.tsx` | 478 | — | Consumes context. |
| `.../frontend/src/components/Results/ResultsPage.tsx` | 462 | ~23 | Consumes context; heaviest local-state cluster after Wizard/Settings. |

Good existing patterns to imitate (already decomposed — do not undo):

- `.../frontend/src/components/Tree/DetailPanel.tsx` (425) → `Tree/DetailPanelTabs/`
  (`AccessTab.tsx` 155, `MemoryEntryCard.tsx` 131, `ReportTab.tsx` 126,
  `MemoryTab.tsx` 113, `TraceTab.tsx` 57, `CodeTab.tsx` 42).
- Extracted hooks: `Tree/useDetailPanelData.ts` (204), `Results/useEAR.ts` (38);
  extracted constants: `Settings/settingsConstants.ts` (86),
  `Wizard/stepResourcesSections.tsx` (407); helpers:
  `Results/resultHelpers.ts` (169), `Tree/detailPanelHelpers.ts` (31),
  `Results/resultTypes.ts` (31).

Read-only references (owned by 063 — do NOT edit here):

- `.../frontend/src/services/api.ts` (863) — the ~90 typed wrappers and the two
  error regimes (`api.ts:18-32` throw; `api.ts:787-799` `pbGet/pbPost` return
  `{error}`). 064 must consume these unchanged.
- `.../frontend/src/types/index.ts` — `AppState`, `Settings`, `Checkpoint`, `TreeNode`.

Tooling / config / tests:

- `.../frontend/package.json` (scripts: `dev/build/typecheck/preview/test/test:watch`).
- `.../frontend/vite.config.ts`, `.../frontend/vitest.config.ts` (jsdom;
  `include: src/**/__tests__/**/*.test.tsx`, `src/**/*.test.tsx`),
  `.../frontend/vitest.setup.ts`.
- Existing FE tests: `.../frontend/src/components/PaperBench/__tests__/PaperBenchWizard.test.tsx`
  (118), `.../PaperImportDialog.test.tsx` (138). **These are the only two FE
  tests today** — 064 must add render/state tests for decomposed components
  (coordinate with 065).
- Per-directory `README.md` files exist throughout `frontend/src/**` (e.g.
  `src/README.md`, `src/context/README.md`, `src/hooks/README.md`, and one per
  component dir) — a readme-parity gate (`scripts/docs/check_readme_parity.py`)
  and i18n-parity gate (`scripts/docs/check_i18n_js.py`) run in CI.
- Backend contract test that depends on the built bundle:
  `ari-core/tests/test_dashboard_html.py` asserts the Vite production bundle
  exists at `ari-core/ari/viz/static/dist/` — so a passing `npm run build` is
  part of keeping the backend suite green.

Upstream planning references: `docs/refactoring/007_subtask_index.md`
(rows 059–066, `Phase 5` section at lines ~255-271),
`docs/refactoring/008_viz_dashboard_refactoring_plan.md`,
`docs/refactoring/014_dashboard_ux_refactoring_plan.md` (UX = Phase 6),
`docs/refactoring/006_target_architecture_plan.md`,
`docs/refactoring/010_contract_preservation_policy.md`. Gates 059/060 docs at
`docs/refactoring/subtasks/059_*.md` and `060_*.md` (author before executing).

## 6. Current Problems

Grounded in the routed frontend findings and re-verified line references:

1. **Two independent sources of truth for the current route.** `App.tsx:60-67`
   holds `page` via `useState(parseHash)` + a `hashchange` listener; separately
   `AppContext.tsx:40-43,70-78` holds `currentPage` + its own `hashchange`
   listener. `Sidebar.tsx:26` navigates via `setCurrentPage` (context) while the
   actual page render is driven by `App.tsx`'s local `page`. Route logic is
   duplicated and can drift.
2. **Catch-all context forces broad re-renders.** `AppContext` bundles four
   unrelated concerns (poll state, checkpoints, WS nodes, route). Every 5s poll
   updates `state`, re-rendering all 9 consumers even if they only need
   `checkpoints` or `currentPage`. There is no memo/selector boundary.
3. **God-components.** `resultSections.tsx` (1590) exports 6 render functions,
   one (`renderReviewScores`) ~460 lines; `StepResources.tsx` (1160) is one
   component with ~18 `useState` + an inline ORS config block;
   `SettingsPage.tsx` (1049) is one component rendering 9 `<Card>` sections
   inline; `WorkflowPage.tsx` (964) + `workflowNodes.tsx` (770) pack the whole
   React Flow editor. These exceed any reasonable review/maintenance boundary.
4. **Oversized local-state clusters.** `WizardPage.tsx` and `SettingsPage.tsx`
   carry ~38 `useState` references each, `ResultsPage.tsx` ~23,
   `StepResources.tsx` ~18. Related fields are not grouped, so invariants
   between them (e.g. wizard step gating, settings form dirtiness) are implicit
   and error-prone.
5. **`useApi` is written but unused.** A generic `{data, loading, error,
   refetch}` hook exists (`hooks/useApi.ts`) but only `PaperRegistryPage.tsx`
   uses it; everywhere else, components re-implement `useState` + `useEffect` +
   `try/catch` fetch blocks by hand, duplicating loading/error handling and
   diverging in how they surface errors.
6. **Two hardcoded route tables that can drift.** `App.tsx:41` `PAGE_MAP` (12
   entries incl. `paperbench/*` sub-routes and the `new`/`wizard` alias) and
   `Sidebar.tsx:12-23` `NAV_ITEMS` (10 entries) are maintained independently;
   adding a page requires editing both, with no compile-time link.
7. **Inconsistent error surfacing at the state boundary.** Because `api.ts` has
   two error regimes (throw vs `{error}` body — owned by 063), the *consuming*
   components each handle failures differently (some `console.warn` and swallow,
   e.g. `AppContext.tsx:55-57,65-67`; some render inline error strings). There is
   no shared FE-side error/loading convention.
8. **Thin test coverage for state and large components.** Only two FE tests
   exist (both under `PaperBench/__tests__`). None cover `AppContext`, the
   router, or any god-component, so decomposition currently has no regression
   net on the FE side.

## 7. Proposed Design / Policy

**Policy: focused state hooks/contexts → thin containers → presentational
children, with zero wire change and zero visible-UX change.** No new heavy
dependency; keep React primitives (`useReducer`, `useContext`, `useMemo`,
custom hooks).

### 7.1 Unify and split app state

- Introduce a single **route hook** (e.g. `hooks/useHashRoute.ts`) that owns
  `parseHash()`, the `hashchange` subscription, and `navigate(page)`. Both
  `App.tsx` and `Sidebar.tsx` consume it; remove the duplicate `currentPage`
  from `AppContext` (or make `AppContext` delegate to the hook) so there is one
  source of truth (fixes problem #1).
- Split the catch-all `AppContext` into **focused providers/hooks** that can be
  composed under a single top-level provider, e.g.:
  - `useAppState()` — the `/state` 5s poll + `refreshState`.
  - `useCheckpoints()` — the `/checkpoints` list + `refreshCheckpoints`.
  - `useTreeNodes()` — the WS-vs-poll `nodesData` fallback (`AppContext.tsx:96`).
  Keep a compatibility `useAppContext()` that returns the same shape as today so
  the 9 existing consumers keep compiling; migrate them consumer-by-consumer to
  the narrower hooks so each subscribes only to what it uses (fixes #2). Do the
  facade-first, migrate-later sequence to keep every step green.
- Preserve the current polling cadence (`STATE_POLL_MS = 5000`,
  `AppContext.tsx:34`) and the WS-first/poll-fallback semantics exactly.

### 7.2 Single route manifest

- Derive both `PAGE_MAP` and `NAV_ITEMS` from **one** manifest (page key → lazy
  component + nav metadata: icon, i18n `labelKey`, whether it appears in the
  sidebar). Keep the `new`→`wizard` alias and the 3 `paperbench/*` sub-routes.
  This removes the drift in problem #6 without changing any route string,
  default (`home`), or lazy-loading behavior.

### 7.3 Decompose god-components (container + presentational + hooks)

Apply the pattern already proven by `Tree/DetailPanel.tsx` → `DetailPanelTabs/*`
+ `useDetailPanelData.ts`:

- `Results/resultSections.tsx` (1590): split the 6 render-fns into sibling
  components under `Results/` (e.g. `sections/ReviewScoresSection.tsx`, etc.),
  each importing shared helpers from the existing `resultHelpers.ts` /
  `resultTypes.ts`. Break `renderReviewScores` (~460 lines) into subcomponents.
- `Wizard/StepResources.tsx` (1160): lift its ~18 `useState` into a
  `useStepResourcesForm` reducer-hook; move the ORS config block and the
  already-partially-extracted `stepResourcesSections.tsx` (407) into cohesive
  child components.
- `Workflow/WorkflowPage.tsx` (964) + `workflowNodes.tsx` (770): separate graph
  state/handlers (hook) from node/edge rendering (presentational), keeping the
  React Flow node-type registry stable.
- `Settings/SettingsPage.tsx` (1049): **state-clustering only** in 064 —
  consolidate its ~38 `useState` into a `useSettingsForm` reducer and, if
  non-conflicting with 070, extract the 9 `<Card>` sections into presentational
  children. The visible sections, order, labels, and the flat 24-key
  `/api/settings` save (`SettingsPage.tsx:235-260`) MUST stay byte-identical.
  If overlap with 070 is a concern, limit 064 to the reducer consolidation and
  hand the section extraction to 070 (Section 17).

### 7.4 Standardize data-fetching + error/loading

- Adopt `hooks/useApi.ts` (or a small extension of it) across components that
  currently hand-roll `useState`+`useEffect` fetches, giving one
  `{data, loading, error, refetch}` convention (fixes #5). Add a shared
  **error-normalization** helper so both `api.ts` error regimes surface
  uniformly on the FE (throw → caught; `{error}` body → mapped to `error`),
  **without** editing `api.ts` (that normalization/consolidation on the client
  side is 063's; 064 only builds the consuming hook). Coordinate the exact seam
  with 063.

### 7.5 Module layout & classification

- New hooks live under `.../frontend/src/hooks/`; new context slices under
  `.../frontend/src/context/`; decomposed children stay inside their feature
  folder (`Results/`, `Wizard/`, `Workflow/`, `Settings/`) next to their parent,
  preferably in a `sections/` or same-dir sibling, re-exported via the existing
  `index.ts` barrels. Update the per-directory `README.md` for any folder that
  gains/loses files (readme-parity gate).
- Classification summary: **ADAPT** the FE state layer and god-components behind
  the frozen wire contract and unchanged UX. The unused-but-kept `useApi.ts` is
  **KEEP** (promote to broad use). No **DELETE_CANDIDATE** unless a helper is
  proven dead by 053/055 tooling. No **MOVE_TO_LEGACY**, no **deprecated**
  (internal reorganization only). The duplicate route-state / dual route tables
  are **MERGE** into one route hook + one manifest.

## 8. Concrete Work Items

Execute only after gates 059 (FE/BE structure inventory) and 060 (API contract
inventory) exist (Section 15). Suggested order — each step ends with the
Section 12 gate set:

1. **Ingest 059/060.** Treat the FE state map, component inventory, and the
   frozen endpoint/shape list as the reference; do not re-derive them ad hoc.
2. **Add `useHashRoute` hook** and route through it from both `App.tsx` and
   `Sidebar.tsx`; delete the duplicate `currentPage`/`hashchange` in
   `AppContext.tsx` (or delegate). Verify all navigation still works; typecheck.
3. **Introduce the single route manifest** and derive `PAGE_MAP` + `NAV_ITEMS`
   from it. No route string, default, alias, or sidebar entry changes.
4. **Split `AppContext`** into `useAppState`/`useCheckpoints`/`useTreeNodes`
   behind a compat `useAppContext()` facade (same return shape). Keep
   `STATE_POLL_MS` and WS-fallback semantics. Full suite green.
5. **Migrate the 9 context consumers** to the narrow hooks one at a time,
   verifying each still renders and behaves identically. Retire the facade only
   once all consumers are migrated (or keep it — it is cheap and harmless).
6. **Adopt `useApi` + shared error normalization** in components with hand-rolled
   fetches; do not edit `api.ts` (coordinate the seam with 063).
7. **Decompose god-components** in LOC order, one component per commit:
   `resultSections.tsx` → `Wizard/StepResources.tsx` → `Workflow/WorkflowPage.tsx`
   + `workflowNodes.tsx` → `SettingsPage.tsx` (state-clustering; sections only if
   non-conflicting with 070). After each, add render/state tests (step 8) and run
   `npm run typecheck && npm test && npm run build`.
8. **Add FE tests** (coordinate with 065): unit tests for `useHashRoute`, the
   route manifest, the split state hooks, and at least one render + interaction
   test per decomposed god-component. Place under `__tests__/` per the existing
   Vitest `include` globs.
9. **Update per-directory `README.md`** files for any folder whose file list
   changed; keep i18n locale files in parity if the manifest touches label keys.
10. **Rebuild the production bundle** (`npm run build`) so
    `ari-core/tests/test_dashboard_html.py` (which asserts `viz/static/dist/`
    exists) stays green, and run the backend suite once for parity.

## 9. Files Expected to Change

Frontend TypeScript (only when this subtask is executed, post-059/060). All
under `ari-core/ari/viz/frontend/src/`:

- `context/AppContext.tsx` — split into focused slices; route state removed;
  compat `useAppContext()` retained.
- `App.tsx` — route via new `useHashRoute`; `PAGE_MAP` derived from the manifest.
- `components/Layout/Sidebar.tsx` — `NAV_ITEMS` derived from the manifest; uses
  `useHashRoute`.
- `hooks/useApi.ts` — possibly extended; adopted broadly (no signature break).
- **New** `hooks/useHashRoute.ts` — single route source of truth.
- **New** route manifest module (e.g. `src/routes.ts` or `context/routes.ts`).
- **New** state-slice hooks/providers (e.g. `context/useAppState.ts`,
  `context/useCheckpoints.ts`, `context/useTreeNodes.ts`, or a `state/`
  subfolder — exact layout per Section 7.5).
- Decomposed god-components + new children/hooks under `components/Results/`,
  `components/Wizard/`, `components/Workflow/`, `components/Settings/`, and their
  `index.ts` barrels.
- **New** tests under the relevant `__tests__/` folders.
- Per-directory `README.md` files for any folder whose contents changed.
- Rebuilt bundle output under `ari-core/ari/viz/static/dist/` (git-ignored at
  `.gitignore:114`; produced by `npm run build`, not hand-edited).

Files that MUST NOT change in this subtask (delegated / frozen):
`services/api.ts` and `types/index.ts` (063); Settings IA/UX (070); any Python
under `ari-core/ari/viz/*.py`; `docs/`; `.github/workflows/`; directory names.

This planning document:
`docs/refactoring/subtasks/064_refactor_dashboard_state_and_component_boundaries.md`
(the only file created by the planning phase).

## 10. Files / APIs That Must Not Be Broken

- **Dashboard REST + WS contract** — every path/method/JSON-shape/status-code
  consumed via `services/api.ts` (863) and the WS message
  `{"type":"update","data":<tree>,"timestamp":...}` on `port+1`. 064 consumes
  it unchanged; it neither adds nor removes calls beyond re-grouping who calls
  them.
- **`services/api.ts` public function surface** — 064 imports these functions;
  their names/signatures are 063's to change, not 064's.
- **`types/index.ts` DTO shapes** (`AppState`, `Settings`, `Checkpoint`,
  `TreeNode`) — read-only here.
- **`/api/settings` flat 24-key save** (`SettingsPage.tsx:235-260`) — the object
  shape posted on Save must stay identical (per-phase model fields, etc.).
- **Route strings and defaults** — the 12 `PAGE_MAP` keys incl. `paperbench/*`
  sub-routes, the `new`→`wizard` alias, and `home` default must resolve exactly
  as before; the sidebar's visible entries and order stay the same.
- **i18n keys** (`i18n/en.ts`/`ja.ts`/`zh.ts`) — no key added/removed/renamed
  without three-locale parity (`check_i18n_js.py`).
- **`ari.viz` backend** and its served-bundle path
  (`ari-core/ari/viz/static/dist/`) — `test_dashboard_html.py` must still find
  the built bundle; CLI `ari` (`ari.cli:app`), `ari.public.*`, MCP tool
  contracts, checkpoint/config formats — all untouched by this FE subtask.
- **Per-directory README parity** and **git-ignored `node_modules/`** — keep the
  READMEs accurate and never track `node_modules/`.

## 11. Compatibility Constraints

- **Pixel- and traffic-identical.** After the refactor the rendered pages, the
  network requests (paths, cadence — incl. the 5s poll), and the WS handling
  must be indistinguishable from before. This is internal reorganization.
- **Facade-first migration.** Keep `useAppContext()` returning the current shape
  until all 9 consumers migrate to narrow hooks; never break a consumer's import
  in a single step. Each step must independently pass `npm run typecheck`,
  `npm test`, and `npm run build`.
- **No new external contract.** No new endpoints, no changed request bodies, no
  new global dependency. If any compatibility shim is ever needed (it should not
  be), document it inline; do not silently change behavior.
- **Do not use the term "deprecated"** for any internal FE code moved into hooks
  or child components — this is internal reorganization, not an external-contract
  deprecation. "Deprecated" is reserved for public API / CLI / MCP / dashboard
  API / documented import paths.
- **Settings boundary with 070.** Do not encroach on the Settings IA/UX redesign;
  if in doubt, defer SettingsPage section extraction to 070 and keep 064 to state
  consolidation, so the two subtasks do not conflict in Wave 5/6.

## 12. Tests to Run

Frontend gate (from `ari-core/ari/viz/frontend/`; `node`+`npm` available, **no
`pnpm`**):

```bash
npm ci                 # or npm install, if lockfile drift is expected
npm run typecheck      # tsc --noEmit — must pass with no new errors
npm test               # vitest run — existing + new component/state tests
npm run build          # vite build — must succeed; refreshes viz/static/dist/
```

Repo-wide gate (from `/home/t-kotama/workplace/ARI`; editable installs already
set up by `setup.sh`: `ari-skill-memory` then `ari-core`):

```bash
python -m compileall .   # syntax gate (no Python changed, but keep green)
ruff check .             # lint (ruff IS available; radon is NOT)
pytest -q                # full suite — must stay green
```

Backend test most sensitive to this FE subtask (asserts the built bundle
exists at `ari-core/ari/viz/static/dist/`):

```bash
pytest -q ari-core/tests/test_dashboard_html.py
```

Also run `scripts/run_all_tests.sh` for parity with CI if present, and the docs
gates that touch the frontend: `python scripts/docs/check_readme_parity.py` and
`python scripts/docs/check_i18n_js.py`. CI guard
`.github/workflows/refactor-guards.yml` must stay green (this FE-only change adds
no `~/.ari/` references and no `$HOME/.ari/` writes).

## 13. Acceptance Criteria

1. `npm run typecheck`, `npm test`, and `npm run build` all pass; `pytest -q`,
   `python -m compileall .`, and `ruff check .` show no new failures.
2. There is exactly **one** source of truth for the current route: the duplicate
   `currentPage`/`hashchange` pair (`App.tsx` vs `AppContext.tsx`) is gone,
   replaced by a single `useHashRoute` hook.
3. `PAGE_MAP` (`App.tsx`) and `NAV_ITEMS` (`Sidebar.tsx`) are derived from a
   single route manifest; route strings, the `new`→`wizard` alias, the
   `paperbench/*` sub-routes, and the sidebar's visible entries/order are
   unchanged.
4. `AppContext` is split into focused hooks/slices; consumers subscribe only to
   what they need; the 5s poll cadence and WS-first/poll-fallback semantics are
   preserved.
5. Each targeted god-component is reduced to a thin container + presentational
   children/hooks; no single component/file in the touched set exceeds the
   project's agreed size budget (set by 059; as a guideline, well under the
   current 1590/1160/1049/964/770 LOC).
6. Large local-state clusters (`WizardPage`, `SettingsPage`, `ResultsPage`,
   `StepResources`) are consolidated into reducers/hooks; the rendered UI and the
   `/api/settings` flat-object save are byte-identical.
7. New render/state tests cover `useHashRoute`, the route manifest, the split
   state hooks, and at least one interaction per decomposed god-component.
8. Per-directory `README.md` files are accurate for every changed folder;
   `check_readme_parity.py` and `check_i18n_js.py` pass; `node_modules/` stays
   untracked.
9. `services/api.ts` and `types/index.ts` are unchanged by 064 (owned by 063);
   Settings IA/UX is unchanged (owned by 070).

## 14. Rollback Plan

- The work is pure frontend reorganization behind a frozen wire contract and
  unchanged UX, so rollback is a `git revert` of the subtask's commits. Because
  each step (route hook, manifest, context split, per-component decomposition) is
  an independent, individually gated commit, a partial rollback (e.g. revert only
  one god-component's decomposition) is safe.
- Land incrementally per Section 8. The facade-first context migration means
  reverting a single consumer migration cannot break others. If the route-state
  unification (step 2) shows any navigation regression, revert to the dual
  `hashchange` listeners and re-derive from 059 before retrying.
- Rebuild the bundle (`npm run build`) after any revert so
  `test_dashboard_html.py` continues to find `viz/static/dist/`. There is no
  data/format migration (frontend holds no persisted state beyond the backend
  contract), so there is nothing to migrate back.

## 15. Dependencies

Consistent with the provided DEPENDENCY GRAPH (`059 -> 060, 061, 062, 063, 064,
065, 066`) and `docs/refactoring/007_subtask_index.md:111` (064 depends on 059,
Phase 5, High, Runtime = Yes):

- **Hard predecessor (fan-out gate): 059** `inventory_dashboard_frontend_backend_structure`.
  064 cannot start until 059 has inventoried the FE/BE structure, the state map,
  and the component list.
- **Required inventory gate: 060** `inventory_dashboard_api_contracts`. Per the
  master rule and `007_subtask_index.md:113-115`, the nine inventory subtasks
  (**001, 002, 020, 036, 045, 053, 059, 060, 067**) gate every runtime-code
  subtask; of these, **059** and **060** are the ones 064 directly relies on
  (state map + API contract), with **001**/**002** (architecture/complexity) as
  cross-cutting inputs.
- **Coordinates with (siblings under 059):** **063**
  `refactor_dashboard_frontend_api_client_and_types` — owns `services/api.ts` +
  `types/index.ts`; 064 consumes them and must not edit them, so sequence 064
  *after* or *alongside* 063 and inherit its client/error conventions. **061**
  `define_dashboard_dto_and_schema_policy` grounds the shapes 064's hooks
  consume. **065** `add_dashboard_contract_and_schema_tests` — 064's new
  component/state tests should slot into 065's harness. **066**
  `add_dashboard_build_and_ci_plan` — 064's `npm build/test` gate feeds the CI
  plan.
- **Boundary with Phase 6:** **067** `inventory_dashboard_visible_settings`,
  **068/069** (IA / progressive-disclosure design), **070**
  `refactor_dashboard_settings_panel`. The Settings UX/IA belongs to 067–070;
  064 must stay to structural state-clustering on `SettingsPage.tsx` (Section 3).
- Upstream policy inputs: **006** (target architecture), **010** (contract
  preservation), **008** (viz dashboard refactoring plan), **014** (dashboard UX
  plan — Phase-6 scope reference).

## 16. Risk Level

- **Does this subtask change runtime code? YES** — when executed it modifies and
  adds frontend TypeScript under `ari-core/ari/viz/frontend/src/` (state
  hooks/context, route manifest, god-component decomposition, tests) and
  regenerates the git-ignored production bundle. (This planning document itself
  changes no runtime code.)
- **Risk: HIGH** (consistent with `007_subtask_index.md:111`). Rationale: the
  frontend has **only two component tests today**, so large-scale decomposition
  starts with almost no FE regression net; the god-components are big
  (1590/1160/1049 LOC) and stateful; and the state layer feeds every page. The
  dominant risks are (a) subtle re-render / effect-timing regressions from
  splitting `AppContext` and unifying route state, and (b) accidental
  visible-UX or `/api/settings`-shape drift while decomposing `SettingsPage`.
  Mitigations: facade-first, incremental, per-commit gating with
  `npm run typecheck/test/build`; adding render/interaction tests *before or with*
  each decomposition (step 8); keeping `services/api.ts`/`types` and Settings UX
  out of scope; and rebuilding the bundle so `test_dashboard_html.py` guards the
  served artifact. Because the change is structural (same traffic, same pixels)
  rather than semantic, residual risk is reducible with discipline.

## 17. Notes for Implementer

- **Do not start before 059 (and 060) exist.** The component inventory and state
  map from 059, and the API-contract inventory from 060, are the reference. If
  they are not yet authored, stop and escalate rather than reverse-engineering
  the state graph from the components ad hoc.
- **Stay off 063's and 070's turf.** `services/api.ts` and `types/index.ts` are
  063's; the Settings information architecture / progressive disclosure /
  dangerous-surface gating (Raw JSON tab, `/api/env-keys` secret exposure at
  `services/api.ts:382` + `StepResources.tsx:333-342`, GPU-monitor SLURM
  auto-resubmit) are Phase-6 (070–072). 064 is *structural* only. If SettingsPage
  section extraction risks colliding with 070, do only the reducer consolidation
  and hand sections to 070.
- **Facade-first, always green.** Keep `useAppContext()` returning today's shape
  until every consumer migrates; never break a consumer import in one step.
- **Preserve route semantics exactly.** The `new`→`wizard` alias
  (`App.tsx:37`), the 3 `paperbench/*` sub-routes, the `home` default, and the
  query-string stripping in `parseHash` (`App.tsx:35`) must be reproduced by
  `useHashRoute` and the manifest.
- **Do not add react-router / Redux / Zustand / react-query / a CSS framework.**
  React primitives (`useReducer`/`useContext`/`useMemo`/custom hooks) are
  sufficient; a new dependency would change bundle size and deployment. If 059/061
  explicitly bless a dependency, follow that; otherwise stay minimal.
- **Imitate the `Tree/` pattern.** `DetailPanel.tsx` → `DetailPanelTabs/*` +
  `useDetailPanelData.ts` is the reference decomposition already in the repo;
  match its container/presentational/hook split and its `index.ts` barrel style.
- **Rebuild the bundle after changes.** `npm run build` refreshes
  `ari-core/ari/viz/static/dist/`, which `ari-core/tests/test_dashboard_html.py`
  asserts exists; a stale/missing bundle fails the backend suite.
- **Keep READMEs and i18n in parity.** Per-directory `README.md` files are
  gated (`scripts/docs/check_readme_parity.py`); locale files are gated
  (`scripts/docs/check_i18n_js.py`, note current minor drift en 444 vs ja/zh 441).
  Any manifest label-key change must land in all three locales.
- **`node_modules/` stays untracked.** It is git-ignored (`.gitignore:113`,
  112 MB on disk); `package-lock.json` **is** tracked — use `npm ci`, and never
  `git add node_modules`.
- **radon is not installed; ruff is; there is no `pnpm`.** Use `npm` for the FE
  and `ruff check .` for Python lint.
- **The "sonfigs" directory does not exist.** It is unrelated to the frontend;
  do not create or reference one.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **064** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
