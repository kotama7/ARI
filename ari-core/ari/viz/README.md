# ari.viz

HTTP + WebSocket dashboard server exposing BFTS state, per-checkpoint
files, EAR bundles, and tooling endpoints to the bundled web frontend.
Entry points: `serve` (programmatic), `main` (`ari viz`).

## Contents

- `README.md` — this file.
- `__init__.py` — package docstring + module map / public symbols.
- `api_capabilities.py` — `GET /api/capabilities` server feature flags (`ARI_GUI_V2` shell switch).
- `api_experiment.py` — launch, run stages, log streaming.
- `api_fewshot.py` — reviewer_rubrics/fewshot_examples corpus management.
- `api_memory.py` — memory backend health + local Letta start/stop.
- `api_ollama.py` — GPU/model detection + Ollama proxy.
- `api_orchestrator.py` — sub-experiment registry, launch, listing.
- `api_paperbench.py` — PaperBench paper registry + run-wizard endpoints.
- `api_paperbench_worker.py` — background worker driving PaperBench skill tools.
- `api_process.py` — experiment process control: stop-all + GPU-monitor start/stop/status.
- `api_publish.py` — publish settings + preview/run endpoints.
- `api_settings.py` — env keys, settings, workflow, skills, profiles.
- `api_state.py` — checkpoint discovery, tree loading, broadcasting (re-export facade).
- `api_tools.py` — chat, config generation, file upload, SSH test.
- `api_wizard.py` — consolidated wizard endpoint router.
- `api_workflow.py` — React Flow workflow-editor endpoints.
- `auth.py` — remote-mode bearer-token gate; loopback binds stay unauthenticated.
- `checkpoint_api.py` — model list, checkpoint list/summary, lineage decisions.
- `checkpoint_finder.py` — checkpoint discovery + PID liveness probe.
- `checkpoint_lifecycle.py` — checkpoint delete + switch.
- `ear.py` — EAR curate/publish/clone REST helpers.
- `file_api.py` — per-checkpoint file CRUD + LaTeX compile.
- `health.py` — `/health/live` + `/health/ready` probes and bounded `/api/v1/diagnostics`; never 500s.
- `internal_adapters.py` — TODO
- `node_work_api.py` — per-node work-dir filetree/filecontent/memory listing.
- `routes.py` — `_Handler` dispatch + access log.
- `server.py` — HTTP/WebSocket server and `ari viz` main entry.
- `state.py` — shared mutable server state.
- `state_sync.py` — node-tree loading + broadcast + filesystem watcher.
- `tree_view.py` — TODO
- `ui_helpers.py` — dashboard rendering helpers.
- `websocket.py` — WebSocket handler streaming tree state.
- `frontend/` — React + Vite + TypeScript. Served by `ari viz` / `python -m ari.viz.server`
- `services/` — TODO
  - `__init__.py` — TODO
  - `file_service.py` — TODO
  - `launch_service.py` — TODO
  - `state_service.py` — TODO
- `v1/` — versioned `/api/v1` platform built on the stdlib server (ADR-02): typed errors, pydantic DTOs, declarative router, generated OpenAPI.
  - `__init__.py` — package docstring + v1 module map (no FastAPI/uvicorn, zero new runtime deps).
  - `catalogs.py` — model/provider catalog re-serving `GET /api/models` plus each provider's API-key env name.
  - `challenges.py` — single-use, TTL-bounded confirmation challenges required by the destructive endpoints (428 otherwise).
  - `config_api.py` — config-document CRUD (project config, run templates, run drafts) with `If-Match` optimistic concurrency.
  - `dto.py` — pydantic v2 response models, each carrying `schema_version`; changes are additive by policy.
  - `errors.py` — typed `{code, message, details, request_id, retryable}` error envelope + frozen code vocabulary.
  - `events.py` — in-process ring-buffer event bus and the SSE framing behind `GET /api/v1/events/stream`.
  - `launch.py` — idempotent `POST /api/v1/runs`: validate → mint `run_id` → materialize checkpoint → spawn the CLI subprocess.
  - `logs.py` — cursor-paged, byte-bounded read model over a run's `ari.log` (committed lines only).
  - `openapi.json` — the committed OpenAPI 3.1 document; drift-guarded against the generator.
  - `openapi.py` — deterministic OpenAPI 3.1 generator from `router.ROUTES` + `dto` schemas (`--check` / `--update`).
  - `queries.py` — pure filesystem read queries: no `viz.state` mutation, no env writes, no file writes.
  - `results.py` — bounded review-score / ORS verdict / EAR lineage read models with honest-absence flags.
  - `router.py` — declarative `(method, path_template, handler)` table + `dispatch` with per-request `request_id`.
  - `rqgm.py` — RQGM artifact read models (offline projector; never imports `ari.rqgm`).
  - `secrets.py` — secret readiness reads + write-only `PUT /api/v1/secrets/{secret_id}` over a fixed allowlist.
  - `store.py` — atomic, per-document-revisioned GUI store under `{workspace_root}/gui_store/` (ADR-12).

## See also

- `docs/reference/rest_api.md` — REST endpoint reference.
- `frontend/README.md` — web frontend develop/test/layout guide.
