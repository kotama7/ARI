# Subtask 071: Add Dashboard Developer Mode

> Phase 6: Dashboard UX
> Classification: **ADAPT** (additive client-side gate over existing raw/debug surfaces; no surface deleted)
> Inventory gates: **059** (`inventory_dashboard_frontend_backend_structure`), **067** (`inventory_dashboard_visible_settings`)
> Coordinates with: **068** (information architecture), **069** (progressive disclosure design), **070** (refactor_dashboard_settings_panel), **072** (empty/loading/error states)

This document is a PLANNING artifact. It changes no runtime code. It is
self-contained: a fresh coding session should be able to execute it after
reading Sections 5, 7, 8, 9, and 10.

---

## 1. Goal

Introduce a single, explicit **Developer Mode** gate in the ARI dashboard
frontend (`ari-core/ari/viz/frontend/`) so that the raw / debug / secret-leaking
/ dangerous UI affordances that are **always visible today** are hidden by
default and only revealed when a user opts into developer mode.

Concretely:

1. Add a client-side developer-mode flag stored in `localStorage`, mirroring the
   existing `ari_lang` language-persistence pattern (`src/i18n/index.ts:9-10`),
   with a matching `useDevMode()` hook (and/or an `AppContext` field) so any
   component can read the flag reactively.
2. Add one user-facing toggle for the flag in the Settings page (adjacent to the
   existing Language section), plus i18n keys in all three dictionaries
   (`en.ts` / `ja.ts` / `zh.ts`) kept at strict key parity.
3. Wrap the currently-unconditional raw/debug surfaces so they render only when
   developer mode is ON. The exhaustive list of surfaces to gate is in Section 6
   (each with a verified file:line citation). Non-developer users see a clean,
   product-safe dashboard; developers keep every diagnostic they have today.

This is **additive** and **client-only**: no dashboard REST/WS endpoint, no
`/api/settings` payload, no backend Python, and no `Settings` TypeScript type is
changed. The developer-mode flag is intentionally NOT persisted server-side
(see Section 4 and Section 11 for why).

## 2. Background

The dashboard frontend is Vite 5 + React 18.3 + TypeScript 5.5 (ESM), styled by
one `src/styles/dashboard.css` plus pervasive inline `style={{}}` objects. It
uses a hand-rolled hash router (`src/App.tsx:32-56`), a single React Context for
global state (`src/context/AppContext.tsx`, 120 lines, 5s polling of `/state` +
`/checkpoints`), and a same-origin fetch client (`src/services/api.ts`, 863
lines, `API_BASE=''`). There is **no auth/token/CSRF header anywhere** and no
Redux/Zustand/react-query.

The routed frontend findings (2026-07-01) enumerate a set of **raw-debug and
dangerous UI surfaces that are exposed to every user unconditionally**:

- **DetailPanel "{ } Raw" tab** dumps full node JSON to the user
  (`src/components/Tree/DetailPanel.tsx:364,411-419`; `TabName` union includes
  `'raw'` at `:23`).
- **`/api/env-keys`** returns actual environment secret values to the browser;
  `StepResources.autoReadApiKey` reads `OPENAI_API_KEY`/`ANTHROPIC_API_KEY`/etc.
  (`src/services/api.ts:382-383`, `src/components/Wizard/StepResources.tsx:333-342`,
  button at `:674`).
- **GPU Monitor "SLURM Auto-Resubmit"** continuously submits SLURM jobs; the only
  guard is `window.confirm` and `gpuMonitorAction` always sends
  `confirmed: true` (`src/components/Monitor/GpuMonitor.tsx` `handleStart` ~`:44-55`,
  `src/services/api.ts:584-585`).
- **`dangerouslySetInnerHTML`** in `src/components/Wizard/StepScope.tsx:121,137`
  (template-string `summaryHtml`); raw `innerHTML` error-stack write in
  `src/main.tsx:38-40`; the `ErrorBoundary` prints the full `error.stack` to the
  page (`src/main.tsx:17-25`).
- **Raw `JSON.stringify` dumps** in `src/components/Monitor/monitorSections.tsx`,
  `src/components/Tree/DetailPanelTabs/TraceTab.tsx`,
  `src/components/Experiments/ExperimentsPage.tsx`,
  `src/components/Results/resultSections.tsx`,
  `src/components/Results/resultHelpers.ts`, and `DetailPanel.tsx`.
- **Raw-YAML editor** (`src/components/Results/PublishYamlEditor.tsx`, i18n key
  `py_editor_raw`).

There is **no existing developer/debug toggle** today: a repo-wide grep for
`developer` / `devmode` / `dev.mode` in `frontend/src/**/*.ts{,x}` returns only
unrelated `debug`-colored node labels
(`src/components/Idea/IdeaPage.tsx`, `src/components/Tree/TreeVisualization.tsx`,
`DetailPanel.tsx:17`). So this subtask is a greenfield feature, not a
refactor of an existing gate.

Precedent for a client-only persisted toggle already exists: language selection
is stored in `localStorage['ari_lang']` and read reactively by `useI18n()`
(`src/i18n/index.ts:8-27`). Developer mode should copy that shape exactly.

## 3. Scope

In scope (runtime frontend TypeScript, executed AFTER the 059/067 inventory
gates):

- **New**: a developer-mode hook/store, e.g. `src/hooks/useDevMode.ts` (the
  `src/hooks/` dir today holds `useApi.ts`, `useWebSocket.ts`, and a
  `README.md`), reading/writing `localStorage['ari_dev_mode']` and exposing a
  boolean + setter. Optionally surface the same flag on `AppContext`
  (`src/context/AppContext.tsx`) so class components / non-hook sites can read
  it; decide in Section 7.
- **New**: a Developer Mode toggle control in `src/components/Settings/SettingsPage.tsx`
  (1049 LOC, 9 `<Card>` sections). Place it in or beside the existing **Language**
  card (`SettingsPage.tsx:383` region; the `settings_lang_section` label is at
  `en.ts:190`). No new `<Card>` is required — one labeled checkbox/switch row.
- i18n additions to `src/i18n/en.ts` (444 lines), `src/i18n/ja.ts` (441),
  `src/i18n/zh.ts` (441): new keys for the toggle label, help text, and any
  "developer-only" badges. Keys MUST be added to all three dictionaries.
- **Conditional-render edits** (guard existing JSX with the dev-mode flag) in the
  surfaces listed in Section 6 / Section 9. These are `KEEP` + wrap, not delete.
- The special case `src/main.tsx` (the top-level `ErrorBoundary`) runs **outside**
  the React context/hook tree, so it must read the flag directly from
  `localStorage['ari_dev_mode']` (a tiny helper is fine); it cannot use the hook.
- Frontend tests under Vitest (`package.json:11` `"test": "vitest run"`;
  `vitest.config.ts` present). Add a focused test file (the only existing
  `__tests__` dir is `src/components/PaperBench/__tests__/`).
- Per-directory `README.md` updates where a new file is added
  (`src/hooks/README.md`, and `frontend/src/README.md` if it enumerates hooks).

## 4. Non-Goals

- **NOT** adding authentication/authorization/CSRF. Developer mode is a
  discoverability/UX gate, not a security boundary — a determined user can flip
  `localStorage` or call the endpoints directly. The genuine security concerns
  (unauthenticated `/api/env-keys` secret exposure, unauthenticated SLURM
  submit, unauthenticated file write / checkpoint delete) are **REVIEW_REQUIRED**
  for a dedicated security subtask; flag them, do not fix them here (Section 17).
- **NOT** persisting the dev-mode flag server-side. Do NOT add a field to the
  `/api/settings` flat save object (currently 24 keys, `SettingsPage.tsx:235-260`)
  or to the `Settings` TypeScript type (`src/types/index.ts:38-75`). Doing so
  would touch the frozen dashboard-settings contract that subtask **070** must
  preserve. Keep it purely in `localStorage`, exactly like `ari_lang`.
- **NOT** deleting or rewriting any raw/debug surface. The Raw tab, JSON dumps,
  YAML editor, env auto-read, and SLURM auto-resubmit all **remain** — they are
  only conditionally rendered. Removing them is out of scope (and would break
  developer workflows and existing tests).
- **NOT** changing any dashboard REST endpoint, HTTP method, request/response
  JSON shape, status code, header, or WebSocket message
  (`{"type":"update","data":...,"timestamp":...}`). Backend `ari-core/ari/viz/*.py`
  is untouched.
- **NOT** refactoring the god-components themselves (`SettingsPage.tsx` 1049,
  `StepResources.tsx` 1160, `resultSections.tsx` 1590). Component decomposition is
  subtask **064** (FE state/component boundaries); here we only add small
  conditional guards and one toggle.
- **NOT** rewriting `StepScope.tsx`'s `dangerouslySetInnerHTML` into safe JSX.
  That is a security/hygiene cleanup (candidate for 072 or a security subtask);
  developer mode may gate it but should not re-author the summary rendering here.
- **NOT** touching `docs/`, `.github/workflows/`, `report/`, or any backend
  Python, config, prompt, or CLI surface.

## 5. Current Files / Directories to Inspect

All paths absolute-from-repo-root (`/home/t-kotama/workplace/ARI`). Line counts
verified 2026-07-01.

Frontend root: `ari-core/ari/viz/frontend/`.

| File | LOC | Why it matters to 071 |
| --- | --- | --- |
| `ari-core/ari/viz/frontend/src/i18n/index.ts` | 40 | `useI18n()` + `localStorage['ari_lang']` pattern to copy for `ari_dev_mode` (`:8-27`). |
| `ari-core/ari/viz/frontend/src/i18n/en.ts` | 444 | English dict; add dev-mode keys. `settings_lang_section` at `:190`. |
| `ari-core/ari/viz/frontend/src/i18n/ja.ts` | 441 | Japanese mirror; must reach key parity. |
| `ari-core/ari/viz/frontend/src/i18n/zh.ts` | 441 | Chinese mirror; must reach key parity. |
| `ari-core/ari/viz/frontend/src/hooks/useApi.ts` / `useWebSocket.ts` | — | existing hook shape/style to match for new `useDevMode.ts`. |
| `ari-core/ari/viz/frontend/src/context/AppContext.tsx` | 120 | optional place to expose the flag app-wide (`AppContextType` at `:11-28`). |
| `ari-core/ari/viz/frontend/src/components/Settings/SettingsPage.tsx` | 1049 | host for the toggle; Language section region ~`:383`; flat save `:235-260`. |
| `ari-core/ari/viz/frontend/src/components/Tree/DetailPanel.tsx` | 425 | Raw tab: `TabName` `:23`, `tabBtn('raw', …)` `:364`, JSON pre `:411-419`. |
| `ari-core/ari/viz/frontend/src/components/Monitor/GpuMonitor.tsx` | 129 | SLURM auto-resubmit Start `handleStart` ~`:44-55`. |
| `ari-core/ari/viz/frontend/src/components/Wizard/StepResources.tsx` | 1160 | env-key auto-read `autoReadApiKey` `:333-342`, button `:674`. |
| `ari-core/ari/viz/frontend/src/components/Wizard/StepScope.tsx` | 424 | `dangerouslySetInnerHTML` `:121,137`. |
| `ari-core/ari/viz/frontend/src/components/Results/PublishYamlEditor.tsx` | — | raw-YAML editor (`py_editor_raw`). |
| `ari-core/ari/viz/frontend/src/components/Monitor/monitorSections.tsx` | — | raw `JSON.stringify` dump. |
| `ari-core/ari/viz/frontend/src/components/Tree/DetailPanelTabs/TraceTab.tsx` | 57 | raw `JSON.stringify` dump. |
| `ari-core/ari/viz/frontend/src/components/Experiments/ExperimentsPage.tsx` | — | raw `JSON.stringify` dump + `sessionStorage` usage. |
| `ari-core/ari/viz/frontend/src/components/Results/resultSections.tsx` | 1590 | raw `JSON.stringify` dump(s). |
| `ari-core/ari/viz/frontend/src/main.tsx` | 40 | `ErrorBoundary` full-stack print `:17-25`, raw `innerHTML` `:38-40` (outside React context). |
| `ari-core/ari/viz/frontend/src/services/api.ts` | 863 | `/api/env-keys` `:382-383`; `gpuMonitorAction` sends `confirmed:true` `:584-585` (read-only reference; NOT changed). |
| `ari-core/ari/viz/frontend/package.json` | — | scripts `dev/build/typecheck/preview/test`; Vitest 2. |
| `ari-core/ari/viz/frontend/vitest.config.ts` / `vite.config.ts` | — | test + build config. |
| `ari-core/ari/viz/frontend/src/hooks/README.md`, `src/README.md` | — | per-directory readmes to update when a hook file is added. |

Upstream planning references:
`docs/refactoring/subtasks/067_inventory_dashboard_visible_settings.md` (visible-settings
inventory — the settings gate), `docs/refactoring/014_dashboard_ux_refactoring_plan.md`
(Phase 6 area plan), `docs/refactoring/007_subtask_index.md:114-121,275-289` (Phase 6
narrative: "071 add_dashboard_developer_mode — additive gate for raw/debug UI"),
`docs/refactoring/010_contract_preservation_policy.md`.

## 6. Current Problems

Grounded in the routed frontend findings and re-verified citations:

1. **Full node JSON is dumped to every user.** `DetailPanel`'s "{ } Raw" tab is
   always present and prints `JSON.stringify(node, null, 2).slice(0, 6000)`
   (`DetailPanel.tsx:411-419`), regardless of audience. Non-technical users see a
   6 KB JSON blob.
2. **Secrets are readable in the browser on demand.** The "auto-read API key"
   affordance calls `GET /api/env-keys` (`api.ts:382-383`) and pulls real
   `OPENAI_API_KEY`/`ANTHROPIC_API_KEY`/etc. into the field
   (`StepResources.tsx:333-342`, button `:674`). It is one click away for anyone
   with the dashboard open.
3. **A destructive HPC action is a single confirm away.** GPU Monitor's SLURM
   auto-resubmit Start (`GpuMonitor.tsx` `handleStart`) submits SLURM jobs; the
   only guard is `window.confirm`, and `gpuMonitorAction` hard-codes
   `confirmed: true` (`api.ts:584-585`). There is no "expert users only" gate.
4. **Full stack traces and raw HTML injection are shown to end users.** The
   top-level `ErrorBoundary` renders `error.message` + `error.stack` verbatim
   (`main.tsx:17-25`), and a fallback writes raw `innerHTML` with the stack
   (`main.tsx:38-40`). `StepScope.tsx:137` injects a template string via
   `dangerouslySetInnerHTML`.
5. **Multiple raw `JSON.stringify` debug dumps leak internal shapes** across
   `monitorSections.tsx`, `TraceTab.tsx`, `ExperimentsPage.tsx`,
   `resultSections.tsx`, `resultHelpers.ts`, and `DetailPanel.tsx` — useful for
   developers, noise (or information disclosure) for everyone else.
6. **A raw-YAML editor is always exposed** (`PublishYamlEditor.tsx`, `py_editor_raw`)
   even though most users publish through the guided UI.
7. **No single switch governs any of the above.** Each surface is independently,
   unconditionally rendered; there is no "developer mode" concept, so there is no
   consistent way to present a clean product view vs. a diagnostic view.

Classification of the affected surfaces: all are **KEEP** (retain functionality)
+ **ADAPT** (render behind the new flag). None are **DELETE_CANDIDATE** in this
subtask. The `StepScope.tsx` `dangerouslySetInnerHTML` is separately
**REVIEW_REQUIRED** for a security/hygiene cleanup outside 071.

## 7. Proposed Design / Policy

**Policy: one client-side developer-mode flag, default OFF, gating every
raw/debug/dangerous surface; zero backend/contract change.**

### 7.1 Flag storage + hook

- Store the flag as `localStorage['ari_dev_mode']` (values `'1'`/`'0'` or
  `'true'`/`'false'` — pick one and document it). Default (key absent) = **OFF**
  → product-safe view.
- Add `ari-core/ari/viz/frontend/src/hooks/useDevMode.ts` returning
  `{ devMode: boolean, setDevMode: (on: boolean) => void }`, structured exactly
  like `useI18n()` (`i18n/index.ts:8-27`): lazy `useState` initializer reading
  `localStorage`, setter writes back + updates state.
- To keep every reader in sync when the flag flips (React `useState` in one hook
  instance does not notify others), either (a) dispatch a `window` custom event /
  `storage` event and have `useDevMode` subscribe, or (b) expose the flag on
  `AppContext` (single source of truth) and have `useDevMode` read from context.
  Prefer **(b)** if the toggle needs to affect components across the tree
  immediately; document the chosen mechanism. (The existing `useI18n` does NOT
  cross-sync instances — a known limitation — so do better here.)

### 7.2 Toggle UI

- Add one labeled switch/checkbox row in `SettingsPage.tsx`, in or next to the
  Language card (`~:383`). Reuse existing `Card`/`common` primitives. Do **not**
  add the value to the flat `/api/settings` save (`:235-260`) — the toggle writes
  `localStorage` directly via `setDevMode`, identical to how language is handled
  independently of the settings POST.
- i18n keys (add to `en.ts`, `ja.ts`, `zh.ts` at parity): e.g.
  `settings_devmode_section`, `settings_devmode_label`, `settings_devmode_help`,
  and a reusable `dev_only_badge`. Follow the existing naming convention
  (`settings_*`, `nav_*`, `lang_*`).

### 7.3 Gating the surfaces

For each Section 6 surface, wrap the existing JSX in `devMode && ( … )` (or an
early-return / conditional tab list). Specific guidance:

- **DetailPanel Raw tab** (`DetailPanel.tsx:23,364,411-419`): only push the
  `'raw'` tab button when `devMode`; guard the `activeTab === 'raw'` render block
  too. If `activeTab` was `'raw'` when the flag flips off, fall back to
  `'overview'`.
- **env-key auto-read** (`StepResources.tsx:333-342,674`): render the auto-read
  button only in dev mode. Manual key entry stays available to all users.
- **SLURM auto-resubmit Start** (`GpuMonitor.tsx` `handleStart`): gate the Start
  control behind dev mode (Stop/status stay visible). Keep the `window.confirm`.
- **Raw JSON dumps** (`monitorSections.tsx`, `TraceTab.tsx`, `ExperimentsPage.tsx`,
  `resultSections.tsx`, `resultHelpers.ts`, `DetailPanel.tsx`): wrap each raw
  `JSON.stringify` display block in `devMode`.
- **Raw-YAML editor** (`PublishYamlEditor.tsx`): gate the raw editor toggle/panel
  behind dev mode; guided publish stays.
- **ErrorBoundary / main.tsx** (`main.tsx:17-25,38-40`): outside React tree —
  read `localStorage['ari_dev_mode']` directly with a tiny inline helper. In dev
  mode show the full stack (current behavior); otherwise show a short friendly
  message with a "enable developer mode for details" hint. Do NOT remove the
  boundary.
- **StepScope `dangerouslySetInnerHTML`** (`:121,137`): optional to gate; the
  clean fix (plain JSX) is out of scope. If gated, non-dev users still see the
  scope summary rendered safely — prefer leaving the summary visible to all and
  flagging the `dangerouslySetInnerHTML` for a separate cleanup rather than
  hiding useful info.

Where a surface is shown in dev mode, add a small `dev_only_badge` so it is
visually obvious the affordance is developer-only.

### 7.4 Default-OFF rationale

Default OFF gives casual/first-run users a clean, non-alarming dashboard and
removes accidental secret/HPC exposure from the default view, while developers
flip one switch in Settings to restore full diagnostics. This matches the
progressive-disclosure direction of sibling subtasks **069** and **070**.

Classification summary: **ADAPT** (frontend behind an additive flag). No
**DELETE**, no **MOVE_TO_LEGACY**, no **MERGE**. The dashboard REST/WS contract,
`/api/settings` payload, and `Settings` type are **KEEP** (untouched).

## 8. Concrete Work Items

Execute only after the 059 (FE/BE structure) and 067 (visible-settings)
inventories exist (Section 15). Suggested order:

1. **Ingest 059/067 inventories** to confirm the authoritative list of
   raw/debug/dangerous surfaces and the Settings layout, so the toggle placement
   and the gate list match the inventory (avoid missing a surface).
2. **Add `src/hooks/useDevMode.ts`** (flag read/write, default OFF) using the
   `useI18n` shape; choose and implement the cross-component sync mechanism
   (Section 7.1). Add a unit test for get/set/default.
3. **Optionally extend `AppContext`** with `devMode` + `setDevMode` if using the
   context-based sync; keep `AppContextType` additive (new optional-ish fields,
   no removals) so existing consumers compile unchanged.
4. **Add the Settings toggle** in `SettingsPage.tsx` (Language card region) +
   i18n keys in `en.ts`/`ja.ts`/`zh.ts` at parity. Verify `tsc --noEmit` and that
   the flat `/api/settings` save object still has exactly its current keys.
5. **Gate each surface** from Section 7.3, one commit per surface where practical:
   DetailPanel Raw tab → env auto-read → SLURM Start → raw JSON dumps → YAML
   editor → main.tsx ErrorBoundary. Run `npm run test` + `npm run typecheck`
   after each.
6. **Handle the `activeTab==='raw'` edge case** in DetailPanel (fall back to
   `overview` when dev mode turns off).
7. **Add/extend Vitest coverage** (`src/**/__tests__` or co-located `*.test.tsx`):
   (a) `useDevMode` default OFF + toggle persists to `localStorage`; (b) the Raw
   tab button is absent when dev mode OFF and present when ON; (c) the env
   auto-read button is hidden when OFF. Reset `localStorage` in `beforeEach`
   (pattern from `PaperBench/__tests__/*.test.tsx`).
8. **Update per-directory READMEs** (`src/hooks/README.md`, `src/README.md` if it
   lists hooks) to mention `useDevMode`.
9. **Run the full gate set** (Section 12): `npm run typecheck`, `npm run test`,
   `npm run build`, plus `python -m compileall .`, `ruff check .`, `pytest -q`
   (the last three should be unaffected but must stay green).

## 9. Files Expected to Change

Runtime frontend code (only when this subtask is executed, post-059/067):

- **New** `ari-core/ari/viz/frontend/src/hooks/useDevMode.ts` — flag hook/store.
- `ari-core/ari/viz/frontend/src/context/AppContext.tsx` — optional `devMode`
  field (only if context-based sync chosen; additive).
- `ari-core/ari/viz/frontend/src/components/Settings/SettingsPage.tsx` — add the
  Developer Mode toggle row; must NOT alter the flat `/api/settings` save keys.
- `ari-core/ari/viz/frontend/src/i18n/en.ts`, `ja.ts`, `zh.ts` — new dev-mode
  keys, added at strict key parity across all three.
- `ari-core/ari/viz/frontend/src/components/Tree/DetailPanel.tsx` — gate the
  `'raw'` tab (button + render block + `activeTab` fallback).
- `ari-core/ari/viz/frontend/src/components/Wizard/StepResources.tsx` — gate the
  env-key auto-read button.
- `ari-core/ari/viz/frontend/src/components/Monitor/GpuMonitor.tsx` — gate the
  SLURM auto-resubmit Start control.
- `ari-core/ari/viz/frontend/src/components/Monitor/monitorSections.tsx`,
  `src/components/Tree/DetailPanelTabs/TraceTab.tsx`,
  `src/components/Experiments/ExperimentsPage.tsx`,
  `src/components/Results/resultSections.tsx`,
  `src/components/Results/resultHelpers.ts` — gate raw `JSON.stringify` dumps.
- `ari-core/ari/viz/frontend/src/components/Results/PublishYamlEditor.tsx` — gate
  the raw-YAML editor.
- `ari-core/ari/viz/frontend/src/main.tsx` — dev-mode-aware ErrorBoundary /
  fallback (direct `localStorage` read; boundary kept).
- Possibly `ari-core/ari/viz/frontend/src/components/Wizard/StepScope.tsx` — only
  if the `dangerouslySetInnerHTML` summary is gated (Section 7.3 prefers leaving
  it visible and flagging the HTML injection separately).
- **New** test file(s), e.g.
  `ari-core/ari/viz/frontend/src/hooks/__tests__/useDevMode.test.ts` and/or
  `src/components/Tree/__tests__/DetailPanel.devmode.test.tsx`.
- `ari-core/ari/viz/frontend/src/hooks/README.md` and, if it enumerates hooks,
  `ari-core/ari/viz/frontend/src/README.md` — mention `useDevMode`.

Files that MUST NOT change: any `ari-core/ari/viz/*.py` backend, `src/services/api.ts`
(the `/api/env-keys` and `gpuMonitorAction` calls are referenced read-only, not
altered), `src/types/index.ts` `Settings` type, `docs/`, `.github/workflows/`,
`report/`.

This planning document:
`docs/refactoring/subtasks/071_add_dashboard_developer_mode.md` (the only file
created by the planning phase).

## 10. Files / APIs That Must Not Be Broken

- **Dashboard REST + WS contract** — every path/method/JSON-key/status-code/
  header consumed by `src/services/api.ts` (863) stays identical; no endpoint is
  added, removed, or reshaped. The `/api/env-keys` and `/api/gpu-monitor` calls
  still exist and behave the same (we only hide the UI buttons that trigger them).
- **`/api/settings` flat-object contract** — the ~24-key POST body
  (`SettingsPage.tsx:235-260`) and the `Settings` TS type (`src/types/index.ts:38-75`)
  are unchanged. `ari-core/tests/test_api_schema_contract.py` (pins `Settings`,
  `AppState`, `Checkpoint`, `CheckpointSummary`) must stay green. Subtask **070**
  relies on this contract being intact.
- **`ari_lang` language persistence** — `useI18n()` and `localStorage['ari_lang']`
  behavior (`i18n/index.ts`) is untouched; the new `ari_dev_mode` key is
  independent and must not collide.
- **i18n key parity** — `en.ts`/`ja.ts`/`zh.ts` must have identical key sets
  after the additions (see Section 11 note on the current 444-vs-441 drift).
- **Existing frontend tests** — `PaperBench/__tests__/PaperBenchWizard.test.tsx`
  and `PaperImportDialog.test.tsx` must still pass; do not change shared i18n keys
  they assert on.
- **CLI `ari`**, **`ari.public.*`**, **MCP tool contracts** of the 14
  `ari-skill-*` servers, checkpoint/config file formats — all untouched
  (frontend-only subtask).
- **Scripts called by `.github/workflows`** — unaffected. Note the React `i18n/*.ts`
  dictionaries are NOT currently covered by `scripts/docs/check_i18n_js.py` (that
  gate targets `docs/i18n/landing.{en,ja,zh}.js`, not React), so key parity here
  is enforced by tests/typecheck, not that script (Section 17).

## 11. Compatibility Constraints

- **Purely additive, client-only.** The dev-mode flag lives only in
  `localStorage`; nothing on the wire changes. No compatibility adapter is
  needed because no external contract is touched. If a future subtask ever wants
  server-persisted dev mode, that is a new `/api/settings` field and MUST be
  designed as an additive-key change with its own contract-test update — do not
  do it here.
- **Default OFF must not hide anything users legitimately need.** The gated
  surfaces are diagnostics, secrets, and one destructive HPC action — safe to
  hide by default. Do not gate primary product functionality (results viewing,
  wizard steps, manual key entry, guided publish).
- **`activeTab` state safety.** Hiding the DetailPanel Raw tab while it is the
  active tab must not leave the panel blank — fall back to `overview`.
- **i18n parity is a hard constraint.** The current tree already has a minor key
  drift (`en.ts` 444 vs `ja.ts`/`zh.ts` 441). This subtask must add its new keys
  to **all three** files so it does not worsen the drift; ideally reconcile the
  pre-existing 3-key gap while here (optional, note it if done).
- **Do not use the term "deprecated"** for any gated internal surface — these are
  internal UI affordances being conditionally rendered, not external-contract
  deprecations.
- **No `pnpm`.** Use `npm` only (no `pnpm`/`yarn` lockfiles). `package-lock.json`
  is the tracked lockfile; `node_modules/` is gitignored
  (`frontend/.gitignore`-scoped, verified) — do not commit it.

## 12. Tests to Run

From repo root `/home/t-kotama/workplace/ARI` (editable installs already set up
by `setup.sh`):

Backend/global gates (must remain green — should be unaffected):

```bash
python -m compileall .        # full syntax gate
ruff check .                  # lint (ruff IS available; radon is NOT)
pytest -q                     # full Python suite (viz contract tests included)
```

Frontend gates (the primary gate for this subtask), from
`ari-core/ari/viz/frontend/`:

```bash
npm ci                        # or npm install; node+npm available, NO pnpm
npm run typecheck             # tsc --noEmit — catches i18n/type regressions
npm run test                  # vitest run
npm run build                 # vite build — production bundle must succeed
```

Targeted contract check (backend): confirm the `/api/settings` shape did not
drift:

```bash
pytest -q ari-core/tests/test_api_schema_contract.py
```

Run `scripts/run_all_tests.sh` if present for CI parity. CI guard
`.github/workflows/refactor-guards.yml` must stay green (no new `~/.ari/`
references).

## 13. Acceptance Criteria

1. `npm run typecheck`, `npm run test`, and `npm run build` all pass; no new
   TypeScript errors.
2. `python -m compileall .`, `ruff check .`, and `pytest -q` pass unchanged
   (including `test_api_schema_contract.py`).
3. A working `useDevMode()` hook exists, defaults to **OFF** (key absent), and
   persists to `localStorage['ari_dev_mode']`; toggling it in Settings flips the
   gated surfaces without a page reload.
4. With dev mode **OFF**: the DetailPanel Raw tab is absent; the env-key
   auto-read button is hidden; the SLURM auto-resubmit Start is hidden; raw
   `JSON.stringify` debug dumps are hidden; the raw-YAML editor is hidden; the
   ErrorBoundary shows a friendly message (no full stack).
5. With dev mode **ON**: every one of those surfaces is available exactly as
   today, marked with a developer-only badge where practical.
6. No dashboard REST/WS endpoint, `/api/settings` key, or `Settings` type changed;
   `src/services/api.ts` unchanged.
7. `en.ts`/`ja.ts`/`zh.ts` have identical key sets after the change (parity
   verified; pre-existing 3-key drift not worsened).
8. New Vitest test(s) assert default-OFF, persistence, and at least one gated
   surface's presence/absence.
9. Per-directory READMEs updated for the new hook file (readme gates pass).

## 14. Rollback Plan

- The change is additive frontend TypeScript behind a single flag, so rollback is
  a `git revert` of the subtask's commits. Because the gated surfaces are only
  conditionally rendered (never deleted), reverting restores the exact prior
  always-visible behavior.
- Land incrementally per Section 8 (one surface per commit); each gate commit is
  independently revertible and independently gated by `npm run test` +
  `npm run typecheck`.
- If the cross-component sync mechanism (Section 7.1) proves flaky, the toggle can
  temporarily require a page reload to take effect (read flag on mount only) as a
  degraded but safe fallback, without reverting the gates.
- No data/format migration is involved (the flag is a browser `localStorage`
  key); clearing `localStorage['ari_dev_mode']` returns any user to the default
  OFF state. Nothing server-side to migrate back.

## 15. Dependencies

Consistent with the provided DEPENDENCY GRAPH: the only explicit edge into 071 is
`059 -> 071` (`007_subtask_index.md:449`).

- **Hard predecessor (gate): 059** `inventory_dashboard_frontend_backend_structure`.
  059 is one of the nine inventory subtasks that MUST precede any runtime code
  change (`001, 002, 020, 036, 045, 053, 059, 060, 067`), and the whole Phase-6
  fan-out (`059 -> 067..073`) originates from it. 059 supplies the authoritative
  FE structure (stack, routing, state, the raw/debug surface list) this subtask
  gates.
- **Inventory gate: 067** `inventory_dashboard_visible_settings`. 067 is itself a
  required inventory gate for the settings surface and inventories the 9-Card
  SettingsPage where the toggle lives; ingest it so the toggle placement and the
  gated-surface list are complete.
- **Coordinates with (design docs, no runtime code): 068**
  (`define_dashboard_information_architecture`) and **069**
  (`design_dashboard_progressive_disclosure`) — developer mode is the concrete
  progressive-disclosure mechanism these design docs specify; align the OFF/ON
  taxonomy with them.
- **Coordinates with (runtime, potential merge conflict): 070**
  (`refactor_dashboard_settings_panel`) — both edit `SettingsPage.tsx`. 070 must
  preserve the `/api/settings` flat contract; 071's toggle must NOT be added to
  that flat save. Sequence 071's toggle addition to land with (or just after) 070
  to avoid conflicting rewrites of the Settings layout.
- **Coordinates with: 072** (`improve_dashboard_empty_loading_error_states`) —
  both touch `main.tsx`'s ErrorBoundary; align on who owns the friendly-error
  fallback so the dev-mode stack gate and the improved error state are
  consistent.
- **Downstream: 073** (`add_dashboard_ux_regression_checks`) — the UX regression
  checks should include a dev-mode ON/OFF assertion; provide the test hooks/data
  attributes 073 can target.
- Per `007_subtask_index.md`, all of 067–073 depend only on 059; there is no edge
  from 070/072 into 071, so the coordination above is scheduling guidance, not a
  hard graph dependency.

## 16. Risk Level

- **Does this subtask change runtime code? YES** — when executed it modifies and
  adds frontend TypeScript under `ari-core/ari/viz/frontend/src/` (a new hook,
  the Settings toggle, i18n keys, conditional-render guards across ~9 components,
  and `main.tsx`). It changes **no backend Python** and **no wire/API contract**.
  (This planning document itself changes no runtime code.)
- **Risk: MEDIUM** (consistent with `007_subtask_index.md:118`). Rationale: the
  change is additive and reversible, but it touches many files (several of them
  very large god-components: `SettingsPage.tsx` 1049, `StepResources.tsx` 1160,
  `resultSections.tsx` 1590), and correctness hinges on (a) not accidentally
  gating primary functionality, (b) i18n key parity across three dictionaries,
  and (c) the cross-component sync of the flag. `main.tsx` is a special case
  (outside React context) and easy to get subtly wrong. Mitigations: default-OFF
  is safe-by-construction, each surface is gated in its own commit, Vitest +
  `tsc --noEmit` + `vite build` gate every step, and the backend contract tests
  confirm nothing leaked into `/api/settings`.

## 17. Notes for Implementer

- **Developer mode is UX, not security.** It hides affordances; it does not
  protect the endpoints. Explicitly flag as **REVIEW_REQUIRED** for a dedicated
  security subtask: unauthenticated `/api/env-keys` returning real secrets
  (`api.ts:382-383`), unauthenticated SLURM submit with hard-coded
  `confirmed:true` (`api.ts:584-585`), and the "no auth on any endpoint" posture.
  Do NOT attempt to add auth/CSRF here — it would change observable behavior and
  is out of scope.
- **Copy the `ari_lang` pattern, but fix its weakness.** `useI18n()` instances do
  not cross-notify on language change; for dev mode, ensure a single source of
  truth (context or a `storage`/custom-event subscription) so flipping the toggle
  updates every mounted component immediately (Section 7.1).
- **`main.tsx` is outside the React tree.** The `ErrorBoundary` cannot call
  `useDevMode()`. Read `localStorage['ari_dev_mode']` directly there with a tiny
  helper (guarded for SSR/absence, though this app is client-only).
- **Do NOT add the flag to `/api/settings`.** The flat 24-key save
  (`SettingsPage.tsx:235-260`) is a frozen contract that subtask 070 preserves and
  `test_api_schema_contract.py` pins. The toggle writes `localStorage` directly,
  exactly like language selection does independently of the settings POST.
- **Keep every gated surface reachable in dev mode.** The goal is to hide by
  default, not to remove. Add a `dev_only_badge` so it is obvious the surface is
  developer-only.
- **Prefer leaving `StepScope.tsx`'s summary visible.** Its
  `dangerouslySetInnerHTML` (`:121,137`) is a hygiene/security nit better fixed by
  converting to plain JSX in a separate cleanup; hiding a useful scope summary
  behind dev mode would degrade the product view.
- **i18n parity: touch all three dictionaries.** `en.ts` (444) already leads
  `ja.ts`/`zh.ts` (441) by 3 keys; add new keys to all three and, if convenient,
  reconcile the pre-existing gap. There is no React-i18n parity CI gate today
  (`scripts/docs/check_i18n_js.py` covers only `docs/i18n/landing.*.js`), so rely
  on `tsc`/tests — and consider proposing such a gate as future work (out of
  scope of 071).
- **No `pnpm`.** Use `npm ci` / `npm run {typecheck,test,build}`. Do not commit
  `node_modules/` (gitignored); `package-lock.json` is the tracked lockfile.
- **Update the per-directory READMEs.** ARI enforces readme-parity/doc-source
  gates; add `useDevMode` to `src/hooks/README.md` (and `src/README.md` if it
  lists hooks).

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **071** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
