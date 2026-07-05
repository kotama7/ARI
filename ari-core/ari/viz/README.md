# ari.viz

HTTP + WebSocket dashboard server exposing BFTS state, per-checkpoint
files, EAR bundles, and tooling endpoints to the bundled web frontend.
Entry points: `serve` (programmatic), `main` (`ari viz`).

## Contents

- `README.md` — this file.
- `__init__.py` — package docstring + module map / public symbols.
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
- `checkpoint_api.py` — model list, checkpoint list/summary, lineage decisions.
- `checkpoint_finder.py` — checkpoint discovery + PID liveness probe.
- `checkpoint_lifecycle.py` — checkpoint delete + switch.
- `ear.py` — EAR curate/publish/clone REST helpers.
- `file_api.py` — per-checkpoint file CRUD + LaTeX compile.
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

## See also

- `docs/reference/rest_api.md` — REST endpoint reference.
- `frontend/README.md` — web frontend develop/test/layout guide.
