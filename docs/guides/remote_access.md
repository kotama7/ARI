---
sources:
  - path: ari-core/ari/viz/server.py
    role: implementation
  - path: ari-core/ari/viz/auth.py
    role: implementation
  - path: ari-core/ari/viz/routes.py
    role: implementation
  - path: ari-core/ari/viz/websocket.py
    role: implementation
  - path: ari-core/ari/viz/health.py
    role: implementation
  - path: ari-core/ari/viz/v1/challenges.py
    role: implementation
  - path: ari-core/ari/viz/v1/queries.py
    role: implementation
  - path: ari-core/ari/viz/api_settings.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/services/api/client.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/shared/realtime/eventStream.ts
    role: implementation
  - path: ari-core/tests/test_gui_remote_auth.py
    role: test
  - path: ari-core/tests/test_gui_bind_cors.py
    role: test
  - path: ari-core/tests/test_gui_csp_headers.py
    role: test
  - path: ari-core/tests/test_gui_health_diagnostics.py
    role: test
  - path: ari-core/tests/test_gui_confirmation_challenges.py
    role: test
  - path: scripts/setup/setup_env.sh
    role: config
last_verified: 2026-08-16
---

# Remote Access and Operations Guide

Everything about running the ARI dashboard somewhere other than the
laptop it is displayed on: the default trust posture, how to open it up
deliberately, and the endpoints an operator needs.

The short version: **the dashboard is a single-operator local tool by
default, and every step away from that is an explicit opt-in.**

## Default posture: loopback only

With no GUI environment variables set:

- the HTTP server binds `127.0.0.1` **and** `::1` (both loopback families,
  so `localhost` works whether your distro resolves it to IPv4 or IPv6);
- the WebSocket server on **HTTP port + 1** binds the same way;
- there is **no authentication** — the loopback bind plus same-origin CORS
  *is* the protection;
- another host on the LAN cannot connect at all.

This is deliberate policy, not a default waiting to be relaxed: an earlier
build bound all interfaces with no authentication and an unconditional
`Access-Control-Allow-Origin: *`, which exposed every endpoint —
including delete, stop, and secret writes — to the whole cluster network.

If you only need the dashboard from another machine, prefer an **SSH
tunnel** (below). Tunnelling keeps the loopback posture intact and needs
no token.

### What the posture does not cover

Stated from the other side: the loopback default, and the remote mode
described below, are a boundary between **hosts**. Neither is a
permission system, and it is worth being blunt about where they stop.

**There is no authorization layer, in either mode.** Local mode has no
credential at all — `resolve_token` returns nothing for a loopback bind,
so the request gate passes everything through. Any process on the machine
that can open a socket to the port therefore has the whole API: writing a
secret through `POST /api/env-keys`, overwriting a file inside a
checkpoint, restarting the memory backend, and — after minting itself the
grant described below — deleting a checkpoint or stopping every
experiment process. A loopback bind separates hosts; it does not separate
the users or the jobs sharing one host.

Remote mode adds a credential and stops there. The bearer token is a
single all-powerful value: it names nobody, it cannot be scoped to a
project or a run, and it is compared against nothing but itself. There is
not yet a boundary a permission check could attach to — the `/api/v1`
surface exposes one virtual `default` project and answers a 404 envelope
for every other project id. Sessions, logout and per-session revocation
do not exist; revoking access means changing `ARI_GUI_TOKEN` and
restarting the server, which revokes it for everyone at once. That is a
decision, not an oversight: [GUI-ADR-13](../adr/gui/GUI-ADR-13-remote-bearer-token.md)
permanently defers sessions, logout, revocation and multi-user to a
future multi-tenant record, and says in its consequences that the single
all-powerful token is not to be extended in place.

**Confirmation challenges are an anti-accident control, not access
control.** Anyone who can call `POST /api/delete-checkpoint` can also
call `POST /api/v1/challenges` and mint the grant it demands — issuance
requires no credential beyond the one the request already carried. What
the two-step buys is that the *server* names the target and the client
must echo that exact single-use grant back, which is what catches a stale
tab, a replayed script, or a bulk action aimed at the wrong path. It is
not a second factor. The vocabulary is narrow by design —
`delete-checkpoint`, `stop-all`, `gpu-monitor-stop`, and nothing else.
Saving, deleting or uploading a file inside a checkpoint
(`POST /api/checkpoint/file/save`, `POST /api/checkpoint/file/delete`,
`POST /api/checkpoint/{id}/file/upload`) and restarting the memory
backend (`POST /api/memory/restart`) execute directly on request.

**`viz_access.jsonl` is a request log, not an audit trail.** Its fields
are the six listed under *Access log* below, and `client` among them is
the peer's network address — so no line names a person, and under the
loopback default every line names the same loopback address. Worse for
after-the-fact reconstruction: nothing is written at all while no
checkpoint is active, and that state does not stop the writes it would
otherwise record. `POST /api/env-keys` edits the project `.env` file and
never touches the checkpoint, so a secret written with no checkpoint
selected leaves no line behind. An absence of lines is not evidence that
nothing happened.

None of this makes the dashboard unsafe for what it is: a single-operator
research tool, run by the person whose runs it displays. It does mean
that "put it behind the token and share the URL" is not a supported
multi-user deployment, and that everyone with access holds every
operator's authority.

## The GUI environment variables

All of them are pre-seeded, commented out, in `scripts/setup/setup_env.sh`.

| Variable | Default | Effect |
|---|---|---|
| `ARI_GUI_V2` | on | `0`/`false` reverts to the legacy shell |
| `ARI_GUI_BIND` | unset → loopback | bind address opt-in (see below) |
| `ARI_GUI_TOKEN` | unset | the bearer token required in remote mode |
| `ARI_GUI_AUTH` | on | `0`/`false` disables the remote token gate |
| `ARI_GUI_CORS_ANY` | off | `1` restores the legacy `ACAO: *` wildcard |
| `ARI_GUI_CSP` | on | `0` drops CSP + nosniff + Referrer-Policy |
| `ARI_GUI_CHALLENGES` | on | `0` disables confirmation challenges |
| `ARI_GUI_HEALTH` | on | `0` disables the health/diagnostics surfaces |

Every one of them except `ARI_GUI_TOKEN` is an intentional rollback lever
carrying a kill-switch register next to its implementation — an ADR-07
register for the six security switches, and the gui_refresh rollout-flag
policy (owner / default / rollback / removal gate) for `ARI_GUI_V2`: turning
one off restores a previously shipped behaviour and unlocks nothing new.
`ARI_GUI_TOKEN` is not a switch but the token value itself — leaving it unset
does not restore anything, it makes the server mint one (see below).

## Opting in to a non-loopback bind

```bash
export ARI_GUI_BIND=0.0.0.0     # IPv4 wildcard
# export ARI_GUI_BIND='::'      # all interfaces, dual stack (the pre-hardening bind)
# export ARI_GUI_BIND=10.0.0.7  # exactly one interface
python -m ari.viz.server --port 8765
```

Resolution rules: unset or blank → `["127.0.0.1", "::1"]`; **any**
explicit value → bind exactly that one host. The WebSocket server follows
the same policy.

A non-loopback value flips the server into **remote mode**, and remote
mode is authenticated. `localhost`, `::1` and any `127.x.y.z` count as
loopback; everything else — including the wildcards — is remote.

## Token authentication in remote mode

In remote mode **every HTTP request except the `/health` prefix** must
present the token, and so must the WebSocket handshake. The gate runs at
the very top of `do_GET` / `do_POST` / `do_PUT` / `do_PATCH` / `do_DELETE`,
before any dispatch or body read.

### Getting a token

Either pin one:

```bash
export ARI_GUI_TOKEN="$(python -c 'import secrets;print(secrets.token_hex(16))')"
```

…or start without one and let the server generate it. This is
**fail-secure**: a remote bind never starts unauthenticated. The generated
token is printed **once**, to stderr, and never to a log file:

```text
  ============================================================
  ARI GUI is bound to a non-loopback address and ARI_GUI_TOKEN
  is not set. A random access token was generated for this run
  (MN-8, ADR-13). It is printed here ONCE and never logged:

      ARI_GUI_TOKEN=<32 hex chars>

  Every request must send 'Authorization: Bearer <token>'
  (SSE/WebSocket: '?token=<token>'). Set ARI_GUI_TOKEN to pin
  a stable token across restarts.
  ============================================================
```

Set `ARI_GUI_TOKEN` explicitly if you want the token to survive restarts
(otherwise every restart mints a new one and every browser must be
re-primed).

### How the browser supplies it

There is no login screen yet. The frontend reads the token from
`localStorage` under the key `ari_gui_token`; prime it once from the
browser console on the page's own origin:

```js
localStorage.setItem('ari_gui_token', '<token>');  // then reload
```

From then on the client attaches `Authorization: Bearer <token>` to every
`fetch`, and appends `?token=<token>` to the two header-less transports.
In the loopback default no key is set, so the request shape is unchanged.

### Why SSE and WebSocket use a query parameter

The browser `EventSource` and `WebSocket` APIs cannot set request headers.
Both therefore also accept the token as a **`token` query parameter**:

```text
GET /api/v1/events/stream?run_id=…&topics=run,tree&token=<token>
ws://host:8766/?token=<token>
```

This is an accepted, recorded tradeoff. The mitigation is that the access
log (`{checkpoint}/viz_access.jsonl`) rewrites any `token=` query value to
`***` before writing, so the token never reaches a log file in either
form. The fetch-consumed legacy `/api/logs` stream uses the header, since
its consumer *can* set one.

### Failure behaviour

A missing or wrong token gets `401` with a typed JSON body and
`WWW-Authenticate: Bearer`; the comparison is constant-time
(`hmac.compare_digest`); the connection is closed so an unread body cannot
desync keep-alive. The WebSocket handshake is rejected with the same 401
shape before it upgrades.

### For scripts and curl

```bash
curl -H "Authorization: Bearer $ARI_GUI_TOKEN" http://host:8765/api/v1/projects
curl -N "http://host:8765/api/v1/events/stream?token=$ARI_GUI_TOKEN"
```

### No cookies, therefore no CSRF

Authentication is a bearer token only. Nothing rides a cookie, so there is
no cross-site request forgery surface and no CSRF token to manage.
Sessions, logout, and multi-user access are deliberately deferred — this
is a single-operator research tool today, and the whole matrix
(local / remote / token / kill-switch) is unit-tested in
`ari-core/tests/test_gui_remote_auth.py`.

### The `ARI_GUI_AUTH` escape hatch

`ARI_GUI_AUTH=0` disables the remote gate and restores the older
unauthenticated remote bind. Use it only when something in front of the
GUI already authenticates — an authenticating reverse proxy, for example.
Loopback binds are unauthenticated regardless; the switch has no effect
there.

## CORS

Responses are **same-origin only**. The request `Origin` is echoed back in
`Access-Control-Allow-Origin` (plus `Vary: Origin`) only when it names this
server — matching the request `Host` header, or one of the loopback forms
`localhost` / `127.0.0.1` / `[::1]` on the server port. A cross-origin
request gets **no** ACAO header at all, so the browser refuses to hand the
response to the page.

Preflight (`OPTIONS`) still answers `204` for a disallowed origin, just
without any `Access-Control-*` headers. An allowed origin additionally
receives `Access-Control-Allow-Methods: GET, POST, PUT, PATCH, DELETE,
OPTIONS`, `Access-Control-Allow-Headers: Content-Type, X-Filename,
If-Match, Last-Event-ID`, and a 24-hour `Access-Control-Max-Age`.

What this means in practice:

- **Tunnels and Host-preserving proxies are fine** — the page origin
  equals the `Host` the server sees.
- **The Vite dev server on `:5173` is fine** — its proxy forwards `/api`,
  `/state` and `/ws` same-origin.
- **A portal that serves the page from a different origin than the API is
  not fine** without `ARI_GUI_CORS_ANY=1`, which restores the legacy
  wildcard. Prefer fixing the topology; the wildcard is the last resort.

Two endpoints — `GET /state` and `GET /api/gpu-monitor` — were historically
ACAO-less and remain so.

## Browser security headers (CSP)

The SPA index and every `/static/` response carry:

```text
Content-Security-Policy: default-src 'self'; script-src 'self';
  style-src 'self' 'unsafe-inline'; img-src 'self' data:;
  connect-src 'self' ws://<host>:<port+1> wss://<host>:<port+1>;
  frame-src 'self'; frame-ancestors 'none'
X-Content-Type-Options: nosniff
Referrer-Policy: no-referrer
```

Notes worth knowing before you deploy behind a proxy:

- The bundle is fully self-contained — there is no CDN `<script>` to
  allow. Offline hosts benefit directly.
- `connect-src` names the tree WebSocket **explicitly**, derived from the
  request `Host` header, because the stream listens on HTTP port + 1 and
  `'self'` covers only the page's own port. **If your proxy remaps the
  WebSocket port, the browser will block it** and the dashboard degrades
  to polling. That is the one topology `ARI_GUI_CSP=0` exists for.
- `frame-ancestors 'none'` means the dashboard cannot be embedded in
  another site's iframe. `frame-src 'self'` keeps the same-origin PDF
  iframes working.
- `style-src 'unsafe-inline'` is an accepted residual (React inline
  `style={}` attributes are pervasive); tightening it is tracked work.
- API/JSON responses deliberately carry no CSP.

## Confirmation challenges for destructive actions

Three operations refuse to fire on a client-side confirmation alone:
deleting a checkpoint, stopping all processes, and stopping the GPU
monitor. The server issues a short-lived grant **bound to one action and
one target**, and the destructive endpoint requires it back.

```bash
# 1. ask for a challenge
curl -X POST http://localhost:8765/api/v1/challenges \
     -H 'Content-Type: application/json' \
     -d '{"action":"delete-checkpoint","target":"/path/to/checkpoints/2026…"}'
# -> {"challenge_id":"chg-0a1b2c3d4e5f","action":…,"target":…,
#     "expires_at":"…Z","ttl_seconds":60}

# 2. echo it back with the destructive call
curl -X POST http://localhost:8765/api/delete-checkpoint \
     -H 'Content-Type: application/json' \
     -d '{"path":"/path/to/checkpoints/2026…","challenge_id":"chg-0a1b2c3d4e5f"}'
```

| Action | Target | Enforced on |
|---|---|---|
| `delete-checkpoint` | the checkpoint path | `POST /api/delete-checkpoint` |
| `stop-all` | `"*"` | `POST /api/stop` |
| `gpu-monitor-stop` | `"*"` | `POST /api/gpu-monitor` with `action=stop` |

Properties:

- **single use**, 60-second TTL measured on a monotonic clock (a wall-clock
  jump cannot extend a grant), bounded in-memory store (cap 100,
  oldest evicted; a restart clears them all — the client just asks again);
- a missing, unknown, expired, already-used, or mis-bound challenge gets
  HTTP **428** with the frozen body
  `{"ok": false, "error": "confirmation challenge required or invalid"}`
  and performs **no destructive work**. The message is identical for every
  failure so it cannot be used as an oracle;
- issuance, consumption and refusal are audit-logged as `challenge_*`
  events into the active checkpoint's `viz_access.jsonl`, interleaved with
  the request lines they authorize;
- in the GUI this is invisible: you still see one confirm dialog, but it
  now displays the exact target the **server** echoed back — an impact
  preview you can verify before agreeing.

Automation that scripted the old single-shot endpoints must either adopt
the two-step flow or set `ARI_GUI_CHALLENGES=0`. Issuance stays available
under the kill-switch, so a two-step client works either way.

## SSH tunnel (recommended, and the verified path)

Keep the server on loopback and forward the port. Nothing about the
server's posture changes, so no token is involved.

```bash
# on the workstation
ssh -N -L 8765:localhost:8765 -L 8766:localhost:8766 user@remote-host
# then open http://localhost:8765/
```

Forward **both** ports: `8765` for HTTP and `8766` (HTTP + 1) for the tree
WebSocket. If you forward only the HTTP port everything still works —
the WebSocket simply fails to connect and the dashboard falls back to
polling.

For a cluster login node in front of a compute node, chain the hops:

```bash
ssh -N -J user@login.cluster -L 8765:localhost:8765 -L 8766:localhost:8766 user@compute-node
```

This is the topology the loopback default was designed around, and the
combination the CORS policy is verified against
(`ari-core/tests/test_gui_bind_cors.py` covers the same-origin matrix
including the loopback aliases).

## HPC reverse proxy (guidance, **not** verified end to end)

> The recipe below is untested guidance. It is written from the server's
> documented header and bind policy, not from a working cluster
> deployment. Validate it in your own environment before relying on it.

If a cluster portal must serve the dashboard through a reverse proxy,
these are the constraints that follow from the implemented behaviour:

1. **Preserve the `Host` header.** The same-origin CORS check and the
   CSP's `connect-src` are both derived from it. A proxy that rewrites
   `Host` will make the browser block its own API calls.
2. **Serve the dashboard at the origin root.** Hash routing (`#/…`) is
   fine behind any path, but static assets are served from `/static/dist/`
   and the SPA fallback answers unknown paths — a sub-path mount is not
   something the server rewrites for you.
3. **Do not remap the WebSocket port.** The browser derives it as page
   port + 1 and the CSP allows exactly that. If you must remap it, expect
   the WebSocket to be CSP-blocked and either accept the polling fallback
   or set `ARI_GUI_CSP=0` for that deployment.
4. **Do not buffer SSE.** `GET /api/v1/events/stream` is a long-lived
   stream with 15-second heartbeat comments and a bounded 300-second
   window; a buffering proxy turns live updates into nothing. Disable
   response buffering and set a read timeout above the heartbeat interval.
5. **Decide where authentication lives.** Either terminate auth at the
   proxy and set `ARI_GUI_AUTH=0` on a bind the proxy alone can reach, or
   keep the token gate and have the proxy pass `Authorization` through
   untouched. Do not do neither.
6. **Bind as narrowly as possible** — `ARI_GUI_BIND=127.0.0.1` with the
   proxy on the same host is strictly better than a wildcard bind.
7. **`frame-ancestors 'none'`** means a portal cannot iframe the
   dashboard; link out to it instead.

## Health and diagnostics for operators

Three read-only surfaces. The `/health` prefix is **exempt** from the token
gate (liveness probes must work without credentials); `/api/v1/diagnostics`
is not — it needs the bearer token in remote mode like everything else.

### `GET /health/live`

A dependency-free constant. If the HTTP handler can answer at all, the
process is live.

```json
{"status": "ok"}
```

### `GET /health/ready`

```json
{"status": "degraded",
 "checks": {"http": true, "websocket": true, "watcher": false,
            "event_bus": true, "active_checkpoint": true}}
```

Each check is evaluated independently and a crashing check reads as
`false`. **Readiness never answers 500** — `degraded` is an honest 200, so
a broken subsystem is observable instead of being an exception. The checks
are: `http` (constitutively true inside a dispatched request),
`websocket` (the WS server started), `watcher` (the checkpoint polling
thread is alive), `event_bus` (the SSE bus is importable and publishable),
`active_checkpoint` (one is selected and still exists on disk).

### `GET /api/v1/diagnostics`

Bounded scalars only — counts, ages and versions:

```json
{"schema_version": 1,
 "sse": {"subscribers": 2, "buffer_len": 137, "last_event_id": 4021},
 "watcher": {"alive": true, "last_scan_age_s": 0.9},
 "process": {"tracked_runs": 1},
 "cache": false,
 "openapi_version": "…"}
```

No secrets, no filesystem paths — `tracked_runs` is a **count**, never the
checkpoint-path keys behind it. `cache: false` states explicitly that no
cache subsystem exists rather than omitting the field. Every sub-collector
degrades to its zero shape on failure, because diagnostics must stay
readable exactly when things are broken.

Typical operator loop:

```bash
curl -s localhost:8765/health/live
curl -s localhost:8765/health/ready | python -m json.tool
curl -s -H "Authorization: Bearer $ARI_GUI_TOKEN" \
     http://host:8765/api/v1/diagnostics | python -m json.tool
```

Interpretation hints: `watcher.alive=false` or a `last_scan_age_s` growing
without bound means the checkpoint watcher is stuck — the tree stops
updating even though the run continues. A high `sse.subscribers` with no
open browser tabs suggests leaked streams from a buffering proxy.

`ARI_GUI_HEALTH=0` restores the pre-existing wire behaviour: `/health/*`
falls through to the SPA response and `/api/v1/diagnostics` answers the
typed 404 envelope.

## Access log

While a checkpoint is active, requests are appended as JSON lines to
`{checkpoint}/viz_access.jsonl` — `ts`, `method`, `path`, `status`,
`duration_ms`, `client` — with any `token=` query value redacted to
`***`. With no active checkpoint nothing is written. Confirmation
challenge events (`challenge_issued`, `challenge_consumed`,
`challenge_refused`) land in the same file, so a destructive request and
the grant that authorized it sit next to each other.

## Quick reference: pick a posture

| You want | Do this | Auth |
|---|---|---|
| Local use | nothing | none |
| View from your laptop | `ssh -L 8765:localhost:8765 -L 8766:localhost:8766 …` | none |
| Direct LAN access | `ARI_GUI_BIND=0.0.0.0` (+ `ARI_GUI_TOKEN`) | bearer token, required |
| Behind an authenticating proxy | narrow `ARI_GUI_BIND` + `ARI_GUI_AUTH=0` | the proxy's |
| Cross-origin portal | as above + `ARI_GUI_CORS_ANY=1` | the proxy's |

## See also

- [Dashboard guide](dashboard.md) — starting the server, ports, the workspace map.
- [Configuration Studio](configuration_studio.md) — how secrets are written (never read back).
- [HPC setup](hpc_setup.md) — running ARI itself on a SLURM cluster.
- [Troubleshooting](troubleshooting.md) — common runtime failures.
- [Environment variables](../reference/environment_variables.md).
- [REST API reference](../reference/rest_api.md).
