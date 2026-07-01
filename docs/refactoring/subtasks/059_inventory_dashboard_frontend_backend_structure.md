# Subtask 059: Inventory Dashboard Frontend / Backend Structure

> Phase 5: Dashboard Frontend · Risk: Low · Runtime code change: **No** · Depends on: — (root inventory)
>
> Planning document only. Nothing here modifies runtime code, imports, prompts,
> configs, workflows, frontend source, or directory names. It hands a fresh coding
> session an executable plan to produce a **read-only structural inventory** of the
> ARI dashboard — both the React/TypeScript frontend (`ari-core/ari/viz/frontend/`)
> and the Python `http.server` backend (`ari-core/ari/viz/`) — as the architectural
> map that the whole Phase-5 and Phase-6 fan-out (**060–073**) consumes. All paths and
> line counts are repository-real, verified against the tree at planning date
> 2026-07-01 (ari-core `0.9.0`, branch `main`).

## 1. Goal

Produce a **complete, diff-friendly inventory of the dashboard's code structure** —
not its wire contract (that is subtask **060**), but the *shape of the codebase*: the
directory layout, module/component tree with per-file LOC, the routing mechanism, the
state-management approach, the build/test tooling, the styling system, the i18n
layout, and — critically — the **frontend↔backend structural boundary** (which React
feature area consumes which `ari-core/ari/viz/*.py` handler group). Concretely, 059
delivers one reference artifact that a fresh session can use to plan every downstream
refactor without re-deriving the topology, enumerating for each unit:

1. the file path and current LOC,
2. its role (page / feature component / shared component / hook / context / service /
   type module / i18n / style / backend handler / backend infra),
3. its feature area (Home, Experiments, Monitor, Tree, Results, Wizard, PaperBench,
   Idea, Workflow, Settings, Layout, common) and the backend module(s) it pairs with,
4. its structural problems (god-component, inline styling, mixed concerns) as a
   **recommendation** with a KEEP / ADAPT / MERGE / MOVE_TO_LEGACY /
   DELETE_CANDIDATE / REVIEW_REQUIRED classification.

This inventory is the **frozen structural baseline** that subtasks 060–066 (Phase 5)
and 067–073 (Phase 6) build on. 059 writes **no runtime code**; its only output is a
reference document under `docs/refactoring/reports/`. Per
`docs/refactoring/007_subtask_index.md:106,125`, 059 is one of the nine inventory
subtasks (001, 002, 020, 036, 045, 053, **059**, 060, 067) that MUST precede any
runtime code change, and per `007_subtask_index.md:257` "Everything fans out from 059".

## 2. Background

The dashboard is a two-tier app under `ari-core/ari/viz/`:

- **Backend** (`ari-core/ari/viz/`, 27 `.py` files, 8131 LOC total): a Python stdlib
  `http.server` app — **no Flask/FastAPI/aiohttp**. `server.py` (201 LOC) starts three
  threads (filesystem watcher, HTTP server, asyncio WebSocket loop on `port+1`);
  `routes.py` (1197 LOC) is a single `BaseHTTPRequestHandler` subclass whose dispatch
  is a giant if/elif chain; handlers live in `api_*.py` modules. This backend
  structure is inventoried at the **wire level** by subtask 020
  (`docs/refactoring/subtasks/020_inventory_viz_dashboard_api_contracts.md`) and by
  the Phase-4 plan `docs/refactoring/008_viz_dashboard_refactoring_plan.md`. **059 does
  not re-derive the wire contract**; it records the *module structure* and how the
  frontend feature areas map onto those backend modules.

- **Frontend** (`ari-core/ari/viz/frontend/`): Vite 5 + React 18.3 + TypeScript 5.5,
  ESM (`"type":"module"` in `package.json:5`). Dependencies are deliberately minimal —
  `react`, `react-dom`, `d3` (^7.9), `reactflow` (^11.11); tests via Vitest 2 +
  Testing Library + jsdom (`package.json:14-32`). Scripts: `dev`, `build`, `typecheck`,
  `preview`, `test`, `test:watch` (`package.json:6-13`). There is **no CSS framework**
  and **no react-router**, **no Redux/Zustand/react-query**.

The frontend is organized by **feature directory** under `src/components/` (12 feature
folders + `common/`), each with its own `index.ts` barrel and per-directory
`README.md`. There is **no `src/pages/` directory** — pages are the top-level component
in each feature folder (e.g. `Home/HomePage.tsx`, `Settings/SettingsPage.tsx`).
Routing is a **hand-rolled hash router** in `App.tsx` (94 LOC): `parseHash()`
(`App.tsx:32-39`) + a `PAGE_MAP` of 14 keys (`App.tsx:41-56`) with every page
`lazy()`-loaded under `Suspense`. Global state is a **single React Context**
(`context/AppContext.tsx`, 120 LOC) that 5s-polls `/state` + `/checkpoints`
(`AppContext.tsx:34` `STATE_POLL_MS = 5000`) and subscribes to the WebSocket via
`hooks/useWebSocket.ts` (97 LOC, `wsPort = httpPort + 1` at `:42`).

Two companion Phase-4/Phase-6 planning documents already exist and are **cross-
references, not duplicates**: `docs/refactoring/008_viz_dashboard_refactoring_plan.md`
(backend structure) and `docs/refactoring/014_dashboard_ux_refactoring_plan.md`
(frontend UX). 059 supplies the structural map that both the API refactors (062/063)
and the UX refactors (070–073) consume.

## 3. Scope

In scope (read-only inventory production):

- **Frontend directory topology.** Enumerate every directory under
  `ari-core/ari/viz/frontend/src/` (`components/` and its 13 subfolders, `context/`,
  `hooks/`, `i18n/`, `services/`, `styles/`, `types/`) and the top-level files
  (`App.tsx`, `main.tsx`, `README.md`, `vite-env.d.ts`) plus the build config files
  (`package.json`, `package-lock.json`, `tsconfig.json`, `vite.config.ts`,
  `vitest.config.ts`, `vitest.setup.ts`, `index.html`).
- **Per-file LOC + role table.** Record every `.tsx`/`.ts` file with its LOC and its
  role, ranked by size. The verified worst offenders are `Results/resultSections.tsx`
  **1590**, `Wizard/StepResources.tsx` **1160**, `Settings/SettingsPage.tsx` **1049**,
  `Workflow/WorkflowPage.tsx` **964**, `services/api.ts` **863**, `Workflow/
  workflowNodes.tsx` **770**.
- **Routing inventory.** Record the hash-router mechanism (`App.tsx:32-56`), the 14
  `PAGE_MAP` keys, the legacy `new`→`wizard` alias (`App.tsx:37,47-48`), and the
  Sidebar nav mirror (`Layout/Sidebar.tsx:12-23`, 10 `NAV_ITEMS`) — including the
  **route drift** between them (see §6).
- **State-management inventory.** Record the single `AppContext` (`context/
  AppContext.tsx`), its 5s polling of `/state`+`/checkpoints`, the WebSocket hook
  (`hooks/useWebSocket.ts`), the generic `hooks/useApi.ts` (42 LOC), and the pattern of
  large per-component `useState` clusters (e.g. SettingsPage ~30 hooks).
- **Styling inventory.** Record the **corrected** styling structure: `styles/
  dashboard.css` is a 14-line **manifest** that `@import`s five topic files —
  `tokens.css` (58), `layout.css` (23), `components.css` (73), `widgets.css` (90),
  `responsive.css` (142) — introduced in the v0.7.0 "Phase B" split
  (`styles/dashboard.css:3-8`), plus pervasive inline `style={{}}` objects across
  components.
- **i18n inventory.** Record `i18n/{en,ja,zh}.ts` + `index.ts` and the key-count drift
  (`en.ts` 444 vs `ja.ts`/`zh.ts` 441).
- **Backend structure inventory (module level, not wire level).** Record the 27
  `ari-core/ari/viz/*.py` files with LOC, grouped into: dispatch/infra (`server.py`,
  `routes.py`, `websocket.py`, `state.py`, `state_sync.py`, `api_state.py` facade,
  `api_wizard.py` dead `WIZARD_ROUTES`), and endpoint-owning `api_*`/helper modules.
- **Frontend↔backend mapping.** For each frontend feature area, record which backend
  handler group(s) it consumes (derived from `services/api.ts` URLs → `routes.py`
  dispatch → owning `api_*` module). This is the load-bearing deliverable that 062/063
  need to co-refactor safely.
- **Classification.** Attach KEEP/ADAPT/MERGE/MOVE_TO_LEGACY/DELETE_CANDIDATE/
  REVIEW_REQUIRED to each unit **as a recommendation only** — 059 changes nothing.

## 4. Non-Goals

- **Do not** modify any file under `ari-core/ari/viz/` (backend or `frontend/`). 059 is
  read-only; the whole point is a frozen baseline captured from an unmodified tree.
- **Do not** re-produce the **wire-contract** inventory (HTTP method/path/request/
  response/CORS/`_status` per endpoint). That is subtask **020** (already done for the
  backend view) and subtask **060** (the FE-side `services/api.ts` contract view). 059
  records *structure and mapping*, referencing 020/060 for the wire detail rather than
  duplicating it.
- **Do not** implement any refactor: not the routes→services extraction (**062**), the
  FE API-client/types refactor (**063**), the state/component-boundary decomposition
  (**064**), the DTO/schema policy (**061**), the contract/schema tests (**065**), the
  build/CI plan (**066**), or any Phase-6 UX work (**067–073**).
- **Do not** do the **visible-settings** inventory (the 9 `<Card>` SettingsPage
  sections + 24-key flat save) — that is subtask **067**; 059 records only that
  `SettingsPage.tsx` is a 1049-LOC god-component, and points to 067 for the section
  breakdown.
- **Do not** change any per-directory `README.md` under `frontend/`, nor
  `docs/refactoring/008_*.md`, `014_*.md`, or `007_subtask_index.md`; cross-reference
  them.
- **Do not** "clean up" `node_modules/` (it is **not** committed — see §11), nor add or
  bump any npm dependency, nor touch `package-lock.json`.
- **Do not** touch `ari.public.*`, the CLI, MCP `ari-skill-*` servers, or checkpoint/
  config formats. None are part of the dashboard structure 059 inventories.
- **Do not** "fix" the structural hazards found (god-components, route drift, i18n key
  drift, inline styling, dangerous raw/debug UI). Record them as classified findings
  for the downstream subtasks; resolving them is out of scope here.

## 5. Current Files / Directories to Inspect

All paths are under `/home/t-kotama/workplace/ARI`.

### 5.1 Frontend build/config (root of `ari-core/ari/viz/frontend/`)

- `package.json` — scripts (`:6-13`) + minimal deps (`:14-32`); `name:"ari-dashboard"`,
  `version:"1.0.0"`, `private:true`, `type:"module"`.
- `package-lock.json` (140 KB, **tracked**), `tsconfig.json`, `vite.config.ts`,
  `vitest.config.ts`, `vitest.setup.ts`, `index.html`, `README.md`.
- `node_modules/` (112 MB on disk, **git-ignored**, 0 tracked files — see §11).

### 5.2 Frontend top-level (`ari-core/ari/viz/frontend/src/`)

- `App.tsx` (94) — hash router: `parseHash()` (`:32-39`), `PAGE_MAP` 14 keys
  (`:41-56`), `Router()` (`:60-84`), `lazy()`+`Suspense` (`:7-28,73-81`).
- `main.tsx` (40) — mount + `ErrorBoundary` (prints full stack to page, `:17-25`;
  raw `innerHTML` at `:38`).
- `vite-env.d.ts` (2), `README.md` (8342 bytes).

### 5.3 Frontend feature components (`src/components/`, LOC verified)

Ranked by LOC (top offenders first). Every folder has `index.ts` + `README.md`.

- `Results/` — `resultSections.tsx` **1590**, `PaperWorkspace.tsx` 519,
  `ResultsPage.tsx` 462, `RubricTreeVisualization.tsx` 462, `EarSection.tsx` 439,
  `resultHelpers.ts` 169, `PublishYamlEditor.tsx` 162, `resultTypes.ts`, `useEAR.ts`.
- `Wizard/` — `StepResources.tsx` **1160**, `StepGoal.tsx` 528, `StepScope.tsx` 424,
  `stepResourcesSections.tsx` 407, `StepLaunch.tsx` 399, `WizardPage.tsx` 352.
- `Settings/` — `SettingsPage.tsx` **1049** (god-component), `settingsConstants.ts`.
- `Workflow/` — `WorkflowPage.tsx` 964, `workflowNodes.tsx` 770.
- `Tree/` — `DetailPanel.tsx` 425, `FileExplorer.tsx` 393, `TreeVisualization.tsx` 366,
  `TreePage.tsx` 206, `useDetailPanelData.ts` 204, `detailPanelHelpers.ts`, and
  `DetailPanelTabs/` (`AccessTab.tsx` 155, `MemoryEntryCard.tsx` 131, `ReportTab.tsx`
  126, `MemoryTab.tsx` 113, `TraceTab.tsx`, `CodeTab.tsx`, `README.md`).
- `Monitor/` — `MonitorPage.tsx` 502, `monitorSections.tsx` 366, `GpuMonitor.tsx` 129,
  `PhaseStepper.tsx` 113.
- `PaperBench/` — `PaperBenchWizard.tsx` 412, `PaperImportDialog.tsx` 254,
  `PaperRegistryPage.tsx` 147, `results/ResultsView.tsx` 390, empty `steps/`, and
  `__tests__/` (`PaperImportDialog.test.tsx` 138, `PaperBenchWizard.test.tsx` 118).
- `Idea/IdeaPage.tsx` 478; `Experiments/ExperimentsPage.tsx` 189; `Home/HomePage.tsx`
  122; `Layout/` (`Layout.tsx`, `Sidebar.tsx` 191); `common/` (`Badge`, `Button`,
  `Card`, `StatBox`, `StatusBadge`, `index.ts`).
- Total under `src/components/`: **15931 LOC** across `.tsx`/`.ts`.

### 5.4 Frontend cross-cutting (`src/`)

- `services/api.ts` (863) — ~90 typed fetch wrappers, `API_BASE=''`; `services/
  websocket.ts` (5, re-export).
- `context/AppContext.tsx` (120) — single global store, 5s poll (`:34`).
- `hooks/useWebSocket.ts` (97, `wsPort=httpPort+1` `:42`); `hooks/useApi.ts` (42).
- `i18n/en.ts` (444), `ja.ts` (441), `zh.ts` (441), `index.ts` (40).
- `types/index.ts` (264) — `Settings`, `AppState`, `Checkpoint`, `TreeNode`, etc.
- `styles/` — `dashboard.css` (14, manifest), `tokens.css` (58), `layout.css` (23),
  `components.css` (73), `widgets.css` (90), `responsive.css` (142).

### 5.5 Backend structure (`ari-core/ari/viz/`, 27 `.py`, LOC verified)

- Dispatch/infra: `routes.py` (1197), `server.py` (201), `websocket.py` (36),
  `state_sync.py` (117), `state.py` (79), `api_state.py` (76, thin re-export facade),
  `api_wizard.py` (35, **unused** `WIZARD_ROUTES`), `ui_helpers.py` (183),
  `__init__.py` (28), `README.md`.
- Endpoint-owning: `api_experiment.py` (929), `api_paperbench.py` (813),
  `api_settings.py` (553), `api_workflow.py` (462), `ear.py` (452), `checkpoint_api.py`
  (327), `api_orchestrator.py` (321), `api_paperbench_worker.py` (319), `file_api.py`
  (307), `api_tools.py` (259), `node_work_api.py` (233), `api_memory.py` (227),
  `api_fewshot.py` (221), `checkpoint_lifecycle.py` (205), `api_process.py` (205),
  `api_publish.py` (191), `api_ollama.py` (90), `checkpoint_finder.py` (65).

### 5.6 Cross-reference docs (do not edit)

- `docs/refactoring/subtasks/020_inventory_viz_dashboard_api_contracts.md` (backend
  wire contract), `docs/refactoring/008_viz_dashboard_refactoring_plan.md`,
  `docs/refactoring/014_dashboard_ux_refactoring_plan.md`,
  `docs/refactoring/007_subtask_index.md` (entries `:106-120,257-271`).
- Output location for the inventory artifact: `docs/refactoring/reports/` (sibling to
  existing report files). The inventory is a **new reference file** (see §9), not a
  code change.

## 6. Current Problems

Reasons the structural inventory must exist before any Phase-5/6 refactor. These are
findings to **record**, not to fix in 059.

1. **God-components with mixed concerns.** `Results/resultSections.tsx` (1590; 6
   exported render-fns including a ~460-line `renderReviewScores`),
   `Wizard/StepResources.tsx` (1160; single component + ~25 `useState` + ORS config),
   and `Settings/SettingsPage.tsx` (1049; all 9 sections inline, no tabs) each mix
   data-fetch, business logic, and presentation. These are the decomposition targets
   for 064 (state/component boundaries) and 070 (settings panel). 059 must record the
   exact per-file LOC so a diff can prove decomposition happened.
2. **No route table; router/nav drift.** Routing is a hand-rolled hash router
   (`App.tsx:32-56`). `PAGE_MAP` has **14 keys** (incl. `new`+`wizard` alias and 3
   `paperbench/*` sub-routes) but `Layout/Sidebar.tsx:12-23` mirrors only **10**
   `NAV_ITEMS` — the two lists are hand-maintained and can drift (Sidebar uses `new`,
   omits the `wizard` alias and the `paperbench/import|run|results` sub-routes). Record
   this as a REVIEW_REQUIRED structural risk for 064/068.
3. **Single-context global state, coarse polling.** All shared state lives in one
   `AppContext` (`context/AppContext.tsx`) that 5s-polls `/state`+`/checkpoints`
   (`:34`) and layers a WebSocket on top (`useWebSocket.ts`). There is no
   Redux/Zustand/react-query; components hold large local `useState` clusters
   (SettingsPage ~30). This coupling is what 064 must untangle; record the store shape.
4. **Inline styling everywhere.** Despite the v0.7.0 CSS split into 6 topic files
   (`styles/dashboard.css:3-8`), components still use pervasive inline `style={{}}`
   objects. Record this as a MERGE/ADAPT recommendation (consolidate into the token/
   widget CSS) for downstream UX work, not to fix here.
5. **i18n key drift.** `i18n/en.ts` is 444 lines vs `ja.ts`/`zh.ts` at 441 each — a
   3-line divergence. `scripts/docs/check_i18n_js.py` only covers the **landing JS**,
   not these React `i18n/*.ts` files (`007_subtask_index.md:289-290`), so drift is
   currently unchecked. Record as REVIEW_REQUIRED for 073.
6. **Frontend↔backend structure is undocumented.** No single artifact maps a React
   feature area (e.g. `Wizard/`) to its backend handler group (e.g. `api_experiment` +
   `api_tools` + `api_workflow`). 062 (backend routes→services) and 063 (FE API client)
   must co-refactor across this boundary; without 059's map they risk splitting one
   side without the other.
7. **Dangerous / raw-debug surfaces embedded in the structure.** The inventory should
   flag (for 071's developer-mode gate) the raw/debug UI baked into components:
   DetailPanel "Raw" JSON tab (`Tree/DetailPanel.tsx`), `/api/env-keys` secret exposure
   consumed by `StepResources.autoReadApiKey`, GPU-monitor "SLURM Auto-Resubmit"
   (`Monitor/GpuMonitor.tsx`), `dangerouslySetInnerHTML` in `Wizard/StepScope.tsx`, and
   raw `JSON.stringify` dumps in `monitorSections.tsx`/`resultSections.tsx`. 059 records
   *where they live*; 071/072 decide what to gate.
8. **Backend dispatch has no structure to mirror.** The backend is a 1197-LOC if/elif
   `routes.py` with an abandoned `WIZARD_ROUTES` (`api_wizard.py:35`) and an
   `api_state.py` facade — recorded in detail by 020. 059 records only the module map
   so the FE inventory has a symmetric backend counterpart; classify `WIZARD_ROUTES`
   DELETE_CANDIDATE (consistent with 020).

## 7. Proposed Design / Policy

059 produces **one structural inventory artifact** plus a short findings section. No
runtime classification changes anything; classifications are *recommendations*
consumed by 060–073.

### 7.1 Inventory format

Emit a diff-friendly reference file (recommended:
`docs/refactoring/reports/dashboard_structure_inventory.md`, optionally with a
companion `.json` twin if 065/066 prefer machine-readable data). Two tables plus a
mapping table:

**Table A — Frontend units.** One row per `.tsx`/`.ts`/`.css` file:

| field | source of truth |
|---|---|
| `path` | file path under `ari-core/ari/viz/frontend/src/` |
| `loc` | `wc -l` of the file |
| `role` | page / feature-component / shared-component / hook / context / service / type / i18n / style / test |
| `feature_area` | Home / Experiments / Monitor / Tree / Results / Wizard / PaperBench / Idea / Workflow / Settings / Layout / common / cross-cutting |
| `structural_flags` | god-component (>500 LOC), inline-styling, raw-debug-UI, mixed-concerns, dead-route |
| `classification` | KEEP / ADAPT / MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED |

**Table B — Backend modules.** One row per `ari-core/ari/viz/*.py`:

| field | source of truth |
|---|---|
| `path` | file path under `ari-core/ari/viz/` |
| `loc` | `wc -l` |
| `role` | dispatch / infra / facade / endpoint-owner / helper |
| `handler_group` | State/tree, Checkpoints/files, Experiment, Settings/workflow, PaperBench, Tools/wizard, Orchestrator, Memory, EAR, Publish, Fewshot, Process/GPU, Ollama/container |
| `classification` | (as above; consistent with subtask 020) |

**Table C — Frontend↔backend map.** One row per frontend feature area → backend
handler group(s) it consumes, derived by pairing `services/api.ts` URLs to `routes.py`
dispatch branches. Example rows (verified consumers, to be completed exhaustively):
`Settings/` → `api_settings`+`api_memory`+`api_process`(gpu)+`api_ollama`(container);
`Wizard/` → `api_tools`(chat-goal/config/upload/ssh)+`api_experiment`(launch/run-stage)
+`api_workflow`(skills/profiles/scheduler)+`api_settings`(env-keys); `Tree/` →
`checkpoint_api`+`file_api`+`node_work_api`+`state_sync`(WS); `Results/` → `ear`+
`api_publish`+`api_fewshot`+`checkpoint_api`; `PaperBench/` → `api_paperbench`+
`api_paperbench_worker`; `Monitor/` → `api_process`+`api_experiment`(logs SSE)+
`api_orchestrator`; `Workflow/` → `api_workflow`.

### 7.2 Cross-cutting sections to capture

- **Routing:** the 14 `PAGE_MAP` keys, the `new`→`wizard` alias, the 10 Sidebar
  `NAV_ITEMS`, and the enumerated drift between them.
- **State:** the single `AppContext` store fields, the 5s poll targets, the WebSocket
  hook, `useApi.ts`, and a note on per-component `useState` density.
- **Build/test tooling:** Vite 5, TS 5.5, Vitest 2, the 6 npm scripts, the minimal
  dep set, and the fact that **npm only** (no `pnpm`) is available.
- **Styling:** the manifest+5-topic CSS split and the inline-style prevalence.
- **i18n:** the 3 locale files + index and the key-count drift.

### 7.3 Extraction method (deterministic, no code change)

- Derive Table A/B by static reading + `wc -l` of the tree (a throwaway analysis
  script under the scratchpad is fine; **only the resulting artifact is committed**).
- Derive Table C by listing every `get(`/`post(`/`pbGet(`/`pbPost(` URL in
  `services/api.ts` and pairing each to the owning `routes.py` branch → `api_*` module
  (cross-check against subtask 020's endpoint inventory rather than re-deriving wire
  detail). Any FE URL with no backend branch (or vice versa) is a **drift finding** —
  record it; do not resolve it.
- Do **not** add a checker to `scripts/` — the dashboard UX/schema checkers are
  subtasks 065/066/073 (`check_viz_api_schema.py`, `check_dashboard_ux.py`).

## 8. Concrete Work Items

1. **Enumerate frontend files.** `wc -l` every `.tsx`/`.ts`/`.css` under
   `ari-core/ari/viz/frontend/src/`; populate Table A with role, feature area, and
   structural flags. Confirm the god-component set (`resultSections.tsx` 1590,
   `StepResources.tsx` 1160, `SettingsPage.tsx` 1049, `WorkflowPage.tsx` 964,
   `api.ts` 863, `workflowNodes.tsx` 770).
2. **Enumerate backend modules.** `wc -l` every `ari-core/ari/viz/*.py`; populate
   Table B with role + handler group; mark `api_state.py` as facade, `api_wizard.py`
   `WIZARD_ROUTES` as DELETE_CANDIDATE (consistent with 020).
3. **Record the routing inventory.** From `App.tsx:32-56` and `Layout/Sidebar.tsx:12-23`:
   the 14 `PAGE_MAP` keys, the `new`→`wizard` alias, the 10 `NAV_ITEMS`, and the
   explicit drift list.
4. **Record the state inventory.** From `context/AppContext.tsx` and `hooks/`: store
   fields, `STATE_POLL_MS=5000` (`:34`), poll targets (`/state`, `/checkpoints`), WS
   fallback to `state.nodes`, `useApi.ts`, per-component `useState` density note.
5. **Record the styling inventory.** From `styles/dashboard.css:3-8` and its 5
   `@import`s: the manifest+topic split and the inline-style prevalence.
6. **Record the i18n inventory.** `i18n/{en,ja,zh}.ts` LOC (444/441/441) + drift; note
   that `check_i18n_js.py` does not cover these files.
7. **Record the build/test tooling.** `package.json` scripts + deps; Vite/Vitest
   versions; npm-only.
8. **Build Table C (FE↔BE map).** Pair every `services/api.ts` URL to its backend
   handler group; produce per-feature-area → backend-module rows; list any drift.
9. **Record raw/debug-UI locations** (for 071): DetailPanel Raw tab, `/api/env-keys`
   consumers, GPU auto-resubmit, `dangerouslySetInnerHTML` (`Wizard/StepScope.tsx`),
   raw `JSON.stringify` dumps.
10. **Assign classifications** (KEEP/ADAPT/MERGE/MOVE_TO_LEGACY/DELETE_CANDIDATE/
    REVIEW_REQUIRED) per row as recommendations for 060–073. Default KEEP
    (structure-preserved); god-components → ADAPT (decompose behind unchanged
    behavior); `WIZARD_ROUTES` → DELETE_CANDIDATE; router/nav drift + i18n drift →
    REVIEW_REQUIRED.
11. **Write the artifact** to `docs/refactoring/reports/dashboard_structure_inventory.md`
    (optionally a `.json` twin). Cross-link 008/014/020 in prose only (do not edit).
12. **Self-check counts.** Confirm 27 backend `.py` files / 8131 LOC and the
    `src/components/` total (15931 LOC) against the live tree; confirm every
    `services/api.ts` URL is mapped to a backend module.

## 9. Files Expected to Change

059 changes **no runtime code**. The only files it creates/edits:

- `docs/refactoring/subtasks/059_inventory_dashboard_frontend_backend_structure.md` —
  this planning document.
- **New (produced when the subtask is executed):**
  `docs/refactoring/reports/dashboard_structure_inventory.md` — the inventory artifact
  (and optionally `docs/refactoring/reports/dashboard_structure_inventory.json`).

Explicitly **not** changed (read-only inputs): everything under `ari-core/ari/viz/`
(all 27 backend `.py` files and the entire `frontend/` tree — components, hooks,
context, services, styles, types, i18n, config, and every per-directory `README.md`),
`docs/refactoring/008_*.md`, `docs/refactoring/014_*.md`,
`docs/refactoring/020_*.md`, `docs/refactoring/007_subtask_index.md`, `scripts/**`,
`.github/workflows/**`, `package.json`, `package-lock.json`.

## 10. Files / APIs That Must Not Be Broken

Because 059 is read-only, "must not be broken" means the inventory must faithfully
record — never alter — these contracts. (059 touches none of them; it only maps them.)

- **Dashboard HTTP + WebSocket API** (`ari-core/ari/viz/routes.py` + `api_*.py` +
  `websocket.py`): the wire contract frozen by subtask 020. 059 records module
  structure only.
- **Frontend consumer contract**: `services/api.ts` wrapper URLs and the two error
  regimes (`get`/`post` throw vs. `pbGet`/`pbPost` no-throw), plus `types/index.ts`
  shapes (`Settings`, `AppState`). Detailed by subtask 060; 059 does not change them.
- **`/api/settings` flat-object contract + the `Settings` type** — the Phase-6 settings
  refactor (070) must preserve these; 059 records that `SettingsPage.tsx` is a
  god-component but does not touch the contract.
- **Hash-router route keys** (`App.tsx` `PAGE_MAP`, including the `new`→`wizard` legacy
  alias) — external bookmarks/links depend on them; record, do not change.
- **The `wsPort = httpPort + 1` derivation** (`useWebSocket.ts:42` ↔ `server.py`
  `ws_serve` on `port+1`) — load-bearing; record, do not change.
- **Frontend build outputs** consumed by the server: `vite.config.ts` build target and
  the `viz/static/` dist path (the server serves the built bundle). 059 changes no
  build config.
- Out-of-band but must not be incidentally touched: **CLI `ari`**, **`ari.public.*`**,
  **MCP `ari-skill-*` tool contracts**, **checkpoint/output/config file formats**,
  **README/docs usage**, **scripts called by `.github/workflows`**.

## 11. Compatibility Constraints

- 059 is **inventory only** — there is nothing to make compatible, because no runtime
  behavior changes. The compatibility obligation is *forward*: the artifact must be
  accurate enough that 062/063/064/070 can prove they preserved the frontend↔backend
  boundary against it.
- Record structure **as it is**, including the hazards (god-components, router/nav
  drift, i18n key drift, inline styling, raw-debug UI). Recording them is not endorsing
  them; do not "normalize" the tree in the inventory.
- **`node_modules/` correction (do not act on it):** `node_modules/` is **not**
  committed. `.gitignore:113` ignores
  `ari-core/ari/viz/frontend/node_modules/` and `git ls-files` returns 0 matches under
  it; it exists on disk (~112 MB) as a normal working install, and `package-lock.json`
  (140 KB) **is** tracked. The earlier "committed node_modules" skeleton claim is false
  for the current tree — record the corrected state, change nothing.
- **`styles/` correction:** the "single `dashboard.css`" skeleton claim is stale.
  `dashboard.css` (14 LOC) is a manifest that `@import`s `tokens/layout/components/
  widgets/responsive.css` (v0.7.0 split, `styles/dashboard.css:3-8`). Record the real
  6-file structure.
- No `pyproject.toml`, `requirements*.txt`, workflow, prompt, or config file is
  touched. There is **no** top-level `pyproject.toml` (the core manifest is
  `ari-core/pyproject.toml`, not touched). The prompt's "sonfigs" directory does **not
  exist** in this repo (the confusable trio is `ari-core/ari/config/` [code] vs.
  `ari-core/ari/configs/` [packaged defaults] vs. top-level `ari-core/config/` [rubric
  data]) — irrelevant to the dashboard structure and not referenced by the inventory.
- The word "deprecated" is reserved for external contracts. Internal dead code found
  during inventory (e.g. `WIZARD_ROUTES`, `api_wizard.py:35`) is classified
  DELETE_CANDIDATE, **not** "deprecated".

## 12. Tests to Run

059 produces documentation/data, so the test surface is a **sanity/lint gate**, not a
behavior gate. From repo root (`/home/t-kotama/workplace/ARI`):

- `python -m compileall ari-core/ari/viz` — confirms the read-only inspection did not
  corrupt any backend source (should be a no-op). Before considering the subtask
  complete, also run `python -m compileall .`.
- `pytest -q` — full core suite must still pass unchanged. The viz-heavy suites
  `ari-core/tests/test_server.py` (1844), `test_gui_errors.py` (1650),
  `test_workflow_contract.py` (1606), `test_wizard.py` (1133) exercise the very
  endpoints and pages whose structure is inventoried; a green run confirms the baseline
  the inventory describes is the live one. No test should need modification.
- `ruff check .` — ruff is available (radon is not); expect no lint changes (no `.py`
  edited).
- **Frontend** (structure inventoried, not changed): from
  `ari-core/ari/viz/frontend/`, run `npm run typecheck`, `npm test` (Vitest), and
  optionally `npm run build` — all should pass unchanged; they confirm the tree the
  inventory describes still type-checks, tests green, and builds. `npm` is available
  (no `pnpm`). No frontend file is edited by 059.
- **Docs guards** for the new report file: `python scripts/docs/check_doc_links.py` and
  `python scripts/docs/check_doc_sources.py` (the inventory is a tracked doc; ensure
  its links/source references resolve). Confirm `.github/workflows/refactor-guards.yml`
  invariants still hold (no new `~/.ari` references introduced by the doc).

## 13. Acceptance Criteria

1. `docs/refactoring/reports/dashboard_structure_inventory.md` exists and contains
   **Table A** (every frontend `.tsx`/`.ts`/`.css` under `src/` with LOC, role, feature
   area, structural flags, classification), **Table B** (every backend
   `ari-core/ari/viz/*.py` with LOC, role, handler group, classification), and
   **Table C** (each frontend feature area → backend handler group(s)).
2. The god-component set is recorded with exact LOC (`resultSections.tsx` 1590,
   `StepResources.tsx` 1160, `SettingsPage.tsx` 1049, `WorkflowPage.tsx` 964,
   `api.ts` 863, `workflowNodes.tsx` 770).
3. The routing inventory records the 14 `PAGE_MAP` keys, the `new`→`wizard` alias, the
   10 Sidebar `NAV_ITEMS`, and the enumerated router/nav drift.
4. The state inventory records the single `AppContext`, `STATE_POLL_MS=5000`, poll
   targets, the WebSocket hook + `port+1` derivation, and per-component `useState`
   density.
5. The styling inventory records the corrected 6-file CSS structure (manifest +
   tokens/layout/components/widgets/responsive) and inline-style prevalence; the i18n
   inventory records the 444/441/441 key drift.
6. The build/test tooling inventory records Vite 5, TS 5.5, Vitest 2, the 6 npm
   scripts, the minimal dep set, and npm-only.
7. Raw/debug-UI locations are recorded (DetailPanel Raw tab, `/api/env-keys` consumers,
   GPU auto-resubmit, `dangerouslySetInnerHTML`, raw `JSON.stringify` dumps) as input
   for 071.
8. Every unit carries a classification (KEEP/ADAPT/MERGE/MOVE_TO_LEGACY/
   DELETE_CANDIDATE/REVIEW_REQUIRED) as a downstream recommendation; `WIZARD_ROUTES`
   is DELETE_CANDIDATE.
9. Self-check counts match the live tree (27 backend `.py` / 8131 LOC; `src/components/`
   15931 LOC); every `services/api.ts` URL is mapped to a backend module.
10. `python -m compileall .`, `pytest -q`, and `ruff check .` are clean; frontend
    `npm run typecheck` + `npm test` pass; `git status` shows only the two docs
    (`059_*.md` + the report), with no runtime file diff.

## 14. Rollback Plan

Trivial and risk-free: 059 adds documentation only. Rollback is `git rm`/`git revert`
of the two doc files:

1. Delete `docs/refactoring/reports/dashboard_structure_inventory.md` (and the optional
   `.json` twin).
2. Revert this planning document if it was committed.

No runtime code, format, migration, build config, or workflow is touched, so there is
nothing to un-migrate and no way for rollback to affect the running dashboard.
Downstream subtasks (060–073) that consumed the inventory simply lose their structural
baseline until it is regenerated.

## 15. Dependencies

- **Predecessors: none.** 059 is a **root inventory subtask** in the dependency graph
  (no `X -> 059` edge; `007_subtask_index.md:106` lists Depends-on `—`). It can start
  immediately and is itself one of the nine inventory subtasks (001, 002, 020, 036,
  045, 053, **059**, 060, 067) that MUST precede any runtime code change
  (`007_subtask_index.md:125`).
- **Dependents (this subtask gates them):** the full Phase-5 and Phase-6 fan-out —
  graph edges `059 -> 060`, `059 -> 061`, `059 -> 062`, `059 -> 063`, `059 -> 064`,
  `059 -> 065`, `059 -> 066` and `059 -> 067`, `059 -> 068`, `059 -> 069`, `059 -> 070`,
  `059 -> 071`, `059 -> 072`, `059 -> 073` (`007_subtask_index.md:438-451`).
  Concretely:
  - **060** `inventory_dashboard_api_contracts` — FE-side `services/api.ts` contract
    inventory (~90 wrappers, two error regimes); itself a required inventory gate.
  - **061** `define_dashboard_dto_and_schema_policy` — grounds 062/063/065.
  - **062** `refactor_dashboard_backend_routes_to_services` (High risk, runtime yes) —
    dashboard API contract ADAPT.
  - **063** `refactor_dashboard_frontend_api_client_and_types` (High, runtime yes) — FE
    API contract ADAPT.
  - **064** `refactor_dashboard_state_and_component_boundaries` (High, runtime yes) —
    decompose the god-components 059 records.
  - **065** `add_dashboard_contract_and_schema_tests`, **066**
    `add_dashboard_build_and_ci_plan` — tests + CI (npm only, no `pnpm`).
  - **067** `inventory_dashboard_visible_settings` — the 9-`<Card>`/24-key SettingsPage
    inventory; a required inventory gate.
  - **068** `define_dashboard_information_architecture`, **069**
    `design_dashboard_progressive_disclosure` — design docs.
  - **070** `refactor_dashboard_settings_panel` (High, runtime yes) — must preserve the
    `/api/settings` flat-object contract + `Settings` type.
  - **071** `add_dashboard_developer_mode`, **072**
    `improve_dashboard_empty_loading_error_states`, **073**
    `add_dashboard_ux_regression_checks`.
- **Companions (not graph edges):** `docs/refactoring/008_viz_dashboard_refactoring_plan.md`
  (backend structure), `docs/refactoring/014_dashboard_ux_refactoring_plan.md`
  (frontend UX), and `docs/refactoring/subtasks/020_inventory_viz_dashboard_api_contracts.md`
  (backend wire contract). 059 supplies the *structural* map these three rely on; there
  is no ordering constraint among the planning docs themselves. Note the deliberate
  scope split: 020/060 = wire contract; **059 = code structure + FE↔BE mapping**.

## 16. Risk Level

**Low** (matches `docs/refactoring/007_subtask_index.md:106`). **Runtime code change:
No.** 059 only reads the backend/frontend and writes a documentation artifact. The sole
risk is *inaccuracy* — an incomplete or wrong structural map would let a downstream
refactor (062/063/064/070) split one side of the FE↔BE boundary without the other, or
miss a god-component. Mitigations: (a) enumerate directly from `wc -l` of the live tree
and from `routes.py`/`services/api.ts` rather than from memory; (b) require the
count self-check (§8.12: 27 backend `.py`/8131 LOC; 15931 component LOC); (c) require a
green `pytest -q` of the viz-heavy suites plus frontend `npm run typecheck`/`npm test`
(§12) as evidence the inventory describes the live tree. No data, format, build config,
or public API is touched, so there is no runtime-regression risk.

## 17. Notes for Implementer

- **Structure, not wire.** 059's job is the *code map* (files, LOC, feature areas,
  FE↔BE module mapping), **not** the HTTP method/path/request/response detail. For wire
  detail, cite subtask 020's artifact rather than re-deriving it. Overlap with 060 is
  the FE `services/api.ts` file — 059 records it as a *structural* unit (863 LOC,
  ~90 wrappers, two error regimes); 060 does the per-endpoint contract.
- **There is no `src/pages/` directory.** Pages are the top-level component in each
  `src/components/<Feature>/` folder (e.g. `Home/HomePage.tsx`,
  `Settings/SettingsPage.tsx`). Do not invent a `pages/` layout.
- **Router↔Sidebar are two hand-maintained lists.** `App.tsx:41-56` `PAGE_MAP` (14
  keys) and `Layout/Sidebar.tsx:12-23` `NAV_ITEMS` (10 keys) are not generated from a
  shared source. Record the exact drift (Sidebar uses `new`, omits the `wizard` alias
  and the three `paperbench/import|run|results` sub-routes). The earlier skeleton claim
  that "Sidebar omits paperbench" is **wrong** — `paperbench` IS present
  (`Sidebar.tsx:19`); the real omissions are the sub-routes.
- **`styles/dashboard.css` is a manifest, not the stylesheet.** It `@import`s five
  topic files (`:10-14`); `App.tsx:5` imports only `dashboard.css`, so Vite bundles the
  five via the import graph. Record the 6-file reality, not the stale "single file"
  claim.
- **`node_modules/` is git-ignored, not committed.** `.gitignore:113`; `git ls-files`
  returns 0 under it. `package-lock.json` is tracked. Change nothing here.
- **`api_state.py` is a facade** (`:22-40`) and `api_wizard.py` `WIZARD_ROUTES`
  (`:35`) is dead — record the concrete owner modules and classify `WIZARD_ROUTES`
  DELETE_CANDIDATE, consistent with subtask 020.
- **Raw/debug surfaces belong to 071, not 059.** Record *where* they are
  (DetailPanel Raw tab, `/api/env-keys` consumers in `Wizard/StepResources.tsx`, GPU
  auto-resubmit in `Monitor/GpuMonitor.tsx`, `dangerouslySetInnerHTML` in
  `Wizard/StepScope.tsx`, raw `JSON.stringify` dumps). Do not gate or remove them.
- **A throwaway enumeration script is fine — but do not commit it.** Put any generator
  under the scratchpad; the only committed output is the report artifact under
  `docs/refactoring/reports/`. Do not add a checker to `scripts/` (that is 065/066/073).
- **Stay read-only.** If you find yourself editing any file under `ari-core/ari/viz/`
  (backend or `frontend/`), or `package.json`/`package-lock.json`, you have left 059's
  scope — stop. The whole value of this subtask is that the baseline it records was
  captured from an *unmodified* tree.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **059** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
