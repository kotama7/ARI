# Subtask 060: Inventory Dashboard API Contracts

> Phase 5: Dashboard Frontend · Risk: Low · Runtime code change: **No** · Depends on: **059**
>
> Planning document only. Nothing here modifies runtime code, imports, prompts,
> configs, workflows, frontend, or directory names. It hands a fresh coding
> session an executable plan to produce a **read-only, front-end-side contract
> inventory** of the ARI dashboard API — i.e. the exact surface the React client
> in `ari-core/ari/viz/frontend/` requires from the `http.server` backend. All
> paths and line counts are repository-real, verified against the tree at
> planning date 2026-07-01 (ari-core `0.9.0`, branch `main`).

## 1. Goal

Produce a **complete, machine-checkable inventory of the dashboard API contract
as seen from the front end** — the "consumer side" of the wire — so the Phase-5
refactors (061 DTO/schema policy, 062 backend routes→services, 063 FE API client
+ types, 064 state/component boundaries, 065 contract+schema tests) can execute
behind an unchanged, explicitly-frozen consumer contract.

Where subtask **020** (`docs/refactoring/subtasks/020_inventory_viz_dashboard_api_contracts.md`)
inventories the same wire from the **backend/producer** side (owning handler
module/function in `ari-core/ari/viz/`, `_status` smuggling, CORS per endpoint,
WebSocket producer), **060 is the mirror image from the front end**: it catalogs,
for every call the client makes, what the client *sends*, what shape it *expects
back*, how it *handles errors*, which *TypeScript type* it decodes into, and
which *component/page* depends on it. The two inventories together bound the
contract from both ends so 062 (backend, `Runtime: Yes`) and 063 (frontend,
`Runtime: Yes`) cannot silently drift apart.

Concretely, 060 delivers a single reference artifact that enumerates, for every
front-end→backend interaction:

1. the exported wrapper name in `services/api.ts` (or the inline `fetch(...)` call
   site, if a component bypasses the client) and its line number,
2. the HTTP method + exact path template (path/query params as the client encodes
   them, e.g. `encodeURIComponent` usage),
3. the request body shape the client serializes (or "none" for GET),
4. the response TypeScript type the client decodes into (`types/index.ts` name +
   line, or the inline `interface` in `api.ts`),
5. the **error regime** the wrapper follows: throw-on-non-2xx (`get`/`post`,
   `api.ts:18-32`) vs never-throw-return-`{error}` (`pbGet`/`pbPost`,
   `api.ts:787-799`) vs the two bespoke raw-`fetch` call sites,
6. the consuming component/page(s) and whether they wrap the call in `try/catch`,
7. the WebSocket consumer contract (`hooks/useWebSocket.ts`, message shape
   `{type,data:{nodes}}`) and the polling fallback (`context/AppContext.tsx`,
   `STATE_POLL_MS = 5000`),
8. absent cross-cutting client behaviors that are part of the contract by
   omission: no auth/token/CSRF header anywhere, `API_BASE = ''` same-origin,
   uniform JSON `Content-Type` on POST.

The inventory is the **frozen baseline** that 061/062/063/065 must preserve. 060
writes **no runtime code**; its only output is a reference document (and an
optional JSON sibling for 065 fixtures) under `docs/refactoring/reports/`.

## 2. Background

The dashboard front end lives under `ari-core/ari/viz/frontend/` — Vite 5 +
React 18.3 + TypeScript 5.5, ESM (`"type":"module"`), no CSS framework, no
react-router (hand-rolled hash router in `App.tsx:32-56`). Its entire dependency
on the backend flows through one file:

- **`ari-core/ari/viz/frontend/src/services/api.ts` (863 LOC)** — the same-origin
  typed API client. `API_BASE = ''` (`api.ts:14`). It exports **79 wrapper
  functions** (`grep -cE '^export (async function|function)'`) plus ~28 exported
  `interface`/`type` declarations, over four internal transport helpers:
  - `get<T>` / `post<T>` (`api.ts:18-32`) — **throw** `new Error(...)` on non-2xx,
  - `pbGet<T>` / `pbPost<T>` (`api.ts:787-799`) — **never throw**; return the
    parsed `{...,error?}` body verbatim (comment `api.ts:780-785` documents this
    is deliberate to mirror PaperBench components' existing `.then(r=>r.json())`).
  - Two call sites bypass the helpers with a bare `fetch`: `deletePaperbenchPaper`
    (`api.ts:814`, POST with **no** `Content-Type`/body) and the SSE/stream
    endpoints consumed directly in components.

- **`ari-core/ari/viz/frontend/src/types/index.ts` (264 LOC)** — the shared TS
  types the client decodes into: `TreeNode` (`:3-22`), `Checkpoint` (`:24-36`),
  `Settings` (35 fields, `:38-75`), `CostSummary` (`:79-85`), `AppState`
  (`:87-129`, with JS-compat aliases `running`/`pid`/`llm_model` the backend
  adds), `WorkflowStage`/`WorkflowData` (`:138-172`), `ResourceMetrics`
  (`:174-183`), `ReviewReport`/`ReproReport` (`:204-235`), `CheckpointSummary`
  (`:237-264`). Several response shapes are **inline** in `api.ts` instead:
  `MemoryEntry`/`MemoryResponse` (`api.ts:53-70`), `MemoryAccessEvent`/`...Response`
  (`api.ts:76-92`), `NodeReport`/`NodeReportResponse` (`api.ts:106-160`),
  `MemoryHealth` (`api.ts:388-396`), `RubricSummary` (`api.ts:417-424`),
  `FewshotExample`/`FewshotListing` (`api.ts:430-443`).

- **`ari-core/ari/viz/frontend/src/hooks/useWebSocket.ts` (97 LOC)** — connects to
  `ws://host:(httpPort+1)/` (`useWebSocket.ts:39-44`), decodes a single message
  type `{type?,data?:{nodes?:TreeNode[]}}` (`:12-15`), exposes `{nodesData,
  connected}`, and auto-reconnects with exponential backoff (1s→30s). Inbound
  frames are the *only* server→client push channel; there is no client→server WS
  protocol.

- **`ari-core/ari/viz/frontend/src/context/AppContext.tsx` (120 LOC)** — single
  React Context; polls `fetchState()` + `fetchCheckpoints()` every
  `STATE_POLL_MS = 5000` (`AppContext.tsx:34,86`), falls back to `state.nodes`
  when WS is unreachable. No Redux/Zustand/react-query.

Per `docs/refactoring/007_subtask_index.md:107,263`, 060 is "**The FE-side
contract inventory**" and is one of the nine inventory subtasks
(`001, 002, 020, 036, 045, 053, 059, 060, 067`) that **must precede any runtime
code change** (`007_subtask_index.md:125`). It depends only on 059
(`inventory_dashboard_frontend_backend_structure`), which establishes the FE/BE
structural map; 060 narrows that to the wire contract.

## 3. Scope

In scope (read-only analysis + one reference document):

- Enumerate all **79 exported wrappers** and their inline `interface`/`type`
  companions in `ari-core/ari/viz/frontend/src/services/api.ts`.
- Classify each wrapper by transport helper and **error regime** (`get`/`post`
  throw; `pbGet`/`pbPost` swallow; bespoke `fetch`).
- Map each wrapper to its request/response TS shape (`types/index.ts` or inline).
- Map each wrapper to its **consuming components/pages** under
  `ari-core/ari/viz/frontend/src/components/**` and note whether the call site is
  guarded by `try/catch` (the throw-regime wrappers are the risk surface).
- Catalog **inline `fetch(...)` call sites that bypass `api.ts`** (SSE streams,
  direct downloads, PaperBench raw calls) — these are contract dependencies not
  visible in `api.ts`.
- Document the **WebSocket consumer contract** (`useWebSocket.ts`) and the
  **polling fallback** (`AppContext.tsx`) as first-class parts of the contract.
- Cross-reference every FE-side endpoint to its **020 backend counterpart** and
  flag any FE-expected endpoint/field that 020 does *not* list (drift finder),
  and vice-versa.
- Record cross-cutting client invariants that are contractual by omission: no
  auth/CSRF/token header (`grep` of `api.ts` returns zero), `API_BASE = ''`
  same-origin, `Content-Type: application/json` on POST, `encodeURIComponent`
  usage patterns (note the *intentional* non-encoded `jobId` at `api.ts:848-850`).
- Produce `docs/refactoring/reports/dashboard_fe_api_contract_inventory.md` (and,
  optionally, a `.json` sibling for 065 snapshot fixtures).

## 4. Non-Goals

- **No runtime code changes.** Do not touch `api.ts`, `types/index.ts`, any
  component, hook, context, the backend `ari-core/ari/viz/*.py`, or anything else
  outside this subtask's single `.md` output.
- **No refactor of the client.** Splitting `api.ts` into per-domain modules,
  unifying the two error regimes, or introducing generated types is **063**'s job
  (ADAPT, `Runtime: Yes`), gated by the **061** DTO/schema policy. 060 only
  records the current state.
- **No backend route inventory.** That is 020's deliverable
  (`docs/refactoring/reports/viz_api_contract_inventory.md`, to be produced when
  020 executes). 060 *consumes/cross-references* it but does not reproduce it.
- **No new tests, checker scripts, or CI.** Contract/schema tests are **065**; the
  viz schema checker is **030** (`scripts/check_viz_api_schema.py`, not yet
  implemented); snapshot fixtures are **034**.
- **No settings/UX judgments.** Whether the 24-key `/api/settings` payload should
  be regrouped is **067–070** (Phase 6). 060 records the payload shape only.
- **No security remediation.** The missing-auth / `/api/env-keys` secret exposure
  / SLURM auto-resubmit issues are *recorded* as contract facts, not fixed here.

## 5. Current Files / Directories to Inspect

All paths under repo root `/home/t-kotama/workplace/ARI/`. Read-only inputs:

**Front-end client + types (primary):**
- `ari-core/ari/viz/frontend/src/services/api.ts` — 863 LOC; 79 exported wrappers,
  4 transport helpers (`get`/`post`/`pbGet`/`pbPost`), ~28 inline types.
- `ari-core/ari/viz/frontend/src/types/index.ts` — 264 LOC; shared response types.
- `ari-core/ari/viz/frontend/src/hooks/useWebSocket.ts` — 97 LOC; WS consumer.
- `ari-core/ari/viz/frontend/src/context/AppContext.tsx` — 120 LOC; polling
  fallback (`STATE_POLL_MS`), WS/poll merge.
- `ari-core/ari/viz/frontend/src/App.tsx` — hash router `parseHash`/`PAGE_MAP`
  (`:32-56`); maps routes to lazy pages (drives which wrappers load when).

**Consuming components/pages (map endpoints → screens):**
- `ari-core/ari/viz/frontend/src/components/Settings/SettingsPage.tsx` (1049 LOC)
  — `fetchSettings`/`saveSettings`/`fetchEnvKeys`/`fetchMemoryHealth`/`restartLetta`/
  `fetchProfiles`/`fetchRubrics`/`fetchSkills`/`sshTest`/`detectRuntime` etc.
- `ari-core/ari/viz/frontend/src/components/Wizard/StepResources.tsx` (1160 LOC)
  — `fetchEnvKeys`, model/provider probes, scheduler/partition detect.
- `ari-core/ari/viz/frontend/src/components/Results/resultSections.tsx` (1590 LOC),
  `ResultsPage.tsx` (462), `PaperWorkspace.tsx` (519) — `fetchCheckpointSummary`,
  EAR/publish, `NodeReport`.
- `ari-core/ari/viz/frontend/src/components/Tree/` (`TreePage`, `DetailPanel.tsx`
  425 + `DetailPanelTabs/*`) — `fetchCheckpointMemory`, `fetchMemoryAccess`,
  file APIs, node report.
- `ari-core/ari/viz/frontend/src/components/Monitor/` (`MonitorPage`,
  `GpuMonitor.tsx`, `monitorSections.tsx`) — `fetchResourceMetrics`,
  `gpuMonitorAction`, `stopExperiment`.
- `ari-core/ari/viz/frontend/src/components/PaperBench/**` (`PaperBenchWizard`,
  `PaperImportDialog`, `RegistryPage`, `results/ResultsView`) — all `pbGet`/`pbPost`
  + `deletePaperbenchPaper` consumers; the never-throw regime.
- `ari-core/ari/viz/frontend/src/components/Workflow/WorkflowPage.tsx` (964),
  `workflowNodes.tsx` (770) — `/api/workflow*` family.
- `ari-core/ari/viz/frontend/src/components/Experiments/ExperimentsPage.tsx`,
  `Idea/IdeaPage.tsx` — `launch`/`runStage`/state consumers.

**Backend counterparts (cross-reference only, do not modify):**
- `ari-core/ari/viz/routes.py` (1197 LOC), `api_state.py`, `api_experiment.py`,
  `api_settings.py`, `api_workflow.py`, `api_paperbench.py`, `checkpoint_api.py`,
  `file_api.py`, `ear.py`, `api_publish.py`, `api_fewshot.py`, `api_process.py`,
  `api_memory.py`, `api_orchestrator.py`, `api_tools.py`, `api_ollama.py`,
  `websocket.py`, `state_sync.py` — 27 `.py` files total in `ari-core/ari/viz/`.

**Prior/sibling planning docs (context, do not modify):**
- `docs/refactoring/subtasks/020_inventory_viz_dashboard_api_contracts.md` — the
  backend-side twin; 060 cross-references its endpoint list.
- `docs/refactoring/subtasks/022_define_dashboard_dto_and_schema_tests.md`,
  `023_separate_viz_file_io_from_route_handlers.md` — Phase-4 downstream of 020.
- `docs/refactoring/008_viz_dashboard_refactoring_plan.md`,
  `014_dashboard_ux_refactoring_plan.md`, `007_subtask_index.md:255-268`.

## 6. Current Problems

These are the front-end contract hazards the inventory must make explicit (they
are *recorded* here, remediated in 061/063/065 — not in 060):

1. **Two coexisting error regimes are a silent contract hazard.** `get`/`post`
   **throw** on non-2xx (`api.ts:18-32`); `pbGet`/`pbPost` **never throw** and
   return a `{error}` body (`api.ts:787-799`). Because the backend `_json` helper
   defaults to HTTP 200 and smuggles status via `_status` (per 020 /
   `routes.py:1047-1057`), a PaperBench application error arrives as `200 +
   {error}` and is handled inline by the component, whereas a non-PaperBench error
   surfaces as a thrown `Error`. A component that calls a throw-regime wrapper
   without `try/catch` will crash to the `ErrorBoundary` (`main.tsx:17-25`, which
   prints the full stack). The inventory must tag every wrapper's regime and every
   consumer's guard status.

2. **Response shapes are split across two files with no single source of truth.**
   Some types live in `types/index.ts`, others are inline in `api.ts`
   (`MemoryResponse`, `NodeReport`, `MemoryHealth`, `RubricSummary`,
   `FewshotListing`, …). There is no generated or backend-shared schema; the TS
   types are hand-maintained mirrors of ad-hoc backend dicts. Drift is invisible
   until runtime. 060 quantifies the split so 061 can define the DTO/schema policy.

3. **Endpoints are consumed both via `api.ts` and via inline `fetch`.** Not every
   dependency is in the client: SSE streams (`/api/logs`, `/api/paperbench/run/
   <jid>/logs`), direct file/paper downloads, and `deletePaperbenchPaper`'s bare
   `fetch` (`api.ts:814`) bypass the typed layer. Any inventory built only from
   `api.ts` exports is incomplete; 060 must `grep` components for raw `fetch(` /
   `EventSource(` / `new WebSocket(`.

4. **Type comments already flag known backend drift.** `types/index.ts` carries
   corrective comments about fields the backend emits but the type historically
   omitted: `AppState.cost` is the parsed `CostSummary` object not a number
   (`:106-109`), `AppState` gains unconditional tail fields `exit_code`, and
   JS-compat aliases `running`/`pid`/`llm_model` (`:115-120`); `Checkpoint.best_metric`
   is "always emitted but never reassigned from null" (`:31-35`);
   `CheckpointSummary.repro` is a "vestigial alias … backend no longer emits"
   (`:250-251`). These optional/aliased/vestigial fields are exactly the fragile
   contract points; the inventory must list them so 062/063 don't drop them.

5. **No auth/CSRF/token anywhere, `API_BASE=''` same-origin.** `grep` of `api.ts`
   for auth/token/secret/csrf returns zero. Every call — including
   `deleteCheckpoint`, `saveSettings` (which persists API keys to `.env`),
   `fetchEnvKeys` (returns real secret values), `gpuMonitorAction` (SLURM
   auto-resubmit, always sends `confirmed:true`) — is unauthenticated. This is a
   contract fact the FE relies on (it never attaches headers); recorded, not fixed.

6. **Encoding is inconsistent and load-bearing.** Most path params use
   `encodeURIComponent`, but `fetchPaperbenchRun`/`...Results` deliberately do
   **not** encode `jobId` ("to match the original call sites verbatim",
   `api.ts:848-850`). 063 must not "helpfully" add encoding without checking the
   backend's job-id parsing. The inventory flags every such intentional asymmetry.

7. **Sidebar / route drift is manual.** `App.tsx` `PAGE_MAP` has 12 routes incl.
   3 `paperbench/*` sub-routes, but the nav mirror in `Layout/Sidebar.tsx` is
   hardcoded separately — a route can exist without a nav entry. Not an API
   contract per se, but relevant to which wrappers are reachable; noted for 064.

## 7. Proposed Design / Policy

060 produces one artifact,
**`docs/refactoring/reports/dashboard_fe_api_contract_inventory.md`**, structured
as follows. (This mirrors 020's report layout so the two can be diffed
endpoint-by-endpoint.)

**A. Wrapper table** — one row per `api.ts` export (79 rows), columns:

| # | Wrapper (`api.ts:LINE`) | Method + path template | Req body type | Resp TS type (file:line) | Error regime | Consumers (component:line) | Guarded? | 020 backend match |
|---|-------------------------|------------------------|---------------|--------------------------|--------------|----------------------------|----------|-------------------|

Error regime ∈ {`throw` (get/post), `swallow` (pbGet/pbPost), `bespoke-fetch`}.
"020 backend match" cites the owning module/function from the 020 report (or
"**FE-only, no 020 entry — DRIFT**" if absent).

**B. Endpoint-family index** — grouped exactly as the FE uses them, so 063 can
split `api.ts` along these seams later:
`/state` & tree; `/api/checkpoints` + `/api/checkpoint/{id}/{summary,memory,
memory_access,files,file,filecontent,filetree,compile}` + `file/{save,delete}`;
`/api/nodes/{run}/{node}/report`; EAR `/api/ear/*`; publish `/api/publish/*`;
`/api/settings` + `/api/env-keys`; `/api/memory/{health,restart}`;
`/api/{profiles,rubrics,fewshot/*,skills,models,workflow*}`;
`/api/{run-stage,stop,launch}`; `/api/{chat-goal,config/generate,upload}`;
`/api/ssh/test`; `/api/scheduler/detect` + `/api/slurm/partitions`;
`/api/{ollama-resources,gpu-monitor,resource-metrics,container/*}`;
`/api/sub-experiments/*`; `/api/paperbench/*` (the pbGet/pbPost family).

**C. Inline-`fetch` / stream / WS appendix** — every raw `fetch(`, `EventSource(`,
`new WebSocket(` in `components/**` + `hooks/**` that is NOT routed through a
typed wrapper: path, method, consumer, and the shape the component parses. This
includes the SSE log streams and any direct binary downloads.

**D. Type catalog** — every response `interface`/`type` the FE decodes, with its
source (`types/index.ts:LINE` or `api.ts:LINE`), field count, and the "fragile
field" annotations from Problem #4 (optional / alias / vestigial / conditional).

**E. Cross-cutting invariants** — the contractual-by-omission list: no
auth/CSRF/token header; `API_BASE=''`; POST `Content-Type: application/json`;
`encodeURIComponent` map incl. the intentional `jobId` exception; the 5s polling
+ WS(`port+1`) push contract; the `{ok}` vs `{error}` vs thrown-Error tri-modal
response convention.

**F. Drift report** — the set difference between this FE inventory and the 020
backend inventory: (a) endpoints the FE calls that 020 does not list, (b)
endpoints 020 lists that no FE code calls (candidate `REVIEW_REQUIRED` /
`DELETE_CANDIDATE` for a later phase — flagged, never deleted here), (c) fields
present in one side's shape but not the other.

**Classification tags** applied per row/finding (master vocabulary): the client
itself is **KEEP** (it is the stable consumer surface); `api.ts` monolith split is
**ADAPT** (deferred to 063); FE-only endpoints with no backend match are
**REVIEW_REQUIRED**; backend endpoints with no FE consumer are **REVIEW_REQUIRED**
(may be external/`ari.public` or CLI consumers). No **DELETE_CANDIDATE** is acted
on in 060.

**Optional JSON sibling** — if trivial, also emit
`docs/refactoring/reports/dashboard_fe_api_contract_inventory.json` (array of
`{wrapper, line, method, path_template, req_type, resp_type, error_regime,
consumers[], backend_match}`) so 065 contract tests and 034 snapshot fixtures can
diff against it deterministically.

## 8. Concrete Work Items

1. **Enumerate wrappers.** From `ari-core/ari/viz/frontend/src/services/api.ts`,
   list all 79 exported functions (`grep -nE '^export (async function|function) '`)
   and, for each, extract method, path template, request body, and declared return
   type from the signature/body. Tag the transport helper used
   (`get`/`post`/`pbGet`/`pbPost`/bespoke).

2. **Resolve response types.** For each wrapper, follow the return type to its
   definition in `types/index.ts` or the inline `api.ts` interface; record
   `file:line` and field count. Capture the fragile-field annotations (Problem #4).

3. **Build the consumer map.** `grep -rn` the 79 wrapper names across
   `ari-core/ari/viz/frontend/src/components/**` and `hooks/**`; record every call
   site (component:line) and whether it sits inside a `try {…} catch` (or an
   awaited `.catch`). Flag throw-regime wrappers with unguarded call sites.

4. **Catalog inline/stream/WS dependencies.** `grep -rn -E 'fetch\(|EventSource\(|new WebSocket\('`
   across `components/**` + `hooks/**`; subtract the `api.ts` transport helpers;
   record each remaining raw dependency (SSE `/api/logs`, PaperBench log stream,
   direct downloads, `deletePaperbenchPaper`).

5. **Document the WS + polling contract.** From `hooks/useWebSocket.ts` record the
   URL derivation (`host:httpPort+1`, `:39-44`), the message shape
   (`{type,data:{nodes}}`), reconnect policy; from `context/AppContext.tsx` record
   `STATE_POLL_MS=5000`, the `fetchState`+`fetchCheckpoints` poll, and the WS/poll
   merge/fallback.

6. **Cross-reference 020.** For each FE endpoint, locate the matching row in the
   020 backend inventory (or its source `routes.py`/`api_*.py` if 020 has not yet
   been executed). Populate the "020 backend match" column and the Drift report
   (Section F). Where 020 is not yet available, cite the backend source directly.

7. **Record cross-cutting invariants.** `grep` `api.ts` for
   `auth|token|secret|csrf|Authorization` (expect zero) and confirm `API_BASE=''`
   (`:14`); enumerate `encodeURIComponent` sites incl. the intentional `jobId`
   exception (`:848-850`); note the tri-modal response convention.

8. **Write the artifact** `docs/refactoring/reports/dashboard_fe_api_contract_inventory.md`
   with sections A–F from Section 7; optionally emit the `.json` sibling.

9. **Self-check counts.** Assert the wrapper count (79), the type count, and that
   every wrapper row has a resolved response type and at least one consumer (or is
   explicitly marked "unused export — REVIEW_REQUIRED for 063 tree-shake").

10. **Link back.** Add a one-line pointer to the new report from this subtask doc's
    Notes and ensure the report references 059/061/062/063/065 as its consumers.

## 9. Files Expected to Change

060 changes **no runtime code**. The only files it creates/edits:

- `docs/refactoring/subtasks/060_inventory_dashboard_api_contracts.md` — this
  planning document.
- **New (produced when the subtask is executed):**
  `docs/refactoring/reports/dashboard_fe_api_contract_inventory.md` — the inventory
  artifact (and optionally `docs/refactoring/reports/dashboard_fe_api_contract_inventory.json`
  for 065/034).

Explicitly **not** changed (read-only inputs): everything under
`ari-core/ari/viz/frontend/` (`services/api.ts`, `types/index.ts`,
`hooks/useWebSocket.ts`, `context/AppContext.tsx`, `App.tsx`, all `components/**`),
all 27 backend `.py` files under `ari-core/ari/viz/`, `docs/refactoring/007_subtask_index.md`,
`docs/refactoring/008_*.md`, `docs/refactoring/014_*.md`,
`docs/refactoring/subtasks/020_*.md`, `scripts/**`, `.github/workflows/**`.

## 10. Files / APIs That Must Not Be Broken

060 is read-only, so nothing can be broken by executing it. The point of the
inventory is to make the following contracts **explicit and frozen** so the
Phase-5 refactors (061–066) preserve them:

- **The dashboard API wire contract** (external contract): every method+path the
  FE calls, exactly as backend `routes.py`/`api_*.py` serve them. This is the
  boundary 062 (ADAPT, backend) and 063 (ADAPT, frontend) must hold constant.
- **The `api.ts` public wrapper names + signatures** — imported by name across
  `components/**`; 063 may re-home them but must keep the import surface (or
  provide a compatibility re-export barrel).
- **The TS response types** `types/index.ts` (`Settings` 35-key, `AppState`,
  `CheckpointSummary`, `WorkflowData`, `ReviewReport`, …) and the inline `api.ts`
  types — consumed structurally by many components.
- **The two error regimes** as *observable behavior* — PaperBench components rely
  on never-throw `{error}` bodies; other components rely on throw-on-non-2xx.
  Unifying them is 061/063 work and needs a compatibility note per call site.
- **The WebSocket message shape** `{type:"update",data:{nodes}}` on `port+1` and
  the 5s `/state`+`/checkpoints` polling fallback.
- **The `/api/settings` flat 24-key POST payload** (`SettingsPage.tsx:235-260`) and
  the `Settings` type — also load-bearing for Phase-6 subtask 070.
- Cross-cutting: `API_BASE=''` same-origin, no auth header, `Content-Type:
  application/json` on POST, the intentional non-encoding of `jobId`.

## 11. Compatibility Constraints

- **Planning-phase HARD RULE:** the only file this subtask may create/modify is
  its own `.md` (plus the report artifact under `docs/refactoring/reports/`). No
  runtime code, imports, prompts, configs, workflows, frontend, or directory
  renames.
- The inventory must **preserve contracts conceptually**: it records the CLI `ari`,
  `ari.public.*`, MCP `ari-skill-*`, dashboard API endpoints/schema, checkpoint/
  output/config file formats, and README/docs usage as-is. Any future change it
  *recommends* to a downstream subtask must carry a compatibility-adapter note; the
  inventory itself proposes nothing breaking.
- **Do not use "deprecated" for internal FE code.** The `CheckpointSummary.repro`
  alias and `AppState` JS-compat aliases are "vestigial"/"back-compat", not
  "deprecated" (that word is reserved for external contracts).
- **"sonfigs" does not exist.** No `sonfigs/` directory exists anywhere in the repo;
  the FE reads nothing from such a path. The confusable trio is backend-side
  (`ari/config/` code vs `ari/configs/` packaged defaults vs top-level `config/`
  rubric/profile data) and is out of scope for this FE inventory — state this if
  the topic arises.
- The report must be consistent with the **020 backend inventory** where they
  overlap; if they disagree, 060 records the disagreement in its Drift report
  rather than "correcting" either side.

## 12. Tests to Run

060 adds no code, so tests exist only to prove the repo is unchanged and the FE
tree still builds/typechecks (baseline for the later runtime subtasks). Run from
repo root `/home/t-kotama/workplace/ARI/`:

- **Python (no-op guard — nothing should differ):**
  - `python -m compileall .` — must pass unchanged.
  - `pytest -q` — full suite green (baseline; note large viz suites
    `ari-core/tests/test_server.py` 1844, `test_gui_errors.py` 1650,
    `test_workflow_contract.py` 1606, `test_wizard.py` 1133).
  - `ruff check .` — clean (ruff **is** available; radon is **not**).
- **Front end (baseline that the inventoried tree is valid):** from
  `ari-core/ari/viz/frontend/` —
  - `npm ci` (or `npm install`) — **npm only, NO pnpm** in this repo.
  - `npm run typecheck` — `tsc` must pass (proves `types/index.ts` + `api.ts`
    still compile; the inventory's type citations must match reality).
  - `npm test` — Vitest suite green (existing tests: `PaperBench/__tests__/
    PaperBenchWizard.test`, `PaperImportDialog.test`).
  - `npm run build` — Vite build succeeds.
- **Sanity for the artifact itself:** confirm the report's wrapper count equals
  `grep -cE '^export (async function|function) ' ari-core/ari/viz/frontend/src/services/api.ts`
  (currently **79**) and that no path outside `docs/refactoring/` was modified
  (`git status --porcelain` shows only the two intended files).

## 13. Acceptance Criteria

1. `docs/refactoring/reports/dashboard_fe_api_contract_inventory.md` exists and
   contains sections A–F from Section 7.
2. **Every** exported wrapper in `api.ts` (79) has a row with: method, path
   template, request body shape, resolved response type (`file:line`), error
   regime, ≥1 consumer (or an explicit "unused export" flag), and a 020 backend
   match (or "FE-only DRIFT").
3. The inline-`fetch`/`EventSource`/`WebSocket` appendix (Section C) lists every
   raw dependency in `components/**`+`hooks/**` not routed through `api.ts`.
4. The type catalog (Section D) covers `types/index.ts` (264 LOC) and the inline
   `api.ts` interfaces, with the fragile-field annotations from Problem #4.
5. The WS+polling contract (Section E) records `port+1`, message shape, and
   `STATE_POLL_MS=5000`.
6. The Drift report (Section F) enumerates FE↔020 mismatches (endpoints and
   fields), tagged `REVIEW_REQUIRED` where appropriate; **no** endpoint/type is
   deleted or edited.
7. `git status --porcelain` shows only `060_*.md` and the report file(s); `python
   -m compileall .`, `ruff check .`, and the FE `npm run typecheck`/`build` all
   pass unchanged.
8. The report is self-contained and cross-links 059 (predecessor), 020 (backend
   twin), and 061/062/063/065 (consumers).

## 14. Rollback Plan

Trivial and total. 060 touches only Markdown under `docs/refactoring/`. To roll
back: `git rm docs/refactoring/reports/dashboard_fe_api_contract_inventory.md`
(and the `.json` sibling if created) and `git checkout --
docs/refactoring/subtasks/060_inventory_dashboard_api_contracts.md`, or simply
revert the commit. No runtime code, tests, configs, or CI are affected, so there
is nothing to migrate or un-migrate and no build/state to restore.

## 15. Dependencies

Per the dependency graph (`059 -> 060`) and `docs/refactoring/007_subtask_index.md:107`:

- **Depends on (must precede 060):** **059
  `inventory_dashboard_frontend_backend_structure`** — establishes the FE/BE
  structural map (stack, hash router, `AppContext` + WS/polling, worst-offender
  files). 060 narrows that structure into the wire contract. No other predecessor.
- **Strongly complements (should be read alongside):** **020
  `inventory_viz_dashboard_api_contracts`** — the backend/producer twin of this
  FE/consumer inventory. 060 cross-references 020's endpoint list; if 020 has not
  yet executed, 060 cites the backend sources (`routes.py`, `api_*.py`) directly.
- **Enables / is a required gate for (depend on 060 conceptually via 059):**
  - **061 `define_dashboard_dto_and_schema_policy`** — uses 060's type catalog +
    error-regime findings to set the DTO/schema policy.
  - **062 `refactor_dashboard_backend_routes_to_services`** (ADAPT, Runtime: Yes)
    — must preserve the contract 060 froze.
  - **063 `refactor_dashboard_frontend_api_client_and_types`** (ADAPT, Runtime:
    Yes) — the direct consumer; splits `api.ts`/unifies error regimes behind 060's
    frozen surface.
  - **064 `refactor_dashboard_state_and_component_boundaries`** — uses the
    consumer map to decompose god-components without dropping calls.
  - **065 `add_dashboard_contract_and_schema_tests`** — consumes the (optional)
    JSON sibling as fixtures.
- **Blocking rule:** 060 is one of the nine inventory subtasks
  (`001, 002, 020, 036, 045, 053, 059, 060, 067`) that **must precede any runtime
  code change** (`007_subtask_index.md:125`). It must be complete before 062/063/064
  begin.

## 16. Risk Level

**Low.** Runtime code change: **No.** This subtask is pure read-only analysis
producing one Markdown reference (plus an optional JSON sibling). It cannot break
CLI `ari`, `ari.public.*`, MCP servers, the dashboard API, checkpoint/config
formats, or CI. The only residual risks are *documentation-quality* risks: (a) the
inventory drifts from reality if `api.ts` changes after it is written — mitigated
by the self-check count in Section 12 and the wrapper-count assertion in Section
13; (b) the FE↔020 cross-reference is inaccurate if 020 has not yet executed —
mitigated by citing backend source lines directly when 020 is unavailable.

## 17. Notes for Implementer

- **Start from the export list, not memory.**
  `grep -nE '^export (async function|function) ' ari-core/ari/viz/frontend/src/services/api.ts`
  yields the canonical 79-wrapper list. Do not hand-transcribe; drive the table
  from grep output so the count is provable.
- **The `pbGet`/`pbPost` swallow-regime is the subtle part.** Read the comment at
  `api.ts:780-785` verbatim into the report — it explains *why* PaperBench never
  throws (backend `_json` returns 200 + `{error}`), which is the crux of the
  tri-modal response convention. Note `deletePaperbenchPaper` (`api.ts:814`) is a
  *third* pattern: bare `fetch`, no body, no `Content-Type`.
- **Follow the fragile-field comments in `types/index.ts`** (`:31-35`, `:106-129`,
  `:247-263`) — they are the maintainers' own drift notes and belong in the type
  catalog (Section D) verbatim, so 063 does not "clean up" a load-bearing optional.
- **Don't stop at `api.ts`.** SSE log streams (`/api/logs`, PaperBench
  `/run/<jid>/logs`) and direct downloads are consumed by inline `fetch`/
  `EventSource` in components — `grep -rn -E 'fetch\(|EventSource\(|new WebSocket\('`
  under `components/**`+`hooks/**` to catch them (Section C).
- **WS contract lives in the hook, not `api.ts`.** `useWebSocket.ts:39-44` derives
  the URL as `host:(httpPort+1)`; message shape is `{type?,data?:{nodes?}}`
  (`:12-15`). The 5s polling fallback is `AppContext.tsx:34,86` (`STATE_POLL_MS`).
- **Cross-reference, don't duplicate, 020.** If 020's report
  (`docs/refactoring/reports/viz_api_contract_inventory.md`) already exists, diff
  against it and record only the deltas (Section F). If not, cite `routes.py`
  (do_GET `:144-1026`, do_POST `:1028-1188`) and the owning `api_*.py` module.
- **Record, do not remediate,** the security/UX facts (no auth header;
  `/api/env-keys` returns real secrets; `gpuMonitorAction` always
  `confirmed:true`; Raw-JSON tab). These are Phase-6 (070/071) concerns; 060 only
  documents them as contract facts.
- **Keep it English + GFM** (ARI canonical language). Tables render in VitePress;
  keep rows terse and cite `file:line` for every claim.
- **Minor hygiene note (optional, do not fix):** i18n key drift — `en.ts` is 444
  lines vs `ja.ts`/`zh.ts` 441 each; not an API contract, mention only if it
  surfaces while mapping the Settings screen. `node_modules/` is **not** committed
  (`.gitignore:113`); the earlier "committed node_modules" concern is false.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **060** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
