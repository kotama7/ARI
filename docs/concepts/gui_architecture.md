---
sources:
  - path: ari-core/ari/viz/frontend/src/app/routeRegistry.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/App.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/Layout/Sidebar.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/app/queryClient.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/hooks/useV1.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/hooks/useRunEvents.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/shared/realtime/eventStream.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/services/api/client.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/services/api/v1.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/context/AppContext.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/hooks/useWebSocket.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/ConfigStudio/ConfigStudioPage.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/Settings/SettingsPage.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/services/api/workflow.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/package.json
    role: config
  - path: ari-core/ari/viz/frontend/src/main.tsx
    role: implementation
  - path: ari-core/ari/viz/routes.py
    role: implementation
  - path: ari-core/ari/viz/auth.py
    role: implementation
  - path: ari-core/ari/viz/server.py
    role: implementation
  - path: ari-core/ari/viz/health.py
    role: implementation
  - path: ari-core/ari/viz/api_capabilities.py
    role: implementation
  - path: ari-core/ari/viz/v1/router.py
    role: implementation
  - path: ari-core/ari/viz/v1/queries.py
    role: implementation
  - path: ari-core/ari/viz/v1/results.py
    role: implementation
  - path: ari-core/ari/viz/v1/rqgm.py
    role: implementation
  - path: ari-core/ari/viz/v1/events.py
    role: implementation
  - path: ari-core/ari/viz/v1/store.py
    role: implementation
  - path: ari-core/ari/viz/v1/config_api.py
    role: implementation
  - path: ari-core/ari/config/field_registry.py
    role: implementation
  - path: ari-core/ari/viz/v1/challenges.py
    role: implementation
  - path: ari-core/ari/viz/v1/openapi.json
    role: schema
  - path: ari-core/ari/viz/v1/launch.py
    role: implementation
  - path: ari-core/ari/viz/api_experiment.py
    role: implementation
  - path: ari-core/ari/viz/api_workflow.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/Workflow/WorkflowPage.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/Overview/OverviewPage.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/Overview/LogsPanel.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/hooks/useDevMode.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/Overview/__tests__/OverviewPage.test.tsx
    role: test
  - path: ari-core/ari/viz/frontend/src/components/Overview/__tests__/LogsPanel.test.tsx
    role: test
  - path: ari-core/ari/viz/frontend/src/app/__tests__/routeRegistry.test.tsx
    role: test
  - path: ari-core/ari/viz/frontend/src/__tests__/routeNavParity.test.tsx
    role: test
  - path: ari-core/ari/viz/frontend/src/__tests__/appContextScope.test.ts
    role: test
  - path: ari-core/ari/viz/frontend/src/__tests__/v1TypesDrift.test.ts
    role: test
  - path: ari-core/ari/viz/frontend/src/services/__tests__/api.test.tsx
    role: test
  - path: ari-core/ari/viz/frontend/src/__tests__/routeRenderBaseline.test.tsx
    role: test
  - path: ari-core/ari/viz/frontend/src/__tests__/shellA11yBaseline.test.tsx
    role: test
  - path: ari-core/ari/viz/frontend/src/hooks/__tests__/useRunEvents.test.tsx
    role: test
  - path: ari-core/ari/viz/frontend/src/shared/realtime/__tests__/eventStream.test.ts
    role: test
  - path: ari-core/ari/viz/services/__init__.py
    role: implementation
  - path: ari-core/tests/test_gui_config_shadow_legacy.py
    role: test
  - path: ari-core/tests/test_gui_state_facade_freeze.py
    role: test
  - path: ari-core/ari/viz/frontend/src/styles/tokens.css
    role: implementation
  - path: ari-core/ari/viz/frontend/src/styles/motion.css
    role: implementation
  - path: ari-core/ari/viz/frontend/src/styles/components.css
    role: implementation
last_verified: 2026-08-16
---

# Dashboard Architecture

The ARI dashboard is a React/TypeScript single-page app served by the Python
HTTP server in `ari/viz/`. This page is the *concept* view: the handful of
structural decisions that explain why the dashboard is shaped the way it is —
one shell hosting two generations of screens, one registry that owns routes,
one cache that owns server state, one seam between HTTP and the filesystem.

It is deliberately not an endpoint list or a click-by-click tour:

- [Dashboard Guide](../guides/dashboard.md) — the operator's tour: starting
  the server, what each workspace answers, deep links.
- [ARI Architecture](architecture.md) — the research system the dashboard
  observes (pipeline, BFTS, checkpoints).
- [Research and Governance State](research_and_governance_state.md) — the
  state vocabularies the dashboard is required to keep apart.
- [REST API Reference](../reference/rest_api.md) — the endpoint tables.

---

## The whole picture

```text
     #/tree2?run=R1&node=N7       ← the URL is navigation truth
               │
               ▼
  ┌──────────────────────────── browser ─────────────────────────────┐
  │  route registry (app/routeRegistry.ts)                           │
  │    · path + legacy aliases  · nav slot  · guiV2 gate             │
  │               │                                                  │
  │               ├──▶ legacy screen  (#/tree, #/results, …)         │
  │               └──▶ v2 workspace   (#/tree2, #/results2, …)       │
  │                     │   both inside the SAME shell/Layout        │
  │                     ▼                                            │
  │  server-state cache (react-query)                                │
  │  key = ['v1', <runId | projectId>, <resource>]                   │
  └────────────┬─────────────────────────────────┬───────────────────┘
    HTTP GET   │                                 │  SSE = invalidations
               ▼                                 ▼
  ┌────────────────── transport: ari/viz/routes.py ──────────────────┐
  │  same-origin CORS · CSP / nosniff / Referrer-Policy ·            │
  │  bearer auth on non-loopback binds · challenges · logs           │
  └────────────┬─────────────────────────────────┬───────────────────┘
               ▼                                 ▼
     v1/router.py (ROUTES table)             v1/events.py (bus)
               │
               ▼
     pure read modules: queries.py · results.py · rqgm.py · logs.py
     (no viz.state writes · no os.environ writes · no ari.rqgm)
               │
               ▼
     {checkpoint}/  tree.json · review_report.json ·
                    rqgm_transitions.jsonl · ear/     ← the truth
```

Everything below is a consequence of one rule: **the committed artifacts on
disk are the only truth, and every layer above them is a projection that can
be thrown away and recomputed.**

---

## 1. Strangler shape: one shell, two generations of screens

The dashboard was not rebuilt in place. Legacy screens and new v2 workspaces
are registered side by side in the same router and render inside the same
`Layout` (sidebar, checkpoint picker). Nothing was deleted to make
room for a new screen.

| Generation | Hash routes |
|---|---|
| Legacy screens | `#/home`, `#/experiments`, `#/monitor`, `#/tree`, `#/results`, `#/wizard` (`#/new`), `#/idea`, `#/workflow`, `#/settings`, `#/paperbench*` |
| v2 workspaces | `#/projects`, `#/overview?run=`, `#/tree2?run=&node=`, `#/ideas2?run=`, `#/results2?run=`, `#/governance?run=`, `#/config?run=`, `#/studio` |

Three mechanisms make the two generations coexist:

- **Parallel running.** A v2 workspace never edits its legacy counterpart.
  `#/tree` and `#/tree2` are different components over the same artifacts;
  both stay reachable.
- **Nav takeover (`navReplaces`).** While the v2 shell is on, a v2 route may
  occupy the *sidebar slot* of its legacy counterpart — it inherits that
  slot's label, order and icon, so the sidebar looks identical and only the
  hash a click writes changes. The legacy route stays registered, so its URL
  keeps working; bookmarks never break.
- **A single kill-switch.** With the v2 shell off, v2-only routes resolve to
  Home exactly like an unknown hash, and the sidebar hides their entries. No
  rebuild, no redeploy — see §9.

The migration therefore has no cutover moment to schedule. A workspace is
promoted by giving it a nav slot; it is rolled back by taking the slot away.

One thing this shape is **not**, and it is the tempting misreading: a thin
legacy facade over a shared application service. `ari/viz/services/` holds
three modules (`state_service`, `file_service`, `launch_service`), and the
only thing `/api/v1` calls from it is `launch_service.load_dotenv_files`.
Beyond a set of shared helpers — checkpoint-directory resolution, the
checkpoint search bases, the pid probe, the byte-preserving tree adapter, the
`.env` chain reader, the access-log writer — the legacy handlers and the v1
read modules are largely two independent implementations over the same
artifacts. But where a legacy function is already the single source of truth,
the v1 module reuses it deliberately rather than forking it: `catalogs.py`
re-serves the legacy `/api/models` payload (`checkpoint_api._api_models`) with
one field added, the provider's API-key env name; `results.py` calls
`ear._synth_repro_report_from_ors` read-only for the ORS verdict, scores and
leaf counts, so the two Results surfaces cannot show different verdicts; and
`secrets.py` writes through `api_settings._upsert_env_key`. Those reuse points
are what keeps the two sides in step, and they are also what legacy removal has
to unpick: deleting the legacy `/api/models` handler or `ear.py` would break
`/api/v1` read models (§7).

Configuration reaches a run by two routes as well: the legacy
Settings-save-and-launch chain maps selected keys into environment variables
for the spawned CLI, while the `/api/v1` config endpoints go through the
canonical resolver — and the two do
not agree everywhere, which the dead and env-only Settings keys in
[Configuration](../reference/configuration.md) enumerate.

The two sides are therefore held in agreement by tests, not by construction.
`ari-core/tests/test_gui_config_shadow_legacy.py` diffs the legacy launch's
effective configuration against the canonical resolver's per leaf and permits
a divergence only when an explicit allowlist names it — failing equally if a
listed divergence quietly stops diverging.
`ari-core/tests/test_gui_state_facade_freeze.py` pins the exact top-level key
set of the frozen `/state` payload and rejects both additions and removals.
The practical consequence for anyone changing behaviour: expect to change it
twice, and expect one of those two suites to be what tells you that you
changed it once.

---

## 2. The route registry is the only place a route exists

`app/routeRegistry.ts` holds one `ROUTE_REGISTRY` array. Each entry carries
the route's `id`, its hash `path`, a lazy `load` thunk, optional nav metadata
(`navLabelKey`, `navOrder`, `navIcon`, `navPath`), `legacyAliases`, and the
migration markers `guiV2` / `navReplaces`.

Both consumers are *derived*, not hand-maintained:

- `App.tsx` builds its lazy-component map and its dispatch from the registry
  (`resolveRoute` strips the `#/` prefix and any query string, treats an empty
  hash as `home`, and applies legacy aliases such as `new` → `wizard`).
- `Sidebar.tsx` builds its nav table from `navItems()`, which materializes a
  `navReplaces` entry onto its target's slot and sorts by `navOrder`; the
  sidebar then hoists the wizard entry out as a primary action and lays the
  rest out in four fixed groups (portfolio / research / quality / system).

Two frozen-literal tests pin the result, so a route cannot drift into existing
in the nav but not the router (or vice versa). The practical rules that fall
out of this:

- **Hash URLs are a deployment contract.** They are what users bookmark and
  what the docs cite; the registry preserves historical spellings (the wizard
  still navigates to `#/new`) rather than tidying them.
- **Reachable-but-unlisted is expressible.** `#/paperbench/import|run|results`
  exist as routes with no nav entry. The first two are opened by buttons on
  the PaperBench registry page; `#/paperbench/results?job=<job_id>` is linked
  from nowhere in the app and is reached only by pasting the URL.
- **Unknown hashes fall back to Home** rather than erroring. That fallback is
  load-bearing in one case and a known deficiency in another. It is deliberate
  for the kill-switch: with the v2 shell off, a v2-only route must resolve
  exactly like an unknown hash so the legacy surface stays whole (§9). For a
  genuine typo it is a deficiency — the user gets Home with no explanation, and
  an explicit "this route does not exist" resolution screen is still open work,
  marked as a `TODO` in `App.tsx`. The *missing run* case is already handled the
  intended way: a v2 workspace opened without `?run=` shows an explicit prompt
  rather than silently adopting a global selection.

**What the registry does not carry.** `RouteDefinition` declares two fields
that nothing reads: `breadcrumbKey` and `requiredContext`. There is no
breadcrumb component anywhere in the dashboard, and no route-level
required-context guard — each v2 workspace enforces its own "no run selected"
prompt instead. Two shell surfaces the GUI refresh specified are likewise
unbuilt: there is no command palette and no notification center, so a run or
governance alert is visible only on the page that renders it. The palette's
specified scope is worth recording as it dies — one box searching routes, runs,
artifacts and actions, filtered by what the caller is permitted and capable of
seeing — because half of that filter could not have been built as specified
here in any case. Routes carry no permission predicate, and will not need one
while the server has no user model — a bearer token is all-or-nothing, and
sessions and multi-user are out of scope. Capability gating is exactly one
marker: `guiV2` on the registry entry, plus the `V2_ONLY_ROUTES` dispatch set
in `App.tsx`.

**No route names its own flag.** Two further fields the refresh specified for a
route record were never declared: a `capability` predicate and a named
`featureFlag`. The boolean `guiV2` stands in for both, and it is not a flag
name a route chooses but a fixed marker for one environment switch,
`ARI_GUI_V2` (§9) — so routes cannot be flipped individually. With the switch
off, all eight marked routes resolve to Home together and all eight nav entries
disappear together, the three that had taken over a legacy slot handing it
back. Staging is nonetheless per slice: the
[GUI Cutover Runbook](../guides/gui_cutover_runbook.md) walks one workspace at
a time through its section "3. Staged rollout", and a slice that has to come
back is rolled back by taking its nav slot away (§1) — but the flag lever in
that document's section "1. Levers" is this one switch for the whole v2
surface.

The missing `capability` field also costs the registry its single-source
property for this one fact. Membership of the v2 gate is written twice: as
`guiV2: true` on the registry entry, which is what the sidebar filters on, and
as the route's *path* in the hand-maintained `V2_ONLY_ROUTES` set in `App.tsx`,
which is what dispatch falls back on. The frozen-literal test pins the
registry's eight marked ids, and the full-App render suite checks the Home
fallback one hash at a time for five of the eight paths; nothing compares the
two lists. A ninth v2 route added to one list and not the other would keep its
URL live while its nav entry vanished, or the reverse, with no test failing.

**One error boundary, at the root.** The dashboard has a single React error
boundary, in `main.tsx`, outside the router and outside `Layout`. A render
failure inside a route — including a lazy chunk that fails to load, since the
`Suspense` in `App.tsx` supplies a fallback but no boundary — therefore
replaces the whole shell, sidebar included, with the "ARI Dashboard Error"
screen; the stack is shown only in developer mode, and the only recovery is
reloading the page. Route-level boundaries with their own retry action were
specified and are not implemented, and there is no test for a failed chunk
load.

---

## 3. The URL is navigation truth

The dashboard is a hash router, and *selection* lives in the hash query
string: `#/overview?run=<run_id>`, `#/tree2?run=<run_id>&node=<node_id>`.
Route dispatch ignores the query string, so each v2 workspace owns its own
parameters — it reads them on mount, re-reads them on `hashchange`, and writes
a changed selection back into the hash.

Why this matters conceptually: a workspace's rendered content is a function of
its URL alone. That makes every view reloadable, bookmarkable and shareable —
"look at node N7 of run R1" is a link, not a sequence of clicks.

The legacy path is the contrast that motivates the rule. Reaching the legacy
Results page from a legacy Experiments row still goes through an *implicit*
handoff (a `sessionStorage` key plus a bare `#/results` hash), and the legacy
shell also carries a process-wide *active checkpoint*. Neither is a valid
input for a v2 workspace: v2 routes are run-explicit, which is what keeps two
runs open in two tabs from stepping on each other — a v2 row links
`#/results?run=<run_id>` instead, and the Results page treats that param as
authoritative, keeping the `sessionStorage` key only as a fallback for older
callers.

That key has a name worth pinning, because it is a cross-page contract rather
than a page's private storage: `ari_selected_checkpoint`. The legacy
Experiments row writes it before navigating to `#/results`; the v2 Projects row
still writes it alongside the explicit `#/results?run=<run_id>` link; the
Results page reads it *only* when the hash carries no `?run=`, and clears it
either way. A second key, `ari_tree_nodes`, is written by the legacy
Experiments page before it navigates to `#/tree` and is read by nothing — the
Tree page takes its nodes from the shared legacy context instead. It is dead
state, and removing the write is part of legacy-page removal rather than a
behaviour change.

**The hash has two owners, and two different parsers.** `App.tsx` resolves it
through `resolveRoute`, which strips the `#/` prefix *and* the query string and
applies legacy aliases. `context/AppContext.tsx` keeps its own `currentPage`,
initialised and updated from its own `hashchange` listener with a bare prefix
strip that does neither. The two agree on a plain legacy hash and disagree on
exactly the URLs the refresh introduced: at `#/tree2?run=R1&node=N7` the router
dispatches `tree2` while the context holds the whole string
`tree2?run=R1&node=N7`.

That second value is the one the sidebar renders from. `Sidebar.tsx` compares a
nav entry's hash key against `currentPage` to set both the `active` class and
`aria-current`, so the highlight is right after a click — a click writes
`#/<key>` and sets `currentPage` to that bare key — and is lost the moment a
workspace writes its own selection back into the hash (`TreeV2Page.tsx`,
`ConfigStudioPage.tsx` do), and is absent on any deep link that arrives with a
query string already in it. So the refresh's completion criterion — that server,
URL, form, preference and ephemeral state each have exactly one owner and do not
duplicate — does not hold for navigation state: one URL has two owners, and the
second is the legacy context that §4 otherwise scopes to remote data.

Nothing catches the disagreement, because no test drives a hash change against a
mounted shell. The two suites that mount the whole `App` —
`src/__tests__/routeRenderBaseline.test.tsx` and
`src/__tests__/shellA11yBaseline.test.tsx` — assign `window.location.hash` and
*then* render, always at a bare `#/<route>`, so only first-paint resolution is
exercised. Nothing exercises browser back or forward, and no test asserts
`aria-current` anywhere. Back/forward coverage was on the refresh's test list
and is a known gap.

---

## 4. Server state lives in a cache, keyed by run

All `/api/v1` reads go through one react-query client. Query keys have the
shape `['v1', <projectId | runId>, <resource>]` — the identifier sits *inside*
the key.

That single decision buys three properties:

- **Two runs can never mix.** Run-scoped entries are separate cache entries,
  so switching runs cannot bleed a previous run's data into the current view.
- **Invalidation has exactly the right granularity.** Dropping
  `['v1', runId]` drops one run's server state and nothing else; a filter that
  belongs to a resource (audit-log record type, epoch) sits in the key too, so
  changing it starts a fresh page chain instead of appending to a stale one.
- **Freshness policy is one place.** The client defaults are `staleTime`
  5000 ms (matching the historical polling cadence, so a remount inside that
  window serves cache), one retry, and no refetch on window focus — a local
  dashboard must not turn focus flapping into request storms against the
  checkpoint scanner. That single default is also the *whole* policy: no query
  overrides it, so a nearly static schema read is treated exactly like a live
  tree, and the freshness banner reports the last snapshot time rather than a
  per-resource age. Per-entity stale times and per-entity freshness labels were
  specified for the refreshed GUI and are not implemented.

**The dedup budget holds over the `/api/v1` surface, not over the dashboard.**
The refresh attached a number to this design: zero in-flight duplicate reads
for the same query key. On `/api/v1` that number is structural rather than
measured — the query client coalesces concurrent fetches of one key, so two
components mounting the same query produce one request — and it is exactly as
wide as that surface, no wider. Nothing in the tree measures it.

The legacy half issues its own traffic outside the client, and always has.
`context/AppContext.tsx` refetches `/state` and the checkpoint list on a
5-second `setInterval` (`STATE_POLL_MS = 5000`) for the whole session, since
`AppProvider` sits above the router; `Monitor/MonitorPage.tsx` runs a second,
independent 5-second interval over `/api/resource-metrics` for as long as that
screen is mounted. Neither goes through the query client, neither can see the
other, and neither stops when the tab is hidden — nothing in the frontend
listens for `visibilitychange` (§6), so a backgrounded dashboard keeps both
intervals running at full rate. Pausing hidden-tab polling and moving those
reads onto stream invalidation plus a snapshot query was specified by the
refresh and is not implemented; it is a known gap. Read the budget as scoped
accordingly: it holds for `/api/v1` reads by construction, and it does not
describe a running dashboard as a whole until those pollers are gone —
`AppContext`'s remote state and the `/state` facade behind it are items 2 and 3
of the removal order in the
[GUI Cutover Runbook](../guides/gui_cutover_runbook.md), section "6. Legacy
removal", and that removal order does not name the Monitor interval at all.

**Run isolation is proved at the seam, not end to end.**
`hooks/__tests__/useRunEvents.test.tsx` shows that an event for one run
invalidates only that run's keys plus the run lists, that a `tree` event touches
only that run's tree key, that the offline poll tick stays inside the subscribed
scope, and that unmounting stops the invalidation;
`shared/realtime/__tests__/eventStream.test.ts` pins the filtered stream URL,
the `Last-Event-ID` cursor, the backoff schedule and the connection state
machine. What no test does is mount two workspaces on two runs and show that
they stay apart. The [Dashboard Guide](../guides/dashboard.md), in its section
"Run-explicit URLs and deep links", tells operators that opening two browser
tabs on two different `?run=` values is safe; that promise rests on the key
composition above plus the server-side `run_id` filter (§6), not on a test of
the two-tab case, which the refresh listed and which is a known gap.

Client-only state (which tab is open, a filter box's text, sidebar width) is
*not* in this cache. The split is: server state is cached and invalidated,
view state is local and ephemeral, and navigation state is in the URL (§3).

**Mutations are never optimistic.** No screen writes a predicted result into
the cache. The write is sent, the server's answer — a new `revision`, or a
`409 revision_conflict` — is what the UI adopts, and the affected query keys
are invalidated so the next render comes from a refetched snapshot. That is why
a conflicted save raises an explicit reload affordance and keeps the unsaved
edits local instead of quietly winning, and why nothing on screen can be a
state the server never accepted.

**One component the refresh specified for the key never landed: a revision.**
Nothing in the `v1Keys` factory (`hooks/useV1.ts`) carries one. A key is the
literal `'v1'`, one identifier or a global resource name, the resource, and any
filter that narrows it — `rqgmAudit(runId, recordType, epoch)` and
`rqgmNodeLineage(runId, nodeId)` are examples of the last shape — and that is
the whole vocabulary. The integer `revision` a `gui_store` document carries is
used on the write side only, as the `If-Match` value a `PATCH` sends back (§7);
a write reaches the cache by invalidating the affected keys, not by minting a
new one. There is therefore no cache entry per revision and no way to hold two
revisions of one resource side by side, and no key churn on save: the next
render comes from a refetch of the same key.

**`AppContext` is legacy-scoped.** It is the remote-data store of the legacy
screens only — the 5-second `/state` poll, the tree-WebSocket mirror, and the
process-wide active checkpoint. A v2 workspace must not import it: it reads
`/api/v1` through the `useV1` hooks and takes its run from `?run=`. The rule is
enforced structurally rather than by review — a source scan under
`src/__tests__/` loads every non-test file in the v2 component directories and
fails on an `AppContext` import specifier. It carries exactly one pinned
exception, the IdeasV2 research-goal card, which reads the goal from `/state`
behind a run-identity check because no run-scoped v1 endpoint serves the goal
yet. Shrinking that exception list is welcome; growing it is a regression,
because `AppContext` cannot be deleted while a v2 screen depends on it.

**The legacy half of the shell parses domain artifacts.** The refresh also asked
that the shell itself never do so, and `AppProvider` — mounted in `App.tsx`
above the router and `Layout` — publishes `nodesData: TreeNode[]`, the run's
node list, taken from the tree WebSocket when that channel has delivered
anything and from the `/state` payload's `nodes` otherwise. That precedence rule
is domain logic living above the router, and two legacy screens
(`Tree/TreePage.tsx`, `Monitor/MonitorPage.tsx`) take their nodes from the shell
instead of fetching their own. `Sidebar.tsx` carries a smaller version of the
same coupling: `checkpointLabel()` matches a checkpoint id against
`^(\d{8})(\d{6})_(.+)$` to build the picker label, so the shell hard-codes the
run-id convention of §5, and it renders the run's status label and running flag
straight from `/state`. A v2 workspace has none of this. The invariant therefore
holds for the new surface and fails for the old one, and what would make it true
everywhere is legacy removal, not a change to the shell.

**Durable preferences have no store.** Locale (`ari_lang`, default `ja`),
developer mode (`ari_dev_mode`) and the remote bearer token (`ari_gui_token`)
go straight to `localStorage`, each behind its own one-key accessor —
`i18n.storedLang()`, `useDevMode.isDevMode()`, `client.getGuiToken()` — and the
Settings page still reads `ari_lang` from `localStorage` itself. There is no
preference-store abstraction over the three, no schema for these keys and no
migration path, so a rename or a re-type is a per-key edit with no single place
to make it. A preference layer was specified for the refreshed shell and is not
implemented; treat the three key names as the actual contract.

**Form drafts have no owner layer at all.** There is no form library among the
frontend's dependencies (`@tanstack/react-query`, `d3`, `pdfjs-dist`, `react`,
`react-dom`, `reactflow`) and no shared form module, so every editing surface
hand-rolls its own draft state and its own conflict discipline.
`ConfigStudio/ConfigStudioPage.tsx` is the pattern worth copying: a `pending`
map holding only the changed values over the server document, that document's
integer `revision` sent as `If-Match`, and a `revision_conflict` surfaced as an
explicit reload that keeps the unsaved edits. `Workflow/WorkflowPage.tsx` runs a
second discipline — a weak content `revision` served by `/api/workflow`, echoed
back as an optional `base_revision` on a write, with the server's refusal
recognised by matching the message of the thrown legacy transport error (§7).
`Settings/SettingsPage.tsx` runs a third and has no conflict path at all:
thirty-seven `useState` hooks in one container, deliberately concentrated there
so its frozen save payload cannot drift. These are not variants of one
mechanism, and the first and the last are two independent form owners over the
overlapping configuration surface §1 describes — the one
`ari-core/tests/test_gui_config_shadow_legacy.py` polices rather than removes. A
single form-state owner was specified for the refreshed GUI; it is a known gap.

---

## 5. The entity model is one level deep

The v1 surface is shaped like a `project → run` hierarchy, but only the lower
level is real. `GET /api/v1/projects` returns exactly one project — the
virtual `default` one, whose `checkpoint_roots` are the checkpoint search
bases that exist and whose run list is a checkpoint-directory scan over all of
them, using the same name filter and skip set as the legacy listing.
`GET /api/v1/projects/{project_id}/runs` answers a typed `404` for any other
id, and the Projects workspace reads `projects[0]` without looking further.

Three consequences to design against:

- **There is no project lifecycle.** The `ROUTES` table has no create, rename
  or delete for a project. The only other project-scoped endpoints are
  `GET` / `PATCH` on `/api/v1/projects/{project_id}/config`, both of which
  reject any id other than `default`; they read and write one singleton
  document, `gui_store/project_config.json`.
- **Runs are not scoped to a project.** Every run-scoped endpoint is
  `/api/v1/runs/{run_id}/…` with no project segment, so the `project_id` in a
  URL or in a cache key (§4) never narrows anything. Read `default` as a fixed
  placeholder that keeps those shapes stable — never as evidence that runs are
  isolated from one another.
- **A run *is* a checkpoint.** `run_id` is literally the checkpoint
  directory's name (`YYYYMMDDHHMMSS_<slug>`). A checkpoint is not modelled as
  a save point that one run could have several of, and no v1 endpoint or DTO
  expresses run-to-run lineage — `meta.json` records `parent_run_id`, but
  nothing under `/api/v1` reads it.

The field registry names levels *above* the project that do not exist either.
Its `scope` vocabulary is `preference` / `installation` / `project` /
`template` / `run` (see [Configuration](../reference/configuration.md)), but
only three of the five are ever assigned: every leaf the registry builds today
is `run` or `project` except a single `installation` one, `llm.api_key` — and
because that leaf is a `secret_reference`, its value lives in the `.env` chain
behind `/api/v1/secrets/*`, never in a GUI document. The document store has
nowhere to put a preference or an installation setting in any case: it holds
`project_config.json`, `run_templates/`, `run_drafts/` and `launches/`, and
nothing else (§7).

Separating real projects (owning reusable configuration) from runs (owning
lifecycle) and checkpoints (owning save points) is reserved design. Nothing in
the tree implements it, so no client should be written as though it were
already there.

**Two entities the versioned surface never modelled at all.** The GUI refresh's
domain model also named an `Artifact` under a run and a `WorkflowDefinition`
under a project; both were specified and neither was built. The shape of each
gap decides what a v2 screen can offer.

*There is no artifact resource.* The `ROUTES` table has no `artifacts`
collection under a run and no addressable member inside one, and the committed
`openapi.json` has no path mentioning an artifact. What `/api/v1` offers instead
is a fixed set of named projections — `idea`, `results`, `ear`, `logs` and the
RQGM family — each hard-wired to the files it knows about (§8). The one *file*
listing among them, `GET /api/v1/runs/{run_id}/ear`, walks a single subtree,
`{ckpt}/ear/`, returning `path` / `kind` / `size` per entry, capped at the first
500 entries with `truncated: true` beyond that while `file_count` still counts
every file. So there is no stable id for "this run's file X", nothing enumerates
what a run actually wrote, and a new kind of artifact cannot surface without a
new endpoint and a regenerated contract. Browsing arbitrary files stayed on the
legacy, checkpoint-keyed surface — the `/api/checkpoint/<id>/files`, `/file`,
`/file/raw`, `/filetree`, `/filecontent` family and `GET /codefile?path=` (see
[REST API Reference](../reference/rest_api.md), "Checkpoint browsing" and
"Static + frontend"). "Artifact" therefore keeps the disk-level meaning the
[Glossary](../reference/glossary.md) gives it under "State & publication": a
non-metadata file produced inside a node work_dir.

*There is no workflow document.* The pipeline definition is a plain file,
`{ckpt}/workflow.yaml`, and `/api/v1` touches it in exactly two ways, neither of
them as a resource: `POST /api/v1/runs` copy-on-write seeds it from the bundled
`config/workflow.yaml` and merges the launch's mode blocks into that copy, and
the resolver behind `GET /api/v1/runs/{run_id}/resolved-config` reads it as the
`workflow` provenance layer and counts its mtime toward `resolved_at`. No route
addresses it as a document: it has no id, it is not one of the `gui_store/`
documents (§7), and it is not reusable across runs — every checkpoint gets its
own copy. Editing it is still the four legacy writes — `POST /api/workflow`,
`/api/workflow/flow`, `/api/workflow/skills`, `/api/workflow/disabled-tools` —
and their concurrency guard is a different mechanism from the store's: MN-3's
`revision` is a sha256 prefix of the
served bytes with an *optional* `base_revision`, so a caller that omits it keeps
last-write-wins, whereas a `gui_store/` document carries an integer `revision`
and refuses a mutation that arrives without `If-Match` (see
[Configuration Studio](../guides/configuration_studio.md), "If-Match
conflicts").

**A workflow edit is scoped to one checkpoint, and a new run never inherits
one.** Every workflow write lands on the *active* checkpoint's copy:
`api_workflow.py` refuses the write outright when no usable checkpoint is
active, and otherwise CoW-seeds `{ckpt}/workflow.yaml` from the bundled file
before applying the edit, so the bundled default is never rewritten from the
GUI. Both launch paths then seed the new checkpoint from that *bundled* file
and only from it: `POST /api/v1/runs` (`ari/viz/v1/launch.py`) copies
`config/workflow.yaml` into the new checkpoint and merges the launch's mode
blocks into that copy, and the legacy wizard launch `POST /api/launch`
(`ari/viz/api_experiment.py`) copies the same bundled file — or, when one of
its phase toggles is off, writes a variant of it with the toggled-off stages
set `enabled: false` and stripped from every downstream `depends_on`. Neither
reads the checkpoint that was active a moment earlier, so there is no path by
which an edited copy becomes the seed. The edited copy is read back only when
the *same* checkpoint runs again: the BFTS loop (`ari/cli/bfts_loop.py`) and
the paper pipeline (`ari/core.py`) both resolve `{ckpt}/workflow.yaml` ahead
of the package copy.

**Known gap — nothing on screen states that scope.** The refresh specified
that a save declare which run the edit takes effect on.
`Workflow/WorkflowPage.tsx` renders the served file path in its toolbar — the
only hint of scope there is — and nothing more: no statement of which run the
edit affects, no warning at save time, and no route that applies a pipeline to
the next run. The two launch paths then differ in a way nothing surfaces
either: the legacy wizard launch switches the process-wide active checkpoint
to the new run, so the editor silently retargets, while `POST /api/v1/runs`
deliberately leaves it alone, so the editor keeps pointing at the previous
run. Treat a workflow edit as a property of one checkpoint, not as a setting.

The nearest reusable document is a run template, and a template carries config
`values`, not a pipeline.

---

## 6. Realtime is invalidation, not a source of truth

`GET /api/v1/events/stream` is a Server-Sent Events stream with server-side
`run_id` / topic filtering. An event is a small notification —
`{event_id, run_id, topic, revision, occurred_at, kind, resource, payload}` —
and the consumer's only reaction is to invalidate the matching cache keys and
refetch the HTTP snapshot.

Nothing is ever *rendered from* an event. The consequences are the reason for
the design:

- **Duplicates and reordering are harmless.** The snapshot endpoint decides
  what is true; the event only decides *when to ask again*.
- **A dropped stream is a freshness problem, never a state change.** The last
  snapshot stays on screen under a staleness banner. A disconnect is never
  presented as "the run stopped".
- **Reconnect is cheap and bounded.** Exponential backoff (1 s → 30 s cap)
  with a `Last-Event-ID` cursor; errors persisting past a minute flip the
  connection to `offline`, which is the *only* state that enables a bounded
  10 s polling fallback over the subscription's own scope.
- **The bus stays small.** Events live in an append-only in-memory ring
  buffer with a fixed cap, with heartbeat comments and a bounded stream
  window so an idle proxy or a stuck client cannot pin a worker forever.

Because events carry their own `run_id`, an event for run B can never touch
run A's cache entries — the same isolation property as §4, enforced on the
write side of the cache.

**One owner, two honest exceptions.** Realtime over `/api/v1` has exactly one
owner: `shared/realtime/eventStream.ts`. Pages call
`subscribe(runId, topics, callbacks)` — normally through the `useRunEvents`
hook — and do not construct an `EventSource` themselves, so the backoff
schedule, the `last_event_id` cursor, the three-state connection machine and
the offline poll tick exist once and are tested once. Two channels sit outside
that ownership and predate it: the legacy tree WebSocket on HTTP port + 1, and
the PaperBench job-log viewer, which opens its own `EventSource` on the
PaperBench log stream while a job is in flight. Both are removal candidates,
not patterns to copy.

**Subscriptions follow the mounted route and its run**, so a page subscribes
for its own lifetime and `run_id` / `topics` filtering happens server-side —
a page never pays for events it would not render. Nothing throttles a hidden
tab, though: the client does not listen for `visibilitychange`, so a
backgrounded tab keeps its stream open, keeps reconnecting on backoff, and
keeps its 10 s offline poll ticking. Background-tab load control was specified
and is not implemented; several stale tabs each hold a stream.

---

## 7. The backend seam

The server is four layers, and each one is allowed to know only about the
layer below it.

There is no web framework under this seam. The transport is the Python
standard library: `server.py` binds one `ThreadingHTTPServer` per host — the
loopback default asks for both families and tolerates one of them being
unavailable, and every server after the first runs `serve_forever()` on a
daemon thread — and requests are served by the single
`BaseHTTPRequestHandler` subclass in `routes.py`, which dispatches the legacy
surface through an explicit `if`/`elif` chain over the request path and hands
anything under `/api/v1/` to the declarative `ROUTES` table
(`/api/v1/events/stream` is intercepted one branch earlier, because the
dispatcher returns a dict and SSE has to write a long-lived stream). Only the
tree WebSocket is asyncio: `_main` is the sole asyncio entry point, and after
starting the watcher and the HTTP server on daemon threads it hosts nothing
but the `websockets` server on HTTP port + 1. Two consequences run through
the rest of this section. The API layer owns its routing, its error envelope
and its OpenAPI generation because there is no framework to inherit them
from — they are built here, not configured. And a connection occupies a
worker thread for as long as it is open: the handler sets
`protocol_version = "HTTP/1.1"` so that short polls reuse one connection
instead of draining the browser's per-origin pool, while the long-lived
streaming endpoints answer `Connection: close` so they do not sit on a
keep-alive slot. Blocking work inside a handler therefore costs a thread, not
a coroutine.

| Layer | Module | Responsibility |
|---|---|---|
| Transport | `ari/viz/routes.py` (+ `auth.py`, `server.py`, `health.py`) | Socket-level policy: same-origin CORS echo, `Content-Security-Policy` / `nosniff` / `Referrer-Policy` on the SPA and static responses, bearer-token auth whenever the bind is non-loopback, access logging, `/health/live` and `/health/ready`. |
| API | `ari/viz/v1/router.py` | One declarative `ROUTES` table of `(method, path template, handler)`. Mints a `request_id` per dispatch and threads it into the success payload or the typed error envelope; enforces `If-Match` optimistic concurrency on `PATCH`/`DELETE`; the same table generates the committed `openapi.json`, so the contract cannot drift from the dispatcher. |
| Read models | `queries.py`, `results.py`, `rqgm.py`, `logs.py`, `catalogs.py` | Pure functions from a checkpoint directory to a DTO. No `viz.state` mutation, no `os.environ` writes, no file writes — a GET has no side effects. |
| Truth | `{checkpoint}/…`, plus `{workspace_root}/gui_store/` for GUI-only documents | Committed artifacts. |

**The four layers are a description, not a package layout.** `ari/viz/` has no
`transport/`, `application/`, `domain/`, `infrastructure/` or `legacy/`
package, and no domain layer of any kind: nothing sits between a read module and
the wire, so a checkpoint `Path` becomes a pydantic DTO directly. The GUI
refresh specified exactly that split — with the unversioned handlers moved
behind an adapter module — and it was not built; the legacy handlers stayed
where they were, imported directly from their `api_*` modules by the
`if`/`elif` chain in `routes.py` (see
[Internal Boundaries](../reference/internal_boundaries.md), "GUI HTTP dispatch
boundary").

The process supervisor from the same proposal is missing on the same terms.
`POST /api/v1/runs` spawns the CLI with
`subprocess.Popen(..., start_new_session=True)` and records the handle in the
module-global `_running_procs` map in `ari/viz/state.py`, keyed by resolved
checkpoint path — the same map the legacy launch handlers write to. Nothing
supervises, restarts or reaps those children. An entry leaves the map only
opportunistically: when the legacy checkpoint listing next notices that the
child has exited, when that same listing prunes entries whose checkpoint
directories no longer exist, or when a checkpoint is deleted. The map is
process-local, so a server restart forgets every handle; the v1 read models
never consult it, deriving run status from the filesystem instead (below), and
`/api/v1/diagnostics` publishes only its length, as `process.tracked_runs`.
Treat this seam as held by the read modules' own discipline and by the tests
that pin it, not by a package boundary anything can enforce.

Three properties of this seam are worth stating explicitly because they are
easy to erode:

- **`GET` is side-effect free.** The read modules deliberately re-derive
  run status from the filesystem (pid probe → tree refinement → review
  report) instead of consulting or pruning the server's process-tracking
  state, which the older handlers mutate as a side effect of being read.
- **Writes are narrow and explicit.** The GUI's own documents — project
  defaults, run templates, run drafts, launch idempotency records — live in
  `{workspace_root}/gui_store/`, not in a global home directory, with atomic
  writes and an integer `revision` that maps 1:1 to `ETag` / `If-Match`. They
  are a convenience layer: launch materializes every effective value into the
  checkpoint, so the CLI never has to read `gui_store/` to reproduce a run.
- **Minted timestamps come from the filesystem, not from the clock.** The time
  fields the server *derives* for a read resource are UTC ISO 8601 strings taken
  from a source file's mtime, never from `datetime.now()`: `mtime_utc` on a run
  summary is the checkpoint directory's mtime, `updated_at` on a run template or
  a run draft is that document file's mtime, and `resolved_at` on a resolved
  config is the newest mtime among the resolver's source files, falling back to
  the checkpoint directory's. That is what makes two consecutive GETs of an
  unchanged run identical apart from the `request_id` the router mints per
  dispatch, so a diff between two captured payloads means "something changed"
  rather than "time passed" —
  `ari-core/tests/test_gui_config_precedence_matrix.py` pins it for the resolver
  with `test_resolved_at_mtime_stable_and_deterministic`, which drops the
  `request_id` and asserts the two responses are otherwise equal. Timestamps
  *copied* out of a
  committed artifact stay that artifact's own values (an RQGM transition's
  `committed_at`, a publish record's `timestamp`). The clock is read only where
  there is no file to read from: an event's `occurred_at` (§6) and a challenge's
  `expires_at`.

**The browser side of the seam has three transport regimes, deliberately not
unified.** `services/api/client.ts` exposes three pairs of wrappers, and which
pair a call uses is part of the contract. Five of the six share one `request`
primitive; the sixth, `v1Send`, deliberately builds its own `RequestInit`,
because the primitive's options shape is itself part of the frozen legacy wire
contract — so the v1 mutation transport, `If-Match` header included, sits
beside `request` rather than inside it:

- `get` / `post` throw `Error('<METHOD> <path> failed: <status>')` on any
  non-2xx. The legacy `useApi` hook and its callers depend on the throw.
- `pbGet` / `pbPost` never throw. The PaperBench handlers answer HTTP 200 with
  an `{error: …}` body, so the application error arrives in the body and the
  caller handles it inline.
- `v1Get` / `v1Send` resolve with the parsed body whatever the status, because
  `/api/v1` returns real non-2xx statuses whose body *is* the typed error
  envelope — a throwing client would discard exactly the payload the UI needs.
  `services/api/v1.ts` then normalizes every failure (typed envelope, network
  error, or unparseable body) into one thrown `ApiErrorV1`
  `{code, message, details, request_id, retryable}`.

The asymmetry is preserved rather than tidied: the first two regimes are pinned
by a frozen-behaviour test, and unifying them would silently change what every
legacy caller sees. New code uses the `/api/v1` regime.

Two gaps in that client are worth naming, because their absence is easy to
mistake for a policy:

- **There is no client-side abort or timeout.** Neither the shared `request`
  primitive nor `v1Send` passes an `AbortSignal` or sets a deadline, so a hung
  request hangs until the browser gives up, and navigating away from a page
  does not cancel its in-flight fetches. Retry policy is the react-query default (one retry) plus
  the server-declared `retryable` flag on the error envelope, which a caller
  may inspect but which nothing consumes automatically. Idempotency is
  per-endpoint rather than per-method metadata: only run launch carries an
  `idempotency_key`, minted once per review approval so a double-click or a
  retry replays the same run instead of spawning a second one. Per-method
  abort/timeout/retry/idempotency metadata was specified and is not built.
- **Schema drift is caught at build time, not at runtime.** The generated DTO
  module `services/api/v1types.gen.ts` is produced from `ari/viz/v1/openapi.json`
  and byte-compared by a drift test, so a contract change that was not
  regenerated fails CI and never ships. At runtime there is no compatibility
  check: a response that does not match the generated DTO is not detected, and
  a body that cannot be parsed at all is normalized to `code: 'internal'` with
  `retryable: true` — indistinguishable from a transport hiccup. A distinct
  "this bundle does not match this server" compatibility error was specified
  and is not implemented, so a bundle/server mismatch surfaces as an ordinary
  internal error, or as a missing field rendering blank.

---

## 8. Read models are disposable projections

A *read model* is a bounded projection computed on demand from committed
artifacts. Delete every read model and no information is lost; delete an
artifact and it is gone. That asymmetry is the point.

**"On demand" is literal: recomputed, never cached.** Each `/api/v1` GET
re-reads the artifacts it projects, every time. There is no projection index, no
memoization and no invalidation table anywhere under `ari/viz/v1/` — the
package's only cache is the idempotency replay map in `launch.py`, which serves
duplicate launch POSTs rather than reads. A persisted read-model index,
invalidated on file identity, size, mtime and content digest, was specified by
the GUI refresh and is not built; the wire says so rather than hiding it, since
`GET /api/v1/diagnostics` carries the literal field `cache: false`. What keeps
the cost bounded is per-endpoint discipline instead — byte-offset cursors,
capped page sizes and the log reader's 1 MiB per-request scan window (see
[REST API Reference](../reference/rest_api.md), "Cursor conventions") — plus the
client cache in §4, which is where an unchanged snapshot stops being fetched
twice. An endpoint with no such bound pays its full cost on every request;
`GET /api/v1/runs/{run_id}/tree`, which returns the whole node list, is the
clearest case.

The governance read model is the strictest instance, and it shows what
"projection" means in practice:

- **It re-executes no decision.** `ari/viz/v1/rqgm.py` never imports
  `ari.rqgm`. It parses the committed artifacts (`rqgm_state.json`,
  `rqgm_transitions.jsonl`, `rqgm_audit.jsonl`, `rqgm_registry.json`, node
  metrics sentinels…) and reports what they say. The GUI cannot invent a
  governance verdict, because it never runs the kernel that produces one.
- **Committed records only.** Current state is the replay of *committed*
  transitions. A torn trailing JSONL line is ignored, and events after a
  prepare with no matching commit are never adopted. A rollup snapshot is
  read only to verify that the replay agrees with it.
- **Degraded, never broken.** A corrupt or missing artifact yields HTTP 200
  with honest flags: integrity is tri-state (`true` verified / `false` broken
  / `null` source missing) and a `degraded_reasons` list travels with the
  payload. A missing source is never rendered as clean, and never as zero.
- **Bounded by construction.** Summaries carry counts, not embedded entry
  lists; long logs are cursor-paged over stable offsets; and the only file
  read out whole is the governed policy body served by `/rqgm/policies` and
  `/rqgm/epochs/{epoch_id}` — withheld outright, as a degraded reason, when
  its bytes no longer hash to the registered `prompt_hash`.

For anyone extending the dashboard, the operational rule is: to change what
the GUI shows, change the projection — never the artifact, and never by
recomputing a decision the kernel already committed.

---

## 9. Capabilities and kill-switches

The dashboard distinguishes two kinds of "this is not available", and neither
is an error.

**Server capability — what this build offers.** `GET /api/capabilities`
reports the `gui_v2` flag (`ARI_GUI_V2`, default on). The frontend fetches it
once on mount and treats a *failed* fetch as on, so an API hiccup can never
strand a local user in the fallback shell.

**Run capability — what this run's artifacts support.** Detected from artifact
presence alone: a run has governance because `rqgm_state.json` exists, and it
is in archive paper mode because `paper_archive_state.json` exists (the two
are independent axes). A run without governance gets an explicit "governance
is not active for this run — this is a capability state, not an error" panel
that names the reason, instead of an empty screen or a fabricated zero.

Every risky behaviour introduced with the refreshed GUI ships with an
environment kill-switch, so a deployment can revert one decision without
reverting a release. All of them are documented in
`scripts/setup/setup_env.sh`:

| Variable | Default | Turning it off restores |
|---|---|---|
| `ARI_GUI_V2` | on | The legacy shell only (v2-only routes fall back to Home) |
| `ARI_GUI_BIND` | loopback (`127.0.0.1` + `::1`) | A wider bind, e.g. `::` for all interfaces |
| `ARI_GUI_TOKEN` / `ARI_GUI_AUTH` | auth enforced on non-loopback binds | An unauthenticated remote bind (e.g. behind an authenticating proxy) |
| `ARI_GUI_CORS_ANY` | off (same-origin echo) | The legacy `Access-Control-Allow-Origin: *` wildcard |
| `ARI_GUI_CSP` | on | Responses without the CSP / nosniff / Referrer-Policy headers |
| `ARI_GUI_CHALLENGES` | on | Direct destructive endpoints, with no confirmation challenge |
| `ARI_GUI_HEALTH` | on | The pre-health-probe responses, with no diagnostics endpoint |

The security defaults these switches guard are worth stating once: the server
binds loopback only, so the default local experience needs no authentication;
a non-loopback bind *fails secure* by requiring a bearer token (generated and
printed once at startup if none was configured); and the three destructive
operations (delete checkpoint, stop, stop GPU monitor) require a server-issued
single-use confirmation challenge, answering `428` without one.

---

## 10. Where frontend code lives

The frontend is grouped by *screen*, and the route registry is the only
composition layer above it. Under `ari-core/ari/viz/frontend/src/`:

| Directory | Holds |
|---|---|
| `app/` | Shell wiring no screen owns: the route registry (§2) and the react-query client (§4). |
| `components/<Screen>/` | One directory per screen, legacy and v2 side by side (`Tree/` and `TreeV2/`, `Results/` and `ResultsV2/`), each exporting the page components the registry lazy-loads — plus `common/` for presentational primitives and `Layout/` for the sidebar and the page frame that wraps the active page. |
| `context/` | The legacy `AppContext` — the `/state` poll and the process-wide active checkpoint. |
| `hooks/` | Cross-screen hooks: `useV1`, `useRunEvents`, `useApi`, `useWebSocket`, `useDevMode`. |
| `services/api/` | One transport core (`client.ts`) plus one module per endpoint family, re-exported by the `services/api.ts` barrel so older import paths keep resolving. |
| `shared/` | Cross-cutting platform code — today only `realtime/`, the SSE client. |
| `i18n/`, `styles/`, `types/` | The three-language string tables, the CSS token and layout sheets, the shared DTO types. |
| `__tests__/` | App-wide guard suites no screen owns: route↔nav parity, full-App route render, shell a11y, developer-mode gating, generated-type drift. |

There is no `pages/` layer. A registry entry's `load` thunk imports the screen
component directly, so route composition *is* the registry entry.

**The feature/entity slicing was specified and not built.** The GUI refresh
called for a further split into `features/` and `entities/` directories, under
the rule that a feature may not import another feature's internal modules and
must go through an entity or shared contract — or the page that composes
them — instead. None of it exists: there
are no `features/`, `entities/` or `pages/` directories, and the tree already
reaches across screen boundaries where reuse was cheaper — `ConfigStudio`
imports `ConfigBrowser`'s read-only config table (deliberately, so the two
config surfaces cannot drift), and both `Monitor` and `TreeV2` import the
legacy `Tree` visualization.

Nothing enforces a layering boundary either. The frontend `package.json` has
no lint step and no lint dependency, so the only structural import guard in the
tree is a test — `src/__tests__/appContextScope.test.ts`, which scans every
non-test file under the v2 screen directories for an `AppContext` import
specifier and fails on any beyond one pinned exception. That guard protects the
legacy-removal gate, not a feature/entity boundary; no scan of any kind
constrains screen-to-screen imports.

Read the slicing as a direction of travel, not as something the tree obeys.
The placement rule that *is* honoured today is the shallower one: presentational
primitives go in `components/common/`, cross-cutting platform code in `shared/`,
shell wiring in `app/` — and a screen directory owns only its own screen.

**The design tokens are two tiers, not three.** `styles/tokens.css` is the only
file that *defines* custom properties. `motion.css` redefines three of them —
`--t-fast`, `--t-med`, `--t-slow` — to zero under `prefers-reduced-motion:
reduce`, and `Layout/Sidebar.tsx` writes an inline `--sidebar-width` that is a
measurement the layout sheets read, not a token. Everything else sits in one
`:root` block, in two named layers. The **primitive** layer is the raw scale:
the hues (`--bg`, `--sidebar`, `--card`, `--border`, `--text`, `--muted`,
`--blue`, `--blue-light`, `--green`, `--red`, `--yellow`, `--purple`, plus the
`--primary` alias), the spacing steps `--sp-1` through `--sp-8` (4px to 32px,
with no `--sp-7`), the radii and the focus shadow, the type scale and the motion
durations. The **semantic** layer names roles and resolves each one to a
primitive or to a `color-mix()` of primitives, introducing no new hue:
`--surface-canvas` / `--surface-raised` / `--surface-overlay`, `--text-primary` /
`--text-muted` / `--text-inverse`, `--border-default` / `--border-focus` /
`--focus-ring`, the three link colours, four `--status-*` foregrounds each with a
`-bg` tint (two of them also with a `-border` tint, declared up beside the
primitives), `--score-penalty`, the five `--state-*` node-score colours and the
ten `--reg-*` registry-lifecycle colours.

A third, **component** tier was specified above those two — a token named for one
component's one role, such as a primary button's background or a selected graph
node's fill — and it was not built. No role token above the semantic layer exists
anywhere in the tree; the only custom property whose *name* comes from a
component is the primitive surface hue `--sidebar`, which is a raw value in the
bottom layer rather than a role above the top one. Where the component tier would
have gone, a CSS class consumes a semantic token directly instead:
`components.css` defines a `.reg-badge--<status>` rule for each of the ten
registry statuses and a `.nodestate-badge--<state>` rule for each of the five
node score states, each setting `color` from the matching `--reg-*` or
`--state-*` token, and the two class families are disjoint on purpose. That does
deliver what the fixed palettes were for — neither vocabulary can borrow the
other's colour, as
[Research and Governance State](research_and_governance_state.md), section
"4. Registry lifecycle vs node score state", requires — but it delivers it
through class names rather than a third layer of tokens.

**Known gap — the rule that nothing above the semantic layer reaches past it to a
primitive colour is unenforced, and the tree does not follow it.** The
`package.json` has no lint step, as noted above; no test and no checker under
`scripts/quality/` reads a stylesheet at all (the bundle-weight gate weighs
`.js` chunks only), so nothing can fail on a violation. Counting `var(…)` uses of
the thirteen primitive colour names: 458 of them sit in 53 non-test `.tsx` files
under `components/`, and another 140 in the stylesheets themselves
(`components.css` 66, `widgets.css` 47, `layout.css` 21, `responsive.css` 6) —
against 113 uses of the entire semantic layer across the same files. The v2
workspaces are the better half of that split but are not clean either: they
account for 38 of the `.tsx` uses and `components/common/` for 2, and every one of
those is a `--muted`, `--border`, `--bg` or `--red` that has a semantic
equivalent — `--text-muted`, `--border-default`, `--surface-canvas`,
`--status-danger` — which would have served. Read the semantic layer as additive
and partly adopted: the intended direction of travel for colour, exactly as the
slicing above is for structure, not a boundary the tree obeys.

**Known gap — the semantic layer carries no themes.** Its stated purpose was to
be the single place a light, dark or high-contrast variant swaps, leaving the
primitives and the components untouched. The dashboard ships exactly one theme,
and `tokens.css` says so at the root: it declares `color-scheme: dark` precisely
so the user agent paints the controls CSS cannot reach — checkbox and radio
glyphs, scrollbars, `<select>` popups — in dark instead of punching light holes
through the surfaces, and pins the checked state with `accent-color`. No
`prefers-color-scheme` block exists anywhere in the frontend and there is no
theme switch, so a second set of semantic values has never been written. The one
user preference the stylesheets do honour is `prefers-reduced-motion: reduce`, in
`motion.css`.

---

## 11. Disclosure levels: what a screen shows before you ask

The dashboard serves several kinds of reader at once — someone launching a
first run, someone reading a search tree, someone diagnosing a stalled
process, someone auditing a governance decision, someone reading raw
artifacts. The refresh answered that with one screen per subject whose *depth*
varies, not one application per reader. The consequence is worth stating
because it is the reason a whole category of design is absent: no screen is
role-aware, no route carries a permission predicate (§2), and nothing in the
product models a reader at all. Depth is something the reader opens, never
something they are granted.

Depth is described on a five-level ladder, P1 to P5. The level names are not
decoration — they are the vocabulary the source uses to decide where a piece
of information belongs, and they appear verbatim in component comments and
test names.

| Level | Material | Intended default |
|---|---|---|
| P1 | Run state, current phase, the reason it is blocked, the next action | Always visible |
| P2 | Score summary, tree, epoch, the main artifacts | Always visible |
| P3 | Evidence, the reason for a transition, config diff, resource detail | One interaction away |
| P4 | Traces, logs, per-node lineage, links to raw events | One or two interactions away |
| P5 | Raw JSON and YAML, internal ids, debug payloads | Developer Mode only |

Read the last column as intent. Three of the five rungs are built, and where
the tree departs from the table it is worth knowing which way.

**Where the ladder is implemented.** The run Overview (`#/overview?run=`) is
the one screen built to it explicitly, and only its P1, P2 and P4 rungs exist.
P1 is the labelled row block — lifecycle badge, research phase, last-update
freshness, and for a governed run a separate governance-stage row carrying the
current epoch and the utility policy hash — with a blockers panel above it
that appears when a governed run's read model reports degraded reasons or one
of its three integrity flags is false (transitions chain, registry snapshot,
audit chain). P2 is the three counters (nodes explored, review score, best
metric) and the workspace links out to the tree, the config browser and, for a
governed run, Governance. P4 is the collapsible log explorer, and it is the
rung that shows what "lazy" has to mean here: while the panel is collapsed
nothing is fetched at all, which its test asserts directly rather than
checking that the markup is hidden. A rung that renders and then hides its
content is not a rung.

One departure inside the built part: the epoch and the policy hash sit at P2
in the table and render inside the P1 row block, because for a governed run
they are part of "where is this run", not part of "how is it scoring".

**P3 was never built as a layer.** No screen has a labelled P3 rung, and the
level name appears in the source only as the note that `P3+ land later`
(`components/Overview/OverviewPage.tsx` and that directory's `README.md`) —
nothing is labelled P3. The material P3 names does exist, but
reaching it means going to another workspace rather than opening something in
place: the committed epoch detail on the Governance epoch-timeline tab (the
sealed policy body, plus the opening and closing boundary transactions with
their raw-source offsets), per-leaf provenance in the config browser, the
effective-config diff against defaults in the Studio's launch panel, resource
and process detail on the legacy Monitor page. Read P3 as a description of the
material, not as a promise about how few clicks reach it.

**P5 is Developer Mode, and only on legacy screens.** The flag is
`localStorage['ari_dev_mode']`, read through one hook (`hooks/useDevMode.ts`),
and the surfaces that consult it are all legacy: the Monitor sections and its
GPU monitor, the legacy Results `publish.yaml` editor, the wizard's resource
step, the legacy Tree detail panel, the Settings page that owns the toggle,
and the root error boundary's stack trace (§2). No v2 workspace imports the
hook, so on a v2 screen there is no P5 rung to open. The specification paired
P5 with a permission check as well; that half cannot exist here, because a
bearer token is all-or-nothing and nothing models a user (§2). Developer Mode
changes display density only. It is not an authorization boundary, and nothing
it reveals is withheld from an unauthenticated caller who asks the API
directly — see the [Dashboard Guide](../guides/dashboard.md), "The legacy
screens, and when to use them".

**There is no global run-context element.** P1 was specified to be present on
*every* run-scoped screen, as one persistent piece of shell carrying project and
run identity, lifecycle, phase and freshness, the execution mode and the paper
mode, the governance capability with its epoch and policy hash, a resource and
cost summary with an alert count, and the connection state. That element does
not exist. It is a known gap, and an uneven one: most of what P1 lists is on
screen somewhere, just never in one place and never on every screen.

What the shell itself carries is the legacy active-checkpoint picker above the
nav — the checkpoint count, a `<select>` bound to the process-wide active
checkpoint, and a status label with a running dot read straight from `/state`
(§4). No v2 workspace reads any of it; the structural scan in
`src/__tests__/appContextScope.test.ts` is what keeps it that way, and a v2
workspace takes its run from `?run=` instead. So the picker describes whichever
checkpoint is selected process-wide, which need not be the run the open
workspace is showing.

The rest is scattered by screen. Lifecycle and research phase render on the run
Overview and nowhere else. The current epoch and the utility policy hash render
on the Overview's governance row for a governed run, and again inside the
Governance workspace — which is also the only place the execution mode and the
paper mode appear as the two independent chips the vocabulary requires, read
there from the RQGM capability model (§9). Run identity is per-screen: every
run-scoped v2 workspace prints its own `?run=` value. So is connection state —
the run Overview, the Tree workspace, Governance and the Projects portfolio each
raise their own freshness banner when the event stream is not live, the config
browser raises one when a refetch fails over cached data, and the Ideas and
Results workspaces subscribe to no stream and show no freshness at all.

Two items on P1's list have no run-scoped home at all. A resource-and-cost
summary is a legacy figure: `/state` carries the parsed `cost_summary.json` as
`cost` (see [REST API Reference](../reference/rest_api.md), "Typed contracts
(stable endpoints)") and the legacy Monitor page renders it beside its resource
cards, while nothing under `/api/v1` mentions cost — so a v2 workspace would
have nothing to show even if the shell had a place to show it. And the nearest
thing to an alert count is the "Needs attention" tile on the Projects portfolio,
which counts runs whose status is `failed`, `stopped` or `unknown`: a portfolio
statistic, not a per-run badge. The "next action" P1 promises is thinner still —
the create, import and resume links on the empty Projects page, all three of
which open the launch wizard. A run that is blocked names its blockers and stops
there.

Treat "P1 is always visible" as a per-screen intent that the run Overview meets
and that no other screen was built to.

---

## See also

- [Dashboard Guide](../guides/dashboard.md) — how to drive the surfaces this
  page explains.
- [ARI Architecture](architecture.md) — the system the dashboard observes.
- [Research and Governance State](research_and_governance_state.md) — the
  state model the shell renders, and the truth rules it must not blur.
- [Constitutional ARI-RQGM Architecture](rqgm_architecture.md) — the
  governance kernel whose committed artifacts the read models project.
- [REST API Reference](../reference/rest_api.md) and
  [Internal Boundaries](../reference/internal_boundaries.md).
