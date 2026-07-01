# Dashboard Front-End API Contract Inventory (Subtask 060)

> **Status:** Read-only inventory artifact produced by subtask
> `docs/refactoring/subtasks/060_inventory_dashboard_api_contracts.md`
> (Phase 5, Low risk, **no runtime code change**). Producing this file modified
> no runtime code, imports, prompts, configs, workflows, frontend source, or
> directory names — its only outputs are this `.md` and its `.json` sibling under
> `docs/refactoring/reports/`.
>
> **Repo baseline:** `/home/t-kotama/workplace/ARI`, branch `whole_refactoring`,
> `ari-core` `0.9.0`. Every claim is grounded in a primary source (`file:line`)
> verified by direct `Read`/`Grep` on 2026-07-01.
>
> **What this is:** the **consumer (front-end) side** of the dashboard wire
> contract — the exact surface the React client in
> `ari-core/ari/viz/frontend/` requires from the stdlib `http.server` backend.
> It is the mirror image of subtask **020**
> (`docs/refactoring/reports/viz_api_contract_inventory.md`), which inventories
> the same wire from the **backend/producer** side. Together they bound the
> contract from both ends so 062 (backend, `Runtime: Yes`) and 063 (frontend,
> `Runtime: Yes`) cannot silently drift.
>
> **Predecessor:** 059
> (`docs/refactoring/reports/dashboard_structure_inventory.md`) — FE/BE structural
> map. **Backend twin:** 020 (cross-referenced below by its `G#`/`P#` row IDs).
> **Consumers of this artifact:** 061 (DTO/schema policy), 062 (backend
> routes→services), 063 (FE API client + types), 064 (state/component
> boundaries), 065 (contract + schema tests; consumes the `.json` sibling as
> fixtures).
>
> **Contract-preservation scope (per `010_contract_preservation_policy.md` §4/§5):**
> this inventory freezes — it does not change — the dashboard API wire contract,
> the `api.ts` wrapper names/signatures, the `types/index.ts` + inline `api.ts`
> response types, the two error regimes, the WS `{"type":"update",...}` message on
> `port+1`, the `/api/settings` flat payload, and the cross-cutting
> `API_BASE=''`/no-auth/`Content-Type: application/json` invariants. It proposes
> nothing breaking; every downstream recommendation carries a compatibility note
> or a `REVIEW_REQUIRED` tag. **There is no `sonfigs/` directory** anywhere in the
> repo and the FE reads nothing from such a path.

---

## 0. Self-check counts (verified against the live tree)

| Metric | Expected (plan) | Verified | How measured |
|---|---|---|---|
| Exported wrappers in `services/api.ts` | 79 | **79** | `grep -cE '^export (async function\|function) ' services/api.ts` |
| Transport helpers (non-export) | 4 | **4** | `get`/`post` (`api.ts:18,24`), `pbGet`/`pbPost` (`api.ts:787,792`) |
| Exported `interface`/`type` in `api.ts` | ~28 | **28** | `grep -cE '^export (interface\|type) ' services/api.ts` |
| Exported types in `types/index.ts` | — | **14** | `grep -cE '^export (interface\|type) ' types/index.ts` |
| Wrappers with a resolved response type | all | **79/79** | every row in §A has a resolved type |
| Wrappers with ≥1 consumer | — | **68 consumed / 11 unused** | §A "Consumers" column; §F.2 lists the 11 |
| Inline `fetch`/`EventSource`/`WebSocket` in `components/**`+`hooks/**` | — | **4** | `grep -rnE 'fetch\(\|EventSource\(\|new WebSocket\('` |
| Direct-URL (`<img>`/`<a>`/`<iframe>`) backend deps | — | **2 families** | `/codefile`, `/api/checkpoint/<id>/paper.pdf` (§C.2) |
| `encodeURIComponent` sites in `api.ts` | — | **27** | `grep -c encodeURIComponent`; intentional `jobId` non-encode at `:848-850` |
| Auth/token/CSRF headers in `api.ts` | 0 | **0** | `grep -niE 'auth\|token\|csrf\|Authorization\|Bearer'` → only unrelated `token?`/`authors?` data fields |

---

## 1. Client architecture (grounded)

The FE's entire backend dependency flows through one file plus a hook and a
context:

- **`src/services/api.ts` (863 LOC)** — same-origin typed client. `API_BASE = ''`
  (`api.ts:14`). 79 exported wrappers over 4 transport helpers:
  - `get<T>` / `post<T>` (`api.ts:18-32`) — **throw** `new Error(...)` on non-2xx.
  - `pbGet<T>` / `pbPost<T>` (`api.ts:787-799`) — **never throw**; return the
    parsed `{...,error?}` body verbatim. The comment `api.ts:780-785` documents
    this is deliberate: the backend `_json` helper defaults to HTTP 200 and
    smuggles status via `_status` (020 / `routes.py:1190`), so a PaperBench
    application error arrives as `200 + {error}` and is handled inline by the
    component.
  - Three wrappers use a **bespoke bare `fetch`** (not the helpers):
    `uploadFile` (`api.ts:534`, octet-stream + `X-Filename`/`X-File-Type`,
    **throws**), `uploadCheckpointFile` (`api.ts:680`, octet-stream + `X-Filename`,
    **throws**), `deletePaperbenchPaper` (`api.ts:814`, POST **no body, no
    Content-Type**, **never throws** — reads `res.json()` directly).
- **`src/types/index.ts` (264 LOC)** — shared response types (`TreeNode`,
  `Checkpoint`, `Settings`, `CostSummary`, `AppState`, `WorkflowStage`/`Data`,
  `ResourceMetrics`, `ReviewReport`, `ReproReport`, `CheckpointSummary`, …).
- **`src/hooks/useWebSocket.ts` (97 LOC)** — the *only* server→client push
  channel (§E).
- **`src/context/AppContext.tsx` (120 LOC)** — 5 s polling fallback (§E).

Tri-modal response convention (the crux 061/063 must preserve):
**(a) thrown `Error`** (get/post non-2xx) · **(b) `200 + {error}` body swallowed**
(pbGet/pbPost) · **(c) `{ok:bool}` / `{error:str}` payloads read inline**. No
handler attaches an auth/CSRF/token header (contractual by omission).

---

## 2. Legend

- **Regime** — the transport wrapper's error behaviour:
  `throw` (get/post, `api.ts:18-32`) · `swallow` (pbGet/pbPost, `api.ts:787-799`) ·
  `bespoke-throw` (raw `fetch` that throws) · `bespoke-swallow` (raw `fetch` that
  reads `res.json()` without throwing).
- **Guard** — how the *primary* consumer handles the call:
  `try` (inside `try{…}catch`) · `.catch` (promise `.catch`/`.finally` chain) ·
  `useApi` (wrapped by the `hooks/useApi.ts` error-capturing hook) ·
  `no-throw-ok` (no `try`/`.catch`, but regime never throws → safe) ·
  **`UNGUARDED`** (throw-regime call with no `try`/`.catch` → RISK) ·
  `unused` (no component consumer).
- **020 match** — the backend twin row ID from
  `viz_api_contract_inventory.md` (`G#` GET / `P#` POST). `— DRIFT` = no backend
  branch (§F.1).
- **Type source** — `T:LINE` = `types/index.ts:LINE`; `A:LINE` = inline in
  `api.ts:LINE`; `inline` = anonymous object literal in the signature.

---

## A. Wrapper table (79 rows, ordered by `api.ts` definition line)

| # | Wrapper (`api.ts:LINE`) | Method + path template | Req body | Resp type | Regime | Consumer(s) (`file:line`) | Guard | 020 |
|---|---|---|---|---|---|---|---|---|
| 1 | `fetchState` (:36) | GET `/state` | none | `AppState` (T:87) | throw | `AppContext.tsx:63`; `IdeaPage.tsx:54` | try / .catch | G5 |
| 2 | `fetchExperimentDetail` (:40) | GET `/api/experiment-detail` | none | `{experiment_detail_config?}` (A:41)→`string` | throw | `monitorSections.tsx:75`; `IdeaPage.tsx:59` | .catch | G34 |
| 3 | `fetchCheckpoints` (:45) | GET `/api/checkpoints` | none | `Checkpoint[]` (T:24) | throw | `AppContext.tsx:53`; `SettingsPage.tsx:173`; `StepLaunch.tsx:218` | try | G13 |
| 4 | `fetchCheckpointSummary` (:49) | GET `/api/checkpoint/{id}/summary` (enc) | none | `CheckpointSummary` (T:237) | throw | `ResultsPage.tsx:100` (try); **`ExperimentsPage.tsx:53`** | try / **UNGUARDED** | G16 |
| 5 | `fetchCheckpointMemory` (:72) | GET `/api/checkpoint/{id}/memory` (enc) | none | `MemoryResponse` (A:62) | throw | `useDetailPanelData.ts:68` | .catch | G17 |
| 6 | `fetchMemoryAccess` (:94) | GET `/api/checkpoint/{id}/memory_access?node_id&op&limit` (enc) | none | `MemoryAccessResponse` (A:86) | throw | `useDetailPanelData.ts:111` | .catch | G18 |
| 7 | `fetchNodeReport` (:162) | GET `/api/nodes/{runId}/{nodeId}/report` (enc) | none | `NodeReportResponse` (A:155) | throw | `useDetailPanelData.ts:146,173` | .catch | G27 |
| 8 | `fetchEAR` (:201) | GET `/api/ear/{runId}` (enc) | none | `EARData` (A:189) | throw | `ResultsPage.tsx:121`; `EarSection.tsx:129,232,251` | try | G26 |
| 9 | `curateEAR` (:217) | POST `/api/ear/{runId}/curate` (enc) | `{}` | `EARCurateResult` (A:206) | throw | `EarSection.tsx:116,239` | try | P15 |
| 10 | `fetchPublishYaml` (:243) | GET `/api/ear/{runId}/publish-yaml` (enc) | none | `PublishYamlResponse` (A:234) | throw | `EarSection.tsx:178` | try | G25 |
| 11 | `savePublishYaml` (:247) | POST `/api/ear/{runId}/publish-yaml` (enc) | `{text?,data?}` | `PublishYamlResponse` (A:234) | throw | `EarSection.tsx:221` | try | P16 |
| 12 | `cloneVerifyBundle` (:273) | POST `/api/ear/clone-verify` | `CloneVerifyRequest` (A:258) | `CloneVerifyResult` (A:264) | throw | — | unused | P17 |
| 13 | `fetchPublishSettings` (:334) | GET `/api/publish/settings` | none | `PublishSettings` (A:278) | throw | — | unused | G29 |
| 14 | `savePublishSettings` (:337) | POST `/api/publish/settings` | `PublishSettings` (A:278) | `{ok?,error?}` (inline) | throw | — | unused | P18 |
| 15 | `previewPublish` (:340) | GET `/api/publish/{runId}/preview` (enc) | none | `PublishPreview` (A:287) | throw | — | unused | G30 |
| 16 | `runPublish` (:343) | POST `/api/publish/{runId}` (enc) | `PublishRunRequest` (A:300) | `PublishRunResult` (A:308) | throw | `EarSection.tsx:303` | try | P20 |
| 17 | `promotePublish` (:346) | POST `/api/publish/{runId}/promote` (enc) | `{target}` | `{ref?,visibility?,error?}` (inline) | throw | `EarSection.tsx:333` | try | P19 |
| 18 | `fetchPublishRecord` (:349) | GET `/api/publish/{runId}/record` (enc) | none | `PublishRecord` (A:320) | throw | `EarSection.tsx:315,336` | try | G31 |
| 19 | `deleteCheckpoint` (:353) | POST `/api/delete-checkpoint` | `{id,path}` | `{ok,error?}` (inline) | throw | `SettingsPage.tsx:301` | try | P36 |
| 20 | `switchCheckpoint` (:360) | POST `/api/switch-checkpoint` | `{path}` | `{ok,error?}` (inline) | throw | `Sidebar.tsx:60` (try); `StepLaunch.tsx:192,223` | try / .catch | P14 |
| 21 | `fetchActiveCheckpoint` (:366) | GET `/api/active-checkpoint` | none | `{id?,path?}` (inline) | throw | — | unused | G35 |
| 22 | `fetchSettings` (:372) | GET `/api/settings` | none | `Settings` (T:38) | throw | `SettingsPage.tsx:120` (try); `WizardPage.tsx:149` (.catch) | try / .catch | G28 |
| 23 | `saveSettings` (:376) | POST `/api/settings` | `Partial<Settings>` (T:38) | `{ok,error?}` (inline) | throw | `SettingsPage.tsx:263` (as `apiSaveSettings`) | try | P1 |
| 24 | `fetchEnvKeys` (:382) | GET `/api/env-keys` | none | `{keys:Record<string,string>}` (inline) | throw | `StepResources.tsx:340` | try | G11 |
| 25 | `fetchMemoryHealth` (:398) | GET `/api/memory/health` | none | `MemoryHealth` (A:388) | throw | — | unused | G19 |
| 26 | `restartLetta` (:402) | POST `/api/memory/restart` | `{path='auto'}` | `{ok,start?,stop?,error?}` (inline) | throw | `SettingsPage.tsx:657` | try | P4 |
| 27 | `fetchProfiles` (:413) | GET `/api/profiles` | none | `string[]` | throw | — | unused | G32 |
| 28 | `fetchRubrics` (:426) | GET `/api/rubrics` | none | `RubricSummary[]` (A:417) | throw | `StepResources.tsx:205` | .catch | G14 |
| 29 | `fetchFewshot` (:445) | GET `/api/fewshot/{rubricId}` (enc) | none | `FewshotListing` (A:438) | throw | `stepResourcesSections.tsx:159` | .catch | G15 |
| 30 | `syncFewshot` (:449) | POST `/api/fewshot/{rubricId}/sync` (enc) | `{}` | `any` | throw | `stepResourcesSections.tsx:178` | try | P21 |
| 31 | `uploadFewshot` (:453) | POST `/api/fewshot/{rubricId}/upload` (enc) | `{example_id,review_json,paper_txt?,paper_pdf?}` | `any` | throw | `stepResourcesSections.tsx:212` | try | P22 |
| 32 | `deleteFewshot` (:465) | POST `/api/fewshot/{rubricId}/{exampleId}/delete` (enc) | `{}` | `any` | throw | `stepResourcesSections.tsx:239` | try | P23 |
| 33 | `fetchSkills` (:479) | GET `/api/skills` | none | `any[]` | throw | `SettingsPage.tsx:164` | try | G38 |
| 34 | `fetchSkillDetail` (:483) | GET `/api/skill/{name}` (enc) | none | `any` | throw | `WorkflowPage.tsx:378` | .catch | G37 |
| 35 | `fetchWorkflow` (:487) | GET `/api/workflow` | none | `WorkflowData` (T:159) | throw | `WorkflowPage.tsx:76` | .catch (@144) | G36 |
| 36 | `saveWorkflow` (:491) | POST `/api/workflow` | `{path,pipeline}` | `{ok,error?}` (inline) | throw | — | unused | P37 |
| 37 | `runStage` (:500) | POST `/api/run-stage` | `{stage}` | `{ok,pid?,error?}` (inline) | throw | `MonitorPage.tsx:100` (as `apiRunStage`) | try | P7 |
| 38 | `stopExperiment` (:506) | POST `/api/stop` | `{}` | `any` | throw | `MonitorPage.tsx:117` | try | P31 |
| 39 | `launchExperiment` (:510) | POST `/api/launch` | `any` (~50-key launch cfg) | `{ok,pid?,error?,checkpoint_path?}` (inline) | throw | `StepLaunch.tsx:135` | try | P5 |
| 40 | `chatGoal` (:518) | POST `/api/chat-goal` | `{messages}` | `{reply?,ready?,md?,error?}` (inline) | throw | `StepGoal.tsx:80` | try | P9 |
| 41 | `generateConfig` (:524) | POST `/api/config/generate` | `{goal}` | `any` | throw | `StepGoal.tsx:122`; `SettingsPage.tsx:276` | try | P8 |
| 42 | `uploadFile` (:530) | POST `/api/upload` (octet-stream; `X-Filename`,`X-File-Type`) | raw `File` bytes | `{ok,path?,filename?,error?}` (inline) | bespoke-throw | `StepGoal.tsx:165` | try | P10 |
| 43 | `deleteUploadedFile` (:547) | POST `/api/upload/delete` | `{filename}` | `{ok,error?}` (inline) | throw | `StepGoal.tsx:144` | try | P11 |
| 44 | `testSSH` (:555) | POST `/api/ssh/test` | `any` (ssh_* fields) | `{ok,info?,error?}` (inline) | throw | `SettingsPage.tsx:289` (as `apiTestSSH`) | try | P13 |
| 45 | `detectScheduler` (:561) | GET `/api/scheduler/detect` | none | `{scheduler,partitions}` (inline) | throw | `MonitorPage.tsx:45`; `StepResources.tsx:271` | .catch | G44 |
| 46 | `fetchPartitions` (:565) | GET `/api/slurm/partitions` | none | `any[]` | throw | `SettingsPage.tsx:213` | try | G45 |
| 47 | `fetchOllamaResources` (:571) | GET `/api/ollama-resources` | none | `{gpus,models}` (inline) | throw | `StepResources.tsx:313` | .catch | G12 |
| 48 | `fetchGpuMonitor` (:575) | GET `/api/gpu-monitor` | none | `{running,pid?,log?,ollama_host?}` (inline) | throw | `GpuMonitor.tsx:21` | try | G6 |
| 49 | `gpuMonitorAction` (:584) | POST `/api/gpu-monitor` | `{action,confirmed:true}` | `any` | throw | `GpuMonitor.tsx:50,60` | try | P30 |
| 50 | `fetchResourceMetrics` (:590) | GET `/api/resource-metrics` | none | `ResourceMetrics` (T:174) | throw | `MonitorPage.tsx:57` | .catch | G39 |
| 51 | `fetchContainerInfo` (:596) | GET `/api/container/info` | none | `{runtime,version,available}` (inline) | throw | `SettingsPage.tsx:317`; `StepResources.tsx:302` | try / .catch | G40 |
| 52 | `fetchContainerImages` (:609) | GET `/api/container/images` | none | `{images:ContainerImage[]}` (A:604) | throw | `StepResources.tsx:378` | try | G41 |
| 53 | `pullContainerImage` (:613) | POST `/api/container/pull` | `{image,mode}` | `{ok,error?}` (inline) | throw | `StepResources.tsx:390` | try | P41 |
| 54 | `fetchCheckpointFiles` (:630) | GET `/api/checkpoint/{id}/files` (enc) | none | `{id,path,files:CheckpointFile[],error?}` (A:622) | throw | `ResultsPage.tsx:168` | try | G21 |
| 55 | `fetchCheckpointFileContent` (:636) | GET `/api/checkpoint/{id}/file?name` (enc) | none | `{name,content,error?}` (inline) | throw | `ResultsPage.tsx:179` | try | G22a |
| 56 | `fetchCheckpointFilecontent` (:643) | GET `/api/checkpoint/{id}/filecontent?path&node_id` (enc) | none | `{name?,content?,error?}` (inline) | throw | `ResultsPage.tsx:150`; `FileExplorer.tsx:211`; `resultSections.tsx:703` | try / .catch | G24 |
| 57 | `fetchCheckpointFiletree` (:656) | GET `/api/checkpoint/{id}/filetree?node_id` (enc) | none | `{tree?,error?}` (inline) | throw | `FileExplorer.tsx:179` | .catch | G23 |
| 58 | `saveCheckpointFile` (:664) | POST `/api/checkpoint/file/save` | `{checkpoint_id,filename,content}` | `{ok,error?}` (inline) | throw | `ResultsPage.tsx:201` | try | P32 |
| 59 | `uploadCheckpointFile` (:676) | POST `/api/checkpoint/{id}/file/upload` (octet-stream; `X-Filename`) | raw `File` bytes | `{ok,name?,error?}` (inline) | bespoke-throw | `ResultsPage.tsx:225` | try | P35 |
| 60 | `deleteCheckpointFile` (:692) | POST `/api/checkpoint/file/delete` | `{checkpoint_id,filename}` | `{ok,error?}` (inline) | throw | `ResultsPage.tsx:247` | try | P33 |
| 61 | `compileCheckpointPaper` (:702) | POST `/api/checkpoint/compile` | `{checkpoint_id,main_file}` | `{ok,log}` (inline) | throw | `ResultsPage.tsx:273` | try | P34 |
| 62 | `fetchWorkflowFlow` (:714) | GET `/api/workflow/flow` | none | `any` | throw | `WorkflowPage.tsx:76` | .catch (@144) | G43 |
| 63 | `saveWorkflowFlow` (:718) | POST `/api/workflow/flow` | `any` (`{flow}`) | `{ok,error?}` (inline) | throw | `WorkflowPage.tsx:193,268` | .catch | P38 |
| 64 | `fetchWorkflowDefault` (:722) | GET `/api/workflow/default` | none | `any` | throw | `WorkflowPage.tsx:280` | .catch | G42 |
| 65 | `saveSkillPhases` (:726) | POST `/api/workflow/skills` | `{skills:[{name,phase}]}` | `{ok,error?}` (inline) | throw | `WorkflowPage.tsx:756` | .catch | P39 |
| 66 | `saveDisabledTools` (:732) | POST `/api/workflow/disabled-tools` | `{disabled_tools}` | `{ok,error?}` (inline) | throw | `WorkflowPage.tsx:870` | .catch | P40 |
| 67 | `fetchModels` (:740) | GET `/api/models` | none | `any` | throw | — | unused | G9 |
| 68 | `fetchSubExperiments` (:761) | GET `/api/sub-experiments` | none | `{sub_experiments:SubExperiment[]}` (A:746) | throw | `ExperimentsPage.tsx:30` | .catch | G47 |
| 69 | `fetchSubExperiment` (:765) | GET `/api/sub-experiments/{runId}` (enc) | none | `SubExperiment` (A:746) | throw | — | unused | G48 |
| 70 | `launchSubExperiment` (:769) | POST `/api/sub-experiments/launch` | `{experiment_md,max_recursion_depth?,parent_run_id?,recursion_depth?,inherit_idea_index?}` | `{ok,run_id?,pid?,error?}` (inline) | throw | — | unused | P6 |
| 71 | `fetchPaperbenchPapers` (:803) | GET `/api/paperbench/papers` | none | `{papers?,error?}` (inline) | swallow (pbGet) | `PaperRegistryPage.tsx:37`; `PaperBenchWizard.tsx:104` | useApi / no-throw-ok | G50 |
| 72 | `deletePaperbenchPaper` (:810) | POST `/api/paperbench/papers/{id}/delete` (enc; **no body/Content-Type**) | none | `{deleted?,error?,reason?}` (inline) | bespoke-swallow | `PaperRegistryPage.tsx:53` | no-throw-ok | P25 |
| 73 | `estimatePaperbenchCost` (:820) | POST `/api/paperbench/cost-estimate` | `{rubric_config,reproduce_config,judge_config}` | `any` | swallow (pbPost) | `PaperBenchWizard.tsx:109` | .catch | P28 |
| 74 | `runPaperbench` (:828) | POST `/api/paperbench/run` | `unknown` | `{job_ids?,error?}` (inline) | swallow (pbPost) | `PaperBenchWizard.tsx:131` | no-throw-ok | P27 |
| 75 | `fetchArxivMetadata` (:834) | GET `/api/paperbench/arxiv/{source}` (enc) | none | `{title?,authors?,year?,license?,error?}` (inline) | swallow (pbGet) | `PaperImportDialog.tsx:54` | try | G51 |
| 76 | `importPaperbenchPaper` (:844) | POST `/api/paperbench/papers/import` | `Record<string,unknown>` | `any` | swallow (pbPost) | `PaperImportDialog.tsx:129` | try | P24 |
| 77 | `fetchPaperbenchRun` (:849) | GET `/api/paperbench/run/{jobId}` (**NOT enc**, :848) | none | `any` | swallow (pbGet) | `ResultsView.tsx:77,111` | try / no-throw-ok | G56 |
| 78 | `fetchPaperbenchRunResults` (:853) | GET `/api/paperbench/run/{jobId}/results` (**NOT enc**) | none | `any` | swallow (pbGet) | `ResultsView.tsx:84` | try | G54 |
| 79 | `requestPaperbenchReport` (:857) | POST `/api/paperbench/run/{jobId}/report` (**NOT enc**) | `{languages,formats}` | `{download_urls?,error?}` (inline) | swallow (pbPost) | `ResultsView.tsx:122` | try | **G55 GET-only — DRIFT F6a** |

**Regime tally:** 57 `throw` (get/post) · 6 `swallow` (pbGet/pbPost) · 2
`bespoke-throw` (uploadFile, uploadCheckpointFile) · 1 `bespoke-swallow`
(deletePaperbenchPaper). (Rows 71–79 are the PaperBench no-throw set except that
`deletePaperbenchPaper` is a bespoke bare fetch.)

**Guard tally:** the **only UNGUARDED throw-regime call site** is
`ExperimentsPage.tsx:53` — `fetchCheckpointSummary(id).then((d)=>{…navigateTo('tree')})`
with **no `.catch`** (confirmed `ExperimentsPage.tsx:53-62`). A rejected promise
here becomes an unhandled rejection (it does **not** reach the `ErrorBoundary`,
which only catches render-phase throws). Every other throw-regime consumer is
inside a `try{…}catch` or a `.catch`/`.finally` chain. This is the single
FE-side robustness finding for 063/064 to note (record only; do not fix here).

---

## B. Endpoint-family index (seams for 063's `api.ts` split)

Grouped as the FE uses them, so 063 can split `services/api.ts` by family without
changing wrapper names:

1. **State / tree** — `fetchState` (G5), `fetchExperimentDetail` (G34),
   `fetchResourceMetrics` (G39), `fetchActiveCheckpoint` (G35, unused),
   `fetchModels` (G9, unused). *(WS + polling are §E.)*
2. **Checkpoints (list + summary)** — `fetchCheckpoints` (G13),
   `fetchCheckpointSummary` (G16), `deleteCheckpoint` (P36),
   `switchCheckpoint` (P14).
3. **Checkpoint files (Overleaf-like)** — `fetchCheckpointFiles` (G21),
   `fetchCheckpointFileContent` (G22a), `fetchCheckpointFilecontent` (G24),
   `fetchCheckpointFiletree` (G23), `saveCheckpointFile` (P32),
   `deleteCheckpointFile` (P33), `uploadCheckpointFile` (P35),
   `compileCheckpointPaper` (P34).
4. **Memory** — `fetchCheckpointMemory` (G17), `fetchMemoryAccess` (G18),
   `fetchMemoryHealth` (G19, unused), `restartLetta` (P4).
5. **Node report** — `fetchNodeReport` (G27).
6. **EAR** — `fetchEAR` (G26), `curateEAR` (P15), `fetchPublishYaml` (G25),
   `savePublishYaml` (P16), `cloneVerifyBundle` (P17, unused).
7. **Publish** — `fetchPublishSettings` (G29, unused),
   `savePublishSettings` (P18, unused), `previewPublish` (G30, unused),
   `runPublish` (P20), `promotePublish` (P19), `fetchPublishRecord` (G31).
8. **Settings / env** — `fetchSettings` (G28), `saveSettings` (P1),
   `fetchEnvKeys` (G11).
9. **Skills / workflow** — `fetchSkills` (G38), `fetchSkillDetail` (G37),
   `fetchWorkflow` (G36), `saveWorkflow` (P37, unused),
   `fetchWorkflowFlow` (G43), `saveWorkflowFlow` (P38),
   `fetchWorkflowDefault` (G42), `saveSkillPhases` (P39),
   `saveDisabledTools` (P40).
10. **Rubrics / few-shot / profiles** — `fetchRubrics` (G14),
    `fetchProfiles` (G32, unused), `fetchFewshot` (G15), `syncFewshot` (P21),
    `uploadFewshot` (P22), `deleteFewshot` (P23).
11. **Experiment lifecycle** — `runStage` (P7), `stopExperiment` (P31),
    `launchExperiment` (P5), `launchSubExperiment` (P6, unused),
    `fetchSubExperiments` (G47), `fetchSubExperiment` (G48, unused).
12. **Wizard / chat / upload** — `chatGoal` (P9), `generateConfig` (P8),
    `uploadFile` (P10), `deleteUploadedFile` (P11).
13. **Infra probes** — `testSSH` (P13), `detectScheduler` (G44),
    `fetchPartitions` (G45), `fetchOllamaResources` (G12), `fetchGpuMonitor` (G6),
    `gpuMonitorAction` (P30), `fetchContainerInfo` (G40),
    `fetchContainerImages` (G41), `pullContainerImage` (P41).
14. **PaperBench (the pbGet/pbPost no-throw family)** — `fetchPaperbenchPapers`
    (G50), `deletePaperbenchPaper` (P25), `estimatePaperbenchCost` (P28),
    `runPaperbench` (P27), `fetchArxivMetadata` (G51),
    `importPaperbenchPaper` (P24), `fetchPaperbenchRun` (G56),
    `fetchPaperbenchRunResults` (G54), `requestPaperbenchReport` (G55/DRIFT).

---

## C. Inline-`fetch` / stream / WebSocket / direct-URL appendix

Dependencies **not** routed through a typed `api.ts` wrapper. These are contract
dependencies invisible to a wrapper-only inventory.

### C.1 Inline `fetch` / `EventSource` / `WebSocket` in `components/**` + `hooks/**`

`grep -rnE 'fetch\(|EventSource\(|new WebSocket\('` → 4 sites (excluding the 4
`api.ts` transport helpers and the 3 bespoke wrappers, which live in `api.ts`):

| Site | Kind | Path | Shape parsed | Guard | 020 |
|---|---|---|---|---|---|
| `Monitor/MonitorPage.tsx:163` | `fetch` (SSE, `res.body.getReader()`) | `GET /api/logs` | `text/event-stream` `data:{msg}` lines | `try` (`:159-166`); "justified direct-fetch (req 02)" | G46 |
| `PaperBench/results/ResultsView.tsx:100` | `new EventSource` | `GET /api/paperbench/run/{jobId}/logs` | `event: log` (JSON row) / `event: done`; `onerror→close` | listeners guard `JSON.parse`; `done`→`fetchPaperbenchRun` | G53 |
| `PaperBench/PaperImportDialog.tsx:77` | `fetch` (multipart `FormData`) | `POST /api/upload` | `{ok?,path?,error?}` | `throw`-on-`!ok`; caller `try` (`stageUpload`) | P10 |
| `hooks/useWebSocket.ts:47` | `new WebSocket` | `ws://{host}:{httpPort+1}/` | `{type?,data?:{nodes?}}` | `try/catch` on ctor + `onmessage` | WS (§E) |

Note the `PaperImportDialog:77` multipart POST to `/api/upload` is a **second,
distinct contract** for the same backend endpoint as the `uploadFile` wrapper
(`api.ts:530`, octet-stream + `X-Filename`): the backend `_api_upload_file`
(P10) must accept **both** `multipart/form-data` (field `file`) and the
octet-stream + `X-Filename` form. 063 must not collapse these without
verifying the backend handles both.

### C.2 Direct-URL (browser-native) backend dependencies (`<img>`/`<a>`/`<iframe>`)

Not `fetch` calls, but hard wire dependencies on backend routes:

| Site(s) | Element | Path | 020 |
|---|---|---|---|
| `resultSections.tsx:1114` (`<img src>`); `EarSection.tsx:61,418` (`<a href>`); `PaperWorkspace.tsx:77` (preview URL) | image/link | `GET /codefile?path={enc}` | G8 |
| `PaperWorkspace.tsx:319` (`<a href download>`), `:363` (`<iframe/embed src>`) | pdf embed/download | `GET /api/checkpoint/{id}/paper.pdf` (enc) | G10 |

(Static asset serves `/`, `/index.html`, `/static/<path>`, `/logo.png` — G1–G3 —
are page-load/asset dependencies, not app-code calls.)

---

## D. Type catalog

### D.1 `types/index.ts` (14 exported, 264 LOC)

| Type (`:LINE`) | Fields | Fragile-field annotations (maintainers' own drift notes — preserve verbatim) |
|---|---|---|
| `TreeNode` (:3) | 18 | consumed by WS + `/state` + summary; nullable analytic fields |
| `Checkpoint` (:24) | 6 (+2 opt) | **`best_metric?` "Always emitted … but never reassigned from its `null` init"** (`:31-33`); `best_scientific_score?` "Conditional: only present when tree nodes carry `metrics._scientific_score`" (`:34-35`) |
| `Settings` (:38) | 35 | flat `/api/settings` object; incl. `model_idea/bfts/coding/eval/paper/review` + `vlm_review_*` **declared but with no SettingsPage UI** (Phase-6/067); `llm_base_url?` optional |
| `CostSummary` (:79) | 5 | shape of `{checkpoint}/cost_summary.json`, surfaced verbatim as `AppState.cost` |
| `AppState` (:87) | 24 (+11 opt/alias) | **`cost?` is the parsed `CostSummary` object, NOT a number** (`:106-109`); tail always-present `exit_code?` (`:117`); **JS-compat aliases `running?`/`pid?`/`llm_model?`** (`:118-120`); conditional `phase_flags?/experiment_md_path?/workflow_yaml?/best_nodes?/all_metric_keys?/summary_stats?/typed_split_sources?` (`:121-128`) |
| `WizardState` (:131) | 4 | FE-local wizard state (not a response type) |
| `WorkflowStage` (:138) | 12 (+3 opt) | stage `phase` single string; `pre_tool?/post_tool?/react?` for react-driver stages (`:153-156`) |
| `WorkflowData` (:159) | 9 | `fetchWorkflow` decode (`{ok,error}` envelope + pipelines) |
| `ResourceMetrics` (:174) | 8 | `fetchResourceMetrics` |
| `ReviewScoreDimension` (:185) | 4 | nested in `ReviewReport` |
| `ReviewDecision` (:196) | union+`string` | **"Do NOT remove `\| string`"** (`:192-202`) — keeps resolved type `string` |
| `ReviewReport` (:204) | 25 | `CheckpointSummary.review_report`; deeply optional |
| `ReproReport` (:235) | union | **legacy runs: `string`; post-§4.1: object** (`:231-234`) |
| `CheckpointSummary` (:237) | 9 (+9 opt) | `id?/path?` echoed; `reproducibility_report?` **object or (legacy) string, only when present** (`:247-249`); **`repro?` "Vestigial alias … the backend no longer emits `repro`"** (`:250-251`); `ors_*?`/`vlm_review?` conditional PaperBench payloads (`:254-262`) |

### D.2 Inline `api.ts` response/request types (28 exported)

Request types: `CloneVerifyRequest` (:258), `PublishRunRequest` (:300).
Response types: `MemoryEntry` (:53), `MemoryResponse` (:62),
`MemoryAccessEvent` (:76), `MemoryAccessResponse` (:86),
`NodeReportFilesChanged` (:107), `NodeReportSelfAssessment` (:118),
`NodeReport` (:124), `NodeReportResponse` (:155), `EARFile` (:172),
`EARPublishedSummary` (:178), `EARData` (:189), `EARCurateResult` (:206),
`PublishYamlData` (:222), `PublishYamlResponse` (:234), `CloneVerifyResult` (:264),
`PublishSettings` (:278), `PublishPreview` (:287), `PublishRunResult` (:308),
`PublishRecord` (:320), `MemoryHealth` (:388), `RubricSummary` (:417),
`FewshotExample` (:430), `FewshotListing` (:438), `ContainerImage` (:604),
`CheckpointFile` (:622), `SubExperiment` (:746).

**Split finding (Problem #2):** response shapes live in **two files with no single
source of truth** — 14 in `types/index.ts`, 26 response/request interfaces inline
in `api.ts`, plus ~20 anonymous inline object literals in wrapper signatures
(e.g. rows 21, 24, 26, 40, 45, 47, 48, 51, 55, 56, 57). There is no
generated/backend-shared schema; every TS type is a hand-maintained mirror of an
ad-hoc backend dict. 061 quantifies from this catalog; 063 consolidates.

---

## E. Cross-cutting invariants (contractual by omission — KEEP)

1. **No auth / CSRF / token / `Authorization` header anywhere.**
   `grep -niE 'auth|token|csrf|Authorization|Bearer' api.ts` matches only the
   unrelated data fields `registries[].token?` (`:281`) and `authors?` (`:836`).
   Every call — incl. `deleteCheckpoint` (P36), `saveSettings` (P1, persists API
   keys to `.env`), `fetchEnvKeys` (G11, returns real secret values),
   `gpuMonitorAction` (P30, SLURM auto-resubmit, **always sends `confirmed:true`**,
   `api.ts:585`) — is unauthenticated. Recorded as a contract fact; **not** fixed
   here (Phase-6 071 policy).
2. **`API_BASE = ''`** (`api.ts:14`) — same-origin; the FE never prefixes a host.
3. **POST `Content-Type: application/json`** for `post`/`pbPost` (`api.ts:27,795`).
   Exceptions: `uploadFile`/`uploadCheckpointFile` send
   `application/octet-stream` + `X-Filename` (+`X-File-Type`);
   `deletePaperbenchPaper` sends **no body and no Content-Type**;
   `PaperImportDialog:77` sends `multipart/form-data`.
4. **`encodeURIComponent` on path params** (27 sites) — with an **intentional
   exception**: `fetchPaperbenchRun`/`...Results`/`requestPaperbenchReport` do
   **NOT** encode `jobId` ("to match the original call sites verbatim",
   `api.ts:848-850`). 063 must not "helpfully" add encoding without checking the
   backend job-id parsing.
5. **WebSocket push contract** (`useWebSocket.ts`): URL
   `${proto}//${host}:${httpPort+1}/` (`:36-43`), single inbound message type
   `{type?,data?:{nodes?:TreeNode[]}}` (`:12-15,58-64`); client reads
   `msg.data.nodes`; inbound-only (no client→server frames); exponential-backoff
   reconnect 1 s→30 s (`:29-31,54-57,72-76`). Matches 020 §5.2 and backend
   `websocket.py:26-29` / `state_sync.py:45-46`.
6. **Polling fallback** (`AppContext.tsx`): `STATE_POLL_MS = 5000` (`:34`); every
   5 s calls `fetchState()` + `fetchCheckpoints()` (`:86-89`); prefers WS nodes
   when non-empty, else `state.nodes` (`:96`).
7. **Tri-modal response convention** — thrown `Error` (get/post) · swallowed
   `200 + {error}` (pbGet/pbPost) · inline `{ok}`/`{error}` payloads. 061/063 must
   preserve all three or migrate both sides in lockstep.

**Schema-guard grounding** (`ari-core/tests/test_api_schema_contract.py`,
verified 2026-06-30): pins the **always-present subset** of three endpoints —
`/api/checkpoints` item keys `id,path,status,node_count,review_score,best_metric,mtime`
(`best_metric is None`), `:53-57`; `/api/checkpoint/<id>/summary` base keys
`id,path,nodes_tree.nodes` and the exact not-found sentinel `{"error":"not found"}`
(`:69-78`); `/api/settings` keys
`llm_model,llm_provider,ollama_host,temperature,retrieval_backend,slurm_partition,slurm_walltime,container_mode,container_pull,vlm_review_enabled,vlm_review_model,letta_base_url,letta_embedding_config,ors` (+ `ors.judge_model`), `:89-98`, with
`{**defaults, **saved}` passthrough. **`GET /state` is NOT pinned by an explicit
test** — its shape is guarded only structurally by `AppState` (T:87) and 010 §4
Contract B; 063/065 should add a `/state` subset guard.

---

## F. Drift report (FE ↔ 020 backend)

### F.1 FE calls with no matching backend branch (FE→BE drift)

- **F6a (high, confirmed against 020 G55):** `requestPaperbenchReport`
  (row 79, `api.ts:857-861`) **POSTs** `/api/paperbench/run/{jobId}/report`, but
  `do_POST` has **no** `/report` branch — only `do_GET` matches `/report`
  (020 **G55**, `api_paperbench.py:707`). A POST falls through to the `do_POST`
  `else` 404 (`routes.py:1187`); because `pbPost` never throws, the empty 404
  body then makes `res.json()` reject with an *unhandled* parse error inside the
  `ResultsView:122` `try` (which catches it and sets `error`). Verify the
  intended method before 062/063 touch it. **Tag: REVIEW_REQUIRED.** No fix here.

All other 78 wrappers map 1:1 to a live backend branch (§A "020" column). No
other FE→BE drift.

### F.2 Backend endpoints with no `api.ts` wrapper (BE→FE drift; = 020 F6b)

Endpoints 020 lists that **no** FE wrapper calls (candidate
`REVIEW_REQUIRED`/`DELETE_CANDIDATE` for a later phase — flagged, never deleted
here):

- `GET /memory/<node_id>` (G4, legacy) · `GET /api/memory/detect` (G20) ·
  `POST /api/memory/start-local` (P2) · `POST /api/memory/stop-local` (P3) ·
  `GET /api/paperbench/papers/<id>/license` (G52) ·
  `POST /api/paperbench/papers/<id>/metadata` (P26) ·
  `POST /api/env-keys` (P12 — the **GET** side is wrapped as `fetchEnvKeys`, the
  **POST** side is not) · `GET /api/checkpoint/<id>/file/raw` (G22b) ·
  `GET /api/upload` (G33, stub) · `GET /api/lineage-decisions/<ckpt>` (G49 —
  `grep` of `components/**` confirms **no** FE consumer at all, correcting 020's
  "component inline fetch, unverified"). **Tag: REVIEW_REQUIRED per endpoint.**

Not drift (consumed via `EventSource`/direct URL, §C): `/api/logs` (G46),
PaperBench logs (G53), `/codefile` (G8), `paper.pdf` (G10).

### F.3 FE wrappers that are exported but **unused** (dead client surface — 11)

Live backend endpoint exists, but **no** component/hook/context calls the wrapper
(confirmed by name grep across `components/**`+`hooks/**`+`context/**`):

`cloneVerifyBundle` (P17) · `fetchPublishSettings` (G29) ·
`savePublishSettings` (P18) · `previewPublish` (G30) ·
`fetchActiveCheckpoint` (G35) · `fetchMemoryHealth` (G19) · `fetchProfiles` (G32)
· `saveWorkflow` (P37 — only `saveWorkflowFlow` is used) · `fetchModels` (G9) ·
`fetchSubExperiment` (G48, singular — only `fetchSubExperiments` is used) ·
`launchSubExperiment` (P6).

These are **not** wire drift (the backend serves them); they are
tree-shake/`REVIEW_REQUIRED` candidates for **063** ("unused export"). Do not
delete here — some (e.g. `fetchMemoryHealth`, `previewPublish`) are plausibly
staged for near-term UI and several are exercised by tests/external callers.

### F.4 Field-level fragility (already annotated in `types/index.ts`; see §D)

`AppState.cost` (object, not number), `AppState.running/pid/llm_model` aliases,
`AppState.exit_code`; `Checkpoint.best_metric` (always-`null`),
`Checkpoint.best_scientific_score` (conditional); `CheckpointSummary.repro`
(vestigial — backend no longer emits), `.reproducibility_report` (object|string),
`.ors_*`/`.vlm_review` (conditional). 062/063 must not drop these
optional/aliased/vestigial fields.

---

## G. Verification performed (read-only gates)

- `grep -cE '^export (async function|function) ' services/api.ts` → **79**
  (matches Section 0 and this doc's row count).
- `python -m compileall ari-core/ari/viz` → exit 0 (no source touched).
- `ruff check ari-core/ari/viz/routes.py` → only the **pre-existing** repo
  baseline findings (no new findings; no `.py` edited). Full `pytest` is run
  centrally by the orchestrator, not here.
- **Frontend build state is unchanged** — this subtask modified **zero** files
  under `ari-core/ari/viz/frontend/`, so `npm run typecheck`/`build`/`test`
  baselines are unaffected. (Packages are not installed per the planning-phase
  hard rule; nothing FE-side was edited to require re-checking.)
- `git status --porcelain` shows only this file and its `.json` sibling under
  `docs/refactoring/reports/` as attributable to subtask 060; no change under
  `ari-core/` or any runtime path.

---

## H. Retirement Condition

This artifact is a **temporary planning artifact** of subtask 060 and the frozen
FE-side baseline consumed by 061/062/063/064/065. It may be archived/`git rm`-ed
only after **all** of: (1) subtask 060 §13 Acceptance Criteria are met; (2) the
implementing PR is merged into `main`; (3)
`docs/refactoring/007_subtask_index.md` marks 060 **DONE**. Until then: **KEEP**.
Verify each condition against primary sources before removal (canonical policy:
`007_subtask_index.md` "Document Retirement Policy").
