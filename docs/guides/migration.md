---
sources:
  - path: ari-core/ari/migrations/v05_to_v07
    role: implementation
  - path: ari-core/ari/memory_cli.py
    role: implementation
  - path: ari-core/ari/viz/api_workflow.py
    role: implementation
  - path: ari-core/ari/viz/api_settings.py
    role: implementation
  - path: ari-core/ari/viz/v1/secrets.py
    role: implementation
  - path: ari-core/ari/viz/server.py
    role: implementation
  - path: ari-core/ari/viz/routes.py
    role: implementation
  - path: ari-core/ari/viz/api_ollama.py
    role: implementation
  - path: ari-core/ari/viz/v1/challenges.py
    role: implementation
  - path: ari-core/ari/viz/auth.py
    role: implementation
  - path: ari-core/ari/viz/health.py
    role: implementation
  - path: ari-core/ari/viz/v1/launch.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/ConfigStudio/LaunchPanel.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/ConfigStudio/ExecutionSection.tsx
    role: implementation
  - path: ari-core/ari/config/field_registry.py
    role: implementation
  - path: scripts/setup/setup_env.sh
    role: config
last_verified: 2026-08-13
---

# Migration Guide

ARI's checkpoint format has evolved through three releases.  This
guide walks the upgrade paths.

| From | To | Headline change |
|---|---|---|
| v0.5 | v0.6 | Letta memory backend replaces JSONL |
| v0.6 | v0.7 | ORS / EAR registry / lineage decisions |
| v0.7 | v0.8 (future) | Refactored checkpoint format (`ari.public/` boundary) |
| v0.8 | v1.0 (future) | Legacy compatibility shims removed |

Enabling the opt-in `ari_rqgm` execution mode is **not** a
checkpoint-format migration: `simple_bfts` stays the default, existing
checkpoints keep working unchanged, and the switch is a configuration
decision (`ari.mode` + `rqgm.enabled`) made in `workflow.yaml`, in the
environment, or — for a new run only — from the Configuration Studio
(MN-12).  See the
[RQGM migration guide](rqgm_migration.md) and
[Execution modes](execution_modes.md).

The **GUI refresh** is not a checkpoint-format migration either — no
checkpoint is rewritten and no downgrade is required — but it does change
dashboard behaviour you may depend on.  Those changes are collected in
[GUI refresh (v2 dashboard)](#gui-refresh-v2-dashboard) below.

## v0.5 → v0.6

### What changed

- **Memory backend.**  `memory_store.jsonl` (per checkpoint) and the
  global `$HOME/.ari/global_memory.jsonl` (cross-experiment) are
  retired.  The default backend is now Letta (per-checkpoint agent
  with archival collections `ari_node_*` and `ari_react_*`).
- **`$HOME/.ari/` removed.**  v0.5.0 already deleted the global
  config directory; v0.6 makes the new layout the only writable
  surface.
- **Rubric system.**  `ari-skill-paper` adopted a YAML rubric
  selected by `ARI_RUBRIC`.

### Recipe

1. **Stand up a Letta service.**  Pick one of the deployment paths
   from `docs/guides/hpc_setup.md#6-letta-memory-backend-deployment`:
   Apptainer SIF, docker-compose, or pip.
2. **Set the required env vars.**
   ```bash
   export LETTA_BASE_URL=http://127.0.0.1:8283
   export LETTA_EMBEDDING_CONFIG=openai/text-embedding-3-small
   export ARI_MEMORY_BACKEND=letta
   ```
   `LETTA_EMBEDDING_CONFIG` is an embedding *handle*, not a file path;
   the default is `letta-default`.
3. **Migrate existing memory.**  In each v0.5 checkpoint:
   ```bash
   ARI_CHECKPOINT_DIR=/path/to/ckpt ari memory migrate
   ```
   The migrator reads `memory_store.jsonl` (and `memory.json` too with
   `--react`), imports the entries into the configured backend as
   content-addressed v1 records, and snapshots the result into
   `memory_backup.v1.json.gz`.  A legacy global JSONL is reported if
   present but deliberately not imported.
4. **Delete the legacy JSONLs.**  The migrator renames each source it
   imported to `<name>.migrated-<nanoseconds>`, so only the global file
   is left to remove by hand:
   ```bash
   rm $HOME/.ari/global_memory.jsonl   # if it ever existed
   ```
5. **Pick a rubric.**  Choose a YAML from
   `ari-core/config/reviewer_rubrics/` and export it:
   ```bash
   export ARI_RUBRIC=neurips
   ```
   Subsequent paper review and BFTS scoring will use the new axes.

### Verification

- `ari memory health` prints the backend's health dict — `ok: true` plus
  `backend`, `latency_ms`, `server_version`, and the checkpoint
  `namespace`.
- A `search_memory` call from the agent loop returns embedding-
  ranked results.
- The dashboard `/api/memory/health` endpoint returns 200.

## v0.6 → v0.7

### What changed

- **ORS (Object Repository Spec).**  The reproducibility chain moved
  from `react_driver`'s ad-hoc replication to `ari-skill-replicate`
  (rubric generator) plus `ari-skill-paper-re` (PaperBench
  SimpleJudge grader).
- **EAR registry.**  EAR bundles can be published to a self-hosted
  `ari-registry` server (in addition to local-tarball / Zenodo /
  GitHub release).
- **Lineage decisions.**  `stagnation_rule` watches the BFTS
  composite score.  On CONFIRMED stagnation ARI first pivots
  **deterministically** to the strongest **unused** runner-up idea
  (`switch_to_idea`); the LLM judge (`continue` / `switch_to_idea` /
  `fanout` / `terminate`) is consulted only as a **fallback** when no
  deterministic pivot is available (budget exhausted, recursion limit
  reached, or no unused alternative remains).  Decisions are appended
  to `lineage_decisions.jsonl`.
- **work_dir blacklist.**  Child node `work_dir` no longer inherits
  result files (`results.csv`, `slurm-*.out`, ...).  Existing
  checkpoints keep working but child runs that relied on inheritance
  must be re-run.

### Recipe

1. **Set up the rubric directory.**  Make sure
   `ari-core/config/reviewer_rubrics/` contains the rubrics you
   want.  `ARI_RUBRIC` selects the active one.
2. **(Optional) Stand up `ari registry serve`.**  Only required if
   you want to publish bundles via `ari://`.  Set
   `ARI_REGISTRY_DATA` first; `ARI_REGISTRIES_FILE` and
   `ARI_REGISTRY_TOKEN` configure the client side.
3. **Re-run sub-experiments that relied on result inheritance.**
   The blacklist guarantees children no longer copy
   `results.csv` / `slurm-*.out` / `node_report.json`.  Code,
   compiled binaries, and inputs still inherit.
4. **(Optional) Wire up the reproducibility flow.**  Once a paper is
   ready, run:
   ```bash
   ari ear curate <checkpoint>
   ari ear publish <checkpoint> --backend ari-registry
   ari paper <checkpoint>
   ```
   There is no `ari replicate` / `ari paper-re` subcommand: the ORS
   chain (`ors_generate_rubric` → `ors_audit_rubric` →
   `ors_seed_sandbox` → `ors_build_reproduce` → `ors_run_reproduce` →
   `ors_grade`) is `workflow.yaml` pipeline stages that `ari paper`
   (and `ari run` / `ari resume`) drive through their MCP skills.

### Verification

- `lineage_decisions.jsonl` is created the first time the
  stagnation rule fires.
- `manifest.lock` and `publish_record.json` appear after `ari ear
  publish`.

## v0.7 → v0.8 (future)

### Anticipated changes

- Skills can only import from `ari.public.*`.  The
  `tests/test_public_api_boundary.py` guard rail is already in
  place; v0.8 removes the deprecation shims.
- `ari/migrations/v05_to_v07/` housekeeping helpers move to a
  dedicated CLI surface (`ari migrate ...`) instead of being mixed
  into `ari run`.

### Pre-emptive steps

- Audit any custom skills for direct `from ari import <internal>`
  imports.  `python -m ari.dev.public_audit` (planned) lists them;
  for now `grep -rn 'from ari import\|from ari\.' my-skill/src/`
  works.
- Where you find an internal import, switch to the matching
  `ari.public.*` module (see `docs/reference/public_api.md`).

## v0.8 → v1.0 (future)

The deprecation programme (`CONTRIBUTING.md::Deprecation process`,
`docs/about/release_policy.md`) schedules:

- Removal of every `$HOME/.ari/...` filesystem fallback (currently
  emitting `DeprecationWarning`).
- Removal of `ari/migrations/v05_to_v07/` (forces users to migrate
  before upgrading).
- Removal of legacy `node_report` reconstruct helpers.

If you have not migrated by v1.0, ARI will refuse to launch with a
hard error pointing to this guide.

## GUI refresh (v2 dashboard)

The dashboard refresh adds the v2 workspaces, `/api/v1`, the configuration
control plane, and a hardened HTTP surface.  Legacy screens, legacy hash
URLs, and the legacy `/api/*` endpoints keep working in parallel, so most
of the migration is invisible.  What follows is the complete list of
**user-visible behaviour changes** — the things that used to succeed and
now refuse, or that used to return data and now return a placeholder.

Nothing here rewrites a checkpoint.  Every new artifact
(`resolved_config.json`, `launch_events.jsonl`,
`{workspace_root}/gui_store/`) is additive and ignored by older ARI, so a
downgrade never needs a data migration.

### Rollback levers at a glance

Each lever is an environment variable read at server start: set it, restart
`ari viz`, no rebuild.  Every one of them re-opens the risk the change was
made to close, so treat them as incident tools, not defaults.  The staged
cutover and the removal plan for these levers live in the
[GUI cutover runbook](gui_cutover_runbook.md).

| Lever | Restores |
|---|---|
| `ARI_GUI_BIND='::'` | pre-refresh all-interfaces bind |
| `ARI_GUI_CORS_ANY=1` | pre-refresh `Access-Control-Allow-Origin: *` |
| `ARI_GUI_CHALLENGES=0` | destructive endpoints without a server challenge |
| `ARI_GUI_CSP=0` | responses without CSP / nosniff / referrer headers |
| `ARI_GUI_AUTH=0` | unauthenticated remote bind |
| `ARI_GUI_HEALTH=0` | `/health/*` as SPA HTML, diagnostics as 404 |
| `ARI_GUI_V2=0` | legacy shell (hides the v2 nav entries and routes) |

Four changes have **no** env lever — they are pure fixes with no supported
way back (MN-1, MN-2, MN-3, and the `/codefile` half of MN-5).  For those,
reverting the commit is the only option.  MN-12 (GUI mode selection) has no
lever either, but needs none: its "off" state is simply leaving the default
selection, which launches a byte-identical run.

### Workflow editing requires an active project (MN-1)

- **Before** — with no active checkpoint selected, `POST /api/workflow`,
  `/api/workflow/flow`, `/api/workflow/skills`, and
  `/api/workflow/disabled-tools` silently rewrote the bundled
  `ari-core/config/workflow.yaml` and answered "success", changing the
  default pipeline of every later CLI and GUI run without warning.
- **After** — with no active checkpoint those four endpoints answer **400**
  and write nothing: `{"ok": false, "error": "No active project. Select a
  checkpoint before editing the workflow (the bundled default
  workflow.yaml is read-only from the GUI)."}`.  With a checkpoint
  selected, editing works exactly as before, against the per-checkpoint
  copy-on-write copy.  `GET /api/workflow` is unchanged — reading the
  bundled default as a fallback is legitimate.
- **Why** — a GUI edit must never mutate shipped configuration that other
  runs inherit.  The write guard is shared by all four handlers, so future
  write endpoints inherit it.
- **Rollback** — none.  Select (or create) a run first; there is no env
  lever and no data migration to undo.

### Secrets are never returned; readiness replaces auto-fill (MN-2)

- **Before** — `GET /api/env-keys` returned the **plaintext** value of every
  environment variable whose name contained `API_KEY`, `SECRET`, or
  `TOKEN`, together with the file each came from.  The wizard's
  developer-mode "Auto-read" used those values to pre-fill the API-key
  field.
- **After** — three things:
  1. `GET /api/env-keys` is redacted.  A non-empty value becomes
     `***configured***`, an empty one stays `""`, the `source` map is
     unchanged, and a top-level `"redacted": true` marker lets clients
     detect the new contract.
  2. The new `GET /api/v1/secrets/status` returns only
     `{name, configured, source_class, last_updated}` for an allowlist of
     secret names — the response has no value field at all.
  3. `POST /api/env-keys` still writes as before, but a key name outside
     `^[A-Z][A-Z0-9_]{0,63}$` (or containing newlines/control characters)
     is rejected with **400**.
- **Why** — an HTTP surface that hands out credentials is a credential
  leak, whatever the client does with them.  Readiness ("is it
  configured, and from which class of source") is all the UI ever needed.
- **Rollback** — none.  "Auto-read" now shows `configured (source_class)`
  or `not configured` instead of filling the field; leave the field blank
  and the value from `.env` is used at launch.  Typing a key by hand and
  saving keys from the Settings page are unchanged.

### Workflow autosave detects conflicts instead of overwriting (MN-3)

- **Before** — the workflow editor autosaved two seconds after an edit by
  POSTing over whatever was on disk, without reading it.  A change made in
  another tab, by another user, or by an external process was destroyed
  silently.
- **After** — `GET /api/workflow` returns a `revision` (the sha256 prefix
  of the served `workflow.yaml` bytes).  The four write endpoints accept an
  optional `base_revision`; when it is stale they answer **409** with
  `{"ok": false, "error": "workflow changed on disk since you loaded it
  (revision mismatch); reload before saving"}` and write nothing (not even
  the copy-on-write seed).  On success the new `revision` comes back in the
  response.  The editor sends `base_revision` on every save, keeps the same
  two-second cadence, and shows an explicit state chip — Unsaved changes /
  Saving / Saved / Conflict.  On conflict it stops saving entirely and
  waits for an explicit **Reload**, which re-reads the disk and discards
  unsaved local edits (the banner says so).
- **Why** — a save that reports success while destroying someone else's
  edit is worse than a save that fails.
- **Rollback** — none for the GUI.  API clients that omit `base_revision`
  keep the old last-write-wins behaviour, so the change is additive on the
  wire.

### Loopback bind and same-origin CORS by default (MN-4)

- **Before** — the HTTP server and the port+1 WebSocket server bound **all
  interfaces**, so anything on the LAN or cluster network could reach every
  endpoint without authentication.  JSON responses, OPTIONS preflights, the
  SSE streams, the manual binary responses (`/memory/`, `/codefile`,
  paper PDF/TeX, raw files), and the ollama proxy all returned
  `Access-Control-Allow-Origin: *`, so any web page could read them.
- **After** — the bind default is **loopback only** (`127.0.0.1` plus
  `::1`, so `localhost` works whichever family your distro resolves it to).
  CORS echoes the request `Origin` only when it matches the server's own
  origin (`Host` header match, or a `localhost` / `127.0.0.1` / `[::1]`
  form on the server port), and adds `Vary: Origin`; a non-matching origin
  gets no `Access-Control-Allow-Origin` header at all, and a preflight from
  one gets a bare 204.  `/state` and `GET /api/gpu-monitor` remain
  header-less exactly as before.
- **Why** — an unauthenticated all-interfaces bind combined with a wildcard
  CORS policy is a remote-control surface for the whole cluster network.
- **Rollback** — `ARI_GUI_BIND='::'` restores the old dual-stack wildcard
  bind (`'0.0.0.0'` for IPv4 only, or a single address); `ARI_GUI_CORS_ANY=1`
  restores the wildcard header.  Both together reproduce the old behaviour.
  Local use over `http://localhost:8765`, an SSH tunnel, or the Vite dev
  proxy needs neither.  Opening `http://<server-ip>:8765` from another host
  now requires `ARI_GUI_BIND`.

### `/codefile` path boundary and ollama proxy allowlist (MN-5)

- **Before** — `GET /codefile?path=` served any absolute path that was
  either under the active checkpoint **or** merely contained a
  `checkpoints` component anywhere in the string, so a crafted path such as
  `/tmp/fake/checkpoints/x` — or a symlink pointing out of the tree — read
  arbitrary files.  `GET|POST /api/ollama/<path>` relayed **any** path to an
  implicit `http://localhost:11434` even when no ollama host was
  configured, which made it a general relay to local HTTP services.
- **After** — `/codefile` serves a file only when its resolved canonical
  path (symlinks followed) is a regular file under the active checkpoint
  directory or under one of the resolved checkpoint search bases.  `..`
  segments are rejected before resolution, symlink escapes are rejected by
  the prefix comparison, and a directory or missing file is a 404 as
  before; the 20 MB cap, content types, and status codes are unchanged.
  The ollama proxy forwards only when the path is one of `/api/tags`,
  `/api/show`, `/api/generate`, `/api/chat`, `/api/ps` **and** the target is
  explicitly configured (`ollama_host` in settings or `OLLAMA_HOST`) or the
  effective LLM backend is `ollama` — only in that last case does the
  `localhost:11434` default still apply.  Otherwise it answers **403**
  without opening an upstream connection.
- **Why** — "the path contains the word checkpoints" is not a boundary, and
  an open-ended proxy to localhost is a pivot.
- **Rollback** — the `/codefile` fix has **no** rollback lever, by design.
  For the proxy, the supported "rollback" is to configure the target
  (`ollama_host` or `OLLAMA_HOST`); relaying non-allowlisted paths is not
  restorable.  Artifacts under the default checkpoint locations, and the
  ollama proxy on an ollama backend, behave exactly as before.

### Destructive operations need a server-issued challenge (MN-6)

- **Before** — confirmation was client-side only.
  `POST /api/delete-checkpoint` `rmtree`d the posted path,
  `POST /api/stop` killed every tracked process (including a `pkill`), and
  `POST /api/gpu-monitor` with `action=stop` executed directly — each
  behind nothing more than a browser dialog.  The GPU monitor's
  `confirmed: true` was hard-coded in the API layer.
- **After** — `POST /api/v1/challenges` with `{action, target}` (actions:
  `delete-checkpoint`, `stop-all`, `gpu-monitor-stop`) issues a single-use
  grant `{challenge_id: "chg-<12hex>", action, target, expires_at,
  ttl_seconds: 60}`.  The TTL is measured on the monotonic clock, so a
  wall-clock jump cannot extend it, and issue / consume / reject are
  recorded as `challenge_*` events in the active checkpoint's
  `viz_access.jsonl`.  The three destructive endpoints run only when the
  body carries a `challenge_id` that is unused, unexpired, and bound to the
  same action **and** target; anything else is **428** with
  `{"ok": false, "error": "confirmation challenge required or invalid"}`
  and no destructive work at all.  In the GUI this is invisible except that
  the confirmation dialog now shows the target the server echoed back, and
  **Stop** now asks for confirmation where it previously did not.
- **Why** — the client must not be the only thing standing between a stray
  request and `rmtree`.
- **Rollback** — `ARI_GUI_CHALLENGES=0` returns all three endpoints to
  direct execution (the challenge endpoint stays, so two-step clients keep
  working).  Automation that calls the old endpoints with `curl` must
  either fetch a challenge first or set this variable.

### CSP, no CDN scripts, and hardened static responses (MN-7)

- **Before** — `frontend/index.html` loaded d3 from `cdn.jsdelivr.net` in
  addition to the copy already in the npm bundle (nothing used
  `window.d3`), and neither the SPA index nor `/static/` responses carried
  `Content-Security-Policy`, `X-Content-Type-Options`, or
  `Referrer-Policy`.  One `dangerouslySetInnerHTML` remained in the wizard.
- **After** — the CDN `<script>` is gone (d3 ships in the bundle), the SPA
  index and `/static/` responses send `Content-Security-Policy`
  (`default-src 'self'`, `script-src 'self'`, `style-src 'self'
  'unsafe-inline'`, `img-src 'self' data:`, `connect-src 'self'` plus the
  `ws://`/`wss://` origin for the tree stream on port+1, `frame-src 'self'`,
  `frame-ancestors 'none'`), `X-Content-Type-Options: nosniff`, and
  `Referrer-Policy: no-referrer`.  API and JSON responses are unaffected.
  `dangerouslySetInnerHTML` is gone from the SPA entirely.
- **Why** — one fewer supply-chain dependency, and a policy that bounds
  what a compromised bundle could reach.
- **Rollback** — `ARI_GUI_CSP=0` stops sending all three headers.  Two
  consequences are worth planning for: embedding the dashboard in another
  site's iframe no longer works (`frame-ancestors 'none'`), and a reverse
  proxy that remaps the WebSocket port will see the WebSocket blocked and
  the tree view degrade to polling — that topology is the one legitimate
  reason to use the lever.  Offline installs are strictly better off: there
  is no CDN fetch left to fail.

### Remote bind requires a bearer token (MN-8)

- **Before** — opting into a remote bind exposed every endpoint — including
  deletion, process control, and secret writes — plus the port+1
  WebSocket, with **no authentication**.  MN-4 fixed the default; it did
  not add a credential.
- **After** — when the bind is non-loopback, every HTTP request except
  `/health` and `/health/*` must carry
  `Authorization: Bearer <ARI_GUI_TOKEN>`.  A missing or wrong token is
  **401** with `WWW-Authenticate: Bearer` and a typed JSON body; the
  comparison is constant-time.  If `ARI_GUI_TOKEN` is unset on a remote
  bind the server generates a random 32-hex token at startup and prints it
  once to stderr — there is no code path that starts a remote bind
  unauthenticated.  Because `EventSource` and `WebSocket` cannot set
  headers, the SSE streams and the WebSocket handshake also accept the same
  token as a `token=` query parameter; the access log redacts `token=` to
  `***`, so the token never reaches `viz_access.jsonl`.  The frontend reads
  `localStorage` key `ari_gui_token`.  **The loopback default is byte-for-byte
  unchanged and stays unauthenticated.**
- **Why** — a remote bind without a credential is a remote shell with extra
  steps.
- **Rollback** — `ARI_GUI_AUTH=0` disables the gate (the sane use is an
  authenticating reverse proxy in front).  For remote use, either set
  `ARI_GUI_TOKEN` yourself or collect the generated token from stderr, then
  run `localStorage.setItem('ari_gui_token', '<token>')` once in the
  browser; `curl` needs `-H 'Authorization: Bearer <token>'`.  A token
  input in the Settings UI is still a follow-up.

### Health probes and bounded diagnostics (MN-9)

- **Before** — `/health/live` and `/health/ready` had no handler and fell
  through to the SPA's HTML, which is useless to a probe.  There was no
  diagnostics endpoint, and no way to observe SSE subscribers, watcher
  liveness, or tracked process count from outside.
- **After** — `GET /health/live` returns the constant `{"status": "ok"}`
  with no dependency checks (if the handler answered, the process is live).
  `GET /health/ready` returns
  `{"status": "ok"|"degraded", "checks": {http, websocket, watcher,
  event_bus, active_checkpoint}}`; each check is evaluated independently and
  an exception degrades that check to `false`, so readiness never answers
  500 — `degraded` is an honest 200.  `GET /api/v1/diagnostics` returns
  bounded scalars only: `sse {subscribers, buffer_len, last_event_id}`,
  `watcher {alive, last_scan_age_s}`, `process {tracked_runs}` (a count, not
  paths), `cache: false` (the cache subsystem does not exist yet), plus
  `schema_version` and `openapi_version`.  No secrets and no filesystem
  paths.
- **Why** — an operator needs liveness and readiness separated, and a
  metrics surface that cannot leak.
- **Rollback** — `ARI_GUI_HEALTH=0` restores the pre-change behaviour
  (`/health/*` as SPA HTML, diagnostics as a typed 404).  Normal GUI use is
  unaffected either way; the React app does not call these endpoints.
  Note the auth asymmetry: `/health/*` is exempt from the MN-8 token gate,
  `/api/v1/diagnostics` is not.

### Canonical idempotent launch (MN-10)

- **Before** — launching went only through `POST /api/launch`, which ran
  LLM slug generation, an `sinfo` scheduler probe, and filesystem mutation
  *before* responding; runs had no unique identity (timestamp plus slug, so
  parallel launches could collide); a double-click spawned a second
  subprocess; and the response carried no `run_id`.
- **After** — the canonical endpoint is `POST /api/v1/runs` with
  `{draft_id, display_name?, profile?, idempotency_key?}`:
  - **validation first** — an unknown draft is a typed 404, validation
    failures are a typed 400 with `details.errors`, and a failed request
    mutates **nothing** on disk;
  - **the server issues the identity** —
    `run_id = <UTC YYYYMMDDHHMMSS>_<slug>-<uuid4 6hex>`, with the slug
    derived deterministically from the display name or the goal's first
    line (no LLM call, no scheduler probe before accepting);
  - **materialize, then spawn** — `experiment.md`, `workflow.yaml` (seeded
    copy-on-write from the bundled default), `launch_config.json`,
    `resolved_config.json`, and a `launch_events.jsonl` lifecycle
    (`draft → validating → accepted → spawned`, or `failed`), then the same
    `python3 -m ari.cli run` subprocess as before;
  - **idempotency** — `idempotency_key` claims
    `{workspace_root}/gui_store/launches/{key}.json` create-only *before*
    the spawn, so a duplicate POST returns the same `run_id` with
    `idempotent_replay: true` and spawns nothing;
  - the global active checkpoint is **not** switched by a launch.
  Two launch-specific refusals exist: a draft with no goal is 400
  `missing_goal`, and a draft containing `ari.mode` or any `rqgm.*` field is
  400 `mode_locked` — selecting the governance/execution mode from the GUI
  was still an open decision at the time.  *(Superseded by MN-12: the four
  mode leaves are now accepted for a new run; the other 104 `rqgm.*` paths
  still refuse with `mode_locked`.)*
- **Why** — a run needs an identity before anything is written, and a
  double-click must not fork an experiment.
- **Rollback** — none needed.  `POST /api/launch` is unchanged and runs in
  parallel, every new file is additive, and no data migration is involved.

### Launching from the Configuration Studio (MN-11)

- **Before** — the launch protocol above was API-only.  The only way to
  launch from the GUI was the legacy wizard, and Studio drafts were
  edit-only.
- **After** — `#/studio?draft=<id>` gains a launch panel with a
  goal → review → launch stepper.  **Resolve & validate** calls the draft's
  `resolve-config` and `validate` endpoints and shows the effective-config
  diff against defaults for every leaf whose value does not come from the
  default layer, the validation errors attributable to the draft, resolver
  warnings, secret readiness rows (values are structurally absent), and the
  governance note.  The immutable review summary — display name,
  profile, the resolved execution and paper mode (MN-12), changed-field
  count, config digest, and an explicit note that the `run_id` is issued by
  the server at accept time — is gated on a confirm checkbox, which mints
  exactly one idempotency key per approval.
  **Launch** posts `/api/v1/runs` and redirects to `#/overview?run=<run_id>`
  using the server-issued id, with no mtime or latest-checkpoint guessing;
  a double-click or a retry replays the same key, so only one run is
  spawned.  Failures render the typed error envelope, including
  `missing_goal` and `mode_locked`.
- **Why** — the review step is where an operator can still say no, so it
  has to show the resolved configuration rather than the draft's intent.
- **Rollback** — none needed; the panel is additive frontend only.  The
  legacy wizard remains fully usable, and the MN-10 backend is independent
  of it.

### Execution and paper mode are selectable for a new run (MN-12)

- **Before** — every field in the `Execution mode` category and every
  `rqgm.*` path (108 paths today) was locked out of the GUI: one disabled group in
  the Studio, and 400 `mode_locked` from `POST /api/v1/runs`.  Choosing
  `ari_rqgm` or `rqgm_archive` meant hand-editing two interlocked keys in
  `workflow.yaml`.
- **After** — exactly four leaves open, as two orthogonal paired intents:
  `ari.mode` + `rqgm.enabled` and `paper.mode` + `rqgm.paper.enabled`.  One
  Studio control writes **both** keys of its pair, so a half-set pair cannot
  be built in the UI; anywhere else it is a typed 400
  `mode_interlock_mismatch` (template and draft create/PATCH, and launch),
  evaluated on the merged document values.  A non-default selection is
  materialized twice — minimal `ari:`/`rqgm:`/`paper:` blocks merged into
  the run's own `workflow.yaml` copy (never the bundled file) plus the
  documented `ARI_MODE` / `ARI_RQGM_ENABLED` / `ARI_PAPER_MODE` /
  `ARI_RQGM_PAPER_ENABLED` environment variables.  The launch review shows
  the **resolved** mode, and an unhonoured request is shown as
  `requested → resolved` with the resolver's warning verbatim instead of
  silently starting the fallback run.  The remaining 104 `rqgm.*` governance
  and tuning parameters stay configuration-file only — visible read-only
  with their effective values, still 400 `mode_locked` at launch — and the
  RQGM API surface is still read-only.  **Resume is unaffected**: the mode
  persisted in `{checkpoint}/rqgm_state.json` still wins — in either
  direction, so a run's mode is fixed for its lifetime — and no GUI path
  writes that file.
- **Why** — the GUI is the offered launch surface but could not state the
  single most consequential property of the run it was starting, while the
  blanket lock treated "which algorithm runs" and "what the adversarial
  budget is" as the same decision (ADR-09).
- **Rollback** — no env lever, and none is needed: leaving the default
  selection (`simple_bfts` + `linear`) produces a byte-identical launch,
  including when the defaults are explicitly re-picked.  `ARI_GUI_V2=0`
  removes the whole v2 Studio, and the legacy wizard still launches the
  defaults.  Reverting the commit needs no data migration — the only new
  artifacts are additive blocks inside per-run `workflow.yaml` copies, which
  older ARI ignores.

## See also

- [GUI cutover runbook](gui_cutover_runbook.md) — making the v2 dashboard
  the default, the staged rollout, and the legacy-removal order.
- [RQGM migration guide](rqgm_migration.md) — turning on the opt-in
  `ari_rqgm` mode (no checkpoint-format change).
- `CHANGELOG.md` — per-release notes.
- `ari memory migrate --help` — CLI options for the v0.5 → v0.6
  migrator.
- `docs/guides/troubleshooting.md` — what to do when migration
  fails.
