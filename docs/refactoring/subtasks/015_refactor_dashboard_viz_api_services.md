# Subtask 015: Refactor Dashboard Viz API Services

> Phase 4: Viz / Dashboard Backend
> Classification: **ADAPT** (behind unchanged wire contract)
> Inventory gate: **020** (`inventory_viz_dashboard_api_contracts`)
> Coordinates with: **021** (extract_viz_services_from_routes), **022**, **023** (separate_viz_file_io_from_route_handlers), **024**, **030**

This document is a PLANNING artifact. It changes no runtime code. It is
self-contained: a fresh coding session should be able to execute it after
reading Sections 5, 8, 9, and 10.

---

## 1. Goal

Introduce a coherent **service layer** for the ARI dashboard backend so that
the HTTP request handlers in `ari-core/ari/viz/` become thin, and the business
logic (state assembly, subprocess/launch orchestration, file I/O, internal
`ari.*` access) lives in testable, dependency-injectable service modules —
**without changing a single wire-visible endpoint path, HTTP method, JSON key,
status code, or WebSocket message shape** consumed by the React frontend
(`ari-core/ari/viz/frontend/src/services/api.ts`, 863 lines).

Concretely, subtask 015 owns the **umbrella policy and scaffolding** that the
finer-grained sibling subtasks (021 routes extraction, 023 file-I/O
separation, 022/024/030) build on:

1. A declarative **route registry** to replace the two giant `if/elif` chains
   in `routes.py` (`do_GET` ~86 branches at lines 144–1026; `do_POST` ~51
   branches at 1028–1188), formalizing the abandoned `WIZARD_ROUTES` intent
   (`api_wizard.py:30`).
2. A uniform **response wrapper / DTO convention** that unifies the two
   coexisting reply styles (`{"ok": bool, ...}` vs `{"error": str}`) and
   removes the `r.pop("_status", 200)` status-smuggling (`routes.py:1047-1057`,
   `1088-1089`).
3. A thin **adapter boundary** so handlers depend on `ari.public.*` instead of
   reaching directly into `ari.paths`, `ari.checkpoint`, `ari.config`,
   `ari.llm.client`, `ari.clone`, `ari.orchestrator`, `ari.container`,
   `ari.pidfile`, and `ari_skill_memory.backends` (all currently imported
   inside handlers).
4. Encapsulate the module-level mutable globals in `state.py` behind accessor
   functions so services own state rather than each handler mutating it.

## 2. Background

The viz backend is a bespoke, framework-free HTTP + WebSocket server:

- **No Flask/FastAPI/aiohttp/ASGI/WSGI.** It is Python stdlib `http.server`.
  `server.py:82` defines `_DualStackServer(ThreadingHTTPServer)` (IPv6 socket
  with `IPV6_V6ONLY=0` for IPv4 fallback). Request handling is a single
  `BaseHTTPRequestHandler` subclass `_Handler` (`routes.py:77`,
  `protocol_version="HTTP/1.1"`). WebSocket runs on `port+1` via the separate
  `websockets` package (`server.py:21`, `ws_serve` at `server.py:178`). Entry
  `main()`/`_main()` (`server.py:159,183`) launches three threads: filesystem
  watcher, HTTP server, asyncio WS loop.
- **Route dispatch is a manual `if/elif` chain** over `self.path` using
  `startswith`/`endswith`/`re.match` and hand-rolled `urllib.parse` query
  parsing. There is no route table. `api_wizard.py:30` defines an unused
  `WIZARD_ROUTES` dict — evidence of a prior, abandoned attempt at a
  declarative table (only 4 POST routes: `/api/chat-goal`,
  `/api/generate-config`, `/api/launch`, `/api/run-stage`).
- **A previous refactor (Phase 3B) already split the API surface** into
  per-cluster `api_*.py` modules, with `api_state.py` (76 lines) reduced to a
  **thin re-export facade** forwarding to `checkpoint_finder`, `state_sync`,
  `checkpoint_api`, `ear`, `file_api`, `checkpoint_lifecycle`,
  `node_work_api`. `server.py` re-exports `_Handler`/`_ws_handler` for
  backward compatibility (`server.py:78,51`). This subtask continues that
  trajectory: the modules exist, but handler bodies still contain heavy logic.
- **Contract surface**: endpoint paths + JSON shapes are the dashboard API
  contract, consumed by the React frontend and documented in
  `docs/reference/rest_api.md` (10.8 KB). Two contract tests already pin
  behavior: `ari-core/tests/test_api_schema_contract.py` (subset/additive
  key assertions against `AppState`, `Settings`, `Checkpoint`,
  `CheckpointSummary`) and `ari-core/tests/test_public_api_boundary.py`
  (skills import only `ari.public.*`).

Note: the "sonfigs" directory referenced in some planning prompts **does not
exist**. Profile YAML consumed by the `/state` handler is read from the
top-level `ari-core/config/` rubric/profile data tree (e.g. `routes.py:376,
388, 401, 612`); this is distinct from `ari-core/ari/config/` (locator code)
and `ari-core/ari/configs/` (packaged defaults).

## 3. Scope

In scope (runtime code, executed AFTER the 020 inventory gate):

- The viz backend package **`ari-core/ari/viz/*.py`** (27 Python files, 8131
  LOC total), specifically the request-handling and service seams:
  - `routes.py` (1197) — dispatch + `_json` + access log.
  - `state.py` (79) — module-level mutable globals.
  - The `api_*.py` service modules that contain in-handler logic:
    `api_settings.py` (553), `api_workflow.py` (462), `api_orchestrator.py`
    (321), `api_process.py` (205), `api_memory.py` (227), `api_ollama.py`
    (90), `api_tools.py` (259), `api_publish.py` (191), `api_fewshot.py`
    (221).
- Introducing new **service / adapter / DTO helper modules** under
  `ari-core/ari/viz/` (e.g. a `services/` subpackage or `*_service.py`
  siblings — exact layout chosen in Section 7).
- The **route registry** abstraction and its wiring into `_Handler`.

Explicitly delegated to sibling subtasks (see Sections 4 and 15) but scoped
here at the *policy* level so those subtasks inherit a consistent pattern:

- The ~450-line inline `GET /state` builder (`routes.py:219-666`) →
  extraction executed by **021**.
- The launch/subprocess orchestration (`api_experiment.py:929`,
  `api_orchestrator.py`, `api_process.py`) → deeper split coordinated with
  **021/024**.
- File-serving + path-traversal consolidation (`file_api.py`,
  `node_work_api.py`, inline `/codefile`, `/api/checkpoint/.../file/raw`,
  `paper.*`) → executed by **023**.
- `api_paperbench.py` (813) `_JOBS` store redesign → **022** (PaperBench is a
  large sub-domain with its own inventory concerns).

## 4. Non-Goals

- **NOT** changing any endpoint path, HTTP method, request body shape,
  response JSON key set, status code, header (`Access-Control-Allow-Origin: *`
  included), or WebSocket message type (`{"type":"update","data":...,
  "timestamp":...}`).
- **NOT** switching HTTP frameworks (no Flask/FastAPI/ASGI migration). The
  stdlib `http.server` foundation stays; only dispatch/logic organization
  changes.
- **NOT** adding authentication/authorization/CSRF. The current posture is
  "no auth anywhere"; changing it is a security decision out of scope here and
  would alter observable behavior. Flag it in Section 17 for a follow-up
  subtask, do not implement.
- **NOT** the actual `/state` extraction (021), file-I/O split (023),
  PaperBench `_JOBS` persistence (022), or frontend refactors (062/063,
  gated by 059/060/067).
- **NOT** touching `frontend/` TypeScript, `docs/`, workflows, or configs.
- **NOT** removing the `api_state.py` re-export facade or the `server.py`
  backward-compat re-exports (`_Handler`, `_ws_handler`, `_write_access_log`)
  — downstream imports depend on them.

## 5. Current Files / Directories to Inspect

All paths absolute-from-repo-root (`/home/t-kotama/workplace/ARI`).

Backend package `ari-core/ari/viz/` (verified line counts, 2026-07-01):

| File | LOC | Role |
| --- | --- | --- |
| `ari-core/ari/viz/routes.py` | 1197 | `_Handler` dispatch (`do_GET` 144, `do_POST` 1028, `do_OPTIONS` 127), `_json` (1190), `_write_access_log` (69). ~97 dispatch-branch tokens in the GET range. |
| `ari-core/ari/viz/api_experiment.py` | 929 | launch / run-stage / SSE logs; Popen spawning + `.env`+`ARI_*` env mapping. |
| `ari-core/ari/viz/api_paperbench.py` | 813 | PaperBench registry + run wizard; `_JOBS` dict (496) + `_JOBS_LOCK` (497). |
| `ari-core/ari/viz/api_settings.py` | 553 | env keys, settings, workflow, skills, profiles, rubrics. |
| `ari-core/ari/viz/api_workflow.py` | 462 | React Flow workflow-editor endpoints. |
| `ari-core/ari/viz/ear.py` | 452 | EAR curate/publish/clone helpers. |
| `ari-core/ari/viz/checkpoint_api.py` | 327 | model list, checkpoint list/summary, lineage decisions. |
| `ari-core/ari/viz/api_orchestrator.py` | 321 | sub-experiment registry/launch (Popen 287). |
| `ari-core/ari/viz/api_paperbench_worker.py` | 319 | background PaperBench worker. |
| `ari-core/ari/viz/file_api.py` | 307 | per-checkpoint file CRUD + LaTeX compile. |
| `ari-core/ari/viz/api_tools.py` | 259 | chat-goal, config gen, upload, SSH test. |
| `ari-core/ari/viz/node_work_api.py` | 233 | per-node filetree/filecontent/memory. |
| `ari-core/ari/viz/api_memory.py` | 227 | memory backend health + local Letta start/stop (subprocess.run 102/121). |
| `ari-core/ari/viz/api_fewshot.py` | 221 | reviewer_rubrics fewshot corpus mgmt. |
| `ari-core/ari/viz/checkpoint_lifecycle.py` | 205 | checkpoint delete + switch. |
| `ari-core/ari/viz/api_process.py` | 205 | stop-all + GPU-monitor (Popen 76, pkill/pgrep 178/191). |
| `ari-core/ari/viz/server.py` | 201 | HTTP/WS server; `_DualStackServer` (82), `main`/`_main`. Re-exports `_Handler` (78), `_ws_handler` (51). |
| `ari-core/ari/viz/api_publish.py` | 191 | publish settings + preview/run. |
| `ari-core/ari/viz/ui_helpers.py` | 183 | dashboard rendering helpers. |
| `ari-core/ari/viz/state_sync.py` | 117 | node-tree load + broadcast + fs watcher. |
| `ari-core/ari/viz/api_ollama.py` | 90 | GPU/model detection + Ollama reverse proxy. |
| `ari-core/ari/viz/state.py` | 79 | shared mutable globals (`_clients`, `_checkpoint_dir`, `_last_proc`, `_running_procs`, `_launch_config`, `_sub_experiments`, `_gpu_monitor_proc`, `_staging_dir`, ...). |
| `ari-core/ari/viz/api_state.py` | 76 | Phase-3B **re-export facade**. |
| `ari-core/ari/viz/checkpoint_finder.py` | 65 | checkpoint discovery + PID liveness. |
| `ari-core/ari/viz/websocket.py` | 36 | WS handler (single `update` message). |
| `ari-core/ari/viz/api_wizard.py` | 35 | consolidated wizard router; unused `WIZARD_ROUTES` (30). |
| `ari-core/ari/viz/__init__.py` | 28 | package docstring / symbol map. |
| `ari-core/ari/viz/README.md` | — | per-directory module map (must be kept accurate). |

Contract / test references to inspect:

- `ari-core/ari/viz/frontend/src/services/api.ts` (863) — the API client; the
  authoritative list of paths/methods/shapes the backend must keep.
- `ari-core/ari/viz/frontend/src/types/index.ts` — TS `AppState`, `Settings`,
  `Checkpoint`, `CheckpointSummary` that `test_api_schema_contract.py` pins.
- `docs/reference/rest_api.md` — human-readable REST reference.
- Tests (Section 12): `ari-core/tests/test_api_schema_contract.py`,
  `test_public_api_boundary.py`, `test_server.py` (1844),
  `test_gui_errors.py` (1650), `test_dashboard_html.py`,
  `test_workflow_contract.py` (1606), `test_workflow_editor.py`,
  `test_wizard.py` (1133), `test_api_paperbench.py`,
  `test_api_paperbench_worker.py`, `test_api_process.py`, `test_ear.py`,
  `test_viz_fewshot_api.py`, `test_viz_memory_api.py`,
  `test_viz_node_report_api.py`, `test_gui_env_propagation.py`,
  `test_publish_yaml_api.py`, `test_api_lineage_decisions.py`.

Upstream planning references: `docs/refactoring/020_*` (inventory, once
authored), `docs/refactoring/008_viz_dashboard_refactoring_plan.md`,
`docs/refactoring/006_target_architecture_plan.md`,
`docs/refactoring/010_contract_preservation_policy.md`.

## 6. Current Problems

Grounded in the routed viz-area findings and re-verified line references:

1. **Monolithic dispatch, no route table.** `do_GET` (`routes.py:144-1026`)
   and `do_POST` (`1028-1188`) are hand-matched `if/elif` chains (~97
   branch-tokens in the GET range alone). Adding/auditing an endpoint means
   editing a 900-line method. The abandoned `WIZARD_ROUTES` (`api_wizard.py:30`)
   proves the intended direction was never finished.
2. **Fat handler: the `/state` builder.** `routes.py:219-666` (~450 lines)
   performs dozens of `Path.exists()`/`read_text()`/`json.loads()` calls, glob
   scans, YAML profile merging (`371-465`, `592-645`), `cost_trace.jsonl`
   tail-parsing (`287-298`), and reaches into `_st._last_proc.poll()` and
   `ari.pidfile.check_pid/read_pid` (`561-563`). Pure business logic living in
   an HTTP method. (Extraction is 021's job; 015 defines the target seam.)
3. **Inconsistent response conventions.** Two coexist: `{"ok": bool, ...}`
   (launch/stage) and `{"error": str}` (file APIs). Status codes are smuggled
   via `r.pop("_status", 200)` (`routes.py:1047-1057`, `1088-1089`). No DTO,
   no validation, no single response wrapper. POST bodies are raw
   `bytes → json.loads(body)` inside each handler.
4. **CORS header inconsistency.** `_json` (`routes.py:1190`) sets
   `Access-Control-Allow-Origin: *`, and there are ~8 wildcard sites, but some
   inline handlers omit it (noted at `routes.py:667-672`), causing
   wire-behavior drift between endpoints.
5. **Handlers bypass the stable public surface.** Direct internal imports in
   handlers: `ari.paths.PathManager`, `ari.checkpoint`, `ari.config.auto_config`,
   `ari.llm.client.LLMClient`, `ari.clone`, `ari.orchestrator.web_provenance`,
   `ari.container`, `ari.pidfile`, and `ari_skill_memory.backends.get_backend`
   (`routes.py:203-205`). These bypass `ari.public.*`, entangling the viz layer
   with core internals.
6. **Mutable global state, no encapsulation.** `state.py` module-level globals
   (`_checkpoint_dir`, `_last_proc`, `_running_procs`, `_launch_config`,
   `_clients`, `_sub_experiments`, `_gpu_monitor_proc`, `_staging_dir`) are read
   and written directly by handlers across modules. `api_paperbench.py` keeps a
   process-local `_JOBS` dict + `_JOBS_LOCK` job store (lost on restart).
7. **Orchestration logic inlined in route helpers.** `api_experiment._api_run_stage`
   inlines `.env` parsing + 15+ `ARI_*` env-var mapping and `Popen`;
   `api_orchestrator._api_launch_sub_experiment` (Popen 287); `api_process`
   (`Popen`/`pkill`/`pgrep`); `api_memory` (subprocess.run). Business logic in
   what should be thin adapters.
8. **Inline SSE + binary file serving with hand-rolled traversal checks.** SSE
   loops written directly in the route (PaperBench logs `934-1000`, `/api/logs`
   `901-908`); binary serving with inconsistent path-traversal guards
   (`/codefile` uses substring `"checkpoints" in str(p)` at `692`, while
   `file_api` uses `relative_to`). (Consolidation is 023's job; 015 defines the
   FileService seam.)

## 7. Proposed Design / Policy

**Policy: thin routes → services → adapters → DTOs, behind a route registry,
with zero wire change.** The stdlib server stays.

### 7.1 Route registry (replaces the if/elif chains)

Introduce a declarative registry that maps `(method, path-pattern) → handler
callable`, generalizing `WIZARD_ROUTES`. Design points:

- Support both exact-match and pattern routes (the current code uses
  `startswith`/`endswith`/`re.match`; the registry must express regex/param
  routes such as `/api/checkpoint/<id>/summary` and `/api/ear/<rid>/curate`).
- `_Handler.do_GET`/`do_POST`/`do_OPTIONS` shrink to: parse path+query, look up
  the registry entry, invoke it, serialize via the response wrapper. The
  ordering semantics of the current chain (first-match-wins, prefix before
  generic) MUST be preserved — capture the existing branch order in the 020
  inventory and encode it as registry priority to avoid dispatch regressions.
- Keep `_Handler`, `_ws_handler`, `_write_access_log` importable from their
  current modules (`server.py` re-exports) — the registry is additive.

### 7.2 Response wrapper + DTO convention

- A single `respond(data, status=200)` / response-builder that emits headers
  (including the wildcard CORS header on **every** JSON response, fixing
  problem #4) and serializes with `ensure_ascii=False` exactly as `_json` does
  today. Preserve both payload styles at the wire level: existing endpoints
  keep returning `{"ok": ...}` or `{"error": ...}` as they do now. The wrapper
  removes the `_status` smuggling by giving handlers an explicit status return
  channel, but the emitted bytes for each endpoint stay byte-compatible with
  today's output (verified by `test_api_schema_contract.py`).
- Optional lightweight request-DTO helpers (`parse_json_body(handler) -> dict`)
  to centralize `json.loads(body)` + error handling. No mandatory schema
  validation in this subtask (that would risk rejecting currently-accepted
  payloads); validation is additive and off by default.

### 7.3 Adapter boundary (`ari.public.*` only)

- Add a thin `viz/adapters.py` (or per-concern adapter functions) wrapping the
  internal imports listed in problem #5 so handlers/services import from the
  adapter, and the adapter is the single place that touches `ari.paths`,
  `ari.checkpoint`, `ari.config`, `ari.llm.client`, `ari.clone`,
  `ari.orchestrator`, `ari.container`, `ari.pidfile`, and
  `ari_skill_memory.backends`. Prefer routing through existing `ari.public.*`
  (`paths`, `container`, `cost_tracker`, `llm`, `run_env`, `config_schema`)
  where a public equivalent already exists; where none exists, the adapter
  documents the gap (do not invent new `ari.public` exports here — that is a
  core-API subtask). This keeps `test_public_api_boundary.py` green and reduces
  viz→core coupling incrementally.

### 7.4 State encapsulation

- Replace direct cross-module reads/writes of `state.py` globals with accessor
  functions (the module already has `get_sub_experiments`/`set_sub_experiment`/
  `set_active_checkpoint`/`active_settings_path`/`require_checkpoint_dir` —
  extend this pattern to `_last_proc`, `_running_procs`, `_launch_config`,
  `_gpu_monitor_proc`, `_staging_dir`, `_clients`). Globals remain (single
  process, threaded server), but access is funneled so services own the
  transitions. Keep the attribute names present on the module so
  `monkeypatch.setattr(_st, "_checkpoint_dir", ...)` in existing tests still
  works (see `test_api_schema_contract.py` fixture).

### 7.5 Module layout

Prefer a `ari-core/ari/viz/services/` subpackage (new) for extracted service
classes/functions, keeping the existing `api_*.py` modules as the thin route
adapters that import from `services/`. Do NOT rename or delete existing
modules; `api_state.py`'s facade role and the `server.py` re-exports are load-
bearing. Update `ari-core/ari/viz/README.md` to list any new files (a
readme-parity gate exists).

Classification summary: **ADAPT** the dashboard backend behind the frozen wire
contract. No **DELETE_CANDIDATE** in this subtask; the unused `WIZARD_ROUTES`
is **MERGE** into the new registry (fold its 4 routes in, then remove the dead
dict). No **MOVE_TO_LEGACY**.

## 8. Concrete Work Items

Execute only after 020 inventory exists (Section 15). Suggested order:

1. **Ingest the 020 inventory** of endpoint (method, path, params, response
   keys, status codes, headers) and the exact `do_GET`/`do_POST` branch order.
   Treat it as the frozen contract table.
2. **Add the route registry** module + wire `_Handler.do_GET`/`do_POST`/
   `do_OPTIONS` to dispatch through it, preserving first-match ordering. Do it
   as a pure mechanical translation first (same handler callables, same order)
   — no logic moves yet. Run the full test suite; it must pass unchanged.
3. **Fold `WIZARD_ROUTES` into the registry** and delete the now-dead dict from
   `api_wizard.py` (keep the module's route callables).
4. **Introduce the response wrapper** and migrate handlers to it incrementally,
   verifying byte-for-byte output parity per endpoint against
   `test_api_schema_contract.py` and `test_dashboard_html.py`. Ensure every
   JSON response carries the CORS header (fixes the inline-omission drift).
5. **Add the adapter module** and reroute the internal `ari.*` /
   `ari_skill_memory` imports in handlers through it. Confirm
   `test_public_api_boundary.py` stays green.
6. **Encapsulate `state.py` globals** behind accessors; update the `api_*.py`
   handlers that mutate them. Keep global attribute names for test monkeypatch
   compatibility.
7. **Extract per-domain services** for the mid-size modules in scope
   (`api_settings`, `api_workflow`, `api_orchestrator`, `api_process`,
   `api_memory`, `api_ollama`, `api_tools`, `api_publish`, `api_fewshot`):
   move file/subprocess/business logic into `services/`, leaving the `api_*`
   function as a thin call-through. Do NOT touch the `/state` builder (021),
   file-serving/traversal (023), PaperBench `_JOBS` (022), or
   `api_experiment` launch internals beyond the adapter reroute (coordinate
   with 021/024).
8. **Update `ari-core/ari/viz/README.md`** to add any new `services/`/adapter
   files (readme-parity gate).
9. **Run the full gate set** (Section 12) after each of steps 2, 4, 5, 6, 7.

## 9. Files Expected to Change

Runtime code (only when this subtask is executed, post-020):

- `ari-core/ari/viz/routes.py` — `_Handler` dispatch replaced by registry
  lookup; `_json` folded into the response wrapper (kept importable).
- `ari-core/ari/viz/api_wizard.py` — `WIZARD_ROUTES` merged into registry then
  removed.
- `ari-core/ari/viz/state.py` — add accessor functions; globals retained.
- `ari-core/ari/viz/api_settings.py`, `api_workflow.py`, `api_orchestrator.py`,
  `api_process.py`, `api_memory.py`, `api_ollama.py`, `api_tools.py`,
  `api_publish.py`, `api_fewshot.py` — handlers thinned to call into services.
- `ari-core/ari/viz/server.py` — only if registry wiring requires it; keep
  `_Handler`/`_ws_handler`/`_write_access_log` re-exports intact.
- **New** `ari-core/ari/viz/services/` (subpackage) — extracted service logic.
- **New** `ari-core/ari/viz/adapters.py` (or equivalent) — `ari.public.*`
  boundary wrapper.
- `ari-core/ari/viz/README.md` — module map updated for new files.
- Possibly **new** `ari-core/tests/test_viz_route_registry.py` — unit tests for
  the registry (additive; does not replace contract tests).

Files that MUST NOT change in this subtask (delegated): `routes.py:219-666`
`/state` builder (021), `file_api.py`/`node_work_api.py`/inline file serving
(023), `api_paperbench.py` `_JOBS` (022), `api_experiment.py` launch internals
beyond the adapter reroute (021/024), all `frontend/` TS, `docs/`, workflows.

This planning document: `docs/refactoring/subtasks/015_refactor_dashboard_viz_api_services.md`
(the only file created by the planning phase).

## 10. Files / APIs That Must Not Be Broken

- **Dashboard REST + WS contract** — every path/method/JSON-key/status-code/
  header consumed by `ari-core/ari/viz/frontend/src/services/api.ts` (863) and
  described in `docs/reference/rest_api.md`. The WS message
  `{"type":"update","data":<tree>,"timestamp":...}` and single-endpoint
  `ws://host:(port+1)/ws` behavior stay identical.
- **`ari.public.*`** stable Python API (claim_gate, config_schema, container,
  cost_tracker, llm, paths, run_env, verified_context) — unchanged; viz may
  only consume it, not modify it.
- **CLI `ari`** (`ari.cli:app`) and `ari viz` entry (`server.main`) — unchanged.
- **MCP tool contracts** of all 14 `ari-skill-*` servers — untouched.
- **Backward-compat re-exports**: `server.py` re-exports `_Handler`,
  `_ws_handler`, `_write_access_log`; `api_state.py` re-export facade. Keep all
  importable at their current paths.
- **`state.py` global attribute names** — tests monkeypatch `_st._checkpoint_dir`,
  `_st._last_proc`, `_st._running_procs`, `_st._settings_path`; do not rename.
- **Checkpoint / output / config file formats** (`ari/checkpoint.py`, YAML under
  `config/` + `configs/`) — read-only from viz; unchanged.
- **Scripts called by `.github/workflows`** — unaffected.

## 11. Compatibility Constraints

- **Byte-compatible responses.** The contract is *additive-subset* per
  `test_api_schema_contract.py` (extra keys allowed; the checkpoint-summary
  not-found path `{"error": "not found"}` is exact-equality). Any refactor must
  keep always-present keys and the fixed error sentinels intact. Do not drop or
  rename keys, do not change status codes.
- **Dispatch order fidelity.** Because dispatch is currently order-sensitive
  string matching, the registry MUST reproduce first-match-wins ordering; an
  ordering regression could route `/api/checkpoint/<id>/file/raw` to a generic
  handler. Encode order explicitly from the 020 inventory.
- **No new external contract.** No new endpoints, no removed endpoints. If a
  compatibility adapter is ever needed (it should not be), document it inline;
  do not silently break a path.
- **Do not use the term "deprecated"** for any internal viz code moved into
  services — this is internal reorganization, not an external-contract
  deprecation.
- **Public-boundary rule** (`test_public_api_boundary.py`) applies to skills,
  but the adapter work reduces viz→core internal coupling in the same spirit;
  do not introduce *new* internal imports outside the adapter module.

## 12. Tests to Run

From repo root `/home/t-kotama/workplace/ARI` (editable installs already set up
by `setup.sh`: `ari-skill-memory` then `ari-core`):

```bash
python -m compileall ari-core/ari/viz          # syntax gate (fast, viz only)
python -m compileall .                          # full syntax gate
ruff check .                                     # lint (ruff IS available; radon is NOT)
pytest -q                                        # full suite
```

Targeted viz suites (run these first for a tight loop):

```bash
pytest -q ari-core/tests/test_api_schema_contract.py \
          ari-core/tests/test_public_api_boundary.py \
          ari-core/tests/test_server.py \
          ari-core/tests/test_dashboard_html.py \
          ari-core/tests/test_gui_errors.py \
          ari-core/tests/test_gui_env_propagation.py \
          ari-core/tests/test_workflow_contract.py \
          ari-core/tests/test_workflow_editor.py \
          ari-core/tests/test_wizard.py \
          ari-core/tests/test_api_paperbench.py \
          ari-core/tests/test_api_paperbench_worker.py \
          ari-core/tests/test_api_process.py \
          ari-core/tests/test_ear.py \
          ari-core/tests/test_viz_fewshot_api.py \
          ari-core/tests/test_viz_memory_api.py \
          ari-core/tests/test_viz_node_report_api.py \
          ari-core/tests/test_publish_yaml_api.py \
          ari-core/tests/test_api_lineage_decisions.py
```

No frontend build is required for this subtask (backend-only; `frontend/`
untouched), so `npm test`/`npm run build` are **not** part of the 015 gate.
Still run `scripts/run_all_tests.sh` if present for parity with CI. CI guard
`.github/workflows/refactor-guards.yml` must stay green (no new `~/.ari/`
references; no `$HOME/.ari/` writes during pytest).

## 13. Acceptance Criteria

1. `python -m compileall .` and `ruff check .` pass with no new violations.
2. `pytest -q` passes with the same or greater number of passing tests; no
   contract test (`test_api_schema_contract.py`, `test_public_api_boundary.py`)
   regresses.
3. `_Handler.do_GET`/`do_POST` no longer contain a hand-written `if/elif`
   dispatch chain; routing goes through the registry, and `WIZARD_ROUTES` is
   folded in and removed.
4. Every JSON response emits `Access-Control-Allow-Origin: *` (CORS drift at
   `routes.py:667-672` resolved); response bytes remain contract-compatible.
5. Handlers no longer import `ari.paths`/`ari.checkpoint`/`ari.config`/
   `ari.llm.client`/`ari.clone`/`ari.orchestrator`/`ari.container`/`ari.pidfile`/
   `ari_skill_memory.backends` directly; those imports are confined to the new
   adapter module.
6. Cross-module direct mutation of `state.py` globals (except within `state.py`
   accessors) is eliminated for the modules in scope; `state.py` global
   attribute names are preserved.
7. `ari-core/ari/viz/README.md` accurately lists any new modules (readme-parity
   / doc-source gates pass).
8. The delegated hotspots (`/state` 021, file-I/O 023, PaperBench `_JOBS` 022)
   are untouched and clearly handed off.
9. `ari viz` still launches and serves the frontend (smoke: `python -m
   ari.viz.server` starts three threads without error).

## 14. Rollback Plan

- The work is a pure internal reorganization behind a frozen wire contract, so
  rollback is a `git revert` of the subtask's commits. Because responses are
  byte-compatible, a partial rollback (e.g. revert only the state-encapsulation
  step) is safe as long as the registry and re-exports remain consistent.
- Land the change incrementally per Section 8 steps; each step is independently
  revertible and independently gated by `pytest -q`. If step 2 (registry) shows
  any routing regression, revert to the `if/elif` chain and re-derive ordering
  from 020 before retrying.
- Keep the old `_json` behavior reachable until the response wrapper is proven
  byte-identical; do not delete it until step 4 passes all contract tests.
- No data/format migration is involved (viz reads checkpoints/config read-only),
  so there is no state to migrate back.

## 15. Dependencies

Consistent with the provided DEPENDENCY GRAPH (015 has **no explicit edge** in
the graph; its inventory gate is 020 per `007_subtask_index.md:62,128-130`).

- **Hard predecessor (gate): 020** `inventory_viz_dashboard_api_contracts`.
  The graph edge `020 -> 021, 022, 023, 024, 030` establishes 020 as the viz
  inventory that must precede any viz runtime change; 015 shares that gate.
  020 supplies the frozen endpoint/branch-order table this subtask consumes.
- **Cross-cutting inventory gate.** The master rule "inventory subtasks MUST
  precede any runtime code change" lists **001, 002, 020, 036, 045, 053, 059,
  060, 067**. Of these, **001** (current architecture) and **020** (viz
  contracts) are the ones this subtask directly relies on; **003**
  (dependency/boundary report) informs the `ari.public.*` adapter work.
- **Coordinates with (siblings, all gated by 020): 021**
  (extract_viz_services_from_routes — owns the `/state` builder extraction),
  **022** (PaperBench `_JOBS`), **023** (separate_viz_file_io_from_route_handlers
  — owns file serving/traversal), **024**, **030**. 015 establishes the
  service/adapter/DTO + registry pattern these subtasks build on; sequence 015
  before or alongside 021/023 so they inherit a consistent seam. Per
  `007_subtask_index.md:535`, these form "Wave 6 — Dashboard backend + viz".
- **Downstream (not blocked by 015, but shares the contract):** frontend
  subtasks **062/063** (gated by 059/060/067) consume the same REST/WS
  contract; keeping wire output byte-compatible protects them.
- Upstream policy inputs: **006** (target architecture), **010** (contract
  preservation), **008** (viz dashboard refactoring plan).

## 16. Risk Level

- **Does this subtask change runtime code? YES** — when executed it modifies
  Python under `ari-core/ari/viz/` (dispatch, response handling, state
  accessors, adapter boundary, service extraction) and adds new modules. (This
  planning document itself changes no runtime code.)
- **Risk: HIGH** (consistent with `007_subtask_index.md:62`). Rationale: the
  viz backend is a large (8131 LOC), test-heavy, framework-free surface whose
  routing is order-sensitive string matching, and its output is a live contract
  for the React frontend. The dominant risks are (a) dispatch-ordering
  regressions from the registry translation and (b) accidental response-byte
  drift. Both are mitigated by the strong existing contract tests
  (`test_api_schema_contract.py`, `test_server.py`, `test_dashboard_html.py`,
  `test_workflow_contract.py`) and by strict incremental, per-step gating.
  Because there is no schema/validation layer today, the change is mechanical
  rather than semantic, which lowers the residual risk somewhat.

## 17. Notes for Implementer

- **Do not start before 020 exists.** The registry translation is only safe if
  you have the authoritative endpoint + branch-order inventory. If 020 is not
  yet authored, stop and escalate rather than reverse-engineering order from
  `routes.py` ad hoc.
- **Framework-free is intentional.** Do not "modernize" to Flask/FastAPI; that
  would change deployment, threading (`_DualStackServer`), and the `port+1`
  WebSocket model. Stay on stdlib `http.server`.
- **The `Access-Control-Allow-Origin: *` wildcard is current behavior** — keep
  it (making it *consistent* across all responses is the only allowed change).
  Do NOT add auth/CSRF here; note that the backend currently has **no auth on
  any endpoint** (including subprocess launch, file write, checkpoint delete,
  and the Ollama reverse proxy) as a **REVIEW_REQUIRED** item for a dedicated
  security subtask — flag it, do not fix it in 015.
- **Preserve `state.py` attribute names.** Existing tests
  (`test_api_schema_contract.py` fixture) `monkeypatch.setattr(_st,
  "_checkpoint_dir", ...)` etc. Renaming a global breaks them even if you add
  accessors.
- **`api_state.py` is a facade, `server.py` re-exports are load-bearing.** Do
  not collapse or delete them; downstream `from .api_state import ...` and
  `from .routes import _Handler` paths must keep working.
- **PaperBench, `/state`, and file-serving are explicitly out of scope** beyond
  the adapter reroute — resist the urge to also refactor `routes.py:219-666`,
  `file_api.py`, or `api_paperbench.py:_JOBS`; those belong to 021/023/022 and
  splitting ownership avoids merge conflicts in Wave 6.
- **The "sonfigs" directory does not exist.** Profile YAML read by the `/state`
  builder comes from `ari-core/config/` (top-level rubric/profile data), not
  from a `sonfigs/` path. Do not create or reference one.
- **radon is not installed; ruff is.** Use `ruff check .` for lint; do not add
  a radon dependency. `node`/`npm` exist (no `pnpm`) but the frontend is not
  part of this backend-only subtask.
- Update `ari-core/ari/viz/README.md` whenever you add a module — a
  readme-parity gate (`scripts/docs/check_readme_parity.py`) and doc-source
  checks run in CI.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **015** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
