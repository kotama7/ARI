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
  - path: ari-core/ari/viz/services/__init__.py
    role: implementation
  - path: ari-core/tests/test_gui_config_shadow_legacy.py
    role: test
  - path: ari-core/tests/test_gui_state_facade_freeze.py
    role: test
last_verified: 2026-08-07
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
`Layout` (sidebar, header, checkpoint picker). Nothing was deleted to make
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
  exist as routes with no nav entry — they are opened from inside a page.
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
governance alert is visible only on the page that renders it. Routes carry no
permission predicate either, and will not need one while the server has no user
model — a bearer token is all-or-nothing, and sessions and multi-user are out
of scope. Capability gating is exactly one marker: `guiV2` on the registry
entry, plus the `V2_ONLY_ROUTES` dispatch set in `App.tsx`.

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

**Durable preferences have no store.** Locale (`ari_lang`, default `ja`),
developer mode (`ari_dev_mode`) and the remote bearer token (`ari_gui_token`)
go straight to `localStorage`, each behind its own one-key accessor —
`i18n.storedLang()`, `useDevMode.isDevMode()`, `client.getGuiToken()` — and the
Settings page still reads `ari_lang` from `localStorage` itself. There is no
preference-store abstraction over the three, no schema for these keys and no
migration path, so a rename or a re-type is a per-key edit with no single place
to make it. A preference layer was specified for the refreshed shell and is not
implemented; treat the three key names as the actual contract.

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

Two properties of this seam are worth stating explicitly because they are
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
  lists; long logs are cursor-paged over stable offsets; no file *content*
  rides these endpoints.

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
| `components/<Screen>/` | One directory per screen, legacy and v2 side by side (`Tree/` and `TreeV2/`, `Results/` and `ResultsV2/`), each exporting the page components the registry lazy-loads — plus `common/` for presentational primitives and `Layout/` for the sidebar and header. |
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
