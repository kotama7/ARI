---
sources:
  - path: ari-core/ari/viz/api_capabilities.py
    role: implementation
  - path: ari-core/ari/viz/server.py
    role: implementation
  - path: ari-core/ari/viz/routes.py
    role: implementation
  - path: ari-core/ari/viz/auth.py
    role: implementation
  - path: ari-core/ari/viz/health.py
    role: implementation
  - path: ari-core/ari/viz/v1/router.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/app/routeRegistry.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/context/AppContext.tsx
    role: implementation
  - path: ari-core/tests/test_gui_state_facade_freeze.py
    role: test
  - path: ari-core/tests/test_gui_config_shadow_legacy.py
    role: test
  - path: ari-core/ari/viz/frontend/src/__tests__/appContextScope.test.ts
    role: test
  - path: scripts/check_viz_api_schema.py
    role: test
  - path: scripts/check_dashboard_ux.py
    role: test
  - path: scripts/check_bundle_budget.py
    role: test
  - path: scripts/snapshot_contracts.py
    role: test
  - path: scripts/setup/setup_env.sh
    role: config
last_verified: 2026-07-30
---

# GUI Cutover Runbook

The dashboard refresh ships the v2 workspaces **next to** the legacy
screens: both are in the same bundle, both are reachable, and a single
environment variable decides which chrome the browser gets.  This runbook is
the operational half of that arrangement — how to promote v2 to the default,
what to watch while you do, how to get back, and what has to be true before
any legacy code is deleted.

For the behaviour changes themselves (what used to work and now refuses, and
why), see [Migration Guide → GUI refresh](migration.md#gui-refresh-v2-dashboard).

**Scope note.** ARI ships no telemetry pipeline.  Every "signal" below is
something an operator reads from a local surface — `/api/v1/diagnostics`,
`/health/ready`, the checkpoint's `viz_access.jsonl` and
`launch_events.jsonl`, the server's stderr, or the browser devtools network
panel.  Treat the rollout as a supervised dogfood, not an instrumented
canary.

## 1. Levers

All levers are environment variables read when `ari viz <checkpoint>` starts.
Set the variable, restart the server; there is no rebuild and no redeploy.
They are declared with their rationale in `scripts/setup/setup_env.sh`.

| Lever | Default | Exact effect when flipped |
|---|---|---|
| `ARI_GUI_V2` | on (any value but `0`/`false`) | `GET /api/capabilities` reports `gui_v2: false`; the SPA hides v2-only nav entries, and v2-only routes fall back to Home.  Legacy routes, legacy hash URLs, and every `/api/*` endpoint are untouched.  A *failed* capabilities fetch is treated as `gui_v2: true`, so an API hiccup can never strand the dashboard in the fallback shell. |
| `ARI_GUI_BIND` | unset → `127.0.0.1` + `::1` | Any explicit value binds exactly that host: `'::'` restores the pre-refresh all-interfaces dual-stack bind, `'0.0.0.0'` the IPv4 wildcard.  A non-loopback value also arms the `ARI_GUI_TOKEN` gate. |
| `ARI_GUI_CORS_ANY` | off | `1` restores `Access-Control-Allow-Origin: *` on every response that previously carried it, instead of the same-origin echo. |
| `ARI_GUI_CHALLENGES` | on | `0` lets `POST /api/delete-checkpoint`, `POST /api/stop`, and `POST /api/gpu-monitor` (`action=stop`) execute without a server-issued `challenge_id`.  The `POST /api/v1/challenges` endpoint remains, so two-step clients keep working. |
| `ARI_GUI_CSP` | on | `0` stops sending `Content-Security-Policy`, `X-Content-Type-Options`, and `Referrer-Policy` on the SPA index and `/static/`.  The legitimate use is a reverse proxy that remaps the WebSocket port, where the CSP `connect-src` would otherwise block the tree stream. |
| `ARI_GUI_TOKEN` | unset | On a non-loopback bind this is the bearer token every request outside `/health*` must present.  Unset on a remote bind, the server generates a 32-hex token at startup and prints it once to stderr — there is no unauthenticated remote start. |
| `ARI_GUI_AUTH` | on | `0` disables the remote token gate entirely (an authenticating reverse proxy in front is the only sane reason). |
| `ARI_GUI_HEALTH` | on | `0` returns `/health/live` and `/health/ready` to the SPA HTML fallback and makes `GET /api/v1/diagnostics` answer the typed 404. |

**Only `ARI_GUI_V2` is a rollout flag.**  The other seven are security
kill-switches, and each one re-opens exactly the risk its change closed.
Do not bake them into a deployment profile to "make something work"; use
them for an incident, record why, and take them back out.  Combination
policy: the supported matrix is *the defaults*, plus one lever at a time,
plus the documented remote-mode pair (`ARI_GUI_BIND` + `ARI_GUI_TOKEN`).
Anything else is untested.

## 2. Pre-cutover checklist

Every row is a hard gate.  Run them on a clean worktree with a pinned
toolchain — a red baseline invalidates the whole exercise, because you can no
longer tell a cutover regression from a pre-existing failure.

| Gate | Command | Pass condition |
|---|---|---|
| Frontend types | `cd ari-core/ari/viz/frontend && npm ci && npm run typecheck` | exit 0 |
| Frontend unit / a11y / contract suites | `cd ari-core/ari/viz/frontend && npm test` | exit 0 — includes the route/nav parity, shell a11y baseline, Settings contract, external-script guard, workflow-revision, Studio launch, and dangerous-operation suites |
| Production build | `cd ari-core/ari/viz/frontend && npm run build` | exit 0, output in `ari-core/ari/viz/static/dist/` |
| Bundle budget | `python scripts/check_bundle_budget.py --fail-on-regression` | exit 0, no net-new violation (run after the build) |
| Backend + viz tests | `python -m pytest ari-core/tests -q` | exit 0 |
| Security regression suites | `python -m pytest ari-core/tests -q -k "gui_bind_cors or gui_path_proxy_hardening or gui_confirmation_challenges or gui_csp_headers or gui_remote_auth or gui_secret_readiness or gui_workflow_write_guard"` | exit 0 — these are the MN-2/4/5/6/7/8 refusals |
| Legacy facade freeze | `python -m pytest ari-core/tests/test_gui_state_facade_freeze.py -q` | exit 0 — `/state` neither grew nor shrank |
| Config/launch shadow parity | `python -m pytest ari-core/tests/test_gui_config_shadow_legacy.py -q` | exit 0 — legacy Settings save+launch and the new resolver agree per leaf, with only the explicitly allowlisted divergences |
| Contract snapshots | `python scripts/snapshot_contracts.py --surface all --check` | exit 0 — the `viz` surface pins the REST inventory and response keys |
| OpenAPI freshness | `python -m ari.viz.v1.openapi` (from `ari-core/`) | exit 0 — the committed `ari/viz/v1/openapi.json` matches the router |
| REST schema drift | `python scripts/check_viz_api_schema.py --fail-on-regression` | exit 0, no net-new drift against the frozen allowlist |
| Dashboard UX checker | `python scripts/check_dashboard_ux.py --fail-on-regression` | exit 0, allowlist not grown |
| Docs gates | `python scripts/check_docs_source_sync.py`, `python scripts/docs/check_doc_sources.py`, `python scripts/readme_sync.py --check`, `python -m pytest scripts/tests/ -q` | all exit 0 |

Then prove the security posture on the running server (loopback default):

```bash
ari viz /path/to/checkpoint --port 8765 &

curl -s http://127.0.0.1:8765/health/live                 # {"status":"ok"}
curl -s http://127.0.0.1:8765/health/ready                # status ok|degraded, five checks
curl -si http://127.0.0.1:8765/ | grep -i 'content-security-policy\|nosniff\|referrer-policy'
curl -si -X POST http://127.0.0.1:8765/api/stop -d '{}'   # 428, no process touched
curl -s 'http://127.0.0.1:8765/codefile?path=/etc/passwd' # 404
ss -ltnp | grep 8765                                      # bound to 127.0.0.1 / ::1 only
```

Gates that are **not** machine-enforced today, and must therefore be signed
off by hand:

- **Browser performance metrics** (LCP/INP/CLS, route interaction latency).
  The jsdom test harness cannot measure layout, paint, or input timing, and a
  shared CI runner is too noisy for a pass/fail budget.  Bundle weight *is*
  enforced (`check_bundle_budget.py`); the browser half is a manual profile
  on a fixed machine, recorded in the release evidence.
- **Cross-browser critical journeys.**  The suites are vitest/jsdom; the only
  Playwright run in this repo is the documentation screenshot capture
  (`npm run capture:screenshots`, headless Chromium only), which asserts
  nothing.  The critical journeys (Settings, new run, launch, resume, monitor,
  tree/results, workflow, RQGM, security) are walked by hand before a
  default-on change.

## 3. Staged rollout

Run every remaining slice through these three stages.  A "slice" is one
route or workspace, not the whole shell — the flag policy is deliberately
per-slice so a problem rolls back one screen, not the dashboard.

**Stage 1 — dogfood.**  Maintainers only, on their own checkpoints, flag on.
Use a real run with real artifacts, not a fixture.  Watch: does the v2
workspace show the same numbers as the legacy screen for the same run?  Does
a second run in a second tab stay isolated?  Exit when the slice's own tests
are green and no legacy/v2 disagreement is open.

**Stage 2 — opt-in.**  The v2 route is reachable and documented, the legacy
route keeps its nav entry, and users choose.  Watch: which one people
actually open, and whether anyone falls back mid-task.  Exit when the slice
has been exercised on a large checkpoint, a corrupt/partial checkpoint, and
an old (pre-refresh) checkpoint.

**Stage 3 — default-on.**  The v2 route takes over the legacy nav slot via
the route registry's `navReplaces`, so the sidebar entry looks identical and
only the hash it writes changes.  **The legacy URL keeps working in both
modes** — that is the parity invariant, and it is what makes the rollback in
§5 instant.  Exit when the slice has run default-on for at least one minor
release with the rollback lever available.

Where the program stands today: `ARI_GUI_V2` ships **default-on**; Projects,
Overview, Governance, ConfigBrowser, and Studio have their own nav entries;
TreeV2, IdeasV2, and ResultsV2 have taken over the Tree, Idea, and Results
slots via `navReplaces`; Settings, Wizard, Monitor, Workflow, Home,
Experiments, and PaperBench are still the legacy screens with their legacy
nav entries.  Settings → Studio and Wizard → Studio launch are the slices
that still have to walk stages 1–3.

Signals to watch during any stage (all read locally):

| Signal | Where to read it |
|---|---|
| Route success/error, schema mismatch, adapter mismatch | browser devtools network panel; typed `/api/v1` error envelopes carry a `request_id` that also appears in `viz_access.jsonl` |
| Config validation failure category, save conflict rate | the draft `validate` responses (`details.errors` paths) and workflow 409 conflict banners |
| Launch accepted / started / failed, idempotency collisions | `{checkpoint}/launch_events.jsonl` (`draft → validating → accepted → spawned` / `failed`) and `{workspace_root}/gui_store/launches/` |
| SSE reconnect / fallback, projector lag, stale views | `GET /api/v1/diagnostics` (`sse.subscribers`, `sse.buffer_len`, `watcher.last_scan_age_s`) and `GET /health/ready` (`degraded` with the failing check named) |
| Legacy route / legacy API fallback usage | `viz_access.jsonl` request paths — legacy `/api/*` and `/state` hits after a slice went default-on |
| Bundle size | `python scripts/check_bundle_budget.py` (per-chunk gzip vs class budget) |
| Browser performance percentiles | manual profile on the fixed reference machine (not CI-enforced) |

## 4. Stop and rollback conditions

Stop the rollout — or roll back a slice that is already default-on — if any
of these occurs.  This list is the release gate; do not soften a row into a
follow-up ticket while the rollout continues.

- **Cross-run data mix, secret exposure, or unauthorized mutation.**  Any of
  the three is an immediate full stop, not a slice rollback: go to §5.3.
- **Config or launch shadow mismatch beyond threshold.**  The legacy
  save+launch path and the new resolver must agree per leaf, with only the
  explicitly allowlisted divergences; a new divergence stops the rollout.
- **Score lineage disagreeing with the source events.**  The governance read
  model re-derives nothing — if a displayed lineage does not match
  `rqgm_transitions.jsonl` / `rqgm_audit.jsonl`, the view is wrong and
  stops.
- **Old-checkpoint or `simple_bfts` identity regression.**  A pre-refresh
  checkpoint must open unchanged, and a `simple_bfts` run must stay
  byte-identical to pre-refresh ARI.
- **Critical journey, a11y, or performance hard-gate failure.**  Any red gate
  from §2, including the manually signed-off ones.

## 5. Rollback procedure, by layer

Roll back the *narrowest* layer that fixes the symptom.  Only §5.3 requires
touching a running experiment.

### 5.1 Flag layer (seconds, no rebuild)

```bash
export ARI_GUI_V2=0
# restart: ari viz /path/to/checkpoint --port 8765
```

`GET /api/capabilities` then reports `gui_v2: false`; the sidebar drops the
v2 entries, v2-only routes fall back to Home, and the legacy screens are back
in their own slots.  Every legacy hash URL and every `/api/*` endpoint was
already working, so nothing else changes.  Drafts, templates, and
`resolved_config.json` written by v2 stay on disk and are simply not read by
the legacy screens.

### 5.2 Bundle layer (minutes)

If the problem is in the built assets rather than the flag, restore the
previously released `ari-core/ari/viz/static/dist/` tree (the SPA index and
`/static/` are served straight from it) and restart.  Rebuild with
`npm ci && npm run build` from `ari-core/ari/viz/frontend` if you need to
re-cut it from a known-good commit.  Keep the previous bundle for at least
one minor release — that retention *is* the rollback window.

### 5.3 Security levers (incident path)

Use these when the trigger is exposure, not a UI defect.  In order:

1. **Rebind to loopback.**  Unset `ARI_GUI_BIND` (and `ARI_GUI_CORS_ANY`)
   and restart.  The server then listens on `127.0.0.1` + `::1` only and
   echoes CORS for its own origin only.  Reach it again through an SSH local
   forward.
2. **Revoke the token.**  Change or unset `ARI_GUI_TOKEN` and restart: every
   previously issued token stops working immediately (a remote bind with the
   variable unset mints a fresh one and prints it once to stderr).  Tell
   operators to clear the browser's `localStorage` key `ari_gui_token`.
   Because the access log redacts `token=` to `***`, an old token is not
   recoverable from `viz_access.jsonl`.
3. **Stop the processes.**  `POST /api/stop` needs a challenge from
   `POST /api/v1/challenges` (`action: "stop-all"`, `target: "*"`); the
   two-step is the point, so do not reach for `ARI_GUI_CHALLENGES=0` here.
   Out of band, stop the `ari viz` process itself — GUI-launched runs are
   separate `python3 -m ari.cli run` subprocesses and survive the server, so
   stop them explicitly if the incident calls for it.
4. **Re-run the §2 posture checks** before letting anyone back in.

### 5.4 Data safety

There is nothing to undo.  Everything the refresh writes is additive —
`{checkpoint}/resolved_config.json`, `{checkpoint}/launch_events.jsonl`,
`{workspace_root}/gui_store/` (drafts, templates, launch claims) — and older
ARI ignores all of it.  No checkpoint is rewritten in place, so a rollback
never requires a downgrade migration.  Confirm in a rollback drill that a
running run, an open draft, saved settings, an edited workflow, and the RQGM
views all survive the flag flip.

## 6. Legacy removal

Removal is a separate decision from default-on, and it is one-way.  Nothing
below may be deleted until **all** of these hold:

- the replacing v2 slice has been default-on for at least one minor release
  with the rollback lever available, and the rollback drill passed;
- usage evidence shows the legacy surface is unused (no legacy route or
  legacy `/api/*` hits for the replaced screen in `viz_access.jsonl` over the
  observation window);
- the compatibility matrix in §7 has been re-run green;
- the removal (or an explicit retention) is recorded as an ADR, and any
  public-API removal follows the deprecation programme in
  `CONTRIBUTING.md` and `docs/about/release_policy.md` — if it is a breaking
  removal, it goes to a major release.

Remove in this order.  The order is a dependency chain: each item's consumers
must be gone before it is.

| # | Removal | Tied gate |
|---|---|---|
| 1 | **Legacy pages** — the Settings, Wizard, Tree, Idea, Results, and Workflow screens, one at a time | the replacing workspace's own capability / a11y / performance gate is green, and the route–nav parity test plus the dashboard UX checker's hidden-route allowlist are re-frozen in the same change |
| 2 | **AppContext remote state** — `context/AppContext.tsx`, i.e. the 5-second `/state` poll, the tree WebSocket mirror, and the global active checkpoint | every legacy page above is gone and the structural guard `src/__tests__/appContextScope.test.ts` passes with **no** exception entries (its one documented exception, the IdeasV2 research-goal card, must be re-sourced from `/api/v1` first) |
| 3 | **The `/state` facade** — the `/state` branch in `routes.py` and `services/state_service.build_app_state` | AppContext is gone; `test_gui_state_facade_freeze.py` is retired in the same change (its whole purpose is to forbid growth *until* this deletion), and the `viz` contract snapshot is regenerated |
| 4 | **The port+1 WebSocket** — the `ws_serve` server, `websocket.py`, and `hooks/useWebSocket.ts` | every realtime consumer reads `GET /api/v1/events/stream` instead; only then may the `ws://`/`wss://` sources be dropped from the CSP `connect-src`, since that allowance exists solely for this socket |
| 5 | **Duplicate constants and CSS** — legacy route/nav literals and duplicated design tokens | the route registry is the single source for routes, nav, breadcrumbs, and aliases (parity test green) and no legacy page imports the duplicates |

After each removal, regenerate the contract snapshots
(`python scripts/snapshot_contracts.py --surface viz --update`) and re-run the
full §2 checklist.  A removal that requires an allowlist to *grow* is not
ready.

## 7. Compatibility matrix

Re-run this matrix before any removal in §6, and record the result in the
release evidence.  It is the same matrix the program uses as its cutover
gate:

- fresh install × upgrade;
- legacy UI × v2 UI, each against the legacy `/api/*` and the canonical
  `/api/v1`;
- `simple_bfts` × RQGM exploration on/off × paper mode on/off;
- new run × resume × clone;
- laptop × HPC profile × cloud profile;
- local loopback × SSH tunnel × HPC reverse proxy;
- small × medium × large × corrupt checkpoint;
- English × Japanese × Chinese.

## See also

- [Migration Guide → GUI refresh](migration.md#gui-refresh-v2-dashboard) —
  the before/after of every user-visible change, with its rollback lever.
- [HPC Setup Guide](hpc_setup.md) — tunnelling and remote operation.
- [Troubleshooting](troubleshooting.md) — runtime failures and their fixes.
- `scripts/setup/setup_env.sh` — the declared `ARI_GUI_*` levers with their
  rationale, in the form the setup script writes into `.env`.
