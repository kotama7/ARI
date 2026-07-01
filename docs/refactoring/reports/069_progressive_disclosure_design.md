# Dashboard Progressive-Disclosure Design Specification

> **Subtask:** 069 — `design_dashboard_progressive_disclosure` (Phase 6: Dashboard UX, Low risk, **no runtime code change**).
> **Status:** DESIGN SPECIFICATION (Markdown deliverable only). This document changes **no** runtime code, imports, prompts, configs, workflows, frontend source, i18n, or directory names. It is the design spec the downstream runtime subtasks **070** (settings panel), **071** (developer mode), **072** (empty/loading/error states) implement against.
> **Repo:** `/home/t-kotama/workplace/ARI` · branch `whole_refactoring` · `ari-core` `0.9.0` · captured 2026-07-01.
> **Depends on:** 059 (`inventory_dashboard_frontend_backend_structure` → `docs/refactoring/reports/dashboard_structure_inventory.md`). Reconciled against 067 (`docs/refactoring/reports/067_dashboard_visible_settings_inventory.md`). 068 (`define_dashboard_information_architecture`) does **not yet exist** as of capture; where its output is needed the parent plan `docs/refactoring/014_dashboard_ux_refactoring_plan.md` §§3–9 is cited as the interim source.
> **Method:** every file:line anchor in this doc was re-verified against the live, unmodified tree on 2026-07-01 (verification log in §11). Where a plan figure disagreed with the live tree, the live tree is recorded.
> **Classification vocabulary:** KEEP / ADAPT / MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED.
> **"deprecated"** is reserved in this document for external contracts (dashboard API endpoints/schema, CLI `ari`, MCP tool contracts, `ari.public.*`, documented import paths, `ari-skill-*` stable interfaces). It is **never** applied to internal UI code — P5 elements are "gated," not "deprecated."

---

## 1. Purpose and Scope

This specification finalizes a single **information-priority ladder (P1–P5)** for the ARI dashboard (`ari-core/ari/viz/frontend/`, React 18.3 + TypeScript 5.5 + Vite 5 SPA) and the **disclosure rules** that decide, for every user-visible surface, what is shown by default, what is one interaction away, and what is gated behind a future Developer Mode (subtask 071).

It expands the abstract ladder in the parent plan (`014_dashboard_ux_refactoring_plan.md` §7) into an **implementable, element-by-element spec** with verified file:line anchors, so downstream implementers (070/071/072) are not free to reinvent priorities per screen.

**In scope (design only):**

1. The canonical **P1–P5 ladder** with concrete data-source bindings (`AppState`/`CostSummary`/`CheckpointSummary` fields, WebSocket node feed) — §2.
2. **Disclosure rules** (default-visible / one-interaction-away / Developer-Mode-gated) — §3.
3. **Per-screen application** for the four everyday screens `home`, `monitor`, `tree`, `results` — §4.
4. The **DetailPanel tab classification** exploiting the existing `overview`-default structure — §5.
5. The **always-on P5 gating inventory** (verbatim hand-off checklist for 071) — §6.
6. The **invariants / acceptance contract** 070/071/072 must not violate — §7.
7. A **cross-reference matrix** to sibling subtasks 067/068/070/071/072/073 — §8.
8. An **open-questions / REVIEW_REQUIRED** list — §9.

**Out of scope (belongs to other subtasks — this doc references, does not implement):**

- The Developer-Mode toggle mechanism / any gating logic → **071**.
- Refactoring `SettingsPage.tsx` into tabs/disclosure → **070**.
- The empty/loading/error state kit → **072**.
- Route-registry / sidebar-grouping code → Phase-5 subtask **064** (and parent §8).
- Any backend, `services/api.ts`, `types/index.ts`, or `AppContext` change.
- Model-catalog freshness (`settingsConstants.ts` hardcoded lists) — noted only.
- The accessibility pass → parent §13 / subtask **073**.

**Baseline facts this design binds to (verified, from 059):**

- Routing is a hand-rolled hash router: `parseHash()` maps `#/<route>` to a `lazy()` page; `PAGE_MAP` declares **14 keys** (`App.tsx:41-56`), with legacy `new` aliased to `wizard` (`App.tsx:37,47-48`). Sidebar `NAV_ITEMS` has **10 keys** (`Sidebar.tsx:12-22`).
- Global state is a single React Context (`context/AppContext.tsx`, 120 LOC): polls `/state` + `/api/checkpoints` every **5000 ms** (`STATE_POLL_MS`, `AppContext.tsx:34,86-89`) and prefers a WebSocket node feed, falling back to `state.nodes` (`AppContext.tsx:96`). No Redux/Zustand/react-query.
- No CSS framework — `src/styles/dashboard.css` manifest + 5 topic files + pervasive inline `style={{}}`.

The core consequence for this design: **priority can only be expressed as client-side conditional rendering / ordering — never as "fetch less."** The 5000 ms poll and the WebSocket feed are shared and stay unchanged.

---

## 2. Canonical Information-Priority Ladder (P1 highest → P5 lowest)

This is the normative ladder. Every downstream screen decision cites a level here. Data-source anchors verified against `types/index.ts` and the owning components.

| Level | Meaning | Concrete data source (verified anchor) | Default treatment |
|---|---|---|---|
| **P1 — Run state** | Is a run active? which checkpoint? phase / PID / running / stopped / status label | `AppState.is_running` (`types/index.ts:92`), `current_phase` (`:94`), `checkpoint_id` (`:89`), `checkpoint_path` (`:90`), `running_pid` (`:91`), `status_label` (`:93`); JS-compat aliases `running` (`:118`) / `pid` (`:119`); sidebar project switcher + `status_label` (`Sidebar.tsx:155-170`) | **Always visible, top of page** |
| **P2 — Tree / node / progress / score** | node count, best score, per-node status/depth/metrics | `nodesData` (WebSocket → `state.nodes` fallback, `AppContext.tsx:96`); `TreeVisualization`, `PhaseStepper` (`MonitorPage.tsx:250`), `computeBestMetrics` (`monitorSections.tsx`, used `MonitorPage.tsx:69`) | **Always visible** |
| **P3 — Artifacts / reports** | paper PDF, review scores, figures, reproducibility, EAR | `CheckpointSummary` (`types/index.ts:237`); `Results/*` render fns (`resultSections.tsx:25,931,1002,1055,1134,1443`) | **Always visible on `results`** |
| **P4 — Trace / prompt / cost / logs** | MCP trace, code snippets, cost breakdown, streamed logs | `DetailPanelTabs/TraceTab.tsx`, `CodeTab.tsx`; `AppState.cost` = `CostSummary` object (`types/index.ts:79-86`); Monitor log stream (`api_experiment` SSE) | **One interaction away** (tab/expander, not pre-expanded) |
| **P5 — Advanced / debug** | raw JSON node dump, raw-YAML editor, env-key readback, workflow internals, full stack traces, advanced infra settings | `DetailPanel` `{ } Raw` (`:411-419`), `PublishYamlEditor.tsx`, `/api/env-keys` readback, `WorkflowPage`, `main.tsx:20-22,38` | **Developer-Mode-gated** (hidden by default) |

**Binding notes (do not reinterpret):**

- `AppState.cost` is a `CostSummary` **object** (`total_cost_usd`, `total_tokens`, `call_count`, `by_phase`, `by_model` — `types/index.ts:79-86`), **not** a number. Cost surfaces are P4 and must render the object, per the schema contract pinned by `tests/test_api_schema_contract.py` (010 §4 Contract B).
- P1 canonical fields AND their JS-compat aliases (`running`/`pid`) are both a dashboard contract (010 §5). The ladder binds to existing fields only; it must not require any new `AppState`/`CostSummary`/`CheckpointSummary` field.
- P2 node data has a defined fallback order (`wsNodes` → `state.nodes`, `AppContext.tsx:96`). The ladder must render P2 identically regardless of which source is live.

---

## 3. Disclosure Rules (normative)

The five rules below are the normative contract every downstream subtask (070/071/072) obeys. They are numbered so a later regression check (073) can cite them.

1. **Default view = P1–P3.** With Developer Mode off (the default state), any user sees run state (P1), tree/score (P2), and artifacts (P3) without extra clicks.
2. **P4 is exactly one interaction away.** Trace / cost / logs render behind an always-present tab or expander that is **not** the default state. The DetailPanel already satisfies this: default tab is `overview` (`DetailPanel.tsx:37,45`); the `trace` / `code` tabs are present but not the default (`DetailPanel.tsx:358-359`). Keep this pattern; do **not** pre-expand P4.
3. **P5 is Developer-Mode-gated.** Raw JSON, raw YAML, env-key readback, workflow-internal editing, and full stack traces render **only** when Developer Mode (subtask 071) is on. When off they are **hidden via conditional rendering** — not CSS-hidden, not disabled-with-tooltip — so raw payloads are not shipped in the DOM by default.
4. **Settings follow the frequency buckets** owned by 067/068 (Primary always visible; Secondary one section away; Advanced behind a disclosure; Developer/Dangerous grouped and visually distinct). This spec **references** those buckets (§8); it does not redefine them. The mapping of the 35 settings controls to buckets is 067's `docs/refactoring/reports/067_dashboard_visible_settings_inventory.md` §3–§4.
5. **Disclosure is view-only.** No rule changes which endpoints are called or when. `AppContext` polling (5000 ms, `AppContext.tsx:34,86-89`) and the WebSocket feed are untouched; priority is expressed purely as conditional rendering / ordering. A rule that would require a backend change, a new endpoint, a new fetch cadence, or a `types/index.ts` field is **out of bounds** and must instead be filed as REVIEW_REQUIRED (§9).

---

## 4. Per-Screen Application

Element-by-element assignment for the four everyday screens. Disclosure verbs: **visible** (default-rendered), **collapsed** (rendered but behind a non-default tab/expander = P4), **gated** (Developer-Mode-only = P5). Every element carries a verified anchor. Classification tag is the treatment the downstream implementer applies.

### 4.1 `home` — `HomePage.tsx` (122 LOC)

| Element | Anchor | Priority | Disclosure verb | Tag |
|---|---|---|---|---|
| 3 `StatBox` (runs / best score / total nodes) | `HomePage.tsx:45,49,53` | P2/P3 | visible | KEEP |
| Latest Experiment card + status badge | `HomePage.tsx` (Latest card) | P1/P3 | visible | KEEP |
| Quick Actions | `HomePage.tsx` | P1 | visible | KEEP |
| Empty state (`No experiments yet`) | `HomePage.tsx:114-116` | P1 (first-run) | visible — needs first-class treatment (**defer implementation to 072**) | ADAPT (072) |

No P5 element exists on `home` today — **keep it that way** (rule 3). No gating work here; the only follow-up is the empty-state kit owned by 072.

### 4.2 `monitor` — `MonitorPage.tsx` (502 LOC) + sections

| Element | Anchor | Priority | Disclosure verb | Tag |
|---|---|---|---|---|
| `PhaseStepper` | `MonitorPage.tsx:250` (import `:13`) | P1/P2 | visible | KEEP |
| Embedded `TreeVisualization` | `MonitorPage.tsx` (embed) | P2 | visible | KEEP |
| Cost summary + model badge | `MonitorPage.tsx` (inline); `AppState.cost` (`CostSummary`, `types/index.ts:79-86`) | P4 | **REVIEW_REQUIRED**: currently inline/visible — decide default-visible vs collapsed (§9-a) | REVIEW_REQUIRED |
| `GpuMonitor` (toggled) | render `MonitorPage.tsx:253`; toggle `:139`; button `:322-324` | P4 | collapsed — already gated behind `gpuVisible` toggle (`:25`), default off | KEEP |
| Stage run / stop controls | `MonitorPage.tsx` (`runStage`/`stopExperiment`) | P1 | visible (confirmation on launch when a run is active — 072/parent §11) | KEEP |
| Log stream (SSE) | `MonitorPage.tsx` → `api_experiment` `/api/logs` | P4 | collapsed / one-interaction | KEEP |
| Raw `JSON.stringify(validated_parameter_sweep)` | `monitorSections.tsx:241` | **P5** | **gated** | ADAPT (071) |
| Raw `JSON.stringify(ctx, null, 2)` | `monitorSections.tsx:339` | **P5** | **gated** | ADAPT (071) |

### 4.3 `tree` — `TreePage.tsx` (206) + `TreeVisualization.tsx` (366) + `DetailPanel.tsx` (425)

| Element | Anchor | Priority | Disclosure verb | Tag |
|---|---|---|---|---|
| Tree canvas (D3) + status/depth filters | `TreeVisualization.tsx`; `TreePage.tsx` | P2 | visible | KEEP |
| Node `DetailPanel` tab stack | `DetailPanel.tsx:354-421` | P2–P5 | per §5 | see §5 |
| DetailPanel `{ } Raw` tab | `DetailPanel.tsx:364` (button), `:411-419` (content), dump `:417` | **P5** | **gated** — the single always-on P5 element on this screen | ADAPT (071) |

### 4.4 `results` — `ResultsPage.tsx` (462) + `resultSections.tsx` (1590)

| Element | Anchor | Priority | Disclosure verb | Tag |
|---|---|---|---|---|
| Paper (PDF/editor), review scores, figures, reproducibility, EAR | `resultSections.tsx:25,931,1002,1055,1134,1443` (6 exported `render*` fns) | P3 | visible | KEEP |
| Inline `JSON.stringify` payload dumps (×6) | `resultSections.tsx:444,481,523,704,992,1022` | **P5** | **gated** | ADAPT (071) |
| `PublishYamlEditor` raw-YAML editor | `Results/PublishYamlEditor.tsx` (162 LOC) | **P5** | **gated** (keep reachable, gate default visibility) | ADAPT (071) |

> Note (grounding, not a task for 069): the six `resultSections.tsx` `JSON.stringify` sites are heterogeneous — `:444/:481/:523` build ORS-chain display strings, `:704` is a file-content fallback, `:992/:1022` are reproducibility-record dumps. 071 must confirm each is a *display dump* (safe to gate) and not load-bearing formatting before gating; flagged as an implementation note, not a REVIEW_REQUIRED blocker.

---

## 5. DetailPanel Tab Classification

The DetailPanel is the **model case** for good disclosure (unlike the god-components in 059 §1): it is cleanly split into `DetailPanelTabs/*`, has a default `overview` tab (`DetailPanel.tsx:37,45`), and one stray always-on P5 element (`{ } Raw`). Downstream work should **emulate this structure, not rebuild it**.

| Tab | Anchor (button / content) | Priority | Disclosure |
|---|---|---|---|
| Overview (default) | button `DetailPanel.tsx:357`; content `:368` | P2/P3 | Always on (default tab) |
| MCP Trace | button `:358` → `TraceTab.tsx` (content `:371-373`) | P4 | On, not default |
| Code | button `:359` → `CodeTab.tsx` (content `:376-378`) | P4 | On, not default |
| Memory | button `:360` → `MemoryTab.tsx` (content `:381-390`) | P3/P4 | On, not default |
| Access | button `:361` → `AccessTab.tsx` (content `:393-399`) | P4 | On, not default |
| Report | button `:363` → `ReportTab.tsx` (content `:402-408`) | P3 | On (already hidden when `node_report.json` absent — `reportAvailable` guard, `:363`) |
| **`{ } Raw`** | button `:364`; content `:411-419`; dump `:417` | **P5** | **Developer-Mode-gated** |

**Disclosure rule application:** rule 2 (P4 one-interaction) is already met by the `trace`/`code`/`access` tabs being present-but-not-default. Rule 3 (P5 gated) requires exactly one change from 071 — wrapping the `{ } Raw` `tabBtn('raw', …)` at `:364` **and** its content block `:411-419` in the Developer-Mode conditional. The `Report` tab's existing `reportAvailable` conditional (`:363`) is the pattern to mirror.

---

## 6. Always-On P5 Gating Inventory (hand-off checklist for subtask 071)

This is the literal checklist 071 consumes to decide what the Developer-Mode toggle hides. Each row is a currently always-on P5 (or P5-flavored) surface, its verified anchor, and its target disclosure. **Missing an entry here means a raw dump ships to end users** — 071 must gate every row (or explicitly, with a note, decide not to).

| # | Surface | Anchor | Target | Note |
|---|---|---|---|---|
| 1 | `{ } Raw` full-node JSON dump | `DetailPanel.tsx:364` (button), `:411-419` (content), `:417` (`JSON.stringify(node,null,2).slice(0,6000)`) | Developer-Mode-gated | The single always-on P5 on `tree`; mirror the `reportAvailable` guard pattern |
| 2 | Raw `validated_parameter_sweep` dump | `monitorSections.tsx:241` | Developer-Mode-gated | `.slice(0,150)` display dump |
| 3 | Raw `ctx` dump | `monitorSections.tsx:339` | Developer-Mode-gated | `JSON.stringify(ctx, null, 2)` |
| 4 | Inline result payload dumps (×6) | `resultSections.tsx:444,481,523,704,992,1022` | Developer-Mode-gated | Confirm each is a display dump before gating (§4.4 note) |
| 5 | Raw-YAML editor | `Results/PublishYamlEditor.tsx` | Developer-Mode-gated (keep reachable) | P5; gate default visibility only |
| 6 | Env-key secret readback | wrapper `services/api.ts` `fetchEnvKeys` (`fetchEnvKeys` → `GET /api/env-keys`); consumer `Wizard/StepResources.tsx:333-342` `autoReadApiKey` (auto-fires on mount `:299`, button `:674`) | Developer-Mode-gate the readback UI; do **not** auto-read secrets on Wizard mount without user action | Returns real secret values to the browser (067 §5). **Endpoint contract unchanged** |
| 7 | Full stack-trace rendering | `main.tsx:20` (`error.message`), `:22` (`error.stack`), `:38` (`innerHTML` catch) | Developer-Mode-gated; non-developers get a friendly message + retry (072) | P5 developer content on the default surface |
| 8 | Raw trace `JSON.stringify` | `DetailPanelTabs/TraceTab.tsx:42` | **Flag only** — P4 tab content; keep. Its raw fallback is P5-flavored | Do not gate the whole Trace tab (it is P4); note only |
| 9 | `dangerouslySetInnerHTML` on `summaryHtml` | `Wizard/StepScope.tsx:137` | **REVIEW_REQUIRED** — sanitize/replace is 071/072 work; **this doc only flags it** | Security-flavored; needs a look before change (§9-b) |

**Dangerous-operation adjacency (record only; owned by parent §11 / subtask 071):** the GPU-monitor SLURM auto-resubmit sends `confirmed:true` unconditionally (`services/api.ts` `gpuMonitorAction`; `Monitor/GpuMonitor.tsx`), making the backend confirmation guard non-functional. This is a REVIEW_REQUIRED **backend audit**, not a disclosure change — listed so 071 does not conflate "hide a dump" with "fix a broken guard."

---

## 7. Invariants / Acceptance Contract for 070 / 071 / 072

The design imposes these invariants on every downstream runtime subtask. A PR that violates any of them is out of spec. (These mirror parent `014` §1 hard constraints and the contract policy `010` §§4–5.)

1. **No setting or affordance deleted.** Progressive disclosure only reorders, collapses, or gates. Every field, tab, editor, and dangerous action stays reachable (P5 items via Developer Mode). Nothing in this design is DELETE / MOVE_TO_LEGACY.
2. **No dashboard-API contract break.** Every endpoint in `services/api.ts` (863 LOC) and the `api_*.py` modules — paths, HTTP verbs, request/response field names — stays stable, including `/state`, `/api/checkpoints`, `/api/checkpoint/{id}/*`, `/api/settings` (flat **24-key** object, 067 §4.1), `/api/env-keys`, `/api/memory/restart`, `/api/paperbench/*`. Disclosure is UI-only; no endpoint may be added or changed to satisfy it.
3. **Both API error regimes preserved.** `get`/`post` throw on non-2xx (`services/api.ts:18-32`); `pbGet`/`pbPost` never throw and return `{error}` bodies (`services/api.ts:787-799`). The design must not require unifying these at the transport layer — a presentational `<ErrorBanner>` wrapper is 072's concern (parent §12).
4. **Hash-router contract preserved.** `PAGE_MAP` keys and `#/` URLs (`App.tsx:41-56`), including the legacy `new`→`wizard` alias (`App.tsx:37`), are unchanged. The ladder must not require renaming or removing a route.
5. **View-layer only / data flow untouched.** `AppContext` polling (5000 ms, `AppContext.tsx:34,86-89`) + the WebSocket feed (`useWebSocket.ts`, `wsPort = httpPort + 1`) stay unchanged. The ladder binds to existing `AppState`/`CostSummary`/`CheckpointSummary` fields (`types/index.ts:79-129,237`) and requires no new field.
6. **P5 gating is conditional rendering, not CSS-hiding.** When Developer Mode is off, gated raw payloads must not be present in the DOM (rule 3).
7. **i18n parity.** Any new UX string a downstream implementer introduces (Developer-Mode label, disclosure captions, gated-empty copy, Danger-Zone labels) must land in `i18n/en.ts`, `ja.ts`, and `zh.ts` **together**. Current state: `en.ts` **444** vs `ja.ts`/`zh.ts` **441** = a 3-line drift (verified). Note: `scripts/docs/check_i18n_js.py` covers only the landing JS, **not** these React `i18n/*.ts` files, so the drift is currently unchecked (073 owns a gate for it).
8. **No new dependency.** The design assumes only the current stack (`react`, `react-dom`, `d3` `^7.9.0`, `reactflow` `^11.11.4`); no CSS framework, no state library.
9. **Out-of-frontend contracts untouched.** CLI `ari` (`ari.cli:app`), `ari.public.*`, the 14 `ari-skill-*` MCP tool contracts, checkpoint/output/config file formats, and the `ari-skill-* → ari-core` interface are entirely outside this design's blast radius.

---

## 8. Cross-Reference Matrix to Sibling Subtasks

Keeps the ladder consistent with the outputs it references and the subtasks it gates. (Edges per `007_subtask_index.md`: `059 → 067,068,069,070,071,072,073`.)

| Subtask | Relationship to 069 | What 069 provides / consumes |
|---|---|---|
| 059 `inventory_dashboard_frontend_backend_structure` | **Upstream (hard, blocking)** | Consumes: FE/BE structure, routes (14/10), 5000 ms poll, WS fallback, raw-debug locations (059 §10). |
| 067 `inventory_dashboard_visible_settings` | **Companion input (reconcile)** | Consumes: settings frequency buckets, the 24-key POST, secret-exposure surfaces (067 §5), dangerous actions. 069 does **not** redefine buckets (rule 4). |
| 068 `define_dashboard_information_architecture` | **Companion input (reconcile)** | Owns the IA groupings the ladder references. **068 does not exist yet** — interim source is parent `014` §§3–9; reconciliation is a follow-up when 068 lands (§9-d). |
| 070 `refactor_dashboard_settings_panel` | **Downstream consumer** | Provides: rule 4 (settings follow buckets) + invariant 2 (24-key `/api/settings` contract). |
| 071 `add_dashboard_developer_mode` | **Downstream consumer** | Provides: the §6 always-on P5 gating checklist (consumed verbatim) + rule 3. Owns the toggle mechanism (§9-c). |
| 072 `improve_dashboard_empty_loading_error_states` | **Downstream consumer** | Provides: the P1–P3 default-visible contract + invariant 3 (both error regimes) + the `home` empty-state deferral (§4.1). |
| 073 `add_dashboard_ux_regression_checks` | **Downstream consumer** | Provides: numbered rules (§3) and the §6 checklist as assertions; owns the React `i18n/*.ts` drift gate (invariant 7). |

---

## 9. Open Questions / REVIEW_REQUIRED

Deferred decisions this design records but does not resolve (each names the owning subtask):

- **(a) Monitor cost / model badge default visibility.** `monitor` shows cost + model badge inline today (`MonitorPage.tsx`, `AppState.cost` = `CostSummary`). P4 rule 2 says "one interaction away," but cost is arguably run-state-adjacent (P1-flavored). **Decision owner: 072** (or 064 if it touches Monitor layout). Record: default-visible vs collapsed. Do not silently collapse without a ruling.
- **(b) `StepScope.tsx:137` `dangerouslySetInnerHTML`.** Raw HTML injection on `summaryHtml`. Sanitize (DOMPurify or React-node replacement) vs gate. Security-flavored → **REVIEW_REQUIRED**, owner **071/072**; this doc only flags it (§6 row 9).
- **(c) Developer-Mode mechanism.** localStorage key + discoverability placement (footer vs Settings→Diagnostics) is **not decided here** — **owner: 071**. The parent plan suggests mirroring the existing `ari_lang` localStorage pattern (`i18n/index.ts`), recorded as a hint only.
- **(d) 068 reconciliation.** 068 (`define_dashboard_information_architecture`) does not exist as of 2026-07-01. When it lands, re-verify that the settings-bucket references in rule 4 match 068's IA groupings; if 068 diverges from 067/parent `014`, 068 wins and this cross-reference (§8) must be revisited. **Owner: whoever authors 068**, then a light 069 re-check.
- **(e) `main.tsx` stack rendering.** Gating full stack traces (rows 7) is a security-flavored change; confirm no build/CI harness relies on the on-page stack before gating. **Owner: 072** (with a security look).

---

## 10. Classification Summary

- **KEEP:** all P1–P3 surfaces on `home`/`monitor`/`tree`/`results`; the DetailPanel default `overview` tab and its P4 `trace`/`code`/`memory`/`access`/`report` tabs; the `common/` primitives (`Card.tsx` 17, `StatBox.tsx` 14, `Badge.tsx` 10, `StatusBadge.tsx` 16); the `GpuMonitor` existing toggle.
- **ADAPT (later, 071/072):** each always-on P5 element in §6 rows 1–7 → conditional render behind Developer Mode (071); the `home` empty state → first-class treatment (072).
- **REVIEW_REQUIRED:** `StepScope.tsx:137` HTML injection (§9-b); `main.tsx` stack rendering (§9-e); Monitor cost/badge default (§9-a). Security- or ruling-flavored — no change in this design.
- **MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE:** **none.** Progressive disclosure adds gating; it does not delete or relocate code.

The word "deprecated" is applied to **no** internal UI element in this document.

---

## 11. Anchor Verification Log (spot-check ≥ 10, per §13)

Every anchor cited above was re-verified against the live tree on 2026-07-01 (branch `whole_refactoring`). Line counts (`wc -l`): `App.tsx` 94, `main.tsx` 40, `AppContext.tsx` 120, `Sidebar.tsx` 191, `types/index.ts` 264, `HomePage.tsx` 122, `MonitorPage.tsx` 502, `monitorSections.tsx` 366, `GpuMonitor.tsx` 129, `PhaseStepper.tsx` 113, `TreePage.tsx` 206, `TreeVisualization.tsx` 366, `DetailPanel.tsx` 425, `ResultsPage.tsx` 462, `resultSections.tsx` 1590, `PublishYamlEditor.tsx` 162, `ExperimentsPage.tsx` 189, `StepScope.tsx` 424, `TraceTab.tsx` 57, `i18n/en.ts` 444, `ja.ts` 441, `zh.ts` 441.

Symbol/anchor confirmations (stable symbols preferred, per §17 of the subtask):

| Claim | Verified anchor |
|---|---|
| `PAGE_MAP` has 14 keys; `new`→`wizard` alias | `App.tsx:41-56` (keys), `:37` (`if (raw === 'new') return 'wizard'`) |
| Suspense fallback = bare spinner | `App.tsx:73-78` |
| `STATE_POLL_MS = 5000`; poll drives `loadState` + `refreshCheckpoints` | `AppContext.tsx:34`, `:86-89` |
| WS node feed falls back to `state.nodes` | `AppContext.tsx:96` (`wsNodes.length > 0 ? wsNodes : (state?.nodes ?? [])`) |
| `NAV_ITEMS` = 10 keys; project switcher + `status_label` | `Sidebar.tsx:12-22`, `:155-170` |
| `AppState` P1 fields | `types/index.ts:89-94` (`checkpoint_id/checkpoint_path/running_pid/is_running/status_label/current_phase`); aliases `:118-119` |
| `CostSummary` is an object | `types/index.ts:79-86` |
| `CheckpointSummary` | `types/index.ts:237` |
| DetailPanel default tab `overview`; tab buttons | `DetailPanel.tsx:37,45` (default); `:357,358,359,360,361,363,364` (tab buttons) |
| `{ } Raw` dump | `DetailPanel.tsx:364` (button), `:411-419` (content), `:417` (`JSON.stringify(node,null,2).slice(0,6000)`) |
| `resultSections` 6 render fns | `resultSections.tsx:25,931,1002,1055,1134,1443` |
| `resultSections` 6 `JSON.stringify` dumps | `resultSections.tsx:444,481,523,704,992,1022` |
| `monitorSections` raw dumps | `monitorSections.tsx:241,339` |
| `main.tsx` stack render | `:20` (`error.message`), `:22` (`error.stack`), `:38` (`innerHTML`) |
| `StepScope` HTML injection | `StepScope.tsx:137` (`dangerouslySetInnerHTML={{ __html: summaryHtml }}`) |
| `ExperimentsPage` raw dump | `ExperimentsPage.tsx:58` (`JSON.stringify(d.nodes_tree.nodes)`) |
| `TraceTab` raw dump | `TraceTab.tsx:42` |
| `HomePage` empty state + 3 StatBox | `HomePage.tsx:114-116`, `:45,49,53` |
| `MonitorPage` PhaseStepper / GpuMonitor toggle | `:250` (PhaseStepper), `:253` (GpuMonitor render), `:139` (toggle), `:25` (`gpuVisible`) |
| i18n drift (en 444 vs ja/zh 441) | `wc -l i18n/{en,ja,zh}.ts` |

**Minor discrepancy recorded (live tree wins):** the subtask §7.1 cites `CostSummary` at `types/index.ts:77-84`; the live interface is at `:79-86` (comment lines `:77-78` precede it). This spec uses the live `:79-86`. All other anchors matched the subtask/067/059 figures exactly.

---

## 12. Retirement Condition

This report is a **temporary planning artifact** of subtask 069. It may be archived / `git rm`-ed only after: (1) subtask 069 §13 Acceptance Criteria are met; (2) the implementing PR is merged to `main`; (3) `docs/refactoring/007_subtask_index.md` marks 069 **DONE**. Until then: **KEEP**. Before any `git rm`, re-read this document's own conditions and verify each against primary sources (the repository state, the merged diff, and the index) — never on assumption. Canonical policy: `docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
