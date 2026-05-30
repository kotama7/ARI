# Frontend State / Hooks / Types Cleanup (requirement 04)

Task-control note from `04_frontend_state_hooks_types_cleanup.md`. Captured
2026-05-30. Backed by a 3-agent audit workflow.

## Audit findings

- **`AppContext.tsx` is already well-scoped.** It holds `state` (AppState),
  `nodesData` (WS-or-poll merge), `checkpoints` (server-state), `currentPage`
  (UI state), and `wsConnected`. No over-broad/mixed global state to split out;
  no change made (avoid unrequested churn). Its inline 5s `/state` poll
  (`STATE_POLL_MS`) could become a `usePolling` hook later, but that touches the
  WS/poll merge and is **deferred** (medium risk, no clear behavior win).
- **`useApi` hook existed with ZERO consumers** (dead code). The clean win was to
  adopt it where components hand-rolled the same `{data,loading,error}` +
  mount-fetch boilerplate it provides. No extension of `useApi` was needed (kept
  its exact 1-arg fetcher signature + 4-key return).
- **`types/index.ts` has ZERO `any`** (already uses `unknown`). The only safe,
  zero-ripple improvement was a documentary `ReviewDecision` alias.

## Changes made (this PR)

1. `components/PaperBench/PaperRegistryPage.tsx` → adopt `useApi`. The audit's
   single clean semantic twin: loading init true, setError(null)+setLoading(true)
   on each fetch, error = thrown message, mount-only. `refresh` aliased to the
   returned `refetch` so the refresh button and delete-then-refetch path are
   byte-identical. `papers` kept typed as `PaperEntry[]`. Adversarially verified
   (6 checks) behaviorPreserved=true.
2. `types/index.ts` → extract `ReviewReport.decision`'s inline union into a named
   `export type ReviewDecision = ... | string`. The trailing `| string` is kept,
   so the resolved type stays exactly `string` and every `decision: string`
   consumer (e.g. `resultSections.tsx` `report.decision === 'accept'`) compiles
   unchanged — purely documentary (readability/autocomplete).

## Deferred (out of scope / would change behavior)

- `ExperimentsPage.tsx` — audit verdict `safeToAdoptSharedHook:false`. It builds
  a `subById` **Record** keyed by `run_id` from `sub_experiments` (not a flat
  array) and deliberately swallows fetch errors with **no loading/error UI** (the
  lineage column just degrades to empty). `useApi`'s single-data + surfaced-error
  contract would change observable behavior. Left unchanged.
- `MonitorPage.tsx` — `setInterval` polling + error-swallowing; `useApi` is
  mount-only and surfaces errors. Defer (needs a `useApi` polling option, or its
  req-15 decomposition).
- `SettingsPage.tsx` — multi-endpoint load + save/dirty/saving sharing the error
  slot; not a clean `useApi` fit. Defer to its req-15 decomposition.
- `PaperBench/results/ResultsView.tsx` — dual-fetch + `setInterval` poll keyed on
  job status. Defer.
- Extracting AppContext's inline 5s `/state` poll to a `usePolling` hook —
  deferred (touches the WS/poll merge; no clear behavior win).

These are recorded in req 04 §12 follow-up and overlap with req 15.

## Checks (2026-05-30)

`npm run typecheck` 11 total / **0 non-test** (only pre-existing `__tests__`
jest-dom errors); `npm run build` exit 0; `npm test -- --run` 4 passed / 2 failed
(pre-existing brittle PaperBench tests), 6 total, 0 resolve errors. No regression.
