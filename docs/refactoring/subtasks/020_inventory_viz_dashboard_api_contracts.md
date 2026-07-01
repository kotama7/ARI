# Subtask 020: Inventory Viz / Dashboard API Contracts

> Phase 4: Viz / Dashboard Backend · Risk: Low · Runtime code change: **No** · Depends on: — (root inventory)
>
> Planning document only. Nothing here modifies runtime code, imports, prompts,
> configs, workflows, frontend, or directory names. It hands a fresh coding session
> an executable plan to produce a **read-only contract inventory** of the dashboard
> HTTP/WebSocket API. All paths are repository-real and verified against the tree at
> planning date 2026-07-01 (ari-core `0.9.0`, branch `main`).

## 1. Goal

Produce a **complete, machine-checkable inventory** of the ARI dashboard's wire
contract — the surface that the React frontend (`ari-core/ari/viz/frontend/`) and
any external caller depend on — so that the downstream Phase-4 refactors can be
executed **behind an unchanged contract**. Concretely, 020 delivers a single
reference artifact enumerating, for every dashboard endpoint:

1. HTTP method + exact path (including path-parameter and query-parameter forms),
2. the owning handler module/function in `ari-core/ari/viz/`,
3. the request body shape (or "none" for GET),
4. the response body shape + the two coexisting conventions (`{"ok": ...}` vs
   `{"error": ...}`) and the `_status` smuggling mechanism,
5. the WebSocket channel + message type(s),
6. the frontend consumer binding in `services/api.ts` (typed wrapper name + line),
7. the CORS/header behavior per endpoint (uniform `Access-Control-Allow-Origin: *`
   vs. inline handlers that omit it).

This inventory is the **frozen baseline** that subtasks 021, 022, 023, 024, and 030
must preserve. 020 writes **no runtime code**; its only output is a reference
document/data file under `docs/refactoring/reports/` (an inventory artifact, not a
code change). Per `docs/refactoring/007_subtask_index.md:67`, 020's deliverable is
the "Viz/dashboard API contract inventory" and it is one of the nine inventory
subtasks that must precede any runtime code change.

## 2. Background

The dashboard backend lives under `ari-core/ari/viz/` (27 `.py` files, 8131 LOC
total) and is a **Python stdlib `http.server` app — no Flask/FastAPI/aiohttp**. The
architecture (verified 2026-07-01) is:

- `server.py` (201 LOC) — `_DualStackServer(ThreadingHTTPServer)` (`:82`) binds an
  IPv6 socket with IPv4 fallback; `main()`/`_main()` (`:183`/`:159`) start three
  threads: filesystem watcher, HTTP server (`_Handler`), and an asyncio WebSocket
  loop via `ws_serve` on `port+1` (`:178`).
- `routes.py` (1197 LOC) — a single `BaseHTTPRequestHandler` subclass `_Handler`
  (`:77`). Dispatch is a **giant if/elif chain**: `do_GET` (`:144`, ~86 branches),
  `do_POST` (`:1028`, ~51 branches), `do_OPTIONS` (CORS preflight, `:127`). There is
  **no route table** — matching is hand-rolled `startswith`/`endswith`/`re.match` on
  `self.path` (137 `self.path` references). Handlers are plain module functions
  imported from the `api_*` modules at `routes.py:27-47`; each returns a `dict`
  serialized by `_Handler._json(data, status)` (`:1190-1197`).
- `websocket.py` (36 LOC) — single `_ws_handler`; on connect it pushes one
  `{"type":"update","data":<tree>,"timestamp":...}` snapshot, then ignores inbound
  frames (`:23-36`). Push updates come from `state_sync._watcher_thread` (polls
  `tree.json`/`nodes_tree.json` mtimes every 1s) → `_broadcast`.
- `api_state.py` (76 LOC) is a **thin re-export facade** (Phase 3B refactor)
  forwarding to `checkpoint_finder`, `state_sync`, `checkpoint_api`, `ear`,
  `file_api`, `checkpoint_lifecycle`, `node_work_api` (`api_state.py:22-40`).
- `api_wizard.py` (35 LOC) defines an **unused `WIZARD_ROUTES` dict** (`:30-36`) — a
  partial, abandoned attempt at a declarative route table. It is imported by no
  route dispatcher today; note it as evidence of prior intent, not a live contract.

The frontend consumes this over same-origin fetch: `services/api.ts` (863 LOC,
`API_BASE=''` at `:14`) has ~90 typed wrappers. **Two error regimes coexist and are
a real contract hazard**: `get`/`post` **throw** on non-2xx (`api.ts:18-32`), but
PaperBench's `pbGet`/`pbPost` **never throw** and read `{error}` bodies from HTTP-200
responses (`api.ts:780-799`). The WebSocket client (`hooks/useWebSocket.ts:35-44`)
derives `wsPort = httpPort + 1` and connects to `${proto}//${host}:${wsPort}/`.

Two prior Phase-4 planning documents already exist and are **companions**, not
duplicates, of this subtask: `docs/refactoring/008_viz_dashboard_refactoring_plan.md`
(backend structure proposal) and `docs/refactoring/014_dashboard_ux_refactoring_plan.md`
(frontend UX). 020 is the *inventory* that both the 008-derived refactors (021/023)
and the schema checker (030) consume. There is **no** `ari-core/ari/viz/REFACTORING.md`
in the tree (only `ari-core/ari/viz/README.md`); references to "viz/REFACTORING.md" in
`api_state.py:18` are a stale docstring pointer — record it, do not act on it.

## 3. Scope

In scope (read-only inventory production):

- Enumerate **every** HTTP endpoint served by `_Handler.do_GET`/`do_POST`
  (`routes.py:144-1188`), grouped by owning `api_*` module, with method, exact path
  (literal + regex/param form), owning function, request shape, response shape, and
  status-code behavior (including `_status` smuggling at `routes.py:1047-1173`).
- Enumerate the **WebSocket contract**: endpoint `ws://host:(port+1)/`, the single
  `{"type":"update", ...}` message shape (`websocket.py:26-29`), and the push trigger
  (`state_sync._watcher_thread`).
- Record the **response-convention split**: `{"ok": bool, ...}` (launch/stage) vs.
  `{"error": str}` (file APIs) vs. bare-payload dicts, and the throw/no-throw
  frontend split (`get`/`post` vs. `pbGet`/`pbPost`).
- Record the **CORS/header inventory**: `_json` always sets
  `Access-Control-Allow-Origin: *` (`routes.py:1194`) but several inline handlers
  build raw responses that omit it (e.g. the `gpu-monitor` handler,
  `routes.py:667-672`); enumerate every inline `send_response`/`send_header` site.
- Map each backend endpoint to its **frontend consumer** in `services/api.ts`
  (wrapper name + line) and, where relevant, the `types/index.ts` shape
  (`Settings` 35 fields `:38-75`, `AppState` `:87-129`, `NodeReport` `api.ts:124-153`).
- Classify each endpoint with the master vocabulary (KEEP / ADAPT / MERGE /
  MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED) **as a recommendation for
  downstream subtasks only** — 020 changes nothing.
- Flag the `WIZARD_ROUTES` abandoned route table (`api_wizard.py:30`) and the
  `api_state.py` facade as inventory metadata.

## 4. Non-Goals

- **Do not** modify any file under `ari-core/ari/viz/` (backend or `frontend/`), any
  route, handler, response shape, header, or the WebSocket protocol. 020 is
  read-only; the whole point is a frozen baseline.
- **Do not** implement the service-layer extraction (that is **021**), the DTO/schema
  tests (**022**), the file-I/O service split (**023**), the BFTS tree-viz adapter
  (**024**), or the `check_viz_api_schema.py` checker script (**030**). 020 only
  produces the inventory those subtasks consume.
- **Do not** change `docs/refactoring/008_*.md` or `014_*.md`; cross-reference them.
- **Do not** touch `ari.public.*`, the CLI, MCP `ari-skill-*` servers, checkpoint or
  config formats. None are in the dashboard wire contract 020 inventories.
- **Do not** "fix" the two known hazards found during inventory (the throw/no-throw
  regime split; the inconsistent CORS on inline handlers). Record them as
  REVIEW_REQUIRED findings for 021/022/030; resolving them is out of scope here.
- **Do not** add authentication or path-traversal hardening. Security posture is
  inventoried (see §6) but not changed.

## 5. Current Files / Directories to Inspect

Backend dispatch + framework:

- `ari-core/ari/viz/routes.py` (1197 LOC) — `_Handler` (`:77`); `do_OPTIONS` (`:127`),
  `do_GET` (`:144`, ~86 branches incl. the inline `GET /state` builder at
  `:219-666`), `do_POST` (`:1028`, ~51 branches), `_json` (`:1190`), `_write_access_log`
  (`:60-74`), handler imports (`:27-47`).
- `ari-core/ari/viz/server.py` (201 LOC) — `_DualStackServer` (`:82`), thread startup
  (`:105-197`), `ws_serve` on `port+1` (`:178`); re-exports `_Handler`/`_ws_handler`
  for back-compat (`:78`, `:51`).
- `ari-core/ari/viz/websocket.py` (36 LOC) — `_ws_handler`, single `update` message
  (`:26-29`).
- `ari-core/ari/viz/state_sync.py` (117 LOC) — `_watcher_thread` (mtime poll → push),
  `_broadcast`/`_do_broadcast`.
- `ari-core/ari/viz/state.py` (79 LOC) — module-level mutable globals read/written by
  handlers (`_checkpoint_dir:19`, `_last_proc:21`, `_running_procs:22`,
  `_launch_config:28`, `_clients:17`, `_sub_experiments:30`).
- `ari-core/ari/viz/api_state.py` (76 LOC) — thin re-export facade (`:22-40`).
- `ari-core/ari/viz/api_wizard.py` (35 LOC) — **unused** `WIZARD_ROUTES` (`:30-36`).

Endpoint-owning `api_*` / helper modules (all under `ari-core/ari/viz/`):

- `api_experiment.py` (929) — `_api_launch`, `_api_run_stage` (Popen `:129`, `.env`
  parse + `ARI_*` env mapping `:44-128`), `_api_logs_sse`.
- `api_paperbench.py` (813) + `api_paperbench_worker.py` (319) — PaperBench endpoints;
  in-memory job store `_JOBS`/`_JOBS_LOCK` (`api_paperbench.py:496-497`), SSE run logs.
- `api_settings.py` (553), `api_workflow.py` (462) — settings/env-keys/workflow/skills/
  profiles/rubrics/scheduler.
- `api_orchestrator.py` (321) — sub-experiments (Popen `:287`).
- `checkpoint_api.py` (327), `checkpoint_lifecycle.py` (205), `checkpoint_finder.py`
  (65), `file_api.py` (307), `node_work_api.py` (233) — checkpoint/file endpoints.
- `ear.py` (452), `api_publish.py` (191), `api_fewshot.py` (221) — EAR/publish/fewshot.
- `api_tools.py` (259) — chat-goal/config-generate/upload/ssh-test.
- `api_memory.py` (227) — memory health/detect/start/stop/restart (subprocess).
- `api_process.py` (205) — gpu-monitor/stop (Popen/pkill/pgrep).
- `api_ollama.py` (90) — ollama resources + reverse proxy.
- `ui_helpers.py` (183) — `_REDACT_KEYS`, `_build_experiment_detail_config`,
  `_collect_resource_metrics`, `_extract_goal_from_md`.

Frontend consumer contract (inventory reference, **not** to be edited):

- `ari-core/ari/viz/frontend/src/services/api.ts` (863) — `API_BASE` (`:14`),
  `get`/`post` throw (`:18-32`), `pbGet`/`pbPost` no-throw (`:787-799`), ~90 wrappers.
- `ari-core/ari/viz/frontend/src/hooks/useWebSocket.ts` — `wsPort = httpPort+1`,
  connect URL (`:35-44`).
- `ari-core/ari/viz/frontend/src/types/index.ts` — `Settings` (`:38-75`), `AppState`
  (`:87-129`).
- `ari-core/ari/viz/frontend/src/context/AppContext.tsx` (120) — 5s polling of
  `/state` + `/checkpoints` (`:34,86-89`).

Companion planning docs (cross-reference, do not edit): `docs/refactoring/008_viz_dashboard_refactoring_plan.md`,
`docs/refactoring/014_dashboard_ux_refactoring_plan.md`, `docs/refactoring/007_subtask_index.md`
(entries at `:67-71`, `:77`, `:238-252`).

Output location for the inventory artifact: `docs/refactoring/reports/` (sibling to
existing reports such as `docs/refactoring/reports/…`). The inventory is a **new
reference file** (see §9), not a code change.

## 6. Current Problems

These are the reasons the inventory must exist before any Phase-4 refactor. They are
findings to **record**, not to fix in 020.

1. **No route table / no schema layer.** Dispatch is ~137 hand-rolled string matches
   across `do_GET`/`do_POST` (`routes.py:144-1188`). There is no single place that
   lists the endpoints, so a refactor (021/023) has no baseline to diff against unless
   020 produces one. The abandoned `WIZARD_ROUTES` (`api_wizard.py:30`) proves the
   intent existed but was never wired.
2. **Two response conventions coexist.** `{"ok": bool, ...}` (launch/run-stage) vs.
   `{"error": str}` (file APIs) vs. bare payloads, with status codes **smuggled** via
   `r.pop("_status", 200)` (`routes.py:1047-1057, 1088-1089, 1167-1173`). Any DTO/
   schema work (022) needs this enumerated per endpoint.
3. **Frontend throw/no-throw split.** `get`/`post` throw on non-2xx (`api.ts:18-32`);
   `pbGet`/`pbPost` never throw and rely on HTTP-200 `{error}` bodies
   (`api.ts:780-799`). The **same** backend `_json` defaults to `status=200`
   (`routes.py:1190`), so error semantics differ per client wrapper. This is a
   contract hazard that 030's checker must cover.
4. **Inconsistent CORS headers.** `_json` always emits `Access-Control-Allow-Origin: *`
   (`routes.py:1194`), but inline raw-response handlers omit it (e.g. gpu-monitor
   `routes.py:667-672`, and the binary file-serving sites at `:710, :740, :815, :905,
   :967`). Wire behavior differs by endpoint; the inventory must flag which endpoints
   are inline vs. `_json`-wrapped.
5. **Business logic + I/O inlined in routes.** The `GET /state` handler is ~450 lines
   inlined in `routes.py:219-666` (glob scans, YAML profile merge, `cost_trace.jsonl`
   tail-parse, `pidfile` reach-in). Several handlers spawn subprocesses
   (`api_experiment._api_run_stage` Popen `:129`, `api_orchestrator` Popen `:287`,
   `api_process` `pkill`/`pgrep`). These are the extraction targets for 021/023; 020
   must record the exact endpoint→side-effect mapping so nothing is lost.
6. **In-memory, restart-losing job store.** PaperBench `_JOBS` dict + `_JOBS_LOCK`
   (`api_paperbench.py:496-497`) is process-local. The inventory should mark the
   PaperBench run endpoints as stateful (job IDs are not durable) so 021/023 preserve
   that behavior explicitly.
7. **No auth anywhere.** Every endpoint (including subprocess launch, file write,
   checkpoint delete, ollama proxy) is open with `Access-Control-Allow-Origin: *`.
   Record as REVIEW_REQUIRED metadata; do not change.
8. **Mutable module globals as implicit contract.** Handlers read/write `state.py`
   globals directly (`_checkpoint_dir`, `_last_proc`, `_running_procs`,
   `_launch_config`, `_clients`, `_sub_experiments`). The inventory should note which
   endpoints mutate which global, because 021's service extraction must keep the same
   observable effect.

## 7. Proposed Design / Policy

020 produces **one inventory artifact** plus a short findings section. No runtime
classification changes anything; classifications are *recommendations* consumed by
021/022/023/024/030.

### 7.1 Inventory format

Emit a structured, diff-friendly reference file (recommended:
`docs/refactoring/reports/viz_api_contract_inventory.md` with an embedded table, or a
companion `.json` if a machine-readable form is preferred by 030). Each endpoint row:

| field | source of truth |
|---|---|
| `method` | `do_GET`/`do_POST`/`do_OPTIONS` branch in `routes.py` |
| `path` (literal + param/regex form) | the `self.path` match expression |
| `owner_module.func` | the imported handler at `routes.py:27-47` (or inline) |
| `request_shape` | `json.loads(body)` keys read inside the handler |
| `response_shape` | dict keys returned + which convention (`ok`/`error`/payload) |
| `status_behavior` | `_json(...)` default 200 vs. `_status` pop vs. inline codes |
| `cors` | `_json` (uniform `*`) vs. inline (record present/absent) |
| `side_effects` | file read/write, Popen/pkill, subprocess.run, global mutation |
| `ws_related` | whether the endpoint's data is also pushed over `update` |
| `frontend_binding` | `services/api.ts` wrapper name + line; `types/index.ts` shape |
| `classification` | KEEP / ADAPT / MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED |

### 7.2 Endpoint groups to capture (verified inventory scaffold)

Capture at minimum these groups (owning module in parentheses; exhaustive
enumeration is the work item, this is the scaffold):

- **State/tree** (`routes.py` inline + `state_sync`): `GET /state` (`:219-666`),
  `GET /memory/<node_id>` (legacy, `:191-218`), `GET /codefile?path=` (`:678-719`),
  `GET /api/models`, `GET /api/active-checkpoint`, `GET /api/experiment-detail`,
  `GET /api/resource-metrics`, `GET /api/lineage-decisions/<ckpt>`.
- **Checkpoints/files** (`checkpoint_api`, `checkpoint_lifecycle`, `file_api`,
  `node_work_api`): `GET /api/checkpoints`, `GET /api/checkpoint/<id>/{summary,memory,
  files,filetree,filecontent,file[/raw],paper.(pdf|tex),memory_access}`,
  `POST /api/switch-checkpoint`, `POST /api/delete-checkpoint`,
  `POST /api/checkpoint/file/{save,delete}`, `POST /api/checkpoint/compile`,
  `POST /api/checkpoint/<id>/file/upload`.
- **Experiment** (`api_experiment`): `POST /api/launch`, `POST /api/run-stage`,
  `GET /api/logs` (SSE).
- **Settings/workflow** (`api_settings`, `api_workflow`): `GET|POST /api/settings`,
  `GET|POST /api/env-keys`, `GET|POST /api/workflow`, `GET /api/workflow/{default,flow}`,
  `POST /api/workflow/{flow,skills,disabled-tools}`, `GET /api/skills`,
  `GET /api/skill/<name>`, `GET /api/profiles`, `GET /api/rubrics`,
  `GET /api/scheduler/detect`, `GET /api/slurm/partitions`.
- **PaperBench** (`api_paperbench`, `_worker`): `GET /api/paperbench/papers`,
  `GET /api/paperbench/arxiv/<id>`, `GET /api/paperbench/papers/<id>/license`,
  `POST /api/paperbench/papers/{import,<id>/delete,<id>/metadata}`,
  `POST /api/paperbench/{run,cost-estimate}`,
  `GET /api/paperbench/run/<jid>[/{logs(SSE),results,report,status}]`.
- **Tools/wizard** (`api_tools`): `POST /api/{chat-goal,config/generate,upload,
  upload/delete,ssh/test}`.
- **Orchestrator** (`api_orchestrator`): `GET /api/sub-experiments[/<id>]`,
  `POST /api/sub-experiments/launch`.
- **Memory** (`api_memory`): `GET /api/memory/{health,detect}`,
  `POST /api/memory/{start-local,stop-local,restart}`.
- **EAR** (`ear`): `GET /api/ear/<rid>[/publish-yaml]`,
  `GET /api/nodes/<rid>/<nid>/report`, `POST /api/ear/<rid>/{curate,publish-yaml}`,
  `POST /api/ear/clone-verify`.
- **Publish** (`api_publish`): `GET|POST /api/publish/settings`,
  `GET /api/publish/<rid>/{preview,record}`, `POST /api/publish/<rid>[/promote]`.
- **Fewshot** (`api_fewshot`): `GET /api/fewshot/<rubric>`,
  `POST /api/fewshot/<rubric>/{sync,upload}`, `POST /api/fewshot/<rubric>/<ex>/delete`.
- **Process/GPU** (`api_process`): `GET|POST /api/gpu-monitor`, `POST /api/stop`.
- **Ollama/container** (`api_ollama`, inline): `GET /api/ollama-resources`,
  `GET|POST /api/ollama/*` (reverse proxy `_ollama_proxy`),
  `GET /api/container/{info,images}`, `POST /api/container/pull`.
- **WebSocket** (`websocket.py`): `ws://host:(port+1)/`, message `{"type":"update",
  "data":<tree>,"timestamp":...}` only.
- **OPTIONS** (`routes.py:127`): CORS preflight for all paths.

### 7.3 Extraction method (deterministic, no code change)

- Derive endpoints by static reading of the `do_GET`/`do_POST` branch bodies
  (`routes.py`) — the branch condition gives the path form; the called handler gives
  the owner; the handler body gives request keys and response dict keys.
- Cross-check the frontend by listing every `get(`/`post(`/`pbGet(`/`pbPost(` call in
  `services/api.ts` and pairing each URL to a backend branch. Any frontend URL with
  no backend branch (or vice versa) is a **drift finding** (candidate REVIEW_REQUIRED
  / DELETE_CANDIDATE) — record it; do not resolve it.
- The inventory generation may be scripted (a throwaway analysis script under the
  scratchpad, not committed) but the **committed artifact** is the resulting
  reference file only. Do not add a checker to `scripts/` — that is subtask **030**.

## 8. Concrete Work Items

1. **Enumerate GET endpoints.** Walk `routes.py:144-1026`; for each branch record
   method/path/owner/request/response/status/cors/side-effects, including the inline
   `GET /state` builder (`:219-666`) and the inline binary-serving branches
   (`/codefile` `:678-719`, `/api/checkpoint/.../file/raw` `:797-818`,
   `/api/checkpoint/<id>/paper.*` `:727-744`).
2. **Enumerate POST endpoints.** Walk `routes.py:1028-1188`; record the same fields
   plus the `_status` smuggling sites (`:1047-1057, 1088-1089, 1167-1173`) and every
   subprocess-spawning handler.
3. **Enumerate SSE endpoints.** Record the two inline SSE loops: PaperBench logs
   (`routes.py:934-1000`, 300s deadline + heartbeat) and `/api/logs`
   (`routes.py:901-908`); note they are streaming, not `_json`-wrapped.
4. **Enumerate the WebSocket contract.** From `websocket.py:23-36` and
   `state_sync._watcher_thread`: one endpoint, one message type `update`, push
   trigger = mtime change on `tree.json`/`nodes_tree.json`/`node_*/tree.json` (1s
   poll). Record that inbound frames are ignored (no client→server protocol).
5. **Record response conventions + status behavior** per endpoint (`ok`/`error`/
   payload; 200-default vs. `_status` pop vs. inline `send_response`).
6. **Record CORS behavior** per endpoint (`_json` uniform `*` vs. inline omit).
   Explicitly list the inline sites at `routes.py:667-672, 710, 740, 815, 905, 967`.
7. **Map frontend bindings.** For each backend endpoint, record the `services/api.ts`
   wrapper (name + line) and the relevant `types/index.ts` shape; flag the
   `get`/`post` vs. `pbGet`/`pbPost` throw/no-throw regime per binding.
8. **Record stateful/side-effecting metadata.** Mark endpoints that (a) spawn
   subprocesses, (b) write files/logs (`viz_access.jsonl` per request,
   `routes.py:60-74`), (c) mutate `state.py` globals, (d) rely on `_JOBS`
   (restart-losing).
9. **Record drift + hazards** as a findings list: throw/no-throw split, CORS
   inconsistency, `WIZARD_ROUTES` dead code, stale `viz/REFACTORING.md` docstring
   pointer (`api_state.py:18`), any frontend/backend URL mismatches, no-auth posture.
10. **Assign classifications** (KEEP/ADAPT/MERGE/MOVE_TO_LEGACY/DELETE_CANDIDATE/
    REVIEW_REQUIRED) as recommendations for 021/022/023/024/030. Default is KEEP
    (contract-preserved); mark the 450-line `/state` builder and subprocess handlers
    ADAPT (extract behind unchanged wire shape); mark `WIZARD_ROUTES` DELETE_CANDIDATE.
11. **Write the artifact** to `docs/refactoring/reports/viz_api_contract_inventory.md`
    (and optionally a `.json` twin for 030). Cross-link from this subtask and from
    008/014 in prose only (do not edit those files).
12. **Self-check counts.** Confirm the enumerated GET-branch count (~86) and
    POST-branch count (~51) against `routes.py`, and that every `services/api.ts`
    URL is accounted for.

## 9. Files Expected to Change

020 changes **no runtime code**. The only files it creates/edits:

- `docs/refactoring/subtasks/020_inventory_viz_dashboard_api_contracts.md` — this
  planning document.
- **New (produced when the subtask is executed):**
  `docs/refactoring/reports/viz_api_contract_inventory.md` — the inventory artifact
  (and optionally `docs/refactoring/reports/viz_api_contract_inventory.json` for 030).

Explicitly **not** changed (read-only inputs): everything under
`ari-core/ari/viz/` (all 27 backend `.py` files and the entire `frontend/` tree),
`docs/refactoring/008_*.md`, `docs/refactoring/014_*.md`, `docs/refactoring/007_subtask_index.md`,
`scripts/**`, `.github/workflows/**`.

## 10. Files / APIs That Must Not Be Broken

Because 020 is read-only, "must not be broken" means the inventory must faithfully
record — never alter — these contracts:

- **Dashboard HTTP API**: every `do_GET`/`do_POST` path in `routes.py` and its
  response shape. The inventory is the frozen baseline; downstream refactors diff
  against it.
- **WebSocket API**: `ws://host:(port+1)/`, single `update` message shape
  (`websocket.py:26-29`); `wsPort = httpPort+1` derivation (`useWebSocket.ts:35-44`).
- **Frontend consumer contract**: `services/api.ts` wrapper URLs, the `get`/`post`
  throw semantics (`:18-32`) and the `pbGet`/`pbPost` no-throw semantics (`:780-799`),
  and `types/index.ts` shapes (`Settings` `:38-75`, `AppState` `:87-129`).
- **The `_status` status-code convention** (`routes.py:1047-1173`) and the
  `Access-Control-Allow-Origin: *` header behavior (`_json` `:1194` + inline sites).
- Out-of-band but must not be incidentally touched: **CLI `ari`**, **`ari.public.*`**,
  **MCP `ari-skill-*` tool contracts**, **checkpoint/output/config file formats**,
  **README/docs usage**, **scripts called by `.github/workflows`**. 020 reads none of
  these into a mutation.

## 11. Compatibility Constraints

- 020 is **inventory only** — there is nothing to make compatible, because no runtime
  behavior changes. The compatibility obligation is *forward*: the artifact must be
  accurate enough that 021/023 can prove byte-for-byte wire preservation against it.
- The inventory must record contracts **as they are**, including the two known
  hazards (throw/no-throw regime; CORS inconsistency). Recording them is not
  endorsing them; do not "normalize" shapes in the inventory (that would hide the
  baseline the checker in 030 must enforce).
- No `pyproject.toml`, `requirements*.txt`, workflow, prompt, or config file is
  touched. There is **no** top-level `pyproject.toml`; the core manifest is
  `ari-core/pyproject.toml` and is not touched. The prompt's "sonfigs" directory does
  **not exist** in this repo (the confusable trio is `ari-core/ari/config/` [code] vs.
  `ari-core/ari/configs/` [packaged defaults] vs. top-level `ari-core/config/` [rubric
  data]) — irrelevant to the viz wire contract and not referenced by the inventory.
- The word "deprecated" is reserved for external contracts. Internal dead code found
  during inventory (e.g. `WIZARD_ROUTES`) is classified DELETE_CANDIDATE, **not**
  "deprecated".

## 12. Tests to Run

020 produces documentation/data, so the test surface is a **sanity/lint gate**, not a
behavior gate. From repo root (`/home/t-kotama/workplace/ARI`):

- `python -m compileall ari-core/ari/viz` — confirms the read-only inspection did not
  accidentally corrupt any backend source (should be a no-op; nothing was edited).
  Before considering the subtask complete, also run `python -m compileall .`.
- `pytest -q` — full core suite must still pass unchanged (the viz-heavy suites
  `ari-core/tests/test_server.py` (1844), `test_gui_errors.py` (1650),
  `test_workflow_contract.py` (1606), `test_wizard.py` (1133) exercise the exact
  endpoints inventoried; a green run confirms the baseline the inventory describes is
  the live one). No test should need modification.
- `ruff check .` — ruff is available (radon is not); confirm no lint regressions
  (expected: none, since no `.py` changed).
- **Frontend** (the consumer contract is inventoried, not changed): from
  `ari-core/ari/viz/frontend/`, `npm run typecheck` and `npm test` (Vitest) should
  pass unchanged; `npm run build` is optional and only to confirm the tree still
  builds. `npm` is available (no `pnpm`). No frontend file is edited by 020.
- **Docs guards** for the new report file: `python scripts/docs/check_doc_links.py`
  and `python scripts/docs/check_doc_sources.py` (the inventory is a tracked doc; make
  sure its links/source references resolve). Confirm `refactor-guards.yml` invariants
  still hold (no new `~/.ari` references introduced by the doc).

## 13. Acceptance Criteria

1. `docs/refactoring/reports/viz_api_contract_inventory.md` exists and enumerates
   **every** endpoint reachable from `_Handler.do_GET`/`do_POST` (`routes.py`), with
   the §7.1 fields populated. The GET/POST branch counts in the artifact match the
   live counts in `routes.py` (~86 GET, ~51 POST); no branch is omitted.
2. The WebSocket contract is captured: one endpoint, one `update` message shape,
   `port+1` derivation, push trigger, inbound-ignored.
3. The two response conventions (`ok`/`error`/payload), the `_status` mechanism, and
   the SSE endpoints are recorded per endpoint.
4. The CORS inventory lists `_json` (uniform `*`) vs. every inline-omit site
   (`routes.py:667-672, 710, 740, 815, 905, 967`).
5. Every `services/api.ts` URL is paired to a backend endpoint (or flagged as drift),
   with the throw/no-throw regime noted per binding.
6. Side-effect/stateful metadata (subprocess spawns, `viz_access.jsonl` writes,
   `state.py` global mutations, restart-losing `_JOBS`) is recorded per endpoint.
7. A findings list captures: throw/no-throw hazard, CORS inconsistency, `WIZARD_ROUTES`
   dead code, stale `viz/REFACTORING.md` docstring pointer, no-auth posture, and any
   frontend/backend drift.
8. Each endpoint carries a classification (KEEP/ADAPT/MERGE/MOVE_TO_LEGACY/
   DELETE_CANDIDATE/REVIEW_REQUIRED) as a downstream recommendation.
9. `python -m compileall .`, `pytest -q`, and `ruff check .` are clean; no runtime
   file diff exists (verify `git status` shows only the two docs).

## 14. Rollback Plan

Trivial and risk-free: 020 adds documentation only. Rollback is `git rm`/`git revert`
of the two doc files:

1. Delete `docs/refactoring/reports/viz_api_contract_inventory.md` (and the optional
   `.json` twin).
2. Revert this planning document if it was committed.

No runtime code, format, migration, or workflow is touched, so there is nothing to
un-migrate and no way for rollback to affect the running dashboard. Downstream
subtasks (021/022/023/024/030) that consumed the inventory simply lose their baseline
reference until it is regenerated.

## 15. Dependencies

- **Predecessors: none.** 020 is a **root inventory subtask** in the dependency graph
  (no `X -> 020` edge). It can start immediately and is itself one of the nine
  inventory subtasks (001, 002, 020, 036, 045, 053, 059, 060, 067) that MUST precede
  any runtime code change (`docs/refactoring/007_subtask_index.md:513`).
- **Dependents (this subtask gates them): 021, 022, 023, 024, 030** — the graph edges
  are `020 -> 021`, `020 -> 022`, `020 -> 023`, `020 -> 024`, `020 -> 030`
  (`007_subtask_index.md:417-421`). Concretely: 021 (`extract_viz_services_from_routes`)
  and 023 (`separate_viz_file_io_from_route_handlers`) extract behind the frozen wire
  contract; 022 (`define_dashboard_dto_and_schema_tests`) turns the inventory into
  schema tests; 024 (`refactor_bfts_tree_visualization_adapter`) preserves the
  `tree.json`/`nodes_tree.json` + WS `update` shape recorded here; 030
  (`add_viz_api_schema_checker_script`) builds `check_viz_api_schema.py` from the
  inventory.
- **Soft gate: 015** (`refactor_dashboard_viz_api_services`) is marked "— (gate 020)"
  in the index (`007_subtask_index.md:62, 129-130, 238`): no hard graph edge, but 015
  should not begin until 020's inventory exists.
- **Companion (not a graph edge):** `docs/refactoring/008_viz_dashboard_refactoring_plan.md`
  (backend structure) and `014_dashboard_ux_refactoring_plan.md` (frontend UX) — 020
  supplies the contract table both rely on. No ordering constraint between the
  planning docs themselves.

## 16. Risk Level

**Low** (matches `docs/refactoring/007_subtask_index.md:67`). **Runtime code change:
No.** 020 only reads the backend/frontend and writes a documentation artifact. The
sole risk is *inaccuracy* — an incomplete or wrong inventory would let a downstream
refactor (021/023) silently break the wire contract. Mitigations: (a) enumerate
directly from `routes.py` branch bodies rather than from memory; (b) cross-validate
against every `services/api.ts` URL; (c) require the branch-count self-check (§8.12)
and a green `pytest -q` of the viz-heavy suites (§12) as evidence the inventory
describes the live contract. No data, format, or public API is touched, so there is no
runtime-regression risk.

## 17. Notes for Implementer

- **Source of truth is the branch body, not the branch condition.** The `self.path`
  match tells you the path; you must read the *called handler* (imported at
  `routes.py:27-47`) to get the real request keys and response dict shape. For the
  inline `GET /state` (`:219-666`) and the inline binary/SSE branches, the handler
  *is* the branch body — read it in place.
- **Do not normalize.** Record `{"ok": ...}` vs. `{"error": ...}` vs. bare payload
  exactly as returned, and record `status=200`-on-error where it happens
  (`pbGet`/`pbPost` depend on it). Hiding this defeats 022/030.
- **`WIZARD_ROUTES` is dead** (`api_wizard.py:30`): no dispatcher imports it; it is
  not a live contract. Classify DELETE_CANDIDATE and note it as prior "route table"
  intent. Do **not** treat it as authoritative for the endpoint list.
- **`api_state.py` is a facade** (`:22-40`), so several endpoints' true owners are
  `checkpoint_finder`/`state_sync`/`checkpoint_api`/`ear`/`file_api`/
  `checkpoint_lifecycle`/`node_work_api`. Record the *concrete* owner, not the facade.
- **CORS is not uniform.** `_json` sets `Access-Control-Allow-Origin: *` (`:1194`) but
  inline handlers (gpu-monitor `:667-672`, file-serving `:710/:740/:815`, SSE
  `:905/:967`) build raw responses; some omit the header. This is a real wire
  difference — record it per endpoint, do not "fix" it (that is 021/022's call).
- **The `port+1` WebSocket rule is load-bearing.** Backend serves WS via `ws_serve`
  on `port+1` (`server.py:178`); the frontend hardcodes `wsPort = httpPort+1`
  (`useWebSocket.ts:41`). Any future single-port migration is out of scope; just
  record the current derivation.
- **Node-modules hygiene note (correction to earlier skeleton):** `node_modules/` is
  **not** committed — `.gitignore:113` ignores
  `ari-core/ari/viz/frontend/node_modules/`; `git ls-files` returns 0 matches. It
  exists on disk as a normal install. Do not "clean up" anything here.
- **Stay read-only.** If you find yourself editing any file under `ari-core/ari/viz/`
  you have left 020's scope — stop. The whole value of this subtask is that the
  baseline it records was captured from an *unmodified* tree.
- Prefer emitting a `.json` twin of the inventory if 030's checker author would rather
  consume structured data; keep the human-readable `.md` as the canonical narrative.
  Both go under `docs/refactoring/reports/`.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **020** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
