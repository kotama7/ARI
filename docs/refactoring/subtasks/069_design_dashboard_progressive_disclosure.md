# Subtask 069: Design Dashboard Progressive Disclosure

> **Phase:** Phase 6 — Dashboard UX
> **Status:** PLANNING ONLY. This subtask produces a **design specification** (a Markdown deliverable). It modifies **no** runtime code, imports, prompts, configs, workflows, frontend source, or directory names. The single artifact this planning document authorizes is one design `.md` file under `docs/refactoring/reports/` (see §9).
> **Planning date:** 2026-07-01 · **ari-core version:** 0.9.0 · **Branch:** main
> **Runtime code change:** No (design deliverable only — implementation happens in downstream subtasks 070/071/072).
> **Classification vocabulary:** KEEP / ADAPT / MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED.
> **"deprecated"** is reserved in this document for external contracts (dashboard API endpoints/schema, CLI `ari`, MCP tool contracts, `ari.public.*`, documented import paths, `ari-skill-*` stable interfaces). It is never applied to internal UI code.

---

## 1. Goal

Produce a **repository-specific progressive-disclosure design specification** for the ARI dashboard (`ari-core/ari/viz/frontend/`, React 18.3 + TypeScript 5.5 + Vite 5 SPA). The specification defines a single **information-priority ladder (P1–P5)** and the **disclosure rules** that decide, for every user-visible dashboard surface, what is shown by default, what is one interaction away, and what is gated behind Developer Mode.

The deliverable is a design document (not code). It:

1. Fixes the canonical **P1–P5 priority ladder** with concrete data sources (`AppState` fields, WebSocket node feed, `CheckpointSummary`) so downstream implementers are not free to reinvent priorities per screen.
2. Maps the ladder onto the **four everyday screens** — `home`, `monitor`, `tree`, `results` — plus the Tree `DetailPanel` tab stack, naming which existing elements are default-visible, collapsed, or Developer-Mode-gated.
3. Enumerates the exact **always-on P5 surfaces today** (raw-JSON dumps, raw-YAML editor, env-key readback, full stack traces) that must move behind a gate, with file/line anchors.
4. States the **hard invariants** every downstream implementation subtask (070 settings panel, 071 developer mode, 072 empty/loading/error states) must not violate: no setting deleted, no dashboard-API contract broken, disclosure is view-layer-only (no change to `AppContext` polling or `services/api.ts` calls).

This subtask does **not** ship the toggle, the gating, or any component change — those are 070/071/072. Its output is the spec they implement against.

## 2. Background

The dashboard is a single-page React app served by the FastAPI backend in `ari-core/ari/viz/` (`routes.py`, 1197 lines, plus 19 `api_*.py` modules). Routing is a **hand-rolled hash router**: `parseHash()` maps `#/<route>` to a lazily-loaded page and `PAGE_MAP` declares **14 keys** (`App.tsx:32-56`), with legacy `new` aliased to `wizard` (`App.tsx:37,47-48`). The sidebar mirror is a **hardcoded** `NAV_ITEMS` array of **10 destinations** (`Sidebar.tsx:12-23`) that omits the three `paperbench/*` sub-routes and the `wizard` alias.

Global state is a single React Context (`context/AppContext.tsx`, 120 lines): it polls `/state` and `/api/checkpoints` every **5000 ms** (`STATE_POLL_MS`, `AppContext.tsx:34,83-93`) and layers a WebSocket node feed on top, preferring `wsNodes` and falling back to `state.nodes` (`AppContext.tsx:96`). There is no Redux/Zustand/react-query; pages hold large local `useState` clusters. There is **no CSS framework** — styling is `src/styles/dashboard.css` plus pervasive inline `style={{}}`.

The UI has accreted organically. Everyday run/result information sits visually equal to developer-only affordances: the Tree `DetailPanel` always exposes a `{ } Raw` tab that dumps `JSON.stringify(node, null, 2).slice(0, 6000)` to any user (`DetailPanel.tsx:364,411-419`); `main.tsx` prints full error stacks to the page (`main.tsx:17-25,38`); several sections `JSON.stringify` raw payloads inline. This subtask is the **design layer** that establishes a priority-driven policy so J1/J2 users (first-time operator, HPC operator) see run state and results first while J3 (developer/debugger) can opt into raw depth.

This subtask is scoped by the parent dashboard-UX plan `docs/refactoring/014_dashboard_ux_refactoring_plan.md` (§7 "Progressive Disclosure Policy", which this subtask expands into an implementable spec) and the master index `docs/refactoring/007_subtask_index.md` (row 069, Phase 6, Low risk, depends on 059). It is a sibling of the two other Phase-6 design/inventory docs: 067 (`inventory_dashboard_visible_settings`) and 068 (`define_dashboard_information_architecture`).

## 3. Scope

In scope (design/spec only):

- Author one design specification Markdown file (§9) that finalizes the **P1–P5 information-priority ladder** with concrete data-source bindings.
- Specify **disclosure rules** (default-visible / one-interaction-away / Developer-Mode-gated) and apply them per screen: `home`, `monitor`, `tree` (incl. `DetailPanel` tabs), `results`.
- Enumerate the **always-on P5 / raw-debug surfaces** to be gated, each with a verified file:line anchor and a target disclosure level.
- Define the **acceptance contract** downstream implementers (070/071/072) must satisfy, plus the invariants they must not break.
- Cross-reference (not re-derive) the settings frequency buckets that subtask 067's inventory / 068's IA design own, so the settings hierarchy stays consistent with the ladder.

Out of scope (belongs to other subtasks; do not do here):

- Implementing the Developer-Mode toggle or any gating logic (subtask **071**).
- Refactoring `SettingsPage.tsx` into tabs/disclosure (subtask **070**).
- Building the empty/loading/error state kit (subtask **072**).
- Route-registry / sidebar-grouping code changes (these are FE state/component-boundary work under Phase-5 subtask **064**; this doc may reference them but must not implement them).
- Any backend, API-client, `types/index.ts`, or `AppContext` change.

## 4. Non-Goals

- **Not** a runtime code change. No `.tsx`/`.ts`/`.py` file is edited by this subtask.
- **Not** deleting, renaming, or hiding-permanently any setting, endpoint, route, or tab. Disclosure reorders and gates; it never removes reachability.
- **Not** changing the dashboard API contract: endpoint paths, HTTP verbs, and request/response field names in `services/api.ts` (863 lines) and the `api_*.py` modules stay stable. This design must be implementable entirely as client-side conditional rendering.
- **Not** changing data-fetching cadence: the 5000 ms `AppContext` poll and the WebSocket feed are untouched; the design must not require new endpoints or new fetch timing.
- **Not** a visual redesign / theming pass, and **not** the accessibility pass (that is the parent plan's §13 / subtask 073 territory) — the spec may note a11y constraints but does not own them.
- **Not** a decision on model-catalog freshness (`settingsConstants.ts` hardcoded lists) — noted as a separate concern, out of scope.

## 5. Current Files / Directories to Inspect

All paths are under `/home/t-kotama/workplace/ARI/`. Line counts verified 2026-07-01.

**Design inputs (read-only context):**

- `docs/refactoring/014_dashboard_ux_refactoring_plan.md` — parent plan; §7 defines the P1–P5 seed this subtask formalizes; §14 lists 067–073 subtask titles.
- `docs/refactoring/007_subtask_index.md` — master index (row 069 at line 116; dependency edges at lines 447/502).
- `docs/refactoring/reports/` — **exists but empty**; deliverable target directory (§9).
- Sibling subtask docs (may not all exist yet): `docs/refactoring/subtasks/067_inventory_dashboard_visible_settings.md`, `068_define_dashboard_information_architecture.md`. As of 2026-07-01 the `subtasks/` directory contains 001–056 plus this file; **067 and 068 do not yet exist** — treat their outputs as inputs to reconcile against, not as present artifacts.

**Frontend surfaces to inspect (the P1–P5 mapping targets):**

- `ari-core/ari/viz/frontend/src/App.tsx` (95 lines) — hash router, `PAGE_MAP` (14 keys), Suspense fallback (`App.tsx:73-78`).
- `ari-core/ari/viz/frontend/src/context/AppContext.tsx` (120 lines) — 5000 ms poll, WebSocket-vs-`state.nodes` fallback (`:96`).
- `ari-core/ari/viz/frontend/src/components/Layout/Sidebar.tsx` (191 lines) — `NAV_ITEMS` (10), project switcher + `status_label` (`:154-172`).
- `ari-core/ari/viz/frontend/src/types/index.ts` — `AppState` (`:87-129`), `CostSummary` (`:77-84`), `CheckpointSummary`.
- `ari-core/ari/viz/frontend/src/components/Home/HomePage.tsx` (122 lines) — 3 `StatBox`, Quick Actions, Latest card, bare empty state (`:114-116`).
- `ari-core/ari/viz/frontend/src/components/Monitor/MonitorPage.tsx` (502 lines) + `PhaseStepper.tsx` (113) + `GpuMonitor.tsx` (129) + `monitorSections.tsx` (366; `JSON.stringify` at `:241,:339`).
- `ari-core/ari/viz/frontend/src/components/Tree/TreePage.tsx` (206) + `TreeVisualization.tsx` (366) + `DetailPanel.tsx` (425; tabs `:354-421`, default `overview` `:37,:44-46`, `{ } Raw` `:364,:411-419`).
- `ari-core/ari/viz/frontend/src/components/Tree/DetailPanelTabs/` — `TraceTab.tsx` (57; `JSON.stringify` `:42`), `CodeTab.tsx` (42), `MemoryTab.tsx` (113), `MemoryEntryCard.tsx` (131), `AccessTab.tsx` (155), `ReportTab.tsx` (126).
- `ari-core/ari/viz/frontend/src/components/Results/ResultsPage.tsx` (462) + `resultSections.tsx` (1590; 6 exported `render*` fns at `:25,:931,:1002,:1055,:1134,:1443`; raw `JSON.stringify` at `:444,:481,:523,:704,:992,:1022`) + `PublishYamlEditor.tsx` (raw-YAML editor).
- `ari-core/ari/viz/frontend/src/components/Experiments/ExperimentsPage.tsx` — raw dump at `:58`.
- `ari-core/ari/viz/frontend/src/components/Wizard/StepScope.tsx` — `dangerouslySetInnerHTML` at `:137`.
- `ari-core/ari/viz/frontend/src/main.tsx` — `ErrorBoundary` full-stack print (`:17-25`), `innerHTML` catch (`:38`).
- `ari-core/ari/viz/frontend/src/components/common/` — `Card.tsx` (17), `StatBox.tsx` (14), `Badge.tsx` (10), `StatusBadge.tsx` — the reusable primitives the spec should assume.
- `ari-core/ari/viz/frontend/src/i18n/{en,ja,zh}.ts` — `en.ts` 444 lines, `ja.ts`/`zh.ts` 441 each (minor key drift; new UX strings must land in all three, gated by `scripts/docs/check_i18n_js.py`).
- `ari-core/ari/viz/frontend/src/styles/dashboard.css` — sole stylesheet (no CSS framework); `.empty-state`, `.spinner`, `var(--muted/red/blue-light)` tokens.

## 6. Current Problems

Grounded, repository-specific problems the design must resolve (each maps to a rule in §7):

1. **No shared priority model.** Each screen decides its own layout ad hoc. `HomePage` computes best-score/total-nodes from `checkpoints` (`HomePage.tsx:20-29`); `MonitorPage` composes `PhaseStepper`/`GpuMonitor`/`computeBestMetrics` (`MonitorPage.tsx:13-16,250-253`); there is no single statement of "run state outranks trace which outranks raw JSON." Downstream implementers would otherwise gate inconsistently.
2. **Always-on P5 raw surfaces.** The `{ } Raw` DetailPanel tab dumps full node JSON to any user (`DetailPanel.tsx:364,411-419`). Additional raw `JSON.stringify` dumps exist in `monitorSections.tsx:241,339`, `resultSections.tsx:444,481,523,704,992,1022`, `ExperimentsPage.tsx:58`, and `DetailPanelTabs/TraceTab.tsx:42`. The raw-YAML editor (`PublishYamlEditor.tsx`) is likewise always available. None are distinguished from everyday result content.
3. **Full stack traces shown to end users.** `main.tsx` `ErrorBoundary` renders `error.message` + `error.stack` (`main.tsx:17-25`) and the outer `catch` writes an `innerHTML` stack (`main.tsx:38`). This is P5 developer content on the default surface.
4. **Unsanitized HTML injection.** `StepScope.tsx:137` uses `dangerouslySetInnerHTML` on a template-string `summaryHtml` — a P5/REVIEW_REQUIRED surface that must be flagged (sanitize/replace is 072/071 work, not this doc's).
5. **No default-visibility contract for Home/Monitor/Tree/Results.** The Suspense fallback is a bare spinner (`App.tsx:73-78`); `HomePage` empty state is a bare `No experiments yet` (`HomePage.tsx:114-116`). Without a priority ladder there is no rule for what a user sees first while data loads.
6. **DetailPanel already well-decomposed but ungated.** Unlike the god-components, `DetailPanel.tsx` (425) is cleanly split into `DetailPanelTabs/*` with a default `overview` tab (`DetailPanel.tsx:37,44-46`). The tabs map naturally onto P2–P5 — but the `{ } Raw` tab is the one always-on P5 element that breaks the ladder. The design should exploit this existing structure rather than propose a rebuild.
7. **Disclosure must not touch data flow.** Any priority scheme has to be pure client-side conditional rendering: `AppContext` polling (5000 ms) and the WebSocket feed are shared and must stay unchanged, so the design cannot express priority via "fetch less" — only via "render/collapse/gate."

## 7. Proposed Design / Policy

The deliverable specifies the following (this section is the normative content the design doc must contain).

### 7.1 Canonical information-priority ladder (P1 highest → P5 lowest)

| Level | Meaning | Concrete data source (verified) | Default treatment |
|---|---|---|---|
| **P1 — Run state** | Is a run active? which checkpoint? phase / PID / running / stopped / status label | `AppState.is_running`, `current_phase`, `checkpoint_id`, `checkpoint_path`, `running_pid`, `status_label` (`types/index.ts:87-94`); sidebar switcher (`Sidebar.tsx:154-172`) | Always visible, top of page |
| **P2 — Tree / node / progress / score** | node count, best score, per-node status/depth/metrics | `nodesData` (WebSocket → `state.nodes`, `AppContext.tsx:96`); `TreeVisualization`, `PhaseStepper`, `monitorSections.computeBestMetrics` | Always visible |
| **P3 — Artifacts / reports** | paper PDF, review scores, figures, reproducibility, EAR | `CheckpointSummary`; `Results/*` (`resultSections.tsx` render fns) | Always visible on `results` |
| **P4 — Trace / prompt / cost / logs** | MCP trace, code snippets, cost breakdown, streamed logs | `DetailPanelTabs/{TraceTab,CodeTab}`, `AppState.cost` (`CostSummary`, `types/index.ts:77-84`), Monitor log stream | One interaction away (tab/expander, not pre-expanded) |
| **P5 — Advanced / debug** | raw JSON node dump, raw-YAML editor, env-key readback, workflow internals, full stack traces, advanced infra settings | `DetailPanel` `{ } Raw` (`:411-419`), `PublishYamlEditor`, `/api/env-keys`, `WorkflowPage`, `main.tsx:17-25,38` | Developer-Mode-gated (hidden by default) |

### 7.2 Disclosure rules (normative)

1. **Default view = P1–P3.** With Developer Mode off, any user sees run state, tree/score, and artifacts without extra clicks.
2. **P4 is exactly one interaction away.** Trace/cost/logs render behind an always-present tab or expander that is **not** the default state. The DetailPanel already satisfies this: default tab is `overview` (`DetailPanel.tsx:37,44-46`); `trace`/`code` tabs are present but not default. Keep this pattern; do not pre-expand P4.
3. **P5 is Developer-Mode-gated.** Raw JSON, raw YAML, env-key readback, workflow-internal editing, and full stack traces render **only** when Developer Mode (subtask 071) is on. When off, they are **hidden via conditional rendering** (not CSS-hidden, not disabled-with-tooltip) so raw payloads are not shipped in the DOM by default.
4. **Settings follow the frequency buckets** owned by 067/068 (Primary always visible; Secondary one section away; Advanced behind a disclosure; Developer/Dangerous grouped and visually distinct). This doc references those buckets; it does not redefine them.
5. **Disclosure is view-only.** No rule changes which endpoints are called or when. `AppContext` polling and the WebSocket feed are untouched; priority is expressed purely as conditional rendering / ordering.

### 7.3 Per-screen application (the spec's core table)

The design doc must contain, for each of the four everyday screens, an element-by-element assignment. Grounded starting point:

- **`home` (`HomePage.tsx`, 122):** stat boxes + Latest card + status badge = **P1/P2/P3** (KEEP, always visible). Empty state (`:114-116`) needs a first-class treatment (defer implementation to 072). No P5 here today — keep it that way.
- **`monitor` (`MonitorPage.tsx`, 502):** `PhaseStepper` (`:250`) = **P1/P2**; cost + model badge = **P4** but currently inline — spec must decide default-visible vs collapsed; `GpuMonitor` (`:253`, toggled `:139`) = **P4**; the `JSON.stringify` dumps in `monitorSections.tsx:241,339` = **P5** (gate). Embedded `TreeVisualization` = **P2**.
- **`tree` (`TreePage.tsx` + `DetailPanel.tsx`):** tree canvas + filters = **P2**; DetailPanel tab stack maps as in §7.4; the `{ } Raw` tab = **P5** (the single always-on P5 element to gate).
- **`results` (`ResultsPage.tsx`, 462 + `resultSections.tsx`, 1590):** paper/scores/figures/repro/EAR = **P3** (KEEP visible); the inline `JSON.stringify` dumps (`:444,:481,:523,:704,:992,:1022`) and `PublishYamlEditor` raw YAML = **P5** (gate).

### 7.4 DetailPanel tab classification (exploits existing structure)

| Tab | Anchor | Priority | Disclosure |
|---|---|---|---|
| Overview (default) | `DetailPanel.tsx:357,368` | P2/P3 | Always on (default tab) |
| MCP Trace | `:358` → `TraceTab.tsx` | P4 | On, not default |
| Code | `:359` → `CodeTab.tsx` | P4 | On, not default |
| Memory | `:360` → `MemoryTab.tsx` | P3/P4 | On, not default |
| Access | `:361` → `AccessTab.tsx` | P4 | On, not default |
| Report | `:363` → `ReportTab.tsx` | P3 | On (already hidden when `node_report.json` absent, `:362`) |
| **`{ } Raw`** | `:364,:411-419` | **P5** | **Developer-Mode-gated** |

### 7.5 Always-on P5 inventory to gate (hand-off list for 071)

The spec must enumerate exactly these, each with anchor and target = Developer-Mode-gated:

- `DetailPanel.tsx:411-419` — `{ } Raw` full-node JSON dump.
- `monitorSections.tsx:241,339` — raw `validated_parameter_sweep` / `ctx` dumps.
- `resultSections.tsx:444,481,523,704,992,1022` — inline `JSON.stringify` payloads.
- `ExperimentsPage.tsx:58` — raw `nodes_tree.nodes` dump.
- `TraceTab.tsx:42` — raw trace `JSON.stringify` (P4 tab content; keep, but its raw fallback is P5-flavored — flag only).
- `PublishYamlEditor.tsx` — raw-YAML editor (P5; keep reachable, gate default visibility).
- `main.tsx:17-25,38` — full stack-trace rendering (P5; behind Developer Mode, non-developers get a friendly message + retry).
- `StepScope.tsx:137` — `dangerouslySetInnerHTML` (REVIEW_REQUIRED; sanitize is 071/072 work — this doc only flags it).

### 7.6 Classification summary

- **KEEP:** the P1–P3 surfaces on `home`/`monitor`/`tree`/`results`; the DetailPanel default `overview` tab; the existing `Card`/`StatBox`/`Badge`/`StatusBadge` primitives.
- **ADAPT (later, 071):** each always-on P5 element in §7.5 → conditional render behind Developer Mode.
- **REVIEW_REQUIRED:** `StepScope.tsx:137` HTML injection; `main.tsx` stack rendering (security-flavored, needs a backend/security look before change).
- **MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE:** none proposed by this design — progressive disclosure adds gating, it does not delete or relocate code.

## 8. Concrete Work Items

1. Create the deliverable design doc at the §9 path. Header block: scope (design-only), classification vocabulary, "deprecated" reservation, no-runtime-change note, planning date, ari-core version.
2. Write the **canonical P1–P5 ladder** (§7.1 table) with the verified data-source bindings; include the `AppState`/`CostSummary` field anchors so implementers do not guess.
3. Write the **disclosure rules** (§7.2) as normative, numbered rules (default = P1–P3; P4 one interaction away; P5 gated; settings follow 067/068 buckets; view-only).
4. Write the **per-screen application** section (§7.3) with an element-by-element table for `home`, `monitor`, `tree`, `results`, each element tagged P1–P5 and given a disclosure verb (visible / collapsed / gated) + file:line anchor.
5. Write the **DetailPanel tab classification** (§7.4) exploiting the existing `overview`-default + `DetailPanelTabs/*` structure.
6. Write the **always-on P5 gating inventory** (§7.5) as a clean hand-off checklist for subtask 071, each row = anchor + target disclosure + note.
7. Write the **invariants / acceptance contract** the design imposes on 070/071/072: no setting deleted; no dashboard-API break; disclosure is conditional rendering only; `AppContext`/WebSocket untouched; new UX strings land in all three i18n locales.
8. Add a **cross-reference matrix** to sibling subtasks (067 settings inventory, 068 IA design, 070 settings panel, 071 developer mode, 072 empty/loading/error, 073 UX regression checks) so the ladder stays consistent with their outputs.
9. Add an **open-questions / REVIEW_REQUIRED** list: (a) whether `monitor` cost/model badge is P4-collapsed or P4-visible-by-default; (b) `StepScope.tsx:137` sanitize approach; (c) Developer-Mode discoverability placement (footer vs Settings→Diagnostics) — defer decisions to 071 but record them.
10. Verify every file:line anchor cited in the doc against the live tree before finalizing (the anchors in §5/§7 were verified 2026-07-01; re-verify if the branch has moved).

## 9. Files Expected to Change

This subtask is **design-only**. Exactly one file is created; no runtime file is touched.

| Path | Action | Notes |
|---|---|---|
| `docs/refactoring/reports/069_progressive_disclosure_design.md` | **CREATE** | The design specification. Target dir `docs/refactoring/reports/` exists and is currently empty (verified 2026-07-01). If the reports/ naming convention established by 067/068 differs, match it; otherwise use this name. |

Explicitly **NOT** changed by this subtask (they are downstream 070/071/072 territory):

- `ari-core/ari/viz/frontend/src/components/Tree/DetailPanel.tsx`, `Settings/SettingsPage.tsx`, `Monitor/*`, `Results/*`, `main.tsx`, `Wizard/StepScope.tsx`.
- `ari-core/ari/viz/frontend/src/context/AppContext.tsx`, `services/api.ts`, `types/index.ts`.
- `ari-core/ari/viz/frontend/src/i18n/{en,ja,zh}.ts`, `styles/dashboard.css`.
- Any `ari-core/ari/viz/*.py` backend module.

Optionally, if a progress tracker exists (subtask 035 deliverable), append a one-line status entry — but only if that tracker file already exists; do not create it here.

## 10. Files / APIs That Must Not Be Broken

This subtask writes no code, so it breaks nothing directly. The design it specifies must, however, preserve (and it must state these as constraints for 070/071/072):

- **Dashboard API contract:** every endpoint in `services/api.ts` (863 lines) and the `api_*.py` modules — paths, verbs, and request/response field names — including `/state`, `/api/checkpoints`, `/api/checkpoint/{id}/*`, `/api/settings` (flat 24-key object), `/api/env-keys`, `/api/memory/restart`, `/api/paperbench/*`. Disclosure is UI-only; no endpoint may be added or changed to satisfy it.
- **Both API error regimes:** `get/post` throw on non-2xx (`api.ts:18-32`); `pbGet/pbPost` never throw and return `{error}` bodies (`api.ts:787-799`). The design must not require unifying these at the transport layer (a presentational wrapper is 072's concern).
- **Hash-router contract:** `PAGE_MAP` keys and `#/` URLs (`App.tsx:41-56`), including the legacy `new`→`wizard` alias. The ladder must not require renaming or removing a route.
- **`AppState`/`CostSummary`/`CheckpointSummary` shapes** (`types/index.ts:77-129`) — the ladder binds to existing fields; it must not require new fields.
- **`AppContext` fetch cadence** (5000 ms poll + WebSocket, `AppContext.tsx:34,83-96`) — unchanged.
- **Out-of-frontend contracts unaffected:** CLI `ari` (`ari.cli:app`), `ari.public.*`, the 14 `ari-skill-*` MCP tool contracts, checkpoint/output/config file formats, and `ari-skill-* → ari-core` interfaces are entirely outside this subtask's blast radius.

## 11. Compatibility Constraints

- **No setting or affordance deleted.** Progressive disclosure only reorders, collapses, or gates. Every field, tab, editor, and dangerous action stays reachable (P5 items via Developer Mode).
- **No default raw/debug exposure.** After the design is implemented, P5 surfaces (raw JSON, raw YAML, env-key readback, full stack traces) must be hidden by default via conditional rendering, not present-but-styled-away.
- **View-layer-only.** The design must be implementable without touching backend routes, the API client's endpoint set, or the two documented error regimes. Any element that would require a backend change is marked REVIEW_REQUIRED (e.g. `StepScope.tsx:137` sanitize; `GpuMonitor` `confirmed:true` hardcode noted in the parent plan §11).
- **i18n parity.** Any new UX string introduced by downstream implementers (Developer-Mode label, disclosure captions, gated-empty copy) must be added to `en.ts`/`ja.ts`/`zh.ts` together to keep the `scripts/docs/check_i18n_js.py` gate green (current drift: 444 vs 441/441).
- **No new dependency.** The design must not assume any library beyond the current stack (`react`, `react-dom`, `d3`, `reactflow`); no CSS framework, no state library.
- **The word "deprecated"** is not applied to any internal UI element in the deliverable; P5 elements are "gated," not "deprecated."

## 12. Tests to Run

This subtask produces a Markdown design document, so there is no code to compile or test. Run the repo-wide sanity checks to confirm the doc addition does not disturb anything:

- `python -m compileall .` — confirms no `.py` was inadvertently changed (expected: unaffected; the deliverable is `.md`).
- `pytest -q` — full suite should be unchanged by a docs-only addition (run to confirm no accidental edits).
- `ruff check .` — Python lint; must remain clean (no Python touched).
- Frontend (should be **unchanged**, run only to prove no FE file was edited):
  - `npm test` (Vitest) in `ari-core/ari/viz/frontend/` — expected: identical result to pre-change.
  - `npm run build` / `npm run typecheck` in `ari-core/ari/viz/frontend/` — expected: identical.
- Docs gates (this is a docs change): `python scripts/docs/check_doc_links.py` and `python scripts/docs/check_doc_sources.py` if the deliverable cites source paths, to keep the docs-source-sync gate green. `scripts/docs/check_i18n_js.py` is unaffected (no i18n edit) but noted because downstream 070/071/072 will trip it.

Note: `scripts/check_dashboard_ux.py` is listed as MISSING/to-be-designed and **must not** be implemented or invoked here.

## 13. Acceptance Criteria

- [ ] Exactly one new file exists at `docs/refactoring/reports/069_progressive_disclosure_design.md` (or the reports/ convention name matching 067/068); no runtime file is modified (`git status` shows only the `.md`).
- [ ] The doc defines the **P1–P5 ladder** with a data-source binding for each level, each citing a real `types/index.ts` / component anchor.
- [ ] The doc states the **five disclosure rules** (§7.2) as numbered normative rules.
- [ ] The doc contains **per-screen element tables** for `home`, `monitor`, `tree`, `results`, every element tagged P1–P5 with a disclosure verb and file:line anchor.
- [ ] The doc contains the **DetailPanel tab classification** (§7.4) and the **always-on P5 gating inventory** (§7.5) as a clean hand-off list for subtask 071.
- [ ] The doc states the **invariants** (no setting deleted; no API break; view-only; `AppContext` untouched; i18n parity) that 070/071/072 must satisfy.
- [ ] Every file:line anchor in the doc resolves in the current tree (spot-check ≥ 10 anchors).
- [ ] The doc uses the KEEP/ADAPT/MERGE/MOVE_TO_LEGACY/DELETE_CANDIDATE/REVIEW_REQUIRED vocabulary and reserves "deprecated" for external contracts only.
- [ ] `python -m compileall .`, `pytest -q`, `ruff check .` are unaffected (docs-only change).

## 14. Rollback Plan

Trivial: this subtask adds a single Markdown file and no code. To roll back, delete `docs/refactoring/reports/069_progressive_disclosure_design.md` (and revert the optional progress-tracker line if one was added). No runtime, config, workflow, or contract state is touched, so there is nothing else to unwind and no migration to reverse. Because downstream subtasks 070/071/072 consume this spec, rolling it back before they run simply blocks them (they lose their design input); rolling it back after they run has no runtime effect but should be paired with re-checking that 070/071/072 still have a spec to reference.

## 15. Dependencies

Per the dependency graph (`059 -> 067, 068, 069, 070, 071, 072, 073`) and the master index (`docs/refactoring/007_subtask_index.md:116,447,502`):

- **Hard upstream (blocking):** **059** (`inventory_dashboard_frontend_backend_structure`) — the sole formal predecessor edge. 059 establishes the FE/BE structure inventory (stack, routes, state model) this design binds to. 069 must not start until 059's inventory exists.
- **Companion inputs (same 059 parent; strongly recommended to reconcile against, though not formal blocking edges in the graph):** **067** (`inventory_dashboard_visible_settings`, gates 070) and **068** (`define_dashboard_information_architecture`). The settings frequency buckets and IA groupings this design references are owned by 067/068; author 069 consistently with them. As of 2026-07-01 their subtask docs do not yet exist — if they are unavailable, cite the parent plan `014` §§3–9 as the interim source and note the reconciliation as a follow-up.
- **Downstream consumers (this design gates them conceptually):** **070** (`refactor_dashboard_settings_panel`), **071** (`add_dashboard_developer_mode`), **072** (`improve_dashboard_empty_loading_error_states`), and **073** (`add_dashboard_ux_regression_checks`). These are the runtime-code subtasks; each is additionally gated by the inventory subtasks (059/060/067) per the master index.
- **No dependency** on Phase-5 refactors (062/063/064) beyond sharing the same `viz/frontend` surface; this design is view-layer policy and does not require them to land first.

## 16. Risk Level

**Low.** **This subtask does NOT change runtime code** — its deliverable is a design/specification Markdown document (index row 069: Runtime Code Change = **No**). Risk is confined to design quality: an incorrect priority assignment or a missed always-on P5 surface would propagate into 071's gating work. Mitigations: every anchor is verified against the live tree (§8 item 10), and the acceptance criteria require spot-checking ≥ 10 anchors. There is no execution, migration, or contract surface touched, so blast radius on the running system is zero. The primary downstream risk (breaking the `/api/settings` 24-key contract, exposing raw debug by default, or altering fetch cadence) is explicitly ruled out by the invariants in §7.2/§10/§11 that this doc hands to 070/071/072.

## 17. Notes for Implementer

- You are writing a **document, not code**. Do not edit any `.tsx`/`.ts`/`.py` file. If you find yourself wanting to change `DetailPanel.tsx` or `SettingsPage.tsx`, stop — that is subtask 070/071.
- Reuse the parent plan's §7 (`docs/refactoring/014_dashboard_ux_refactoring_plan.md`) as the seed, but this deliverable must be **more concrete**: per-screen element tables with file:line anchors, not just the abstract ladder.
- Re-verify anchors before finalizing. The frontend is under active refactoring (Phase 5 subtasks 062–064 touch the same files); a moved line invalidates a citation. Prefer citing stable symbols (`PAGE_MAP`, `NAV_ITEMS`, `STATE_POLL_MS`, `activeTab === 'raw'`, exported `render*` names) alongside line numbers.
- The DetailPanel is the **model case** for good disclosure (default `overview`, tabbed P4, single stray P5 `{ } Raw`). Use it as the worked example the other screens should emulate; do not propose rebuilding it.
- Keep the P5 gating inventory (§7.5) as a literal checklist — subtask 071 will consume it verbatim to decide what the Developer-Mode toggle hides. Missing an entry there means a raw dump ships to end users.
- Do **not** decide the Developer-Mode mechanism (localStorage key, placement) — that is 071. Record it as an open question so 071 owns it.
- Do **not** implement `scripts/check_dashboard_ux.py`; it is a separate to-be-designed tooling subtask. You may describe what such a linter would assert (always-on raw dumps, missing i18n keys), but only as future work.
- Write the deliverable in English (ARI canonical). If new UX terms need translating, note that 070/071/072 must add them to all three `i18n/*.ts` files — do not add strings yourself.
- Sanity-check with `git status` at the end: only `docs/refactoring/reports/069_progressive_disclosure_design.md` (plus an optional tracker line) should appear.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **069** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
