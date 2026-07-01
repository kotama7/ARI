# Dashboard Frontend / Backend Structure Inventory

> **Subtask:** 059 — `inventory_dashboard_frontend_backend_structure` (Phase 5, Low risk, **no runtime code change**).
> **Status:** Read-only structural inventory. This document changes no runtime code, imports, prompts, configs, workflows, frontend source, or directory names. It is the frozen structural baseline consumed by subtasks **060–066** (Phase 5) and **067–073** (Phase 6).
> **Repo:** `/home/t-kotama/workplace/ARI` · branch `whole_refactoring` · `ari-core` `0.9.0` · captured 2026-07-01.
> **Method:** every count is `wc -l` / `git ls-files` / static `grep` of the **live, unmodified** tree. Frontend↔backend map derived by pairing `services/api.ts` URLs → `routes.py` dispatch branches → owning `api_*` module.
> **Classification vocabulary:** KEEP / ADAPT / MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED. "deprecated" is reserved for external contracts (dashboard API, CLI, MCP, `ari.public.*`, documented import paths) and is not applied to internal UI code.
> **Scope split (do not duplicate):** wire contract (HTTP method/path/request/response/CORS/`_status`) is subtask **020** (backend) + **060** (FE `services/api.ts`). **059 = code structure + FE↔BE module mapping only.** Visible-settings card breakdown is subtask **067**. Cross-reference docs `008_viz_dashboard_refactoring_plan.md`, `014_dashboard_ux_refactoring_plan.md`, `subtasks/020_*.md` — cited in prose, not edited.

---

## 0. Self-Check Counts (verified against live tree)

| Metric | Expected (plan) | Verified | Match |
|---|---|---|---|
| Backend `.py` files under `ari-core/ari/viz/` (maxdepth 1) | 27 | **27** | ✅ |
| Backend total LOC (27 files) | 8131 | **8131** | ✅ |
| `src/components/**` total `.tsx`/`.ts` LOC | 15931 | **15931** | ✅ |
| All `src/**` `.tsx`/`.ts`/`.css` LOC | — | **19223** | (recorded) |
| God-component set (exact LOC) | see §1 | matches | ✅ |
| `services/api.ts` URLs mapped to a backend module | all | **all (0 unmapped FE wrappers)** | ✅ |
| `node_modules/` git-tracked files | 0 | **0** (`git ls-files`) | ✅ |

Frontend feature directories under `src/components/` (12 total): `common`, `Experiments`, `Home`, `Idea`, `Layout`, `Monitor`, `PaperBench`, `Results`, `Settings`, `Tree`, `Wizard`, `Workflow` — i.e. **10 page/feature areas** (Home, Experiments, Monitor, Tree, Results, Wizard, PaperBench, Idea, Workflow, Settings) + `Layout` (app shell/nav) + `common` (shared primitives). **There is no `src/pages/` directory** — each page is the top-level component in its feature folder (e.g. `Home/HomePage.tsx`, `Settings/SettingsPage.tsx`).

> **Accuracy note (plan §2/§5.3 phrasing):** the parent doc says "12 feature folders + common/". The live tree has **12 directories total including `common`** (so 11 non-`common` folders, of which `Layout` is app-shell not a page). Recorded here as the ground truth; not a code defect.

---

## 1. God-Component Set (exact LOC — §13.2)

Required to be recorded verbatim so a later diff can prove decomposition happened:

| File | LOC | Kind | Classification |
|---|---|---|---|
| `src/components/Results/resultSections.tsx` | **1590** | 6 exported `render*` fns (incl. ~460-line `renderReviewScores`) | ADAPT (split → 064/070) |
| `src/components/Wizard/StepResources.tsx` | **1160** | single component, ~25 `useState`, ORS + per-phase-model config, env-key autoread | ADAPT (split → 064) |
| `src/components/Settings/SettingsPage.tsx` | **1049** | single god-component, all 9 `<Card>` sections inline, no tabs, ~30 `useState` | ADAPT (split → 067/070) |
| `src/components/Workflow/WorkflowPage.tsx` | **964** | ReactFlow pipeline editor | ADAPT (split → 064) |
| `src/services/api.ts` | **863** | ~90 typed fetch wrappers, two error regimes | ADAPT (split by family → 063) |
| `src/components/Workflow/workflowNodes.tsx` | **770** | ReactFlow node renderers | ADAPT (already-extracted helper; split further → 064) |

Additional >500-LOC units (flag `oversized`): `StepGoal.tsx` 528, `PaperWorkspace.tsx` 519, `MonitorPage.tsx` 502.

---

## 2. Table A — Frontend Units

One row per `.tsx`/`.ts`/`.css` under `ari-core/ari/viz/frontend/src/`. `loc` = `wc -l`. Roles: page / feature-component / shared-component / hook / context / service / type / i18n / style / test / root. Flags: `god` (>500 LOC), `oversized` (>500 non-component), `inline-style`, `raw-debug`, `dead-route`, `mixed-concerns`. Default classification KEEP unless noted.

### 2.1 Top-level `src/`

| path | loc | role | feature_area | flags | class |
|---|---|---|---|---|---|
| `App.tsx` | 94 | root/router | cross-cutting | hand-rolled hash router; `PAGE_MAP` 14 keys; `new→wizard` alias | REVIEW_REQUIRED (route registry → 064/067-UX) |
| `main.tsx` | 40 | root/bootstrap | cross-cutting | `ErrorBoundary` prints full stack (`:17-25`); raw `innerHTML` (`:38`) → raw-debug | REVIEW_REQUIRED (gate stack → 072) |
| `vite-env.d.ts` | 2 | type-decl | cross-cutting | — | KEEP |

### 2.2 `components/common/` (shared primitives)

| path | loc | role | class |
|---|---|---|---|
| `common/Badge.tsx` | 10 | shared-component | KEEP |
| `common/Button.tsx` | 29 | shared-component | KEEP |
| `common/Card.tsx` | 17 | shared-component | KEEP |
| `common/StatBox.tsx` | 14 | shared-component | KEEP |
| `common/StatusBadge.tsx` | 16 | shared-component | KEEP |
| `common/index.ts` | 5 | barrel | KEEP |

### 2.3 Page/feature folders

| path | loc | role | feature_area | flags | class |
|---|---|---|---|---|---|
| `Home/HomePage.tsx` | 122 | page | Home | — | KEEP |
| `Home/index.ts` | 1 | barrel | Home | — | KEEP |
| `Experiments/ExperimentsPage.tsx` | 189 | page | Experiments | `sessionStorage` handoff | KEEP |
| `Experiments/index.ts` | 1 | barrel | Experiments | — | KEEP |
| `Monitor/MonitorPage.tsx` | 502 | page | Monitor | god, inline-style | ADAPT |
| `Monitor/monitorSections.tsx` | 366 | feature-component | Monitor | raw-debug (2× `JSON.stringify`) | ADAPT |
| `Monitor/GpuMonitor.tsx` | 129 | feature-component | Monitor | raw-debug (SLURM auto-resubmit, `:71`) | REVIEW_REQUIRED (→071) |
| `Monitor/PhaseStepper.tsx` | 113 | feature-component | Monitor | — | KEEP |
| `Monitor/index.ts` | 3 | barrel | Monitor | — | KEEP |
| `Tree/TreePage.tsx` | 206 | page | Tree | — | KEEP |
| `Tree/TreeVisualization.tsx` | 366 | feature-component | Tree | D3, inline-style | ADAPT |
| `Tree/DetailPanel.tsx` | 425 | feature-component | Tree | raw-debug (`{ } Raw` tab `:364,411-419`) | REVIEW_REQUIRED (gate Raw →071) |
| `Tree/FileExplorer.tsx` | 393 | feature-component | Tree | — | KEEP |
| `Tree/useDetailPanelData.ts` | 204 | hook | Tree | — | KEEP |
| `Tree/detailPanelHelpers.ts` | 31 | helper | Tree | — | KEEP |
| `Tree/index.ts` | 4 | barrel | Tree | — | KEEP |
| `Tree/DetailPanelTabs/AccessTab.tsx` | 155 | feature-component | Tree | — | KEEP |
| `Tree/DetailPanelTabs/MemoryEntryCard.tsx` | 131 | feature-component | Tree | — | KEEP |
| `Tree/DetailPanelTabs/ReportTab.tsx` | 126 | feature-component | Tree | — | KEEP |
| `Tree/DetailPanelTabs/MemoryTab.tsx` | 113 | feature-component | Tree | — | KEEP |
| `Tree/DetailPanelTabs/TraceTab.tsx` | 57 | feature-component | Tree | — | KEEP |
| `Tree/DetailPanelTabs/CodeTab.tsx` | 42 | feature-component | Tree | — | KEEP |
| `Results/resultSections.tsx` | **1590** | feature-component | Results | god, raw-debug (6× `JSON.stringify`), mixed-concerns | ADAPT |
| `Results/PaperWorkspace.tsx` | 519 | feature-component | Results | god, inline-style | ADAPT |
| `Results/ResultsPage.tsx` | 462 | page | Results | mixed-concerns | ADAPT |
| `Results/RubricTreeVisualization.tsx` | 462 | feature-component | Results | D3 | ADAPT |
| `Results/EarSection.tsx` | 439 | feature-component | Results | — | KEEP |
| `Results/resultHelpers.ts` | 169 | helper | Results | — | KEEP |
| `Results/PublishYamlEditor.tsx` | 162 | feature-component | Results | raw-debug (raw-YAML editor) | REVIEW_REQUIRED (→071) |
| `Results/useEAR.ts` | 38 | hook | Results | — | KEEP |
| `Results/resultTypes.ts` | 31 | type | Results | — | KEEP |
| `Results/index.ts` | 1 | barrel | Results | — | KEEP |
| `Wizard/StepResources.tsx` | **1160** | feature-component | Wizard | god, raw-debug (env-key autoread `:333-342`), mixed-concerns | ADAPT |
| `Wizard/StepGoal.tsx` | 528 | feature-component | Wizard | god | ADAPT |
| `Wizard/StepScope.tsx` | 424 | feature-component | Wizard | raw-debug (`dangerouslySetInnerHTML` `:137`) | REVIEW_REQUIRED (sanitize →071) |
| `Wizard/stepResourcesSections.tsx` | 407 | feature-component | Wizard | — | KEEP |
| `Wizard/StepLaunch.tsx` | 399 | feature-component | Wizard | — | KEEP |
| `Wizard/WizardPage.tsx` | 352 | page | Wizard | — | KEEP |
| `Wizard/index.ts` | 1 | barrel | Wizard | — | KEEP |
| `PaperBench/PaperBenchWizard.tsx` | 412 | page | PaperBench | — | KEEP |
| `PaperBench/results/ResultsView.tsx` | 390 | page | PaperBench | — | KEEP |
| `PaperBench/PaperImportDialog.tsx` | 254 | page | PaperBench | — | KEEP |
| `PaperBench/PaperRegistryPage.tsx` | 147 | page | PaperBench | — | KEEP |
| `PaperBench/index.ts` | 4 | barrel | PaperBench | — | KEEP |
| `PaperBench/__tests__/PaperImportDialog.test.tsx` | 138 | test | PaperBench | — | KEEP |
| `PaperBench/__tests__/PaperBenchWizard.test.tsx` | 118 | test | PaperBench | — | KEEP |
| `PaperBench/steps/` | (dir) | — | PaperBench | **empty dir** | DELETE_CANDIDATE (empty) |
| `Idea/IdeaPage.tsx` | 478 | page | Idea | — | KEEP |
| `Idea/index.ts` | 1 | barrel | Idea | — | KEEP |
| `Workflow/WorkflowPage.tsx` | **964** | page | Workflow | god, ReactFlow | ADAPT |
| `Workflow/workflowNodes.tsx` | **770** | feature-component | Workflow | god | ADAPT |
| `Workflow/index.ts` | 1 | barrel | Workflow | — | KEEP |
| `Settings/SettingsPage.tsx` | **1049** | page | Settings | god, inline-style, raw-debug (env-key consumer path), mixed-concerns | ADAPT (→067/070) |
| `Settings/settingsConstants.ts` | 86 | data | Settings | hardcoded/stale provider-model lists | KEEP (data; freshness →012-UX §14) |
| `Settings/index.ts` | 1 | barrel | Settings | — | KEEP |
| `Layout/Sidebar.tsx` | 191 | app-shell | Layout | hardcoded `NAV_ITEMS` (10), nav↔route drift | REVIEW_REQUIRED |
| `Layout/Layout.tsx` | 11 | app-shell | Layout | — | KEEP |
| `Layout/index.ts` | 2 | barrel | Layout | — | KEEP |

### 2.4 Cross-cutting `src/`

| path | loc | role | flags | class |
|---|---|---|---|---|
| `services/api.ts` | **863** | service | oversized; two error regimes (`get/post` throw vs `pbGet/pbPost` no-throw, `:787-799`) | ADAPT (→063) |
| `services/websocket.ts` | 5 | service | stub re-export (`export {}`) | DELETE_CANDIDATE (dead stub) |
| `context/AppContext.tsx` | 120 | context | single global store; 5s poll (`:34`) | ADAPT (→064) |
| `hooks/useWebSocket.ts` | 97 | hook | `wsPort=httpPort+1` (`:42`) | KEEP |
| `hooks/useApi.ts` | 42 | hook | generic fetch hook | KEEP |
| `types/index.ts` | 264 | type | `Settings`/`AppState`/`Checkpoint`/`TreeNode`; declares unused `model_*`/`vlm_review_*` fields | KEEP (contract; §067) |
| `i18n/en.ts` | 444 | i18n | key-count drift vs ja/zh | REVIEW_REQUIRED (→073) |
| `i18n/ja.ts` | 441 | i18n | drift | REVIEW_REQUIRED |
| `i18n/zh.ts` | 441 | i18n | drift | REVIEW_REQUIRED |
| `i18n/index.ts` | 40 | i18n | `useI18n`; `localStorage ari_lang` (default `ja`) | KEEP |
| `styles/dashboard.css` | 14 | style | **manifest** — `@import`s the 5 topic files (`:10-14`) | KEEP |
| `styles/tokens.css` | 58 | style | — | KEEP |
| `styles/layout.css` | 23 | style | — | KEEP |
| `styles/components.css` | 73 | style | — | KEEP |
| `styles/widgets.css` | 90 | style | — | KEEP |
| `styles/responsive.css` | 142 | style | — | KEEP |

Inline-style prevalence: despite the v0.7.0 6-file CSS split, components use pervasive inline `style={{}}` objects (e.g. `Sidebar.tsx`, `App.tsx:75`, `main.tsx:17`, monitor/tree/results sections). Recommendation: MERGE inline styles into token/widget CSS (view-layer, downstream UX work) — **not fixed here**.

---

## 3. Table B — Backend Modules (`ari-core/ari/viz/*.py`, 27 files / 8131 LOC)

Roles: dispatch / infra / facade / endpoint-owner / helper. Handler groups per §7.1 taxonomy.

| path | loc | role | handler_group | class |
|---|---|---|---|---|
| `routes.py` | 1197 | dispatch | ALL (single `if/elif` `do_GET` ~86 branches + `do_POST` ~51); inline `/state` builder (`:219-666`); inline `/api/container/*`→`ari.container`, `/api/active-checkpoint`, `/api/resource-metrics` | ADAPT (route registry →062) |
| `api_experiment.py` | 929 | endpoint-owner | Experiment (`/api/run-stage`, `/api/launch`, `/api/logs` SSE) | ADAPT |
| `api_paperbench.py` | 813 | endpoint-owner | PaperBench (papers/arxiv/run/results/report/cost-estimate) | ADAPT |
| `api_settings.py` | 553 | endpoint-owner | Settings/workflow (`/api/settings`, `/api/env-keys`, `/api/workflow` GET/POST, `/api/skills`, `/api/skill/<n>`, `/api/profiles`, `/api/rubrics`, `/api/scheduler/detect`) | ADAPT |
| `api_workflow.py` | 462 | endpoint-owner | Settings/workflow (`/api/workflow/{flow,default,skills,disabled-tools}`) | ADAPT |
| `ear.py` | 452 | endpoint-owner | EAR (`/api/ear/*`, `/api/nodes/<r>/<n>/report`, publish-yaml, curate, clone-verify) | ADAPT |
| `checkpoint_api.py` | 327 | endpoint-owner | State/tree + Checkpoints (`_api_models`, `_api_checkpoints`, `_api_checkpoint_summary`, `_api_lineage_decisions`) | ADAPT |
| `api_orchestrator.py` | 321 | endpoint-owner | Orchestrator (`/api/sub-experiments*`); **core→viz edge** `cli/lineage.py→_api_launch_sub_experiment` | ADAPT |
| `api_paperbench_worker.py` | 319 | endpoint-owner | PaperBench (worker; dup `_run_pipeline` `:168`, cf. subtask 002/008) | ADAPT |
| `file_api.py` | 307 | endpoint-owner | Checkpoints/files (`/api/checkpoint/{files,file,file/save,file/delete,file/upload,compile}`) | ADAPT |
| `api_tools.py` | 259 | endpoint-owner | Tools/wizard (`/api/chat-goal`, `/api/config/generate`, `/api/upload`, `/api/upload/delete`, `/api/ssh/test`) | ADAPT |
| `node_work_api.py` | 233 | endpoint-owner | Checkpoints/files (`/api/checkpoint/{filetree,filecontent,memory}`) | ADAPT |
| `api_memory.py` | 227 | endpoint-owner | Memory (`/api/memory/{health,detect,restart,start-local,stop-local}`, `memory_access`) | ADAPT |
| `api_fewshot.py` | 221 | endpoint-owner | Fewshot (`/api/fewshot/<id>/{,sync,upload,<ex>/delete}`) | ADAPT |
| `checkpoint_lifecycle.py` | 205 | endpoint-owner | Checkpoints (`/api/delete-checkpoint`, `/api/switch-checkpoint`) | ADAPT |
| `api_process.py` | 205 | endpoint-owner | Process/GPU (`/api/gpu-monitor` GET/POST, `/api/stop`) | ADAPT |
| `server.py` | 201 | infra | dispatch/infra — `_DualStackServer`, 3 threads (watcher/HTTP/WS on `port+1`) | KEEP |
| `api_publish.py` | 191 | endpoint-owner | Publish (`/api/publish/{settings,<id>,<id>/preview,<id>/record,<id>/promote}`) | ADAPT |
| `ui_helpers.py` | 183 | helper | shared (`_collect_resource_metrics`→`/api/resource-metrics`, `_build_experiment_detail_config`→`/api/experiment-detail`, `_REDACT_KEYS`) | KEEP |
| `state_sync.py` | 117 | infra | State/tree (`_load_nodes_tree`, `_watcher_thread`, `_broadcast`) | KEEP |
| `api_ollama.py` | 90 | endpoint-owner | Ollama (`/api/ollama-resources`, `_ollama_proxy`) | ADAPT |
| `state.py` | 79 | infra | module-global state (`_checkpoint_dir`, etc.) | KEEP |
| `api_state.py` | 76 | facade | thin re-export facade → checkpoint_finder/state_sync/checkpoint_api/ear/file_api/checkpoint_lifecycle/node_work_api | KEEP (facade; §17) |
| `checkpoint_finder.py` | 65 | helper | State/tree (`_resolve_checkpoint_dir`, `_check_pid_alive`) | KEEP |
| `websocket.py` | 36 | infra | WebSocket loop (single `{"type":"update",...}` msg on `port+1`) | KEEP |
| `api_wizard.py` | 35 | infra | **dead** `WIZARD_ROUTES` dict (`:35`, abandoned declarative-routing intent) | **DELETE_CANDIDATE** (consistent w/ 020) |
| `__init__.py` | 28 | infra | package init | KEEP |

Backend structural facts: stdlib `http.server` (**no Flask/FastAPI/aiohttp**); routing is a hand-rolled `if/elif` on `self.path`; `api_state.py` is a facade so callers keep `from .api_state import ...` paths; `api_wizard.WIZARD_ROUTES` is the abandoned route-table intent (revived by 062/ST-11-1).

---

## 4. Table C — Frontend Feature Area → Backend Handler Group(s)

Derived by pairing each `services/api.ts` wrapper a feature folder imports → its URL → the owning `routes.py` branch → `api_*` module. **All consumed wrappers map to a backend module; no orphan FE wrapper found.** (Exhaustive per-endpoint wire detail is subtask 020/060.)

| Feature area | api.ts wrappers consumed | Backend module(s) / group |
|---|---|---|
| **Home** | (none direct — reads `AppState` via `AppContext`) | `routes.py` `/state` (→ state_sync + ui_helpers + api_settings) |
| **Experiments** | `fetchCheckpointSummary`, `fetchSubExperiments` | `checkpoint_api`, `api_orchestrator` |
| **Monitor** | `runStage`, `stopExperiment`, `fetchGpuMonitor`, `gpuMonitorAction`, `fetchResourceMetrics`, `fetchExperimentDetail`, `detectScheduler` | `api_experiment` (run-stage/logs SSE), `api_process` (gpu/stop), `ui_helpers` (resource-metrics/experiment-detail), `api_settings` (scheduler) |
| **Tree** | `fetchCheckpointMemory`, `fetchCheckpointFiletree`, `fetchCheckpointFilecontent`, `fetchMemoryAccess`, `fetchNodeReport` | `node_work_api` (filetree/filecontent/memory), `api_memory` (memory_access), `ear` (node_report); realtime via `state_sync` (WS `port+1`) |
| **Results** | `fetchCheckpointSummary`, `fetchCheckpointFiles`, `fetchCheckpointFileContent`, `fetchCheckpointFilecontent`, `saveCheckpointFile`, `deleteCheckpointFile`, `uploadCheckpointFile`, `compileCheckpointPaper`, `fetchEAR`, `curateEAR`, `fetchPublishYaml`, `savePublishYaml`, `fetchPublishRecord`, `runPublish`, `promotePublish` | `checkpoint_api`, `file_api`, `ear`, `api_publish` |
| **Wizard** | `chatGoal`, `generateConfig`, `uploadFile`, `deleteUploadedFile`, `launchExperiment`, `fetchSettings`, `fetchEnvKeys`, `fetchRubrics`, `detectScheduler`, `fetchCheckpoints`, `switchCheckpoint`, `fetchContainerInfo`, `fetchContainerImages`, `pullContainerImage`, `fetchOllamaResources`, `fetchFewshot`, `syncFewshot`, `uploadFewshot`, `deleteFewshot` | `api_tools`, `api_experiment` (launch), `api_settings` (settings/env-keys/rubrics/scheduler), `checkpoint_api`+`checkpoint_lifecycle`, `routes.py`-inline→`ari.container`, `api_ollama`, `api_fewshot` |
| **PaperBench** | `fetchPaperbenchPapers`, `fetchArxivMetadata`, `importPaperbenchPaper`, `deletePaperbenchPaper`, `estimatePaperbenchCost`, `runPaperbench`, `fetchPaperbenchRun`, `fetchPaperbenchRunResults`, `requestPaperbenchReport`, `uploadFile` | `api_paperbench` (+ `api_paperbench_worker`), `api_tools` (upload) |
| **Idea** | `fetchState`, `fetchExperimentDetail` | `routes.py` `/state`, `ui_helpers` (experiment-detail) |
| **Workflow** | `fetchWorkflow`, `fetchWorkflowFlow`, `fetchWorkflowDefault`, `saveWorkflowFlow`, `saveSkillPhases`, `saveDisabledTools`, `fetchSkillDetail` | `api_settings` (`_api_get_workflow`, `_api_skill_detail`), `api_workflow` (flow/default/skills/disabled-tools) |
| **Settings** | `fetchSettings`, `saveSettings`, `fetchEnvKeys`(via type), `fetchSkills`, `fetchPartitions`, `fetchContainerInfo`, `restartLetta`, `deleteCheckpoint`, `testSSH`, `generateConfig` | `api_settings` (settings/skills/partitions via scheduler/env-keys), `api_memory` (restart), `checkpoint_lifecycle` (delete), `api_tools` (ssh/config), `routes.py`-inline→`ari.container` |
| **Layout** (Sidebar) | `switchCheckpoint` (+ `AppContext` `fetchCheckpoints`/`fetchState`) | `checkpoint_lifecycle`, `checkpoint_api`, `routes.py` `/state` |
| **AppContext** (cross-cutting store) | `fetchState`, `fetchCheckpoints` | `routes.py` `/state`, `checkpoint_api` |

### 4.1 Map drift findings (record, do not resolve)

1. **Plan §7.1 example imprecision (not a code defect).** The parent example row `Settings/ → api_settings+api_memory+api_process(gpu)+api_ollama(container)` is illustrative and slightly off vs the live tree: **container** is served **inline in `routes.py`** delegating to `ari.container` (public: `ari.public.container`) — **not** `api_ollama`; and the current `SettingsPage` does **not** call `api_process`(gpu) or `api_ollama` (GPU/Ollama live in `Monitor/`/`Wizard/`). The accurate mapping is in Table C above.
2. **`fetchWorkflow` GET vs flow endpoints split across two modules.** `GET/POST /api/workflow` is owned by `api_settings` (`_api_get_workflow`/`_api_save_workflow`) while `/api/workflow/{flow,default,skills,disabled-tools}` is owned by `api_workflow`. A routes→services refactor (062) must keep both owners in view for the Workflow feature area.
3. **`api_state.py` facade indirection.** Many Tree/Results/Checkpoint endpoints are imported by `routes.py` **through** `api_state.py` (which re-exports the real owners). Table C attributes each to its **real** owner module (checkpoint_api / file_api / ear / node_work_api / checkpoint_lifecycle), not the facade, so 062 can split by true owner.
4. **No orphan FE wrappers.** Every `services/api.ts` wrapper consumed by a component resolves to a live `routes.py` branch → backend module. (Whole-file `api.ts` also defines wrappers not yet consumed by any folder, e.g. `fetchModels`, `fetchMemoryHealth`, `cloneVerifyBundle`, `fetchActiveCheckpoint`, `fetchPublishSettings`/`savePublishSettings`, `launchSubExperiment` — these are live backend endpoints with FE wrappers but no current component call site; recorded for 060/063, not resolved here.)

---

## 5. Routing Inventory

- **Mechanism:** hand-rolled hash router — `parseHash()` (`App.tsx:32-39`) + `PAGE_MAP` (`App.tsx:41-56`), each page `lazy()`+`Suspense`. `AppContext` mirrors the hash independently (`AppContext.tsx:40-43,71-78`).
- **`PAGE_MAP` — 14 keys:** `home`, `experiments`, `monitor`, `tree`, `results`, `new`, `wizard`, `idea`, `workflow`, `settings`, `paperbench`, `paperbench/import`, `paperbench/run`, `paperbench/results`.
- **Legacy alias:** `new` → `wizard` (`App.tsx:37`, plus both keys present in `PAGE_MAP`). Contract — external bookmarks may use `#new`. KEEP.
- **`NAV_ITEMS` (Sidebar) — 10 keys** (`Sidebar.tsx:12-23`): `home`, `experiments`, `monitor`, `tree`, `results`, `new`, `paperbench`, `idea`, `workflow`, `settings`.
- **Router↔Nav drift (REVIEW_REQUIRED, two hand-maintained lists):** Sidebar uses `new` (not the `wizard` alias key) and **omits** the three sub-routes `paperbench/import`, `paperbench/run`, `paperbench/results`. **Correction of an earlier skeleton claim:** `paperbench` **IS** present in the Sidebar (`Sidebar.tsx:19`); the real omissions are the three sub-routes, not `paperbench` itself.

---

## 6. State-Management Inventory

- **Single global store:** `context/AppContext.tsx` (120 LOC). No Redux/Zustand/react-query.
- **Store fields (`AppContextType`):** `state: AppState|null`, `nodesData: TreeNode[]`, `currentPage`, `setCurrentPage`, `refreshState`, `wsConnected`, `checkpoints: Checkpoint[]`, `refreshCheckpoints`.
- **Polling:** `STATE_POLL_MS = 5000` (`AppContext.tsx:34`); the interval calls `loadState()` (`GET /state`) **and** `refreshCheckpoints()` (`GET /api/checkpoints`) every 5s (`:83-93`).
- **WebSocket:** `hooks/useWebSocket.ts` (97 LOC), connects `ws(s)://host:(httpPort+1)/` — `wsPort = httpPort + 1` (`:42`); consumes `{type,data:{nodes}}`; auto-reconnect w/ exponential backoff (max 30s). Node feed **falls back to `state.nodes`** when WS empty (`AppContext.tsx:96`).
- **Generic hook:** `hooks/useApi.ts` (42 LOC) — `{data,loading,error,refetch}`.
- **Per-component `useState` density:** large local clusters, notably `Settings/SettingsPage.tsx` (~30 hooks) and `Wizard/StepResources.tsx` (~25). This coupling is what 064 must untangle.

---

## 7. Styling Inventory (corrected 6-file structure)

- `styles/dashboard.css` (14 LOC) is a **manifest**, not the stylesheet: it `@import`s 5 topic files (`:10-14`) introduced by the v0.7.0 "Phase B" split — `tokens.css` (58), `layout.css` (23), `components.css` (73), `widgets.css` (90), `responsive.css` (142). `App.tsx:5` imports only `dashboard.css`; Vite bundles the 5 via the import graph.
- No CSS framework. Pervasive inline `style={{}}` coexists with the topic files (MERGE/ADAPT recommendation for downstream UX; not fixed here).

---

## 8. i18n Inventory

- Files: `i18n/en.ts` (**444**), `i18n/ja.ts` (**441**), `i18n/zh.ts` (**441**), `i18n/index.ts` (40). Default locale `ja` (`index.ts:10`, `localStorage ari_lang`).
- **Key drift:** en 444 vs ja/zh 441 — a 3-line divergence. `scripts/docs/check_i18n_js.py` covers only the **landing JS**, not these React `i18n/*.ts` files, so the drift is currently **unchecked**. REVIEW_REQUIRED → subtask 073.

---

## 9. Build / Test Tooling Inventory

- **Stack:** Vite **5** (`^5.4.2`) + React **18.3** (`^18.3.1`) + TypeScript **5.5** (`^5.5.4`); Vitest **2** (`^2.1.0`) + Testing Library + jsdom. ESM (`package.json:5 "type":"module"`).
- **Runtime deps (minimal, 4):** `react`, `react-dom`, `d3` (`^7.9.0`), `reactflow` (`^11.11.4`). **No** react-router, Redux, Zustand, react-query.
- **npm scripts (6):** `dev`, `build`, `typecheck` (`tsc --noEmit`), `preview`, `test` (`vitest run`), `test:watch`.
- **Package manager:** **npm only** (no `pnpm`). `package-lock.json` (140 KB) is **git-tracked**.
- **Build output:** `vite.config.ts` → `base:"/static/dist/"`, `build.outDir:"../static/dist"` (server serves the built bundle from `ari/viz/static/dist/`); dev proxy `/api`,`/state`→`:8765`, `/ws`→`ws://:8765`.
- **Config files:** `package.json`, `package-lock.json`, `tsconfig.json`, `vite.config.ts`, `vitest.config.ts`, `vitest.setup.ts`, `index.html`.

---

## 10. Raw / Debug UI Locations (input for subtask 071 — record only)

| Surface | Location | Note |
|---|---|---|
| `{ } Raw` node JSON tab | `Tree/DetailPanel.tsx:364,411-419` | dumps `JSON.stringify(node,null,2).slice(0,6000)` to any user (P5) |
| Env-key secret readback | `services/api.ts:382` `fetchEnvKeys` → `/api/env-keys`; consumed by `Wizard/StepResources.tsx:333-342` `autoReadApiKey` (auto-fires on mount `:299`, button `:674`) | returns real secrets to browser |
| GPU SLURM auto-resubmit | `Monitor/GpuMonitor.tsx:71` (title); `services/api.ts:585` `gpuMonitorAction` **always sends `confirmed:true`** | backend guard non-functional (REVIEW_REQUIRED backend audit → 071) |
| `dangerouslySetInnerHTML` | `Wizard/StepScope.tsx:137` | raw HTML injection |
| Full stack trace to page | `main.tsx:17-25` (ErrorBoundary), `main.tsx:38` (raw `innerHTML`) | gate → 072 |
| Raw `JSON.stringify` dumps | `Monitor/monitorSections.tsx` (2×), `Results/resultSections.tsx` (6×); raw-YAML editor `Results/PublishYamlEditor.tsx` | P5 dumps |

All recorded, **none gated or removed** (that is 071/072).

---

## 11. Hygiene Corrections (record the true state; change nothing)

- **`node_modules/` is NOT committed.** `git ls-files ari-core/ari/viz/frontend/node_modules` → **0**. `.gitignore` ignores it at lines **112** (`node_modules/`) and **113** (`ari-core/ari/viz/frontend/node_modules/`). It exists on disk (~**112 MB**) as a normal install. `package-lock.json` (140 KB) **is** tracked. The "committed node_modules" skeleton claim is **false** for this tree.
- **`styles/` is a manifest + 5 topic files**, not a single monolith (§7).
- **`services/websocket.ts`** is a dead stub (`export {}`) — the live WS logic is `hooks/useWebSocket.ts`. DELETE_CANDIDATE.
- **No `src/pages/`** directory; pages are top-level feature-folder components.
- **No `sonfigs/`** anywhere in the repo (irrelevant to the dashboard; the confusable trio is `ari/config/` code vs `ari/configs/` packaged data vs top-level `config/` rubric data). Not referenced by this inventory.

---

## 12. Classification Summary (recommendations for 060–073)

- **ADAPT (decompose behind unchanged behaviour):** the 6 god-files (`resultSections.tsx`, `StepResources.tsx`, `SettingsPage.tsx`, `WorkflowPage.tsx`, `api.ts`, `workflowNodes.tsx`) + `MonitorPage`, `PaperWorkspace`, `StepGoal`, `AppContext`, and all 18 endpoint-owner backend modules + `routes.py`.
- **DELETE_CANDIDATE:** `api_wizard.WIZARD_ROUTES` (dead route table), `services/websocket.ts` (dead stub), `PaperBench/steps/` (empty dir).
- **REVIEW_REQUIRED:** router↔nav drift (`App.tsx` `PAGE_MAP` vs `Sidebar.tsx` `NAV_ITEMS`), i18n key drift (en 444 vs ja/zh 441), and the raw/debug surfaces in §10 (gating decisions belong to 071/072).
- **KEEP:** shared `common/*` primitives, `Layout`, hooks, infra (`server.py`, `state.py`, `state_sync.py`, `websocket.py`, `checkpoint_finder.py`, `ui_helpers.py`), `api_state.py` facade, the CSS topic files, `types/index.ts` (contract), `settingsConstants.ts` (data).

---

## 13. Contracts Recorded (not altered — §10 of the subtask)

- Dashboard HTTP + WS API (`routes.py` + `api_*.py` + `websocket.py`) — wire contract frozen by 020; single WS `{"type":"update",...}` on `port+1`.
- FE consumer contract: `services/api.ts` wrapper URLs + two error regimes (`get/post` throw vs `pbGet/pbPost` no-throw); `types/index.ts` `Settings`/`AppState`.
- `/api/settings` flat-object + `Settings` type (preserved by 070).
- Hash-router keys incl. `new→wizard` alias (external bookmarks).
- `wsPort = httpPort + 1` (`useWebSocket.ts:42` ↔ `server.py` WS on `port+1`).
- Build output `viz/static/dist/` served by the backend.

---

## 14. Retirement Condition

This report is a **temporary planning artifact** of subtask 059. It may be archived/`git rm`-ed only after: (1) subtask 059 §13 Acceptance Criteria are met; (2) the implementing PR is merged to `main`; (3) `docs/refactoring/007_subtask_index.md` marks 059 **DONE**. Until then: **KEEP**. Verify each condition against primary sources before removal (canonical policy: `007_subtask_index.md` "Document Retirement Policy").
