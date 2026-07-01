# 008 — Viz / Dashboard Backend Refactoring Plan

> Status: PLANNING ONLY. This document proposes structure; it changes no runtime code, imports,
> prompts, configs, workflows, frontend, or directory names. The only artifact produced by this
> task is this `.md` file.
>
> Scope: the **dashboard backend** under `ari-core/ari/viz/` (Python `http.server` app + `api_*`
> modules + WebSocket). The React/TypeScript frontend under `ari-core/ari/viz/frontend/` is
> treated as a **consumer contract** (see §5); it is inventoried but not restructured here.
>
> Classification vocabulary (from the master prompt): **KEEP / ADAPT / MERGE / MOVE_TO_LEGACY /
> DELETE_CANDIDATE / REVIEW_REQUIRED**. The word "deprecated" is reserved for external contracts
> only (dashboard HTTP API, CLI, MCP tool contracts, `ari.public.*`, documented import paths).

Repo root: `/home/t-kotama/workplace/ARI` (branch `main`, ari-core `0.9.0`). Verified 2026-07-01
by direct inspection. Note: the `sonfigs/` directory referenced in some planning prompts **does
not exist**; viz reads profile YAML from `ari-core/config/` (e.g. `routes.py:376,388,401,612`).

---

## 1. Current Files

All paths below are under `ari-core/ari/viz/`. Line counts are `wc -l` verified on 2026-07-01.
Total Python surface in the package: **8,131 LOC across 27 `.py` files** (excluding `frontend/`).

| File | LOC | Role | Classification |
|------|-----|------|----------------|
| `routes.py` | 1197 | `_Handler(BaseHTTPRequestHandler)` — the entire `do_GET`/`do_POST`/`do_OPTIONS` dispatch chain + `_write_access_log` + `_json` | REVIEW_REQUIRED (split into Route/Service) |
| `api_experiment.py` | 929 | launch/run-stage/SSE-logs; subprocess spawning + `.env`/`ARI_*` env mapping | REVIEW_REQUIRED |
| `api_paperbench.py` | 813 | PaperBench papers/import/run; in-memory `_JOBS` job store | REVIEW_REQUIRED |
| `api_settings.py` | 553 | settings/env-keys/workflow/skills/profiles/rubrics/scheduler read+write | ADAPT |
| `api_workflow.py` | 462 | workflow flow/skills/disabled-tools | ADAPT |
| `ear.py` | 452 | EAR curate/publish-yaml/clone-verify + node report | ADAPT |
| `checkpoint_api.py` | 327 | model list, checkpoint list/summary, lineage decisions | ADAPT |
| `api_orchestrator.py` | 321 | sub-experiment list/get/launch (Popen) | ADAPT |
| `api_paperbench_worker.py` | 319 | PaperBench run worker | ADAPT |
| `file_api.py` | 307 | checkpoint file read/save/upload/delete/compile + traversal guards | ADAPT |
| `api_tools.py` | 259 | wizard chat-goal/config-generate/upload/ssh-test | ADAPT |
| `node_work_api.py` | 233 | per-node work-dir filetree/filecontent/memory | ADAPT |
| `api_memory.py` | 227 | Letta memory health/detect/start/stop/restart (subprocess) | ADAPT |
| `checkpoint_lifecycle.py` | 205 | delete/switch checkpoint | ADAPT |
| `api_process.py` | 205 | GPU monitor status/action, stop (Popen/pkill/pgrep) | ADAPT |
| `server.py` | 201 | `_DualStackServer`, `_http_thread`, `_main()`, three-thread bootstrap; re-exports `_Handler`/`_ws_handler` | KEEP (thin entrypoint) |
| `api_publish.py` | 191 | publish settings/preview/record/promote | ADAPT |
| `ui_helpers.py` | 183 | `_REDACT_KEYS`, `_build_experiment_detail_config`, `_collect_resource_metrics`, `_extract_goal_from_md` | KEEP (already a helper layer) |
| `state_sync.py` | 117 | tree loading + WS `_broadcast`/`_do_broadcast` + `_watcher_thread` | KEEP |
| `api_ollama.py` | 90 | ollama resources + reverse proxy | ADAPT |
| `state.py` | 79 | module-level mutable globals + `set_active_checkpoint`/`require_checkpoint_dir` | REVIEW_REQUIRED (encapsulate) |
| `api_state.py` | 76 | **thin re-export facade** (Phase 3B) → `checkpoint_finder`/`state_sync`/`checkpoint_api`/`ear`/`file_api`/`checkpoint_lifecycle`/`node_work_api` | KEEP (compat facade) |
| `checkpoint_finder.py` | 65 | `_checkpoint_search_bases`, `_check_pid_alive`, `_resolve_checkpoint_dir` | KEEP |
| `websocket.py` | 36 | `_ws_handler` (single async fn) | KEEP |
| `api_wizard.py` | 35 | re-export shim + **unused** `WIZARD_ROUTES` declarative table | REVIEW_REQUIRED (dead/abandoned) |
| `__init__.py` | — | package marker | KEEP |

Observations:
- The package has **already been through a "Phase 3B" split** (banners in `api_state.py`,
  `state_sync.py`, `checkpoint_api.py`, `ear.py`, `node_work_api.py`, `checkpoint_lifecycle.py`).
  That refactor moved *bodies* out of the old monolithic `api_state.py` into per-cluster modules,
  leaving `api_state.py` as a 76-line re-export facade. It did **not** introduce a
  Route→Service→Store layering; the modules are still flat function collections that mix HTTP-shape
  concerns, business logic, and file/subprocess I/O.
- A circular-by-design pattern exists: `checkpoint_api.py`, `ear.py`, etc. define bare-name
  wrappers that call back into `api_state` at call time (e.g. `checkpoint_api.py:26-40`) so tests
  that `monkeypatch.setattr(api_state, ...)` still intercept. This is a **test-seam workaround**
  that a real Service layer would obviate — flag as REVIEW_REQUIRED, do not remove without
  replacing the seam.
- `api_wizard.py`'s `WIZARD_ROUTES` dict (`api_wizard.py:30-35`) is imported nowhere; it is an
  abandoned first attempt at a declarative route table (DELETE_CANDIDATE, but see §12 — its intent
  should be *realized*, not just deleted).

## 2. Current Route Handlers

There is **one** HTTP handler class: `_Handler(BaseHTTPRequestHandler)` in `routes.py:77`
(`protocol_version = "HTTP/1.1"`). Dispatch is a hand-rolled if/elif chain:

- `do_OPTIONS` — `routes.py:127-142` (CORS preflight; emits `Access-Control-Allow-*`).
- `do_GET` — `routes.py:144-1026` (~880 lines). Branch selection by `self.path` via
  `==` / `startswith` / `endswith` / `re.match`, with query strings parsed inline via
  `urllib.parse`.
- `do_POST` — `routes.py:1028-1188` (~160 lines). Same style; POST bodies are read as raw
  `bytes` and `json.loads`-ed inside each downstream handler, not in the router.
- `_json(self, data, status=200)` — `routes.py:1190-1197`. The only response serializer; always
  sets `Access-Control-Allow-Origin: *`.
- `_write_access_log(checkpoint_dir, entry)` — `routes.py:69-74`. Appends one line to
  `viz_access.jsonl` per request.

There is **no route table, no decorator registry, no middleware, no auth layer**. `self.path`
string literals appear **137 times** in `routes.py` (`grep -c "self.path"`). WebSocket has its own
handler `_ws_handler` in `websocket.py:20`, wired in `server.py`, not through `_Handler`.

The single largest handler is the **inline `GET /state` builder at `routes.py:219-666`
(~450 lines)** — this is the primary target for extraction (see §7, §11, §12).

## 3. Current API Endpoints

Grouped by owning module. Method + path as matched in `routes.py` (`do_GET`/`do_POST`) and
delegated to `api_*`. This is the **dashboard HTTP API contract** consumed by the frontend
(`frontend/src/services/api.ts`, 863 lines) — **must not break** without a compatibility adapter.

**State / tree** (inline in `routes.py` + `state_sync`/`checkpoint_api`):
`GET /state` (219-666), `GET /memory/<node_id>` (legacy, 191-218), `GET /codefile?path=`
(678-719), `GET /api/models`, `GET /api/active-checkpoint`, `GET /api/experiment-detail`,
`GET /api/resource-metrics`, `GET /api/lineage-decisions/<ckpt>`.

**Checkpoints** (`checkpoint_api`, `checkpoint_lifecycle`, `file_api`, `node_work_api`):
`GET /api/checkpoints`, `GET /api/checkpoint/<id>/{summary,memory,files,filetree,filecontent}`,
`GET /api/checkpoint/<id>/file[/raw]`, `GET /api/checkpoint/<id>/paper.(pdf|tex)`,
`GET /api/checkpoint/<id>/memory_access`, `POST /api/switch-checkpoint`,
`POST /api/delete-checkpoint`, `POST /api/checkpoint/file/{save,delete}`,
`POST /api/checkpoint/compile`, `POST /api/checkpoint/<id>/file/upload`.

**Experiment** (`api_experiment`): `POST /api/launch`, `POST /api/run-stage`, `GET /api/logs` (SSE).

**Settings / workflow** (`api_settings`, `api_workflow`): `GET|POST /api/settings`,
`GET|POST /api/env-keys`, `GET|POST /api/workflow`, `GET /api/workflow/{default,flow}`,
`POST /api/workflow/{flow,skills,disabled-tools}`, `GET /api/skills`, `GET /api/skill/<name>`,
`GET /api/profiles`, `GET /api/rubrics`, `GET /api/scheduler/detect`, `GET /api/slurm/partitions`.

**PaperBench** (`api_paperbench`, `api_paperbench_worker`): `GET /api/paperbench/papers`,
`GET /api/paperbench/arxiv/<id>`, `GET /api/paperbench/papers/<id>/license`,
`POST /api/paperbench/papers/{import,<id>/delete,<id>/metadata}`, `POST /api/paperbench/run`,
`POST /api/paperbench/cost-estimate`, `GET /api/paperbench/run/<jid>[/logs(SSE)|/results|/report|status]`.

**Tools / wizard** (`api_tools`): `POST /api/chat-goal`, `POST /api/config/generate`,
`POST /api/upload`, `POST /api/upload/delete`, `POST /api/ssh/test`.

**Orchestrator** (`api_orchestrator`): `GET /api/sub-experiments[/<id>]`,
`POST /api/sub-experiments/launch`.

**Memory** (`api_memory`): `GET /api/memory/{health,detect}`,
`POST /api/memory/{start-local,stop-local,restart}`.

**EAR** (`ear`): `GET /api/ear/<rid>[/publish-yaml]`, `GET /api/nodes/<rid>/<nid>/report`,
`POST /api/ear/<rid>/curate`, `POST /api/ear/<rid>/publish-yaml`, `POST /api/ear/clone-verify`.

**Publish** (`api_publish`): `GET|POST /api/publish/settings`,
`GET /api/publish/<rid>/{preview,record}`, `POST /api/publish/<rid>[/promote]`.

**Fewshot** (`api_fewshot`): `GET /api/fewshot/<rubric>`,
`POST /api/fewshot/<rubric>/{sync,upload}`, `POST /api/fewshot/<rubric>/<ex>/delete`.

**Process / GPU** (`api_process`): `GET|POST /api/gpu-monitor`, `POST /api/stop`.

**Ollama / container** (`api_ollama` + inline): `GET /api/ollama-resources`,
`GET|POST /api/ollama/*` (reverse proxy via `_ollama_proxy`, `routes.py:673-676`/`1146-1148`),
`GET /api/container/{info,images}`, `POST /api/container/pull` (inline `ContainerConfig` build,
`routes.py:1174-1185`).

There is no OpenAPI/schema description of any of this; the contract lives implicitly in the
if/elif chain and the frontend's typed wrappers.

## 4. Request / Response Contracts

**No schema or validation layer, no DTOs.** Concretely:

- **Requests**: POST bodies arrive as raw `bytes`; each handler does its own
  `json.loads(body)` (e.g. `file_api.py:177` `_api_checkpoint_file_save`,
  `api_experiment._api_launch`). Missing/malformed fields are handled ad hoc per handler.
- **Responses**: each handler returns a plain `dict`, serialized by `_Handler._json`
  (`routes.py:1190-1197`). **Two success/error conventions coexist:**
  - `{"ok": bool, ...}` for launch/run-stage flows.
  - `{"error": str}` for file/checkpoint flows.
- **Status codes are smuggled through the payload**: handlers put `_status` into the returned
  dict and the router pops it — `r.pop("_status", 200)` appears at `routes.py:1047,1049,1051,1057,1089,1167,1169,1171,1173`. This couples HTTP status to the business dict shape.
- **CORS is inconsistent**: `_json` and 8 explicit sites emit `Access-Control-Allow-Origin: *`
  (`routes.py:137,216,710,740,815,905,967,1194`), but some manual responses deliberately omit it
  (e.g. GPU monitor at `routes.py:667-672`), producing wire-behavior drift between endpoints.
- **Frontend mirror hazard** (`frontend/src/services/api.ts`): the generic `get`/`post` helpers
  **throw** on non-2xx (`api.ts:18-32`), but the PaperBench `pbGet`/`pbPost` helpers **never
  throw** and instead surface `{error}` bodies (`api.ts:780-799`). The backend's dual
  `{ok}`/`{error}` convention is the root cause of this split — unifying the response envelope
  (see §13) removes it.

## 5. Frontend Dependencies

The React client is the **primary consumer of the dashboard API** and defines the contract that
this backend refactor must preserve. It is not restructured by this plan.

- Stack: Vite 5 + React 18.3 + TypeScript 5.5, ESM. Runtime deps limited to `react`, `react-dom`,
  `d3` 7.9, `reactflow` 11.11; tests via Vitest 2 + Testing Library + jsdom
  (`frontend/package.json`).
- API client: `frontend/src/services/api.ts` (863 LOC), same-origin (`API_BASE=''`, `api.ts:14`),
  ~90 typed wrappers. **No auth/token/CSRF header anywhere** — every call is unauthenticated
  same-origin.
- Transport: 5s polling of `/state` + `/api/checkpoints` from `context/AppContext.tsx`, plus a
  single WebSocket (`hooks/useWebSocket.ts`) that receives `{"type":"update","data":<tree>}`
  snapshots.
- Typed shapes the backend must keep emitting: `AppState` (`types/index.ts:87-129`, note backend
  adds JS-compat aliases `running`/`pid`/`llm_model`), `Settings` (35 fields,
  `types/index.ts:38-75`), `NodeReport` (`api.ts:124-153`), `MemoryEntry`/`MemoryAccessEvent`
  (`api.ts:53-104`).

Implication for this plan: introducing a DTO/response-envelope layer (see §13) must be **shape-
preserving** — the serialized JSON keys the frontend reads (including `running`/`pid`/`llm_model`
aliases on `/state`) are part of the contract. Any envelope change requires a coordinated
frontend change and a contract test (see §14), so the default is an **adapter that preserves the
current wire shape**.

## 6. Data Sources

The viz backend is a **read-through view over the checkpoint filesystem** plus a few live process
probes. It owns no database. Sources, verified:

- **Node tree** — the canonical BFTS/pipeline tree. Written by the run side
  (`cli/bfts_loop.py` and `pipeline/orchestrator.py:247`) via
  `ari.checkpoint.save_tree_json` / `save_nodes_tree_json`. Read by viz through
  `ari.checkpoint.load_nodes_tree` (search order `tree.json` → `nodes_tree.json` → newest
  non-empty `node_*/tree.json`, `checkpoint.py:86-93`). Viz never writes the tree.
- **Checkpoint directories** — `workspace/checkpoints/<ts_slug>/` (and a coexisting legacy
  root-level `checkpoints/`). Discovery via `checkpoint_finder._checkpoint_search_bases` /
  `_resolve_checkpoint_dir` (`checkpoint_finder.py`). The active checkpoint is held in
  `state._checkpoint_dir` and bound to a project-scoped settings file via
  `state.set_active_checkpoint` → `PathManager.project_settings_path` (`state.py:44-60`).
- **Cost trace** — `cost_trace.jsonl`, tail-parsed inline by the `/state` handler
  (`routes.py:287-298`).
- **Experiment metadata** — `experiment.md` goal extraction (`ui_helpers._extract_goal_from_md`),
  profile/rubric YAML from `ari-core/config/` (read at `routes.py:376,388,401,612`).
- **Settings / env** — project settings YAML (`state.active_settings_path()`) and repo `.env`
  (`state._env_write_path`, `state.py:15`).
- **Live process state** — `state._last_proc.poll()` and `ari.pidfile.check_pid`/`read_pid`
  (`routes.py:561-563,655`), GPU probes via `api_process`, memory/Letta health via `api_memory`.
- **PaperBench jobs** — in-memory only: `api_paperbench._JOBS` dict guarded by `_JOBS_LOCK`
  (`api_paperbench.py:496-497`). **Not persisted** — lost on server restart (see §10/§11).
- **Access log** — `viz_access.jsonl`, written by `_write_access_log` (`routes.py:69-74`).

All checkpoint JSON I/O has a single home in `ari/checkpoint.py`; viz should depend on that (or a
Store adapter over it) rather than re-implementing path search (which it partly still does inline
in `/state`).

## 7. File I/O Usage

The dominant refactoring signal: **file/subprocess/glob I/O is performed directly inside route
and `api_*` handler functions**, not behind a store/adapter. Verified sites:

- **`GET /state` (`routes.py:219-666`)** — the worst offender. It performs dozens of
  `Path.exists()`/`read_text()`/`json.loads()` calls, glob scans (`routes.py:247-266`), YAML
  profile merging (`371-465`, `592-645`), `cost_trace.jsonl` tail-parsing (`287-298`), and reaches
  directly into `state._last_proc.poll()` and `ari.pidfile` (`561-563`). ~450 lines of I/O +
  business logic inside a request handler.
- **Access log write per request** — `_write_access_log` → `viz_access.jsonl` (`routes.py:69-74`).
- **Inline binary file serving with hand-rolled traversal checks**: `/codefile` (`682-719`, guard
  is a substring test `"checkpoints" in str(p)` at `routes.py:692`), `/api/checkpoint/.../file/raw`
  (`797-818`), `/api/checkpoint/<id>/paper.*` (`727-744`).
- **File CRUD in `file_api.py`** — `_api_checkpoint_file_save`/`_upload`/`_delete`/`compile` do
  their own `json.loads`, `.resolve()`, and `relative_to(paper.resolve())` traversal checks
  (`file_api.py:140-142,162-164,186-188,208`). Guard style here is stricter than `/codefile`'s,
  i.e. **two inconsistent traversal-guard implementations coexist**.
- **Per-node walks** — `node_work_api.py` walks work dirs with `_BINARY_EXTENSIONS`/`_SKIP_DIRS`
  filters (`node_work_api.py:26-44`).
- **SSE streaming written inline in the route**: PaperBench logs stream (`routes.py:934-1000`,
  300s deadline + heartbeat) and `/api/logs` (`routes.py:901-908`).
- **Subprocess spawning inside handlers**: `api_experiment._api_run_stage` (Popen ~129-136) and
  `_api_launch` (~782); `api_orchestrator._api_launch_sub_experiment` (Popen ~287);
  `api_process` (Popen; `pkill`/`pgrep`); `api_memory` (`subprocess.run`).
  `_api_run_stage` also inlines `.env` parsing + 15+ `ARI_*` env-var mapping (~44-128) — pure
  business logic embedded in a route helper.
- **Direct internal (non-`ari.public`) imports in handlers**: `ari.paths.PathManager`,
  `ari.checkpoint`, `ari.config.auto_config`, `ari.llm.client.LLMClient`, `ari.clone`,
  `ari.orchestrator.web_provenance`, `ari.container`, `ari.pidfile`, and
  `ari_skill_memory.backends.get_backend` (`routes.py:203-205`). These bypass the stable
  `ari.public.*` surface — an import-boundary concern (see §12, §16).

## 8. BFTS Tree Visualization Flow

End-to-end path from run engine to the Tree page:

1. **Produce** — the BFTS loop (`cli/bfts_loop.py`) and pipeline
   (`pipeline/orchestrator.py:243-297`) write the tree to the active checkpoint via
   `ari.checkpoint.save_tree_json` (`tree.json`) / `save_nodes_tree_json` (`nodes_tree.json`).
2. **Detect** — `state_sync._watcher_thread` (`state_sync.py:68-116`) polls, every 1s, the mtimes
   of `tree.json`, `nodes_tree.json`, and `node_*/tree.json` under `state._checkpoint_dir`. On any
   change it calls the `api_state` facade's `_load_nodes_tree` → `_broadcast`.
3. **Load** — `state_sync._load_nodes_tree` (`state_sync.py:26-36`) delegates to
   `ari.checkpoint.load_nodes_tree(checkpoint_dir)` (search order in §6). Empty-dict trees are
   rejected there.
4. **Push** — `_broadcast` builds `{"type":"update","data":<tree>,"timestamp":...}` and
   `_do_broadcast` fan-outs to all `state._clients` WebSockets via
   `asyncio.run_coroutine_threadsafe` (`state_sync.py:42-63`). Dead sockets are pruned.
5. **Connect-time snapshot** — on WS connect, `websocket._ws_handler` (`websocket.py:20-36`) sends
   one immediate `update` snapshot, then ignores all inbound frames (there is **no client→server
   protocol**; a single `update` message type exists).
6. **Poll fallback** — the frontend also pulls the tree through `GET /state` every 5s
   (`AppContext.tsx`), and via `useWebSocket` prefers the WS `nodes` payload, falling back to
   `state.nodes`.

Refactoring notes: steps 2-4 are already reasonably isolated in `state_sync.py` (KEEP). The
coupling problem is at step 6 — the tree is *also* rebuilt inside the 450-line `/state` handler,
so tree-shaping logic is duplicated between `state_sync` and `routes.py`. A `TreeService`
(consumed by both the WS broadcaster and the `/state` service) removes that duplication.

## 9. Artifact / Trace / Checkpoint Browsing Flow

Two related browsing surfaces, both file-system-backed:

- **Checkpoint browsing** — `GET /api/checkpoints` (list) and
  `GET /api/checkpoint/<id>/{summary,memory,files,filetree,filecontent,file,file/raw}` resolve a
  checkpoint via `checkpoint_finder._resolve_checkpoint_dir`, then read files through `file_api`
  (paper dir CRUD, compile) and `node_work_api` (per-node filetree/filecontent/memory).
  Mutations: `POST /api/switch-checkpoint` and `POST /api/delete-checkpoint`
  (`checkpoint_lifecycle.py`), `POST /api/checkpoint/file/{save,delete}`, `.../file/upload`,
  `.../compile` (`file_api.py`).
- **Artifact / EAR browsing** — `GET /api/ear/<rid>` and `GET /api/nodes/<rid>/<nid>/report`
  (`ear.py`) expose the Experiment Artifact Record; curate/publish-yaml/clone-verify are the
  mutating POSTs. `_synth_repro_report_from_ors` synthesizes a repro report when ORS data is
  present.
- **Trace browsing** — the frontend `DetailPanel` `Trace`/`Code`/`Memory`/`Report`/`Access` tabs
  read node work-dir content served by `node_work_api` (`filetree`/`filecontent`) and memory via
  `_api_checkpoint_memory` / `api_memory._api_memory_access`.

Cross-cutting problem: **three different path-resolution + traversal-guard implementations** serve
these flows — `file_api.relative_to(paper.resolve())`, `node_work_api._resolve_node_work_dir`, and
the inline `/codefile` substring guard (`routes.py:692`). This is the strongest case for a single
`FileService`/`ArtifactStore` (see §12).

## 10. Error Handling

Current behavior is per-handler and inconsistent:

- **No central error middleware.** Each handler decides whether to return `{"error": str}` with a
  smuggled `_status`, return `{"ok": False}`, or let an exception bubble to the `http.server`
  default 500. There is no uniform mapping from exception → HTTP status.
- **Two error envelopes** (`{ok:false}` vs `{error}`) — see §4 — which the frontend must special-
  case (`api.ts` throwing `get/post` vs non-throwing `pbGet/pbPost`).
- **Traversal-guard failures** are handled locally and differently per site (§7, §9); a rejected
  path in `file_api` raises/returns an error dict, while `/codefile`'s weaker substring check can
  admit paths the stricter guard would reject — a **security-relevant inconsistency** (flag
  REVIEW_REQUIRED; do not "fix" silently in a planning phase).
- **SSE loops** (`routes.py:934-1000`, `901-908`) manage their own deadlines/heartbeats and
  swallow disconnects inline; failures mid-stream are not surfaced through the normal envelope.
- **Volatile job state**: PaperBench `_JOBS` is in-memory (`api_paperbench.py:496-497`); a server
  restart drops all run status/logs with no error surfaced to the client — the client just sees a
  missing job.
- **WebSocket**: `_ws_handler` swallows `ConnectionClosed` (`websocket.py:31-34`); broadcast prunes
  dead sockets silently (`state_sync._do_broadcast`).

## 11. Current Problems

Ranked, repository-grounded:

1. **`routes.py` is a 1197-line god-module** with a 137-way `self.path` if/elif dispatch and a
   450-line inline `/state` handler. No route table, no separation of routing / business / I/O.
2. **Handlers do file, glob, YAML, subprocess, and pidfile I/O directly** (§7), so business logic
   is untestable without a live filesystem and processes.
3. **No DTO/validation/response-envelope layer** (§4): raw `json.loads` per handler, dual
   `{ok}`/`{error}` conventions, `_status` smuggling, inconsistent CORS.
4. **Internal-boundary violations**: handlers import `ari.paths`, `ari.checkpoint`, `ari.config`,
   `ari.llm.client`, `ari.container`, `ari.pidfile`, `ari_skill_memory.backends` directly instead
   of `ari.public.*` (`routes.py:203-205` et al.).
5. **Duplicated path resolution + three inconsistent traversal guards** (§7, §9), one of which
   (`/codefile` substring) is weaker than the others — a correctness/security smell.
6. **Mutable module globals** in `state.py` (`_last_proc`, `_running_procs`, `_launch_config`,
   `_clients`, `_sub_experiments`, …) are read/written directly by handlers with no encapsulation;
   PaperBench adds a second ad-hoc in-memory store (`_JOBS`).
7. **Test-seam workaround**: `checkpoint_api`/`ear`/etc. bounce calls back through the `api_state`
   facade purely so `monkeypatch.setattr(api_state, ...)` works (`checkpoint_api.py:26-40`) — a
   Service layer with injectable stores removes this contortion.
8. **Abandoned declarative-router intent**: `api_wizard.WIZARD_ROUTES` is defined but unused
   (`api_wizard.py:30-35`).
9. **Security posture is unenforced and likely unintentional for some endpoints**: no auth on any
   endpoint (including subprocess launch, file write, checkpoint delete, ollama proxy) combined
   with `Access-Control-Allow-Origin: *`. This is REVIEW_REQUIRED — the local-only dashboard model
   may be by design, but it is not documented as such in the code.
10. **Duplicated tree-shaping** between `state_sync` and the inline `/state` handler (§8).

## 12. Proposed Layering

Target shape for the viz backend: **Route (thin) → Service → Adapter → Store → DTO**. This is a
structural, contract-preserving refactor — the HTTP paths, JSON shapes, and WS message type in §3–§5
stay identical; only the internal organization changes.

```
HTTP / WS transport (server.py, http.server + websockets)   [KEEP: entrypoint only]
  │
Route layer            thin: parse path+query+body -> DTO, call Service, envelope the result
  │   (routes.py becomes a registry of route -> handler; NO I/O, NO business logic)
Service layer          StateService, TreeService, CheckpointService, FileService,
  │                    LaunchService, PaperBenchService, SettingsService, EarService, ...
Adapter layer          wrap ari.public.* and (behind a boundary) the few internal ari.* /
  │                    ari_skill_memory calls handlers do today; hide subprocess spawning
Store layer            CheckpointStore (over ari.checkpoint), ArtifactStore/FileStore (single
  │                    traversal-guard impl), JobStore (replaces in-memory _JOBS), ConfigStore
DTO layer              request/response dataclasses; one response envelope + status mapping
```

Concrete moves (all future-phase; none performed here):

- **Realize a route registry.** Replace the `do_GET`/`do_POST` if/elif chain with a declarative
  table (method, path pattern → handler). `api_wizard.WIZARD_ROUTES` (`api_wizard.py:30-35`) is
  the abandoned seed of this — MERGE its intent into a single registry rather than deleting it in
  isolation. Preserve match order semantics so routing stays byte-for-byte compatible (the current
  code is explicitly ordered).
- **Extract `StateService` + `TreeService`** from the 450-line `/state` handler
  (`routes.py:219-666`) and from `state_sync`. `TreeService.build()` becomes the single source for
  both the WS broadcaster and `/state` (removes §8/§10 duplication).
- **Extract `FileService`/`ArtifactStore`** owning the *one* traversal-guard implementation used by
  `file_api`, `node_work_api`, and `/codefile` (§7, §9). This resolves the guard inconsistency
  behind a single tested function.
- **Extract `LaunchService`** for subprocess/env orchestration — `_api_run_stage`, `_api_launch`,
  `_api_launch_sub_experiment`, and the inline `.env`/`ARI_*` mapping (`api_experiment.py:44-128`).
- **Introduce a `JobStore`** for PaperBench (§6/§10) so run status survives semantics are explicit
  (in-memory is fine, but behind an interface with a documented persistence stance).
- **Adapters over internal imports**: route/service code depends only on `ari.public.*`; the
  handful of internal `ari.paths`/`ari.checkpoint`/`ari.container`/`ari.pidfile`/
  `ari_skill_memory` calls move behind adapter modules (§7, item 4 of §11). This is the natural
  place to add `check_import_boundaries.py` enforcement (§16).
- **Encapsulate `state.py` globals** behind accessor objects passed into services (dependency
  injection), which also **replaces the `api_state`-bounce test seam** (§11 item 7) with real
  injectable stores.

Compatibility note: `api_state.py` (facade), `server.py` re-exports of `_Handler`/`_ws_handler`,
and the `api_*` module import paths are **documented/used seams** (tests import them, `server.py`
imports them). Keep them as thin re-export shims during migration; do not rename modules in the
same change that moves logic.

## 13. DTO / Schema Policy

- **Request DTOs**: define per-endpoint request dataclasses (or `TypedDict`) parsed once at the
  Route boundary, replacing scattered `json.loads(body)` + manual field access. Validation errors
  produce a uniform 400 through the envelope.
- **Response envelope**: converge on **one** shape. Because the frontend already depends on the
  current keys (§5), the envelope must be introduced as a **shape-preserving adapter first**:
  services return typed result objects; a serializer maps them to the exact JSON the frontend reads
  today (including `AppState` JS-compat aliases `running`/`pid`/`llm_model`). Only after a
  coordinated frontend change should the raw `{ok}`/`{error}` duality be collapsed.
- **Status handling**: replace the `_status` payload smuggling (`routes.py:1047-1173`) with an
  explicit `(status, body)` return from services, mapped centrally in the envelope serializer.
- **CORS**: centralize the `Access-Control-Allow-Origin` policy in the envelope/serializer so the
  8 explicit sites and the deliberately-omitting ones (`routes.py:667-672`) become consistent (§4).
- **No new serialization framework**: the app is stdlib `http.server` with no Flask/FastAPI
  (verified). DTOs should be plain dataclasses + `json.dumps`, not a new dependency — keep the
  dependency surface unchanged in this refactor.
- **Schema description**: emit a machine-readable description of the endpoint table (path, method,
  request DTO, response DTO) that a `check_viz_api_schema.py` gate (§16) can diff against the
  frontend `api.ts` wrappers to catch drift.

## 14. Contract Test Strategy

The refactor is a large internal move; the safety net is **golden contract tests at the HTTP/WS
boundary** that assert current behavior before and after each phase.

1. **HTTP golden tests** (extend, do not replace): existing suites already exercise the boundary —
   `ari-core/tests/test_server.py` (1844 LOC), `test_gui_errors.py` (1650), `test_workflow_contract.py`
   (1606), `test_wizard.py` (1133). Add a **frozen endpoint-inventory test** that asserts every path
   in §3 still responds with the same status class and top-level JSON keys.
2. **Response-shape snapshots**: capture `/state`, `/api/checkpoints`,
   `/api/checkpoint/<id>/summary`, `/api/ear/<rid>`, and the two SSE endpoints against a fixture
   checkpoint; assert byte-shape stability (esp. the `running`/`pid`/`llm_model` aliases the
   frontend reads).
3. **WS contract test**: assert connect-time snapshot is one `{"type":"update","data":...}` message
   and that a `tree.json` mtime change triggers a broadcast (drives `state_sync._watcher_thread` +
   `_do_broadcast`).
4. **Traversal-guard equivalence test**: once `FileService` unifies the three guards (§9), a
   parametrized test must show the unified guard rejects everything the *strictest* current guard
   rejects (and does not newly admit anything) — this is the correctness gate for that merge.
5. **Frontend-side**: `services/api.ts` typed wrappers + the existing Vitest suites
   (PaperBench `__tests__`) act as the consumer contract; a `check_viz_api_schema.py` gate (§16)
   diffs the backend endpoint table against `api.ts`.
6. **Import-boundary test**: assert route/service modules import only `ari.public.*` (allow-list
   the adapter modules), enforced by `check_import_boundaries.py` (§16).

Each migration PR (§15) must keep suites 1–3 green with **zero fixture edits** — a fixture edit is
the signal that a contract changed and needs an adapter + coordinated frontend change.

## 15. Migration Strategy

Incremental, contract-preserving, one seam at a time. No big-bang rewrite; `http.server` stays.

- **Phase A — freeze the contract.** Land the golden HTTP/WS/inventory tests of §14 *first*, on the
  current code, so every later phase has a red/green oracle. No production code changes.
- **Phase B — route registry.** Introduce the declarative route table behind `_Handler`; port
  branches from the if/elif chain in small batches, preserving match order. MERGE
  `api_wizard.WIZARD_ROUTES` intent; keep the old dispatch reachable until the table covers all 137
  paths, then remove it. Frontend untouched.
- **Phase C — Service extraction (read paths first).** Extract `TreeService`/`StateService` from
  the `/state` handler and `state_sync`; both WS broadcast and `/state` consume the same builder.
  Then `CheckpointService`/`FileService` (unify the traversal guard, §9/§14 suite 4).
- **Phase D — Service extraction (write/side-effect paths).** `LaunchService` (subprocess + env
  mapping), `JobStore` for PaperBench, `SettingsService`. These carry the highest risk; gate behind
  suites 1–2.
- **Phase E — Adapter boundary.** Move internal `ari.*`/`ari_skill_memory` imports behind adapters;
  turn on `check_import_boundaries.py`.
- **Phase F — DTO/envelope.** Introduce request DTOs + one response envelope as a **shape-preserving
  adapter** (§13); collapse the `{ok}`/`{error}` duality and remove `_status` smuggling **only**
  alongside the matching `api.ts` change, in one coordinated PR with suite 5 updated deliberately.

Throughout: `api_state.py` facade, `server.py` re-exports, and `api_*` import paths remain as thin
shims (documented seams). Do not rename `viz/` or any `api_*` module during logic moves. Treat the
open-auth posture (§11 item 9) as a separate REVIEW_REQUIRED decision, not part of the mechanical
refactor.

## 16. Related Subtasks

This plan is the viz-backend slice of the broader ARI refactoring program. It depends on / feeds
the following planned subtasks (subtask docs live under `docs/refactoring/subtasks/`, currently
**empty** on disk — these are to be authored, not implemented here):

- **015** — (viz-backend layering subtask) primary implementation vehicle for §12; Route→Service→
  Adapter→Store→DTO extraction sequenced per §15.
- **020** — `check_complexity.py` gate. `radon` is **not installed** (per environment facts); the
  gate must either vendor a stdlib LOC/branch heuristic or add `radon` deliberately. Targets:
  `routes.py` 1197, `api_experiment.py` 929, `api_paperbench.py` 813.
- **021** — `check_import_boundaries.py` gate enforcing route/service → `ari.public.*` only
  (Phase E). Directly addresses §11 item 4 / §7 internal imports.
- **022** — `check_viz_api_schema.py` gate diffing the backend endpoint table (§3/§13) against
  `frontend/src/services/api.ts` to catch contract drift (§14 suite 5).
- **023** — `check_directory_policy.py` gate (naming/placement); relevant because this plan
  explicitly preserves the `viz/` and `api_*` names during migration and confirms **no `sonfigs/`**
  directory exists (the confusable trio is `config/` code vs `configs/` packaged defaults vs
  top-level `config/` rubric data).
- **024** — `check_public_api_contracts.py` gate protecting `ari.public.*`, the dashboard HTTP API,
  and the WS message type as external contracts (ties to §13/§14).
- **030** — `check_dashboard_ux.py` gate covering frontend-visible concerns adjacent to this
  backend (e.g. raw-JSON `{ } Raw` tab, `/api/env-keys` secret exposure). Backend-side, this plan's
  DTO/redaction policy (`ui_helpers._REDACT_KEYS`) is the coordination point.

These gates are **not** to be built in this planning phase. Note the partial overlap flagged in the
program facts: a proposed `check_docs_source_sync.py` overlaps the existing
`scripts/docs/check_doc_sources.py`; and `check_viz_api_schema.py` (022) is new, with no existing
equivalent under `scripts/`.

## Retirement Condition

This is a **program-level planning document**, not a per-subtask artifact. It
stays live for the duration of the refactoring program and may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources — never on assumption:

1. Every subtask this document governs is marked **DONE** in
   `docs/refactoring/007_subtask_index.md`, **or** this document has been
   explicitly **superseded** by a named replacement (the superseding document
   must reference this file by name).
2. Any conclusions worth keeping have been folded into the permanent
   documentation / architecture.

Before any `git rm`, re-read this document's own conditions and check each one
against the current repository. See the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
