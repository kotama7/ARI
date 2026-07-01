# Subtask 072: Improve Dashboard Empty / Loading / Error States

> Phase 6: Dashboard UX · Risk: Low–Medium · Runtime code change: **Yes (frontend only)** · Depends on: **059** (direct), and the inventory gate **001, 002, 020, 036, 045, 053, 060, 067** must land first.
>
> This is a planning document. Nothing here modifies runtime code, imports, prompts,
> configs, workflows, frontend source, or directory names. It hands a fresh coding
> session an executable plan to **unify the loading / empty / error rendering** of the
> ARI dashboard React frontend (`ari-core/ari/viz/frontend/`). All paths and line
> numbers are repository-real, verified against the working tree on 2026-07-01
> (ari-core `0.9.0`, branch `main`). Where a path or symbol was checked and not found,
> it is written as "does not exist".

---

## 1. Goal

Make the three **non-happy-path UI states** — *loading*, *empty*, and *error* —
**consistent, i18n-complete, and token-styled** across every dashboard React page and
feature component, without changing any dashboard API endpoint, wire schema, or the
`services/api.ts` function signatures.

Concretely:

1. Introduce three tiny shared presentational components under
   `ari-core/ari/viz/frontend/src/components/common/` — `LoadingState`,
   `EmptyState`, `ErrorState` — exported from `components/common/index.ts` alongside
   the existing `Card`, `Badge`, `StatBox`, `Button`, `StatusBadge`.
2. **Adopt the hook that already exists**: `hooks/useApi.ts` (43 lines) already returns
   `{ data, loading, error, refetch }` with `loading` initialised `true`, but only
   **one** of the ~12 top-level pages consumes it
   (`components/PaperBench/PaperRegistryPage.tsx:37`). Wire the remaining page-level
   fetchers to the same hook where they hand-roll `useState`/`.then`/`.catch`.
3. Replace the ad-hoc mix of bare spinners, hardcoded-English strings, hardcoded hex
   error colors, and silent `.catch(() => {})` swallows with the shared components and
   existing (or newly added) i18n keys.
4. Guarantee every user-triggered fetch has a **visible** failure path (no invisible
   swallows) and every list/detail surface has a defined **empty** rendering.

The end state: a reader can point at any page and see the same loading affordance
(`spinner` + translated label), the same empty affordance (`.empty-state` icon + block),
and the same error affordance (token-colored message + optional **Retry**), all driven
by keys present in `en.ts` **and** its `ja.ts` / `zh.ts` mirrors.

## 2. Background

The dashboard is Vite 5 + React 18.3 + TypeScript, hash-routed, single React Context
(`context/AppContext.tsx`), same-origin `fetch` via `services/api.ts` (863 lines). There
is **no** CSS framework — styling is `src/styles/*.css` plus pervasive inline
`style={{}}`. The three state renderings grew per-component, so today they diverge along
four axes:

**(a) Loading indicators are inconsistent.** Confirmed variants:

| Where | Render | i18n? |
| --- | --- | --- |
| `App.tsx:75-77` (Suspense fallback) | bare `<div className="spinner" />`, no text | n/a |
| `components/Results/ResultsPage.tsx:385` | `<span className="spinner" /> {t('loading')}` | yes |
| `components/Results/PaperWorkspace.tsx:384` | `<span className="spinner" /> Loading file...` | **no (hardcoded EN)** |
| `components/Wizard/StepLaunch.tsx:130` | `<span className="spinner" /> Launching...` | **no** |
| `components/Results/EarSection.tsx:52` | `<span className="spinner" /> Loading EAR...` | **no** |
| `components/Tree/FileExplorer.tsx:346,368` | plain `Loading...`, **no spinner** | **no** |
| `components/Tree/DetailPanelTabs/MemoryTab.tsx:33` | `Loading memory…`, no spinner | **no** |
| `components/PaperBench/PaperRegistryPage.tsx:79` | `{t('pb_loading')}`, no spinner | yes |

**(b) Empty states use three different idioms.**

- `.empty-state` + `.empty-icon` emoji block (CSS at `styles/components.css:71-73`):
  `components/Experiments/ExperimentsPage.tsx:88-90` (`🗂️`, "No experiments found" — hardcoded EN),
  `components/Home/HomePage.tsx:114-115` ("No experiments yet" — hardcoded EN),
  `components/Results/ResultsPage.tsx:397-398,451-453` (`📊`, "No results data found in this checkpoint" — hardcoded EN).
- Muted inline text driven by i18n keys:
  `MemoryTab.tsx:46` `t('memory_empty')`, `DetailPanelTabs/AccessTab.tsx:36` `t('memory_access_empty')`,
  `FileExplorer.tsx:375` `t('file_explorer_empty')`, `PaperRegistryPage.tsx:87` `t('pb_no_papers')`,
  `Wizard/stepResourcesSections.tsx:330` `t('wiz_fewshot_empty')`,
  `Results/resultSections.tsx:573,1526` `t('repro_log_empty')`, `:1585` `t('no_repro')`,
  `Tree/DetailPanelTabs/ReportTab.tsx:93` `t('report_no_changes')`.
- Hardcoded-English inline sentence: `components/Idea/IdeaPage.tsx:274`
  ("No VirSci hypotheses available. VirSci deliberation may not have run yet…").

**(c) Error rendering uses hardcoded hex and an undefined token.** A grep over
`components/**.tsx` counts **43** hardcoded state hex colors (`#fee`, `#efe`, `#d33`,
`#ef4444`, `#888`, `#666`, `#64748b`). Examples: `#fee` error backgrounds at
`PaperBench/PaperBenchWizard.tsx:389`, `PaperBench/PaperImportDialog.tsx:244`,
`PaperBench/results/ResultsView.tsx:148`, `PaperRegistryPage.tsx:81`; `var(--red)` at
`Wizard/StepLaunch.tsx:200` and `FileExplorer.tsx:371` (`var(--red, #ef4444)`).
**Confirmed defect:** `components/Workflow/WorkflowPage.tsx:394` renders error text with
`color: 'var(--danger)'`, but `--danger` is **not defined** anywhere in
`styles/tokens.css` (defined tokens are `--muted #64748b`, `--blue`, `--green`,
`--red #ef4444`, `--yellow`, `--purple`; no `--danger`). So that error message renders in
the inherited body color, not red. `ReportTab.tsx:22` avoids the bug only by supplying a
fallback `var(--danger, #ef4444)`.

**(d) Some failures are invisible.** `components/Experiments/ExperimentsPage.tsx:37`
swallows the lineage fetch failure with `.catch(() => { /* swallow */ })`, and the
`viewTree` handler at `ExperimentsPage.tsx:54-64` calls
`fetchCheckpointSummary(id).then(...)` with **no `.catch`** at all — a rejected promise
leaves the user with no feedback.

**(e) i18n vocabulary is half-present but under-used.** `i18n/en.ts` already defines
`loading: 'Loading…'` (`en.ts:162`), `no_data: 'No data available'` (`:163`), and
`error_prefix: 'Error: '` (`:165`), plus many `*_empty` / `*_loading` keys, yet most
components ignore them and hardcode English (see table above). The mirror files are also
out of sync: `en.ts` is 444 lines vs `ja.ts` / `zh.ts` at 441 each — 3 keys already drift,
and this gap is guarded by `scripts/docs/check_i18n_js.py`.

**(f) Two error regimes in the API client.** `get`/`post` **throw** on non-2xx
(`services/api.ts:18-32`), but the PaperBench `pbGet`/`pbPost` wrappers **never throw**
and instead return `{ error }` bodies (`api.ts:787-799`). So a shared `ErrorState`
component must accept both a thrown-message string (from `useApi`) and a
`response.error` string — it must not assume one regime. **This subtask does not change
either regime** (that is a contract concern owned by 060 / 021).

This subtask is pure **Phase 6 UX polish**: it standardizes presentation and closes the
"invisible failure" gaps. It does not decompose god-components (that is other Phase-6 /
Phase-5 subtasks) and does not touch the backend.

## 3. Scope

**In scope (frontend only):**

- Create `LoadingState`, `EmptyState`, `ErrorState` presentational components in
  `components/common/` and export them from `components/common/index.ts`.
- Add any missing i18n keys to `i18n/en.ts`, `i18n/ja.ts`, `i18n/zh.ts` **together**
  (keep all three in lockstep to satisfy `check_i18n_js.py`).
- Optionally add an `.error-state` rule to `styles/components.css` mirroring the
  existing `.empty-state` block; reuse the existing `--red` / `--muted` tokens (never
  reintroduce hardcoded hex).
- Wire page-level and feature-level fetchers to render the shared components, adopting
  `hooks/useApi.ts` where a page currently hand-rolls `useState` loading/error/`.catch`.
- Give `ExperimentsPage` (and any other silent swallow / missing `.catch`) a visible
  error or graceful degraded rendering.
- Give the top-level `App.tsx` Suspense fallback a translated label next to the spinner.

**Out of scope but adjacent (leave as-is, cross-reference):**

- `services/api.ts` behavior (throw vs `{error}` regimes), endpoint set, and typed
  shapes — owned by subtasks **060** (contract inventory) and **021** (viz services).
- The `main.tsx` ErrorBoundary raw-stack dump (`main.tsx:17-25`) and raw-`innerHTML`
  fallback (`main.tsx:38`) — these are a security/raw-debug concern tracked separately
  in the Phase-6 "dangerous/raw-debug UI" line item; classify **REVIEW_REQUIRED** and do
  not gate this subtask on them (an implementer *may* add a translated headline while
  preserving the stack for developer diagnostics, but must not remove the boundary).
- God-component decomposition (`resultSections.tsx` 1590, `StepResources.tsx` 1160,
  `SettingsPage.tsx` 1049) — separate subtasks.

## 4. Non-Goals

- **No** change to any dashboard API endpoint path, request/response schema, or
  WebSocket message shape (`services/api.ts`, `hooks/useWebSocket.ts`,
  `ari-core/ari/viz/routes.py` and `api_*.py`).
- **No** change to the two `services/api.ts` error regimes (throw vs `{error}`).
- **No** new runtime dependency (no react-query, no toast library, no CSS framework).
  The three shared components are plain React + existing CSS tokens.
- **No** state-management refactor (keep the single `AppContext` + 5 s polling model).
- **No** routing change (keep the hand-rolled hash router in `App.tsx`).
- **No** removal of raw-debug surfaces (Raw JSON tab, `dangerouslySetInnerHTML`, env-key
  reads) — owned by other Phase-6 items.
- **No** backend (`.py`) edits. This subtask must remain frontend-only.

## 5. Current Files / Directories to Inspect

Root: `ari-core/ari/viz/frontend/`. All paths below are real (verified 2026-07-01).

**Shared building blocks (will be extended):**
- `src/components/common/index.ts` — barrel export (`Card, Badge, StatBox, Button, StatusBadge`); **no** state components today.
- `src/components/common/` — `Badge.tsx`, `Button.tsx`, `Card.tsx`, `StatBox.tsx`, `StatusBadge.tsx`, `README.md`.
- `src/hooks/useApi.ts` (43 lines) — the reusable `{data, loading, error, refetch}` hook to adopt.
- `src/styles/components.css` — `.spinner` (`:67`), `.empty-state` / `.empty-icon` / `.empty-state p` (`:71-73`); **no** `.error-state`.
- `src/styles/tokens.css` — color tokens (`--muted`, `--red`, `--green`, `--blue`, `--yellow`, `--purple`); **`--danger` is not defined here.**
- `src/i18n/en.ts` (444), `src/i18n/ja.ts` (441), `src/i18n/zh.ts` (441) — existing keys `loading`, `no_data`, `error_prefix`, and the `*_empty` / `*_loading` family.

**Pages / components with divergent state rendering (targets):**
- `src/App.tsx` — Suspense fallback (`:75-77`).
- `src/components/Experiments/ExperimentsPage.tsx` — swallowed `.catch` (`:37`), missing `.catch` (`:54-64`), hardcoded empty (`:88-90`).
- `src/components/Home/HomePage.tsx` — hardcoded empty (`:114-115`).
- `src/components/Results/ResultsPage.tsx` — multiple local loading `useState` (`:31,35,45,54`), `t('loading')` spinner (`:385`), hardcoded empty (`:397-398,451-453`).
- `src/components/Results/PaperWorkspace.tsx` — hardcoded "Loading file..." (`:384`).
- `src/components/Results/EarSection.tsx` — hardcoded "Loading EAR..." (`:52`).
- `src/components/Results/resultSections.tsx` (1590) — `t('repro_log_empty')` (`:573,1526`), `t('no_repro')` (`:1585`).
- `src/components/Tree/FileExplorer.tsx` — plain "Loading..." (`:346,368`), `error` (`:371`), `t('file_explorer_empty')` (`:375`).
- `src/components/Tree/DetailPanelTabs/MemoryTab.tsx` — "Loading memory…" (`:33`), `t('memory_empty')` (`:46`).
- `src/components/Tree/DetailPanelTabs/AccessTab.tsx` — `t('memory_access_empty')` (`:36`).
- `src/components/Tree/DetailPanelTabs/ReportTab.tsx` — `var(--danger, #ef4444)` (`:22`), `t('report_no_changes')` (`:93`).
- `src/components/Idea/IdeaPage.tsx` — hardcoded empty sentence (`:274`).
- `src/components/Wizard/StepLaunch.tsx` — "Launching..." (`:130`), `var(--red)` error (`:200`).
- `src/components/Wizard/stepResourcesSections.tsx` — `t('wiz_fewshot_empty')` (`:330`).
- `src/components/Workflow/WorkflowPage.tsx` — **undefined-token** error color (`:394`).
- `src/components/PaperBench/PaperRegistryPage.tsx` (147) — **reference model**: `useApi` at `:37`, loading/error/empty at `:79-87`.
- `src/components/PaperBench/PaperImportDialog.tsx` — `#d33`/`#fee` error (`:244`).
- `src/components/PaperBench/PaperBenchWizard.tsx` — `#fee`/`#efe` result banner (`:389`).
- `src/components/PaperBench/results/ResultsView.tsx` — `#d33`/`#fee` error (`:148`), empty labels (`:141,178,295`).

**Reference / guardrails (read-only for context):**
- `src/main.tsx` — ErrorBoundary (`:5-30`), raw fallback (`:36-40`) — out of scope, do not break.
- `scripts/docs/check_i18n_js.py` — CI guard for i18n key parity across `en/ja/zh`.
- `src/components/PaperBench/__tests__/PaperBenchWizard.test.tsx`, `.../PaperImportDialog.test.tsx` — the only existing frontend tests (Vitest).

## 6. Current Problems

1. **No shared state components.** `components/common/` exports only layout atoms; every
   page reinvents loading/empty/error inline, so the same concept has 8+ renderings
   (Section 2a-c). Maintenance and translation coverage suffer.
2. **`useApi` is orphaned.** A perfectly good `{data, loading, error, refetch}` hook
   exists (`hooks/useApi.ts`) but is used by exactly **one** component
   (`PaperRegistryPage.tsx:37`). Other pages hand-roll `useState` clusters
   (`ResultsPage.tsx` alone has `loading`, `earLoading`, `fileLoading`,
   `reproLogLoading` at `:31,35,45,54`).
3. **Loading strings are half-translated.** Four components hardcode English loading
   labels ("Loading file...", "Loading...", "Launching...", "Loading EAR...",
   "Loading memory…") despite `en.ts:162 loading: 'Loading…'` existing.
4. **Empty states diverge three ways** (emoji `.empty-state` block, muted i18n text,
   hardcoded English sentence) — see Section 2b — with no shared component to unify them.
5. **Error colors are hardcoded and one is broken.** 43 hardcoded state hex values;
   `WorkflowPage.tsx:394` uses the **undefined** `var(--danger)` token, so its error text
   is not red. Design tokens exist (`--red`, `--muted`) but are inconsistently applied.
6. **Invisible failures.** `ExperimentsPage.tsx:37` swallows a fetch error; the
   `viewTree` handler (`ExperimentsPage.tsx:54-64`) has no `.catch`. Users get no signal
   when these fail.
7. **No Retry affordance** except where a component happens to call `refetch`. `useApi`
   exposes `refetch`, but non-adopters cannot offer retry without bespoke wiring. i18n
   already ships `cfg_retry` (`en.ts:225`) that can seed a generic retry label.
8. **i18n mirror drift** (444 vs 441). Adding new state keys must update all three files
   simultaneously or `check_i18n_js.py` fails CI.
9. **Two API error regimes** (throw vs `{error}`) mean a shared `ErrorState` must accept
   a plain string message from either source without assuming which one produced it.

## 7. Proposed Design / Policy

### 7.1 Three shared presentational components (classification: KEEP + ADD)

Add under `components/common/` (plain function components, no new deps, tokens only):

- **`LoadingState`** — props `{ label?: string; inline?: boolean }`. Renders
  `<span className="spinner" /> {label ?? t('loading')}`. `inline` toggles between a
  centered block (page-level) and an inline row (within a card/editor). This unifies the
  spinner + label pattern from `ResultsPage.tsx:385` and the bare spinner from
  `App.tsx:76`.
- **`EmptyState`** — props `{ icon?: string; message: string; hint?: string }`. Renders
  the existing `.empty-state` / `.empty-icon` markup (CSS already at
  `components/components.css:71-73`) so the emoji-block idiom becomes the single
  canonical empty rendering. Callers pass a **translated** `message`.
- **`ErrorState`** — props `{ message: string; onRetry?: () => void; retryLabel?: string }`.
  Renders a token-colored (`var(--red)`) message plus, when `onRetry` is supplied, a
  small `Button` labeled `retryLabel ?? t('cfg_retry')`. Accepts the message string from
  **either** API error regime (thrown message or `response.error`). Optionally styled via
  a new `.error-state` CSS rule (Section 7.4).

Export all three from `components/common/index.ts`.

### 7.2 Adoption policy (per surface)

| Surface | Policy | Action |
| --- | --- | --- |
| Page-level fetchers that hand-roll `useState`+`.then`+`.catch` | **ADAPT** to `useApi` where it fits mount-only fetch; otherwise keep local state but render via shared components | `ExperimentsPage`, `HomePage`, `ResultsPage`, `IdeaPage`, `WorkflowPage` |
| Already uses `useApi` | **KEEP**, swap inline markup for shared components | `PaperRegistryPage` |
| Feature sub-panels with local loading | **KEEP** local state (they are coupled to parent state), swap markup for shared components | `FileExplorer`, `MemoryTab`, `AccessTab`, `PaperWorkspace`, `EarSection`, `StepLaunch` |
| PaperBench `{error}`-regime callers | **KEEP** regime, feed `response.error` into `ErrorState` | `PaperImportDialog`, `PaperBenchWizard`, `results/ResultsView` |
| Top-level Suspense fallback | **ADAPT** `App.tsx:75-77` to `<LoadingState />` (spinner + `t('loading')`) | `App.tsx` |
| `main.tsx` ErrorBoundary | **REVIEW_REQUIRED** — leave stack for devs; optional translated headline only | `main.tsx` |

Adopting `useApi` is a *should*, not a *must*: some components legitimately keep local
state because loading is derived from parent props (e.g. `MemoryTab.memLoading`). The
hard requirement is that **rendering** goes through the shared components.

### 7.3 i18n policy

- Reuse existing keys first: `loading`, `no_data`, `error_prefix`, `cfg_retry`, and the
  `*_empty` family.
- Add only the small number of **new** keys needed (e.g. a generic
  `empty_generic`, `error_generic`, `loading_file`, `retry`), and add them to **all
  three** of `en.ts`, `ja.ts`, `zh.ts` in the same commit so `check_i18n_js.py` stays
  green and the 444/441 gap does not widen (ideally shrink it).
- Every replaced hardcoded English string ("Loading file...", "No experiments found",
  "No experiments yet", "No results data found in this checkpoint", "Launching...",
  "Loading EAR...", the IdeaPage sentence) must be routed through `t(...)`.

### 7.4 Styling policy

- Reuse tokens from `styles/tokens.css` (`--red`, `--muted`, `--green`). **Never**
  reintroduce hardcoded hex for state colors.
- Fix the broken reference: wherever `var(--danger)` is used without a fallback
  (`WorkflowPage.tsx:394`), route through `ErrorState` (which uses `var(--red)`); do
  **not** define a new `--danger` token unless a broader design-token subtask owns it —
  standardize on the existing `--red` to avoid token proliferation.
- Add one optional `.error-state` rule to `styles/components.css` mirroring
  `.empty-state`, so `ErrorState` has a canonical class instead of inline styles.

### 7.5 Failure-visibility policy

- No `.catch(() => {})` that hides a user-facing fetch. Either render `ErrorState` or, if
  the data is genuinely optional (e.g. the lineage provenance column at
  `ExperimentsPage.tsx:37`), keep the graceful degrade **but** add a code comment and,
  where appropriate, a subtle inline note rather than total silence.
- Every user-triggered navigation fetch (e.g. `viewTree` at `ExperimentsPage.tsx:54-64`)
  must have a `.catch` that surfaces an error (toast-free: inline `ErrorState` or an
  `alert`/status line consistent with the page).

## 8. Concrete Work Items

1. **Add `LoadingState.tsx`, `EmptyState.tsx`, `ErrorState.tsx`** under
   `src/components/common/` per Section 7.1; export from `components/common/index.ts`.
2. **(Optional) Add `.error-state` CSS** to `src/styles/components.css` mirroring
   `.empty-state` (`:71-73`), using `var(--red)` / `var(--muted)`.
3. **Add missing i18n keys** to `i18n/en.ts`, `i18n/ja.ts`, `i18n/zh.ts` in lockstep
   (generic empty/error/retry + any per-surface loading labels).
4. **Migrate `App.tsx:75-77`** Suspense fallback to `<LoadingState />`.
5. **Migrate empty renderings** to `<EmptyState>`: `ExperimentsPage.tsx:88-90`,
   `HomePage.tsx:114-115`, `ResultsPage.tsx:397-398,451-453`, `IdeaPage.tsx:274`
   (translate the sentence). Where an i18n `*_empty` key is already used with muted text
   (`MemoryTab`, `AccessTab`, `FileExplorer`, `PaperRegistryPage`,
   `stepResourcesSections`, `resultSections`, `ReportTab`), optionally re-route through
   `EmptyState` for consistency but preserve the existing translated message.
6. **Migrate loading renderings** to `<LoadingState>`: `ResultsPage.tsx:385`,
   `PaperWorkspace.tsx:384`, `EarSection.tsx:52`, `StepLaunch.tsx:130`,
   `FileExplorer.tsx:346,368`, `MemoryTab.tsx:33`, `PaperRegistryPage.tsx:79`.
   Translate all hardcoded English labels.
7. **Migrate error renderings** to `<ErrorState>` (token color, optional Retry):
   `WorkflowPage.tsx:394` (fixes the undefined `--danger`), `FileExplorer.tsx:371`,
   `StepLaunch.tsx:200`, `PaperImportDialog.tsx:244`, `PaperBenchWizard.tsx:389`,
   `ResultsView.tsx:148`, `PaperRegistryPage.tsx:80-84`. Remove the hardcoded
   `#fee`/`#efe`/`#d33` hex.
8. **Close invisible failures**: give `ExperimentsPage.tsx:54-64` (`viewTree`) a
   `.catch` with visible feedback; annotate/soften the intentional degrade at
   `ExperimentsPage.tsx:37`.
9. **Wire Retry**: for `useApi` consumers, pass `refetch` into `ErrorState.onRetry`.
10. **Add Vitest tests** (new `__tests__` folder or co-located) for the three shared
    components: label rendering, empty/error message rendering, `onRetry` invocation.
11. **Run the full test gate** (Section 12) and confirm `check_i18n_js.py` passes and the
    en/ja/zh line gap did not widen.

## 9. Files Expected to Change

**New files:**
- `ari-core/ari/viz/frontend/src/components/common/LoadingState.tsx`
- `ari-core/ari/viz/frontend/src/components/common/EmptyState.tsx`
- `ari-core/ari/viz/frontend/src/components/common/ErrorState.tsx`
- `ari-core/ari/viz/frontend/src/components/common/__tests__/StateComponents.test.tsx` (or co-located per-component tests)

**Modified files:**
- `ari-core/ari/viz/frontend/src/components/common/index.ts` (add three exports)
- `ari-core/ari/viz/frontend/src/styles/components.css` (optional `.error-state` rule)
- `ari-core/ari/viz/frontend/src/i18n/en.ts`, `.../ja.ts`, `.../zh.ts` (new keys, lockstep)
- `ari-core/ari/viz/frontend/src/App.tsx`
- `ari-core/ari/viz/frontend/src/components/Experiments/ExperimentsPage.tsx`
- `ari-core/ari/viz/frontend/src/components/Home/HomePage.tsx`
- `ari-core/ari/viz/frontend/src/components/Idea/IdeaPage.tsx`
- `ari-core/ari/viz/frontend/src/components/Results/ResultsPage.tsx`
- `ari-core/ari/viz/frontend/src/components/Results/PaperWorkspace.tsx`
- `ari-core/ari/viz/frontend/src/components/Results/EarSection.tsx`
- `ari-core/ari/viz/frontend/src/components/Results/resultSections.tsx` (empty rows only)
- `ari-core/ari/viz/frontend/src/components/Tree/FileExplorer.tsx`
- `ari-core/ari/viz/frontend/src/components/Tree/DetailPanelTabs/MemoryTab.tsx`
- `ari-core/ari/viz/frontend/src/components/Tree/DetailPanelTabs/AccessTab.tsx`
- `ari-core/ari/viz/frontend/src/components/Tree/DetailPanelTabs/ReportTab.tsx`
- `ari-core/ari/viz/frontend/src/components/Wizard/StepLaunch.tsx`
- `ari-core/ari/viz/frontend/src/components/Wizard/stepResourcesSections.tsx`
- `ari-core/ari/viz/frontend/src/components/Workflow/WorkflowPage.tsx`
- `ari-core/ari/viz/frontend/src/components/PaperBench/PaperRegistryPage.tsx`
- `ari-core/ari/viz/frontend/src/components/PaperBench/PaperImportDialog.tsx`
- `ari-core/ari/viz/frontend/src/components/PaperBench/PaperBenchWizard.tsx`
- `ari-core/ari/viz/frontend/src/components/PaperBench/results/ResultsView.tsx`

The migration is mechanical and can land incrementally (page by page) — each page's edit
is independent, so partial adoption never breaks the build.

## 10. Files / APIs That Must Not Be Broken

- **`services/api.ts` (863 lines)** — do not change any exported function signature,
  path string, or the throw-vs-`{error}` behavior of `get`/`post` vs `pbGet`/`pbPost`.
  This subtask consumes the client; it does not modify it.
- **Dashboard API endpoints & schema** — `ari-core/ari/viz/routes.py`, `api_*.py`,
  `websocket.py` are untouched. No new query params, headers, or auth.
- **`types/index.ts`** typed shapes (`AppState`, `Settings`, `Checkpoint`, etc.) — not
  modified.
- **`context/AppContext.tsx`** polling model and `hooks/useWebSocket.ts` — not modified.
- **`hooks/useApi.ts` public shape** `{ data, loading, error, refetch }` — keep it; more
  callers may depend on it after this subtask.
- **`main.tsx` ErrorBoundary** must remain a working boundary (do not delete the
  stack-preserving developer path).
- **`scripts/docs/check_i18n_js.py`** parity gate — must stay green.
- **Existing frontend tests** — `PaperBench/__tests__/PaperBenchWizard.test.tsx` and
  `PaperImportDialog.test.tsx` must still pass; if `PaperImportDialog.tsx:244`'s error
  markup is refactored, update the test's selectors rather than weakening assertions.
- **CLI `ari`, `ari.public.*`, MCP `ari-skill-*`, checkpoint/config formats** — entirely
  out of this subtask's blast radius (frontend-only), but listed here to affirm they are
  not touched.

## 11. Compatibility Constraints

- **Frontend-only, no backend contract change.** Because nothing in
  `ari-core/ari/viz/*.py` changes, no compatibility adapter is required for the dashboard
  API. The three new components are internal presentational units with no external
  contract.
- **i18n lockstep.** Any new key must be added to `en.ts`, `ja.ts`, and `zh.ts` in the
  same change to satisfy `check_i18n_js.py`; do not introduce an en-only key.
- **Design-token discipline.** Standardize on the existing `--red` token; do **not**
  introduce a new `--danger` token in this subtask (that would be a design-system change
  owned elsewhere). Fixing `WorkflowPage.tsx:394` by routing through `ErrorState`
  (which uses `--red`) is the compatible path.
- **No new npm dependency** — keeps `package-lock.json` and the (gitignored)
  `node_modules/` install unchanged in shape; no supply-chain surface added.
- **Incremental safety.** Each page migration is self-contained; a half-finished
  migration still type-checks and builds.

## 12. Tests to Run

**Frontend (run in `ari-core/ari/viz/frontend/`):**
```bash
npm ci            # or: npm install (no pnpm in this repo)
npm run typecheck # tsc --noEmit — must pass with the new components + props
npm test          # vitest run — existing PaperBench tests + new state-component tests
npm run build     # vite build — production bundle must succeed
```

**i18n parity guard (run from repo root):**
```bash
python scripts/docs/check_i18n_js.py   # en/ja/zh key parity must stay green
```

**Repo-wide sanity gate (run from repo root; frontend edits should not perturb these):**
```bash
python -m compileall .   # no .py changed, but confirm nothing broke
pytest -q                # backend/viz Python tests unaffected
ruff check .             # lint clean
```

New Vitest cases to add for the three components: (a) `LoadingState` renders the spinner
and the default `t('loading')` label; (b) `EmptyState` renders the passed message and
optional icon; (c) `ErrorState` renders the message and calls `onRetry` when the retry
button is clicked and hides the button when `onRetry` is absent.

## 13. Acceptance Criteria

1. `components/common/index.ts` exports `LoadingState`, `EmptyState`, `ErrorState`, and
   they compile under `tsc --noEmit`.
2. No component in `src/components/**` renders a **hardcoded English** loading/empty/error
   string; every such string resolves through `t(...)`. (Spot-check via
   `grep -rn "Loading\.\.\.\|Loading file\|Launching\|No experiments\|No results data" src/components` returning
   only test fixtures.)
3. No `var(--danger)` without a fallback remains; `WorkflowPage.tsx` error text renders
   red via `ErrorState`/`--red`.
4. The count of hardcoded state hex colors (`#fee`, `#efe`, `#d33`, `#ef4444` used for
   error/empty text or backgrounds) in `src/components/**` is reduced (target: the four
   PaperBench error banners and the `WorkflowPage` bug are gone).
5. `ExperimentsPage` `viewTree` has a `.catch` with visible feedback; the intentional
   lineage degrade is annotated.
6. `App.tsx` Suspense fallback shows spinner **and** a translated label.
7. `npm run typecheck`, `npm test`, `npm run build` all pass.
8. `python scripts/docs/check_i18n_js.py` passes; the en/ja/zh line-count gap does not
   widen (444/441/441 or tighter).
9. Repo gate (`python -m compileall .`, `pytest -q`, `ruff check .`) passes unchanged.

## 14. Rollback Plan

- The change is additive + mechanical and lands as one PR (or a stack of per-page
  commits). Rollback = `git revert` the PR / commits. No data migration, no schema
  change, no persisted state involved.
- Because each page migration is independent, a problematic single page can be reverted
  in isolation without touching the shared components.
- The three new components and their exports are inert if unused, so even a partial
  revert leaves a compilable tree.
- No backend, checkpoint, config, or API artifact is touched, so there is nothing to
  roll back outside `ari-core/ari/viz/frontend/`.

## 15. Dependencies

Per the Phase-6 dependency graph, **059 → 072** (072 is one of the seven Phase-6 UX
subtasks — 067–073 — that fan out from the Phase-5 dashboard inventory root **059**).

- **Direct predecessor: 059** — *Inventory Dashboard Frontend / Backend Structure*
  (`docs/refactoring/subtasks/059_inventory_dashboard_frontend_backend_structure.md`).
  Provides the frozen structural map (component tree, LOC, feature-area boundaries) this
  migration walks.
- **Mandatory inventory gate before any runtime code change** (per the master index, the
  nine inventory subtasks that must precede runtime edits): **001, 002, 020, 036, 045,
  053, 059, 060, 067**. Since 072 *does* change runtime (frontend) code, all nine must be
  complete first. The directly relevant ones are **059** (structure), **060** (dashboard
  API contract inventory — confirms the endpoints/error regimes this UX layer renders
  against), and **067** (the Phase-6 inventory root).
- **Soft/adjacent (not blocking):** **021** (extract viz services) and **015** (refactor
  dashboard viz api services) may change backend error payloads later; this subtask reads
  whatever the client already returns and does not depend on their completion. **No other
  subtask depends on 072** (it is a leaf in the graph).

## 16. Risk Level

**Risk: Low–Medium.** · **Runtime code change: Yes** (frontend TypeScript/React + CSS +
i18n; no backend `.py`).

Low because the change is mechanical, additive, frontend-only, and each page is
independently revertible with full test coverage available (`typecheck` + `build` +
Vitest). The Medium edge comes from touching ~20 components (surface area for visual
regressions) and from the i18n lockstep requirement — a forgotten `ja.ts`/`zh.ts` key
fails `check_i18n_js.py` in CI. Both are caught by the Section 12 gate before merge.

## 17. Notes for Implementer

- **Start from the reference model.** `components/PaperBench/PaperRegistryPage.tsx`
  (147 lines) already shows the target pattern end-to-end: `useApi` at `:37`, then
  loading (`:79`), error (`:80-84`), empty (`:85-87`). Build `LoadingState`/`EmptyState`/
  `ErrorState` so this file becomes three shared-component calls, then replicate outward.
- **Do not "fix" the two API error regimes.** `get`/`post` throw; `pbGet`/`pbPost` return
  `{error}`. `ErrorState` takes a plain `message: string`, so both regimes feed it — no
  need to unify the client here (that is 060/021 territory).
- **The `--danger` token is a real bug, not a style preference.** It is undefined in
  `styles/tokens.css`; `WorkflowPage.tsx:394` silently renders non-red error text.
  Standardize on `--red` via `ErrorState`; do not add a new token.
- **Keep the ErrorBoundary developer stack.** `main.tsx:17-25` intentionally prints the
  stack for debugging. You may add a translated headline, but preserve the stack; its
  removal is a separate (security/raw-debug) subtask.
- **i18n edits are lockstep.** Add each new key to `en.ts`, `ja.ts`, `zh.ts` in the same
  commit; run `python scripts/docs/check_i18n_js.py` locally before pushing. The current
  gap (444 vs 441) means three keys already drift — do not widen it; if convenient, close
  it.
- **Prefer reusing existing keys** (`loading`, `no_data`, `error_prefix`, `cfg_retry`,
  and the `*_empty` family) before minting new ones, to keep the i18n surface small.
- **CSS: reuse, don't invent.** `.empty-state`/`.empty-icon`/`.spinner` already exist in
  `styles/components.css`; only add a single `.error-state` if it removes inline styles.
  Use `var(--red)`/`var(--muted)` — never hardcoded hex.
- **Landing strategy:** ship the three components + i18n keys + tests first (green
  baseline), then migrate pages in small commits (Experiments → Home → Results → Tree →
  Wizard → Workflow → PaperBench), running `npm run typecheck` after each.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **072** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
