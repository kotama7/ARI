---
sources:
  - path: ari-core/ari/viz/v1/router.py
    role: implementation
  - path: ari-core/ari/viz/v1/errors.py
    role: implementation
  - path: ari-core/ari/viz/v1/events.py
    role: implementation
  - path: ari-core/ari/viz/v1/logs.py
    role: implementation
  - path: ari-core/ari/viz/v1/store.py
    role: implementation
  - path: ari-core/ari/viz/v1/openapi.json
    role: schema
  - path: ari-core/ari/viz/auth.py
    role: implementation
  - path: ari-core/ari/viz/health.py
    role: implementation
  - path: ari-core/ari/viz/routes.py
    role: implementation
  - path: ari-core/ari/viz/api_paperbench.py
    role: implementation
  - path: ari-core/ari/viz/api_experiment.py
    role: implementation
  - path: ari-core/ari/viz/checkpoint_api.py
    role: implementation
  - path: ari-core/ari/viz/api_settings.py
    role: implementation
  - path: ari-core/tests/test_gui_state_facade_freeze.py
    role: test
last_verified: 2026-07-30
---

# REST API Reference

The viz dashboard server (`ari viz` → `ari-core/ari/viz/server.py`) exposes
two HTTP surfaces that run **in parallel**:

- **`/api/v1` — the canonical, versioned API.** Declarative dispatch in
  `ari-core/ari/viz/v1/router.py`, typed pydantic DTOs, a typed error
  envelope, and a committed OpenAPI 3.1 document. All new features land
  here.
- **The legacy unversioned API** (`/state`, `/api/*`) — a *frozen facade*
  kept byte-compatible for the legacy dashboard pages. It is documented
  below for reference; do not extend it.

Both are dispatched by `viz/routes.py`; the `/api/v1/` branches delegate to
`v1/router.py:dispatch()` while every other branch keeps its historical
handler.

## Transport basics

- Base URL: `http://127.0.0.1:<port>` (default port set by `ari viz`).
- The server binds to **loopback only** by default (`127.0.0.1` + `::1`);
  `ARI_GUI_BIND` opts into a remote bind.
- CORS is **same-origin echo only** — the request `Origin` is echoed back
  only when it matches the server's own origin. `ARI_GUI_CORS_ANY=1`
  restores the historical `Access-Control-Allow-Origin: *`.
- Authentication: **none on a loopback bind**; on a non-loopback bind every
  request except the `/health*` prefix requires
  `Authorization: Bearer <ARI_GUI_TOKEN>` (see [Authentication](#authentication)).
- All response bodies are JSON unless noted otherwise.
- The SPA index and `/static/*` carry `Content-Security-Policy`,
  `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`
  (`ARI_GUI_CSP=0` drops them). API/JSON responses are deliberately
  untouched.

The `ARI_GUI_*` variables that govern all of the above are listed in
[Environment Variables → GUI server](environment_variables.md#gui-server-ari_gui_).

---

## `/api/v1` (canonical)

### Versioning policy

| Aspect | Rule |
|---|---|
| URL version | `/api/v1`. A breaking change means a new path prefix, never a silent change under `v1`. |
| Payload version | Every resource DTO carries `schema_version: 1` (`Literal[1]` in `ari/viz/v1/dto.py`), so a consumer can detect the contract revision from the body alone. |
| Change policy | **Additive only**: new optional fields may appear at any time; existing fields are neither removed nor retyped within `v1`. Clients must ignore unknown keys. |
| Document version | `info.version` in the OpenAPI document (`1.0.0` today, constant `OPENAPI_INFO_VERSION`); `GET /api/v1/diagnostics` reports it as `openapi_version`. |
| Resolver version | The config surface versions its *resolution algorithm* separately: `resolver_version: "legacy-compatible-1"` on `GET /api/v1/config/schema`, `.../resolved-config` and the draft resolve endpoint. |
| Error codes | The code vocabulary is frozen and extended additively (`ERROR_CODES` in `ari/viz/v1/errors.py`). |

### Machine-readable source

`ari-core/ari/viz/v1/openapi.json` is the committed, machine-readable
contract. It is **generated deterministically** from the route table plus
the pydantic DTO schemas — sorted keys, no timestamps, no commit SHAs — so
it is diffable and drift-guarded:

```bash
python -m ari.viz.v1.openapi            # verify committed == regenerated (default)
python -m ari.viz.v1.openapi --update   # regenerate ari/viz/v1/openapi.json
```

`ari-core/tests/test_gui_v1_api.py` fails when the committed document drifts
from the generator. Never hand-edit `openapi.json`; edit `router.py` /
`dto.py` and regenerate.

Three routes are intentionally **not** in `openapi.json` because they are
not JSON request/response operations of the v1 router: the SSE stream
`GET /api/v1/events/stream` (served directly by `routes.py`) and the
`/health/live` / `/health/ready` probes (served by `ari/viz/health.py`
outside the `/api/v1` namespace). They are documented in the endpoint table
below.

### Error envelope

Every `/api/v1` failure is the same JSON shape (`ari/viz/v1/errors.py`):

```json
{
  "error": {
    "code": "not_found",
    "message": "unknown run: 20260726T101500_matmul",
    "details": null,
    "request_id": "req-4f2a91c7b0de",
    "retryable": false
  }
}
```

| Field | Meaning |
|---|---|
| `code` | One of the frozen codes below. Switch on this, never on `message`. |
| `message` | Human-readable, English, safe to display. Never contains a stack trace. |
| `details` | Optional structured payload (e.g. `{"errors": [...]}` for validation, `{"expected": n, "actual": m}` for a revision conflict). `null` when unused. |
| `request_id` | `req-<12 hex>`, minted per dispatch. The same id is echoed as a top-level `request_id` on **successful** responses, so a UI can quote it in a bug report. |
| `retryable` | `true` only where a retry can plausibly succeed (today: `internal`). |

Frozen code vocabulary:

| `code` | HTTP | Raised when |
|---|:--:|---|
| `not_found` | 404 | No route matches, or the addressed run / project / template / draft / node / epoch / secret does not exist. Also used for "this run is not an RQGM run". |
| `invalid_request` | 400 | Malformed JSON body, a non-object body, a malformed `If-Match`, an out-of-range `cursor`/`limit`, or a rejected config patch (offending paths ride in `details.errors`). |
| `revision_conflict` | 409 | `If-Match` did not match the stored document revision. `details` carries `{expected, actual}`. |
| `already_exists` | 409 | A create-only `POST` hit an existing document — today only `POST /api/v1/run-templates` with a `template_id` that is already taken. |
| `internal` | 500 | Unhandled handler exception. `retryable: true`; the exception type + message are surfaced, the traceback is not. |

HTTP `401` (missing/invalid bearer token) and `428` (missing confirmation
challenge) are produced *outside* the v1 envelope builder — see
[Authentication](#authentication) and
[Confirmation challenges](#confirmation-challenges).

### Optimistic concurrency (`If-Match` / revisions)

The GUI configuration documents (project config, run templates, run drafts)
are stored by `ari/viz/v1/store.py` with a per-document integer `revision`
starting at `1` and incremented on every successful write. That revision is
the optimistic-concurrency token:

- Every document response body carries `revision` (there is **no** HTTP
  `ETag` header — the revision travels in the JSON body).
- `PATCH` and `DELETE` require the header `If-Match: "<revision>"`. Both the
  quoted ETag form (`"3"`) and a bare integer (`3`) are accepted; weak
  validators (`W/"3"`) are not — revisions are exact.
- A **missing** `If-Match` on a mutation is `400 invalid_request` (the
  handler enforces requiredness so the message can name the mutation); a
  **malformed** value is also `400 invalid_request`.
- A **stale** value is `409 revision_conflict` with
  `details: {"expected": <yours>, "actual": <stored>}`. Re-`GET`, re-apply
  your edit on top of the newer document, and retry.
- `revision 0` means "the document must not exist yet" — that is how a
  create-only write is expressed internally.
- A missing project-config document reads as `revision: 0` with empty
  values; the matching first `PATCH` therefore sends `If-Match: "0"`.
- Writes are atomic and durable (same-directory temp file + `fsync` +
  `os.replace`, files `0o600`, directories `0o700`), so a crash mid-write
  leaves the previous document byte-intact.

`POST /api/v1/run-templates` is create-only and takes no `If-Match`: an
existing id answers `409 already_exists`.

### Cursor conventions

Three collections are paged with **byte-offset cursors** into their
append-only source file, which makes paging stable while the file grows:

| Endpoint | Source artifact | Cursor unit |
|---|---|---|
| `GET /api/v1/runs/{run_id}/logs` | `{ckpt}/ari.log` | Raw byte offset |
| `GET /api/v1/runs/{run_id}/rqgm/transitions` | `{ckpt}/rqgm_transitions.jsonl` | Byte offset of a committed entry |
| `GET /api/v1/runs/{run_id}/rqgm/audit` | `{ckpt}/rqgm_audit.jsonl` | Byte offset of a line |

Rules that hold for all three:

- **No gaps, no duplicates.** A page selects records at/after the cursor and
  returns `next_cursor` = the first byte offset it did *not* serve
  (`null` when the page reached the end). Following `next_cursor` walks the
  file exactly once.
- **Committed-only reads.** A trailing line without its terminating newline
  is a torn append: it is never emitted, and the cursor parks at its first
  byte so the line is served once the newline lands. For the RQGM
  transition log, an `epoch_transaction_prepare` with no matching commit
  (and everything after it) is likewise not adopted into current state.
- **Bounded work.** `limit` defaults to 200 (max 1000) for logs and 20 (max
  100) for the RQGM pages; the log reader additionally scans at most 1 MiB
  per request, so no request ever reads a whole 5 MB log.
- **Filters never move the cursor.** `?grep=` on logs (case-insensitive
  substring) and `?record_type=` / `?epoch=` on the audit page select which
  scanned records are *returned*; the cursor advances over non-matching
  records too, so a page chain stays consistent even if the filter changes
  between requests.
- **Out-of-range values are rejected**, not clamped: a negative/non-integer
  `cursor`, or a `limit` outside its range, is `400 invalid_request`.
- `source_revision` on the RQGM pages is the parsed byte length of the
  source file (the torn tail excluded) — a cheap "has the log grown?" check.

`GET /api/v1/runs/{run_id}/rqgm/score-rewrites` also takes `cursor`/`limit`,
but its cursor is an **integer index** into the deterministic joined rewrite
list (it is a join across two logs, not a single file scan).

### Realtime: `GET /api/v1/events/stream` (SSE)

A single Server-Sent Events stream carries **invalidations, never state**:
on any event the client refetches the named snapshot resource. The
authoritative data always comes from a normal GET.

Query parameters: `run_id` (filter to one run), `topics` (comma-separated),
`last_event_id` (resume cursor when the header cannot be set), `token`
(remote-mode auth).

Event payload:

```
id: 42
event: resource.changed
data: {"event_id":"42","run_id":"20260726T101500_matmul","topic":"tree",
       "revision":7,"occurred_at":"2026-07-26T10:20:31Z",
       "kind":"resource.changed",
       "resource":"/api/v1/runs/20260726T101500_matmul/tree","payload":{}}
```

| Aspect | Contract |
|---|---|
| Topics | The published vocabulary is frozen at `run` and `tree` (`events.TOPICS`). `tree` is published by the state watcher (mirroring the legacy WebSocket broadcast); `run` is published on checkpoint switch and after a v1 launch. |
| `resource` | The `/api/v1` snapshot to refetch — `.../tree` for `tree`, `.../summary` for `run` (a publisher may override it). |
| `revision` | A per-`(topic, run_id)` counter, so a client can detect that it missed an invalidation for one resource. |
| `event_id` | Process-lifetime monotonic integer, serialized as a string, emitted as the SSE `id:` field. |
| Replay | On connect the server replays buffered events with id greater than `Last-Event-ID` (the header wins; `?last_event_id=` is the fallback because `EventSource` cannot set headers). The buffer is a 1000-event ring — anything evicted is simply gone, which is safe precisely because events are not a source of truth: the reconnect refetch covers the gap. |
| Heartbeat | `: heartbeat` comment every 15 s of idleness, so proxies do not drop the connection. The stream opens with `: connected` + `retry: 5000` (the browser's reconnect delay). |
| Reconnect | The stream window is bounded at 300 s; on expiry the server writes `: stream-timeout - reconnect` and closes, and the client reconnects with its `Last-Event-ID`. A client disconnect ends the stream silently. |

### Authentication

The trust model is decided by the **bind**, not by a setting
(`ari/viz/auth.py`):

- **Local mode** (default — `ARI_GUI_BIND` unset, so the bind is loopback):
  no authentication at all. Request shapes are unchanged from pre-auth
  builds even if `ARI_GUI_TOKEN` happens to be exported.
- **Remote mode** (`ARI_GUI_BIND` names a non-loopback host, including the
  wildcards `::` / `0.0.0.0`): every HTTP request except the `/health*`
  prefix must send `Authorization: Bearer <token>`. Missing/incorrect →
  `401` with a typed JSON body and `WWW-Authenticate: Bearer`. The
  comparison is constant-time.
- If `ARI_GUI_TOKEN` is unset while remote-bound, the server **generates** a
  32-hex token at startup and prints it once to stderr — a remote bind is
  never silently unauthenticated.
- **SSE and WebSocket** accept the same token as the `token` **query
  parameter**, because `EventSource` and the WS handshake cannot set
  headers (recorded tradeoff). The access log redacts any `token=` value, so
  the token never reaches `viz_access.jsonl`. The fetch-consumed legacy
  `/api/logs` stream uses the header.
- No cookies are used, so there is no CSRF surface. Sessions, logout and
  multi-user are out of scope.
- `ARI_GUI_AUTH=0` disables the gate (documented escape hatch for a
  topology that terminates its own auth, e.g. an authenticating reverse
  proxy).

### Confirmation challenges

Destructive legacy operations require a **server-issued, single-use
challenge** minted by `POST /api/v1/challenges`:

| Action | Bound target | Consumed by |
|---|---|---|
| `delete-checkpoint` | the checkpoint path being deleted | `POST /api/delete-checkpoint` |
| `stop-all` | `"*"` | `POST /api/stop` |
| `gpu-monitor-stop` | `"*"` | `POST /api/gpu-monitor` with `action=stop` |

The response is `{challenge_id: "chg-<12 hex>", action, target, expires_at,
ttl_seconds: 60}`. The destructive endpoint executes only when the body's
`challenge_id` is unused, unexpired and bound to the same action+target;
otherwise it answers HTTP `428` with the frozen payload
`{"ok": false, "error": "confirmation challenge required or invalid"}` and
performs nothing. TTL is measured on a monotonic clock (a wall-clock jump
cannot extend it) and the store is a bounded in-memory deque (cap 100).
Issue/consume/refuse are audit-logged. `ARI_GUI_CHALLENGES=0` restores
direct execution.

### Endpoint table

Generated from `ari-core/ari/viz/v1/openapi.json` (36 paths / 41
operations), grouped for reading; the JSON document remains authoritative.

#### Projects and runs

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/projects` | List projects — one virtual `default` project aggregating the checkpoint search bases. |
| GET | `/api/v1/projects/{project_id}/runs` | Runs (checkpoints) in one project, as summary cards — one portfolio merged across every checkpoint root, newest first (mtime descending). |
| GET | `/api/v1/runs/{run_id}` | Run detail: summary plus artifact-derived detail fields and a capability map. |
| GET | `/api/v1/runs/{run_id}/summary` | Summary-card scalars for one run (status, node count, review score, best metric, `has_paper`). |
| GET | `/api/v1/runs/{run_id}/tree` | BFTS tree — the `tree_view` node list passed through byte-preserving. |
| GET | `/api/v1/runs/{run_id}/idea` | Pure read of `{ckpt}/idea.json` (ideas / gap analysis / primary metric); absence is `present: false`, never fabricated empties. |
| GET | `/api/v1/runs/{run_id}/results` | Bounded result read model: paper / review / ORS / EAR presence flags and scalars — never file contents. |
| GET | `/api/v1/runs/{run_id}/ear` | EAR bundle listing metadata plus curate/publish lineage scalars. |
| GET | `/api/v1/runs/{run_id}/logs` | One bounded cursor page over `{ckpt}/ari.log` (`cursor`, `limit`, `grep`). |
| POST | `/api/v1/runs` | Idempotent launch: validate the draft, mint the `run_id`, materialize the checkpoint, spawn the CLI. |

#### Configuration control plane

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/config/schema` | The canonical config field registry — metadata only, never an effective value. |
| GET | `/api/v1/config/catalogs/models` | Server-side provider/model suggestions plus each provider's API-key env name. |
| GET | `/api/v1/runs/{run_id}/resolved-config` | Post-hoc resolved manifest for an existing checkpoint (values + provenance + digest). |
| GET | `/api/v1/projects/{project_id}/config` | The default project's config document (`revision` + flat `values`). |
| PATCH | `/api/v1/projects/{project_id}/config` | Merge-validate-write a partial `{values: {dotted.path: value}}`; `If-Match` required. |
| GET | `/api/v1/run-templates` | List run templates (codepoint-ordered). |
| POST | `/api/v1/run-templates` | Create a run template (create-only → `409 already_exists`). |
| GET | `/api/v1/run-templates/{template_id}` | Read one run template. |
| PATCH | `/api/v1/run-templates/{template_id}` | Merge values into a template; `If-Match` required. |
| DELETE | `/api/v1/run-templates/{template_id}` | Delete a template; `If-Match` required. |
| POST | `/api/v1/run-drafts` | Create a run draft (server-generated `draft-<12 hex>` id; optional `goal`). |
| GET | `/api/v1/run-drafts/{draft_id}` | Read one run draft. |
| PATCH | `/api/v1/run-drafts/{draft_id}` | Merge values into a draft (the goal is preserved); `If-Match` required. |
| POST | `/api/v1/run-drafts/{draft_id}/resolve-config` | Preview the full new-run resolution chain for this draft (optional `profile`), with provenance and warnings. |
| POST | `/api/v1/run-drafts/{draft_id}/validate` | `{valid, errors, warnings}` distilled from the same resolution run (interlock mismatch is an **error** here). |

#### Secrets

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/secrets/status` | Readiness rows for the allowlisted secret names (`configured` / `source_class` / `last_updated`) — the value field does not exist. |
| PUT | `/api/v1/secrets/{secret_id}` | Write-only assignment of one allowlisted secret; the response is the post-write readiness row, never the value. |

#### RQGM governance (read-only)

See [RQGM GUI read models](rqgm_gui_read_models.md) for the semantics of
each payload.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/runs/{run_id}/rqgm/capabilities` | Whether this run is an RQGM run (artifact presence) and which paper mode it uses. |
| GET | `/api/v1/runs/{run_id}/rqgm/overview` | Bounded governance summary: current epoch, policy/constitution hashes, registry counts, integrity flags. |
| GET | `/api/v1/runs/{run_id}/rqgm/registry` | Components and prompts from committed transition replay, plus the rollup-verification result. |
| GET | `/api/v1/runs/{run_id}/rqgm/transitions` | Byte-offset page over the committed transition log (`expand=1` returns raw events). |
| GET | `/api/v1/runs/{run_id}/rqgm/audit` | Byte-offset page over the audit log, filterable by `record_type` / `epoch`. |
| GET | `/api/v1/runs/{run_id}/rqgm/policies` | Registered utility policies with their write-once bodies and adoption provenance. |
| GET | `/api/v1/runs/{run_id}/rqgm/score-rewrites` | Epoch-boundary score rewrites: policy supersession joined with its erasure/rebuild consequences. |
| GET | `/api/v1/runs/{run_id}/rqgm/nodes/{node_id}/lineage` | One node's two score channels (adversarial penalty vs epoch-policy rewrite), never merged. |
| GET | `/api/v1/runs/{run_id}/rqgm/epochs` | Committed epoch timeline with per-epoch policy hash and boundary counts. |
| GET | `/api/v1/runs/{run_id}/rqgm/epochs/{epoch_id}` | One epoch's frozen scalars, active sets, opening/closing transactions and policy body. |
| GET | `/api/v1/runs/{run_id}/rqgm/evolution` | Prompt / utility-policy / meta candidate lineage with explicit adoption joins. |
| GET | `/api/v1/runs/{run_id}/rqgm/paper-archive` | Paper-archive mode scalars: epochs, draft count, anchor state, self-preference stat, best-belief draft. |

#### Operations

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/challenges` | Mint a single-use confirmation challenge for one dangerous operation. |
| GET | `/api/v1/diagnostics` | Bounded operational scalars: SSE bus stats, watcher liveness, tracked-process count, versions. No secrets, no paths. |

#### Not in `openapi.json`

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/events/stream` | SSE invalidation stream (see [Realtime](#realtime-get-apiv1eventsstream-sse)). |
| GET | `/health/live` | Dependency-free liveness constant `{"status": "ok"}`. Auth-exempt. |
| GET | `/health/ready` | Readiness: a `status` of `ok` or `degraded` plus a `checks` object (`http`, `websocket`, `watcher`, `event_bus`, `active_checkpoint`). Each check is evaluated independently and a crashing check reads as `false`; a degraded readiness is an honest `200` — this probe never answers 500. Auth-exempt. |

`ARI_GUI_HEALTH=0` removes all three health/diagnostics surfaces
(`/health/*` falls back to the SPA response, `/api/v1/diagnostics` answers
the typed 404).

---

## Legacy unversioned API (legacy facade — frozen, see MN notes)

> **Frozen.** The unversioned surface below is kept for the legacy dashboard
> pages and existing integrations. It is **not** extended: new data must be
> served from a run-explicit `/api/v1` endpoint. `GET /state` in particular
> is a frozen facade whose exact top-level key set is pinned by
> `ari-core/tests/test_gui_state_facade_freeze.py` (7 keys with no active
> checkpoint, 35 keys for a fully-populated checkpoint) — adding a key to it
> fails that test by design, and removing one breaks the legacy pages.

### Behaviour changes on the legacy surface (MN notes)

The GUI refresh program changed a handful of legacy behaviours; each is
recorded as a numbered migration note (MN-n) with its rollback lever. The
tables further down list the *routes*, which are unchanged; these are the
*semantics* that moved.

| MN | Legacy endpoints affected | Change | Rollback |
|---|---|---|---|
| MN-1 | `POST /api/workflow{,/flow,/skills,/disabled-tools}` | Without an active checkpoint these refused to be a silent rewrite of the bundled `workflow.yaml`: they now answer `400` and write nothing. | revert only |
| MN-2 | `GET /api/env-keys` | Secret values are redacted (`***configured***`) and a `redacted: true` marker added; `POST /api/env-keys` enforces a name allowlist (`400` otherwise). Readiness moved to `GET /api/v1/secrets/status`. | revert only |
| MN-3 | `GET /api/workflow` + the four workflow writes | Additive `revision` (sha256[:12] of the served bytes) and optional `base_revision` on writes; a stale write is refused with `409` instead of blind-overwriting. Callers that omit `base_revision` keep last-write-wins. | revert only |
| MN-4 | all (bind), all CORS-bearing responses | Loopback bind by default + same-origin CORS echo. | `ARI_GUI_BIND`, `ARI_GUI_CORS_ANY=1` |
| MN-5 | `GET /codefile`, `GET/POST /api/ollama/<path>` | `/codefile` serves only files whose resolved canonical path is under the active checkpoint or a checkpoint search base; the Ollama proxy is restricted to a 5-path allowlist and refuses (`403`) unless a target is explicitly configured or the effective backend is Ollama. | none (security fix) |
| MN-6 | `POST /api/delete-checkpoint`, `POST /api/stop`, `POST /api/gpu-monitor` (`action=stop`) | Require a server-issued `challenge_id`; otherwise `428` and no side effect. | `ARI_GUI_CHALLENGES=0` |
| MN-7 | `GET /`, SPA fallback, `GET /static/*` | CSP + `nosniff` + `Referrer-Policy` headers; the CDN `<script>` was removed from the bundle. | `ARI_GUI_CSP=0` |
| MN-8 | all, on a remote bind | Bearer-token authentication (`401` without it); SSE/WS accept `?token=`. | `ARI_GUI_AUTH=0` |
| MN-9 | `GET /health/live`, `GET /health/ready` | Were the SPA HTML fallback; now JSON probes (plus the new `GET /api/v1/diagnostics`). | `ARI_GUI_HEALTH=0` |
| MN-10 | `POST /api/launch` | **Unchanged** — the canonical idempotent launch is the additive `POST /api/v1/runs`; both run in parallel. | n/a |

### Conventions (legacy)

- Errors come back as `{"error": "<message>"}` with a non-2xx HTTP code
  (some handlers use `{"ok": false, "error": ...}`).
- CORS preflight (`OPTIONS`) is answered on `/api/*` for same-origin
  requests only (MN-4).

### Typed contracts (stable endpoints)

The highest-traffic GET endpoints have their response shape mirrored by a
frontend TypeScript type in `ari-core/ari/viz/frontend/src/types/index.ts` and
guarded by `ari-core/tests/test_api_schema_contract.py` (asserts the
always-present keys as a **subset** — extra/optional fields are allowed, so the
contract is additive).

| Endpoint | Producer | Frontend type | Always-present keys |
|---|---|---|---|
| `GET /state` | `services/state_service.build_app_state` | `AppState` | `running_pid`, `is_running`, `exit_code`, `running`, `pid`, `status_label` (the rest are checkpoint-gated → optional in the type). `cost` is the parsed `cost_summary.json` **object** (`CostSummary`), not a number. |
| `GET /api/settings` | `api_settings._api_get_settings` | `Settings` | the full defaults dict (`llm_model`, `llm_provider`, `ollama_host`, `temperature`, … , nested `ors`); arbitrary saved keys also pass through (`{**defaults, **saved}`). |
| `GET /api/checkpoints` | `checkpoint_api._api_checkpoints` | `Checkpoint[]` | `id`, `path`, `status`, `node_count`, `review_score`, `best_metric` (always `null`), `mtime`; `best_scientific_score` is conditional. |
| `GET /api/checkpoint/<id>/summary` | `checkpoint_api._api_checkpoint_summary` | `CheckpointSummary` | `id`, `path` (or `{error:"not found"}`); all report bodies are conditional. `reproducibility_report` is a parsed **object** (legacy runs: string), not always a string. |

Contracts are **permissive**: new optional fields may be added without breaking
consumers; existing fields are never removed during a migration (see the
refactoring global rules).

### Worked examples

Minimal `curl` request/response pairs for the endpoints you reach for first.
The examples assume the dashboard is on the default port `8765`.

**Read the live state:**

```bash
curl http://localhost:8765/state
```

```json
{
  "checkpoint_id": "20260526T101500_matmul",
  "current_phase": "bfts",
  "node_count": 7,
  "nodes": [{ "id": "node-0", "status": "success", "metrics": {} }],
  "has_paper": false,
  "llm_model": "ollama_chat/qwen3:8b",
  "running_pid": 48213,
  "is_running": true,
  "exit_code": null,
  "status_label": "🟢 Running",
  "cost": { "total": 0.0 }
}
```

Abridged: the frozen facade emits exactly 7 top-level keys with no active
checkpoint and 35 with a fully-populated one. `nodes` is the tree node list
(not a count summary) and `cost` is the parsed `cost_summary.json` object.

**Launch a run:**

```bash
curl -X POST http://localhost:8765/api/launch \
  -H 'Content-Type: application/json' \
  -d '{"experiment_md": "# Goal\nImprove GFLOP/s of a dense matmul.\n",
       "profile": "laptop", "provider": "ollama", "model": "qwen3:8b",
       "max_nodes": 8, "max_depth": 3, "workers": 2}'
```

```json
{ "ok": true, "pid": 48213, "checkpoint_path": "workspace/checkpoints/20260526T101500_matmul" }
```

**List checkpoints:**

```bash
curl http://localhost:8765/api/checkpoints
```

```json
[
  { "id": "20260526T101500_matmul", "path": "workspace/checkpoints/20260526T101500_matmul",
    "status": "running", "node_count": 7, "review_score": null,
    "best_metric": null, "mtime": 1779795300 },
  { "id": "20260520T090000_sort", "path": "workspace/checkpoints/20260520T090000_sort",
    "status": "completed", "node_count": 12, "review_score": 0.71,
    "best_metric": null, "mtime": 1779267600, "best_scientific_score": 0.83 }
]
```

The list is one portfolio across every checkpoint search base, ordered by
`mtime` descending (newest first). `status` is one of `unknown` / `running` /
`stopped` / `completed`.

**Error shape** (any legacy endpoint, non-2xx):

```json
{ "error": "no active checkpoint" }
```

### State + dashboards

| Method | Path | Purpose | Source |
|---|---|---|---|
| GET | `/state` | Current BFTS state snapshot used by the dashboard live view (**frozen key set**) | `routes.py` |
| GET | `/api/gpu-monitor` | GPU utilisation poll | `routes.py` |
| GET | `/api/resource-metrics` | CPU / memory / disk metrics | `routes.py` |
| GET | `/api/logs` | Recent log lines for the active run | `routes.py` |

### Models + skills

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/models` | Discover LLMs available via LiteLLM + Ollama |
| GET | `/api/ollama-resources` | Memory / disk needed by a model |
| GET | `/api/ollama/<...>` | Proxy through to a local Ollama daemon (allowlisted paths only — MN-5) |
| GET | `/api/skills` | Enumerate registered skills + their tool counts |
| GET | `/api/skill/<skill_name>` | Per-skill metadata (tool list, env vars) |
| GET | `/api/tools` | Combined tool catalogue across all skills |
| GET | `/api/scheduler/detect` | `local` / `slurm` / `apptainer` autodetect |
| GET | `/api/slurm/partitions` | SLURM partition list |
| GET | `/api/container/info` | Container runtime probe |
| GET | `/api/container/images` | Cached SIF / OCI images |
| POST | `/api/container/pull` | Pull / build an image referenced by `ARI_CONTAINER_IMAGE` |

### Checkpoint browsing

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/checkpoints` | List all checkpoints across the checkpoint search bases, newest first (`mtime` descending) |
| GET | `/api/checkpoint/<id>/summary` | Run summary (goal, node count, status, top metric) |
| GET | `/api/checkpoint/<id>/memory` | Letta memory contents |
| GET | `/api/checkpoint/<id>/memory_access` | Memory write/read telemetry |
| GET | `/api/checkpoint/<id>/files` | File list with sizes + types |
| GET | `/api/checkpoint/<id>/file?path=...` | Raw file content (text or base64) |
| GET | `/api/checkpoint/<id>/file/raw` | Same, alternate route |
| GET | `/api/checkpoint/<id>/filetree` | Hierarchical tree view |
| GET | `/api/checkpoint/<id>/filecontent` | Multi-file batch read |
| GET | `/api/active-checkpoint` | Currently selected checkpoint |
| POST | `/api/switch-checkpoint` | Change the active checkpoint |
| POST | `/api/delete-checkpoint` | Delete a checkpoint (also drops the matching Letta agent) — requires a challenge (MN-6) |
| POST | `/api/checkpoint/file/save` | Edit a file in-place |
| POST | `/api/checkpoint/file/delete` | Delete a file from a checkpoint |
| POST | `/api/checkpoint/compile` | Run `pdflatex` on a paper draft |

### Run lifecycle

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/launch` | Start a new BFTS run (`ari run` programmatically) — unchanged; the canonical path is `POST /api/v1/runs` |
| POST | `/api/run-stage` | Run a single pipeline stage |
| POST | `/api/stop` | Stop the active run — requires a challenge (MN-6) |

### Sub-experiments + lineage

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/sub-experiments` | All sub-experiment records |
| GET | `/api/sub-experiments/<run_id>` | Single sub-experiment detail |
| POST | `/api/sub-experiments/launch` | Launch a child run inheriting from a parent checkpoint |
| GET | `/api/lineage-decisions/<run_id>` | Decisions emitted by the stagnation rule (v0.7.0) |

### Memory backend

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/memory/health` | Letta health probe |
| GET | `/api/memory/detect` | Inventory of running Letta deploy paths |
| POST | `/api/memory/start-local` | Spawn a local Letta server |
| POST | `/api/memory/stop-local` | Stop the local Letta server |
| POST | `/api/memory/restart` | Restart the local Letta server |

### Settings + workflow

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/settings` | Read settings.json |
| POST | `/api/settings` | Write settings.json |
| GET | `/api/profiles` | Saved profile list |
| GET | `/api/env-keys` | Env-var keys ARI knows about (values redacted — MN-2) |
| POST | `/api/env-keys` | Persist env-var key/value pairs to `.env` (name allowlist — MN-2) |
| GET | `/api/workflow` | Active workflow.yaml (+ `revision` — MN-3) |
| GET | `/api/workflow/default` | Bundled default |
| GET | `/api/workflow/flow` | Workflow visualised as DAG nodes / edges |
| POST | `/api/workflow` | Save workflow.yaml (optional `base_revision` — MN-1/MN-3) |
| POST | `/api/workflow/flow` | Save the DAG view (optional `base_revision` — MN-1/MN-3) |
| POST | `/api/workflow/skills` | Toggle which skills are enabled (optional `base_revision` — MN-1/MN-3) |
| POST | `/api/workflow/disabled-tools` | Per-skill tool whitelist / blacklist (optional `base_revision` — MN-1/MN-3) |

### Wizard / config gen

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/experiment-detail` | Wizard's parsed experiment.md |
| POST | `/api/config/generate` | Generate `ari.yaml` from wizard answers |
| POST | `/api/chat-goal` | LLM-assisted goal narrative refinement |
| POST | `/api/ssh/test` | Probe an SSH cluster login |

### Uploads + few-shot corpus

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/upload` | Multipart upload into the active checkpoint |
| POST | `/api/upload/delete` | Remove an uploaded file |
| GET | `/api/fewshot/<rubric_id>` | Few-shot examples for a rubric |
| POST | `/api/fewshot/<rubric_id>/sync` | Pull the published corpus |
| POST | `/api/fewshot/<rubric_id>/upload` | Add an example |
| POST | `/api/fewshot/<rubric_id>/delete` | Remove an example |
| GET | `/api/rubrics` | Available reviewer rubrics (driven by `ARI_RUBRIC`) |

### Node reports

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/nodes/<...>/report` | Per-node `node_report.json` |

### PaperBench (v0.7.2)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/paperbench/papers` | Registered papers (`{"papers": [...]}` from the registry manifest) |
| GET | `/api/paperbench/arxiv/<arxiv_id>` | Metadata probe against the public arXiv Atom API |
| GET | `/api/paperbench/papers/<paper_id>/license` | Recorded license / redistribution posture for one paper |
| POST | `/api/paperbench/papers/import` | Register a new paper in the registry |
| POST | `/api/paperbench/papers/<paper_id>/metadata` | Merge fields into an existing manifest entry |
| POST | `/api/paperbench/papers/<paper_id>/delete` | Drop the manifest entry + paper directory (idempotent) |
| POST | `/api/paperbench/cost-estimate` | Dry-run cost estimate for a prospective run |
| POST | `/api/paperbench/run` | Enqueue PaperBench jobs for the supplied `paper_ids` |
| GET | `/api/paperbench/run/<job_id>` | Job status snapshot |
| GET | `/api/paperbench/run/<job_id>/logs` | SSE log stream for one job (`since=`, `Last-Event-ID`; 300 s window, `: heartbeat`, terminal `event: done`) |
| GET | `/api/paperbench/run/<job_id>/results` | Per-job result payload |
| GET, POST | `/api/paperbench/run/<job_id>/report` | Trigger / fetch the audit report (`languages`, `formats` — URL query or POST body) |

Job state is an in-memory table mirrored atomically to
`{registry_root}/jobs/{job_id}.json` (temp file + `os.replace`, mode `0o600`),
so a viz-server restart no longer forgets historical jobs. After a restart the
GET readers fall back to that record read-only; a job persisted in a live
status (`queued` / `running`) is reported with the additive status
`interrupted` — workers are never respawned.

### EAR + publish (v0.7.0)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/ear/<run_id>` | EAR bundle metadata for a run |
| GET | `/api/ear/<run_id>/publish-yaml` | Generated publish.yaml preview |
| POST | `/api/ear/<run_id>/curate` | Run the curate step |
| POST | `/api/ear/<run_id>/publish-yaml` | Save the publish.yaml |
| POST | `/api/ear/clone-verify` | Verify a remote bundle by hash |
| GET | `/api/publish/settings` | Backend configuration |
| POST | `/api/publish/settings` | Update backend configuration |
| GET | `/api/publish/<run_id>/preview` | Pre-publish payload preview |
| GET | `/api/publish/<run_id>/record` | Read `publish_record.json` |
| POST | `/api/publish/<run_id>/promote` | Promote `staged` → `unlisted` / `public` |
| POST | `/api/publish/<run_id>` | Push to the configured backend |

### Static + frontend

| Method | Path | Purpose |
|---|---|---|
| GET | `/static/<path>` | Bundled UI assets (security headers — MN-7) |
| GET | `/memory/<path>` | Memory inspector static page |
| GET | `/codefile?path=...` | Source file viewer (canonical-path boundary — MN-5) |

### Updating this reference

For `/api/v1`: add the route to `ari/viz/v1/router.py`, regenerate
`openapi.json` (`python -m ari.viz.v1.openapi --update`), then mirror the
one-line purpose into the endpoint table above.

For the legacy surface: the route table is the dispatch chain in
`ari-core/ari/viz/routes.py`. New routes belong on `/api/v1`, not here.

### See also

- `docs/reference/rqgm_gui_read_models.md` — semantics of the RQGM read models.
- `docs/reference/configuration.md` — the configuration control plane behind
  `/api/v1/config/*`.
- `docs/reference/environment_variables.md` — the `ARI_GUI_*` switches.
- `docs/concepts/architecture.md` — viz package overview.
- `ari-core/ari/viz/__init__.py` — module-level docstring with the current
  sub-module map.
