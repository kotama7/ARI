---
sources:
  - path: ari-core/ari/cli/commands.py
    role: implementation
  - path: ari-core/ari/viz/server.py
    role: implementation
  - path: ari-core/ari/viz/checkpoint_finder.py
    role: implementation
  - path: ari-core/ari/viz/checkpoint_lifecycle.py
    role: implementation
  - path: ari-core/ari/viz/api_capabilities.py
    role: implementation
  - path: ari-core/ari/viz/api_workflow.py
    role: implementation
  - path: ari-core/ari/viz/api_experiment.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/App.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/app/routeRegistry.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/Layout/Sidebar.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/Overview/OverviewPage.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/Overview/LogsPanel.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/TreeV2/TreeV2Page.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/TreeV2/TreeTablePanel.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/Workflow/WorkflowPage.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/shared/realtime/eventStream.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/hooks/useRunEvents.ts
    role: implementation
  - path: ari-core/ari/viz/v1/logs.py
    role: implementation
  - path: ari-core/ari/viz/v1/router.py
    role: implementation
  - path: ari-core/ari/viz/v1/launch.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/__tests__/routeNavParity.test.tsx
    role: test
  - path: ari-core/tests/test_launch_config.py
    role: test
  - path: ari-core/ari/viz/frontend/scripts/capture_screenshots.mjs
    role: doc
  - path: scripts/setup/setup_env.sh
    role: config
last_verified: 2026-08-13
---

# Dashboard Guide

A walkthrough of the ARI dashboard as it ships today: how to start the
server, what each workspace answers, how to share a link to exactly what
you are looking at, and what the freshness banner means.

The dashboard runs two shells side by side. The **v2 workspaces**
(Projects, Overview, Tree, Ideas, Results, Governance, Config, Studio)
are gated behind one server capability flag; every **legacy screen** stays
registered and reachable at its original URL in both modes. Nothing was
removed.

## Start the server

Two entry points, same server:

```bash
# 1. CLI — a checkpoint directory is a REQUIRED argument
ari viz path/to/checkpoints/20260727120000_my_run --port 8765

# 2. Module — checkpoint optional; pick one in the GUI afterwards
python -m ari.viz.server --port 8765
```

`start.sh` uses form 2 (`ARI_GUI_PORT`, default `8765`) so the dashboard
comes up before you have chosen a run. On startup you get:

```text
  ⚗️  ARI Viz running at http://localhost:8765/
  📁  Checkpoint: /…/checkpoints/20260727120000_my_run
  🔌  WebSocket:  ws://localhost:8766/ws
  Ctrl+C to stop
```

The WebSocket always listens on **HTTP port + 1**. If that port is not
reachable (a tunnel forwarding only one port, a proxy that does not remap
it) the tree stream degrades to polling — the dashboard keeps working.

By default both servers bind **loopback only** (`127.0.0.1` plus `::1`
when available). Anything beyond `localhost` is an explicit opt-in — see
[Remote access](remote_access.md).

The React bundle is served from `ari-core/ari/viz/static/dist/`. If that
directory is missing or stale, rebuild it from
`ari-core/ari/viz/frontend/` with `npm ci && npm run build` (Vite writes
straight into `../static/dist`).

## Which checkpoint the server starts on

The two entry points differ in more than ergonomics. `ari viz <dir>` takes
the checkpoint directory as a **required** argument, so the active
checkpoint is exactly the one you named. `python -m ari.viz.server` makes
it optional — and started without one, the server does **not** stay empty.

In that case it enumerates every checkpoint under the same search roots
the checkpoint list uses, adopts the one with the newest directory mtime
as the process-global active checkpoint, and seeds the launch-config state
(model, provider, profile) from that checkpoint's `launch_config.json`,
falling back to a `launch_config.json` in its parent directory.

Only directories whose name matches the run-id shape — 8 to 14 digits then
an underscore, e.g. `20260727120000_my_run` — are candidates, and
`experiments`, `__pycache__` and `.git` are skipped. If nothing matches,
nothing is selected and the endpoints that need a checkpoint refuse with a
*"No active project"* error.

Two properties of this adoption are worth knowing before you trust what
you see:

- **It is not announced.** The startup banner prints the argument you
  passed — literally `Checkpoint: None` when you passed none — and is not
  rewritten when a checkpoint is adopted afterwards.
- **It is not per-tab.** There is one selection per server process. Every
  browser tab talking to this server shares it, and using the sidebar's
  project picker in one tab moves it for all of them.

What moves the global selection after startup:

| Action | Effect on the global selection |
|---|---|
| the sidebar's project picker (`POST /api/switch-checkpoint`) | sets it to the chosen checkpoint |
| the legacy `POST /api/launch` | points it at the run directory the launch just pre-created |
| deleting the active checkpoint | clears it — nothing is selected afterwards |
| a wizard file upload with nothing selected | creates a staging directory and makes *that* the selection |
| the Studio launch (`POST /api/v1/runs`) | **none** — deliberately, see [Configuration Studio](configuration_studio.md) |

So the run the legacy screens describe after a bare restart is "whichever
checkpoint was touched last", which is not necessarily the run you care
about. The server's own HTTP access log follows the same selection: it is
appended to `{active checkpoint}/viz_access.jsonl`, so with no checkpoint
argument those request lines land in the auto-adopted run.

The v2 workspaces are unaffected. A `/api/v1` read that concerns one run
resolves its checkpoint from the request's own `run_id`, not from the
global selection, so a `?run=` deep link renders the same thing whatever
that selection happens to be. Pass an explicit checkpoint path, or use a
v2 deep link, when you need determinism.

## The capability flag

The frontend asks `GET /api/capabilities` once on mount:

```json
{"gui_v2": true, "server_version": "wave1"}
```

`gui_v2` is `true` unless the server environment sets `ARI_GUI_V2=0` or
`ARI_GUI_V2=false`. Two deliberate behaviours:

- **Fail-open.** If the capability fetch itself fails, the frontend keeps
  the v2 shell on. An API hiccup must never drop a local user into the
  fallback shell.
- **Rollback without a rebuild.** Export `ARI_GUI_V2=0`, restart the
  server, reload the page: v2-only routes resolve to Home exactly like an
  unknown hash, their sidebar entries disappear, and the legacy entries
  come back. No redeploy, no bundle change.

`ARI_GUI_V2` is documented alongside the other GUI switches in
`scripts/setup/setup_env.sh`.

## The workspace map

Every nav entry — label, icon, and the hash a click writes — comes from a
single route registry, so the sidebar cannot drift apart from the router
(pinned by `src/__tests__/routeNavParity.test.tsx`). The sidebar itself
then lays those entries out as one primary action followed by four fixed
groups. With `gui_v2` on it reads:

| Group | Slot | Hash it writes | Kind |
|---|---|---|---|
| *(primary action)* | ✨ New Experiment | `#/new` | legacy (alias of `#/wizard`) |
| Workspace | 📁 Projects | `#/projects` | v2 only |
| Workspace | 🏠 Dashboard | `#/home` | legacy |
| Workspace | 🗂️ Run archive | `#/experiments` | legacy |
| Current run | 🧭 Overview | `#/overview?run=` | v2 only |
| Current run | 💡 Idea | `#/ideas2?run=` | v2 **takes over** the legacy Idea slot |
| Current run | 🌳 Research tree | `#/tree2?run=` | v2 **takes over** the legacy Tree slot |
| Current run | 📡 Live monitor | `#/monitor` | legacy |
| Current run | 📊 Paper & results | `#/results2?run=` | v2 **takes over** the legacy Results slot |
| Review & governance | 🏛️ Governance | `#/governance?run=` | v2 only |
| Review & governance | 📚 PaperBench | `#/paperbench` | legacy |
| System | ⚡ Workflow | `#/workflow` | legacy |
| System | 🔧 Run config | `#/config?run=` | v2 only |
| System | 🎛️ Config studio | `#/studio` | v2 only |
| System | ⚙️ Settings | `#/settings` | legacy |

The group headings are labels only — they carry no state and disappear
when the sidebar is dragged narrow enough to collapse to icons. The active
run picker sits above the whole nav, so you confirm what you are operating
on before you choose a workspace.

"Takes over" means only the hash a click writes changes — the slot keeps
the legacy label, icon and position, and `#/tree`, `#/results`, `#/idea`
still resolve to the legacy pages if you type or bookmark them.

The intended path through the v2 workspaces:

```text
Projects ──► Overview ──┬──► Tree      (#/tree2?run=&node=)
  (portfolio) (one run) ├──► Ideas     (#/ideas2?run=)
                        ├──► Results   (#/results2?run=)
                        ├──► Governance(#/governance?run=)  RQGM runs only
                        └──► Config    (#/config?run=)

Studio (#/studio) ──► project defaults / run template / run draft ──► launch
```

**Projects** (`#/projects`) lists every run found under the checkpoint
search roots as one virtual `default` project, above a four-tile counter
strip (all / active / completed / needs attention). Each row's Open column
links to that run's Overview, its paper/results page, and its Config;
clicking the row itself goes to the run-explicit `#/results?run=<run_id>`
(the old `sessionStorage` handoff is still written alongside it, as a
compatibility fallback for older callers). RQGM and paper capabilities are
badges next to the run id rather than their own column.

![The Projects workspace: one table row per run, carrying the run id with its RQGM and paper capability badges, a status badge, node count, review score, best metric, last-updated time, and a single Open column](../assets/images/en/dashboard_projects.png)

**Overview** (`#/overview?run=`) is the per-run landing page: lifecycle
badge, current *research* phase (`idle`/`starting`/`bfts`/`paper`/`review`),
last-update time, node count / review score / best metric, workspace
links, a blockers panel, and the collapsible log explorer. For an RQGM run
the *governance stage* renders as its own separate row — research phase
and governance stage are never merged into one label, and neither implies
the other.

![The Overview workspace for one run: the lifecycle / research phase / last-update rows, the Nodes Explored, Review Score and Best Metric counters, a Workspaces card linking to Tree and Config, and the collapsed logs panel with its Show logs button](../assets/images/en/dashboard_overview.png)

**Tree** (`#/tree2?run=&node=`) is the run-explicit node graph plus an
inspector. **Ideas** (`#/ideas2?run=`) shows `idea.json` (gap analysis,
primary metric, generated hypotheses) plus the BFTS hypothesis list from
the run tree. **Results** (`#/results2?run=`, titled *Paper & results*) is
a read-only summary: review scores, the ORS reproducibility chain, and the
EAR publication lineage as a badge chain. When the run has a paper it also
offers two links out — *Preview / edit paper* (the legacy workspace at
`#/results?run=`) and *Open original PDF* — but edits nothing itself.

![The Tree workspace: the D3 node graph on the left with the run id printed above it, the windowed ARIA tree table on the right, and the inspector column prompting "Select a node in the tree to inspect it"](../assets/images/en/dashboard_tree.png)

Node cards are coloured by their BFTS **label** (`draft` blue, `improve`
purple, `ablation` amber, `debug` red, `validation` green); the run status
is the separate badge inside each card and the word next to each table
row. Colour is never the only carrier of either fact.

**Governance** (`#/governance?run=`) is the RQGM workspace — see
[RQGM governance workspace](rqgm_gui.md). **Config** (`#/config?run=`)
and **Studio** (`#/studio`) are covered in
[Configuration Studio](configuration_studio.md).

![The Config workspace: a resolver-warnings panel, a filter box with the field counter, and the per-category tables listing each dotted path with its effective value, a provenance source badge and a mutability badge; the llm.api_key row reads "secret (reference only)"](../assets/images/en/dashboard_config.png)

![The Studio workspace: the scope tab strip, the template and draft creation controls, the category list on the left, and the generated form on the right with a select, text inputs, the write-only secret control, and the Save changes / Discard edits footer showing the document revision](../assets/images/en/dashboard_studio.png)

The Studio is also where
a **new** run's execution mode (`simple_bfts` / `ari_rqgm`) and paper mode
(`linear` / `rqgm_archive`) are chosen; the RQGM governance and tuning
parameters themselves stay configuration-file only, and no screen can
change the mode of a run that already exists.

**Operations** is not a single route today. Process control, resource and
GPU monitoring live on the legacy `#/monitor` page; secrets, env keys and
the SLURM/container/SSH settings live on `#/settings`; the operator-facing probes are HTTP
endpoints (`/health/live`, `/health/ready`, `/api/v1/diagnostics`) rather
than screens — see [Remote access](remote_access.md).

## Run-explicit URLs and deep links

Every v2 workspace reads its run from the **hash query string**, not from
a hidden session variable:

```text
#/overview?run=20260727120000_my_run
#/tree2?run=20260727120000_my_run&node=node_17
#/ideas2?run=20260727120000_my_run
#/results2?run=20260727120000_my_run
#/governance?run=20260727120000_my_run
#/config?run=20260727120000_my_run
#/studio?template=hpc-baseline
#/studio?draft=draft-0a1b2c3d4e5f
```

Consequences worth knowing:

- **The URL is the state.** Selecting a node in the Tree workspace —
  by canvas click, table click, or <kbd>Enter</kbd> in the table — writes
  `?node=` back into the hash. Copy the address bar and you have shared
  the exact node you were looking at; both the canvas and the side table
  re-render from that one URL.
- **Two runs never mix.** Query caches and realtime subscriptions are
  keyed by run id, so an event for run B can never refresh run A's view.
  Opening two browser tabs on two different `?run=` values is safe.
- **Open the page without `?run=`** and you get an explicit prompt
  ("No run selected — open this page as `#/tree2?run=<run_id>`"), not an
  error and not somebody else's run.
- The Governance deep link from the Tree inspector intentionally carries
  only `?run=` — the Governance page owns its node selection as component
  state, and the UI says so rather than pretending to preselect.

## Live updates, staleness, and reconnection

v2 workspaces subscribe to `GET /api/v1/events/stream` (Server-Sent
Events) with server-side `run_id` and `topics` filters (`run`, `tree`).

The contract is deliberate: **events are invalidations, never data.** An
event tells the page "this resource changed"; the page then refetches the
typed `/api/v1` snapshot. Duplicate or out-of-order events are therefore
harmless, and nothing you see was assembled from a partial event.

The client tracks three connection states:

| State | Meaning | What happens |
|---|---|---|
| `live` | stream open | normal; no banner |
| `reconnecting` | stream errored, retrying | last snapshot stays on screen under the freshness banner; backoff 1s → 2s → 4s … capped at 30s, carrying `last_event_id` so no event is skipped |
| `offline` | errors persisting > 60s | reconnects keep running **and** a bounded 10s poll tick starts refreshing the subscription's own scope |

Whenever the state is not `live` (or a background refetch fails while a
snapshot is already on screen) the page shows the shared freshness
banner:

> Showing last known data.  Last updated: *&lt;timestamp&gt;*   [Refresh]

Read it literally. It means "this view may lag", **not** "the run
stopped". A stalled stream and a stopped run are different facts, and the
dashboard never converts one into the other. The Refresh button forces the
snapshot refetch immediately.

The legacy tree WebSocket (HTTP port + 1) is a separate channel with its
own exponential-backoff reconnect; when it cannot connect, the legacy
pages fall back to their 5-second `/state` poll.

## Keyboard navigation in the tree

`#/tree2` renders the same visible node set twice: the D3 canvas and a
windowed side table. The table is a real ARIA tree
(`role="tree"` / `role="treeitem"` with `aria-level`, `aria-expanded`,
`aria-selected`) with a roving tabindex, so it is the keyboard-complete
equivalent of the canvas:

| Key | Action |
|---|---|
| <kbd>↓</kbd> / <kbd>↑</kbd> | move the focused row |
| <kbd>→</kbd> | expand the focused subtree |
| <kbd>←</kbd> | collapse the focused subtree |
| <kbd>Enter</kbd> | select the node → writes `?node=` and opens the inspector |

Focus is tracked by node id, so expanding or collapsing never silently
jumps focus to a different node. Only the rows inside the viewport (plus
a small overscan) exist in the DOM, so a 10 000-node tree still renders
about 40 rows.

**Large trees are reduced, never silently.** Above the level-of-detail
threshold the view collapses to a shallow structural depth plus the
selected node's ancestor path and its children, and states exactly what
it did:

> Showing 312 of 10420 nodes (depth-limited)   [Expand all]

Expanding an oversized tree flips the banner to "Showing all 10420 nodes"
with a way back to the depth limit. The count is always visible; the
dashboard never shows a pruned tree as if it were the whole tree.

## The log explorer

The Overview page embeds a collapsible log explorer over the run's
append-only `{checkpoint}/ari.log`. It is collapsed by default and fetches
nothing until you open it.

- **Cursor = raw byte offset.** [Load more] appends the next bounded page
  with no gap and no duplicate.
- **Filter without breaking pagination.** The case-insensitive substring
  filter selects which scanned lines are *returned*, never which bytes are
  *consumed*, so changing the filter mid-chain cannot corrupt the cursor.
- **Committed lines only.** A trailing line without its newline is not
  emitted; the cursor parks at its first byte and serves it once the
  newline lands. You never see half a log line.
- **Bounded reads.** Each request scans at most 1 MiB from the cursor —
  the explorer never reads a 5 MB file whole. If the window ends before
  the page limit is reached you get what was found plus an advanced
  cursor.
- **Follow tail** is event-driven, not a timer: each delivered run event
  triggers exactly one fetch from `next_cursor`. While following with the
  stream down, the panel shows its own freshness banner — again, "the log
  view may lag", not "the run stopped".
- A run with no `ari.log` yet answers honestly ("No log file yet") instead
  of showing an empty-but-healthy log.

For PaperBench job logs and the legacy whole-file `/api/logs` stream, use
the legacy screens described below.

## The legacy screens, and when to use them

Every legacy route still exists and still works — in both flag states.
Reach for them when the v2 workspace is deliberately read-only:

| Legacy route | Still the only place for |
|---|---|
| `#/home` | the classic single-checkpoint landing page |
| `#/experiments` | the checkpoint list with lineage columns |
| `#/monitor` | starting/stopping stages, process control, resource + GPU monitoring |
| `#/tree` | the original tree page (the v2 workspace reuses its D3 component) |
| `#/results` | the full paper/PDF editor **and every EAR mutation** — curate, `publish.yaml` editing, publish, promote |
| `#/new` (`#/wizard`) | the original guided launch wizard |
| `#/idea` | the `/state`-derived idea cards for the active checkpoint |
| `#/workflow` | the React-Flow workflow editor, skill phases, disabled tools |
| `#/settings` | the full `/api/settings` env-key surface and the Developer Mode toggle (the eight allowlisted secrets — six API keys plus `ZENODO_TOKEN` and `ARI_REGISTRY_TOKEN` — are also writable from the Config Studio secret field) |
| `#/paperbench`, `#/paperbench/import`, `#/paperbench/run`, `#/paperbench/results` | the whole PaperBench surface (see [PaperBench GUI guide](paperbench/paperbench_gui.md)) |

The v2 Results workspace links out to `#/results` for exactly this reason
and says so on the page: *"This workspace is read-only — curate,
publish.yaml editing, publish, and promote run on the legacy page only."*

Two legacy behaviours changed for safety and are worth knowing before you
click:

- **Workflow writes need an active project.** With no checkpoint
  selected, the workflow write endpoints refuse with 400 instead of
  silently rewriting the bundled `workflow.yaml`.
- **Destructive actions are two-step.** Deleting a checkpoint, stopping
  all processes, and stopping the GPU monitor now require a server-issued,
  single-use confirmation challenge; the dialog shows the exact target the
  server echoed back. See [Remote access](remote_access.md).

**A workflow edit belongs to one checkpoint.** `#/workflow` edits the active
checkpoint's own `workflow.yaml`; when that checkpoint has no copy yet, the
first write copies the bundled `ari-core/config/workflow.yaml` into it and edits
the copy, so the bundled file is never written. Starting a new experiment does
not carry the edit forward — the wizard at `#/new` (`POST /api/launch`) and the
Config Studio at `#/studio` (`POST /api/v1/runs`) each seed the new run from the
bundled file again and then apply their own launch-time toggles to that fresh
copy. Your change takes effect when the same checkpoint runs again, and nowhere
else; and because the wizard makes the new run the active checkpoint, the editor
you return to is already pointing at the new copy. The toolbar prints the path
the editor loaded, but the page never says that this path is the entire scope of
your edit, and no warning appears at launch — that missing statement is a known
gap.

**Developer Mode** is a client-only toggle (`localStorage['ari_dev_mode']`)
that reveals raw JSON tabs, raw YAML editors and full stack traces. It
changes display density only — it is not an authorization boundary.

## Regenerating these screenshots

The screenshots on this page (and in the [QuickStart](../getting-started/quickstart.md),
[Configuration Studio](configuration_studio.md) and
[RQGM governance workspace](rqgm_gui.md) guides) are captured from a real
running server by `npm run capture:screenshots`, 15 routes × 3 locales.
Any change to the shell invalidates all 45 at once, so they are always
regenerated together — a half-updated set is worse than a uniformly stale
one, because the reader cannot tell which page is current.

The command, the RQGM fixture checkpoint the Governance shots need, and
the headless-Chromium font and library prerequisites are documented once,
next to the script:
[`ari-core/ari/viz/frontend/scripts/README.md`](../../ari-core/ari/viz/frontend/scripts/README.md).
Read it before capturing — a capture with the wrong fonts installed still
exits 0 and silently writes tofu boxes, so the last step is always to open
the images and look at them.

## See also

- [Configuration Studio](configuration_studio.md) — inspect, edit, and launch configuration.
- [RQGM governance workspace](rqgm_gui.md) — the Governance tabs.
- [Remote access](remote_access.md) — binding beyond localhost, tokens, health probes.
- [Execution modes](execution_modes.md) — how a run becomes an RQGM run, from config, env, or the Studio.
- [GUI cutover runbook](gui_cutover_runbook.md) — the flag rollout and rollback levers.
- [REST API reference](../reference/rest_api.md) — the legacy JSON API.
- [Environment variables](../reference/environment_variables.md).
