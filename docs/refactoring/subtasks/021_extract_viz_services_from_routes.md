# Subtask 021: Extract Viz Services From Routes

> Phase 4: Viz / Dashboard Backend · Depends on 020 · Risk: Medium · Runtime code change: **Yes** (when implemented)
>
> This document is a **planning artifact only**. Writing it changes no runtime
> code. It describes the work a later implementation session will perform. The
> only file this task creates is this `.md`.

## 1. Goal

Extract the **business logic that is currently inlined inside the dashboard HTTP
route handlers** into dedicated, testable service modules, so that the handlers
in `ari-core/ari/viz/routes.py` (1197 LOC) and the `api_*.py` modules become
thin adapters that (a) parse the request, (b) call a service, and (c) serialize
the result — without changing a single endpoint path, JSON shape, status code,
CORS header, or SSE frame on the wire.

The two worst offenders in scope are:

1. The **~450-line inline `GET /state` handler** (`routes.py:219-666`) — a giant
   dict-builder that does filesystem scans, YAML profile merging,
   `cost_trace.jsonl` tail-parsing, and process-liveness probing directly inside
   the request handler. It becomes a `StateService.build_app_state(...) -> dict`.
2. The **subprocess + environment orchestration** duplicated across
   `api_experiment._api_run_stage` (`api_experiment.py:18`, env mapping
   `:44-128`, `Popen` `:129`), `api_experiment._api_launch` (`:144`, env block
   `:249-281`), and `api_orchestrator._api_launch_sub_experiment` (`Popen` at
   `api_orchestrator.py:287`). This ~150 LOC of `.env` parsing + `ARI_*` env-var
   mapping + `Popen` wiring becomes a `LaunchService`.

Secondary goal: route the handlers' **direct internal `ari.*` / `ari_skill_memory`
imports** through the `ari.public.*` surface where a public entry already exists,
and through a single thin `internal adapter` module where it does not (flagging
the gaps REVIEW_REQUIRED rather than inventing new public API here).

The refactor is **behavior-preserving**: `test_api_schema_contract.py`,
`test_server.py` (1844 LOC), `test_gui_errors.py` (1650 LOC),
`test_gui_env_propagation.py`, `test_launch_config.py`, and `test_status_fallback.py`
keep passing with **no edits to their assertions**.

## 2. Background

### HTTP stack (verified)

The viz backend is **Python stdlib `http.server` — there is no Flask/FastAPI/
aiohttp/ASGI/WSGI**. `_DualStackServer(ThreadingHTTPServer)` (in
`ari/viz/server.py`) binds an IPv6 socket with IPv4 fallback; all HTTP requests
are handled by a single `BaseHTTPRequestHandler` subclass `_Handler`
(`routes.py:77`, `protocol_version="HTTP/1.1"`). WebSocket runs on `port+1` via
the separate `websockets` package. `server.py` re-exports `_Handler` /
`_write_access_log` from `routes.py` (`server.py:78`) and `_ws_handler` from
`websocket.py` (`server.py:51`) for backward-compat.

### How routes are registered (verified)

There is **no route table**. Dispatch is a single giant `if/elif` chain matched
on `self.path` strings/regexes inside `_Handler.do_GET` (`routes.py:144-1026`)
and `do_POST` (`routes.py:1028-1188`), plus `do_OPTIONS` (CORS preflight,
`:127-142`). Hand-rolled `startswith`/`endswith`/`re.match` + `urllib.parse`
query parsing. Handlers are plain module functions imported at the top of
`routes.py:27-47` from the `api_*` modules; each returns a `dict` serialized by
`_Handler._json(data, status)` (`routes.py:1190-1197`, which always sets
`Access-Control-Allow-Origin: *`).

`api_state.py` (76 LOC) is already a **thin re-export facade** (Phase 3B
refactor) forwarding to `checkpoint_finder`, `state_sync`, `checkpoint_api`,
`ear`, `file_api`, `checkpoint_lifecycle`, `node_work_api`. `api_wizard.py:30`
defines an **unused `WIZARD_ROUTES` dict** — an abandoned, partial attempt at a
declarative route table (its handlers are also imported directly by
`routes.py`). These show the codebase already trending toward "thin file →
sibling logic module"; 021 continues that direction for the *fat* handlers that
the Phase-3B split left inline.

### Where the logic actually lives today (verified)

- `GET /state` builder (`routes.py:219-666`, ~450 LOC): dozens of
  `Path.exists()` / `read_text()` / glob scans, YAML profile merging
  (`config/` reads at `:376,388,401,612`), `cost_trace.jsonl` tail-parse
  (`:287-298`), and reaches into `_st._last_proc.poll()` plus
  `ari.pidfile.check_pid`/`read_pid` (`:561`, `:655`).
- Launch/stage orchestration: `.env` discovery + 15+ `ARI_*` mappings inside
  `api_experiment._api_run_stage` (`:44-128`) and `_api_launch` (`:249-281`);
  `Popen` at `api_experiment.py:129` and `api_orchestrator.py:287`.
- Direct **non-`ari.public`** imports inside handlers: `ari.paths.PathManager`
  (`routes.py:201`), `ari.pidfile` (`routes.py:561,655`), `ari.container`
  (`routes.py:887,890,1177`), and `ari_skill_memory.backends.get_backend`
  (`routes.py:203`). Also `ari.checkpoint`, `ari.config.auto_config`,
  `ari.llm.client.LLMClient`, `ari.clone`, `ari.orchestrator.web_provenance`
  are reached from `api_*` handlers.
- Mutable module-level globals in `state.py` (79 LOC): `_checkpoint_dir`,
  `_last_proc`, `_running_procs`, `_launch_config`, `_clients`,
  `_sub_experiments`, etc. — read/written directly by handlers. `state.py`
  already exposes a few encapsulation helpers (`set_active_checkpoint`,
  `get_sub_experiments`, `require_checkpoint_dir`); 021 extends that pattern
  rather than replacing the module.

### Why this is 021 (and what it is NOT)

Subtask **020** (`inventory_viz_dashboard_api_contracts`) is the inventory gate:
it enumerates the ~130 endpoints and freezes the JSON shapes 021 must preserve.
021 is the **service-extraction** step. Its siblings in Phase 4 own adjacent
concerns and 021 must not poach them:

- **015** `refactor_dashboard_viz_api_services` — the broader API-service-layer
  reshape (e.g. replacing the `if/elif` dispatch with a registry). 021 keeps the
  dispatch chain and only thins the handler *bodies*.
- **022** `define_dashboard_dto_and_schema_tests` — DTOs + schema validation +
  the unification of the `{"ok"}` vs `{"error"}` regimes. 021 does **not** add a
  validation layer.
- **023** `separate_viz_file_io_from_route_handlers` — the FileService for
  per-checkpoint file CRUD + path-traversal guards (`/codefile`,
  `/api/checkpoint/<id>/file/raw`, `paper.pdf|tex` serving). 021 leaves file I/O
  handlers to 023.
- **024** `refactor_bfts_tree_visualization_adapter` — the `tree.json` /
  `nodes_tree.json` → WS `update` adapter. 021 leaves the tree/WS snapshot shape
  to 024.
- **030** `add_viz_api_schema_checker_script` — the net-new `check_viz_api_schema.py`.
- **062** (Phase 5) `refactor_dashboard_backend_routes_to_services` — the larger
  follow-on. 021 is the Medium-risk down payment; 062 finishes the reshape.

## 3. Scope

In scope (implementation phase, not this planning doc):

- Add a **`StateService`** that owns the `GET /state` app-state builder currently
  inlined at `routes.py:219-666`. The handler shrinks to: resolve checkpoint,
  call `StateService.build_app_state(...)`, `self._json(...)`. The returned dict
  must be **key-for-key identical** to today's payload (the `AppState` contract
  pinned by `test_api_schema_contract.py`).
- Add a **`LaunchService`** (or `LaunchAdapter`) that owns `.env` discovery, the
  `ARI_*` env-var mapping, and `subprocess.Popen` construction shared by
  `_api_run_stage`, `_api_launch`, and `_api_launch_sub_experiment`. The three
  handlers delegate; the spawned command lines, env keys, and `_st` writes
  (`_last_proc`, `_running_procs`, `_launch_config`, `_sub_experiments`) stay
  identical.
- Route the in-handler **internal imports** (`ari.pidfile`, `ari.container`,
  `ari.paths`, `ari_skill_memory.backends`) through `ari.public.*` where a public
  entry exists (e.g. `ari.public.paths`, `ari.public.container`), and through a
  single new **`ari/viz/internal_adapters.py`** thin wrapper where no public
  surface exists yet — with a `REVIEW_REQUIRED` note pointing at the future
  public-API subtask.
- Add small **encapsulation accessors** to `state.py` if a service needs to read
  a global (following the existing `get_sub_experiments()` pattern), keeping the
  raw attributes still directly assignable so tests that `monkeypatch.setattr(_st,
  "_last_proc", ...)` keep working.
- Update `ari-core/ari/viz/README.md` module map and `docs/reference/rest_api.md`
  only if a symbol name a doc references moves (paths/shapes do not change, so
  likely no doc edit is needed).

Out of scope: everything in Section 4.

## 4. Non-Goals

- **Do NOT change any endpoint path, HTTP method, JSON key, status code, CORS
  header, or SSE frame format.** The dashboard REST + WS surface is the contract
  (ADAPT, not break).
- **Do NOT replace the `if/elif` dispatch chain with a route registry** — that is
  015 (and 062). Leave the abandoned `api_wizard.WIZARD_ROUTES` dict alone (flag
  it REVIEW_REQUIRED for 015; do not adopt or delete it here).
- **Do NOT extract file I/O / path-traversal handlers** (`/codefile`
  `routes.py:678-719`, `/api/checkpoint/<id>/file/raw` `:788-818`, `paper.pdf|tex`
  `:727-744`, `file_api.py` CRUD) — that is 023.
- **Do NOT build the BFTS/tree-visualization adapter** or touch the WS `update`
  snapshot shape / `state_sync.py` watcher — that is 024.
- **Do NOT add DTOs, a request-validation layer, or unify the `{"ok"}` vs
  `{"error"}` / `_status`-smuggling conventions** — that is 022.
- **Do NOT add authentication/authorization or change the `Access-Control-Allow-
  Origin: *` posture.** The open, no-auth posture is out of scope; note it as
  REVIEW_REQUIRED, do not "fix" it.
- **Do NOT create the `check_viz_api_schema.py` checker** — that is 030.
- **Do NOT touch the React/TypeScript frontend** (`ari/viz/frontend/`,
  `services/api.ts` 863 LOC). No frontend file changes; `npm test`/`npm run
  build` are N/A for 021.
- **Do NOT resolve the `core → viz` back-edge** (`cli/lineage.py:151` importing
  `ari.viz.api_orchestrator._api_launch_sub_experiment`) — flag REVIEW_REQUIRED
  for a dependency-boundary subtask.
- **Do NOT rename directories or move packages.** Adding a new `services/`
  subpackage (or top-level service modules) inside `ari/viz/` is additive and
  allowed; renaming an existing dir is not.
- No `sonfigs/` involvement — that directory does not exist in the repo.

## 5. Current Files / Directories to Inspect

Primary target package — `ari-core/ari/viz/` (verified LOC):

| Path | LOC | Role in 021 |
| --- | --- | --- |
| `ari-core/ari/viz/routes.py` | 1197 | `_Handler` dispatch. **Extract**: `/state` builder (`:219-666`), inline `ari.container` calls (`:887,890,1177`), inline `ari.pidfile` use (`:561,655`), inline `ari_skill_memory`/`ari.paths` use (`:201-205`). Keep dispatch order byte-identical. |
| `ari-core/ari/viz/api_experiment.py` | 929 | `_api_run_stage` (`:18`, env map `:44-128`, `Popen :129`), `_api_launch` (`:144`, env block `:249-281`). **Extract** into `LaunchService`. |
| `ari-core/ari/viz/api_orchestrator.py` | 321 | `_api_launch_sub_experiment` (`Popen :287`). **Extract** shared launch logic. |
| `ari-core/ari/viz/api_process.py` | 205 | `Popen`/`pkill`/`pgrep` process control. Read for context; overlaps `LaunchService` (only extract if shared). |
| `ari-core/ari/viz/state.py` | 79 | Mutable globals + existing accessors (`set_active_checkpoint`, `get_sub_experiments`, `require_checkpoint_dir`). Add read accessors as needed; keep attrs monkeypatchable. |
| `ari-core/ari/viz/api_state.py` | 76 | Thin re-export facade (Phase 3B). Pattern to mirror; must keep its `from .api_state import ...` symbol paths intact. |
| `ari-core/ari/viz/api_wizard.py` | 35 | Unused `WIZARD_ROUTES` (`:30`). Read-only in 021 (REVIEW_REQUIRED for 015). |
| `ari-core/ari/viz/server.py` | 201 | Re-exports `_Handler`/`_write_access_log` (`:78`), `_ws_handler` (`:51`). Must keep re-exporting. |
| `ari-core/ari/viz/ui_helpers.py` | 183 | `_build_experiment_detail_config`, `_collect_resource_metrics`, `_extract_goal_from_md` — existing helpers `/state` uses; reuse, do not duplicate. |
| `ari-core/ari/viz/README.md` | ~55 | Module map to update if a module is added. |

Contract / consumer / test files (read-only in 021):

- `docs/reference/rest_api.md` (+ `docs/ja/`, `docs/zh/` mirrors) — REST endpoint
  reference; the frozen contract 021 preserves.
- `ari-core/ari/viz/frontend/src/services/api.ts` (863 LOC) — the API client that
  consumes these endpoints. **Do not edit**; use to confirm no shape drifts.
- `ari-core/ari/public/` — `paths`, `container`, `cost_tracker`, `llm`, `run_env`
  (the stable surface handlers should prefer). Check which internal imports have a
  public equivalent before wrapping.
- Tests: `ari-core/tests/test_api_schema_contract.py` (pins `AppState`/`Settings`/
  `Checkpoint`/`CheckpointSummary` keys; monkeypatches `_st._checkpoint_dir`,
  `_last_proc`, `_running_procs`, `_settings_path`), `test_server.py` (1844),
  `test_gui_errors.py` (1650), `test_gui_env_propagation.py`, `test_launch_config.py`,
  `test_status_fallback.py`, `test_api_process.py`, `test_public_api_boundary.py`.

The **020 inventory output** (endpoint + shape freeze) is the authoritative input;
read it first.

## 6. Current Problems

1. **God handler.** The `GET /state` branch is ~450 LOC inlined in `do_GET`
   (`routes.py:219-666`). It mixes checkpoint resolution, glob scans, YAML profile
   merge, cost-trace tail-parsing, and process-liveness probing. It can only be
   exercised end-to-end through the HTTP stack; no unit-level test is possible.
2. **Duplicated launch orchestration.** `.env` discovery + `ARI_*` env mapping +
   `Popen` wiring is copy-pasted across `_api_run_stage` (`api_experiment.py:44-136`),
   `_api_launch` (`:249-281`), and `_api_launch_sub_experiment`
   (`api_orchestrator.py:287`). A change to env mapping must be made in three
   places, risking drift (already a source of `test_gui_env_propagation.py`
   coverage).
3. **Handlers bypass the public API.** Route handlers import internal modules
   directly — `ari.pidfile` (`routes.py:561,655`), `ari.container`
   (`:887,890,1177`), `ari.paths.PathManager` (`:201`),
   `ari_skill_memory.backends.get_backend` (`:203`). Some have a `ari.public.*`
   equivalent already; the direct imports couple the viz layer to core internals.
   (Note: `test_public_api_boundary.py` only enforces the boundary for
   `ari-skill-*` packages, **not** for `ari-core/ari/viz`, so nothing currently
   guards this — it is a design debt, not a test failure.)
4. **Business logic in "route helpers".** `_api_run_stage` inlines pure
   env-mapping business logic (`:44-128`) and even a `sinfo` subprocess probe for
   the Slurm partition (`:117-128`) inside what should be a request adapter.
5. **Unencapsulated global reads.** Handlers reach directly into `_st._last_proc`,
   `_st._checkpoint_dir`, `_st._running_procs` (e.g. `routes.py:223,364,533,553`).
   Extraction is only safe if the service reads/writes the *same* globals so the
   monkeypatch-driven tests still observe the effects.
6. **Abandoned partial refactor.** `api_wizard.WIZARD_ROUTES` (`api_wizard.py:30`)
   is dead code — a route-table stub never wired into dispatch. It signals the
   intended direction but adds confusion. (Left for 015/030 to resolve.)

## 7. Proposed Design / Policy

**Classification:** `ari/viz/routes.py` + the `api_*.py` handlers are **ADAPT** —
internal refactor behind unchanged endpoints and JSON shapes. `state.py` is
**ADAPT** (add accessors, keep attrs). `api_wizard.WIZARD_ROUTES` is
**REVIEW_REQUIRED** (defer to 015). The direct-internal-import sites are
**REVIEW_REQUIRED / ADAPT** (route through `ari.public.*` where possible). No file
is a DELETE_CANDIDATE in 021. Nothing here is "deprecated" (that term is reserved
for external contracts).

### 7.1 `StateService` (new)

New module, e.g. `ari-core/ari/viz/services/state_service.py`, exposing:

```
def build_app_state(checkpoint_dir: Path, *, last_proc, running_procs, ...) -> dict
```

Port the body of `routes.py:219-666` **verbatim in behavior**: same glob patterns,
same YAML profile merge (reading `config/` at the same relative paths), same
`cost_trace.jsonl` tail logic, same `has_paper`/`has_pdf` flags (`:243-244`), same
process-liveness fields. The handler becomes ~10 LOC. The service reads process
state via injected `_st` values (or `state.py` accessors) so the
`test_api_schema_contract.py` monkeypatches still take effect. Reuse
`ui_helpers._collect_resource_metrics` / `_build_experiment_detail_config` /
`_extract_goal_from_md` — do not duplicate them.

> Boundary with 024: `build_app_state` currently sets `has_paper`/`has_pdf` and
> experiment-status fields, **not** the `tree.json`/`nodes_tree.json` node tree
> (that is served by the WS `update` channel and `_load_nodes_tree`). Keep the
> tree-loading concern out of `StateService`; it belongs to 024.

### 7.2 `LaunchService` (new)

New module, e.g. `ari-core/ari/viz/services/launch_service.py`, exposing helpers
that the three launch handlers share:

```
def build_process_env(checkpoint_dir, launch_config, *, base_env=None) -> dict[str, str]
def spawn_experiment(cmd, env, *, cwd, checkpoint_dir) -> subprocess.Popen
```

`build_process_env` owns the `.env` discovery order (`checkpoint/.env` →
`/ARI/.env` → `/ARI/ari-core/.env` → `~/.env`, per `api_experiment.py:48-51`,
`:253-258`) and the full `ARI_*` mapping (`:87-128`, including `ARI_MODEL`/
`ARI_LLM_MODEL`/`ARI_BACKEND`, the VirSci keys, and the `sinfo` Slurm-partition
fallback `:117-128`). `spawn_experiment` owns the `Popen` construction and the
`_st._last_proc` / `_st._running_procs` writes. The three handlers keep their
signatures and their exact `{"ok": ...}` / `_status` return dicts. **Every env
key and its value derivation must be reproduced 1:1** — `test_gui_env_propagation.py`
and `test_launch_config.py` assert these.

### 7.3 Internal-import routing

For each direct internal import in a handler:

- If a `ari.public.*` equivalent exists (`ari.public.paths`,
  `ari.public.container`, `ari.public.cost_tracker`, `ari.public.run_env`),
  switch the handler/service to the public import.
- If no public surface exists (`ari.pidfile`, `ari_skill_memory.backends`), add a
  single thin `ari-core/ari/viz/internal_adapters.py` with named wrapper functions
  (`pid_is_alive(pid)`, `read_pid(dir)`, `memory_backend(...)`) so the coupling is
  in one auditable place, and add a `# REVIEW_REQUIRED: promote to ari.public.*`
  comment tied to the future public-API subtask. Do **not** create new
  `ari.public.*` modules in 021.

### 7.4 State encapsulation

Do not rip out `state.py` globals. Add read accessors only where a service needs
one (mirroring `get_sub_experiments()`), and keep the underlying attributes as
plain module globals so `monkeypatch.setattr(_st, "_last_proc", ...)` in tests
still mutates the value the service reads.

### 7.5 Compatibility policy

Handlers keep their names and import paths (`from .api_experiment import
_api_launch`, etc.); `server.py`/`routes.py` re-exports are untouched;
`api_state.py`/`api_wizard.py` facades stay. New service modules are **additive**.
The dispatch `if/elif` order in `do_GET`/`do_POST` is preserved verbatim.

## 8. Concrete Work Items

1. Read the **020** inventory and `docs/reference/rest_api.md`; snapshot the exact
   `AppState` key set the `/state` payload must return (cross-check against
   `test_api_schema_contract.py`).
2. Create `ari/viz/services/__init__.py` (new subpackage; additive) with a short
   docstring, or place the two service modules at `ari/viz/state_service.py` /
   `ari/viz/launch_service.py` — pick one and record it in the README.
3. Add `StateService.build_app_state(...)`; move the `routes.py:219-666` body into
   it verbatim (behavior-preserving), reusing `ui_helpers.*`. Reduce the `/state`
   branch to resolve-checkpoint + call + `_json`.
4. Add `LaunchService.build_process_env(...)` + `spawn_experiment(...)`; move the
   `.env`/`ARI_*`/`Popen` logic out of `_api_run_stage`, `_api_launch`, and
   `_api_launch_sub_experiment`. Keep each handler's return dict + `_status` field
   identical.
5. Add `ari/viz/internal_adapters.py` and switch handler-level internal imports to
   `ari.public.*` (where available) or the adapter (where not), with
   REVIEW_REQUIRED comments for the pidfile / memory-backend cases.
6. Add any needed `state.py` read accessors; verify no attribute is removed or
   renamed.
7. Update `ari/viz/README.md` module map to list the new service module(s). Only
   edit `docs/reference/rest_api.md` (+ ja/zh) if an endpoint/shape actually
   changed — it must not.
8. Run the full gate (Section 12); fix only real breakages, never by weakening an
   assertion or changing a wire shape.

## 9. Files Expected to Change

Modified (existing):

- `ari-core/ari/viz/routes.py` — `/state` branch reduced to a thin delegator;
  internal `ari.container`/`ari.pidfile`/`ari.paths`/`ari_skill_memory` calls
  routed via public API or `internal_adapters`. Dispatch order unchanged.
- `ari-core/ari/viz/api_experiment.py` — `_api_run_stage` / `_api_launch` delegate
  env+spawn to `LaunchService`; signatures and return dicts unchanged.
- `ari-core/ari/viz/api_orchestrator.py` — `_api_launch_sub_experiment` delegates
  its `Popen` + env build to `LaunchService`.
- `ari-core/ari/viz/state.py` — additive read accessors only (optional).
- `ari-core/ari/viz/README.md` — module map lists new service module(s).

New files (additive, inside `ari-core/ari/viz/`):

- `services/__init__.py` (if using a subpackage) — package docstring.
- `services/state_service.py` — `StateService` / `build_app_state`.
- `services/launch_service.py` — `LaunchService` / `build_process_env` +
  `spawn_experiment`.
- `internal_adapters.py` — thin wrappers for internal (`ari.pidfile`,
  `ari_skill_memory.backends`) access, with REVIEW_REQUIRED notes.

Must **NOT** change: any endpoint path/JSON shape, `server.py` re-exports,
`api_state.py` / `api_wizard.py` facades, `state_sync.py`, `websocket.py`,
`file_api.py` / `node_work_api.py` (023's territory), `checkpoint_*.py`, the
frontend, `config/` YAML, `docs/reference/rest_api.md` shapes.

## 10. Files / APIs That Must Not Be Broken

- **Dashboard REST contract:** every endpoint path + method + JSON shape in
  `routes.py`/`api_*.py` consumed by `frontend/src/services/api.ts` and pinned by
  `docs/reference/rest_api.md`. In particular the `GET /state` `AppState` payload
  keys, the `/api/launch` / `/api/run-stage` `{"ok": ...}` shape, and the
  `_status`-smuggling convention (`routes.py:1047,1051,...`).
- **WebSocket `update` message** shape (`websocket.py` + `state_sync.py`) — 021
  does not touch it; it must remain byte-identical (guarded further by 024).
- **SSE frames** for `/api/logs` (`routes.py:901-908`) and PaperBench job logs
  (`routes.py:934-1000`, heartbeat `: heartbeat\n\n`) — unchanged.
- **Backward-compat re-exports:** `server.py` re-exporting `_Handler`,
  `_write_access_log`, `_ws_handler`; `routes.py`'s top-level `from .api_* import`
  symbol names; `api_state.py` / `api_wizard.py` facade symbol names. Tests import
  handlers by these exact paths (`test_api_schema_contract.py` does
  `from ari.viz import checkpoint_api, api_settings`).
- **`state.py` attribute surface:** `_checkpoint_dir`, `_last_proc`,
  `_running_procs`, `_settings_path`, `_launch_config`, `_sub_experiments`,
  `_clients` — must remain module-level and monkeypatchable
  (`test_api_schema_contract.py` fixture `isolated_state`).
- **`ari.public.*`** surface — 021 consumes it, never modifies it.
- CLI `ari`, MCP tool contracts, checkpoint/config file formats — untouched by
  this subtask.

## 11. Compatibility Constraints

- **Behavior-preserving.** No endpoint added/removed/renamed; no JSON key
  added/removed/reordered on the wire; no status code changed. The `AppState`
  additive-subset policy in `test_api_schema_contract.py` means extra keys *could*
  be tolerated, but 021 should aim for an exact port — do not intentionally add or
  drop keys.
- **Env + spawn semantics unchanged.** `.env` discovery order, the full `ARI_*`
  mapping, the `sinfo` Slurm fallback, the child command line, `cwd`, and the
  `_st._last_proc`/`_running_procs` writes must be reproduced 1:1. `LaunchService`
  *wraps*, it does not rewrite.
- **Global state stays observable.** Services must read/write the same `state.py`
  globals the handlers do, so monkeypatch-based tests still see the effects.
- **No new runtime dependencies.** `radon` is not installed; `pnpm` is absent.
  Use only the standard library + already-vendored packages (`websockets`). `ruff`
  is available.
- **Term discipline:** internal viz code superseded here is ADAPT/refactored,
  never "deprecated" (that word is reserved for external contracts).
- **No `sonfigs/`.** That directory does not exist; profile YAML is read from
  `ari-core/config/` (e.g. `routes.py:376,388,401,612`). 021 does not touch config
  consolidation (subtask 003).
- **Security posture unchanged.** 021 does not add auth and does not alter
  `Access-Control-Allow-Origin: *`; it must not accidentally *remove* a CORS
  header either (note the existing intentional omissions at `routes.py:668-672`).

## 12. Tests to Run

Baseline gate (run before and after; must be green after):

- `python -m compileall .`
- `ruff check .`
- `pytest -q` (full suite)

Targeted viz suites that must remain green with **no assertion edits** (all under
`ari-core/tests/`):

- `test_api_schema_contract.py` — pins `AppState`/`Settings`/`Checkpoint`/
  `CheckpointSummary` keys; the primary `/state` + settings contract guard.
- `test_server.py` (1844 LOC) — HTTP handler behavior.
- `test_gui_errors.py` (1650 LOC) — handler error paths.
- `test_gui_env_propagation.py` — env mapping into spawned processes (the
  `LaunchService` guard).
- `test_launch_config.py` — launch-config → env/`_st` wiring.
- `test_status_fallback.py` — `/state` process-status fallback (the `_last_proc`
  liveness logic being extracted).
- `test_api_process.py` — process control endpoints.
- `test_public_api_boundary.py` — must stay green (021 must not introduce a new
  `ari-skill-*` → non-public import; note it does not cover `ari/viz` itself).
- Plus the broader viz set that imports `ari.viz`: `test_ear.py`,
  `test_publish_yaml_api.py`, `test_viz_*`, `test_api_paperbench*.py`,
  `test_settings_roundtrip.py`, `test_model_passthrough.py`,
  `test_variable_passthrough.py`.

Frontend (`npm test` / `npm run build`): **not applicable** — 021 changes no file
under `ari/viz/frontend/`.

CI guard to keep green: `.github/workflows/refactor-guards.yml` (runs
`pytest ari-core/tests/ -q` under a redirected `HOME`; forbids new `~/.ari/`
references outside `migrations/`) — the extraction must introduce neither.

## 13. Acceptance Criteria

1. The `GET /state` branch in `routes.py` is a thin delegator (target: well under
   ~30 LOC); the ~450-line builder lives in `StateService.build_app_state` and the
   returned dict is key-identical to the pre-refactor payload.
2. `.env`/`ARI_*`/`Popen` orchestration lives in `LaunchService` and is called by
   `_api_run_stage`, `_api_launch`, and `_api_launch_sub_experiment`; the three
   handlers keep identical signatures and return dicts.
3. Handler-level internal imports go through `ari.public.*` where available, else
   through `ari/viz/internal_adapters.py` with REVIEW_REQUIRED notes; no new
   `ari.public.*` module is created.
4. `python -m compileall .` and `ruff check .` are clean.
5. All Section 12 tests pass with **no edits to assertions** and no change to any
   wire shape.
6. `server.py`/`routes.py`/`api_state.py`/`api_wizard.py` re-export symbol names
   are unchanged; `state.py` attributes remain module-level and monkeypatchable.
7. `docs/reference/rest_api.md` (and ja/zh mirrors) require no shape edit; the
   README module map lists the new service module(s).
8. No new `~/.ari/` references; `refactor-guards.yml` stays green.

## 14. Rollback Plan

- The change is confined to `ari-core/ari/viz/` (route handlers + new additive
  service modules). Revert is a single `git revert` of the implementation
  commit/branch; there is no data migration and no checkpoint/config format change,
  so rollback cannot corrupt existing checkpoints or settings files.
- Because the refactor is behavior-preserving and gated by
  `test_api_schema_contract.py`, `test_gui_env_propagation.py`, and
  `test_server.py`, a shape or env regression surfaces in CI before merge.
- Keep the `StateService` extraction, the `LaunchService` extraction, and the
  internal-import routing as **separate commits** so any one can be reverted
  independently (e.g. if the env-mapping port shows a subtle drift, revert only the
  `LaunchService` commit and restore the inline handlers).

## 15. Dependencies

Per the master dependency graph (`020 -> 021, 022, 023, 024, 030`):

- **Depends on: 020** (`inventory_viz_dashboard_api_contracts`). 020 is the Phase-4
  inventory gate that enumerates the ~130 dashboard endpoints and freezes the JSON
  shapes 021 must preserve. 021 must not start until 020's contract inventory is
  complete — it is the authoritative "must-not-break" list.
- **Sibling refactors sharing the 020 gate** (`020 -> 022, 023, 024, 030`): 021 is
  disjoint from them file-wise but must coordinate boundaries:
  - **023** owns file I/O + traversal handlers (`file_api.py`, `/codefile`,
    `/file/raw`, `paper.*`). 021 leaves those inline.
  - **024** owns the `tree.json`/`nodes_tree.json` → WS `update` adapter. 021's
    `StateService` must **not** absorb node-tree loading.
  - **022** owns DTOs + schema tests. 021 preserves the ad-hoc dict shapes as-is;
    022 formalizes them later.
  - **030** adds `check_viz_api_schema.py`. Not a code dependency for 021.
  - **015** (`refactor_dashboard_viz_api_services`, gated on 020 per the index) is
    the broader service-layer/dispatch reshape and the natural consumer of the
    service modules 021 creates; align module names with it if 015 is in flight.
- **Inventory prerequisites for any runtime code change** (must all precede
  implementation): 001, 002, 020, 036, 045, 053, 059, 060, 067. 021 is a runtime
  code change, so it lands only after these baseline/inventory subtasks, consistent
  with the master rule.
- **Downstream:** the Phase-5 subtask **062**
  (`refactor_dashboard_backend_routes_to_services`) is the larger follow-on that
  continues this direction; 021 is a compatible down payment, not a blocker for it.

## 16. Risk Level

**Risk: Medium.** **Does this subtask change runtime code? Yes** — implementing 021
relocates the `/state` builder and the launch/env/subprocess orchestration into new
service modules and rewires handler imports. (Writing *this planning document*
changes no runtime code.)

Risk drivers: the `/state` handler feeds the dashboard home screen (high traffic,
shape pinned by `test_api_schema_contract.py`), and the launch/env path is on the
critical experiment-start path where a dropped or misspelled `ARI_*` key silently
breaks propagation. Mitigations: behavior-preserving mandate, the strong existing
guards (`test_api_schema_contract.py`, `test_gui_env_propagation.py`,
`test_launch_config.py`, `test_status_fallback.py`, `test_server.py` 1844 LOC),
additive-only new modules, per-concern commits, and an explicit "port env keys 1:1"
rule. Risk is Medium rather than High because the HTTP dispatch chain and every wire
shape stay untouched and no external contract moves.

## 17. Notes for Implementer

- **Read 020 first.** Treat its endpoint/shape inventory as the frozen contract.
  Diff the `/state` payload before and after (e.g. capture the dict for a fixture
  checkpoint) to prove key-for-key parity.
- **Port, do not clean up.** The `/state` builder's glob patterns, YAML merge
  order, and `cost_trace.jsonl` tail logic (`routes.py:287-298`) are behavior —
  move them verbatim. Same for the `ARI_*` mapping in `api_experiment.py:87-128`.
- **Keep globals observable.** `StateService`/`LaunchService` must read/write the
  same `state.py` attributes the handlers do. Do **not** snapshot `_st._last_proc`
  into a service-local variable at import time — read it at call time so
  `monkeypatch.setattr(_st, "_last_proc", ...)` still works.
- **The public-API boundary test does not cover viz.** `test_public_api_boundary.py`
  only scans `ari-skill-*`. Routing viz's internal imports through `ari.public.*`
  is a design improvement, not a test requirement — do it opportunistically and
  flag the no-public-surface cases (`ari.pidfile`, `ari_skill_memory.backends`) as
  REVIEW_REQUIRED; do not manufacture new `ari.public.*` modules here.
- **Do not touch `WIZARD_ROUTES`.** `api_wizard.py:30`'s unused route table is a
  015 concern. Leaving it means a lint pass may flag it as unused — confirm `ruff`
  was already tolerating it (it is exported, `noqa`-free today) and do not "tidy"
  it as part of 021.
- **Respect the 023 / 024 seams.** Do not extract file-serving handlers
  (`/codefile` `routes.py:678-719`, `/file/raw` `:788-818`, `paper.*` `:727-744`)
  or node-tree loading — those belong to 023 and 024 respectively. If
  `StateService` appears to need tree data, stop and coordinate with 024.
- **Preserve CORS quirks.** `_json` always adds `Access-Control-Allow-Origin: *`
  (`routes.py:1194`), but some inline handlers deliberately omit it (`:668-672`).
  A thinned handler must reproduce the same header presence/absence per endpoint —
  do not accidentally normalize it.
- **`sonfigs/` does not exist.** Profile YAML is read from top-level `config/`
  (rubric/profile data); `ari/config/` is code and `ari/configs/` is packaged
  defaults. 021 touches none of the config-consolidation concerns (subtask 003).
- **Leave the `core → viz` back-edge alone.** `cli/lineage.py:151` importing
  `ari.viz.api_orchestrator._api_launch_sub_experiment` is a known boundary
  violation; flag it REVIEW_REQUIRED, do not refactor it inside 021.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **021** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
