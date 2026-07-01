# Subtask 068: Define Dashboard Information Architecture

- **Phase:** Phase 6 — Dashboard UX
- **Status:** PLANNING / DESIGN ONLY (this subtask produces an information-architecture specification; it does **not** modify runtime code, frontend, imports, prompts, configs, workflows, or directory names)
- **Planning date:** 2026-07-01
- **Repo:** `/home/t-kotama/workplace/ARI` (git branch `main`; `ari-core` version 0.9.0)
- **Author role:** senior software architect
- **Parent plan:** `docs/refactoring/014_dashboard_ux_refactoring_plan.md`
- **Consumes:** subtask **067** (`inventory_dashboard_visible_settings`) — the raw settings/screen inventory
- **Hands off to:** subtask **069** (`design_dashboard_progressive_disclosure`), **070** (`refactor_dashboard_settings_panel`), **071** (`add_dashboard_developer_mode`), **072** (`improve_dashboard_empty_loading_error_states`), **073** (`add_dashboard_ux_regression_checks`)

> **Hard scope note.** This document defines the *information architecture* — the target taxonomy of screens, the navigation grouping, the single source of truth for routes, the information-priority ladder (P1–P5), and the settings **category structure**. It records *decisions*, not code. It proposes **nothing** that renames a route, edits `App.tsx` / `Sidebar.tsx`, restructures `SettingsPage.tsx`, or changes any dashboard API endpoint today. Every "target" named here is a destination for the later, contract-preserving implementation subtasks (069–073), not an instruction to edit any `.tsx` now.
>
> **Classification vocabulary:** KEEP / ADAPT / MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED.
>
> **Numbering note.** The authoritative subtask numbering is `docs/refactoring/007_subtask_index.md` (rows 114–120), where **068 = `define_dashboard_information_architecture`**. The parent plan `014_dashboard_ux_refactoring_plan.md` §14 uses an earlier, informal 067–073 mapping (it labels 068 "Settings hierarchy"); that informal table is superseded by the 007 index. This document follows the 007 index.

---

## 1. Goal

Produce a single, authoritative **Dashboard Information Architecture (IA)** specification that the downstream Phase-6 subtasks (069–073) implement against without re-litigating structural questions. The IA must:

1. Define the **target screen taxonomy** — a grouping of the existing 13 distinct hash routes into a small number of navigation categories, without renaming, merging, or removing any route or its `#/` URL.
2. Declare a **single route registry** as the source of truth (SSOT) for route key → component → nav metadata, ending the manual `PAGE_MAP` (`App.tsx:41-56`) ↔ `NAV_ITEMS` (`Sidebar.tsx:12-23`) drift — as a *design decision*, implemented later.
3. Define the **information-priority ladder P1–P5** (run state → tree/score → artifacts → trace/logs → advanced/debug) and map every major surface to a priority band. This ladder is the shared vocabulary 069 turns into disclosure mechanics.
4. Define the **settings category structure** (Essentials / Project / Infrastructure / Secrets / Diagnostics-&-Danger) as an information *taxonomy* over the inventoried controls, so that 070 can reshape `SettingsPage.tsx` against a fixed target — while preserving the flat 24-key `/api/settings` contract.
5. Classify every screen and settings group with KEEP / ADAPT / MERGE / REVIEW_REQUIRED and fix the boundary of what belongs to 068 (structure) versus 069 (disclosure), 070 (settings widget), 071 (dev mode), 072 (states).

The deliverable is this `.md` file. There is no code change in subtask 068.

## 2. Background

The ARI dashboard is a single-page React app (Vite 5 + React 18.3 + TypeScript 5.5) served by the FastAPI backend in `ari-core/ari/viz/` (`routes.py`, 1197 lines, plus 19 `api_*.py` modules). Verified structural facts (read-only, 2026-07-01):

- **Routing is a hand-rolled hash router.** `parseHash()` strips the query string and maps `#/<route>` to a lazily-loaded page (`App.tsx:32-56`). `PAGE_MAP` declares **14 route keys** (`App.tsx:41-56`) covering **13 distinct destinations** after the legacy `new`→`wizard` alias (`App.tsx:37`). The router body is a 30-line `Router()` with a single global Suspense fallback (`App.tsx:60-89`).
- **The sidebar is a hardcoded mirror.** `NAV_ITEMS` (`Sidebar.tsx:12-23`) lists **10 destinations** with emoji icons and i18n label keys. It includes `paperbench` but **omits the three `paperbench/*` sub-routes** (`import`/`run`/`results`), so nav↔route parity is maintained by hand — a drift hazard with no SSOT.
- **State is a single React Context.** `context/AppContext.tsx` (120 lines) polls `/state` and `/api/checkpoints` every **5 s** and layers a WebSocket node feed on top (`hooks/useWebSocket.ts`). There is no Redux/Zustand/react-query. Gating and grouping are therefore pure client-side view concerns, not data-fetching changes.
- **Several screens are god-components.** `Results/resultSections.tsx` (1590), `Wizard/StepResources.tsx` (1160), `Settings/SettingsPage.tsx` (1049), `Workflow/WorkflowPage.tsx` (964). The IA does not decompose them (that is 064/070's job); it defines the *categories* those decompositions target.
- **Settings are a flat wall.** `SettingsPage.tsx` renders **10 `<Card>` sections** top-to-bottom with no tabs, no search, no grouping, and `handleSave` POSTs a **flat 24-key object** to `/api/settings` (`SettingsPage.tsx:235-260`). Subtask **067** inventories these controls; 068 imposes a taxonomy over them.
- **Developer/debug affordances are always-on for everyone.** The Tree DetailPanel `{ } Raw` tab dumps `JSON.stringify(node)` to any user (`Tree/DetailPanel.tsx:411-419`); raw `JSON.stringify` appears in `monitorSections.tsx`, `DetailPanelTabs/TraceTab.tsx`, `ExperimentsPage.tsx`, `resultSections.tsx`. The IA assigns these to priority band P5; 071 gates them.

The parent plan `014_dashboard_ux_refactoring_plan.md` (285 lines) already sketches screen tables (§2), a settings-frequency classification (§4), a P1–P5 model (§7), and a proposed screen/settings structure (§8–§9). Subtask 068 **lifts, verifies, and fixes** that structure into a single normative IA spec that 069–073 can cite; it does not restate the whole parent plan.

## 3. Scope

**In scope (design decisions recorded in this document):**

1. **Screen taxonomy & navigation grouping** — categorize the 13 distinct routes into named groups (§7.1). Ordering/label metadata only; every route key, `#/` URL, component binding, and the `new`→`wizard` alias KEEP.
2. **Route SSOT design** — specify a single route-registry table (route key → component → nav group/label/icon) as the target replacement for the duplicated `PAGE_MAP` / `NAV_ITEMS` knowledge (§7.2). Design only; 067-adjacent implementation is deferred.
3. **Information-priority ladder P1–P5** — define the bands and map the major screens/surfaces onto them (§7.3). This is the vocabulary 069 consumes.
4. **Settings category structure** — define 5 information categories over the inventoried controls, with the invariant that the flat 24-key POST and every field survive (§7.4).
5. **Screen-level classification** — KEEP / ADAPT / MERGE / REVIEW_REQUIRED per screen (§7.5).

**Out of scope (owned by later subtasks; named here for boundary clarity):**

- Progressive-disclosure *mechanics* (default-visible vs collapsed vs gated rules, expander behavior) → **069**.
- Actual `SettingsPage.tsx` reshaping into tabs / the settings widget → **070**.
- The Developer/Debug-Mode toggle and P5 gating implementation → **071**.
- Empty/loading/error-state kit → **072**.
- UX regression checks / `scripts/check_dashboard_ux.py` (which **does not exist** and must not be created here) → **073**.
- God-component decomposition and backend routes→services → Phase-5 subtasks **062/063/064**.

## 4. Non-Goals

- **No route is renamed, merged, moved, or deleted.** The hash-router contract (`App.tsx:32-56`) and every existing `#/` URL are preserved.
- **No dashboard API change.** No endpoint path, HTTP verb, request/response field, or the flat 24-key `/api/settings` object is altered or proposed for alteration here.
- **No setting is deleted or hidden-into-unreachability.** The IA only assigns categories/priority bands; reachability is guaranteed.
- **No code is written or edited** — no `.tsx`, `.ts`, `.css`, `.py`, `.yaml`, workflow, or i18n file. The only artifact is this `.md`.
- **No new dependency, state library, router library, or CSS framework** is introduced or recommended for adoption in this subtask.
- **No visual/aesthetic redesign** (color, typography, spacing). IA is structure and priority, not styling.

## 5. Current Files / Directories to Inspect

Read-only inputs for whoever executes 068 (all under `ari-core/ari/viz/frontend/` unless noted). Line counts verified 2026-07-01.

**Routing & navigation (the IA subjects):**

| Path | LOC | Why it matters to IA |
| --- | --- | --- |
| `src/App.tsx` | 94 | `parseHash()` (`:32-39`), `PAGE_MAP` 14 keys (`:41-56`), Router + global Suspense fallback (`:60-89`) |
| `src/components/Layout/Sidebar.tsx` | ~200 | `NAV_ITEMS` hardcoded 10-item mirror (`:12-23`), `handleNav` hash write (`:72-79`), project switcher (`:154-172`) |
| `src/components/Layout/Layout.tsx` | 12 | Shell = `<Sidebar/>` + `<div id="main">`; wrapper the taxonomy renders into |
| `src/context/AppContext.tsx` | 120 | 5 s polling of `/state` + `/checkpoints`; confirms gating is a view concern, not a fetch change |

**Screens to categorize (representative anchors; not exhaustive):**

| Path | LOC | Route |
| --- | --- | --- |
| `src/components/Home/HomePage.tsx` | 122 | `home` |
| `src/components/Experiments/ExperimentsPage.tsx` | ~189 | `experiments` |
| `src/components/Monitor/MonitorPage.tsx` | 502 | `monitor` |
| `src/components/Tree/TreePage.tsx` + `DetailPanel.tsx` (425) + `DetailPanelTabs/*` | — | `tree` |
| `src/components/Results/ResultsPage.tsx` (462) + `resultSections.tsx` (1590) | — | `results` |
| `src/components/Wizard/WizardPage.tsx` + `StepResources.tsx` (1160) | — | `new`/`wizard` |
| `src/components/Idea/IdeaPage.tsx` | ~478 | `idea` |
| `src/components/Workflow/WorkflowPage.tsx` | 964 | `workflow` |
| `src/components/Settings/SettingsPage.tsx` | 1049 | `settings` |
| `src/components/Settings/settingsConstants.ts` | 86 | provider/model tables, Letta handle encode/decode |
| `src/components/PaperBench/` (`PaperRegistryPage`, `PaperImportDialog`, `PaperBenchWizard`, `results/ResultsView`) | — | `paperbench` + 3 sub-routes |

**Priority-band evidence:**

| Path | Anchor | Band |
| --- | --- | --- |
| `src/types/index.ts` | `AppState.is_running/current_phase/checkpoint_path/status_label` (`:87-129`); `Settings` `model_idea…model_review` (`:59-71`) | P1 / settings |
| `src/components/Tree/DetailPanel.tsx` | `{ } Raw` tab (`:411-419`); default `overview` tab (`:37`) | P5 / P2-P3 |
| `src/components/Monitor/monitorSections.tsx` | raw `JSON.stringify` dumps | P5 |
| `src/i18n/en.ts` / `ja.ts` / `zh.ts` | 444 / 441 / 441 lines; `nav_*` keys (`en.ts:3-11,356`) | any new nav/category label must land in all three |

**Cross-references (docs, not runtime):**

| Path | Why |
| --- | --- |
| `docs/refactoring/014_dashboard_ux_refactoring_plan.md` | Parent plan; §2 (screen table), §4 (frequency), §7 (P1–P5), §8–§9 (structure) |
| `docs/refactoring/007_subtask_index.md` | Authoritative 068 numbering (rows 114–120); dependency edges (`:446`) |
| `docs/refactoring/subtasks/067_inventory_dashboard_visible_settings.md` | The settings inventory this IA categorizes (**does not exist yet** at planning time; produced by 067) |

## 6. Current Problems

Grounded, repository-specific IA problems this subtask's design resolves (each maps to a decision in §7):

1. **No screen taxonomy — a flat 10-item sidebar.** `NAV_ITEMS` (`Sidebar.tsx:12-23`) is a single ungrouped list. "Run" actions (Home, New), "observe" surfaces (Monitor, Tree, Results, Idea), a benchmark track (PaperBench), and configuration (Workflow, Settings) are visually equal. → §7.1.
2. **Route knowledge is duplicated and drifts.** `PAGE_MAP` (14 keys, `App.tsx:41-56`) and `NAV_ITEMS` (10 items, `Sidebar.tsx:12-23`) independently encode routes; the sidebar omits `paperbench/*` sub-routes with no SSOT. → §7.2.
3. **No shared information-priority vocabulary.** Each screen decides ad-hoc what to show first; there is no agreed ladder tying run state > tree/score > artifacts > trace > debug. 069/070/071 would otherwise each invent their own. → §7.3.
4. **Flat settings wall with no categories.** 10 cards, ~1049 lines, no grouping (`SettingsPage.tsx`); Primary controls (LLM, Language) sit among rarely-touched infra (SLURM, SSH, Container, Letta). → §7.4.
5. **Settings/UX split is undocumented.** The `Settings` TS type declares `model_idea/model_bfts/model_coding/model_eval/model_paper/model_review` and `vlm_review_enabled/_max_iter/_threshold` (`types/index.ts:59-71`) with **no UI on the Settings page** — per-phase models live in `Wizard/StepResources.tsx`. The IA must place these fields deliberately (Project category, REVIEW_REQUIRED) rather than let 070 silently drop them. → §7.4.
6. **P5 debug surfaces have no band.** The `{ } Raw` tab and other `JSON.stringify` dumps (§2) are always-on with no priority classification, so 071 has nothing to gate against. → §7.3.

## 7. Proposed Design / Policy

### 7.1 Screen taxonomy (navigation grouping)

The 13 distinct routes KEEP their keys, components, and `#/` URLs. The IA overlays **four navigation groups** as ordering/label metadata only. Grouping is a labeling decision on the existing `NAV_ITEMS` array shape (`key`/`labelKey`/`icon` contract unchanged); the `paperbench/*` sub-routes remain non-nav but registry-declared (§7.2).

| Group | Routes (existing keys) | Intent | Classification |
| --- | --- | --- | --- |
| **Run** | `home`, `experiments`, `new`/`wizard` | Start/launch and pick a run | KEEP (regroup only) |
| **Observe** | `monitor`, `tree`, `results`, `idea` | Watch a live/finished run and its artifacts | KEEP (regroup only) |
| **Benchmark** | `paperbench` (+ `paperbench/import`, `paperbench/run`, `paperbench/results` reachable within) | PaperBench replication track | KEEP |
| **Configure** | `workflow`, `settings` | Pipeline shape + environment/settings | ADAPT (`settings` is the core of 070; `workflow` is REVIEW_REQUIRED power-user surface) |

This is a view-layer reorder/label of an array. No `handleNav` hash write (`Sidebar.tsx:72-79`), route key, or icon contract changes. The legacy `new`→`wizard` alias (`App.tsx:37`) stays.

### 7.2 Single route registry (SSOT) — design

Target: one `routes` table (route key → lazy component → optional nav metadata: group, `labelKey`, icon, `inNav` flag) from which **both** the router map and the sidebar list derive. This removes the manual duplication and the `paperbench/*` omission (§6.2). Non-nav routes (`paperbench/import|run|results`) are declared with `inNav:false` rather than silently absent.

- **Classification:** REVIEW_REQUIRED (touches `App.tsx` + `Sidebar.tsx` in a later subtask). Design-only here.
- **Invariants for the implementer:** the produced `#/` URLs, the `PAGE_MAP` lookup keys, `parseHash()` behavior (including query-strip and `new`→`wizard` alias), and the `lazy()` code-split boundaries are byte-for-byte preserved. The registry is an internal refactor, not a routing-contract change.
- **Boundary:** the parent plan (014 §14) attributed the route registry to its informal "067". Under the 007 numbering, 068 **specifies** the registry as IA; the actual `App.tsx`/`Sidebar.tsx` edit is a downstream implementation subtask (candidate: 064 FE state/component boundaries, or a 070-adjacent nav task), not this design doc.

### 7.3 Information-priority ladder (P1–P5)

A single ladder shared by all screens. Higher priority = shown first / more prominent by default. **This subtask only defines the bands and the mapping; the default-visible-vs-collapsed-vs-gated *rules* are 069's deliverable.**

| Band | Meaning | Primary sources (verified) | Example surfaces |
| --- | --- | --- | --- |
| **P1 — Run state** | Is a run active? which checkpoint / phase / PID / exit? | `AppState.is_running/current_phase/checkpoint_path/status_label` (`types/index.ts:87-94`) | Home stat boxes, Monitor header, Sidebar project switcher (`Sidebar.tsx:154-172`) |
| **P2 — Tree / node / score** | node count, best score, per-node status/depth/metrics | `nodesData` (WebSocket), `TreeVisualization`, `PhaseStepper` | Tree page, Monitor phase stepper |
| **P3 — Artifacts / reports** | paper PDF, review scores, figures, reproducibility, EAR | `CheckpointSummary`, `Results/*` | Results page, DetailPanel Report/Memory tabs |
| **P4 — Trace / cost / logs** | MCP trace, code snippets, cost breakdown, log stream | `DetailPanelTabs/{TraceTab,CodeTab}`, `AppState.cost`, Monitor log stream | DetailPanel Trace/Code/Access tabs, Monitor logs |
| **P5 — Advanced / debug** | raw JSON dump, raw-YAML editor, env-key readback, workflow internals | `DetailPanel {} Raw` (`:411-419`), `monitorSections.tsx` dumps, `PublishYamlEditor`, `/api/env-keys`, `WorkflowPage` | `{ } Raw` tab, raw-YAML editor, workflow graph internals |

**Mapping rule of thumb (normative for 069–071):** default operator view should reach P1–P3 without opting in; P4 is one interaction away (a tab/expander already present); P5 is Developer-Mode-gated (071). The **only** always-on P5 element today is the `{ } Raw` tab — the IA marks it the canonical first gate target.

### 7.4 Settings information architecture (category structure)

The IA groups the inventoried controls (from 067) into **five information categories**. This is a *taxonomy*, not a widget spec — 070 chooses tabs vs accordions; 069 chooses disclosure defaults. **Hard invariant carried into 070: the flat 24-key POST (`SettingsPage.tsx:235-260`) and every field survive; no card is deleted; "Available Skills" (read-only) and "Project Management" (delete) stay reachable.**

| Category | Members (current cards → controls) | Rationale |
| --- | --- | --- |
| **A. Essentials** | Language (Card 1); LLM provider + model + temperature (Card 2 core); Save / Test LLM bar | Touched almost every run |
| **B. Project** | Paper Retrieval backend (Card 3); VLM Figure Review model (Card 4); per-phase models `model_idea/bfts/coding/eval/paper/review` (**REVIEW_REQUIRED** — declared in `types/index.ts:59-71`, currently only surfaced in `Wizard/StepResources.tsx`; decide surface-here-as-Advanced vs keep-per-run; **do not drop**) | Per-project, occasional |
| **C. Infrastructure** | SLURM/HPC (Card 6) + Detect; Container (Card 7) + Detect Runtime; SSH (Card 9) + Test; Letta base URL / deployment / embedding (Card 5 non-secret) | Infra/HPC; rarely changed, env-scoped |
| **D. Secrets** | LLM API key, Semantic Scholar key, Letta API key (persisted to `.env` via `/api/settings`) | Secret; isolate. Fields stay `type="password"`; the `/api/env-keys` readback is P5 (071 gates it) |
| **E. Diagnostics & Danger Zone** | Available Skills read-only table (Card 8); Restart Letta (Card 5 action → `/api/memory/restart`); Project delete (Card 10) | Read-only diagnostics + irreversible/daemon-affecting actions grouped away from Primary |

The provider/model tables and the two-stage Letta handle encode/decode (`_splitHandle`, `settingsConstants.ts:71-86`) KEEP unchanged. Hardcoded/stale model lists (`settingsConstants.ts:9-15`) are a separate model-catalog concern — **not** a deletion and **not** an IA problem.

### 7.5 Screen-level classification (summary)

| Screen | Classification | IA note |
| --- | --- | --- |
| `home`, `experiments`, `idea`, `paperbench` (+ sub-routes) | KEEP | Regroup only (§7.1) |
| `monitor`, `tree`, `results`, `new`/`wizard`, `settings` | ADAPT | Priority-banded (§7.3) / categorized (§7.4) in later subtasks |
| `workflow` | REVIEW_REQUIRED | Power-user pipeline editor; sits in Configure; internals are P5 |
| `PAGE_MAP` / `NAV_ITEMS` duplication | REVIEW_REQUIRED | Replace with route SSOT (§7.2) |

## 8. Concrete Work Items

1. **Verify inventory inputs.** Confirm 067's settings inventory (or, if 067 not yet landed, re-derive from `SettingsPage.tsx` directly) and the route/nav facts (`App.tsx:41-56`, `Sidebar.tsx:12-23`). Reconcile the 010 counts: 14 `PAGE_MAP` keys / 13 distinct destinations / 10 `NAV_ITEMS`.
2. **Write §7.1 screen taxonomy** into this document: the four groups, their route members, and the KEEP/ADAPT classification. Confirm every current route key appears in exactly one group.
3. **Write §7.2 route-SSOT design**: the target registry shape and its byte-for-byte routing invariants; mark REVIEW_REQUIRED and name the downstream implementation subtask.
4. **Write §7.3 P1–P5 ladder**: the five bands with verified source anchors and the per-surface mapping; declare the `{ } Raw` tab the canonical first gate target for 071.
5. **Write §7.4 settings category structure**: the five categories over the inventoried controls, with the flat-24-key invariant restated and the per-phase-model REVIEW_REQUIRED flagged.
6. **Write §7.5 classification summary** and the §14/§15 hand-off boundaries to 069–073.
7. **Cross-check i18n impact**: enumerate the new label strings the IA will require (four group labels + any category labels) and note they must land in all three locales (`en.ts`/`ja.ts`/`zh.ts`) when implemented — recorded as a constraint, not added here.
8. **Add cross-references** to `014` §§2/4/7/8–9 and to sibling subtask docs (067, 069, 070, 071, 072, 073) so the IA is traceable.

## 9. Files Expected to Change

**In this subtask (068):**

| Path | Change |
| --- | --- |
| `docs/refactoring/subtasks/068_define_dashboard_information_architecture.md` | **Created** — this IA specification (the only file written) |

No other file — no `.tsx`, `.ts`, `.css`, `.py`, `.yaml`, workflow, i18n, or config — is created or modified in subtask 068.

**Files the IA will GOVERN in downstream subtasks (informational; NOT changed here):**

| Path | Governed by (this doc) | Subtask that edits it |
| --- | --- | --- |
| `src/App.tsx` (`PAGE_MAP` `:41-56`) | §7.2 route SSOT | later (route-registry impl; e.g. 064) |
| `src/components/Layout/Sidebar.tsx` (`NAV_ITEMS` `:12-23`) | §7.1 grouping, §7.2 SSOT | later (route-registry / nav impl) |
| `src/components/Settings/SettingsPage.tsx` (1049) | §7.4 category structure | **070** |
| Home / Monitor / Tree / Results surfaces | §7.3 P1–P5 ladder | **069** |
| `{ } Raw` tab (`Tree/DetailPanel.tsx:411-419`) + other P5 dumps | §7.3 (P5 band) | **071** |
| `src/i18n/{en,ja,zh}.ts` | §7.1/§7.4 new label strings | **070/073** (trilingual) |

(Paths are under `ari-core/ari/viz/frontend/`.)

## 10. Files / APIs That Must Not Be Broken

This is a design doc and breaks nothing at execution time. The **contracts the IA must never propose breaking** (carried into 069–073):

- **Dashboard API contract.** All `services/api.ts` (863 lines) endpoint paths, HTTP verbs, and request/response field names, and the flat **24-key `/api/settings`** object (`SettingsPage.tsx:235-260`). The two error regimes (`get/post` throw vs `pbGet/pbPost` return `{error}`, `api.ts:18-32,787-799`) KEEP.
- **Hash-router contract.** Every `#/` URL, all `PAGE_MAP` keys (`App.tsx:41-56`), `parseHash()` behavior (query-strip + `new`→`wizard` alias), and `lazy()` split boundaries.
- **Settings persistence surface.** No setting deleted or made unreachable; provider/model tables and the Letta handle encode/decode KEEP.
- **Broader ARI contracts (untouched here and in all Phase-6 work):** CLI `ari` (`ari.cli:app`), `ari.public.*`, MCP tool contracts (`ari-skill-*` servers), checkpoint/output/config file formats, `ari-skill-* → ari-core` stable interfaces, and README/docs usage. The dashboard-UX track is confined to `ari-core/ari/viz/frontend/` view-layer changes plus explicitly-flagged REVIEW_REQUIRED backend audits.

## 11. Compatibility Constraints

- **View-layer only, downstream.** Every decision here is realized as client-side grouping/rendering; none changes which endpoints are called or when (`AppContext` 5 s polling + WebSocket feed untouched).
- **Adapter/SSOT note (route registry).** If the route registry (§7.2) is implemented, it must be a pure refactor: `PAGE_MAP`/`NAV_ITEMS` become derived views of one table with identical output. No compatibility shim is otherwise needed because no external contract is touched.
- **i18n parity.** `en.ts` (444) vs `ja.ts`/`zh.ts` (441) already have minor key drift; any new IA string (group/category labels) must be added to all three locales to keep the `scripts/docs/check_i18n_js.py` gate green.
- **No `sonfigs/`.** The hypothesized `sonfigs/` directory does not exist anywhere in the repo and is irrelevant to the dashboard; the config trio (`ari/config/` code vs `ari/configs/` packaged defaults vs top-level `config/` rubric data) is owned by subtask 003, not this one.

## 12. Tests to Run

068 writes only a Markdown file, so no runtime test can fail. Run these to prove the working tree is unperturbed (they must pass **unchanged** relative to `main`):

```bash
# From repo root: /home/t-kotama/workplace/ARI
python -m compileall .            # no .py touched → must stay green
pytest -q                         # backend/contract suite unchanged
ruff check .                      # no lint delta

# Frontend (from ari-core/ari/viz/frontend/) — proves the SPA is untouched:
npm run typecheck                 # tsc --noEmit
npm test                          # Vitest suite (incl. PaperBench __tests__)
npm run build                     # Vite production build still succeeds
```

Additionally, before considering 068 "done," confirm the doc-quality gates that watch `docs/`:

```bash
python scripts/docs/check_doc_links.py       # no broken links in the new .md
python scripts/docs/check_doc_sources.py     # cited file:line anchors resolve
```

(`radon` is **not installed**; do not add a complexity step. `pnpm` is **not** available — use `npm`.)

## 13. Acceptance Criteria

- [ ] `docs/refactoring/subtasks/068_define_dashboard_information_architecture.md` exists and is the **only** file added/modified by this subtask (`git status` shows exactly one new file).
- [ ] §7.1 assigns **every** current route key (`home, experiments, monitor, tree, results, new/wizard, idea, workflow, settings, paperbench, paperbench/import, paperbench/run, paperbench/results`) to exactly one navigation group; no route renamed/removed.
- [ ] §7.2 specifies the route SSOT with explicit byte-for-byte routing invariants (URLs, keys, alias, split boundaries) and marks it REVIEW_REQUIRED.
- [ ] §7.3 defines P1–P5 with a verified source anchor per band and names the `{ } Raw` tab (`DetailPanel.tsx:411-419`) the first P5 gate target.
- [ ] §7.4 maps every inventoried settings control into one of five categories, restates the flat-24-key invariant, and flags the per-phase-model fields (`types/index.ts:59-71`) REVIEW_REQUIRED (not dropped).
- [ ] The 069/070/071/072/073 hand-off boundaries are explicit (§3, §9, §15) — 068 owns *structure*, not disclosure/widget/gate/state implementation.
- [ ] Every file:line anchor cited resolves against the current tree; `check_doc_links.py` / `check_doc_sources.py` pass.
- [ ] All Section-12 commands pass unchanged relative to `main` (no runtime delta).
- [ ] No use of "deprecated" for internal UI code; the term appears only (if at all) for external contracts.

## 14. Rollback Plan

Trivial and self-contained: this subtask adds one Markdown file and touches nothing else.

- **To roll back:** `git rm docs/refactoring/subtasks/068_define_dashboard_information_architecture.md` (or revert the single commit). No code, config, workflow, frontend, or generated artifact is affected, so there is nothing else to undo and no migration to reverse.
- Because 068 changes no runtime behavior, rollback cannot break a build, a test, or the dashboard. Downstream subtasks (069–073) that were to consume this IA simply lose their design input until it is re-added.

## 15. Dependencies

Consistent with the master DEPENDENCY GRAPH (`059 -> 067, 068, 069, 070, 071, 072, 073`) and `007_subtask_index.md:446` (`059 --> 068`).

- **Hard predecessor (graph edge):** **059** (`inventory_dashboard_frontend_backend_structure`) — the FE/BE structure inventory that establishes the stack facts (Vite/React/TS, hash router, `AppContext` polling) this IA builds on. 068 must not start before 059's inventory exists.
- **Strongly-recommended predecessor (sibling under 059):** **067** (`inventory_dashboard_visible_settings`) — the raw 9/10-card settings inventory this IA categorizes in §7.4. The master graph roots 067 and 068 both on 059 (siblings); this document *consumes* 067's output, so land 067 first in practice. If 067 is unavailable, re-derive the inventory from `SettingsPage.tsx` directly.
- **Downstream consumers (this IA is their design input):** **069** (progressive disclosure — consumes §7.3), **070** (settings panel refactor — consumes §7.4), **071** (developer mode — consumes the P5 mapping), **072** (empty/loading/error states), **073** (UX regression checks). In the master graph these are rooted on 059; conceptually they depend on the structure fixed here.
- **Related (not blocking):** Phase-5 subtasks **062/063/064** (backend routes→services, FE API/types, FE state/component boundaries) and **060/061** (API-contract inventory, DTO/schema policy) share the `viz/` surface; the IA references but does not depend on them.
- **Inventory-before-runtime rule:** 068 is itself a design (non-runtime) subtask and is one of the inventory/design gates that must precede runtime UI changes (070/071/072).

## 16. Risk Level

- **Overall risk: LOW.**
- **Changes runtime code: NO.** This subtask produces a single IA specification `.md` and touches no `.tsx`, `.ts`, `.css`, `.py`, `.yaml`, config, workflow, prompt, i18n file, or directory name. (`007_subtask_index.md` row 115 marks 068 "Changes runtime code: No".)
- The *decisions* recorded here (screen grouping, route SSOT, P1–P5 bands, settings categories) carry design risk that is realized only when 069–073 implement them; those subtasks own that risk and must preserve the dashboard-API and hash-router contracts and the flat-24-key POST.
- The one elevated design tension to surface (not resolve here): the per-phase-model fields declared-but-unused in `Settings` (`types/index.ts:59-71`) — placing them wrongly in 070 could either duplicate the Wizard's controls or drop them; flagged REVIEW_REQUIRED.

## 17. Notes for Implementer

- **You are writing a spec, not code.** The deliverable is this document's §7. Do not open an editor on any `.tsx`/`.ts`; if you find yourself proposing an edit, that belongs to 069/070/071.
- **Follow the 007 numbering, not 014 §14.** The parent plan's informal 068="Settings hierarchy" label is superseded; 068 = information architecture. Cite `007_subtask_index.md` if the mismatch confuses a reader.
- **Verify every anchor.** File:line references drift; re-grep `PAGE_MAP` (`App.tsx`), `NAV_ITEMS` (`Sidebar.tsx`), the `handleSave` 24-key list (`SettingsPage.tsx:235-260`), and the `{ } Raw` tab (`DetailPanel.tsx`) before finalizing, so `check_doc_sources.py` stays green.
- **Reconcile the route counts once, explicitly.** 14 `PAGE_MAP` keys, 13 distinct destinations (`new`/`wizard` alias), 10 `NAV_ITEMS`, 3 non-nav `paperbench/*` sub-routes. The parent plan says "12 hash routes"; state your verified count to avoid propagating an off-by-one.
- **Correct the stale "Sidebar omits paperbench" note.** The current `Sidebar.tsx:12-23` *does* include `paperbench`; what it omits is the three `paperbench/*` **sub-routes**. Say so precisely.
- **Preserve the guardrails verbatim** in the spec: no setting deleted, no dashboard-API break, no raw/debug exposed by default, hash-router URLs stable. These are the acceptance gates every downstream subtask inherits.
- **`node_modules` is not committed** (`.gitignore:113`); `package-lock.json` (140 KB) is tracked. Do not treat vendored deps as a hygiene item in this IA — it is out of scope and factually not present in git.
- **Keep the doc self-contained.** A fresh session should be able to read this file plus `014` and produce 069/070 without re-reading the whole frontend.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **068** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
