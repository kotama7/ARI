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
  - path: ari-core/ari/viz/v1/challenges.py
    role: implementation
  - path: ari-core/ari/viz/v1/openapi.json
    role: schema
  - path: ari-core/ari/viz/frontend/src/app/__tests__/routeRegistry.test.tsx
    role: test
  - path: ari-core/ari/viz/frontend/src/__tests__/routeNavParity.test.tsx
    role: test
last_verified: 2026-07-27
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
  rebuild, no redeploy — see §7.

The migration therefore has no cutover moment to schedule. A workspace is
promoted by giving it a nav slot; it is rolled back by taking the slot away.

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
  `navReplaces` entry onto its target's slot and sorts by `navOrder`.

Two frozen-literal tests pin the result, so a route cannot drift into existing
in the nav but not the router (or vice versa). The practical rules that fall
out of this:

- **Hash URLs are a deployment contract.** They are what users bookmark and
  what the docs cite; the registry preserves historical spellings (the wizard
  still navigates to `#/new`) rather than tidying them.
- **Reachable-but-unlisted is expressible.** `#/paperbench/import|run|results`
  exist as routes with no nav entry — they are opened from inside a page.
- **Unknown hashes fall back to Home** rather than erroring.

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
Results page from a run row still goes through an *implicit* handoff (a
`sessionStorage` key plus a bare `#/results` hash), and the legacy shell also
carries a process-wide *active checkpoint*. Neither is a valid input for a v2
workspace: v2 routes are run-explicit, which is what keeps two runs open in
two tabs from stepping on each other.

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
  checkpoint scanner.

Client-only state (which tab is open, a filter box's text, sidebar width) is
*not* in this cache. The split is: server state is cached and invalidated,
view state is local and ephemeral, and navigation state is in the URL (§3).

---

## 5. Realtime is invalidation, not a source of truth

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

---

## 6. The backend seam

The server is four layers, and each one is allowed to know only about the
layer below it.

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

---

## 7. Read models are disposable projections

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

## 8. Capabilities and kill-switches

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
