# Subtask 073: Add Dashboard UX Regression Checks

> Phase 6: Dashboard UX
> Classification: **KEEP** (net-new tooling + tests; guards UX invariants, redefines no runtime code)
> Inventory gate: **059** (`inventory_dashboard_frontend_backend_structure`)
> Coordinates with: **067** (visible-settings inventory), **068/069** (IA / progressive-disclosure design), **070** (settings-panel refactor), **071** (developer mode + dangerous-op hardening), **072** (empty/loading/error states), and the quality-tooling lane **025/031/032** + workflow track **012/046**
> Runtime code change: **NO**

This document is a PLANNING artifact. It changes **no runtime code**. It is
self-contained: a fresh coding session should be able to execute it after
reading Sections 5, 7, 8, 9, 10, and 12. All paths are absolute-from-repo-root
(`/home/t-kotama/workplace/ARI`). Line counts verified 2026-07-01 (`wc -l`).

---

## 1. Goal

Add a **regression-check harness** that locks in the dashboard-UX invariants
established by the Phase 6 siblings (067–072) and prevents silent UX regressions,
without touching any runtime view-layer code. Two deliverables:

1. **`scripts/check_dashboard_ux.py`** — a net-new, deterministic,
   stdlib-only **static linter** (the design-only checker named in
   `docs/refactoring/014_dashboard_ux_refactoring_plan.md:281` §14 and the master
   plan `docs/refactoring/000_master_refactoring_plan.md:222` ST-12-6). It covers
   the two gaps that no existing gate covers:
   - **React i18n key-set parity** across
     `ari-core/ari/viz/frontend/src/i18n/{en,ja,zh}.ts`. The only existing i18n
     gate, `scripts/docs/check_i18n_js.py`, targets the **landing-page JS**
     (`docs/i18n/landing.{en,ja,zh}.js`) whose keys are *quoted*
     (`'key': '...'`, regex `^\s*'([^']+)'\s*:` at `check_i18n_js.py:42`). The
     React dictionaries use **unquoted identifier keys** (`nav_home: 'Home'`,
     `en.ts:3`), so that regex matches nothing there — the React locales are
     currently **unguarded**.
   - **Always-on raw/debug exposure** — a warning-first inventory of raw dumps
     and unconfirmed dangerous UI (Raw JSON tabs, `dangerouslySetInnerHTML`,
     `JSON.stringify` page dumps, env-secret readback, hardcoded confirmation
     bypass), so 070/071's hardening can be regression-gated.

2. **Vitest regression tests** under
   `ari-core/ari/viz/frontend/src/**/__tests__/` that codify the always-true UX
   invariants (i18n key parity mirrored in TS; the `/api/settings` 24-key POST
   shape + all 9 Settings sections; route↔sidebar parity) and stub the
   sibling-gated invariants (developer-mode gating, ARIA tab semantics) as
   `it.todo`/`.skip` placeholders to be enabled when 070/071/072 land.

The checker and tests **guard**, never **redefine**, the dashboard UX contract.
No endpoint, JSON key, i18n string, component, route, or directory is added,
renamed, or removed by this subtask.

## 2. Background

**Dashboard frontend stack (verified).** Vite 5 + React 18.3 + TypeScript 5.5,
ESM; tests via **Vitest 2 + Testing Library + jsdom**
(`ari-core/ari/viz/frontend/package.json:14-32`; scripts `dev/build/typecheck/
preview/test` at `:6-13`). No CSS framework, no react-router (hand-rolled hash
router, `App.tsx:32-56`), single React Context for state (`context/AppContext.tsx`).
Vitest config globs `src/**/__tests__/**/*.test.tsx` + `src/**/*.test.tsx`, env
`jsdom`, setup `vitest.setup.ts`
(`ari-core/ari/viz/frontend/vitest.config.ts:14-23`). Today the **only** frontend
tests are `src/components/PaperBench/__tests__/{PaperBenchWizard,PaperImportDialog}.test.tsx`
— there is no i18n test, no settings test, no route-parity test.

**i18n contract.** `src/i18n/index.ts` merges three flat dictionaries
(`en, ja, zh`, `index.ts:2-6`) and resolves `t(key)` with `en` fallback then the
raw key (`index.ts:13-19`). Default language is `ja` (`index.ts:10`). The three
dictionaries are **not** in key parity today: `en.ts` 444 lines vs `ja.ts`/`zh.ts`
441 each, and a rough key probe (`grep -cE "^\s*[A-Za-z0-9_]+:\s*'"`) returns
387/391/391 — i.e. the sets diverge in **both** directions (some keys only in
`en`, some only in `ja`/`zh`). A missing key renders as a blank/fallback string
in the untranslated locale (the exact failure `check_i18n_js.py` was built to
prevent for the landing page). Nothing currently catches this drift for the
React app.

**Raw/dangerous UI (verified, from the 059 inventory).** Several surfaces expose
raw internals unconditionally today:

- **DetailPanel `{ } Raw` tab** dumps full node JSON
  (`Tree/DetailPanel.tsx:364` tab button, `:410-419` `JSON.stringify(node,null,2)`).
- **`dangerouslySetInnerHTML`** in `Wizard/StepScope.tsx:137` (template-string
  `summaryHtml`).
- **Raw `JSON.stringify` dumps** in `Results/resultSections.tsx`,
  `Monitor/monitorSections.tsx`, `Tree/DetailPanelTabs/TraceTab.tsx`,
  `Experiments/ExperimentsPage.tsx`, `Results/resultHelpers.ts`,
  `Tree/DetailPanel.tsx`.
- **Env-secret readback**: `getEnvKeys()` calls `/api/env-keys`
  (`services/api.ts:383`), returning actual secret values to the browser.
- **Hardcoded confirmation bypass**: `gpuMonitorAction()` always sends
  `{ action, confirmed: true }` (`services/api.ts:585`), so the SLURM
  auto-resubmit's only guard is a client-side `window.confirm`.

These are the exact items 070 (developer mode) and 071 (dangerous-op hardening)
will gate; 073 provides the machine check that (a) inventories them today and
(b) fails when a **new** always-on raw dump is added after the hardening lands.

**Existing tooling that this does NOT duplicate.**
`scripts/docs/check_i18n_js.py` (landing JS only, different key syntax);
`report/scripts/check_i18n.py` (Gate 6, report i18n, not React);
`scripts/docs/check_site_i18n.py` (HTML site). None touch
`ari-core/ari/viz/frontend/src/i18n/*.ts`. A repo-wide `grep` confirms
**`scripts/check_dashboard_ux.py` and `scripts/quality/` do not exist** — both
are net-new.

Note: the `sonfigs/` directory referenced in some upstream prompts **does not
exist** and is irrelevant here; this subtask touches only
`ari-core/ari/viz/frontend/` (tests) and `scripts/` (checker).

## 3. Scope

This subtask creates only **tooling + tests + config + docs**; it modifies **no
runtime module** and does not alter the production bundle (Vitest test files are
excluded from `vite build`).

In scope:

- **New** `scripts/check_dashboard_ux.py` — the static UX linter (Section 7),
  in the `scripts/`-family house style.
- **New** `scripts/quality/` config directory (does **not** exist today) holding
  `check_dashboard_ux.yaml` (target globs, i18n file set, raw-dump patterns) and
  `check_dashboard_ux.allow.yaml` (the **baseline** of currently-known raw dumps,
  dangerous ops, and pre-existing i18n drift so the first run is
  clean-or-warning), plus a per-directory `README.md` (tracked by
  `scripts/readme_sync.py`). If a sibling checker subtask (e.g. 030) already
  created `scripts/quality/` + `_common.py`, **reuse** them.
- **New** `ari-core/tests/test_check_dashboard_ux.py` — Python unit tests for the
  checker's extraction/parity/pattern logic (fixture-based; no live server, no
  node).
- **New** Vitest regression tests under
  `ari-core/ari/viz/frontend/src/**/__tests__/` (Section 7.4): i18n parity,
  Settings field-preservation, route↔nav parity, plus `it.todo`/`.skip`
  placeholders for developer-mode gating and ARIA tab semantics.
- Read-only *inputs*: `src/i18n/{en,ja,zh}.ts`, `src/App.tsx`,
  `Layout/Sidebar.tsx`, `Settings/SettingsPage.tsx`, `services/api.ts`, and the
  raw-dump files listed in Section 2.

Out of scope (delegated / deferred):

- **Any** edit to `src/i18n/*.ts` content (adding/translating keys). Closing the
  **pre-existing** key drift is a data-only frontend edit and therefore a
  runtime-touching change owned by whichever sibling (067–072) introduces or
  needs those strings, or a tiny follow-up. 073 **records** the current drift in
  the baseline allowlist and gates against **new** drift — it does not itself
  translate strings (keeps Runtime = No; see Section 4, 16).
- **Any** hardening of the raw/dangerous surfaces (gating the Raw tab, fixing the
  `confirmed:true` hardcode, hiding `/api/env-keys`) — that is 070 (`localStorage`
  developer-mode gate) and 071 (typed confirmations + backend audit). 073 only
  detects.
- **Wiring the checker/tests into `.github/workflows/`.** CI integration is
  additive and belongs to the workflow track (`012_github_workflow_integration_
  plan.md` / subtask 046); 073 ships warning-first, not a blocking gate. `npm test`
  is already the frontend test entry point and needs no new job to run locally.
- Response-shape / endpoint-path reconciliation — owned by 065
  (`add_dashboard_contract_and_schema_tests`) and 030
  (`check_viz_api_schema.py`). 073 is UX/i18n/raw-dump scoped, orthogonal to
  those.

## 4. Non-Goals

- **NOT** editing any `src/i18n/*.ts` string, key, or translation; **NOT**
  auto-fixing the drift. 073 detects and baselines; the fix is delegated
  (Section 3).
- **NOT** modifying any React component, hook, context, route, endpoint, JSON
  key, or the `/api/settings` 24-key wire shape. The tests assert the current
  behavior; they do not change it.
- **NOT** gating, hiding, or removing the Raw tab, `dangerouslySetInnerHTML`,
  `/api/env-keys`, or the `confirmed:true` call — that is 070/071. 073 flags them
  as **REVIEW_REQUIRED** findings only.
- **NOT** introducing a new i18n runtime lib (react-i18next etc.), a CSS
  framework, react-router, or any new production dependency.
- **NOT** shelling out to `node`/`npm`/`pnpm` from the Python checker; it parses
  `*.ts` statically in Python to stay stdlib-only and deterministic (design
  principle P2). (`pnpm` is not installed; `npm` is used only by the separate
  Vitest suite.)
- **NOT** making any LLM or network call from the checker or tests.
- **NOT** reusing `check_i18n_js.py`'s `KEY_RE` verbatim — the React key syntax
  differs (unquoted identifiers) and the file set differs; only the union-diff /
  duplicate-detection **algorithm** is mirrored.
- **NOT** wiring anything into the 5 existing workflows.

## 5. Current Files / Directories to Inspect

Verified 2026-07-01. Line counts from `wc -l`.

Frontend inputs (`ari-core/ari/viz/frontend/`):

| Path | LOC | Relevance |
| --- | --- | --- |
| `src/i18n/en.ts` | 444 | English dictionary (unquoted identifier keys, `en.ts:3`). Parity source. |
| `src/i18n/ja.ts` | 441 | Japanese dictionary. Diverges from `en`. |
| `src/i18n/zh.ts` | 441 | Chinese dictionary. Diverges from `en`. |
| `src/i18n/index.ts` | 41 | `useI18n`/`useT`; merges `{en,ja,zh}`, `en`→key fallback (`:13-19`), default lang `ja` (`:10`). |
| `src/App.tsx` | ~120 | Hash router: `parseHash()` + `PAGE_MAP` (12 routes + 3 `paperbench/*` sub-routes), `App.tsx:32-56`; `new`→`wizard` alias. |
| `src/components/Layout/Sidebar.tsx` | — | `NAV_ITEMS` nav mirror (`:12-23`); omits `paperbench` (manual drift risk). `role="button"`+`tabIndex`+Enter keyboard pattern at `:141-145`. |
| `src/components/Settings/SettingsPage.tsx` | 1049 | 9 `<Card>` sections; Save posts a **flat 24-key** object (`:235-260`). Field list is the 067 invariant. |
| `src/components/Settings/settingsConstants.ts` | 86 | Hardcoded provider/model tables. |
| `src/services/api.ts` | 863 | `getEnvKeys` → `/api/env-keys` (`:383`); `gpuMonitorAction` sends `confirmed:true` (`:585`); `updateSettings` POST shape. |
| `src/components/Tree/DetailPanel.tsx` | 425 | `{ } Raw` tab (`:364`, `:410-419`). |
| `src/components/Wizard/StepScope.tsx` | — | `dangerouslySetInnerHTML` (`:137`). |
| `src/components/Monitor/GpuMonitor.tsx` | — | SLURM auto-resubmit UI (`window.confirm` only guard). |
| `src/components/{Results/resultSections.tsx, Monitor/monitorSections.tsx, Tree/DetailPanelTabs/TraceTab.tsx, Experiments/ExperimentsPage.tsx, Results/resultHelpers.ts}` | — | Raw `JSON.stringify` dumps (baseline entries). |
| `src/components/PaperBench/__tests__/{PaperBenchWizard,PaperImportDialog}.test.tsx` | — | The **only** existing FE tests; the test-authoring convention to copy. |
| `vitest.config.ts` | 23 | Test globs + jsdom + setup. |
| `vitest.setup.ts` | 41 | `@testing-library/jest-dom`, `cleanup`, `FakeEventSource`, default fetch stub. |
| `package.json` | — | `test: "vitest run"` (`:11`); deps minimal (react, react-dom, d3, reactflow). |

Convention references (house style to copy for the Python checker):

- `scripts/docs/check_i18n_js.py` (120 lines) — the **algorithm** to mirror:
  `keys_of` (`:45-51`), `duplicates` (`:54-61`), `parity_errors` (union-diff,
  `:68-88`), `--json` output, exit 1 on error. Uses `REPO_ROOT = parents[2]`
  (that is the `scripts/docs/` level — see below for the top-level level).
- `scripts/docs/check_doc_sources.py` (223 lines) — canonical checker shape:
  `#!/usr/bin/env python3`, docstring citing a design doc, `argparse` + `--json`,
  `Finding`-style object with `level` in `{error, warning, coverage}`,
  `SystemExit(2)` on missing PyYAML.
- `scripts/readme_sync.py:31` — `REPO_ROOT = Path(__file__).resolve().parents[1]`
  (the level a **top-level** `scripts/` checker uses; 073's checker lives at
  `scripts/`, so use `parents[1]`, not `parents[2]`).
- `docs/refactoring/subtasks/030_add_viz_api_schema_checker_script.md` — sibling
  checker plan (same `scripts/quality/` lane, `_common.py` reuse, warning-first
  rollout); copy its config/allowlist conventions.

Upstream planning inputs:

- `docs/refactoring/014_dashboard_ux_refactoring_plan.md:270-289` (§14 subtask
  table + guardrails), `:281` (the `check_dashboard_ux.py` design row), §13
  (accessibility/i18n acceptance items).
- `docs/refactoring/000_master_refactoring_plan.md:222` (ST-12-6: plan
  `check_dashboard_ux.py` + note the i18n drift).
- `docs/refactoring/007_subtask_index.md:120` (073 row: Phase 6, Low, dep 059,
  Runtime No, Inventory No), `:275-290` (Phase-6 cluster + 073 blurb),
  `:445-451` (059→073 edge).
- `docs/refactoring/009_quality_scripts_plan.md` — `scripts/quality/` placement,
  `_common.py`, `--json` schema, staged warning→error rollout.
- `docs/refactoring/010_contract_preservation_policy.md` — dashboard + i18n as
  preserved contracts.

## 6. Current Problems

Grounded, verified 2026-07-01:

1. **The React i18n locales are unguarded.** `check_i18n_js.py` only checks
   `docs/i18n/landing.*.js`; its quoted-key regex (`check_i18n_js.py:42`) matches
   **zero** keys in the unquoted-identifier React files. The three React
   dictionaries have already drifted (444/441/441 lines; ~387/391/391 keys), so a
   real, active drift exists with **no** machine gate — new UX strings added to
   `en` but not `ja`/`zh` (or vice-versa) render blank/fallback with no CI signal.

2. **Raw internals are exposed unconditionally with no regression gate.** The
   `{ } Raw` node-JSON tab (`DetailPanel.tsx:364,410-419`),
   `dangerouslySetInnerHTML` (`StepScope.tsx:137`), env-secret readback
   (`api.ts:383`), and six+ `JSON.stringify` page dumps ship on by default.
   Nothing prevents a seventh from being added, and once 070/071 gate the known
   ones, nothing stops a regression re-exposing them.

3. **Dangerous-op confirmation is bypassable and untested.** `gpuMonitorAction`
   hardcodes `confirmed:true` (`api.ts:585`); the SLURM auto-resubmit's only
   guard is a client `window.confirm`. There is no test pinning "a destructive
   action requires an explicit confirmation payload," so 071's fix could silently
   regress.

4. **UX invariants the Phase-6 refactors must preserve are unpinned.** The
   `/api/settings` **24-key** flat POST (`SettingsPage.tsx:235-260`) and the
   presence of all **9** Settings sections are the exact things 070's tabbed
   redesign must not break — but there is no test. Likewise the route↔`NAV_ITEMS`
   set (`App.tsx:32-56` vs `Sidebar.tsx:12-23`) drifts manually (Sidebar omits
   `paperbench`), and 067's route-registry work has no parity test to satisfy.

5. **Only PaperBench has FE tests.** The single `__tests__` directory
   (`PaperBench/__tests__/`) covers a wizard and an import dialog; core UX
   surfaces (i18n, Settings, routing) have zero coverage, so the Phase-6 churn
   (067–072) lands without a regression net.

## 7. Proposed Design / Policy

**Policy: a deterministic, standalone, warning-first static linter plus a
Vitest regression suite that pin the always-true dashboard-UX invariants and
baseline the known raw/dangerous surfaces — guarding, never redefining, the UX
contract.**

### 7.1 Placement and house style (Python checker)

- File: `scripts/check_dashboard_ux.py` (top level, alongside `readme_sync.py`),
  **not** under `scripts/docs/` (that family is docs/site scoped). Use
  `REPO_ROOT = Path(__file__).resolve().parents[1]` (matching `readme_sync.py:31`),
  **not** `parents[2]`.
- Shape: `#!/usr/bin/env python3`; module docstring citing
  `docs/refactoring/014_dashboard_ux_refactoring_plan.md §14` +
  `009_quality_scripts_plan.md` + this subtask; `argparse` + `--json`; **stdlib +
  PyYAML only** (guard the YAML import with `SystemExit(2)` exactly like
  `check_doc_sources.py:29-35`). No LLM, no network, no `node`/`npm`/`pnpm`.
- Config dir: `scripts/quality/` (new, or reuse 030's).
  `check_dashboard_ux.yaml` = i18n file set + target globs + raw-dump patterns;
  `check_dashboard_ux.allow.yaml` = the **baseline** (current known raw dumps,
  dangerous ops, and pre-existing i18n drift, each with a justification /
  owning-subtask note). Add `scripts/quality/README.md` (readme-sync tracked).
- Shared helpers: import from `scripts/quality/_common.py` if present (JSON-schema
  emitter, allowlist loader, Markdown writer); otherwise create a minimal one.
  The checker must run standalone.

### 7.2 CLI contract (matches 009 plan common contract)

```
scripts/check_dashboard_ux.py
  --frontend ari-core/ari/viz/frontend/src   # default target root
  --config   scripts/quality/check_dashboard_ux.yaml       # default
  --allow    scripts/quality/check_dashboard_ux.allow.yaml # baseline
  --json                        # machine-readable output (quality-suite schema)
  --warning-only                # never exit nonzero (rollout default)
  --fail-on-regression          # exit 1 only on NEW (non-baselined) finding
```

Exit convention (matches `scripts/docs/`): `0` = clean or `--warning-only`;
`1` = findings above threshold (i18n key drift not in baseline, or a new raw
dump under `--fail-on-regression`); `2` = usage/environment error (missing
PyYAML, missing target file).

### 7.3 Checks performed by `check_dashboard_ux.py`

**(A) React i18n key parity.** Parse `src/i18n/{en,ja,zh}.ts` with a
React-aware key regex — `^\s*([A-Za-z_$][\w$]*)\s*:` — that **skips** comment
lines (`//`), the `const X: Record<...> = {` header, and the closing brace.
Mirror `check_i18n_js.parity_errors`: compute the union of the three key sets;
report per-file **missing** keys and **duplicate** keys. Values are NOT compared
(a proper noun may read identically across locales). Pre-existing drift is listed
in the baseline allowlist so the initial run is warning-only; **new** divergence
fails under `--fail-on-regression`.

**(B) Always-on raw/debug exposure inventory (REVIEW_REQUIRED, warning-first).**
Static-grep the target tree for the patterns in `check_dashboard_ux.yaml`:
`dangerouslySetInnerHTML`, `JSON.stringify(` used in JSX/render context,
the literal `'{ } Raw'`/raw-tab markers, `getEnvKeys`/`/api/env-keys` call sites,
and a hardcoded `confirmed: true` in a destructive action call. Each hit is a
`warning`/`REVIEW_REQUIRED` finding with `file:line`. The current known hits
(Section 2) are seeded into the baseline so today's run is clean; a **new** hit
(a seventh raw dump, or a re-exposure after 070/071 gate the known ones) fails
under `--fail-on-regression`. The checker never edits these — hardening is 070/071.

**(C) (advisory) Route↔nav parity.** Optionally extract `PAGE_MAP` keys from
`App.tsx` and `NAV_ITEMS` from `Sidebar.tsx`; report routes with no nav entry
(minus an allowlist of intentionally-hidden routes such as `paperbench/*`
sub-routes). Advisory (`warning`) — the authoritative version of this invariant
lives in the Vitest test (7.4) which can import the actual modules.

### 7.4 Vitest regression suite (frontend `__tests__`)

New `*.test.tsx` files under `ari-core/ari/viz/frontend/src/**/__tests__/`,
following the `PaperBench/__tests__` convention (Testing Library + jsdom, run by
`npm test`). Author them in three tiers so the **059-only** hard gate holds
(no sibling merge required to keep the tree green):

- **Tier 1 — always-green invariants (ship enabled):**
  - `src/i18n/__tests__/parity.test.ts` — import `{ en, ja, zh }` from
    `../index`; assert the three `Object.keys(...)` sets are equal **modulo a
    `KNOWN_DRIFT` constant** seeded with today's diverging keys (so it is green
    now and any *new* divergence fails). This is the TS-native mirror of check (A).
  - `src/components/Settings/__tests__/SettingsContract.test.tsx` — render
    `SettingsPage`; assert all **9** section headings are present and that
    invoking Save posts an object with exactly the **24 keys**
    (mock `api.updateSettings`, assert `Object.keys(payload)`), pinning the 067
    invariant that 070 must preserve.
  - `src/__tests__/routeNavParity.test.ts` — import `PAGE_MAP`/`parseHash` (or
    the 067 route registry once it exists) and `NAV_ITEMS`; assert every
    user-navigable route has a nav entry or is in an explicit hidden-route
    allowlist. Encodes the drift risk in Problem #4 and gates 067.
- **Tier 2 — sibling-gated placeholders (ship as `it.todo`/`describe.skip` with a
  "un-skip when 07x merges" comment):**
  - Developer-mode gating: `{ } Raw` tab, raw-YAML editor, and env-key readback
    are **not** rendered when developer mode is off (enable when **070/071**
    land).
  - Dangerous-op confirmation: a destructive action (SLURM auto-resubmit) does
    **not** send `confirmed:true` without an explicit user confirmation (enable
    when **071** fixes `api.ts:585`).
  - ARIA tab semantics: Settings/DetailPanel tabs expose
    `role="tab"`/`role="tabpanel"`/`aria-selected` (enable when **068/069/070**
    add tab semantics).
  - Empty/loading/error state kit renders skeleton/empty/error components
    (enable when **072** lands).

Tier-2 placeholders keep the intent discoverable and reviewable without a red
suite; each names the sibling that un-skips it.

### 7.5 Output

- **Markdown** (default): a per-check summary (i18n parity table like
  `check_i18n_js`'s; raw-dump findings as `file:line — pattern`).
- **JSON** (`--json`): the quality-suite schema
  `{"checker","version","target","summary":{counts},"findings":[{id,severity,
  file,line,kind,message,allowlisted}]}` so the future `generate_quality_report`
  (subtask 031) can merge it.

### 7.6 Rollout

Warning-first (009 convention): ship with `--warning-only` behavior. The **i18n
new-divergence** class is the first promoted to hard failure once the
pre-existing drift is closed (by the delegated fix, Section 3); the raw-dump
class stays advisory behind the baseline until 070/071 gate the known instances.
Classification: **KEEP** (net-new tooling + tests). No runtime code is
`ADAPT`/`MERGE`/`MOVE_TO_LEGACY`/`DELETE_CANDIDATE` here; the raw/dangerous
surfaces are **REVIEW_REQUIRED** and owned by 070/071.

## 8. Concrete Work Items

Suggested order (author after 059 exists; coordinate Tier-1 tests with 067/070):

1. **Create `scripts/quality/`** (if not already created by 030) with
   `README.md` and, if absent, a minimal `_common.py`. Reuse if present.
2. **Write `scripts/check_dashboard_ux.py`** in the `check_doc_sources.py` house
   style: docstring citing 014 §14 + this subtask, `argparse` with Section-7.2
   flags, PyYAML `SystemExit(2)` guard, `REPO_ROOT = parents[1]`.
3. **Implement check (A) i18n parity**: React-aware `keys_of` (unquoted-identifier
   regex, comment/header/brace skipping), then mirror
   `check_i18n_js.parity_errors` union-diff + duplicate detection over
   `src/i18n/{en,ja,zh}.ts`.
4. **Implement check (B) raw-dump inventory**: pattern scan from
   `check_dashboard_ux.yaml`, emit `file:line` findings, apply the baseline
   allowlist.
5. **Implement check (C) route↔nav parity** (advisory) — optional, behind the
   allowlist.
6. **Author config + baseline**: `check_dashboard_ux.yaml` (i18n file set,
   patterns, target globs) and `check_dashboard_ux.allow.yaml` seeded with
   today's known raw dumps (Section 2), the `confirmed:true` site, and the
   current i18n drift keys — each with an owning-subtask note. Confirm the
   initial run is clean-or-warning.
7. **Emit Markdown + `--json`** per Section 7.5.
8. **Add `ari-core/tests/test_check_dashboard_ux.py`**: fixture-based unit tests
   for the React key regex (unquoted keys, comment lines ignored, duplicates
   caught), parity union-diff (synthetic missing key → finding; baselined key →
   suppressed), and raw-dump pattern matching (synthetic new
   `dangerouslySetInnerHTML` → finding). Include a smoke test that the checker
   runs clean/warning-only against the real tree at authoring time.
9. **Add the Vitest suite** (Section 7.4): Tier-1 tests enabled, Tier-2 as
   `it.todo`/`.skip`. Follow the `PaperBench/__tests__` convention; keep imports
   resolving under `vitest.config.ts`'s plugin set.
10. **Run the full gate set** (Section 12): `python -m compileall .`,
    `ruff check .`, `pytest -q`, and in `ari-core/ari/viz/frontend/`:
    `npm test` + `npm run build` (bundle unaffected). Confirm
    `scripts/readme_sync.py --check` passes after adding
    `scripts/quality/README.md`.
11. **Do NOT wire into any workflow** — leave CI wiring to 046/012 (warning-first).
    Note the intended job name in the checker docstring as a hand-off.

## 9. Files Expected to Change

Created by this subtask (all net-new; **no runtime module is modified**):

- **New** `scripts/check_dashboard_ux.py` — the static UX linter.
- **New** `scripts/quality/README.md` — per-directory README (readme-sync tracked).
- **New** `scripts/quality/check_dashboard_ux.yaml` — i18n set + patterns + globs.
- **New** `scripts/quality/check_dashboard_ux.allow.yaml` — raw-dump + i18n-drift
  baseline.
- **New (only if absent)** `scripts/quality/_common.py` — shared helpers (reuse
  030's if present).
- **New** `ari-core/tests/test_check_dashboard_ux.py` — Python unit tests.
- **New** `ari-core/ari/viz/frontend/src/i18n/__tests__/parity.test.ts`.
- **New** `ari-core/ari/viz/frontend/src/components/Settings/__tests__/SettingsContract.test.tsx`.
- **New** `ari-core/ari/viz/frontend/src/__tests__/routeNavParity.test.ts`.
- **New** Tier-2 placeholder `*.test.tsx` file(s) (developer-mode / dangerous-op /
  ARIA / state-kit) as `it.todo`/`.skip`.

Read-only inputs (must **not** be modified): `src/i18n/{en,ja,zh,index}.ts`,
`src/App.tsx`, `Layout/Sidebar.tsx`, `Settings/SettingsPage.tsx`,
`services/api.ts`, and the raw-dump files in Section 2.

This planning document:
`docs/refactoring/subtasks/073_add_dashboard_ux_regression_checks.md` (the only
file created by the planning phase).

## 10. Files / APIs That Must Not Be Broken

- **`/api/settings` 24-key flat POST + the `Settings` type** — the
  `SettingsContract.test.tsx` asserts the current shape; it must not change it,
  and 070's redesign must keep the test green. (`SettingsPage.tsx:235-260`.)
- **i18n runtime contract** — `useI18n`/`useT`, the `{en,ja,zh}` merge, and the
  `en`→key fallback (`index.ts:13-19`) are untouched; the checker/tests only read
  the dictionaries. No key is renamed or removed.
- **Dashboard REST + WS contract** — every path/method/JSON-key consumed by
  `services/api.ts` (863); the tests mock these, they do not change them. The
  `/api/env-keys` and `/api/gpu-monitor` endpoints are read-only inputs (their
  UX exposure is 070/071's concern, not this subtask's).
- **`ari.public.*`** stable Python API, **CLI `ari`** (`ari.cli:app`), **MCP tool
  contracts** of the 14 `ari-skill-*` servers, **checkpoint/output/config
  formats** — all untouched (the checker parses files statically; the tests are
  frontend-only).
- **Scripts called by `.github/workflows`** — the 5 existing workflows and their
  scripts are unchanged; this checker/tests are additive and **not** wired into
  CI here. `refactor-guards.yml` must stay green (no new `~/.ari/` refs, no
  `$HOME/.ari/` writes).
- **Existing gates** `scripts/docs/check_i18n_js.py`, `report/scripts/check_i18n.py`,
  and the `PaperBench/__tests__` suite — not modified; the new checker/tests cover
  a different surface (React i18n + UX regressions).

## 11. Compatibility Constraints

- **Read-only guard.** The checker never writes to any runtime file; the Vitest
  tests render/inspect components without mutating them. Any drift surfaced is
  fixed by the owning sibling (067/070/071/072) or the delegated i18n fix, not by
  this tooling.
- **Determinism (P2).** Python checker is stdlib + PyYAML only; no LLM, no
  network, no `node`/`npm`/`pnpm`. Same inputs → same output, safe as a future CI
  gate.
- **059-only hard gate honored.** Tier-1 tests assert invariants **true today**;
  Tier-2 tests are `it.todo`/`.skip` until their sibling lands. The i18n parity
  gate ships **warning-first** with the pre-existing drift baselined, so a clean
  tree at authoring time stays green without requiring 067–072 to be merged first.
- **No i18n content edits.** Closing the pre-existing key drift touches
  `src/i18n/*.ts` (a runtime frontend artifact) and is therefore delegated
  (Section 3); 073 keeps Runtime = No by baselining, not translating.
- **No "deprecated" for internal code.** A flagged raw dump is a
  "REVIEW_REQUIRED candidate for developer-mode gating," not "deprecated" — that
  term is reserved for external contracts (dashboard API, CLI, MCP, public
  import paths).
- **Warning-first rollout.** Ship non-blocking; promote the i18n
  new-divergence class to a hard gate only after the pre-existing drift is closed
  (Section 7.6). Do not fail CI on day one.
- **Bundle-neutral.** Vitest `*.test.tsx` files are excluded from `vite build`
  (they live in `__tests__`/`*.test.tsx`, not imported by app code), so the
  production bundle is byte-unaffected.

## 12. Tests to Run

From repo root `/home/t-kotama/workplace/ARI` (editable installs already set up
by `setup.sh`: `ari-skill-memory` then `ari-core`):

```bash
python -m compileall .          # full syntax gate (includes the new checker + test)
ruff check .                    # lint (ruff IS available; radon is NOT)
pytest -q                       # full suite (must stay green)
pytest -q ari-core/tests/test_check_dashboard_ux.py   # tight loop for the checker
```

Frontend (run inside `ari-core/ari/viz/frontend/`; `npm`, no `pnpm`):

```bash
npm test            # Vitest run — Tier-1 regression tests must pass; Tier-2 are todo/skip
npm run build       # vite build — must succeed; bundle unchanged (test files excluded)
npm run typecheck   # tsc --noEmit — new .test.tsx files must typecheck
```

Direct exercise of the new checker (all three exit paths):

```bash
python scripts/check_dashboard_ux.py --json             # clean/warning JSON
python scripts/check_dashboard_ux.py --warning-only      # never nonzero (rollout mode)
python scripts/check_dashboard_ux.py --fail-on-regression  # nonzero only on NEW drift/dump
```

Also confirm `scripts/readme_sync.py --check` passes after adding
`scripts/quality/README.md`, and that `.github/workflows/refactor-guards.yml`
stays green. Run `scripts/run_all_tests.sh` for CI parity if convenient (it runs
each skill's pytest; unaffected here).

## 13. Acceptance Criteria

1. `python -m compileall .` and `ruff check .` pass with no new violations; the
   new checker and Python test are lint-clean.
2. `pytest -q` passes, including `test_check_dashboard_ux.py`; no existing test
   regresses.
3. In `ari-core/ari/viz/frontend/`, `npm test`, `npm run build`, and
   `npm run typecheck` all succeed; Tier-1 regression tests pass and Tier-2 are
   `it.todo`/`.skip` (documented, not failing).
4. `scripts/check_dashboard_ux.py` exists at the top level with the
   `check_doc_sources.py` house style (shebang, docstring citing 014 §14 + this
   subtask, `argparse` + `--json`, PyYAML `SystemExit(2)` guard,
   `REPO_ROOT = parents[1]`), and runs with **no LLM/network/node/npm/pnpm**
   dependency.
5. Running the checker against the real tree is **clean or warning-only** at
   authoring time: the pre-existing i18n drift and the known raw dumps are
   baselined; **zero** new (non-baselined) findings.
6. The i18n check parses the **unquoted-identifier** React key syntax correctly
   (unit-tested: keys extracted, comment/header/brace lines ignored, duplicates
   caught) — proving it fills the gap `check_i18n_js.py` cannot cover.
7. `SettingsContract.test.tsx` asserts the **24-key** POST shape and **9**
   Settings sections; `routeNavParity.test.ts` asserts route↔nav coverage with an
   explicit hidden-route allowlist; `i18n/__tests__/parity.test.ts` mirrors the
   Python parity check with a `KNOWN_DRIFT` allowlist.
8. `scripts/quality/README.md` exists and `scripts/readme_sync.py --check`
   passes; `--json` conforms to the quality-suite schema.
9. The checker/tests are **not** wired into any `.github/workflows/*.yml`; the 5
   existing workflows are unchanged.
10. **No runtime file** under `ari-core/ari/viz/frontend/src/` (components, hooks,
    context, `i18n/*.ts`, `services/api.ts`) or elsewhere in `ari-core/ari/` was
    modified.

## 14. Rollback Plan

- The subtask adds only new tooling/config/test files and touches no runtime
  code, so rollback is a `git revert`/`git rm` of the added files
  (`scripts/check_dashboard_ux.py`, `scripts/quality/check_dashboard_ux.*`,
  `scripts/quality/README.md` if newly added, `ari-core/tests/test_check_dashboard_ux.py`,
  and the new `frontend/src/**/__tests__/*.test.ts(x)` files). Nothing else
  references them.
- Because the checker/tests are **not** wired into CI in this subtask, reverting
  cannot break any existing workflow or gate. `npm test`/`vite build` behave
  identically after removal (the new tests are additive).
- If `scripts/quality/_common.py` was created here and a sibling checker later
  depends on it, leave it on revert (shared). No data/format migration is
  involved; no i18n content was changed to undo.

## 15. Dependencies

Consistent with the provided DEPENDENCY GRAPH (edge `059 -> 073`) and
`docs/refactoring/007_subtask_index.md:120,275-290,445-451`.

- **Hard predecessor (gate): 059** `inventory_dashboard_frontend_backend_structure`.
  The graph lists `059 -> 067..073`; 059 supplies the verified FE/BE structure
  (stack, i18n layout, component map, raw-dump inventory) that this subtask's
  patterns and tests target. It is the **only** hard predecessor.
- **Cross-cutting inventory gate.** The master rule "inventory subtasks MUST
  precede any runtime code change" lists **001, 002, 020, 036, 045, 053, 059,
  060, 067**. 073 itself changes **no** runtime code, so it is not bound by all of
  these; its structural inventory is **059** (and **067** for the settings-field
  set that Tier-1 asserts).
- **Coordinates with (siblings, all gated by 059):**
  - **067** `inventory_dashboard_visible_settings` — supplies the authoritative
    9-section / 24-key settings inventory that `SettingsContract.test.tsx` pins.
  - **068/069** `define_dashboard_information_architecture` /
    `design_dashboard_progressive_disclosure` — define the tab/disclosure model
    the Tier-2 ARIA test targets.
  - **070** `refactor_dashboard_settings_panel` — must keep
    `SettingsContract.test.tsx` green; un-skips the developer-mode gating test.
  - **071** `add_dashboard_developer_mode` / dangerous-op hardening — resolves the
    `confirmed:true` REVIEW_REQUIRED finding and un-skips the dangerous-op test.
  - **072** `improve_dashboard_empty_loading_error_states` — un-skips the
    state-kit test.
  073 is best **landed after (or alongside) 070–072** so its Tier-2 tests can be
  enabled, but the graph hard-gates only on **059** (Tier-1 + the checker ship
  independently, warning-first).
- **Adjacent tooling lane:** **025** (`add_complexity_checker_script`), **030**
  (`check_viz_api_schema.py`, same `scripts/quality/` + `_common.py` lane),
  **031** (`generate_quality_report`, consumes `--json`), **032**
  (`add_quality_script_ci_plan`). 073 reuses 030's `scripts/quality/` scaffolding
  if it landed first; either may create `_common.py`.
- **Contract-test sibling:** **065** `add_dashboard_contract_and_schema_tests`
  (Phase 5) — the endpoint/DTO-shape counterpart to 073's UX/i18n checks;
  orthogonal, no ordering dependency.
- **Downstream:** the workflow track
  (`012_github_workflow_integration_plan.md` / subtask **046**) wires the checker
  into CI warning-first; the drift-fix follow-up (Section 3) closes the i18n
  baseline. Neither blocks 073 from shipping.

## 16. Risk Level

- **Does this subtask change runtime code? NO.** It adds a standalone Python
  linter (`scripts/check_dashboard_ux.py`), its config/baseline under
  `scripts/quality/`, an optional `_common.py`, one Python test, and additive
  Vitest `*.test.tsx` files under `frontend/src/**/__tests__/`. It modifies **no**
  React component/hook/context, **no** `i18n/*.ts` content, **no** endpoint or
  JSON shape, **no** prompt/config/workflow, and **no** directory name. Vitest
  files are excluded from `vite build`, so the production bundle is unaffected.
  (This matches `007_subtask_index.md:120`: Runtime = No, Inventory = No.)
- **Risk: LOW.** Failure modes: (a) a fragile TS parser mis-reading the unquoted
  React key syntax or template-literal values → false i18n findings — mitigated
  by unit tests, the baseline allowlist, and warning-first rollout, and bounded
  because the checker cannot alter runtime behavior; (b) Tier-1 tests being too
  strict and going red against today's tree — mitigated by the `KNOWN_DRIFT` /
  hidden-route allowlists that make them green now while catching *new* drift;
  (c) Tier-2 tests referencing behavior that does not exist yet — mitigated by
  shipping them as `it.todo`/`.skip` tied to the un-skipping sibling. Since
  nothing is wired into CI here, a bug cannot block the pipeline.

## 17. Notes for Implementer

- **Do not edit `i18n/*.ts` content.** Adding/translating keys is a runtime
  frontend change owned by the sibling that introduces the strings (or a tiny
  follow-up). 073 **baselines** today's drift and gates **new** drift only —
  that is what keeps this subtask Runtime = No. If you feel tempted to "just fix
  the three keys," stop: that belongs to 070/072 or a dedicated data-only PR.
- **The React key syntax is NOT the landing-JS syntax.** `check_i18n_js.py:42`
  matches `'key':` (quoted); React files use `nav_home: 'Home'` (unquoted
  identifier, `en.ts:3`). Use `^\s*([A-Za-z_$][\w$]*)\s*:` and explicitly skip
  `//` comment lines, the `const ... = {` header, and the closing `};`. Reuse
  `check_i18n_js`'s **algorithm** (`parity_errors` union-diff + `duplicates`),
  not its regex.
- **Seed the baseline, do not fix the findings.** Today's known raw dumps —
  `Tree/DetailPanel.tsx:364,410-419` (Raw tab), `Wizard/StepScope.tsx:137`
  (`dangerouslySetInnerHTML`), `services/api.ts:383` (`/api/env-keys`),
  `services/api.ts:585` (`confirmed:true`), and the `JSON.stringify` dumps in
  `Results/resultSections.tsx`, `Monitor/monitorSections.tsx`,
  `Tree/DetailPanelTabs/TraceTab.tsx`, `Experiments/ExperimentsPage.tsx`,
  `Results/resultHelpers.ts` — go into `check_dashboard_ux.allow.yaml` with an
  owning-subtask note (070/071). Never "fix" one by editing a component.
- **Match the `scripts/docs/` house style exactly.** Copy the scaffolding of
  `check_doc_sources.py`: `#!/usr/bin/env python3`, docstring citing the design
  doc, `argparse` + `--json`, a `Finding`-style object with `level`,
  `SystemExit(2)` on missing PyYAML, exit 1 on error. Use
  `REPO_ROOT = Path(__file__).resolve().parents[1]` (top-level `scripts/`, per
  `readme_sync.py:31`), **not** `parents[2]` (the `scripts/docs/` level).
- **Add `scripts/quality/README.md`** so `readme_sync.py --check` stays green;
  list the config + allowlist + `_common.py`. If 030 already created
  `scripts/quality/`, extend its README instead of duplicating.
- **Vitest, not node from Python.** The Python checker must never shell out to
  `node`/`npm`/`pnpm` (P2 determinism; `pnpm` is not installed). The behavioral
  invariants that need real rendering live in the Vitest suite, run by
  `npm test`, following the `PaperBench/__tests__` convention and
  `vitest.setup.ts` (jsdom, `@testing-library/jest-dom`, `FakeEventSource`,
  default fetch stub).
- **Keep Tier-2 tests honest.** Author developer-mode / dangerous-op / ARIA /
  state-kit tests as `it.todo` or `describe.skip` with a one-line comment naming
  the sibling that un-skips them (070/071/072). Do not assert behavior that does
  not exist yet — that would make the suite red on a clean tree and violate the
  059-only hard gate.
- **Do not wire CI here.** The workflow-integration subtask (046) owns adding the
  job (warning-first). Note the intended `.github/workflows` job name in the
  checker docstring as a hand-off, but create/edit no `*.yml`.
- **This checker guards, does not redefine, the contract.** The React i18n
  dictionaries and the dashboard UX are preserved surfaces
  (`010_contract_preservation_policy.md`); "deprecated" is reserved for external
  contracts, not for a raw dump the checker merely flags.
- **The "sonfigs" directory does not exist** and is irrelevant here. This subtask
  touches only `scripts/` (checker + config) and `ari-core/ari/viz/frontend/src/
  **/__tests__/` + `ari-core/tests/` (tests).

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **073** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
