# Dashboard UX Refactoring Plan

> **Status:** PLANNING ONLY — no runtime code, imports, prompts, configs, workflows, frontend, or directory names are modified by this document. The only artifact produced here is this `.md` file.
> **Scope root:** `ari-core/ari/viz/frontend/` (React 18.3 + TypeScript 5.5 + Vite 5 SPA) and its backend contract `ari-core/ari/viz/routes.py` + `api_*.py`.
> **Planning date:** 2026-07-01 · **ari-core version:** 0.9.0 · **Branch:** main
> **Classification vocabulary:** KEEP / ADAPT / MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED.
> **Word "deprecated"** is reserved in this document for external contracts (dashboard API endpoints/schema, CLI, MCP tool contracts, `ari.public.*`, documented import paths, ari-skill stable interfaces). It is never applied to internal UI code.

## 1. Purpose

The ARI dashboard is a single-page React app served by the FastAPI backend in `ari-core/ari/viz/` (backend: `routes.py`, 1197 lines, plus 19 `api_*.py` route modules). It exposes **12 hash routes** (`App.tsx:41-56`) driven by a hand-rolled hash router (`App.tsx:32-39`) and a **10-item sidebar** (`components/Layout/Sidebar.tsx:12-23`). The UI has accreted organically: several screens are single god-components (`Results/resultSections.tsx` 1590 lines, `Wizard/StepResources.tsx` 1160, `Settings/SettingsPage.tsx` 1049, `Workflow/WorkflowPage.tsx` 964), settings are a flat 10-card wall with no grouping or search, and developer-only affordances (raw-JSON node dump, environment-secret readback, SLURM auto-resubmit) sit inline with everyday controls.

This document is the **UX/information-architecture planning layer** for the dashboard refactoring track. Its goals:

1. Inventory the **real** screens, settings, and detail-panel surfaces as they exist today, with file/line anchors.
2. Classify every user-visible setting by **frequency of use** (Primary / Secondary / Advanced / Developer / Dangerous).
3. Define an **information-priority model** (P1–P5) and a **progressive-disclosure policy** so that everyday users see run state and results first, and power/debug surfaces are opt-in.
4. Propose a screen structure, a settings hierarchy, a Developer/Debug-mode gate, a dangerous-operations policy, and empty/loading/error and accessibility policies — all **without breaking the dashboard API contract** (endpoint paths, request/response schema) consumed through `services/api.ts` (863 lines).

**Hard constraints carried into every later implementation phase (do not violate in this planning doc, and flag any later PR that would):**

- **No settings may be deleted.** Reorganization, grouping, and disclosure only. A field that moves out of the default view must remain reachable.
- **No backend contract break for UI convenience.** Endpoint paths, HTTP verbs, and request/response field names in `services/api.ts` and the `api_*.py` modules stay stable; any UI-only change must be adapter-side.
- **No raw JSON / debug output exposed by default.** The `{ } Raw` tab (`Tree/DetailPanel.tsx:364,411-419`) and equivalent `JSON.stringify` dumps become Developer-Mode-gated, not removed.

## 2. Current Dashboard Screens

Routing is a hash router: `parseHash()` strips the query string and maps `#/<route>` to a lazily-loaded page (`App.tsx:32-56`). Legacy `new` aliases to `wizard` (`App.tsx:37,47-48`). The sidebar mirror is a **hardcoded** `NAV_ITEMS` array with emoji icons and i18n label keys (`Sidebar.tsx:12-23`); it lists 10 destinations and **omits the three `paperbench/*` sub-routes**, so nav↔route parity is maintained by hand (drift risk — see §6).

| Route (`PAGE_MAP`) | Sidebar item | Primary component(s) (LOC) | What it shows | Classification |
|---|---|---|---|---|
| `home` | `nav_home` 🏠 | `Home/HomePage.tsx` (122) | 3 stat boxes (runs, best score, total nodes), Quick Actions, Latest Experiment card | KEEP |
| `experiments` | `nav_experiments` 🗂️ | `Experiments/ExperimentsPage.tsx` (189) | Checkpoint list with status/lineage; View Results / View Tree navigation via `sessionStorage` handoff (`ExperimentsPage.tsx:46-63`) | KEEP |
| `monitor` | `nav_monitor` 📡 | `Monitor/MonitorPage.tsx` (502) + `GpuMonitor.tsx` (129) + `PhaseStepper.tsx` (113) + `monitorSections.tsx` (366) | Live run state, phase stepper, cost, model badge, stage run/stop, log stream, embedded tree, GPU monitor | ADAPT |
| `tree` | `nav_tree` 🌳 | `Tree/TreePage.tsx` (206) + `TreeVisualization.tsx` (366) + `DetailPanel.tsx` (425) + `DetailPanelTabs/*` (637) + `FileExplorer.tsx` | BFTS tree (D3), status/depth filters, node DetailPanel with 7 tabs, file explorer | ADAPT |
| `results` | `nav_results` 📊 | `Results/ResultsPage.tsx` (462) + `resultSections.tsx` (1590) + `PaperWorkspace.tsx` (519) + `RubricTreeVisualization.tsx` (462) + `EarSection.tsx` + `PublishYamlEditor.tsx` | Paper (PDF/editor), review scores, figures, reproducibility, EAR curation, Overleaf-style file mgmt | ADAPT |
| `new` / `wizard` | `nav_new` ✨ | `Wizard/WizardPage.tsx` (352) + `StepGoal.tsx` (528) + `StepScope.tsx` (424) + `StepResources.tsx` (1160) + `StepLaunch.tsx` (399) + `stepResourcesSections.tsx` (407) | 4-step launch wizard: Goal → Scope → Resources → Launch (`WizardPage.tsx:40`) | ADAPT |
| `idea` | `nav_idea` 💡 | `Idea/IdeaPage.tsx` (478) | Idea/gap-analysis view keyed off `AppState.ideas` / `gap_analysis` | KEEP |
| `workflow` | `nav_workflow` ⚡ | `Workflow/WorkflowPage.tsx` (964) + `workflowNodes.tsx` (770) | ReactFlow pipeline graph editor: stage enable/disable, skill phases, disabled tools | REVIEW_REQUIRED (power-user surface; see §10) |
| `settings` | `nav_settings` ⚙️ | `Settings/SettingsPage.tsx` (1049) + `settingsConstants.ts` (86) | 10-card settings wall (see §3) | ADAPT (core of this plan) |
| `paperbench` | `nav_paperbench` 📚 | `PaperBench/PaperRegistryPage.tsx` (147) | Registry of importable PaperBench papers | KEEP |
| `paperbench/import` | *(not in nav)* | `PaperBench/PaperImportDialog.tsx` (254) | arXiv import dialog | KEEP |
| `paperbench/run` | *(not in nav)* | `PaperBench/PaperBenchWizard.tsx` (412) | PaperBench replication launcher | KEEP |
| `paperbench/results` | *(not in nav)* | `PaperBench/results/ResultsView` | PaperBench grading/ORS results | KEEP |

State is a single React Context (`context/AppContext.tsx`) that polls `/state` and `/api/checkpoints` every **5 s** and layers a WebSocket node feed on top (`hooks/useWebSocket.ts`, falling back to `state.nodes`). There is no Redux/Zustand/react-query. Pages hold large local `useState` clusters (e.g. `SettingsPage.tsx:44-114` holds ~30 hooks). These facts constrain the disclosure design in §7: gating is a client-side view concern, not a data-fetching change.

## 3. Current Visible Settings

`SettingsPage.tsx` renders **10 `<Card>` sections** stacked vertically with no tabs, no search, and no grouping. Save (`handleSave`, `SettingsPage.tsx:226-269`) POSTs a **flat 24-key object** to `/api/settings`. The card inventory:

| # | Card title (i18n key / literal) | Lines | Controls | Persisted keys |
|---|---|---|---|---|
| 1 | Language (`settings_lang_section`) | 369-380 | en / ja / zh select (client-side i18n + `localStorage ari_lang`) | `language` (via i18n, not in the 24-key POST) |
| 2 | LLM Backend (`settings_llm`) | 383-478 | provider (openai/anthropic/gemini/ollama/cli-shim), model dropdown + custom, temperature, API Key (hidden for ollama), Base URL (ollama/cli-shim) | `llm_backend`, `llm_model`, `temperature`, `llm_api_key`, `llm_base_url` |
| 3 | Paper Retrieval (`settings_paper`) | 481-509 | backend radio (semantic_scholar / alphaxiv / both), Semantic Scholar key | `retrieval_backend`, `semantic_scholar_key` |
| 4 | VLM Figure Review (literal) | 512-523 | VLM model select (reuses provider model list) | `vlm_review_model` |
| 5 | Memory (Letta) (`settings_memory`) | 526-695 | base URL, API key, two-stage embedding picker (provider→model), custom handle, deployment (auto/docker/singularity/pip), **Restart Letta** button | `letta_base_url`, `letta_api_key`, `letta_embedding_config` |
| 6 | SLURM / HPC Defaults (`settings_slurm`) | 698-770 | partition multi-select + **Detect**, CPUs, Memory (GB), walltime | `slurm_partitions`, `slurm_partition`, `slurm_cpus`, `slurm_memory_gb`, `slurm_walltime` |
| 7 | Container (literal) | 773-827 | mode, pull policy, image, **Detect Runtime** | `container_mode`, `container_image`, `container_pull` |
| 8 | Available Skills (`settings_skills`) | 830-877 | read-only skill table (name / display / description / env) | *(read-only; none)* |
| 9 | SSH Remote Host (`settings_ssh`) | 880-943 | host, port, user, remote path, key path, **Test SSH** | `ssh_host`, `ssh_port`, `ssh_user`, `ssh_path`, `ssh_key` |
| 10 | Project Management (literal) | 946-1035 | per-checkpoint **Delete** buttons (irreversible) | *(mutating action; none in POST)* |
| — | Action bar | 1038-1045 | **Save**, **Test LLM** | — |

**Structural findings (verified):**

- The 24 persisted keys are: `llm_model, llm_backend, llm_base_url, temperature, llm_api_key, semantic_scholar_key, retrieval_backend, ssh_host, ssh_port, ssh_user, ssh_path, ssh_key, slurm_partitions, slurm_partition, slurm_cpus, slurm_memory_gb, slurm_walltime, container_mode, container_image, container_pull, vlm_review_model, letta_base_url, letta_api_key, letta_embedding_config` (`SettingsPage.tsx:235-260`). This exact key set is a dashboard-API contract with `/api/settings` and **must not change** during a UX reshuffle.
- **Settings/UX split (flag):** the `Settings` TS type declares `model_idea/model_bfts/model_coding/model_eval/model_paper/model_review` and `vlm_review_enabled/vlm_review_max_iter/vlm_review_threshold` (`types/index.ts:59-71`) that have **no UI on this page** — the per-phase model pickers live in `Wizard/StepResources.tsx`, not in global Settings. Any hierarchy proposal must decide whether these belong to global Settings (Advanced) or stay per-run in the Wizard (see §9).
- Provider/model option lists are **hardcoded and stale-prone** in `settingsConstants.ts:9-15` (e.g. `gpt-5.2`, `claude-opus-4-5`, `gemini-2.5-pro`). This is a maintenance hazard, not a UX-hierarchy problem; noted for the model-catalog subtask (§14) — **not** for deletion.
- The Letta embedding picker stores a flat `provider/model` handle string (`_splitHandle`, `settingsConstants.ts:71-86`) so env propagation (`LETTA_EMBEDDING_CONFIG`) is unchanged. This encode/decode contract KEEPs as-is under any regrouping.

## 4. Settings Frequency Classification

Each control is classified by how often a typical operator touches it and by its blast radius. Buckets: **Primary** (touched most runs), **Secondary** (per-project, occasional), **Advanced** (infra/tuning, rarely), **Developer** (debug/inspection), **Dangerous** (irreversible or resource-committing). No setting is dropped; the bucket only decides default visibility (§7, §9).

| Setting / control | Card | Bucket | Rationale |
|---|---|---|---|
| Language (en/ja/zh) | 1 | Primary | First-run choice; cheap, reversible |
| LLM provider + model + temperature | 2 | Primary | Chosen almost every run |
| LLM API Key | 2 | Dangerous | Secret; persisted to `.env` via `/api/settings`; readback via `/api/env-keys` (see §11) |
| LLM Base URL (ollama/cli-shim) | 2 | Advanced | Only for local/self-hosted backends |
| Paper retrieval backend | 3 | Secondary | Per-project retrieval preference |
| Semantic Scholar key | 3 | Advanced (secret) | Optional; API key |
| VLM Figure Review model | 4 | Secondary | Only when figure review is used |
| Letta base URL / deployment | 5 | Advanced | Infra wiring; default localhost:8283 |
| Letta API key | 5 | Dangerous | Secret |
| Letta embedding provider/model | 5 | Advanced | Affects memory correctness; rarely changed |
| **Restart Letta** | 5 | Dangerous | Kills + restarts a long-lived daemon (`restartLetta`, `/api/memory/restart`) |
| SLURM partitions / CPUs / mem / walltime | 6 | Advanced | HPC-only defaults; irrelevant off-cluster |
| **Detect partitions** | 6 | Secondary | Read-only probe |
| Container mode / pull / image | 7 | Advanced | Infra; default `auto` |
| **Detect Runtime** | 7 | Secondary | Read-only probe |
| Available Skills table | 8 | Developer (read-only) | Diagnostic inventory, not a setting |
| SSH host/port/user/path/key | 9 | Advanced | Remote-execution wiring |
| **Test SSH** | 9 | Secondary | Read-only probe |
| **Delete project** | 10 | Dangerous | Irreversible checkpoint deletion |
| Save / Test LLM | bar | Primary / Secondary | Save is Primary; Test LLM is a read-only probe |

## 5. User Journey

Three representative personas trace how information priority should flow. All three enter through the sidebar (`Sidebar.tsx`) and the 5 s-polled `AppState` (`context/AppContext.tsx`).

**J1 — First-time operator (laptop, cloud LLM):**
`home` (see nothing yet — empty state) → `settings` (set Language, LLM provider+model+key = Primary/Dangerous only) → `new` wizard (Goal → Scope → Resources → Launch) → `monitor` (watch P1 run state + P2 progress) → `results` (P3 paper/scores). Today this path forces the user past 10 settings cards, 7 of which (SLURM, Container, SSH, Letta infra, VLM) are irrelevant on a laptop. **Problem:** Primary settings are buried between Advanced infra cards.

**J2 — HPC operator (SLURM cluster):**
`settings` (LLM + SLURM partitions via Detect + Container + SSH) → `new` → `monitor` (+ GPU monitor, cost) → `tree` (inspect BFTS nodes) → `results`. This user needs the Advanced infra cards — but only once per environment. After setup, they live in `monitor`/`tree`/`results`. **Problem:** no separation between one-time environment setup and per-run choices.

**J3 — Developer / debugger:**
`tree` → node DetailPanel → `MCP Trace` / `Code` / `{ } Raw` tabs (`DetailPanel.tsx:355-420`) → `workflow` (edit pipeline) → `monitor` log stream. This user *wants* the raw JSON, trace, and prompt-level detail. **Problem:** those affordances are always-on for everyone, and the `{ } Raw` tab dumps `JSON.stringify(node)` to any user (§11), which is noise/leak risk for J1/J2.

**Journey conclusion:** the three personas want the *same screens* but *different depths*. This is exactly the case progressive disclosure + a Developer-Mode toggle solves (§7, §10), without moving or deleting anything.

## 6. Information Architecture Problems

Grounded, repository-specific problems (each maps to a fix in §7–§12):

1. **Flat settings wall.** 10 cards, ~1049 lines, no tabs/search/grouping (`SettingsPage.tsx`). Primary controls (LLM, Language) are visually equal to rarely-touched infra (SLURM, SSH, Container, Letta). → §9 hierarchy.
2. **God-components block per-section work.** `resultSections.tsx` (1590), `StepResources.tsx` (1160), `SettingsPage.tsx` (1049), `WorkflowPage.tsx` (964). Large single files make disclosure hard to bolt on cleanly. → §8 proposes section extraction (view-layer only; MERGE of inline blocks into per-section components).
3. **Always-on developer surfaces.** `{ } Raw` node tab (`DetailPanel.tsx:364,411-419`), `JSON.stringify` dumps in `monitorSections.tsx`, `DetailPanelTabs/TraceTab.tsx`, `ExperimentsPage.tsx`, `resultSections.tsx`, and the raw-YAML editor (`PublishYamlEditor.tsx`). No user-facing distinction between "result" and "debug dump." → §10 Developer Mode.
4. **Dangerous actions guarded only by `window.confirm`.** Project delete (`SettingsPage.tsx:299`), Letta restart (`SettingsPage.tsx:653`), GPU-monitor SLURM auto-resubmit (`GpuMonitor.tsx:47`, and `gpuMonitorAction` always sends `confirmed:true` — `api.ts:585`). No typed confirmation, no consistent affordance. → §11.
5. **Secret exposure by default.** `/api/env-keys` returns actual env secret values to the browser (`api.ts:383`); `StepResources.autoReadApiKey` reads `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` (`StepResources.tsx:333-342`); API keys are editable and persisted to `.env`. Keys are `type="password"` inputs but the readback path is a plaintext transport. → §11 (policy; backend contract unchanged).
6. **Nav↔route drift is manual.** `PAGE_MAP` has 12 entries (`App.tsx:41-56`); `NAV_ITEMS` has 10 (`Sidebar.tsx:12-23`) and omits `paperbench/*`. There is no single source of truth. → §8 (single route registry as a view-layer refactor; **the hash-router contract and existing `#/` URLs stay stable**).
7. **Inconsistent error regimes reach the UI.** `get/post` **throw** on non-2xx (`api.ts:18-32`) while `pbGet/pbPost` **never throw** and return `{error}` bodies (`api.ts:787-799`). Screens therefore render errors inconsistently. → §12 (state policy is UI-side; the two API regimes are a documented contract and are **not** changed here).
8. **No empty/loading/error contract.** Ad-hoc handling: HomePage shows a bare `No experiments yet` (`HomePage.tsx:114-116`); Suspense fallback is a bare spinner (`App.tsx:74-78`); many sections show nothing while loading. → §12.

## 7. Progressive Disclosure Policy

The dashboard adopts a single, explicit information-priority ladder. Higher-priority information is visible by default and higher on the page; lower-priority information is collapsed, tab-gated, or Developer-Mode-gated.

**Information priority (P1 highest → P5 lowest):**

- **P1 — Run state.** Is a run active? Which checkpoint? Phase, PID, running/stopped, exit code. Sources: `AppState.is_running/current_phase/checkpoint_id/status_label` (`types/index.ts:87-129`). Surfaces on `home`, `monitor`, and the sidebar project switcher (`Sidebar.tsx:154-172`).
- **P2 — BFTS tree / node / progress / score.** Node count, best score, per-node status/depth/metrics. Sources: `nodesData` (WebSocket), `TreeVisualization`, `PhaseStepper`, `monitorSections.computeBestMetrics`.
- **P3 — Artifacts / reports.** Paper PDF, review scores, figures, reproducibility, EAR. Sources: `CheckpointSummary` (`types/index.ts:237-264`), `Results/*`.
- **P4 — Trace / prompt / cost / logs.** MCP trace, code snippets, cost breakdown, streamed logs. Sources: `DetailPanelTabs/{TraceTab,CodeTab}`, `AppState.cost` (`CostSummary`), Monitor log stream.
- **P5 — Advanced / debug.** Raw JSON node dump, raw-YAML editor, env-key readback, workflow-graph internals, advanced infra settings. Sources: `DetailPanel {} Raw`, `PublishYamlEditor`, `/api/env-keys`, `WorkflowPage`.

**Disclosure rules:**

1. **Default view = P1–P3.** Any user, with Developer Mode off, sees run state, tree/score, and artifacts without extra clicks.
2. **P4 is one interaction away.** Trace/cost/logs live behind a tab or an expander that is always present but not pre-expanded (e.g. DetailPanel `MCP Trace`/`Code` tabs stay, but are not the default tab — `overview` already is the default, `DetailPanel.tsx:37,44-46`).
3. **P5 is Developer-Mode-gated.** Raw JSON, raw YAML, env-key readback, and workflow-internal editing render only when Developer Mode is enabled (§10). When gated off, the affordance is hidden (not disabled-with-tooltip) to keep the everyday surface clean.
4. **Settings follow the frequency buckets (§4).** Primary always visible; Secondary one scroll/section away; Advanced behind an "Advanced" disclosure; Developer/Dangerous grouped and visually distinct (§9, §11).
5. **Disclosure state is view-only.** No rule in this policy changes which endpoints are called or when — `AppContext` polling and the WebSocket feed are untouched. Gating is pure client-side conditional rendering.

## 8. Proposed Screen Structure

The 12 routes KEEP their paths and `#/` URLs (hash-router contract, `App.tsx:32-56`). The changes are view-layer grouping and a single route registry — **no route is renamed, merged, or removed**, and the legacy `new`→`wizard` alias stays.

**Sidebar grouping (view-only reorder of `NAV_ITEMS`, `Sidebar.tsx:12-23`):**

- **Run** — Home, Experiments, New Experiment (Wizard)
- **Observe** — Monitor, Tree, Results, Idea
- **PaperBench** — PaperBench (registry; sub-routes reachable from within, as today)
- **Configure** — Workflow, Settings

This is a labeling/ordering change to an array; the `key`/`labelKey`/`icon` contract and the `handleNav` hash write (`Sidebar.tsx:72-79`) are unchanged.

**Single route registry (REVIEW_REQUIRED):** today `PAGE_MAP` (`App.tsx:41-56`) and `NAV_ITEMS` (`Sidebar.tsx:12-23`) duplicate route knowledge and drift (§6.6). Proposal: derive both from one `routes.ts` table (route key → component + optional nav metadata). This is an internal refactor; the produced `#/` URLs and lazy-load boundaries stay identical. `paperbench/*` sub-routes remain non-nav but registry-declared, ending the manual omission.

**God-component decomposition (MERGE inline blocks → per-section components; view-layer only):**

| File | LOC | Proposed split (illustrative; no behavior change) |
|---|---|---|
| `Results/resultSections.tsx` | 1590 | already exposes 6 render-fns; extract each `render*` (e.g. the 460-line `renderReviewScores`) into its own component file |
| `Wizard/StepResources.tsx` | 1160 | pull the ORS block and per-phase model block into sub-components (some sectioning already in `stepResourcesSections.tsx`, 407) |
| `Settings/SettingsPage.tsx` | 1049 | one component per card (§9), each reading/writing the same 24-key POST |
| `Workflow/WorkflowPage.tsx` | 964 | separate graph canvas from side panels (`workflowNodes.tsx`, 770, already extracted) |

Decomposition is a prerequisite for §9/§10 gating but changes no endpoints, no `services/api.ts` signatures, and no persisted keys.

## 9. Proposed Settings Hierarchy

`SettingsPage` becomes a **tabbed + progressively-disclosed** page. The 24-key POST (`SettingsPage.tsx:235-260`) and every field KEEP; only layout and default visibility change. No card is deleted; the "Available Skills" read-only table and "Project Management" actions stay reachable.

**Tab A — Essentials (Primary, default tab):**
- Language (Card 1)
- LLM Backend: provider, model, temperature (Card 2 core)
- Save / Test LLM action bar

**Tab B — Project (Secondary):**
- Paper Retrieval backend (Card 3)
- VLM Figure Review model (Card 4)
- Per-phase models `model_idea/bfts/coding/eval/paper/review` — REVIEW_REQUIRED: today only in `Wizard/StepResources.tsx` and declared-but-unused in `Settings` type (`types/index.ts:59-71`). Decide: surface here as Advanced, or keep per-run in Wizard. **Do not silently drop.**

**Tab C — Infrastructure (Advanced, collapsed by default):**
- SLURM / HPC (Card 6) + Detect
- Container (Card 7) + Detect Runtime
- SSH Remote Host (Card 9) + Test SSH
- Letta base URL / deployment / embedding (Card 5 non-secret parts)

**Tab D — Secrets (Dangerous, isolated):**
- LLM API Key, Semantic Scholar key, Letta API key
- Explicit "these are written to `.env`" notice (policy §11). Fields stay `type="password"`; the readback path (`/api/env-keys`) is Developer-Mode-gated (§10) — the endpoint contract itself is unchanged.

**Tab E — Diagnostics / Danger Zone:**
- Available Skills read-only table (Card 8) — Developer-flavored, read-only
- Restart Letta (Card 5 action) — Dangerous (§11)
- Project Management / Delete (Card 10) — Dangerous (§11)

The provider/model tables (`settingsConstants.ts`) KEEP; the two-stage Letta handle encode/decode (`_splitHandle`) KEEP. A model-catalog freshness subtask (§14) tracks the hardcoded lists but is out of scope for the hierarchy change.

## 10. Developer / Debug Mode Policy

**Mechanism (proposed, view-layer only):** a single client-side "Developer Mode" toggle persisted in `localStorage` (mirroring the existing `ari_lang` pattern used by i18n, `SettingsPage.tsx:121`). Default **off**. No new endpoint, no backend flag, no change to `AppContext` fetching. When off, P5 affordances are **hidden**; when on, they render.

**Candidate Developer-Mode content — the Tree DetailPanel tabs** (`Tree/DetailPanelTabs/`, 637 lines total):

| Tab | File (LOC) | Priority | Developer-Mode? |
|---|---|---|---|
| Overview (default) | inline `DetailPanel.tsx:368` | P2/P3 | Always on |
| Access | `AccessTab.tsx` (155) | P4 (memory access audit) | On by default; keep |
| Code | `CodeTab.tsx` (42) | P4 (extracted code snippets) | On by default; keep |
| Memory | `MemoryTab.tsx` (113) + `MemoryEntryCard.tsx` (131) | P3/P4 | On by default; keep |
| Report | `ReportTab.tsx` (126) | P3 (node_report.json; already hidden when absent, `DetailPanel.tsx:362-363`) | On by default; keep |
| Trace | `TraceTab.tsx` (57) | P4 (MCP trace) | On by default; keep |
| **`{ } Raw`** | inline `DetailPanel.tsx:411-419` | **P5** | **Developer-Mode-gated** |

Rationale: the DetailPanel is already well-decomposed (unlike the god-components in §8) and its tabs map cleanly onto P3–P5. The **only** always-on P5 element is the `{ } Raw` tab, which dumps `JSON.stringify(node, null, 2).slice(0, 6000)` to any user. That single tab, plus the other raw dumps (`monitorSections.tsx`, `PublishYamlEditor` raw-YAML, `/api/env-keys` readback, `WorkflowPage` internal editing), move behind the Developer-Mode gate.

**Policy rules:**
1. Developer Mode gates **rendering only**. It never unlocks a *new* mutating capability that a non-developer lacks; every mutation still goes through the same dangerous-operation confirmations (§11).
2. Developer Mode is discoverable but not prominent (e.g. a footer or Settings→Diagnostics toggle), so it does not clutter J1/J2.
3. Gating uses conditional rendering, not CSS hiding, so gated raw JSON is not shipped in the DOM by default.

## 11. Dangerous Operations Policy

"Dangerous" = irreversible, resource-committing (submits jobs / spends money), or secret-exposing. Grounded inventory and required treatment. **No dangerous capability is removed** — each is made deliberate. Backend endpoints/verbs are unchanged; all hardening is client-side affordance + policy, except where noted as a later REVIEW_REQUIRED backend subtask.

| Operation | Location | Current guard | Required treatment |
|---|---|---|---|
| Delete project (checkpoint) | `SettingsPage.tsx:298-311` (`deleteCheckpoint`) | `confirm()` only (`:299`) | Typed/explicit confirmation (e.g. type the project id); keep in Danger Zone tab (§9-E); irreversibility notice |
| Delete checkpoint file | `Results` file mgmt (`deleteCheckpointFile`, `api.ts`) | inline | Confirmation + undo-affordance where feasible |
| Restart Letta | `SettingsPage.tsx:649-687` (`restartLetta` → `/api/memory/restart`) | `confirm()` (`:653`) | Danger Zone placement; single-flight (already present via `lettaRestarting`); clear "kills daemon" copy |
| GPU-monitor SLURM auto-resubmit | `GpuMonitor.tsx:46-55` (`gpuMonitorAction`) | `window.confirm` (`:47`) — but `api.ts:585` **always sends `confirmed:true`** | REVIEW_REQUIRED: the `confirmed:true` hardcode makes the backend guard non-functional; require an explicit UI confirmation whose result actually flows to the request. Backend contract audit before change. |
| LLM / SS / Letta API keys (edit + persist) | `SettingsPage.tsx` Cards 2/3/5 → `/api/settings` → `.env` | `type="password"` inputs | §9-D Secrets tab; explicit "written to `.env`" notice; no plaintext echo |
| Env-key readback | `/api/env-keys` (`api.ts:383`); `StepResources.autoReadApiKey` (`StepResources.tsx:333-342`) | none (returns real secrets to browser) | Developer-Mode-gate the readback UI (§10); do **not** auto-read secrets on Wizard mount without user action. Endpoint contract unchanged. |
| Raw HTML injection | `StepScope.tsx:137` `dangerouslySetInnerHTML`; `main.tsx:38` `innerHTML` error stack; ErrorBoundary full-stack print (`main.tsx:17-25`) | none | REVIEW_REQUIRED: sanitize or replace with React nodes; gate full stack traces behind Developer Mode (§12). |
| Stage run / stop / launch | `MonitorPage.tsx` (`runStage`, `stopExperiment`) | inline status only | Confirmation on launch when a run is already active; clear P1 run-state feedback |

Cross-cutting policy: dangerous controls get a **consistent visual treatment** (red/danger affordance, already partially present, e.g. delete button styling `SettingsPage.tsx:1016-1027`), live in dedicated Danger-Zone groupings, and never sit adjacent to Primary controls.

## 12. Empty / Loading / Error State Policy

Today these are ad-hoc: bare `No experiments yet` (`HomePage.tsx:114-116`), a bare Suspense spinner (`App.tsx:74-78`), silent catches (`SettingsPage.tsx:157-159,166,177`), and two divergent API error regimes (§6.7). Proposed uniform policy (view-layer only; no endpoint change):

- **Empty:** every list/detail surface renders a first-class empty state with a next action (e.g. Home empty → "Start a new experiment" → `#/new`). Reuse `components/common/Card` and existing `.empty-state` styling.
- **Loading:** consistent skeleton/spinner per surface, not a single global spinner. Long-poll surfaces (5 s `AppContext`) show "last updated" rather than blanking.
- **Error:**
  - Standardize on rendering the error regime already present: `get/post` throw (`api.ts:18-32`) → catch → inline error banner; `pbGet/pbPost` return `{error}` (`api.ts:787-799`) → render `{error}` inline. Both regimes KEEP (documented contract); the UI wraps them in one presentational `<ErrorBanner>` so users see consistent messaging.
  - Full stack traces (`main.tsx:17-25,38`) become Developer-Mode-gated (§10); non-developers see a friendly message + retry.
- **Never blank the screen on transient poll failure.** A failed `/state` or `/checkpoints` poll keeps the last good render (AppContext already tolerates this) and surfaces a non-blocking staleness indicator.

## 13. Accessibility / Readability Notes

Grounded observations (the app has **no CSS framework** — a single `styles/dashboard.css` plus pervasive inline `style={{}}`), with policy for the reshuffle:

- **Keyboard nav:** sidebar items are `role="button"` + `tabIndex={0}` + Enter handler (`Sidebar.tsx:141-145`) — good; extend the same pattern to DetailPanel tab buttons and any new disclosure/toggle controls so Developer Mode and tabs are keyboard-reachable.
- **Focus / ARIA on tabs:** DetailPanel tabs (`DetailPanel.tsx:148-168`) and the proposed Settings tabs need `role="tab"`/`role="tabpanel"`/`aria-selected` semantics; today they are plain buttons.
- **Color-only status:** status is conveyed via color badges (`DetailPanel.tsx:135-144`, label color maps in `IdeaPage.tsx:11-31`, `DetailPanel.tsx:13-19`). Pair color with text/icon (several already include a glyph, e.g. `✓/✗/⏳` in `HomePage.tsx:10-13`) to meet non-color-dependent contrast.
- **Contrast / theme tokens:** colors come from CSS variables (`var(--muted)`, `var(--red)`, `var(--blue-light)`) in `dashboard.css`; verify muted-on-card contrast (`.72–.85rem` text at `var(--muted)`) meets WCAG AA — many detail labels are `.72rem` `var(--muted)`.
- **Password fields:** keys use `type="password"` (`SettingsPage.tsx:449,503,542`) — keep; add visible labels (present) and avoid autofill of secrets into non-secret contexts.
- **i18n parity:** `en.ts` (444 lines) vs `ja.ts`/`zh.ts` (441 each) — minor key drift; any new UX strings (Developer Mode, Danger Zone, tab labels, empty/error copy) must be added to all three locales to keep the existing i18n contract and `scripts/docs/check_i18n_js.py` gate green.
- **Mobile:** a hamburger + overlay pattern exists (`Sidebar.tsx:85-108`); ensure new tabbed Settings and DetailPanel disclosures collapse gracefully at ≤480 px.

## 14. Related Subtasks

This plan is the parent of a set of dashboard-UX subtasks. **Current state (verified):** `docs/refactoring/subtasks/` and `docs/refactoring/reports/` **exist but are empty** — subtasks 067–073 **do not exist yet**; they are planned deliverables spawned by this document. Likewise the quality checker `scripts/check_dashboard_ux.py` **does not exist** (it is listed as MISSING/to-be-designed) and must not be implemented in this planning phase.

| Subtask | Working title | Scope (planning → later implementation) | Depends on §§ |
|---|---|---|---|
| 067 | Route registry + sidebar grouping | Single `routes.ts` source of truth; group `NAV_ITEMS`; end nav↔route drift (paths/URLs unchanged) | §6.6, §8 |
| 068 | Settings hierarchy (tabbed + disclosure) | Reshape `SettingsPage.tsx` into Tabs A–E; keep 24-key POST + all fields | §3, §4, §9 |
| 069 | Progressive-disclosure / P1–P5 model | Apply priority ladder across Home/Monitor/Tree/Results; view-layer only | §7 |
| 070 | Developer / Debug Mode gate | `localStorage` toggle; gate `{ } Raw`, raw-YAML, env-key readback, workflow internals | §10 |
| 071 | Dangerous-operations hardening | Typed confirmations; fix `confirmed:true` hardcode (REVIEW_REQUIRED backend audit); Danger Zone grouping | §11 |
| 072 | Empty / Loading / Error state kit | `<ErrorBanner>`, skeletons, empty states; unify the two API error regimes at the presentation layer | §12 |
| 073 | Accessibility / i18n pass | ARIA tab semantics, keyboard reach, color+text status, trilingual strings for all new copy | §13 |
| (tooling) | `scripts/check_dashboard_ux.py` | Design-only here: lint for always-on raw dumps, unconfirmed dangerous ops, missing i18n keys. **Not implemented in planning phase.** | §10–§13 |

**Guardrails inherited by every subtask above:** no setting deleted; no dashboard-API endpoint/schema break (`services/api.ts` + `api_*.py`); no raw JSON/debug exposed by default; CLI `ari`, `ari.public.*`, MCP tool contracts, checkpoint/output/config formats, and `ari-skill-* → ari-core` interfaces remain untouched — the dashboard work is confined to `ari-core/ari/viz/frontend/` view-layer changes plus explicitly-flagged REVIEW_REQUIRED backend audits.

## Retirement Condition

This is a **program-level planning document**, not a per-subtask artifact. It
stays live for the duration of the refactoring program and may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources — never on assumption:

1. Every subtask this document governs is marked **DONE** in
   `docs/refactoring/007_subtask_index.md`, **or** this document has been
   explicitly **superseded** by a named replacement (the superseding document
   must reference this file by name).
2. Any conclusions worth keeping have been folded into the permanent
   documentation / architecture.

Before any `git rm`, re-read this document's own conditions and check each one
against the current repository. See the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
