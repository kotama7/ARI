# GUI-ADR-01: router and server-state library

Cited in source and tests as `ADR-01`. Accepted 2026-07-23 for the GUI refresh
program; not superseded, and it supersedes nothing.

Decision: keep the hand-rolled hash router and adopt `@tanstack/react-query`
v5 for server state. `ari-core/ari/viz/frontend/src/app/routeRegistry.ts` is
the single source a route exists in; `App.tsx` derives its lazy page map and
dispatch from it and `components/Layout/Sidebar.tsx` derives its nav table
from `navItems()`. The query cache owns fetch dedup, retry, stale time and
invalidation, under the ownership split that server state lives in the cache,
navigation state in the URL, form drafts in the feature, durable preferences
in the browser store, and ephemeral UI in the component.

Adopting react-router was rejected: the registry had already shipped with
parity tests, so replacement bought nothing and would have handed the frozen
`#/<path>` deployment contract to a second owner. Hand-rolling the query cache
was rejected as re-inventing cache invalidation, in-flight dedup and abort
propagation.

Consequences accepted: exactly one new runtime dependency, paid for out of the
bundle budget; routes may be added only through the registry, where the parity
and render-baseline tests see them; and hand-written fetch hooks migrate into
the cache rather than accumulating a second cache beside it.

Verified against the tree: no `react-router` in `src/`, `package.json` or
`package-lock.json`; `@tanstack/react-query ^5.101.4` is a dependency;
`src/app/queryClient.ts` sets `staleTime` 5000 ms, `retry` 1,
`refetchOnWindowFocus` false, and `App.tsx` wraps the shell in
`QueryClientProvider`. The registry has grown well past the 13 routes this
record was written against: it now holds 21 routes and an 18-entry nav table,
the 10 frozen legacy entries plus the v2-only ones.

Where the code diverges from the record. The bundle cost was estimated at
~13 KiB gzip; the measured main-chunk growth was +9.3 (70.52 → 79.82 KiB
gzip against a 69.91 pre-program baseline), and the budget is now enforced
rather than narrated, by `scripts/check_bundle_budget.py` against
`scripts/quality/check_bundle_budget.yaml` (entry ≤ 100, route ≤ 150, shared
≤ 150, total ≤ 600 KiB gzip; `SettingsPage` and `WizardPage` ≤ 50 each).
Abort propagation was a stated reason to buy rather than build, but no
`AbortController` or `AbortSignal` exists anywhere in the frontend source:
superseded queries have their results discarded, the request is not cancelled.
The migration off hand-written fetch is unfinished — `src/hooks/useApi.ts`
still backs `components/PaperBench/PaperRegistryPage.tsx`; it holds per-mount
state rather than a cache, so the no-second-cache consequence still holds.
The per-entity stale times and freshness labels the state-ownership plan asked
for were not built: the client default is the whole freshness policy and no
query overrides it.

The permanent description of both halves is `docs/concepts/gui_architecture.md`,
sections "2. The route registry is the only place a route exists" and
"4. Server state lives in a cache, keyed by run". Owning tests:
`src/app/__tests__/routeRegistry.test.tsx` (the 21 routes, nav order, alias and
query-string resolution), `src/__tests__/routeNavParity.test.tsx` (nav table
pinned literal, plus floors of 12 routes and 10 nav entries),
`src/__tests__/routeRenderBaseline.test.tsx` (every one of the 18 nav-reachable
routes mounts), and `scripts/tests/test_check_bundle_budget.py`.
