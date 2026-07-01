# Subtask 063: Refactor Dashboard Frontend Api Client And Types

> Phase 5: Dashboard Frontend
> Classification: **ADAPT** (behind an unchanged REST/WS wire contract and unchanged TypeScript public shapes)
> Inventory gate: **059** (`inventory_dashboard_frontend_backend_structure`)
> Grounded by: **060** (`inventory_dashboard_api_contracts`), **061** (`define_dashboard_dto_and_schema_policy`)
> Coordinates with: **062** (backend routes→services), **064** (state/component boundaries), **065** (contract/schema tests), **072** (empty/loading/error states — owns error-regime UX unification)

This document is a PLANNING artifact. It changes no runtime code. It is
self-contained: a fresh coding session should be able to execute it after
reading Sections 5, 8, 9, 10, and 11.

---

## 1. Goal

Reorganize the ARI dashboard **frontend API client** (`ari-core/ari/viz/frontend/src/services/api.ts`,
863 LOC, 79 exported functions) and its **TypeScript type layer**
(`src/types/index.ts`, 264 LOC, plus the 28 DTO interfaces currently inlined in
`api.ts`) into a coherent, domain-partitioned, well-typed module set —
**without changing a single endpoint URL, HTTP method, request body shape,
response JSON key, or WebSocket message shape**, and **without breaking any of
the 29 modules that import `services/api` or the 15 that import `types`**.

Concretely, subtask 063 owns:

1. **Splitting the 863-line `api.ts` god-module** into a `services/api/`
   subpackage partitioned by endpoint family, re-exported through a
   backward-compatible barrel so every existing
   `import { ... } from '../../services/api'` keeps resolving unchanged.
2. **Consolidating the four duplicated fetch cores** (`get`/`post` at
   `api.ts:18-32`, `pbGet`/`pbPost` at `api.ts:787-799`, plus three inline
   `fetch(...)` bodies in `uploadFile` `534`, `uploadCheckpointFile` `680`,
   `deletePaperbenchPaper` `814`) into one request primitive with explicit
   per-call options, **while preserving each endpoint family's current
   throw-vs-return-`{error}` behavior byte-for-byte** (see §7.2, §11).
3. **Relocating the 28 DTO interfaces inlined in `api.ts`** (e.g. `NodeReport`,
   `EARData`, `PublishRecord`, `SubExperiment`, `CheckpointFile`,
   `MemoryEntry`, `MemoryAccessResponse`, `ContainerImage`) into the shared
   type layer, **keeping them re-exported from `services/api`** because ≥11
   components import them as types from that path (§6.3).
4. **Type-hardening the `any`-typed wrappers** (`fetchSkills(): any[]`,
   `fetchModels(): any`, `launchExperiment(data: any)`, `testSSH(data: any)`,
   `syncFewshot`/`uploadFewshot`/`deleteFewshot`/`fetchSkillDetail`/PaperBench
   helpers, etc.) into named DTOs, keeping the resolved types assignable so no
   consumer's compilation regresses.

This is an **ADAPT** subtask: the client's shape as seen by React components
(function names, signatures resolved-type-compatible, importable symbols) and
the backend it talks to (URLs/methods/JSON) both stay frozen; only the internal
organization and type precision change.

## 2. Background

The dashboard frontend is Vite 5 + React 18.3 + TypeScript 5.5 (ESM), living at
`ari-core/ari/viz/frontend/`. Its data layer is deliberately minimal — there is
no Redux/Zustand/react-query. All server access flows through one hand-written
typed client:

- **`src/services/api.ts` (863 LOC)** — same-origin `fetch` client, `API_BASE = ''`
  (`api.ts:14`). ~79 exported async wrappers over the `ari.viz` REST surface,
  plus a WebSocket-adjacent stub (`src/services/websocket.ts` is `export {}`;
  the live WS logic is in `src/hooks/useWebSocket.ts`).
- **`src/types/index.ts` (264 LOC)** — the shared TS shapes for the wire
  contract: `TreeNode`, `Checkpoint`, `Settings` (35 fields), `AppState` (with
  JS-compat aliases `running`/`pid`/`llm_model` mirroring
  `is_running`/`running_pid`, `types/index.ts:118-120`), `CostSummary`,
  `WorkflowStage`, `WorkflowData`, `ResourceMetrics`, `ReviewReport`,
  `ReproReport`, `CheckpointSummary`, and the `ReviewDecision` union whose
  trailing `| string` is load-bearing (`types/index.ts:196-202`, comment
  explicitly says "Do NOT remove `| string`").
- **28 more DTO interfaces are inlined directly in `api.ts`** (grep:
  `export interface`/`export type` at lines 53, 62, 76, 86, 107, 118, 124, 155,
  172, 178, 189, 206, 222, 234, 258, 264, 278, 287, 300, 308, 320, 388, 417,
  430, 438, 604, 622, 746). Several are imported *as types* by components from
  the `services/api` path, not from `types/` (§6.3), so `api.ts` doubles as a
  de-facto type module.
- **Consumption:** 29 source files import from `services/api`; 15 import from
  `types` (verified via grep). Data-fetching is funnelled through the generic
  `src/hooks/useApi.ts` hook, which relies on the client **throwing** on error
  (it wraps the fetcher in try/catch and surfaces `err.message`,
  `useApi.ts:24-35`).

A prior refactor pass (referenced throughout `src/README.md` as "req 15" / "req
03") already extracted helpers/subcomponents (`resultTypes.ts`,
`settingsConstants.ts`, `detailPanelHelpers.ts`, the `DetailPanelTabs/*` split,
etc.), but `api.ts` and the type layer were left monolithic. This subtask
continues that trajectory for the client + types specifically; the
god-*component* decomposition (`resultSections.tsx` 1590,
`StepResources.tsx` 1160, `SettingsPage.tsx` 1049) is delegated to **064**.

Contract framing: the endpoint URLs/methods/JSON shapes are the **dashboard API
contract**, which is the *backend's* responsibility (owned by **062**) and is
pinned by the backend contract test `test_api_schema_contract.py` (asserts
`AppState`/`Settings`/`Checkpoint`/`CheckpointSummary` key sets). This subtask
must keep the frontend's view of that contract identical so the two sides stay
in agreement.

Note: the "sonfigs" directory referenced in some planning prompts **does not
exist** anywhere in the repo, and is irrelevant to the frontend; state this only
to avoid confusion — no frontend path depends on it.

## 3. Scope

In scope (frontend TypeScript, executed AFTER the 059 inventory gate, grounded
by 060/061):

- **`ari-core/ari/viz/frontend/src/services/api.ts`** (863) — split into a
  domain-partitioned `services/api/` subpackage + compat barrel; consolidate
  the fetch cores; relocate inline DTOs; harden `any` signatures.
- **`ari-core/ari/viz/frontend/src/types/index.ts`** (264) — receive the
  relocated DTOs (or host new domain type modules); keep every currently
  exported symbol exported and shape-compatible.
- **`ari-core/ari/viz/frontend/src/hooks/useApi.ts`** (42) — only if the
  error-regime consolidation touches its throw contract (see §7.2; default
  posture is to leave it untouched and preserve throw semantics).
- **`ari-core/ari/viz/frontend/src/services/websocket.ts`** (stub) and the
  `TreeMessage` type inlined in `src/hooks/useWebSocket.ts` — optional tidy:
  move `TreeMessage` next to the WS message DTO if a WS-message type is
  formalized; otherwise leave as-is (WS shape is frozen).
- **Per-directory READMEs** that a readme-parity gate checks:
  `src/services/README.md`, `src/types/README.md`, and the master
  `src/README.md` (which enumerates every file, lines 118-133 for
  `services/`/`types/`).

Explicitly *coordinated with* but delegated elsewhere (see §4, §15):

- The two-error-regime **UX unification** at the presentation layer → **072**
  (`improve_dashboard_empty_loading_error_states`). 063 may consolidate the
  *transport* cores but must not change *observable* throw-vs-`{error}`
  behavior per endpoint family without 072's sign-off.
- The **god-component decomposition** and `AppContext`/state boundaries → **064**.
- The **DTO/schema policy** that dictates naming/placement conventions → **061**
  (063 implements against that policy; it does not invent it).
- Any **backend** URL/JSON change → **062** (063 must mirror, never lead).

## 4. Non-Goals

- **NOT** changing any endpoint URL, HTTP method, query-param name, request body
  shape, response JSON key, or status handling of the `ari.viz` backend. The
  frontend only *describes* that contract; changing it is 062's domain.
- **NOT** changing the WebSocket contract: `ws://host:(port+1)/ws`, message
  `{"type":"update","data":{nodes},...}` consumed by `useWebSocket.ts`.
- **NOT** altering the resolved public TS shapes that 15 modules import from
  `types` (`AppState`, `Settings`, `Checkpoint`, `CheckpointSummary`,
  `WorkflowData`, `ReviewReport`, etc.). New/relocated types must be
  assignment-compatible. In particular, **do not remove `| string` from
  `ReviewDecision`** (`types/index.ts:196-202`) and **do not narrow** the
  JS-compat alias fields on `AppState`.
- **NOT** decomposing god-components or touching `AppContext.tsx`/polling/state
  wiring (that is **064**).
- **NOT** reshaping Settings into tabs (**070**), adding a developer/debug-mode
  gate (**071**), building the empty/loading/error-state kit or changing which
  errors surface to the user (**072**), or the a11y/i18n pass (**073**).
- **NOT** adding auth/token/CSRF headers. The client is currently unauthenticated
  same-origin (no header anywhere); changing that alters observable behavior and
  is a security decision. Flag as **REVIEW_REQUIRED** in §17; do not implement.
- **NOT** migrating imports to the `@/*` path alias. The alias is configured in
  `tsconfig.json` and `vite.config.ts` but used in **0** files and is **absent
  from `vitest.config.ts`** (which only registers `plugins: [react()]`), so a
  blanket `@`-import migration would break test resolution. Out of scope here
  (see §17 gotcha).
- **NOT** changing `package.json` dependencies, the Vite/Vitest config build
  targets, or `docs/`, workflows, or backend Python.
- **NOT** using the term "deprecated" for any internal client/type reorg — this
  is internal reorganization, not an external-contract deprecation.

## 5. Current Files / Directories to Inspect

All paths absolute-from-repo-root (`/home/t-kotama/workplace/ARI`). Verified line
counts, 2026-07-01.

Primary targets:

| File | LOC | Role |
| --- | --- | --- |
| `ari-core/ari/viz/frontend/src/services/api.ts` | 863 | Typed REST client. `API_BASE=''` (14). Cores: `get`/`post` throw on non-2xx (18-32); `pbGet`/`pbPost` never throw, return `{error}` (787-799, comment 780-785). 79 exported functions; 28 inline `export interface`/`type` DTOs. Inline `fetch` in `uploadFile` (534), `uploadCheckpointFile` (680), `deletePaperbenchPaper` (814). |
| `ari-core/ari/viz/frontend/src/types/index.ts` | 264 | Shared wire types: `TreeNode`, `Checkpoint`, `Settings` (38-75), `CostSummary`, `AppState` (87-129, JS-compat aliases 118-120), `WizardState`, `WorkflowStage`, `WorkflowData`, `ResourceMetrics`, `ReviewScoreDimension`, `ReviewDecision` (196-202, keep `| string`), `ReviewReport`, `ReproReport`, `CheckpointSummary`. |
| `ari-core/ari/viz/frontend/src/hooks/useApi.ts` | 42 | Generic fetch hook; depends on client **throwing** (24-35). |
| `ari-core/ari/viz/frontend/src/hooks/useWebSocket.ts` | ~90 | WS stream; inline `TreeMessage` type; frozen WS shape. |
| `ari-core/ari/viz/frontend/src/services/websocket.ts` | 6 | Stub (`export {}`). |

READMEs the readme-parity gate checks (must stay accurate if files are added):

- `ari-core/ari/viz/frontend/src/README.md` (133 lines; enumerates
  `services/` at 118-121 and `types/` at 130-132).
- `ari-core/ari/viz/frontend/src/services/README.md` (10 lines).
- `ari-core/ari/viz/frontend/src/types/README.md` (9 lines).

Consumer set to keep compiling (verified counts):

- **29 importers of `services/api`** — including `context/AppContext.tsx`,
  `components/Settings/SettingsPage.tsx`, `components/Monitor/{MonitorPage,GpuMonitor,monitorSections}.tsx`,
  `components/Results/{ResultsPage,resultSections,EarSection,PaperWorkspace,PublishYamlEditor,useEAR}.tsx/ts`,
  `components/Tree/{FileExplorer,useDetailPanelData}.ts` + `DetailPanelTabs/{Access,Memory,Report}Tab.tsx`,
  `components/Wizard/{WizardPage,StepGoal,StepLaunch,StepResources,stepResourcesSections}.tsx`,
  `components/Workflow/WorkflowPage.tsx`, `components/Idea/IdeaPage.tsx`,
  `components/Experiments/ExperimentsPage.tsx`, `components/Layout/Sidebar.tsx`,
  `components/PaperBench/{PaperBenchWizard,PaperImportDialog,PaperRegistryPage}.tsx`,
  `components/PaperBench/results/ResultsView.tsx`.
- **15 importers of `types`.**

Config/build/test context:

- `ari-core/ari/viz/frontend/package.json` — scripts `dev/build/typecheck/preview/test`;
  deps `react`/`react-dom`/`d3`/`reactflow`; dev `vitest`/@testing-library/`typescript`/`vite`.
- `ari-core/ari/viz/frontend/tsconfig.json` — `strict`, `noUnusedLocals`,
  `noUnusedParameters`, `isolatedModules`, `@/*` path alias (unused).
- `ari-core/ari/viz/frontend/vite.config.ts` — build `outDir ../static/dist`,
  base `/static/dist/`, `@` alias, dev proxy to `:8765`.
- `ari-core/ari/viz/frontend/vitest.config.ts` — jsdom, `globals`,
  `setupFiles: ['./vitest.setup.ts']`, glob `src/**/__tests__/**/*.test.tsx`.
  **No `resolve.alias` here** (the `@` alias is not registered for tests).
- `ari-core/ari/viz/frontend/src/components/PaperBench/__tests__/{PaperBenchWizard,PaperImportDialog}.test.tsx`
  — stub global `fetch` via `vi.stubGlobal('fetch', fetchMock)` and assert on
  **exact URL strings** (e.g. `/api/upload`, `/api/paperbench/arxiv/<source>`).
  These pin the URL strings the client builds.

Upstream planning references: `docs/refactoring/subtasks/059_*` (inventory,
once authored), `060_*`, `061_*`, `docs/refactoring/008_viz_dashboard_refactoring_plan.md`,
`docs/refactoring/010_contract_preservation_policy.md`,
`docs/refactoring/subtasks/015_refactor_dashboard_viz_api_services.md` (the
backend counterpart pattern).

## 6. Current Problems

Grounded in the routed frontend findings and re-verified line references:

1. **`api.ts` is a 863-line god-module** mixing four concerns: (a) transport
   primitives, (b) 79 endpoint wrappers spanning ~15 unrelated domains
   (state, checkpoints, EAR, publish, settings, memory/Letta, profiles/rubrics,
   fewshot, skills/workflow, experiment lifecycle, wizard/chat, upload, SSH/HPC,
   Ollama/GPU, container, sub-experiments, PaperBench), and (c) 28 DTO type
   definitions. It is the frontend's most-imported module (29 importers) and its
   size makes review, tree-shaking, and per-domain testing hard.

2. **Two coexisting error regimes in one file — a real contract hazard.**
   `get`/`post` (`api.ts:18-32`) `throw new Error()` on non-2xx; `pbGet`/`pbPost`
   (`api.ts:787-799`, documented at 780-785) **never throw** and return the
   backend's `{error}` body verbatim (the backend `_json` defaults to
   `status=200`). Because `useApi.ts` only surfaces errors it *catches*, any
   PaperBench call routed through `useApi` (e.g. `PaperRegistryPage.tsx:37`
   `useApi(() => fetchPaperbenchPapers())`) silently reports "no error" even on
   backend failure, forcing every PaperBench call site to hand-check
   `data.error`. The two regimes are undocumented at the type level (both return
   `Promise<{...; error?}>` vs `Promise<T>` with `throw`).

3. **DTOs are split across two locations with cross-path imports.** 28 interfaces
   live in `api.ts`; the "core" ones live in `types/index.ts`. ≥11 components
   import DTO *types* from the `services/api` path rather than `types`, e.g.
   `Results/PublishYamlEditor.tsx:2` (`PublishYamlData`),
   `Results/useEAR.ts:9` (`PublishRecord`, `PublishYamlData`),
   `Results/PaperWorkspace.tsx:16` (`CheckpointFile`),
   `Results/EarSection.tsx:22` (`EARData`, `EARCurateResult`, `PublishRunResult`),
   `Wizard/StepResources.tsx:4` (`ContainerImage`),
   `Experiments/ExperimentsPage.tsx:8` (`SubExperiment`),
   `Tree/DetailPanelTabs/ReportTab.tsx:8` (`NodeReport`),
   `Tree/DetailPanelTabs/AccessTab.tsx:8` (`MemoryAccessResponse`),
   `Tree/DetailPanelTabs/MemoryTab.tsx:8` (`MemoryEntry`). There is no single
   source of truth for "where does a dashboard DTO live".

4. **Weakly-typed wrappers leak `any` into the app.** `fetchSkills(): Promise<any[]>`
   (`api.ts:479`), `fetchSkillDetail(): Promise<any>` (483), `fetchModels(): Promise<any>`
   (740), `launchExperiment(data: any)` (510), `testSSH(data: any)` (555),
   `syncFewshot`/`uploadFewshot`/`deleteFewshot` (`Promise<any>`, 449/453/465),
   `detectScheduler`/`fetchPartitions`/`fetchOllamaResources` (`any[]`/loose),
   `fetchWorkflowFlow`/`saveWorkflowFlow`/`fetchWorkflowDefault` (`any`,
   714-724), and most PaperBench helpers (`Promise<any>`). These defeat the
   `strict` tsconfig for a large slice of the surface.

5. **Duplicated transport cores.** Four near-identical fetch bodies:
   `get`/`post` (18-32), `pbGet`/`pbPost` (787-799), plus three hand-rolled
   `fetch(...)` calls for octet-stream uploads and the no-body PaperBench delete
   (534-545, 680-690, 814-818). URL-encoding discipline is inconsistent (some
   call sites `encodeURIComponent`, `fetchPaperbenchRun` deliberately does not,
   per comment at 848).

6. **`services/websocket.ts` is a dead stub** (`export {}`, with a comment saying
   "kept for potential direct-connection scenarios"). The real WS message type
   `TreeMessage` is inlined in `useWebSocket.ts`. Minor: a **DELETE_CANDIDATE**
   or MERGE-into-`useWebSocket` decision, but the `src/services/README.md`
   currently documents it (line 9), so removal requires a readme edit.

7. **README drift risk.** `src/README.md` enumerates every source file
   (`services/` 118-121, `types/` 130-132). Adding a `services/api/` subpackage
   or type modules requires README updates or the readme-parity gate fails.

## 7. Proposed Design / Policy

**Policy: partition the client by domain behind a compat barrel, unify the
transport core, and centralize DTOs — with zero wire change and zero break to
existing import paths.** Implement against the 061 DTO/schema policy.

### 7.1 Domain-partitioned `services/api/` subpackage + compat barrel

Introduce `src/services/api/` with one module per endpoint family, e.g.
`state.ts`, `checkpoints.ts`, `files.ts`, `ear.ts`, `publish.ts`, `settings.ts`,
`memory.ts`, `catalog.ts` (profiles/rubrics/fewshot/skills/models), `workflow.ts`,
`experiment.ts`, `wizard.ts`, `ssh.ts`, `resources.ts` (Ollama/GPU/container/
resource-metrics), `subExperiments.ts`, `paperbench.ts`, and a shared
`client.ts` (transport core, §7.2). Then either:

- **Option A (lowest-risk, recommended):** keep `src/services/api.ts` as a thin
  **barrel** that `export * from './api/<module>'` for every family, so all 29
  `from '../../services/api'` imports resolve unchanged; or
- **Option B:** convert `services/api.ts` → `services/api/index.ts` (barrel),
  which also keeps `from '../../services/api'` resolving (bundler resolution
  picks up the directory index). Update `src/README.md`/`services/README.md`
  accordingly.

Either way, **the public import surface `'../../services/api'` must continue to
export every function and every currently-exported type by the same name.** No
consumer edit is required by this subtask (consumers may be migrated to
per-domain imports later, but that is optional and additive).

### 7.2 Unified transport core (behavior-preserving)

Add one request primitive in `services/api/client.ts`:

```ts
// illustrative — final signature per 061 policy
async function request<T>(path: string, opts?: {
  method?: 'GET' | 'POST';
  json?: unknown;          // JSON body
  raw?: BodyInit;          // octet-stream uploads
  headers?: Record<string, string>;
  throwOnError?: boolean;  // true → current get/post regime; false → pb* regime
}): Promise<T>;
```

Then define the two regimes as thin wrappers over `request`:
`get`/`post` call it with `throwOnError: true` (preserving
`throw new Error('GET <path> failed: <status>')`); `pbGet`/`pbPost` call it with
`throwOnError: false` (preserving "return `res.json()` unconditionally"). The
three inline upload/delete `fetch` bodies fold into `request` via `raw`/custom
headers. **Observable behavior per endpoint family must not change:** the same
endpoints that throw today still throw; the same ones that return `{error}`
still return `{error}`. Any *change* to which regime an endpoint uses is a UX
decision owned by **072** and must not happen here without its sign-off — call
it out in the PR description as a coordination point.

URL-encoding: preserve each call site's *exact* current encoding, including the
deliberate non-encoding in `fetchPaperbenchRun`/`fetchPaperbenchRunResults`/
`requestPaperbenchReport` (comment at `api.ts:848`) and
`deletePaperbenchPaper`'s no-Content-Type POST (comment at `api.ts:813`). The
PaperBench tests assert exact URL strings and will catch any drift.

### 7.3 DTO relocation (single source of truth, re-exported for compat)

Per the 061 policy, move the 28 inline `api.ts` DTOs into the type layer —
either into `src/types/index.ts` or into domain type modules under
`src/types/` (e.g. `types/ear.ts`, `types/publish.ts`, `types/memory.ts`,
`types/node-report.ts`). **Critical compat rule:** because ≥11 components import
these as types *from `services/api`* (§6.3), the `services/api` barrel MUST
re-export them (`export type { NodeReport, EARData, ... } from '../types/...'`)
so those imports keep resolving. Do not force consumer edits in this subtask.
Keep `types/index.ts`'s existing exports intact and assignment-compatible.

### 7.4 Type hardening

Replace the `any` wrappers (§6.4) with named DTOs sourced from the 060 API
inventory and 061 policy. Because tsconfig is `strict`, use precise types; but
where a shape is genuinely open-ended or unstable, prefer
`Record<string, unknown>`/`unknown` + narrowing at the call site over `any`, and
ensure the resolved type stays assignable to what current consumers expect
(mirror the `ReviewDecision = ... | string` pattern: widen for documentation,
never narrow in a way that breaks a consumer). Do not tighten a type so much
that a currently-compiling call site fails `tsc --noEmit`.

### 7.5 WS stub + README housekeeping

- `services/websocket.ts`: **DELETE_CANDIDATE** — it is `export {}` with no
  importers. If deleted, remove its line from `src/services/README.md` (line 9)
  and `src/README.md` (line 121); if retained for symmetry, leave untouched.
  Prefer keeping it only if 064 (which owns WS/state) plans to use it; otherwise
  defer the decision to 064 to avoid cross-subtask churn. Recommended: **leave
  as-is** in 063 (out of the client/types core focus) unless trivially removed
  with README sync.
- Update `src/services/README.md`, `src/types/README.md`, and `src/README.md`
  (§5) to reflect any new `services/api/` and `types/` modules — the
  readme-parity gate enforces this.

Classification summary: **ADAPT** the frontend client + type layer behind the
frozen REST/WS wire contract and frozen TS public shapes. `services/websocket.ts`
is a **DELETE_CANDIDATE** (defer to 064 unless removed with README sync). The 28
inline DTOs are **MOVE** (relocate + re-export). No **MOVE_TO_LEGACY**. The
error-regime *behavior* is **KEEP** in 063 (UX unification is 072's **ADAPT**).

## 8. Concrete Work Items

Execute only after 059 inventory exists and 060/061 are available (§15).
Suggested order, each step gated by §12:

1. **Ingest 060/061.** Treat the 060 endpoint inventory (URLs, methods, params,
   response keys, error regime per family) as the frozen contract table, and the
   061 DTO/schema policy as the naming/placement rulebook.
2. **Add `services/api/client.ts`** with the unified `request` primitive and the
   `get`/`post`/`pbGet`/`pbPost` wrappers on top of it (behavior-preserving,
   §7.2). Do not move any endpoint wrapper yet. Run `npm run typecheck && npm test`
   — must pass unchanged.
3. **Split endpoint wrappers into per-domain modules** under `services/api/`,
   importing the transport core from `client.ts`. Keep function names and
   signatures identical. Wire the compat barrel (Option A or B, §7.1) so
   `'../../services/api'` re-exports everything. Run typecheck/test/build.
4. **Relocate the 28 inline DTOs** into `types/` (or domain type modules) per
   §7.3, and add re-exports from the `services/api` barrel for the ≥11
   type-from-`api` importers. Confirm `tsc --noEmit` passes with no consumer
   edits. Run the full gate.
5. **Type-harden the `any` wrappers** (§7.4) using 060/061 DTOs, one domain at a
   time, verifying `tsc --noEmit` after each. Keep resolved types assignable.
6. **README sync** — update `src/README.md`, `src/services/README.md`,
   `src/types/README.md` for every new/moved file. Run the readme-parity /
   doc-source checkers (§12).
7. **Optional WS stub decision** (§7.5) — only if removing with README sync;
   otherwise leave for 064.
8. **Run the full gate set** (§12) after steps 2–6.

Explicitly *not* in the work list: changing any URL/method/body/response;
editing consumer import paths; touching `AppContext`/components (064);
changing which errors surface to the user (072); adding auth (REVIEW_REQUIRED).

## 9. Files Expected to Change

Frontend TypeScript (only when this subtask is executed, post-059, grounded by
060/061):

- `ari-core/ari/viz/frontend/src/services/api.ts` — becomes a thin compat barrel
  (Option A) or is replaced by `services/api/index.ts` (Option B); its 79
  wrappers move into per-domain modules; its 28 inline DTOs relocate.
- **New** `ari-core/ari/viz/frontend/src/services/api/` — `client.ts` (transport
  core) + per-domain modules (state, checkpoints, files, ear, publish, settings,
  memory, catalog, workflow, experiment, wizard, ssh, resources, subExperiments,
  paperbench) + barrel.
- `ari-core/ari/viz/frontend/src/types/index.ts` — receives relocated DTOs
  and/or gains sibling domain type modules; all existing exports preserved.
- **Possibly new** `ari-core/ari/viz/frontend/src/types/*.ts` — domain type
  modules (if the 061 policy prefers per-domain type files over one `index.ts`).
- `ari-core/ari/viz/frontend/src/hooks/useApi.ts` — only if §7.2 alters its
  throw contract (default: unchanged).
- `ari-core/ari/viz/frontend/src/services/websocket.ts` — only if the
  DELETE_CANDIDATE decision (§7.5) removes it (with README sync).
- `ari-core/ari/viz/frontend/src/README.md`,
  `ari-core/ari/viz/frontend/src/services/README.md`,
  `ari-core/ari/viz/frontend/src/types/README.md` — module maps updated for new
  files (readme-parity gate).

Files that MUST NOT change in this subtask: `package.json`, `tsconfig.json`,
`vite.config.ts`, `vitest.config.ts` (unless the `@`-alias question is settled —
see §17; default: unchanged), all `components/**` and `context/**` consumers
(no import-path edits forced), backend Python under `ari-core/ari/viz/*.py`
(that is 062), `docs/`, and `.github/workflows`.

This planning document:
`docs/refactoring/subtasks/063_refactor_dashboard_frontend_api_client_and_types.md`
(the only file created by the planning phase).

## 10. Files / APIs That Must Not Be Broken

- **Dashboard REST + WS wire contract** — every URL/method/query-param/JSON-key
  the client references (`api.ts` in full) and the WS message
  `{"type":"update","data":{nodes},...}` in `useWebSocket.ts`. The frontend's
  description of this contract must stay identical to the backend's (062) and to
  the shapes pinned by the backend `test_api_schema_contract.py`.
- **The `services/api` import surface** — all 79 function names + every
  currently-exported type name (including the 28 inline DTOs) must remain
  importable from `'.../services/api'` with resolved-type-compatible signatures.
  29 modules depend on this path.
- **The `types` import surface** — `AppState`, `Settings`, `Checkpoint`,
  `CheckpointSummary`, `WorkflowStage`, `WorkflowData`, `ResourceMetrics`,
  `ReviewReport`, `ReproReport`, `ReviewDecision`, `TreeNode`, `CostSummary`,
  etc. stay exported and assignment-compatible. **Do not remove `| string` from
  `ReviewDecision`** (`types/index.ts:196-202`); **do not narrow** `AppState`'s
  JS-compat alias fields (`running`/`pid`/`llm_model`, 118-120) or the optional
  builder-tail fields (117-128).
- **Exact URL strings asserted by tests** — the PaperBench `__tests__` assert on
  literal URLs (`/api/upload`, `/api/paperbench/arxiv/<source>`, `/api/paperbench/papers/import`);
  keep them byte-identical, including the deliberate non-`encodeURIComponent`
  and no-Content-Type cases.
- **`useApi` throw dependency** — `useApi.ts:24-35` relies on the client
  throwing; keep `get`/`post` throwing unless 072 changes the model.
- **Vitest resolution** — tests import components that import `services/api`;
  the compat barrel must resolve under `vitest.config.ts` (which lacks the `@`
  alias). Do not introduce `@`-alias imports into any file on a test path.
- **CLI `ari` / `ari viz`**, **`ari.public.*`**, **MCP tool contracts**, and
  **backend `ari.viz` routes** — untouched by this frontend-only subtask.

## 11. Compatibility Constraints

- **Wire contract is frozen.** No URL/method/param/body/response-key change.
  The frontend follows the backend; 062 owns any backend change and 063 mirrors
  it, never leads.
- **Import-path stability is a hard constraint.** The `'../../services/api'`
  and `'../types'` module specifiers must keep resolving and exporting the same
  names. Prefer a compat barrel over consumer edits so this subtask stays a
  low-blast-radius internal reorg.
- **Error-regime behavior is preserved, not unified, in 063.** Consolidating the
  transport core is allowed; changing which endpoints throw vs return `{error}`
  is **not** — that observable change belongs to 072. If a compatibility adapter
  is ever needed, keep both regimes reachable and document inline.
- **Type widening only, never breaking narrowing.** Follow the existing
  `ReviewDecision = ... | string` precedent: hardened types must remain
  assignable to what consumers currently accept, so `tsc --noEmit` stays green
  with zero consumer edits.
- **Do not use "deprecated"** for any moved client function or relocated type —
  internal reorganization, not an external-contract deprecation. (The external
  contract here is the REST/WS surface + the documented import paths; those are
  explicitly *not* being deprecated.)
- **No new dependency, no build-config change.** `package.json` deps,
  Vite/Vitest configs, and the `../static/dist` build output stay as-is. `npm`
  only (no `pnpm`).
- **README parity.** Any file added/removed under `src/services/` or `src/types/`
  must be reflected in the enumerating READMEs or the readme-parity /
  doc-source CI checks fail.

## 12. Tests to Run

Repo-level Python gates (from repo root `/home/t-kotama/workplace/ARI`; the
backend contract test mirrors the FE types this subtask must not diverge from):

```bash
python -m compileall .        # full syntax gate (backend untouched, but CI runs it)
ruff check .                   # lint (ruff IS available; radon is NOT)
pytest -q                      # full suite; keep test_api_schema_contract.py green
```

Frontend gates (from `ari-core/ari/viz/frontend/`; this is the primary gate for
a frontend subtask):

```bash
npm run typecheck    # tsc --noEmit — the main guard; strict + noUnusedLocals
npm test             # vitest run — PaperBench __tests__ assert exact URLs
npm run build        # vite build → ../static/dist (must succeed)
```

Targeted frontend checks (tight loop):

```bash
# after each step, before the full gate
npm run typecheck
npx vitest run src/components/PaperBench/__tests__   # URL-string contract tests
```

Backend contract test to keep green (mirrors FE `AppState`/`Settings`/
`Checkpoint`/`CheckpointSummary`): `pytest -q ari-core/tests/test_api_schema_contract.py`.
Run `scripts/run_all_tests.sh` for parity with CI if present. Readme/doc gates:
the checkers under `scripts/docs/` (`check_readme_parity.py`, `check_doc_sources.py`)
and CI `.github/workflows/readme-sync.yml`, `refactor-guards.yml` must stay green.

## 13. Acceptance Criteria

1. `npm run typecheck` passes (`strict`, `noUnusedLocals`, `noUnusedParameters`)
   with **zero consumer-file edits forced** by this subtask.
2. `npm test` passes; the PaperBench URL-string assertions are unchanged and
   green.
3. `npm run build` succeeds and still emits to `../static/dist`.
4. `python -m compileall .`, `ruff check .`, and `pytest -q` pass with no new
   violations; `test_api_schema_contract.py` does not regress.
5. `src/services/api.ts` no longer contains a 863-line mixed god-module: endpoint
   wrappers live in per-domain `services/api/` modules over a single transport
   core, re-exported through a compat barrel; all 79 functions remain importable
   from `'.../services/api'` by the same names.
6. The 28 previously-inline DTOs live in the type layer and are re-exported from
   the `services/api` barrel; the ≥11 components importing them as types from
   `services/api` compile without edits.
7. The `any`-typed wrappers (§6.4) are replaced with named DTOs / `unknown` +
   narrowing; no new `any` is introduced; resolved types stay assignable.
8. The two error regimes' **observable** behavior is unchanged (throw vs
   `{error}` per endpoint family), and `useApi`'s throw dependency still holds.
9. `src/README.md`, `src/services/README.md`, `src/types/README.md` accurately
   list all modules; readme-parity / doc-source checks pass.
10. `ReviewDecision` still carries `| string`; `AppState` JS-compat aliases and
    optional fields are unchanged.

## 14. Rollback Plan

- The change is a pure internal reorganization behind a frozen wire contract and
  frozen import surface, so rollback is a `git revert` of the subtask's commits.
- Land incrementally per §8; each step is independently revertible and gated by
  `npm run typecheck && npm test`. If the barrel split (step 3) surfaces any
  resolution break under Vitest, revert to the single `api.ts` and re-derive the
  module boundaries; the transport-core step (2) and DTO relocation (4) are each
  separately revertible.
- Keep the old fetch cores reachable until the unified `request` primitive is
  proven behavior-identical (typecheck + PaperBench URL tests green); do not
  delete `get`/`post`/`pbGet`/`pbPost` names until the barrel re-exports them.
- No data/format migration is involved (client only describes the wire), so
  there is no persisted state to migrate back. The backend (062) is untouched,
  so a frontend rollback cannot desync the two sides.

## 15. Dependencies

Consistent with the provided DEPENDENCY GRAPH (`059 -> 060, 061, 062, 063, 064,
065, 066`; and `007_subtask_index.md:106-113` lists 063's predecessor as 059).

- **Hard predecessor (inventory gate): 059**
  `inventory_dashboard_frontend_backend_structure`. Per the master rule
  "inventory subtasks MUST precede any runtime code change" (list includes 059),
  no frontend runtime change starts before 059 exists. 059 supplies the FE/BE
  structure map (stack, hash router, `AppContext`, worst-file inventory).
- **Grounding predecessors (should exist before execution): 060 & 061.**
  **060** `inventory_dashboard_api_contracts` is the FE-side contract inventory
  (`services/api.ts` 863 LOC, ~90 wrappers, the two error regimes) and is
  itself a required inventory gate; it hands 063 the frozen endpoint/regime
  table. **061** `define_dashboard_dto_and_schema_policy` "grounds 062/063/065"
  (`007_subtask_index.md:266`) — it dictates DTO naming/placement conventions
  this subtask implements. Both are `059 -> {060,061}` in the graph.
- **Sibling coordination (all fan out from 059):**
  - **062** `refactor_dashboard_backend_routes_to_services` (ADAPT, backend) —
    owns the REST/JSON contract; 063 must mirror whatever 062 keeps stable and
    must not lead any wire change. Sequence so 062's contract is settled first,
    or run in lockstep with the shared 060 inventory as the single source of
    truth.
  - **064** `refactor_dashboard_state_and_component_boundaries` — owns
    `AppContext`/polling/god-component decomposition and the WS stub decision;
    063 leaves those untouched.
  - **065** `add_dashboard_contract_and_schema_tests` — will pin the
    client/type surface; 063 should leave the surface test-friendly (stable
    names, exported types).
- **Downstream (Phase 6, all depend on 059): 072**
  `improve_dashboard_empty_loading_error_states` owns the *UX* unification of
  the two error regimes; 063 preserves their behavior and hands 072 a single
  consolidated transport core to build on. **070/071/073** do not depend on 063
  but share the client.
- Upstream policy inputs: `docs/refactoring/010_contract_preservation_policy.md`,
  `docs/refactoring/008_viz_dashboard_refactoring_plan.md`, and the backend
  counterpart `docs/refactoring/subtasks/015_refactor_dashboard_viz_api_services.md`.

## 16. Risk Level

- **Does this subtask change runtime code? YES** — when executed it modifies
  frontend TypeScript under `ari-core/ari/viz/frontend/src/services/` and
  `src/types/` (client reorganization, transport-core unification, DTO
  relocation, type hardening) and adds new modules. (This planning document
  itself changes no runtime code.)
- **Risk: HIGH** (consistent with `007_subtask_index.md:110`). Rationale: `api.ts`
  is the single most-imported frontend module (29 importers) and doubles as a
  type module (≥11 type-from-`api` importers), so an import-surface or
  resolved-type regression fans out widely. The two-error-regime consolidation
  is behavior-sensitive, and Vitest's missing `@` alias plus exact-URL
  assertions make resolution/encoding drift easy to introduce. Mitigations:
  strict `tsc --noEmit` catches every broken import/type; the PaperBench URL
  tests catch encoding drift; the compat-barrel strategy means **zero consumer
  edits**, keeping blast radius small; and each step is independently gated and
  revertible. Because the wire contract and consumer import paths are frozen,
  the change is mechanical/organizational rather than semantic, which lowers
  residual risk.

## 17. Notes for Implementer

- **Do not start before 059 exists, and prefer 060/061 authored first.** 060
  gives you the frozen endpoint + error-regime table; 061 gives you the DTO
  naming/placement policy. Reverse-engineering DTO placement ad hoc risks
  churning the very files 062/065 also touch.
- **Compat barrel over consumer edits.** The safest path is to keep
  `'../../services/api'` exporting every function and type by name (Option A/B,
  §7.1) and touch **no** component import. This turns a high-risk refactor into
  a low-blast-radius internal move. Migrating consumers to per-domain imports is
  a separate, optional follow-up — do not bundle it here.
- **Preserve the two error regimes' behavior.** `get`/`post` throw; `pbGet`/`pbPost`
  return `{error}`. `useApi.ts` depends on throwing. Unifying *which* errors the
  user sees is **072**'s job — do not change it here, only consolidate the
  transport plumbing beneath it. Flag the consolidation as a 072 coordination
  point in the PR.
- **Vitest has no `@` alias — do NOT migrate to `@/*` imports.** The alias is in
  `tsconfig.json`/`vite.config.ts` but **absent from `vitest.config.ts`** and
  used in **0** files today. Introducing `@`-imports on any test path would break
  `npm test`. Keep relative imports. (If a future subtask wants the alias, it
  must first add `resolve.alias` to `vitest.config.ts` — out of scope here.)
- **Exact URL strings are pinned by tests.** PaperBench `__tests__` assert literal
  URLs and preserve deliberate quirks: `fetchPaperbenchRun` does **not**
  `encodeURIComponent` the job id (`api.ts:848`), and `deletePaperbenchPaper`
  sends **no** Content-Type and no body (`api.ts:813`). Keep these verbatim.
- **Keep `ReviewDecision`'s `| string`** (`types/index.ts:196-202`) and the
  `AppState` JS-compat aliases / optional builder-tail fields — the comments in
  `types/index.ts` explicitly warn against narrowing them.
- **README parity is enforced.** Update `src/README.md` (enumerates every file),
  `src/services/README.md`, and `src/types/README.md` for any add/move/remove, or
  `scripts/docs/check_readme_parity.py` / `check_doc_sources.py` and
  `.github/workflows/readme-sync.yml` will fail.
- **`services/websocket.ts` is a dead stub** (`export {}`, 0 importers). It is a
  **DELETE_CANDIDATE**, but the WS/state ownership sits with **064**; prefer to
  leave it alone in 063 unless you remove it together with its two README lines.
- **No auth is a REVIEW_REQUIRED item, not a 063 fix.** The client sends **no
  token/CSRF/auth header on any call** (including settings save that writes
  `.env`, checkpoint delete, subprocess launch, and the env-key readback
  `/api/env-keys`). Do not add auth here; flag it for a dedicated security
  subtask. Note the env-key readback and raw/debug surfaces are 071's concern.
- **"sonfigs" does not exist** and is irrelevant to the frontend; the confusable
  backend trio (`ari/config/` code vs `ari/configs/` packaged defaults vs
  top-level `config/` rubric data) does not touch this subtask.
- **radon is not installed; ruff is; `npm` only (no `pnpm`).** Use
  `npm run typecheck`/`npm test`/`npm run build` as the primary gate and
  `ruff check .` / `pytest -q` for the repo-level pass.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **063** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
