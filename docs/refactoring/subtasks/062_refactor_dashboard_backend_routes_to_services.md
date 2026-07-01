# Subtask 062: Refactor Dashboard Backend Routes To Services

> Phase 5: Dashboard Frontend · Depends on 059 · Risk: **High** · Runtime code change: **Yes** (when implemented)
>
> This document is a **planning artifact only**. Writing it changes no runtime
> code. It describes the work a later implementation session will perform. The
> only file this task creates is this `.md`. Classification of the target code:
> **ADAPT** (internal reshape behind an unchanged wire contract).

## 1. Goal

Complete the migration of the ARI dashboard **backend** from a hand-rolled
`if/elif` HTTP dispatcher with fat, logic-heavy handlers into a **declarative
route registry + thin-adapter handlers + a testable service layer** — *without
changing a single wire-visible endpoint path, HTTP method, JSON key, status
code, SSE frame, CORS header, or WebSocket message shape* consumed by the React
frontend (`ari-core/ari/viz/frontend/src/services/api.ts`, 863 LOC) and pinned
by `docs/reference/rest_api.md` (+ ja/zh mirrors).

Concretely, 062 lands the reshape that the Phase-4 subtasks designed and
down-paid on:

1. Replace the two giant `if/elif` chains in `routes.py` — `do_GET` (~86
   branches, `routes.py:144-1026`) and `do_POST` (~51 branches,
   `routes.py:1028-1188`) — with a **declarative route table** keyed by
   `(method, path-pattern) -> handler`, formalizing the abandoned
   `WIZARD_ROUTES` intent (`api_wizard.py:30`). Dispatch order and match
   semantics (`startswith`/`endswith`/`re.match`) must stay observably
   identical.
2. Ensure **every** handler is a thin adapter: parse request → call a service →
   serialize. No route body performs filesystem I/O, YAML merging, subprocess
   spawning, or direct `ari.*` internal reach-through. The heavy logic lives in
   service modules (`StateService`, `LaunchService`, `FileService`, and the
   PaperBench job/worker service).
3. Route the remaining in-handler **internal `ari.*` / `ari_skill_memory`
   imports** through `ari.public.*` where a public entry exists, and through a
   single thin adapter module where it does not — so the viz layer depends on
   the stable public surface, not core internals.

062 is the **High-risk culmination** in Phase 5: it is behaviour-preserving,
gated by the existing contract tests (`test_api_schema_contract.py`,
`test_server.py` 1844 LOC, `test_gui_errors.py` 1650 LOC,
`test_gui_env_propagation.py`, `test_launch_config.py`,
`test_status_fallback.py`, `test_api_process.py`, `test_public_api_boundary.py`)
passing with **no edits to their assertions**.

## 2. Background

### HTTP/WS stack (verified)

The viz backend is a bespoke, framework-free server. **There is no
Flask/FastAPI/aiohttp/ASGI/WSGI** — it is Python stdlib `http.server`.
`server.py:82` defines `_DualStackServer(ThreadingHTTPServer)` (IPv6 socket with
`IPV6_V6ONLY=0` for IPv4 fallback). All HTTP requests are handled by a single
`BaseHTTPRequestHandler` subclass `_Handler` (`routes.py:77`,
`protocol_version="HTTP/1.1"`). WebSocket runs on `port+1` via the separate
`websockets` package (`server.py:21`, `ws_serve` at `server.py:178`). Entry
`main()`/`_main()` (`server.py:183`/`159`) launches three threads: a filesystem
watcher, the HTTP server, and the asyncio WS loop. `server.py` re-exports
`_Handler`/`_write_access_log` from `routes.py` (`server.py:78`) and
`_ws_handler` from `websocket.py` (`server.py:51`) for backward compatibility.

### How routes are registered today (verified)

**There is no route table.** Dispatch is a single giant `if/elif` chain over
`self.path` strings/regexes inside `_Handler.do_GET` (`routes.py:144-1026`) and
`do_POST` (`routes.py:1028-1188`), plus `do_OPTIONS` (CORS preflight,
`routes.py:127-142`). Matching uses hand-rolled `startswith`/`endswith`/
`re.match` + `urllib.parse` query parsing. Handlers are plain module functions
imported at the top of `routes.py:27-47` from the `api_*` modules; each returns
a `dict` serialized by `_Handler._json(data, status)` (`routes.py:1190-1197`,
which always sets `Access-Control-Allow-Origin: *`). Status codes are smuggled
via `r.pop("_status", 200)` (`routes.py:1047-1057`, `1088-1089`).

`api_wizard.py:30` defines an **unused `WIZARD_ROUTES` dict** — an abandoned,
partial attempt at a declarative table (only 4 POST routes: `/api/chat-goal`,
`/api/generate-config`, `/api/launch`, `/api/run-stage`; its handlers are also
imported directly by `routes.py`). `api_state.py` (76 LOC) is already a **thin
re-export facade** (Phase 3B refactor) forwarding to `checkpoint_finder`,
`state_sync`, `checkpoint_api`, `ear`, `file_api`, `checkpoint_lifecycle`,
`node_work_api`. The codebase is already trending "thin file → sibling logic
module"; 062 finishes the *dispatch* and *handler-body* halves of that
trajectory.

### Where the heavy logic still lives (verified)

- **`GET /state` builder** inlined at `routes.py:219-666` (~450 LOC): dozens of
  `Path.exists()`/`read_text()`/`json.loads()`, glob scans, YAML profile merging
  (reading `ari-core/config/` at `routes.py:376,388,401,612`),
  `cost_trace.jsonl` tail-parsing (`routes.py:287-298`), and reaching into
  `_st._last_proc.poll()` + `ari.pidfile`.
- **Launch/subprocess orchestration**: `.env` discovery + 15+ `ARI_*` env-var
  mapping inside `api_experiment._api_run_stage` and `_api_launch`
  (`api_experiment.py`, 929 LOC), plus `Popen` in
  `api_orchestrator._api_launch_sub_experiment` (`api_orchestrator.py:287`) and
  `api_process` (`api_process.py`, 205 LOC: `Popen`/`pkill`/`pgrep`), and
  `subprocess.run` in `api_memory` (`api_memory.py`, 227 LOC).
- **SSE loops written inline in the route**: `/api/logs` (`routes.py:901-908`,
  `Content-Type: text/event-stream` at `routes.py:903`) and the PaperBench job
  logs stream (`routes.py:934-1000`, heartbeat `: heartbeat\n\n` at
  `routes.py:996`).
- **Inline binary/file serving + hand-rolled path-traversal checks**:
  `/codefile` (`routes.py:678-719`), `/api/checkpoint/<id>/file/raw`
  (`routes.py:797-818`), `/api/checkpoint/<id>/paper.(pdf|tex)`
  (`routes.py:727-744`).
- **Inline container/ollama coupling**: `from ari.container import
  get_container_info/list_images` (`routes.py:886-890`), inline `ContainerConfig`
  build for `POST /api/container/pull` (`routes.py:1174-1185`), and the ollama
  reverse proxy `_ollama_proxy` (`routes.py:673-676` GET, `1146-1148` POST).
- **Mutable module-level globals** in `state.py` (79 LOC): `_settings_path`,
  `_clients`, `_checkpoint_dir`, `_last_proc`, `_running_procs`, `_launch_config`,
  `_sub_experiments`, `_gpu_monitor_proc`, `_staging_dir` — read/written directly
  by handlers. `state.py` already exposes accessors (`set_active_checkpoint`
  ~`:54`, `get_sub_experiments` `:34`, `require_checkpoint_dir` `:73`).
  PaperBench keeps its own in-memory job store `_JOBS` + `_JOBS_LOCK`
  (`api_paperbench.py:496-497`, lost on restart).

### Why this is 062, and its relationship to the Phase-4 backend subtasks

The dashboard backend reshape spans two phases. The Phase-4 subtasks authored
the **design and down payment**; 062 (Phase 5, High risk) is the **execution /
consolidation** that lands the full registry + service layer. 062 must not
re-author those designs — it consumes them and completes the migration for any
handler a Phase-4 subtask left inline:

- **015** `refactor_dashboard_viz_api_services` — the umbrella policy/scaffolding
  (route registry, response-wrapper/DTO convention, adapter boundary, state
  encapsulation). 062 realizes that scaffolding across the whole dispatcher.
- **021** `extract_viz_services_from_routes` — the Medium-risk down payment that
  extracts the `/state` builder into `StateService` and the launch/env logic into
  `LaunchService` while *keeping* the `if/elif` chain. 062 finishes what 021
  started by replacing the dispatch chain and thinning any remaining handler.
- **023** `separate_viz_file_io_from_route_handlers` — the `FileService` for
  per-checkpoint file CRUD + traversal guards. 062 registers those handlers on
  the table; it does not re-implement the FileService.
- **061** `define_dashboard_dto_and_schema_policy` — the DTO/response-shape policy
  062 conforms to (it does not invent a new shape).
- **060/065** — the FE-side contract inventory and the contract/schema tests that
  bound and verify 062.

If a Phase-4 subtask (015/021/023) has *not* landed when 062 is implemented, 062
performs that extraction as part of its own work rather than assuming it exists;
if they *have* landed, 062 consolidates them behind the registry. Either way the
**wire contract is frozen** and identical before and after.

Note: the "sonfigs" directory referenced in some planning prompts **does not
exist**. Profile YAML consumed by `/state` is read from the top-level
`ari-core/config/` rubric/profile tree (`routes.py:376,388,401,612`), distinct
from `ari-core/ari/config/` (locator code) and `ari-core/ari/configs/` (packaged
defaults). 062 touches none of the config-consolidation concerns (subtask 003).

## 3. Scope

In scope (implementation phase, not this planning doc):

- **Route registry.** Introduce a declarative table (e.g.
  `ari-core/ari/viz/route_table.py`) mapping `(method, matcher) -> handler`,
  where `matcher` covers the existing exact-string, `startswith`, `endswith`,
  and `re.match` cases. Rewrite `_Handler.do_GET`/`do_POST` to iterate the table
  in the **same order** the `if/elif` chain evaluates today, calling the first
  match. `do_OPTIONS` (`routes.py:127-142`) and the SSE/streaming endpoints keep
  their bespoke response paths (register them as "raw" handlers that own the
  socket, not `_json`-returning handlers).
- **Thin adapters.** Any handler still doing I/O/subprocess/YAML/internal-import
  work delegates to a service: `StateService.build_app_state(...)` for `/state`;
  `LaunchService` (`.env` discovery + `ARI_*` mapping + `Popen`) for
  `_api_run_stage`/`_api_launch`/`_api_launch_sub_experiment`; `FileService` for
  file serving/CRUD/traversal; a PaperBench job service wrapping `_JOBS`. Where
  021/023 already extracted these, 062 just wires the registered handler to them.
- **Public-API boundary.** Switch handler/service internal imports (`ari.paths`,
  `ari.checkpoint`, `ari.config`, `ari.llm.client`, `ari.clone`,
  `ari.orchestrator.web_provenance`, `ari.container`, `ari.pidfile`,
  `ari_skill_memory.backends`) to `ari.public.*` where an entry exists, else a
  single thin `ari/viz/internal_adapters.py` wrapper carrying a
  `# REVIEW_REQUIRED: promote to ari.public.*` note. Do **not** create new
  `ari.public.*` modules here.
- **State encapsulation (additive).** Add `state.py` read accessors where a
  service needs a global, mirroring `get_sub_experiments()`; keep every attribute
  module-level and monkeypatchable.
- Update `ari-core/ari/viz/README.md` module map to list the registry + any new
  service modules. Update `docs/reference/rest_api.md` (+ ja/zh) **only** if a
  symbol name a doc references moves — no endpoint/shape changes, so likely no
  doc edit.

Out of scope: everything in Section 4.

## 4. Non-Goals

- **Do NOT change any endpoint path, HTTP method, JSON key, status code, CORS
  header presence/absence, SSE frame format, or WebSocket `update` message
  shape.** The dashboard REST + WS surface is the contract (ADAPT, not break).
- **Do NOT introduce a web framework** (Flask/FastAPI/aiohttp/ASGI). The registry
  is a plain dict/list dispatched by the existing `BaseHTTPRequestHandler`; no
  new runtime dependency.
- **Do NOT add authentication/authorization** and do NOT alter the
  `Access-Control-Allow-Origin: *` posture. The open, no-auth posture is
  REVIEW_REQUIRED for a later security subtask; note it, do not "fix" it. Do not
  accidentally *remove* a CORS header either (some inline handlers deliberately
  omit it — `routes.py:667-672`).
- **Do NOT redesign the DTO/response convention** (`{"ok"}` vs `{"error"}`,
  `_status` smuggling). 062 conforms to 061's policy; it must not unilaterally
  unify these regimes if that would change wire bytes.
- **Do NOT touch the React/TypeScript frontend** (`ari/viz/frontend/`,
  `services/api.ts` 863 LOC). `npm test`/`npm run build` are N/A for 062 (no
  frontend file changes). Frontend client/type work is **063**.
- **Do NOT modify the WS watcher / broadcast** (`state_sync.py` 117 LOC,
  `websocket.py` 36 LOC) or the `tree.json`/`nodes_tree.json` → `update` snapshot
  shape.
- **Do NOT rename directories or move packages.** Adding new modules (a
  `services/` subpackage or top-level `route_table.py`/`internal_adapters.py`)
  inside `ari/viz/` is additive and allowed; renaming an existing dir is not.
- **Do NOT resolve the `core → viz` back-edge** (`cli/lineage.py:151` importing
  `ari.viz.api_orchestrator._api_launch_sub_experiment`) — flag REVIEW_REQUIRED
  for a dependency-boundary subtask; do not refactor it here.
- **Do NOT delete `api_wizard.WIZARD_ROUTES`** as a separate cleanup — 062 either
  supersedes it by the real registry (then remove the dead stub as part of that
  same commit) or leaves it; do not leave a half-adopted table.
- **Do NOT create the `check_viz_api_schema.py` checker** — that is 030.
- No `sonfigs/` involvement — that directory does not exist in the repo.

## 5. Current Files / Directories to Inspect

Primary target package — `ari-core/ari/viz/` (27 `.py` files, 8103 LOC total;
verified counts):

| Path | LOC | Role in 062 |
| --- | --- | --- |
| `ari-core/ari/viz/routes.py` | 1197 | `_Handler` dispatch: `do_OPTIONS` (`:127-142`), `do_GET` (`:144-1026`, ~86 branches), `do_POST` (`:1028-1188`, ~51 branches), `_json` (`:1190-1197`), `_write_access_log` (`:69`). **Replace dispatch with registry; thin any remaining fat handler** (`/state` `:219-666`, container `:886-890,1174-1185`, ollama `:673-676,1146-1148`, SSE `:901-908,934-1000`, file serving `:678-719,727-744,797-818`). |
| `ari-core/ari/viz/api_experiment.py` | 929 | `_api_run_stage`/`_api_launch`: `.env`/`ARI_*`/`Popen`. Delegate to `LaunchService`; register handlers. |
| `ari-core/ari/viz/api_paperbench.py` | 813 | PaperBench endpoints + in-memory `_JOBS`/`_JOBS_LOCK` (`:496-497`). Register; wrap job store in a service. |
| `ari-core/ari/viz/api_settings.py` | 553 | `GET|POST /api/settings`, env-keys, workflow, skills, profiles, rubrics, scheduler. Register handlers. |
| `ari-core/ari/viz/api_workflow.py` | 462 | Workflow flow/default/skills/disabled-tools. Register handlers. |
| `ari-core/ari/viz/ear.py` | 452 | EAR endpoints (`/api/ear/*`, node reports, curate, publish-yaml). Register handlers. |
| `ari-core/ari/viz/checkpoint_api.py` | 327 | Checkpoints list/summary/lineage. Register handlers. |
| `ari-core/ari/viz/api_orchestrator.py` | 321 | `_api_launch_sub_experiment` (`Popen :287`). Delegate to `LaunchService`. |
| `ari-core/ari/viz/api_paperbench_worker.py` | 319 | PaperBench worker (Popen/pipeline). Register/wrap. |
| `ari-core/ari/viz/file_api.py` | 307 | Per-checkpoint file CRUD + traversal (023's territory). Register; delegate to `FileService`. |
| `ari-core/ari/viz/api_tools.py` | 259 | wizard chat-goal / config-generate / upload / ssh-test. Register handlers. |
| `ari-core/ari/viz/node_work_api.py` | 233 | filetree/filecontent/memory per node. Register handlers. |
| `ari-core/ari/viz/api_memory.py` | 227 | memory health/detect + start/stop/restart (`subprocess.run`). Register/delegate. |
| `ari-core/ari/viz/api_fewshot.py` | 221 | fewshot get/sync/upload/delete. Register handlers. |
| `ari-core/ari/viz/api_process.py` | 205 | gpu-monitor + stop (`Popen`/`pkill`/`pgrep`). Register/delegate to `LaunchService` where shared. |
| `ari-core/ari/viz/checkpoint_lifecycle.py` | 205 | delete/switch checkpoint. Register handlers. |
| `ari-core/ari/viz/server.py` | 201 | Re-exports `_ws_handler` (`:51`), `_Handler`/`_write_access_log` (`:78`); `_DualStackServer` (`:82`); `main`/`_main` (`:183`/`159`). Must keep re-exporting the same symbols. |
| `ari-core/ari/viz/api_publish.py` | 191 | publish settings/preview/record/promote. Register handlers. |
| `ari-core/ari/viz/ui_helpers.py` | 183 | `_build_experiment_detail_config`, `_collect_resource_metrics`, `_extract_goal_from_md` (used by `/state`). Reuse; do not duplicate. |
| `ari-core/ari/viz/state_sync.py` | 117 | WS watcher/broadcast. **Read-only** (WS territory). |
| `ari-core/ari/viz/api_ollama.py` | 90 | `_api_ollama_resources`, `_ollama_proxy`. Register; keep raw-proxy path. |
| `ari-core/ari/viz/state.py` | 79 | Mutable globals + accessors. Add read accessors; keep attrs monkeypatchable. |
| `ari-core/ari/viz/api_state.py` | 76 | Thin re-export facade (Phase 3B). Keep its `from .api_state import ...` symbol paths intact. |
| `ari-core/ari/viz/checkpoint_finder.py` | 65 | `_resolve_checkpoint_dir`, `_check_pid_alive`. Reuse. |
| `ari-core/ari/viz/websocket.py` | 36 | `_ws_handler`. **Read-only** (WS territory). |
| `ari-core/ari/viz/api_wizard.py` | 35 | Unused `WIZARD_ROUTES` (`:30`). Superseded by the real registry (remove only as part of adopting it). |
| `ari-core/ari/viz/README.md` | — | Module map to update. |

Contract / consumer / test files (read-only in 062 unless noted):

- `ari-core/ari/viz/frontend/src/services/api.ts` (863 LOC) — the API client that
  consumes these endpoints. **Do not edit**; use to confirm no shape drifts.
  (Frontend client/type refactor is 063.)
- `docs/reference/rest_api.md`, `docs/reference/api_paperbench.md` (+ `docs/ja/`,
  `docs/zh/` mirrors) — REST endpoint reference; the frozen contract 062
  preserves.
- `ari-core/ari/public/` — `paths`, `container`, `cost_tracker`, `llm`, `run_env`,
  `config_schema`, `claim_gate`, `verified_context` (the stable surface handlers
  should prefer). Check which internal imports already have a public equivalent.
- Tests (all under `ari-core/tests/`): `test_api_schema_contract.py` (pins
  `AppState`/`Settings`/`Checkpoint`/`CheckpointSummary` keys; monkeypatches
  `_st._checkpoint_dir`, `_last_proc`, `_running_procs`, `_settings_path`),
  `test_server.py` (1844), `test_gui_errors.py` (1650), `test_workflow_contract.py`
  (1606), `test_wizard.py` (1133), `test_gui_env_propagation.py`,
  `test_launch_config.py`, `test_status_fallback.py`, `test_api_process.py`,
  `test_public_api_boundary.py`, `test_viz_fewshot_api.py`, `test_viz_memory_api.py`,
  `test_viz_repro_synth.py`, `test_dashboard_html.py`, `test_node_report.py`,
  `test_api_paperbench_worker.py`, `test_settings_propagation.py`.

The **059** structure inventory and **060** API-contract inventory are the
authoritative inputs; read them first (they are the frozen "must-not-break"
lists).

## 6. Current Problems

1. **No route table (order-sensitive string matching).** ~137 endpoints are
   dispatched by two hand-written `if/elif` chains (`routes.py:144-1026` GET,
   `1028-1188` POST). Adding, reordering, or auditing a route means editing a
   ~1000-line method; there is no single enumerable source of endpoints (which is
   exactly why 030's schema checker is hard). The abandoned `WIZARD_ROUTES`
   (`api_wizard.py:30`) is dead evidence of the intended fix.
2. **God handler.** The `GET /state` branch is ~450 LOC inlined in `do_GET`
   (`routes.py:219-666`), mixing checkpoint resolution, glob scans, YAML profile
   merge (`config/` reads at `:376,388,401,612`), `cost_trace.jsonl` tail-parsing
   (`:287-298`), and `_st._last_proc.poll()`/`ari.pidfile` probing. Only
   testable end-to-end through the HTTP stack.
3. **Duplicated launch orchestration.** `.env` discovery + `ARI_*` env mapping +
   `Popen` wiring recurs across `_api_run_stage`/`_api_launch`
   (`api_experiment.py`) and `_api_launch_sub_experiment`
   (`api_orchestrator.py:287`); a change to env mapping must be made in multiple
   places (already the reason `test_gui_env_propagation.py` exists).
4. **Handlers bypass the public API.** Route handlers import core internals
   directly (`ari.paths`, `ari.checkpoint`, `ari.config`, `ari.llm.client`,
   `ari.clone`, `ari.orchestrator.web_provenance`, `ari.container` at
   `routes.py:886-890,1174-1185`, `ari.pidfile`, and
   `ari_skill_memory.backends`). This couples viz to internals and is not guarded
   (`test_public_api_boundary.py` only scans `ari-skill-*`, not `ari/viz`).
5. **Streaming/proxy logic inline in routes.** SSE loops (`/api/logs`
   `routes.py:901-908`; PaperBench logs `:934-1000`, heartbeat `:996`) and the
   ollama reverse proxy (`:673-676,1146-1148`) live in the dispatcher body,
   making the handler method huge and the streaming logic untestable in
   isolation.
6. **Unencapsulated global state.** Handlers read/write `state.py` globals
   directly (`_st._last_proc`, `_st._checkpoint_dir`, `_st._running_procs`, …) and
   PaperBench keeps a restart-losing `_JOBS` dict (`api_paperbench.py:496-497`).
   Any extraction is only safe if services read/write the *same* globals so
   monkeypatch-driven tests still observe the effects.
7. **`_status` smuggling + two reply regimes.** Status codes ride inside the
   response dict via `r.pop("_status", 200)` (`routes.py:1047-1057,1088-1089`)
   and two shapes coexist (`{"ok"}` vs `{"error"}`). 062 must preserve these on
   the wire even while formalizing them behind the registry (per 061).

## 7. Proposed Design / Policy

**Classification:** `routes.py` + the `api_*.py` handlers are **ADAPT** (internal
reshape behind unchanged endpoints/shapes). `state.py` is **ADAPT** (add
accessors, keep attrs). `api_state.py`/`server.py` facades are **KEEP** (must
keep re-exporting). `api_wizard.WIZARD_ROUTES` is **MERGE** into the real registry
(then remove the stub). Direct-internal-import sites are **ADAPT /
REVIEW_REQUIRED** (route through `ari.public.*` where possible). No file is a
DELETE_CANDIDATE. Nothing here is "deprecated" (that term is reserved for
external contracts).

### 7.1 Route registry (new)

New module, e.g. `ari-core/ari/viz/route_table.py`, exposing a declarative list
evaluated in the same order the current chain evaluates:

```
# match kind covers the existing exact / startswith / endswith / regex cases
Route = namedtuple("Route", "method match handler kind")  # kind: "json" | "raw"
GET_ROUTES:  list[Route]
POST_ROUTES: list[Route]
```

`_Handler.do_GET`/`do_POST` become a short loop: find the first matching
`Route`, dispatch. `kind="json"` handlers return a dict and are serialized by
`_json` (preserving the `_status`-pop and CORS behaviour). `kind="raw"` handlers
own the socket directly (SSE `/api/logs` and PaperBench logs, the ollama proxy,
binary file serving) — they must reproduce the exact current bytes/headers. The
**iteration order must equal the `if/elif` order** so overlapping prefixes
(e.g. `/api/paperbench/run/<id>/logs` vs `/results` vs `/report`) resolve
identically. Fold the 4 `WIZARD_ROUTES` entries into this table and delete the
dead stub in the same commit.

### 7.2 Service layer (new or reused)

- `StateService.build_app_state(...) -> dict` owns `routes.py:219-666` verbatim
  in behaviour (same globs, same YAML merge order reading `ari-core/config/`,
  same `cost_trace.jsonl` tail, same `has_paper`/`has_pdf` flags, same
  process-liveness fields), reusing `ui_helpers.*`. If 021 already created this,
  062 reuses it.
- `LaunchService.build_process_env(...)` + `spawn_experiment(...)` own `.env`
  discovery order, the full `ARI_*` mapping, and `Popen` + `_st._last_proc`/
  `_st._running_procs` writes shared by `_api_run_stage`, `_api_launch`,
  `_api_launch_sub_experiment`. **Every env key and its derivation reproduced
  1:1** (`test_gui_env_propagation.py`, `test_launch_config.py`).
- `FileService` owns file serving/CRUD + traversal guards (`/codefile`
  `:678-719`, `/file/raw` `:797-818`, `paper.*` `:727-744`, `file_api.py`). If
  023 created it, 062 reuses it.
- A PaperBench job service wraps `_JOBS`/`_JOBS_LOCK` (`api_paperbench.py:496-497`)
  behind get/set/update accessors (still in-memory; persistence is out of scope).

### 7.3 Internal-import routing

For each direct internal import in a handler/service: switch to `ari.public.*`
where an equivalent exists (`ari.public.paths`, `ari.public.container`,
`ari.public.cost_tracker`, `ari.public.run_env`, `ari.public.llm`,
`ari.public.config_schema`); otherwise add a single thin
`ari-core/ari/viz/internal_adapters.py` wrapper (`pid_is_alive`, `read_pid`,
`memory_backend`, …) with `# REVIEW_REQUIRED: promote to ari.public.*` comments.
Do **not** create new `ari.public.*` modules in 062.

### 7.4 State encapsulation

Do not rip out `state.py` globals. Add read accessors only where a service needs
one (mirroring `get_sub_experiments()`), keeping attributes as plain module
globals so `monkeypatch.setattr(_st, "_last_proc", ...)` still mutates what the
service reads.

### 7.5 Compatibility policy

Handlers keep their names and `from .api_* import ...` paths;
`server.py`/`routes.py` re-exports (`_Handler`, `_write_access_log`,
`_ws_handler`) and the `api_state.py` facade symbols are untouched. New modules
(`route_table.py`, service modules, `internal_adapters.py`) are additive. Every
endpoint's method/path/JSON shape/status/CORS/SSE/WS bytes are byte-identical.

## 8. Concrete Work Items

1. Read **059** (structure inventory) and **060** (API-contract inventory);
   cross-check against `docs/reference/rest_api.md` and
   `test_api_schema_contract.py`. Enumerate every `(method, path, response
   shape, status, CORS header, streaming?)` tuple the registry must preserve.
2. Snapshot the current dispatch order: extract the ordered list of
   `(method, matcher)` from `do_GET`/`do_POST` so the registry can be diffed for
   order-equivalence.
3. Add `ari/viz/route_table.py` with `GET_ROUTES`/`POST_ROUTES` in the exact
   current order; classify each as `json` or `raw`. Fold in the 4
   `WIZARD_ROUTES` entries.
4. Rewrite `_Handler.do_GET`/`do_POST` to iterate the table; keep `do_OPTIONS`,
   `_json`, `_write_access_log`, and the `_status`-pop untouched in behaviour.
5. For each remaining fat/`raw` handler, delegate to a service
   (`StateService`/`LaunchService`/`FileService`/PaperBench job service) — reuse
   021/023 extractions if present, else perform the extraction here. Keep return
   dicts + `_status` fields identical.
6. Add `ari/viz/internal_adapters.py`; switch handler/service internal imports to
   `ari.public.*` (where available) or the adapter, with REVIEW_REQUIRED notes
   for pidfile / memory-backend / any no-public-surface case.
7. Add any needed `state.py` read accessors; verify no attribute is removed or
   renamed and all stay monkeypatchable.
8. Remove the now-superseded `api_wizard.WIZARD_ROUTES` stub (same commit that
   adopts the registry) and confirm `ruff` is clean.
9. Update `ari/viz/README.md` module map to list `route_table.py` + service
   modules. Edit `docs/reference/rest_api.md` (+ ja/zh) only if a referenced
   symbol name moved — endpoints/shapes must not.
10. Run the full gate (Section 12); fix only real breakages, never by weakening
    an assertion or changing a wire shape. Land the registry, the service
    delegations, and the internal-import routing as **separate commits**.

## 9. Files Expected to Change

Modified (existing, all under `ari-core/ari/viz/`):

- `routes.py` — `do_GET`/`do_POST` become registry-driven loops; fat/`raw`
  handlers delegate to services; internal `ari.*` imports routed via public API /
  adapter. `_json`, `_write_access_log`, `do_OPTIONS` behaviour unchanged.
- `api_experiment.py`, `api_orchestrator.py`, `api_process.py`, `api_memory.py` —
  subprocess/env logic delegated to `LaunchService`; handlers registered.
- `api_paperbench.py`, `api_paperbench_worker.py` — `_JOBS` wrapped in a service;
  handlers registered.
- `file_api.py`, `node_work_api.py` — file serving/CRUD delegated to
  `FileService` (or reused from 023); handlers registered.
- `api_settings.py`, `api_workflow.py`, `api_tools.py`, `api_fewshot.py`,
  `api_publish.py`, `api_ollama.py`, `ear.py`, `checkpoint_api.py`,
  `checkpoint_lifecycle.py` — handlers registered on the table (bodies otherwise
  unchanged unless they still hold heavy logic).
- `api_wizard.py` — dead `WIZARD_ROUTES` stub removed once folded into the real
  registry.
- `state.py` — additive read accessors only (optional).
- `README.md` — module map lists new modules.

New files (additive, inside `ari-core/ari/viz/`):

- `route_table.py` — declarative `(method, matcher) -> handler` registry.
- `internal_adapters.py` — thin wrappers for internal (`ari.pidfile`,
  `ari_skill_memory.backends`, …) access, with REVIEW_REQUIRED notes.
- `services/state_service.py`, `services/launch_service.py`,
  `services/file_service.py`, `services/paperbench_jobs.py` (or a flat layout) —
  only those not already created by 021/023; align names with 015's scaffolding.

Must **NOT** change: any endpoint path/JSON shape/status/CORS/SSE bytes;
`server.py` re-exports; `api_state.py` facade symbols; `state_sync.py`;
`websocket.py`; the WS `update` shape; the frontend (`ari/viz/frontend/`);
`ari-core/config/` YAML; `docs/reference/rest_api.md` shapes.

## 10. Files / APIs That Must Not Be Broken

- **Dashboard REST contract:** every endpoint path + method + JSON shape in
  `routes.py`/`api_*.py` consumed by `frontend/src/services/api.ts` and pinned by
  `docs/reference/rest_api.md` — including the `GET /state` `AppState` payload
  keys, the `/api/launch`/`/api/run-stage` `{"ok": ...}` shape, and the
  `_status`-smuggling convention (`routes.py:1047-1057,1088-1089`).
- **WebSocket `update` message** shape (`websocket.py` + `state_sync.py`) — 062
  does not touch it; byte-identical.
- **SSE frames** for `/api/logs` (`routes.py:901-908`) and PaperBench job logs
  (`routes.py:934-1000`, heartbeat `: heartbeat\n\n` at `:996`) — including
  headers, deadlines, and heartbeat cadence — unchanged.
- **Backward-compat re-exports:** `server.py` re-exporting `_Handler`,
  `_write_access_log` (`:78`), `_ws_handler` (`:51`); `routes.py`'s top-level
  `from .api_* import` symbol names; `api_state.py` facade symbols. Tests import
  handlers by these exact paths.
- **`state.py` attribute surface:** `_checkpoint_dir`, `_last_proc`,
  `_running_procs`, `_settings_path`, `_launch_config`, `_sub_experiments`,
  `_clients`, `_gpu_monitor_proc`, `_staging_dir` — must remain module-level and
  monkeypatchable.
- **`ari.public.*`** surface — 062 consumes it, never modifies it.
- **Contract surfaces from the master rules:** CLI `ari`, MCP tool contracts
  (`ari-skill-*`), checkpoint/output/config file formats, `ari-skill-*` →
  `ari-core` stable interfaces, README/docs usage, and scripts called by
  `.github/workflows/` (e.g. `refactor-guards.yml`, `readme-sync.py`) — all
  untouched by this subtask.

## 11. Compatibility Constraints

- **Behaviour-preserving.** No endpoint added/removed/renamed; no JSON key
  added/removed/reordered on the wire; no status code, CORS header, SSE frame, or
  WS message changed. The registry must dispatch in the **same order** as the
  current `if/elif` chain (overlapping-prefix routes resolve identically).
- **Env + spawn semantics unchanged.** `.env` discovery order, the full `ARI_*`
  mapping, the child command line, `cwd`, and the `_st._last_proc`/`_running_procs`
  writes reproduced 1:1. `LaunchService` wraps, it does not rewrite.
- **Global state stays observable.** Services read/write the same `state.py`
  globals the handlers do, so monkeypatch-based tests still see effects. Read
  `_st._last_proc` at call time, never snapshot at import.
- **No new runtime dependencies.** `radon` is not installed; `pnpm` is absent
  (npm only). Use only the standard library + already-vendored packages
  (`websockets`). `ruff` is available.
- **Term discipline:** internal viz code superseded here is ADAPT/refactored /
  MERGE, never "deprecated" (reserved for external contracts).
- **No `sonfigs/`.** Profile YAML is read from `ari-core/config/`
  (`routes.py:376,388,401,612`). 062 does not touch config consolidation
  (subtask 003).
- **Security posture unchanged.** No auth added; `Access-Control-Allow-Origin: *`
  unchanged; do not remove the intentional CORS omissions (`routes.py:667-672`).
- **No new `~/.ari/` references** (guarded by `refactor-guards.yml`).

## 12. Tests to Run

Baseline gate (run before and after; must be green after):

- `python -m compileall .`
- `ruff check .`
- `pytest -q` (full suite)

Targeted viz suites that must remain green with **no assertion edits** (all under
`ari-core/tests/`):

- `test_api_schema_contract.py` — pins `AppState`/`Settings`/`Checkpoint`/
  `CheckpointSummary` keys; the primary `/state` + settings contract guard.
- `test_server.py` (1844 LOC) — HTTP handler behaviour (the registry's main
  guard: every dispatched path must still resolve).
- `test_gui_errors.py` (1650 LOC) — handler error paths.
- `test_workflow_contract.py` (1606 LOC), `test_wizard.py` (1133 LOC) — workflow
  + wizard endpoint contracts.
- `test_gui_env_propagation.py`, `test_launch_config.py` — env mapping / launch
  config into spawned processes (the `LaunchService` guard).
- `test_status_fallback.py` — `/state` process-status fallback (the `_last_proc`
  liveness logic).
- `test_api_process.py` — process-control endpoints.
- `test_public_api_boundary.py` — must stay green (062 must not introduce a new
  `ari-skill-*` → non-public import; note it does not cover `ari/viz` itself).
- Plus the broader viz set: `test_viz_fewshot_api.py`, `test_viz_memory_api.py`,
  `test_viz_repro_synth.py`, `test_dashboard_html.py`, `test_node_report.py`,
  `test_api_paperbench_worker.py`, `test_settings_propagation.py`.

Frontend (`npm test` / `npm run build`): **not applicable** — 062 changes no file
under `ari-core/ari/viz/frontend/`. (Frontend client/type work is 063.)

CI guard to keep green: `.github/workflows/refactor-guards.yml` (runs
`pytest ari-core/tests/ -q` under a redirected `HOME`; forbids new `~/.ari/`
references outside `migrations/`).

## 13. Acceptance Criteria

1. `_Handler.do_GET`/`do_POST` dispatch via a declarative `route_table.py`
   registry, in the same order as the pre-refactor `if/elif` chain; no endpoint's
   resolution changes. The dead `api_wizard.WIZARD_ROUTES` stub is removed (folded
   into the registry).
2. No route handler performs filesystem I/O, YAML merging, subprocess spawning,
   or direct internal `ari.*`/`ari_skill_memory` reach-through; the heavy logic
   lives in service modules (`StateService`, `LaunchService`, `FileService`,
   PaperBench job service), reused from 021/023 where present.
3. Handler/service internal imports go through `ari.public.*` where available,
   else through `ari/viz/internal_adapters.py` with REVIEW_REQUIRED notes; no new
   `ari.public.*` module is created.
4. `python -m compileall .` and `ruff check .` are clean.
5. All Section 12 tests pass with **no edits to assertions** and no change to any
   wire shape (REST, SSE, or WS).
6. `server.py`/`routes.py`/`api_state.py` re-export symbol names are unchanged;
   `state.py` attributes remain module-level and monkeypatchable.
7. `docs/reference/rest_api.md` (+ ja/zh mirrors) require no shape edit; the
   README module map lists the new modules.
8. No new `~/.ari/` references; `refactor-guards.yml` stays green.

## 14. Rollback Plan

- The change is confined to `ari-core/ari/viz/` (route handlers + additive
  registry/service modules). Revert is a single `git revert` of the
  implementation branch; there is no data migration and no checkpoint/config
  format change, so rollback cannot corrupt existing checkpoints or settings.
- Because the refactor is behaviour-preserving and gated by
  `test_api_schema_contract.py`, `test_server.py` (1844 LOC),
  `test_gui_env_propagation.py`, and `test_status_fallback.py`, a shape/order/env
  regression surfaces in CI before merge.
- Land as **separate commits** — (a) route registry, (b) service delegations,
  (c) internal-import routing — so any one can be reverted independently (e.g. if
  the env-mapping port drifts, revert only the `LaunchService` commit and restore
  the inline handlers; if the registry order regresses, revert only the registry
  commit and restore the `if/elif` chain).

## 15. Dependencies

Per the master dependency graph (`059 -> 060, 061, 062, 063, 064, 065, 066`):

- **Hard predecessor: 059** (`inventory_dashboard_frontend_backend_structure`).
  059 is the Phase-5 root inventory from which the whole dashboard fan-out
  depends; 062 must not start until 059's FE/BE structure inventory is complete.
- **Runtime-change inventory gate.** 062 changes runtime code (Section 16), so
  the cross-cutting rule applies: the nine inventory subtasks
  **001, 002, 020, 036, 045, 053, 059, 060, 067** must all precede it. The most
  directly relevant are **020** (`inventory_viz_dashboard_api_contracts`, the
  Phase-4 endpoint/shape freeze), **059** (structure), and **060**
  (`inventory_dashboard_api_contracts`, the FE-side contract inventory) — these
  are the authoritative "must-not-break" lists 062 preserves.
- **Design input: 061** (`define_dashboard_dto_and_schema_policy`, also
  `059 -> 061`). 062 conforms to 061's DTO/response-shape policy; it does not
  invent a new shape. Coordinate so the registry's response handling matches
  061's convention on the wire.
- **Phase-4 precursors / down payments (different phase, compatible direction):**
  **015** (`refactor_dashboard_viz_api_services`, registry + service-layer
  umbrella), **021** (`extract_viz_services_from_routes`, `StateService`/
  `LaunchService` extraction), **023** (`separate_viz_file_io_from_route_handlers`,
  `FileService`). If landed first, 062 consolidates them behind the registry; if
  not, 062 performs the equivalent extraction. These are not hard graph edges to
  062 but should be reconciled to avoid duplicate work.
- **Downstream / parallel (all depend on 059):** **063**
  (`refactor_dashboard_frontend_api_client_and_types`) depends on 062's backend
  contract staying stable; **065** (`add_dashboard_contract_and_schema_tests`)
  verifies 062; **066** (`add_dashboard_build_and_ci_plan`) plans the CI wiring.
  062 does not block them beyond keeping the contract frozen.

## 16. Risk Level

**Risk: High.** **Does this subtask change runtime code? Yes** — implementing 062
rewrites the HTTP dispatch of the entire dashboard backend (replacing ~137
`if/elif` branches with a route registry) and moves the remaining heavy handler
logic into service modules, rewiring handler imports through `ari.public.*`.
(Writing *this planning document* changes no runtime code.)

Risk drivers: (a) the registry must reproduce the **order-sensitive** matching of
overlapping path prefixes (e.g. `/api/paperbench/run/<id>/logs` vs `/results` vs
`/report`, `routes.py:934-1010`) — a single reorder silently misroutes a live
endpoint; (b) the `/state` builder feeds the dashboard home screen and its
`AppState` shape is pinned by `test_api_schema_contract.py`; (c) the launch/env
path is on the critical experiment-start path where a dropped `ARI_*` key breaks
propagation; (d) `raw` (SSE/proxy/binary) handlers own the socket and must
reproduce exact bytes/headers. Mitigations: behaviour-preserving mandate, the
order-equivalence snapshot (work item 2), the strong existing guards
(`test_server.py` 1844 LOC, `test_gui_errors.py` 1650 LOC,
`test_api_schema_contract.py`, `test_gui_env_propagation.py`), additive-only new
modules, and per-concern commits. Rated High (not Medium like the Phase-4 down
payment 021) because the *dispatch mechanism itself* changes for every endpoint,
not just individual handler bodies.

## 17. Notes for Implementer

- **Read 059 + 060 first.** Treat their endpoint/shape inventories as the frozen
  contract. Capture the ordered `(method, matcher)` list from `do_GET`/`do_POST`
  and diff it against `route_table.py` to prove order-equivalence *before*
  running the suite.
- **Preserve dispatch order exactly.** The `if/elif` chain's first-match-wins
  behaviour is a contract. Register routes in source order; do not "optimize" by
  grouping or sorting. Watch the PaperBench `/run/<id>/...` family
  (`routes.py:934-1010`) and the ollama proxy prefix (`:673-676,1146-1148`).
- **Distinguish `json` vs `raw` handlers.** SSE (`/api/logs` `:901-908`;
  PaperBench logs `:934-1000`, heartbeat `:996`), the ollama reverse proxy, and
  binary file serving (`/codefile` `:678-719`, `/file/raw` `:797-818`, `paper.*`
  `:727-744`) write to the socket directly — they are **not** `_json`-returning
  handlers. Register them as `raw` and keep their headers/deadlines/heartbeat
  byte-identical.
- **Port, do not clean up.** The `/state` builder's globs, YAML merge order, and
  `cost_trace.jsonl` tail logic (`routes.py:287-298`), and the `ARI_*` mapping in
  `api_experiment.py`, are behaviour — move them verbatim.
- **Keep globals observable.** Services must read/write the same `state.py`
  attributes the handlers do. Do not snapshot `_st._last_proc` into a
  service-local variable at import time — read at call time so
  `monkeypatch.setattr(_st, "_last_proc", ...)` still works.
- **Reuse Phase-4 extractions.** If 021 already created `StateService`/
  `LaunchService` and 023 created `FileService`, wire the registered handlers to
  them rather than re-extracting. Align module names with 015's scaffolding.
- **The public-API boundary test does not cover viz.** `test_public_api_boundary.py`
  only scans `ari-skill-*`. Routing viz's internal imports through `ari.public.*`
  is a design improvement, not a test requirement — do it opportunistically and
  flag no-public-surface cases (`ari.pidfile`, `ari_skill_memory.backends`) as
  REVIEW_REQUIRED; do not manufacture new `ari.public.*` modules here.
- **`WIZARD_ROUTES` is MERGE, not KEEP.** Fold its 4 entries into the real
  registry and delete the stub in the same commit; do not leave a second,
  half-adopted table (`ruff` would flag the unused dict otherwise).
- **Preserve CORS quirks.** `_json` always adds `Access-Control-Allow-Origin: *`
  (`routes.py:1194`), but some inline handlers deliberately omit it (`:667-672`).
  A registry-dispatched handler must reproduce the same header presence/absence
  per endpoint — do not normalize it.
- **Leave the `core → viz` back-edge alone.** `cli/lineage.py:151` importing
  `ari.viz.api_orchestrator._api_launch_sub_experiment` is a known boundary
  violation; flag it REVIEW_REQUIRED, do not refactor it inside 062.
- **`sonfigs/` does not exist.** Profile YAML is read from top-level
  `ari-core/config/`; `ari/config/` is code and `ari/configs/` is packaged
  defaults. 062 touches none of the config-consolidation concerns (subtask 003).
- **Do not touch the frontend or the WS layer.** `services/api.ts` (863 LOC) is
  063's territory; `state_sync.py`/`websocket.py`/the `update` snapshot shape are
  read-only here.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **062** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
