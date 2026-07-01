# Viz / Dashboard API Contract Inventory (Subtask 020)

> **Status:** Read-only inventory artifact produced by subtask
> `docs/refactoring/subtasks/020_inventory_viz_dashboard_api_contracts.md`.
> No runtime code, prompt, config, workflow, frontend, or directory was modified
> to produce this file (see §16 of the subtask). This document is the **frozen
> wire-contract baseline** that subtasks 021, 022, 023, 024, and 030 must
> preserve.
>
> **Repo baseline:** `/home/t-kotama/workplace/ARI`, branch `whole_refactoring`,
> `ari-core` `0.9.0`. Every claim below is grounded in a primary source
> (`file:line`) verified by direct `Read`/`Grep` on 2026-07-01. Where the source
> disagrees with the scaffold in the 020 plan, the source wins and the
> divergence is flagged (see §6, Finding F2).
>
> **Companions (cross-referenced, not edited):**
> `docs/refactoring/008_viz_dashboard_refactoring_plan.md` (backend structure),
> `docs/refactoring/014_dashboard_ux_refactoring_plan.md` (frontend UX),
> `docs/refactoring/010_contract_preservation_policy.md` §4/§5 (contract tags).
> Machine-readable twin for subtask 030: `viz_api_contract_inventory.json`
> (sibling file).

---

## 1. Architecture summary (grounded)

The dashboard backend is a Python **stdlib `http.server`** app — no
Flask/FastAPI/aiohttp. Key facts:

- `server.py` — `_DualStackServer(ThreadingHTTPServer)` (`server.py:82`), IPv6 bind
  with IPv4 fallback (`server.py:148-151`). `_main()` (`server.py:159`) starts
  three threads: filesystem watcher (`_watcher_thread`), HTTP server
  (`_http_thread` → `_Handler`), and the asyncio WebSocket loop
  (`ws_serve(_ws_handler, "", ws_port)` where **`ws_port = port + 1`**,
  `server.py:172,178`). The console banner advertises `ws://localhost:{ws_port}/ws`
  (`server.py:175`), but `ws_serve` binds all paths.
- `routes.py` (1197 LOC) — a single `BaseHTTPRequestHandler` subclass `_Handler`
  (`routes.py:77`, `protocol_version = "HTTP/1.1"`). Dispatch is a **hand-rolled
  if/elif chain** on `self.path`: `do_GET` (`routes.py:144`), `do_POST`
  (`routes.py:1028`), `do_OPTIONS` (`routes.py:127`). There is **no route table**.
  The only response serializer is `_json(self, data, status=200)`
  (`routes.py:1190-1197`). Per-request access log: `_write_access_log` →
  `viz_access.jsonl` (`routes.py:69-74`, called from `log_request`
  `routes.py:87-104`).
- `websocket.py` (36 LOC) — single `_ws_handler`; on connect pushes one
  `{"type":"update","data":<tree>,"timestamp":...}` snapshot (`websocket.py:24-29`),
  then ignores inbound frames (`websocket.py:30-31`). `ConnectionClosed` swallowed.
- `state_sync.py` — `_watcher_thread` (`state_sync.py:68`) polls, every 1s, the
  mtimes of `tree.json`, `nodes_tree.json`, and `node_*/tree.json` under
  `_st._checkpoint_dir`; on change → `_load_nodes_tree()` → `_broadcast()` →
  `_do_broadcast()` fan-out to `_st._clients` (`state_sync.py:42-63,68-116`).
- `api_state.py` (76 LOC) is a **thin re-export facade** (`api_state.py:24-75`)
  forwarding to `checkpoint_finder`, `state_sync`, `checkpoint_api`, `ear`,
  `file_api`, `checkpoint_lifecycle`, `node_work_api`. The **concrete owner** is
  recorded in the tables below, never the facade.
- `state.py` (79 LOC) holds mutable module globals used as an implicit contract:
  `_checkpoint_dir`, `_last_proc`, `_running_procs`, `_launch_config`,
  `_launch_llm_model`, `_launch_llm_provider`, `_last_experiment_md`,
  `_last_log_fh`/`_last_log_path`, `_clients`, `_loop`, `_sub_experiments`,
  `_gpu_monitor_proc`, `_staging_dir`, `_settings_path`, `_env_write_path`,
  `_ari_root` (`state.py:12-31`).

### 1.1 Branch-count self-check (§8.12, §13.1)

Verified by `grep`/`awk` on `routes.py`:

| Metric | Count | How measured |
|---|---|---|
| Total `self.path` references | **137** | `grep -c "self.path" routes.py` |
| `self.path` refs inside `do_GET` body (L144–1027) | **86** | matches the "~86 GET" figure in `010:246`/master `§5.5` |
| `self.path` refs inside `do_POST` body (L1028–1188) | **51** | matches the "~51 POST" figure |
| Top-level GET dispatch branches (`if/elif … self.path`) | **56** | distinct endpoint decisions in `do_GET` (incl. 1 `re.match`, `routes.py:723`) |
| Top-level POST dispatch branches | **41** | distinct endpoint decisions in `do_POST` (incl. 1 `re.match`, `routes.py:1159`) |
| `_status` pop sites in router | **9** | `routes.py:1047,1049,1051,1057,1089,1167,1169,1171,1173` |
| Inline `Access-Control-Allow-Origin` sites | **8** | `routes.py:137,216,710,740,815,905,967,1194` |

"~86 GET / ~51 POST" (010 §4, master §5.5) counts **`self.path` references**, not
endpoints; the distinct endpoint dispatch branches are **56 GET + 41 POST**
(+ `do_OPTIONS` + 1 WebSocket). Both figures are reproduced above so downstream
checkers can pick either definition. No branch is omitted from §3/§4 below.

---

## 2. Legend

- **Convention** — the response envelope actually returned by the owner:
  `{ok}` = `{"ok": bool, ...}`; `{error}` = bare `{"error": str}` envelope;
  `payload` = a bare data dict/list with no ok/error wrapper (errors, if any,
  ride inside the payload's own fields); `bytes/stream` = raw non-JSON body.
- **Status** — `200` (router default via `_json`); `_status:NNN` = handler sets a
  `_status` key that the router pops (`r.pop("_status", 200)`); `inline` = handler
  writes `send_response(code)` directly.
- **CORS** — `_json *` = uniform `Access-Control-Allow-Origin: *` via `_json`
  (`routes.py:1194`); `inline *` = raw response that sets the header;
  `inline none` = raw response that **omits** the header (wire difference).
- **FE binding** — `services/api.ts` wrapper name + def line, and its regime:
  `get`/`post` **throw** on non-2xx (`api.ts:18-32`); `pbGet`/`pbPost` **never
  throw** and read `{error}` from HTTP-200 bodies (`api.ts:787-799`). `direct` =
  consumed by a component via `fetch`/`EventSource`/`<img>`/`<a href>`, not a
  wrapper. `— none` = no confirmed frontend consumer (drift; see §6).
- **Class** — downstream recommendation only (KEEP / ADAPT / MERGE /
  MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED). 020 changes nothing.

---

## 3. GET endpoints (`_Handler.do_GET`, `routes.py:144-1026`)

| # | Path (literal + param form) | Owner `module.func` (def) | Request | Response (convention) | Status | CORS | Side effects / WS | FE binding (regime) | Class |
|---|---|---|---|---|---|---|---|---|---|
| G1 | `GET /logo.png`, `/logo` | inline `do_GET` (`routes.py:145`) | none | image/png bytes / 404 (`bytes`) | inline 200/404 | inline none | reads `docs/assets/logo.png` | direct (`<img>`) | KEEP |
| G2 | `GET /`, `/index.html` | inline `_serve_spa_index` (`routes.py:109,163`) | none | text/html (`bytes`) | inline 200 | inline none | reads `static/dist/index.html`→`dashboard.html` | direct (page load) | KEEP |
| G3 | `GET /static/<path>` | inline `do_GET` (`routes.py:166`) | none | asset bytes / 404 (`bytes`) | inline 200/404 | inline none | reads `viz/static/<path>` | direct (asset) | KEEP |
| G4 | `GET /memory/<node_id>` (legacy) | inline `do_GET` (`routes.py:191`) | none (path `node_id`) | `{entries:[{text,metadata}]}` / `{entries:[],error}` (`payload`) | inline 200 | **inline `*`** (`:216`) | `PathManager.set_checkpoint_dir_env`; `get_backend(...).get_node_memory` | — none (no consumer) | MOVE_TO_LEGACY |
| G5 | `GET /state` | inline builder (`routes.py:219-666`, ~450 L) | none | `AppState` bare dict: `nodes, checkpoint_id/_path, running_pid, is_running, exit_code, running, pid, status_label, current_phase, phase_flags, has_paper/pdf/review/repro, node_count, actual_models, llm_model_actual, llm_model, experiment_config, cost (CostSummary object), best_nodes, all_metric_keys, summary_stats, typed_split_sources, ideas, …` (`payload`) | inline 200 (`:662`) | **inline none** (`:662-666`, no ACAO header) | reads `tree.json`/`nodes_tree.json`, `cost_trace.jsonl` tail (`:287-298`), `cost_summary.json`, `idea.json`, `science_data.json`, `results.json`, `experiment.md`, `workflow.yaml`, `launch_config.json`, profile/`default.yaml` (`:376,388,401,612`); reads `_st._last_proc/_checkpoint_dir/_launch_*`; `ari.pidfile.check_pid/read_pid` (`:561-563,655`); **mutates** `_st._last_experiment_md=None` on exited proc (`:224`). **WS: same tree mirrored in `update`** | `fetchState` (`api.ts:36`, get/throw); AppContext 5s poll | ADAPT |
| G6 | `GET /api/gpu-monitor` | `api_process._api_gpu_monitor_status` (`api_process.py:31`) | none | `{running,pid,log,ollama_host}` (`payload`) | inline 200 (`:672`) | **inline none** (`:668-672`) | reads `~/ARI/logs/gpu_monitor.log`, `_st._settings_path` | `fetchGpuMonitor` (`api.ts:575`, get/throw) | ADAPT / REVIEW |
| G7 | `GET /api/ollama/<*>` | `api_ollama._ollama_proxy(self)` (`api_ollama.py:43`) | forwards method/path/body/headers | upstream body (`stream`) / 502 `{error}` | inline (upstream) | inline `*` (proxy) | reverse-proxy `http.client` → `ollama_host` (timeout 600) | direct (external ollama clients) | KEEP / REVIEW |
| G8 | `GET /codefile?path=<p>` | inline `do_GET` (`routes.py:678-719`) | query `path` | file bytes / 404 / 500 (`bytes`) | inline 200/404/500 | **inline `*` on 200** (`:710`); none on 404/500 | reads arbitrary file; **weak traversal guard** `"checkpoints" in str(p)` (`:692`); 20 MB cap | direct (`EarSection.tsx:61,418`, `PaperWorkspace.tsx:77`) | ADAPT / REVIEW |
| G9 | `GET /api/models` | `checkpoint_api._api_models` (`checkpoint_api.py:63`) | none | `{providers:[{id,name,models}]}` (`payload`) | 200 | `_json *` | none (hardcoded constant) | `fetchModels` (`api.ts:740`, get/throw) | KEEP |
| G10 | `GET /api/checkpoint/<id>/paper.(pdf\|tex)` (`re.match`, `:723`) | inline `do_GET` (`routes.py:723-745`) | path `id`, `ext` | application/pdf or text/plain bytes / 404 (`bytes`) | inline 200/404 | **inline `*` on 200** (`:740`) | reads `full_paper.{ext}` across search paths | direct (`PaperWorkspace.tsx:319,363`) | KEEP / ADAPT |
| G11 | `GET /api/env-keys` | `api_settings._api_get_env_keys` (`api_settings.py:40`) | none | `{keys:{…secret values…},source:{}}` (`payload`) | 200 | `_json *` | reads `.env` candidates; falls back to `os.environ` | `fetchEnvKeys` (`api.ts:382`, get/throw) | REVIEW_REQUIRED (secret exposure) |
| G12 | `GET /api/ollama-resources` | `api_ollama._api_ollama_resources` (`api_ollama.py:14`) | none | `{gpus,models,has_gpu}` (`payload`) | 200 | `_json *` | `subprocess nvidia-smi` (timeout 5); `urllib` → ollama `/api/tags` | `fetchOllamaResources` (`api.ts:571`, get/throw) | ADAPT |
| G13 | `GET /api/checkpoints` | `checkpoint_api._api_checkpoints` (`checkpoint_api.py:78`) | none | bare list `[{id,path,status,node_count,review_score,best_metric(always null),mtime}]` (`payload`) | 200 | `_json *` | reads per-dir `tree/nodes_tree/review_report.json`; `_check_pid_alive`; **mutates `_st._running_procs`** (prunes finished/stale) | `fetchCheckpoints` (`api.ts:45`, get/throw); AppContext 5s poll | ADAPT |
| G14 | `GET /api/rubrics` | `api_settings._api_rubrics` (`api_settings.py:523`) | none | bare list `[{id,venue,domain,version,closed_review,path}]` (`payload`) | 200 | `_json *` | reads `config/reviewer_rubrics/*.yaml` | `fetchRubrics` (`api.ts:426`, get/throw) | KEEP |
| G15 | `GET /api/fewshot/<rubric>` | `api_fewshot._api_fewshot_list` (`api_fewshot.py:50`) | path `rubric_id` | `{rubric_id,count,examples[]}` / `{error:"invalid rubric_id"}` (`payload`) | 200 | `_json *` | reads `fewshot_examples/<rid>/` | `fetchFewshot` (`api.ts:445`, get/throw) | KEEP |
| G16 | `GET /api/checkpoint/<id>/summary` | `checkpoint_api._api_checkpoint_summary` (`checkpoint_api.py:195`) | path `id` | `{id,path,nodes_tree,review_report,science_data,figures_manifest,reproducibility_report,ors_*,vlm_review,paper_tex,has_pdf}` / `{error:"not found"}` (`payload`) | 200 | `_json *` | reads many `*.json` + `full_paper.tex`; `_synth_repro_report_from_ors` | `fetchCheckpointSummary` (`api.ts:49`, get/throw); **pinned by `test_api_schema_contract.py`** | ADAPT |
| G17 | `GET /api/checkpoint/<id>/memory` | `node_work_api._api_checkpoint_memory` (`node_work_api.py:180`) | path `id` | `{id,entries,by_node,global,error,count}` / `{error:"checkpoint not found"}` (`payload`) | 200 | `_json *` | `PathManager.set_checkpoint_dir_env` (env mutation); `get_backend(...).list_all_nodes/list_react_entries` | `fetchCheckpointMemory` (`api.ts:72`, get/throw) | ADAPT |
| G18 | `GET /api/checkpoint/<id>/memory_access?node_id&op&limit` | `api_memory._api_memory_access` (`api_memory.py:150`) | path `id`; query `node_id,op(=all),limit(=200)` | `{node_id,writes,reads,read_by_entry}` / `{…,error}` (`payload`) | 200 | `_json *` | reads `memory_access.jsonl` | `fetchMemoryAccess` (`api.ts:94`, get/throw) | ADAPT |
| G19 | `GET /api/memory/health` | `api_memory._api_memory_health` (`api_memory.py:27`) | none | `{status,latency_ms,namespace,server_version,detected_deployment,reason?,error?}` (`payload`) | 200 | `_json *` | `PathManager.set_checkpoint_dir_env`; Letta `backend.health()` (network); `shutil.which` | `fetchMemoryHealth` (`api.ts:398`, get/throw) | ADAPT |
| G20 | `GET /api/memory/detect` | `api_memory._api_memory_detect` (`api_memory.py:61`) | none | `{recommended,available,reasons}` (`payload`) | 200 | `_json *` | `shutil.which` probes | — none (drift) | REVIEW_REQUIRED |
| G21 | `GET /api/checkpoint/<id>/files` | `file_api._api_checkpoint_files` (`file_api.py:106`) | path `id` | `{id,path,files[{name,size,editable,ext,abs_path}]}` / `{error}` (`payload`) | 200 | `_json *` | **`_ensure_paper_dir` mkdir+`copy2` seeds `paper/` — WRITE on GET**; reads tree | `fetchCheckpointFiles` (`api.ts:630`, get/throw) | ADAPT / REVIEW |
| G22a | `GET /api/checkpoint/<id>/file?name=<f>` | `file_api._api_checkpoint_file_read` (`file_api.py:135`) | path `id`; query `name` | `{name,content}` / `{error}` (`payload`) | 200 | `_json *` | seeds `paper/`; reads file (5 MB cap) | `fetchCheckpointFileContent` (`api.ts:636`, get/throw) | ADAPT |
| G22b | `GET /api/checkpoint/<id>/file/raw?name=<f>` | inline via `file_api._resolve_paper_file` (`routes.py:797-818`, `file_api.py:157`) | path `id`; query `name` | binary bytes / 404 (`bytes`) | inline 200/404 | **inline `*` on 200** (`:815`) | seeds `paper/`; reads file (20 MB cap) | — none (drift) | ADAPT / REVIEW |
| G23 | `GET /api/checkpoint/<id>/filetree?node_id=` | `node_work_api._api_checkpoint_filetree` (`node_work_api.py:87`) | path `id`; query `node_id` | `{id,path,tree[]}` / `{error}` (`payload`) | 200 | `_json *` | reads dir tree (`_resolve_node_work_dir`) | `fetchCheckpointFiletree` (`api.ts:656`, get/throw) | ADAPT |
| G24 | `GET /api/checkpoint/<id>/filecontent?path&node_id` | `node_work_api._api_checkpoint_filecontent` (`node_work_api.py:149`) | path `id`; query `path,node_id` | `{name,content}` / `{error}` (`payload`) | 200 | `_json *` | reads file (5 MB cap; binary reject) | `fetchCheckpointFilecontent` (`api.ts:643`, get/throw) | ADAPT |
| G25 | `GET /api/ear/<rid>/publish-yaml` | `ear._api_ear_publish_yaml_get` (`ear.py:248`) | path `rid` | `{exists,path,text,data}` / `{error}` (`payload`) | 200 | `_json *` | reads `ear/publish.yaml` | `fetchPublishYaml` (`api.ts:243`, get/throw) | ADAPT |
| G26 | `GET /api/ear/<rid>` | `ear._api_ear` (`ear.py:47`) | path `rid` | `{run_id,ear_dir,files,readme,results,file_count,publish_yaml_present,published}` / `{error}` (`payload`) | 200 | `_json *` | reads `ear/` tree, `README.md`/`RESULTS.md`/`manifest.lock` | `fetchEAR` (`api.ts:201`, get/throw) | ADAPT |
| G27 | `GET /api/nodes/<rid>/<nid>/report` | `ear._api_node_report` (`ear.py:134`) | path `rid,nid` | `{run_id,node_id,report}` / `{error}` (`payload`) | 200 | `_json *` | reads `node_report.json` | `fetchNodeReport` (`api.ts:162`, get/throw) | ADAPT |
| G28 | `GET /api/settings` | `api_settings._api_get_settings` (`api_settings.py:119`) | none | bare settings dict (~40 keys incl. nested `ors`) (`payload`) | 200 | `_json *` | reads `workflow.yaml` + project `settings.json` | `fetchSettings` (`api.ts:372`, get/throw); **pinned by `test_api_schema_contract.py`** | ADAPT |
| G29 | `GET /api/publish/settings` | `api_publish._api_publish_settings_get` (`api_publish.py:81`) | none | settings dict / default dict / `{error}` (`payload`) | 200 | `_json *` | reads `$ARI_PUBLISH_SETTINGS` else **`~/.ari/publish.yaml`** (DeprecationWarning) | `fetchPublishSettings` (`api.ts:334`, get/throw) | ADAPT / REVIEW |
| G30 | `GET /api/publish/<rid>/preview` | `api_publish._api_publish_preview` (`api_publish.py:93`) | path `rid` | `{run_id,ear_published_dir,bundle_sha256,files,file_count,visibility,license,publish}` / `{error,needs_curate?}` (`payload`) | 200 | `_json *` | reads `ear_published/manifest.lock` | `previewPublish` (`api.ts:340`, get/throw) | ADAPT |
| G31 | `GET /api/publish/<rid>/record` | `api_publish._api_publish_record` (`api_publish.py:180`) | path `rid` | `{published:bool,…}` / `{error}` (`payload`) | 200 | `_json *` | reads `publish_record.json` | `fetchPublishRecord` (`api.ts:349`, get/throw) | ADAPT |
| G32 | `GET /api/profiles` | `api_settings._api_profiles` (`api_settings.py:505`) | none | bare list `[{name,path}]` (`payload`) | 200 | `_json *` | globs `config/profiles/*.yaml` | `fetchProfiles` (`api.ts:413`, get/throw) | KEEP |
| G33 | `GET /api/upload` | inline stub (`routes.py:869`) | none | `{error:"use POST /api/upload"}` (`{error}`) | 200 | `_json *` | none | — none | DELETE_CANDIDATE |
| G34 | `GET /api/experiment-detail` | `ui_helpers._build_experiment_detail_config` (`ui_helpers.py:64`) | none | `{experiment_detail_config:str}` (`payload`) | 200 | `_json *` | reads `default.yaml`/`workflow.yaml`/`launch_config.json`; redacts `_REDACT_KEYS` | `fetchExperimentDetail` (`api.ts:40`, get/throw) | KEEP / ADAPT |
| G35 | `GET /api/active-checkpoint` | inline (`routes.py:874`) | none | `{path,id}` (`payload`) | 200 | `_json *` | reads `_st._checkpoint_dir` | `fetchActiveCheckpoint` (`api.ts:366`, get/throw) | KEEP |
| G36 | `GET /api/workflow` | `api_settings._api_get_workflow` (`api_settings.py:235`) | none | `{ok,workflow,path,skill_mcp,disabled_tools,bfts_pipeline,paper_pipeline,full_pipeline}` / `{ok:False,error}` (`{ok}`) | 200 | `_json *` | reads `workflow.yaml` + each `ari-skill-*/mcp.json`/`server.py`; **rglob `ari-core/ari/**/*.py`** | `fetchWorkflow` (`api.ts:487`, get/throw) | ADAPT |
| G37 | `GET /api/skill/<name>` | `api_settings._api_skill_detail` (`api_settings.py:428`) | path `name` | `{ok,name,dir,files}` / `{ok:False,error}` (`{ok}`) | 200 | `_json *` | reads skill doc/src files | `fetchSkillDetail` (`api.ts:483`, get/throw) | KEEP / ADAPT |
| G38 | `GET /api/skills` | `api_settings._api_skills` (`api_settings.py:466`) | none | bare list of skill dicts (`payload`) | 200 | `_json *` | reads each `ari-skill-*/skill.yaml` | `fetchSkills` (`api.ts:479`, get/throw) | KEEP |
| G39 | `GET /api/resource-metrics` | `ui_helpers._collect_resource_metrics` (`ui_helpers.py:139`) | none | `{process_count,memory_rss_mb,cpu_load_1m/5m/15m,cpu_count,experiment_pid,timestamp}` (`payload`) | 200 | `_json *` | reads `/proc/<pid>`; `os.getloadavg` | `fetchResourceMetrics` (`api.ts:590`, get/throw) | KEEP |
| G40 | `GET /api/container/info` | inline `ari.container.get_container_info` (`routes.py:886`) | none | container info dict (`payload`) | 200 | `_json *` | `ari.container` probe | `fetchContainerInfo` (`api.ts:596`, get/throw) | KEEP |
| G41 | `GET /api/container/images` | inline `ari.container.list_images` (`routes.py:889`) | none | `{images:[…]}` (`payload`) | 200 | `_json *` | `ari.container` probe | `fetchContainerImages` (`api.ts:609`, get/throw) | KEEP |
| G42 | `GET /api/workflow/default` | `api_workflow._api_get_default_workflow` (`api_workflow.py:446`) | none | `{ok,flow,workflow,path}` / `{ok:False,error}` (`{ok}`) | 200 | `_json *` | reads default `config/workflow.yaml` | `fetchWorkflowDefault` (`api.ts:722`, get/throw) | ADAPT |
| G43 | `GET /api/workflow/flow` | `api_workflow._api_get_workflow_flow` (`api_workflow.py:271`) | none | `{ok,flow,path}` / `{ok:False,error}` (`{ok}`) | 200 | `_json *` | reads `workflow.yaml` | `fetchWorkflowFlow` (`api.ts:714`, get/throw) | ADAPT |
| G44 | `GET /api/scheduler/detect` | `api_settings._api_detect_scheduler` (`api_settings.py:515`) | none | env summary dict / `{error,scheduler:"none",…}` (`payload`) | 200 | `_json *` | `ari.env_detect.get_environment_summary` (may probe scheduler) | `detectScheduler` (`api.ts:561`, get/throw) | ADAPT |
| G45 | `GET /api/slurm/partitions` | inline via `_api_detect_scheduler` (`routes.py:898`) | none | bare list `partitions` (`payload`) | 200 | `_json *` | as G44 | `fetchPartitions` (`api.ts:565`, get/throw) | KEEP |
| G46 | `GET /api/logs` (SSE) | inline `api_experiment._api_logs_sse(self.wfile)` (`routes.py:901-908`, `api_experiment.py:808`) | none | `text/event-stream` `data:{"msg":…}` (`stream`) | inline 200 (`:902`) | **inline `*`** (`:905`) | tails `ari_run_*.log` + `cost_trace.jsonl`; `Connection: close` | `direct` `fetch('/api/logs')` (`MonitorPage.tsx:163`) | ADAPT |
| G47 | `GET /api/sub-experiments` | `api_orchestrator._api_list_sub_experiments` (`api_orchestrator.py:60`) | none | `{sub_experiments:[…]}` (`payload`) | 200 | `_json *` | reads `meta.json` under checkpoints; **rebuilds `_st._sub_experiments`** | `fetchSubExperiments` (`api.ts:761`, get/throw) | ADAPT |
| G48 | `GET /api/sub-experiments/<rid>` | `api_orchestrator._api_get_sub_experiment` (`api_orchestrator.py:79`) | path `rid` | bare meta dict / `{error}` (`payload`) | 200 | `_json *` | reads `meta.json`; **writes `_st._sub_experiments`** | `fetchSubExperiment` (`api.ts:765`, get/throw) | ADAPT |
| G49 | `GET /api/lineage-decisions/<ckpt>` | `checkpoint_api._api_lineage_decisions` (`checkpoint_api.py:301`) | path `ckpt` | `{records,n}` / `{error,records:[],n:0}` (`payload`) | 200 | `_json *` | reads `lineage_decisions.jsonl` | — none (component inline fetch, unverified) | ADAPT |
| G50 | `GET /api/paperbench/papers` | `api_paperbench._api_list_papers` (`api_paperbench.py:335`) | none | `{papers:[…]}` (`payload`) | 200 | `_json *` | reads `manifest.jsonl` | `fetchPaperbenchPapers` (`api.ts:803`, **pbGet/no-throw**) | KEEP / ADAPT |
| G51 | `GET /api/paperbench/arxiv/<id>` | `api_paperbench._api_arxiv_fetch` (`api_paperbench.py:262`) | path `arxiv_id` | `{arxiv_id,title,authors,year,license,…}` / `{error}` (`payload`) | 200 | `_json *` | **network** `urllib` → arxiv API (timeout 6) | `fetchArxivMetadata` (`api.ts:834`, **pbGet/no-throw**) | ADAPT |
| G52 | `GET /api/paperbench/papers/<id>/license` | `api_paperbench._api_paper_license` (`api_paperbench.py:484`) | path `paper_id` | license dict / `{error,paper_id}` (`payload`) | 200 | `_json *` | reads `manifest.jsonl` | — none (drift) | REVIEW_REQUIRED |
| G53 | `GET /api/paperbench/run/<jid>/logs` (SSE) | inline (`routes.py:934-1000`) via `_job_snapshot`/`_job_logs_since` (`api_paperbench.py:500,552`) | path `jid`; query `since`; header `Last-Event-ID` | `text/event-stream` `event:log/done` / 404 `{error:"job not found"}` (`stream`) | inline 200/404 (300 s deadline + heartbeat) | **inline `*` on 200** (`:967`); none on 404 (`:959`) | reads **restart-losing `_JOBS`** | `direct` `EventSource` (`ResultsView.tsx:100`) | ADAPT |
| G54 | `GET /api/paperbench/run/<jid>/results` | `api_paperbench._api_run_results` (`api_paperbench.py:682`) | path `jid` | `snap["results"]` dict / `{error,status?}` (`payload`) | 200 | `_json *` | reads `_JOBS` | `fetchPaperbenchRunResults` (`api.ts:853`, **pbGet/no-throw**) | ADAPT |
| G55 | `GET /api/paperbench/run/<jid>/report?languages&formats` | `api_paperbench._api_run_report` (`api_paperbench.py:707`) | path `jid`; query `languages,formats,output_root` | `{…,download_urls,job_id}` / `{error,…}` (`payload`) | 200 | `_json *` | reads `_JOBS`; **dynamically `exec_module` `report/scripts/paperbench_report.py`**; renders reports to disk | — none via GET (FE uses **POST**; see F6a drift) | ADAPT / REVIEW |
| G56 | `GET /api/paperbench/run/<jid>` (catch-all) | `api_paperbench._api_run_status` (`api_paperbench.py:672`) | path `jid` | full job snapshot dict / `{error,job_id}` (`payload`) | 200 | `_json *` | reads `_JOBS` | `fetchPaperbenchRun` (`api.ts:849`, **pbGet/no-throw**) | ADAPT |
| G57 | `else` fallback (`routes.py:1020-1026`) | inline `_serve_spa_index` or 404 | none | html / 404 | inline | inline none | non-`/api/` → SPA index; `/api/…` → 404 | direct (client-side routing) | KEEP |

---

## 4. POST endpoints (`_Handler.do_POST`, `routes.py:1028-1188`)

`do_POST` reads the body once (`routes.py:1034`, 10 MB cap → 413 at `:1030-1033`),
then dispatches. All `_json`-wrapped responses carry `Access-Control-Allow-Origin:
*` (`routes.py:1194`).

| # | Path | Owner `module.func` (def) | Request body | Response (convention) | Status | Side effects / WS | FE binding (regime) | Class |
|---|---|---|---|---|---|---|---|---|
| P1 | `POST /api/settings` | `api_settings._api_save_settings` (`api_settings.py:202`) | full settings dict (`api_key`/`llm_api_key` popped) | `{ok:True}` / `{ok:False,error,_status:400}` (`{ok}`) | **handler sets `_status:400` but router does NOT pop it** (`routes.py:1036`) → HTTP **200**, `_status` leaks into body (**F7**) | writes project `settings.json` + `.env`; `os.environ` | `saveSettings` (`api.ts:376`, post/throw) | ADAPT / REVIEW |
| P2 | `POST /api/memory/start-local` | `api_memory._api_memory_start_local` (`api_memory.py:82`) | `{path}` | `{ok,path,stdout}` / `{ok:False,error}` (`{ok}`) | 200 | `subprocess.run` docker-compose up / start_singularity.sh / start_pip.sh (timeout 300) | — none (drift) | ADAPT / REVIEW |
| P3 | `POST /api/memory/stop-local` | `api_memory._api_memory_stop_local` (`api_memory.py:111`) | none | `{ok,attempts}` (`{ok}`) | 200 | `subprocess.run` docker down / instance stop / `pkill -f "letta server"` | — none (drift) | ADAPT / REVIEW |
| P4 | `POST /api/memory/restart` | `api_memory._api_memory_restart` (`api_memory.py:130`) | `{path}` | `{ok,stop,start}` (`{ok}`) | 200 | stop + `sleep 2` + start (subprocess set above) | `restartLetta` (`api.ts:402`, post/throw) | ADAPT |
| P5 | `POST /api/launch` | `api_experiment._api_launch` (`api_experiment.py:144`) | ~50 keys: `profile,experiment_md,max_nodes,max_depth,max_react,timeout_min,workers,frontier_score,composite,axis_mode,hpc_*,partition,rubric_id,fewshot_mode,num_reviews_ensemble,num_reflections,language,retrieval_backend,phase_models,container_*,ors{…},llm_model/model,llm_provider,include_*,max_recursion_depth,parent_run_id,recursion_depth,vir_sci_*` | `{ok:True,pid,checkpoint_root,checkpoint_path}` / `{ok:False,error}` (`{ok}`) | router pops `_status` (`:1047`) but handler **never sets it** → always 200 (**F7**) | **Popen** `python3 -m ari.cli run <cfg> [--profile p]` (`api_experiment.py:782`); writes `experiment.md`/`launch_config.json`/`workflow.yaml`/`meta.json`/log; `sinfo` probes; ~40 `ARI_*` env mappings; **mutates** `_last_proc,_running_procs,_launch_*,_last_log_fh/path,_last_experiment_md,_staging_dir`, `set_active_checkpoint`, `set_sub_experiment` | `launchExperiment` (`api.ts:510`, post/throw) | ADAPT |
| P6 | `POST /api/sub-experiments/launch` | `api_orchestrator._api_launch_sub_experiment` (`api_orchestrator.py:98`) | `{experiment_md,parent_run_id,recursion_depth,max_recursion_depth,dry_run,inherit_idea_index}` | `{ok:True,run_id,pid,…}` / `{ok:False,error,…}` (`{ok}`) | router pops `_status` (`:1049`) but handler **never sets it** → always 200 (**F7**) | **Popen** `python3 -m ari.cli run <ckpt>/experiment.md` (`start_new_session`); writes `meta.json`/`experiment.md`/`idea.json`/`orchestrator.log`; **mutates `_st._sub_experiments`** | `launchSubExperiment` (`api.ts:769`, post/throw) | ADAPT |
| P7 | `POST /api/run-stage` | `api_experiment._api_run_stage` (`api_experiment.py:18`) | `{stage}` (resume/paper/review) | `{ok:True,pid,stage,cmd}` / `{ok:False,error}` (`{ok}`) | router pops `_status` (`:1051`) but handler **never sets it** → always 200 (**F7**) | **Popen** `python3 -m ari.cli resume\|paper <ckpt>`; `.env` parse + `ARI_*` mapping; touches `.pipeline_started`; **mutates `_last_proc,_running_procs`** | `runStage` (`api.ts:500`, post/throw) | ADAPT |
| P8 | `POST /api/config/generate` | `api_tools._api_generate_config` (`api_tools.py:104`) | `{goal}` | `{content}` / `{error}` (`payload`) | 200 | **LLM call** `LLMClient.complete`; loads `prompts/viz/wizard_generate_config.md` | `generateConfig` (`api.ts:524`, post/throw) | ADAPT |
| P9 | `POST /api/chat-goal` | `api_tools._api_chat_goal` (`api_tools.py:15`) | `{messages,context_md}` | `{reply,ready,md}` / `{error}` (`payload`) | 200 | **LLM call** `litellm.completion`; reads `.env`; loads `prompts/viz/wizard_chat_goal.md` | `chatGoal` (`api.ts:518`, post/throw) | ADAPT |
| P10 | `POST /api/upload` | `api_tools._api_upload_file(headers,body)` (`api_tools.py:144`) | headers `X-Filename`,`Content-Type`; raw body bytes | `{ok:True,path,filename}` / `{error}` (`{ok}`) | router pops `_status` (`:1057`) but handler **never sets it** → always 200 (**F7**) | writes `uploads/<file>`; may auto-`new_staging_dir` + `set_active_checkpoint` + set `_staging_dir` | `uploadFile` (`api.ts:530`, raw fetch/throw) | ADAPT |
| P11 | `POST /api/upload/delete` | `api_tools._api_upload_delete` (`api_tools.py:190`) | `{filename}` | `{ok:True,filename}` / `{ok:False,error}` (`{ok}`) | 200 | unlinks `uploads/<file>` | `deleteUploadedFile` (`api.ts:547`, post/throw) | ADAPT |
| P12 | `POST /api/env-keys` | `api_settings._api_save_env_key` (`api_settings.py:107`) | `{key,value}` | `{ok:True}` / `{ok:False,error}` (`{ok}`) | 200 | writes project `.env` + `os.environ` | — none (drift; GET wrapped, POST not) | ADAPT / REVIEW |
| P13 | `POST /api/ssh/test` | `api_tools._api_ssh_test` (`api_tools.py:216`) | `{ssh_host,ssh_port,ssh_user,ssh_key,ssh_path}` | `{ok:True,info}` / `{ok:False,error}` (`{ok}`) | 200 | **subprocess** `ssh …` (outbound network, timeout 15) | `testSSH` (`api.ts:555`, post/throw) | ADAPT |
| P14 | `POST /api/switch-checkpoint` | `checkpoint_lifecycle._api_switch_checkpoint` (`checkpoint_lifecycle.py:157`) | `{path}` | `{ok:True,path}` / `{error}` (mixed) | 200 | `set_active_checkpoint`; **WS `_broadcast`** of tree; mutates `_last_*`/`_launch_*` | `switchCheckpoint` (`api.ts:360`, post/throw) | ADAPT |
| P15 | `POST /api/ear/<rid>/curate` | `ear._api_ear_curate` (`ear.py:202`) | none (path `rid`) | `{ear_published_dir,manifest_path,bundle_sha256,included_files,excluded_count,skipped}` / `{error,kind}` (`payload`) | 200 | writes `ear_published/` + `manifest.lock`; **mutates `sys.path`** | `curateEAR` (`api.ts:217`, post/throw) | ADAPT |
| P16 | `POST /api/ear/<rid>/publish-yaml` | `ear._api_ear_publish_yaml_set` (`ear.py:288`) | `{text}` or `{data}` | `{ok:True,path,text,data}` / `{error}` (`{ok}`) | 200 (router does not pop `_status`, `:1073`; handler sets none) | writes `ear/publish.yaml` | `savePublishYaml` (`api.ts:247`, post/throw) | ADAPT |
| P17 | `POST /api/ear/clone-verify` | `ear._api_ear_clone_verify` (`ear.py:165`) | `{ref,dest,expect_sha256,extract}` | `{ref,dest,bundle_sha256,file_count,extracted}` / `{error,kind}` (`payload`) | 200 | `ari.clone.clone` → fetch/extract to `dest` | `cloneVerifyBundle` (`api.ts:273`, post/throw) | ADAPT |
| P18 | `POST /api/publish/settings` | `api_publish._api_publish_settings_set` (`api_publish.py:85`) | full settings dict | `{ok:True,path}` / `{error}` (`{ok}`) | 200 | writes publish settings YAML (`~/.ari/publish.yaml` legacy) | `savePublishSettings` (`api.ts:337`, post/throw) | ADAPT |
| P19 | `POST /api/publish/<rid>/promote` | `api_publish._api_publish_promote` (`api_publish.py:156`) | `{target}` | `{ref,visibility,promoted_at}` / `{error,kind}` (`payload`) | 200 | `ari.publish.promote` writes `publish_record.json` | `promotePublish` (`api.ts:346`, post/throw) | ADAPT |
| P20 | `POST /api/publish/<rid>` (not `/preview\|/record\|/settings`) | `api_publish._api_publish_run` (`api_publish.py:118`) | `{backend,visibility,dry_run,metadata,consent}` | `{backend,ref,bundle_sha256,visibility,dry_run,extra,timestamp}` / `{error,_status:400}` (`payload`) | **`_status:400` set on consent-gate (`api_publish.py:131`) AND popped by router (`:1089`)** — the one fully-wired non-200 path | `ari.publish.publish` (registry/network upload unless dry_run) + `publish_record.json` | `runPublish` (`api.ts:343`, post/throw) | ADAPT |
| P21 | `POST /api/fewshot/<rid>/sync` | `api_fewshot._api_fewshot_sync` (`api_fewshot.py:106`) | none (path `rid`) | `{rubric_id,returncode,stdout,stderr,updated}` / `{error}` (`payload`) | 200 | **subprocess** `python scripts/fewshot/sync.py --venue <rid>` (timeout 300) | `syncFewshot` (`api.ts:449`, post/throw) | ADAPT |
| P22 | `POST /api/fewshot/<rid>/upload` | `api_fewshot._api_fewshot_upload` (`api_fewshot.py:147`) | `{example_id,review_json,paper_txt,paper_pdf}` | `{ok,rubric_id,example_id,listing}` / `{error}` (`{ok}`); **inline `{error}` status=400** on bad JSON (`routes.py:1100`) | 200 / inline 400 | writes `<eid>.json/.txt/.pdf` | `uploadFewshot` (`api.ts:453`, post/throw) | ADAPT |
| P23 | `POST /api/fewshot/<rid>/<ex>/delete` | `api_fewshot._api_fewshot_delete` (`api_fewshot.py:203`) | none (path `rid,ex`) | `{ok,removed,listing}` / `{error}` (`{ok}`); **inline `{error}` status=400** on bad path (`routes.py:1107`) | 200 / inline 400 | unlinks `<eid>.*` | `deleteFewshot` (`api.ts:465`, post/throw) | ADAPT |
| P24 | `POST /api/paperbench/papers/import` | `api_paperbench._api_import_paper` (`api_paperbench.py:343`) | `{source_type,source,title,license,paper_id,overwrite,authors,venue,year,artifact_url,pdf_path,ad_pdf_path,ae_pdf_path}` | manifest `entry` dict / `{error,…}` (`payload`); **inline `{error}` status=400** on bad JSON (`routes.py:1118`) | 200 / inline 400 | writes `manifest.jsonl` + `papers/<id>/*.pdf` | `importPaperbenchPaper` (`api.ts:844`, **pbPost/no-throw**) | ADAPT |
| P25 | `POST /api/paperbench/papers/<id>/delete` | `api_paperbench._api_delete_paper` (`api_paperbench.py:440`) | none (path `id`; FE sends no body) | `{deleted:True,paper_id}` / `{deleted:False,reason,paper_id}` (`payload`) | 200 | `rmtree papers/<id>`; rewrites `manifest.jsonl` | `deletePaperbenchPaper` (`api.ts:810`, raw fetch/no-throw) | ADAPT |
| P26 | `POST /api/paperbench/papers/<id>/metadata` | `api_paperbench._api_patch_paper_metadata` (`api_paperbench.py:461`) | arbitrary merge fields (`license` special) | merged `entry` / `{error}` (`payload`); **inline status=400** on bad JSON (`routes.py:1130`) | 200 / inline 400 | rewrites `manifest.jsonl` | — none (drift) | REVIEW_REQUIRED |
| P27 | `POST /api/paperbench/run` | `api_paperbench._api_launch_run` (`api_paperbench.py:597`) | `{paper_ids,rubric_config,reproduce_config,judge_config,dry_run}` | `{dry_run,job_ids,estimated_cost}` / `{error}` (`payload`); **inline status=400** on bad JSON (`routes.py:1137`) | 200 / inline 400 | **mutates `_JOBS`**; spawns **worker threads** `start_paperbench_job` (`api_paperbench_worker.py:289`, each pooling MCP stdio subprocesses) | `runPaperbench` (`api.ts:828`, **pbPost/no-throw**) | ADAPT |
| P28 | `POST /api/paperbench/cost-estimate` | `api_paperbench._api_cost_estimate` (`api_paperbench.py:694`) | `{rubric_config,reproduce_config,judge_config}` | `{wall_time_sec,llm_cost_usd,breakdown}` (`payload`); **inline status=400** on bad JSON (`routes.py:1143`) | 200 / inline 400 | pure compute | `estimatePaperbenchCost` (`api.ts:820`, **pbPost/no-throw**) | KEEP |
| P29 | `POST /api/ollama/<*>` | `api_ollama._ollama_proxy(self)` (`api_ollama.py:43`) | forwards body/headers | upstream body (`stream`) / 502 `{error}` | inline (upstream) | reverse-proxy → `ollama_host` | direct (external ollama clients) | KEEP / REVIEW |
| P30 | `POST /api/gpu-monitor` | `api_process._api_gpu_monitor_action` (`api_process.py:60`) | `{action,confirmed}` | `{ok:True,pid}` / `{ok:False,needs_confirm/msg}` (`{ok}`) | 200 (via `_json`, CORS `*`) | **Popen** `bash gpu_ollama_monitor.sh`; `terminate()`; **mutates `_st._gpu_monitor_proc`** | `gpuMonitorAction` (`api.ts:584`, post/throw; **always sends `confirmed:true`** — SLURM auto-resubmit hazard) | ADAPT / REVIEW |
| P31 | `POST /api/stop` | `api_process._api_stop` (`api_process.py:91`) | none | `{ok:True,stopped,report}` (`payload`) | 200 | `os.killpg` SIGTERM→SIGKILL; `pkill/pgrep -f`; `remove_pid` | `stopExperiment` (`api.ts:506`, post/throw) | ADAPT |
| P32 | `POST /api/checkpoint/file/save` | `file_api._api_checkpoint_file_save` (`file_api.py:175`) | `{checkpoint_id,filename,content}` | `{ok:True,path,size}` / `{error}` (mixed) | 200 | seeds `paper/`; `write_text` | `saveCheckpointFile` (`api.ts:664`, post/throw) | ADAPT |
| P33 | `POST /api/checkpoint/file/delete` | `file_api._api_checkpoint_file_delete` (`file_api.py:221`) | `{checkpoint_id,filename}` | `{ok:True,deleted}` / `{error}` (mixed) | 200 | seeds `paper/`; `unlink` | `deleteCheckpointFile` (`api.ts:692`, post/throw) | ADAPT |
| P34 | `POST /api/checkpoint/compile` | `file_api._api_checkpoint_compile` (`file_api.py:246`) | `{checkpoint_id,main_file}` | `{ok,log}` / `{error}` (**mixed `{ok}`+`{error}`**) | 200 | seeds `paper/`; **subprocess** pdflatex/bibtex ×4 (timeout 120); `copy2` PDF back | `compileCheckpointPaper` (`api.ts:702`, post/throw) | ADAPT |
| P35 | `POST /api/checkpoint/<id>/file/upload` (`re.match`, `:1159`) | `file_api._api_checkpoint_file_upload` (`file_api.py:200`) | header `X-Filename`; raw body bytes | `{ok:True,name,path,size}` / `{error}` (mixed) | 200 | seeds `paper/`; `write_bytes` | `uploadCheckpointFile` (`api.ts:676`, raw fetch/throw) | ADAPT |
| P36 | `POST /api/delete-checkpoint` | `checkpoint_lifecycle._api_delete_checkpoint` (`checkpoint_lifecycle.py:39`) | `{path}` (FE also sends `id`) | `{ok:True,deleted,cleaned_logs,…}` / `{error}` (mixed) | 200 | `rmtree` checkpoint + `experiments/<run>` + logs; `purge_checkpoint` memory; **mutates `_st` globals** (`set_active_checkpoint(None)`,`_running_procs`,`_sub_experiments`,…) | `deleteCheckpoint` (`api.ts:353`, post/throw) | ADAPT |
| P37 | `POST /api/workflow` | `api_settings._api_save_workflow` (`api_settings.py:399`) | `{pipeline,path}` | `{ok:True}` / `{ok:False,error,_status:400}` (`{ok}`) | **`_status:400` set (`api_settings.py:404`) AND popped by router (`:1167`)** — wired | writes `workflow.yaml` | `saveWorkflow` (`api.ts:491`, post/throw) | ADAPT |
| P38 | `POST /api/workflow/flow` | `api_workflow._api_save_workflow_flow` (`api_workflow.py:294`) | `{flow}` | `{ok:True}` / `{ok:False,error,_status:400}` (`{ok}`) | **`_status:400` (`api_workflow.py:301`) popped (`:1169`)** — wired | writes `workflow.yaml` | `saveWorkflowFlow` (`api.ts:718`, post/throw) | ADAPT |
| P39 | `POST /api/workflow/skills` | `api_workflow._api_save_skill_phases` (`api_workflow.py:364`) | `{skills:[{name,phase}]}` | `{ok:True}` / `{ok:False,error,_status:400}` (`{ok}`) | **`_status:400` (`api_workflow.py:380,389`) popped (`:1171`)** — wired | writes `workflow.yaml` | `saveSkillPhases` (`api.ts:726`, post/throw) | ADAPT |
| P40 | `POST /api/workflow/disabled-tools` | `api_workflow._api_save_disabled_tools` (`api_workflow.py:414`) | `{disabled_tools}` | `{ok:True}` / `{ok:False,error,_status:400}` (`{ok}`) | **`_status:400` (`api_workflow.py:424`) popped (`:1173`)** — wired | writes `workflow.yaml` | `saveDisabledTools` (`api.ts:732`, post/throw) | ADAPT |
| P41 | `POST /api/container/pull` | inline `ari.container.pull_image` (`routes.py:1174-1185`) | `{image,mode}` | `{ok}` / `{ok:False,error}` (`{ok}`) | 200 | builds `ContainerConfig`; pulls image | `pullContainerImage` (`api.ts:613`, post/throw) | ADAPT |
| P42 | `else` fallback (`routes.py:1186-1188`) | inline | — | 404 (`bytes`) | inline 404 | none | — | KEEP |

---

## 5. OPTIONS + WebSocket + SSE contracts

### 5.1 OPTIONS (CORS preflight)

`do_OPTIONS` (`routes.py:127-142`): responds `204` for **all** paths with
`Access-Control-Allow-Origin: *`, `Access-Control-Allow-Methods: GET, POST,
OPTIONS`, `Access-Control-Allow-Headers: Content-Type, X-Filename`,
`Access-Control-Max-Age: 86400`. Class: KEEP.

### 5.2 WebSocket (§13.2)

- **Endpoint:** `ws://<host>:(port+1)/` — backend serves via
  `ws_serve(_ws_handler, "", ws_port)` where `ws_port = port + 1`
  (`server.py:172,178`); banner advertises `.../ws` (`server.py:175`) but all
  paths bind. Frontend derives `wsPort = httpPort + 1` and connects to
  `${proto}//${host}:${wsPort}/` (`useWebSocket.ts:38-43`).
- **Messages (server→client only):** exactly one `type`: `update`, shape
  `{"type":"update","data":<nodes_tree>,"timestamp":<iso8601>}`
  (`websocket.py:26-29`, `state_sync.py:45-46`). Client reads `msg.data.nodes`
  (`useWebSocket.ts:60-63`).
- **Triggers:** (a) connect-time snapshot (`websocket.py:24-29`); (b) push on
  `tree.json`/`nodes_tree.json`/`node_*/tree.json` mtime change, 1 s poll
  (`state_sync._watcher_thread`, `state_sync.py:68-116`).
- **Inbound frames are ignored** — `async for _ in websocket: pass`
  (`websocket.py:30-31`). There is **no client→server protocol**.
- **Fallback:** frontend also derives the tree from `GET /state` every 5 s and
  prefers WS nodes when non-empty (`AppContext.tsx:34,86-89,96`).
- Class: KEEP (shape is the contract preserved by subtask 024).

### 5.3 SSE endpoints (§8.3)

Two inline streaming loops, **not** `_json`-wrapped:

1. `GET /api/logs` (G46, `routes.py:901-908`) — `_api_logs_sse` tails logs +
   `cost_trace.jsonl`, frames `data:{"msg":…}`; `Connection: close`; CORS `*`.
2. `GET /api/paperbench/run/<jid>/logs` (G53, `routes.py:934-1000`) — 300 s
   deadline, `: heartbeat` comments, `Last-Event-ID` resume, `event: log`/`done`;
   `404 {"error":"job not found"}` when the (restart-losing) job is unknown; CORS
   `*` on the 200 stream, absent on the 404.

---

## 6. Findings (§8.9, §13.7) — record only, do not fix

- **F1 — Frontend throw / no-throw regime split (hazard).** `get`/`post`
  **throw** on non-2xx (`api.ts:18-32`); `pbGet`/`pbPost` **never throw** and read
  `{error}` from HTTP-200 bodies (`api.ts:787-799`, comment `:780-785`). Because
  `_json` defaults to `status=200` (`routes.py:1190`) and almost no handler sets a
  non-200 status, error semantics differ purely by which wrapper the frontend
  used. PaperBench endpoints (G50–G56, P24–P28) are the no-throw set.
  Class: REVIEW_REQUIRED (for 022/030).
- **F2 — CORS inconsistency (corrects the 020 scaffold).** `_json` emits
  `Access-Control-Allow-Origin: *` on every JSON response (`routes.py:1194`).
  The **inline** sites split two ways, verified by grep of `routes.py`:
  - Inline sites that **DO** set the header: `/memory/<node_id>` (`:216`),
    `/codefile` 200 (`:710`), `paper.*` 200 (`:740`), `file/raw` 200 (`:815`),
    `/api/logs` SSE (`:905`), PaperBench logs SSE 200 (`:967`), plus
    `_ollama_proxy`.
  - Inline sites that **OMIT** the header: **`GET /state` (`:662-666`)** and
    **`GET /api/gpu-monitor` (`:668-672`, comment says so explicitly)**, plus the
    asset serves (logo `:153`, static `:179`, SPA index `:118`) and every inline
    error branch (`:715,718,744,801,959,1025,1187`).
  > The 020 plan's §6.4 lists `710, 740, 815, 905, 967` as "omit" sites; the live
  > source shows those lines **set** the header. The genuine production-endpoint
  > omissions are `/state` and `/api/gpu-monitor`. Ground truth wins.
  Class: REVIEW_REQUIRED.
- **F3 — `WIZARD_ROUTES` dead code.** `api_wizard.py:30-35` defines a declarative
  route table imported by **no** dispatcher (`grep -rn WIZARD_ROUTES` → only its
  own def). It also maps a **stale path** `"/api/generate-config"` whereas the live
  route is `POST /api/config/generate` (`routes.py:1052`). Prior "route table"
  intent; not an authoritative endpoint list. Class: DELETE_CANDIDATE.
- **F4 — Stale `viz/REFACTORING.md` docstring pointer.** `api_state.py:19` (and 8
  sibling files: `state_sync.py:3`, `checkpoint_finder.py:3`, `file_api.py:3`,
  `checkpoint_api.py:3`, `ear.py:3`, `node_work_api.py:3`,
  `checkpoint_lifecycle.py:3`, `server.py:48,62`) reference `viz/REFACTORING.md`,
  which **does not exist** (`ls` → only `ari-core/ari/viz/README.md`). Record; do
  not act. Class: DELETE_CANDIDATE (doc pointer only).
- **F5 — No auth anywhere.** Every endpoint (subprocess launch P5/P6/P7/P30,
  file write, checkpoint delete P36, memory lifecycle P2–P4, ollama proxy G7/P29,
  `GET /api/env-keys` secret readback G11) is open with `Access-Control-Allow-
  Origin: *`. Local-only-by-design is plausible but undocumented in code.
  Class: REVIEW_REQUIRED.
- **F6 — Frontend/backend drift.**
  - **F6a (high):** `requestPaperbenchReport` **POSTs** to
    `/api/paperbench/run/<jid>/report` (`api.ts:857-861`), but `do_POST` has **no**
    `/report` branch — only `do_GET` matches `/report` (G55, `routes.py:1005`). A
    POST therefore falls through to the `else` 404 (`routes.py:1187`); because
    `pbPost` does not throw, the empty 404 body then fails `res.json()`. Verify
    intended method before 021/023 touch it. Class: REVIEW_REQUIRED.
  - **F6b (endpoints with no `services/api.ts` wrapper — grep-confirmed):**
    `GET /memory/<node_id>` (G4, legacy), `GET /api/memory/detect` (G20),
    `POST /api/memory/start-local` (P2), `POST /api/memory/stop-local` (P3),
    `GET /api/paperbench/papers/<id>/license` (G52),
    `POST /api/paperbench/papers/<id>/metadata` (P26),
    `POST /api/env-keys` (P12), `GET /api/checkpoint/<id>/file/raw` (G22b),
    `GET /api/upload` (G33 stub), `GET /api/lineage-decisions/<ckpt>` (G49).
    (Endpoints consumed via `EventSource`/direct URL rather than a wrapper —
    `/api/logs`, PaperBench logs, `/codefile`, `paper.pdf` — are **not** drift;
    grep located their consumers in `MonitorPage.tsx:163`, `ResultsView.tsx:100`,
    `EarSection.tsx`, `PaperWorkspace.tsx`.) No **reverse** drift found: every
    `get/post/pbGet/pbPost` URL in `api.ts` maps to a live backend branch.
    Class: REVIEW_REQUIRED / DELETE_CANDIDATE per endpoint.
- **F7 — `_status` smuggling is only partially wired.** The router pops
  `_status` at 9 sites (`routes.py:1047,1049,1051,1057,1089,1167,1169,1171,1173`),
  but the handlers actually **fall into three classes**:
  - **Fully wired (non-200 reaches the wire):** `_api_save_workflow` (P37),
    `_api_save_workflow_flow` (P38), `_api_save_skill_phases` (P39),
    `_api_save_disabled_tools` (P40), `_api_publish_run` (P20) — all set
    `_status:400` and are popped.
  - **Popped-but-never-set (defensive, always 200):** `_api_launch` (P5),
    `_api_launch_sub_experiment` (P6), `_api_run_stage` (P7), `_api_upload_file`
    (P10) — the `.pop("_status",200)` never fires.
  - **Set-but-never-popped (bug: `_status` leaks into JSON body, HTTP stays
    200):** `_api_save_settings` (P1) sets `{…,_status:400}` (`api_settings.py:223-228`)
    but the router calls it as `self._json(_api_save_settings(body))` with no pop
    (`routes.py:1036`). Also `_api_ear_publish_yaml_set` (P16) uses `ok/error` but
    is called without a pop (`routes.py:1073`). Class: REVIEW_REQUIRED (022/030
    must pin the exact live status per endpoint, including this asymmetry).
- **F8 — GET endpoints with write side effects.** `GET /api/checkpoint/<id>/files`
  (G21), `.../file` (G22a), `.../file/raw` (G22b) all call `_ensure_paper_dir`
  (`file_api.py:53`), which `mkdir`s `paper/` + `paper/figures/` and `copy2`-seeds
  root artefacts into `paper/`. A "read" endpoint mutates the checkpoint tree.
  Class: ADAPT / REVIEW.
- **F9 — Two divergent path-traversal guards.** `/codefile` uses a weak substring
  test `"checkpoints" in str(p)` (`routes.py:692`); `file_api`/`node_work_api` use
  strict `relative_to(paper.resolve())`. Inconsistent security posture.
  Class: REVIEW_REQUIRED.
- **F10 — Restart-losing PaperBench `_JOBS`.** `_JOBS`/`_JOBS_LOCK`
  (`api_paperbench.py:496-497`) is a process-local dict; job status/results/logs
  are never persisted (module docstring `:39-43`). Endpoints G53–G56 and P27 are
  stateful and lose all history on server restart. Class: ADAPT (preserve
  behaviour explicitly).
- **F11 — Legacy `~/.ari/publish.yaml`.** `api_publish._resolve_settings_path`
  falls back to `~/.ari/publish.yaml` with a `DeprecationWarning`
  (G29/P18). Notable given the v0.5.0 no-`~/.ari` design; record, do not act.
  Class: REVIEW_REQUIRED.
- **F12 — `/api/env-keys` returns secret values** (G11) to the browser. UX/safety
  concern already flagged in `010:360`. Record. Class: REVIEW_REQUIRED.

### 6.1 State-global mutation map (§8.8, §6.8)

Endpoints that write `state.py` globals (021's service extraction must preserve
the observable effect):

- `_last_proc` / `_running_procs`: P5, P6*, P7, P10*; pruned by G13;
  read/terminated by P31 (`*` via `_running_procs` only where noted).
- `_checkpoint_dir` / `_settings_path` (`set_active_checkpoint`): P5, P10 (staging),
  P14, P36 (→ `None`), and G5 clears `_last_experiment_md`.
- `_launch_config` / `_launch_llm_model` / `_launch_llm_provider`: P5, P14.
- `_last_experiment_md` / `_last_log_fh` / `_last_log_path`: P5, P14, P36.
- `_sub_experiments`: G47 (rebuild), G48, P6, P36.
- `_gpu_monitor_proc`: P30 (assign), read by G6/P31.
- `_staging_dir`: P5 (clear), P10 (assign).
- `_clients` / `_loop`: WS connect/disconnect (`websocket.py:21,36`), broadcast
  (`state_sync.py:43-63`).

Per-request `viz_access.jsonl` append happens for **every** request via
`log_request` → `_write_access_log` (`routes.py:87-104,69-74`).

---

## 7. Classification roll-up (§13.8)

Every endpoint above carries a class. Summary of the non-KEEP recommendations
(for 021/022/023/024/030 — 020 changes nothing):

- **ADAPT** (extract behind an unchanged wire shape): `GET /state` (G5, the
  ~450-line builder), all subprocess/LLM/file-IO/state-mutating handlers
  (G6, G12, G13, G16–G28, G36, G42–G51, G53–G56, P1–P41 excluding pure/KEEP).
- **KEEP** (pure/static/constant): G1–G3, G9, G14, G15, G32, G35, G38–G41, G45,
  G57, P28, P42, OPTIONS, WebSocket.
- **MOVE_TO_LEGACY:** `GET /memory/<node_id>` (G4).
- **DELETE_CANDIDATE:** `GET /api/upload` stub (G33); `WIZARD_ROUTES` (F3);
  stale `viz/REFACTORING.md` pointers (F4).
- **REVIEW_REQUIRED:** the throw/no-throw split (F1), CORS inconsistency (F2),
  no-auth posture (F5), FE/BE drift incl. the POST-report 404 (F6), the partial
  `_status` wiring incl. the `/api/settings` leak (F7), GET-with-write (F8),
  divergent traversal guards (F9), legacy `~/.ari` publish path (F11), env-keys
  secret exposure (F12); endpoints G7/G11/G20/G22b/G29/G52/P2/P3/P12/P26/P30.

---

## 8. Verification performed (read-only gates)

- `python -m compileall ari-core/ari/viz` → exit 0 (no source corrupted).
- `python -m compileall .` → exit 0.
- `ruff check ari-core/ari/viz` → reports only the **pre-existing** baseline
  (F401/E402/E741, part of the 661-finding repo baseline in master `§5`); **020
  introduces zero new findings** because no `.py` was edited (`git status` shows
  no runtime diff). Full `pytest -q` is intentionally **not** run here (the
  orchestrator runs it centrally).
- `git status --porcelain` shows no change under `ari-core/` or any runtime path;
  the only additions attributable to 020 are this file and its `.json` twin under
  `docs/refactoring/reports/`.

## 9. Retirement

This artifact is the baseline consumed by subtasks 021/022/023/024/030. It may be
superseded once those refactors land and pin the contract in tests
(`test_api_schema_contract.py`) + the `check_viz_api_schema.py` gate (030). See the
subtask's §18 and `007_subtask_index.md` "Document Retirement Policy".
