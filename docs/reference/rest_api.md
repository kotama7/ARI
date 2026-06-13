---
sources:
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
last_verified: 2026-06-10
---

# REST API Reference

The viz dashboard server (`ari viz` → `ari-core/ari/viz/server.py`)
exposes a JSON HTTP API used by the bundled web UI and accessible to
external integrations.  Endpoints are dispatched by `viz/routes.py`
into per-domain handler modules (`viz/api_*.py`,
`viz/checkpoint_api.py`, `viz/file_api.py`, etc., split out in Phase
3B).

All endpoints are unauthenticated by default — `ari viz` binds to
`127.0.0.1` and is intended for the local user.  Wrap it in nginx /
oauth2-proxy if you want to expose it.

## Conventions

- Base URL: `http://127.0.0.1:<port>` (default port set by `ari viz`).
- All response bodies are JSON unless noted otherwise.
- Errors come back as `{"error": "<message>"}` with a non-2xx HTTP code.
- CORS preflight (`OPTIONS`) is permissive on `/api/*`.

## Typed contracts (stable endpoints)

The highest-traffic GET endpoints have their response shape mirrored by a
frontend TypeScript type in `ari-core/ari/viz/frontend/src/types/index.ts` and
guarded by `ari-core/tests/test_api_schema_contract.py` (asserts the
always-present keys as a **subset** — extra/optional fields are allowed, so the
contract is additive). Verified 2026-05-30.

| Endpoint | Producer | Frontend type | Always-present keys |
|---|---|---|---|
| `GET /state` | `routes.py` `/state` builder | `AppState` | `running_pid`, `is_running`, `exit_code`, `running`, `pid`, `status_label` (the rest are checkpoint-gated → optional in the type). `cost` is the parsed `cost_summary.json` **object** (`CostSummary`), not a number. |
| `GET /api/settings` | `api_settings._api_get_settings` | `Settings` | the full defaults dict (`llm_model`, `llm_provider`, `ollama_host`, `temperature`, … , nested `ors`); arbitrary saved keys also pass through (`{**defaults, **saved}`). |
| `GET /api/checkpoints` | `checkpoint_api._api_checkpoints` | `Checkpoint[]` | `id`, `path`, `status`, `node_count`, `review_score`, `best_metric` (always `null`), `mtime`; `best_scientific_score` is conditional. |
| `GET /api/checkpoint/<id>/summary` | `checkpoint_api._api_checkpoint_summary` | `CheckpointSummary` | `id`, `path` (or `{error:"not found"}`); all report bodies are conditional. `reproducibility_report` is a parsed **object** (legacy runs: string), not always a string. |

Contracts are **permissive**: new optional fields may be added without breaking
consumers; existing fields are never removed during a migration (see the
refactoring global rules).

## Worked examples

Minimal `curl` request/response pairs for the endpoints you reach for first.
The examples assume the dashboard is on the default port `8765`.

**Read the live state:**

```bash
curl http://localhost:8765/state
```

```json
{
  "phase": "bfts",
  "nodes": { "total": 7, "completed": 5, "running": 2, "failed": 0 },
  "model": { "provider": "ollama", "model": "qwen3:8b" },
  "cost": { "usd": 0.0, "tokens": 0 }
}
```

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
  { "id": "20260526T101500_matmul", "status": "running", "nodes": 7, "review_score": null },
  { "id": "20260520T090000_sort",   "status": "done",    "nodes": 12, "review_score": 0.71 }
]
```

**Error shape** (any endpoint, non-2xx):

```json
{ "error": "no active checkpoint" }
```

## State + dashboards

| Method | Path | Purpose | Source |
|---|---|---|---|
| GET | `/state` | Current BFTS state snapshot used by the dashboard live view | `routes.py:211` |
| GET | `/api/gpu-monitor` | GPU utilisation poll | `routes.py:654` |
| GET | `/api/resource-metrics` | CPU / memory / disk metrics | `routes.py:886` |
| GET | `/api/logs` | Recent log lines for the active run | `routes.py:903` |

## Models + skills

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/models` | Discover LLMs available via LiteLLM + Ollama |
| GET | `/api/ollama-resources` | Memory / disk needed by a model |
| GET | `/api/ollama/<...>` | Proxy through to a local Ollama daemon |
| GET | `/api/skills` | Enumerate registered skills + their tool counts |
| GET | `/api/skill/<skill_name>` | Per-skill metadata (tool list, env vars) |
| GET | `/api/tools` | Combined tool catalogue across all skills |
| GET | `/api/scheduler/detect` | `local` / `slurm` / `apptainer` autodetect |
| GET | `/api/slurm/partitions` | SLURM partition list |
| GET | `/api/container/info` | Container runtime probe |
| GET | `/api/container/images` | Cached SIF / OCI images |
| POST | `/api/container/pull` | Pull / build an image referenced by `ARI_CONTAINER_IMAGE` |

## Checkpoint browsing

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/checkpoints` | List all checkpoints under `ARI_CHECKPOINT_DIR` parent |
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
| POST | `/api/delete-checkpoint` | Delete a checkpoint (also drops the matching Letta agent) |
| POST | `/api/checkpoint/file/save` | Edit a file in-place |
| POST | `/api/checkpoint/file/delete` | Delete a file from a checkpoint |
| POST | `/api/checkpoint/compile` | Run `pdflatex` on a paper draft |

## Run lifecycle

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/launch` | Start a new BFTS run (`ari run` programmatically) |
| POST | `/api/run-stage` | Run a single pipeline stage |
| POST | `/api/stop` | Stop the active run |

## Sub-experiments + lineage

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/sub-experiments` | All sub-experiment records |
| GET | `/api/sub-experiments/<run_id>` | Single sub-experiment detail |
| POST | `/api/sub-experiments/launch` | Launch a child run inheriting from a parent checkpoint |
| GET | `/api/lineage-decisions/<run_id>` | Decisions emitted by the stagnation rule (v0.7.0) |

## Memory backend

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/memory/health` | Letta health probe |
| GET | `/api/memory/detect` | Inventory of running Letta deploy paths |
| POST | `/api/memory/start-local` | Spawn a local Letta server |
| POST | `/api/memory/stop-local` | Stop the local Letta server |
| POST | `/api/memory/restart` | Restart the local Letta server |

## Settings + workflow

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/settings` | Read settings.json |
| POST | `/api/settings` | Write settings.json |
| GET | `/api/profiles` | Saved profile list |
| GET | `/api/env-keys` | Env-var keys ARI knows about (no values) |
| POST | `/api/env-keys` | Persist env-var key/value pairs to `.env` |
| GET | `/api/workflow` | Active workflow.yaml |
| GET | `/api/workflow/default` | Bundled default |
| GET | `/api/workflow/flow` | Workflow visualised as DAG nodes / edges |
| POST | `/api/workflow` | Save workflow.yaml |
| POST | `/api/workflow/flow` | Save the DAG view |
| POST | `/api/workflow/skills` | Toggle which skills are enabled |
| POST | `/api/workflow/disabled-tools` | Per-skill tool whitelist / blacklist |

## Wizard / config gen

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/experiment-detail` | Wizard's parsed experiment.md |
| POST | `/api/config/generate` | Generate `ari.yaml` from wizard answers |
| POST | `/api/chat-goal` | LLM-assisted goal narrative refinement |
| POST | `/api/ssh/test` | Probe an SSH cluster login |

## Uploads + few-shot corpus

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/upload` | Multipart upload into the active checkpoint |
| POST | `/api/upload/delete` | Remove an uploaded file |
| GET | `/api/fewshot/<rubric_id>` | Few-shot examples for a rubric |
| POST | `/api/fewshot/<rubric_id>/sync` | Pull the published corpus |
| POST | `/api/fewshot/<rubric_id>/upload` | Add an example |
| POST | `/api/fewshot/<rubric_id>/delete` | Remove an example |
| GET | `/api/rubrics` | Available reviewer rubrics (driven by `ARI_RUBRIC`) |

## Node reports

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/nodes/<...>/report` | Per-node `node_report.json` |

## EAR + publish (v0.7.0)

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

## Static + frontend

| Method | Path | Purpose |
|---|---|---|
| GET | `/static/<path>` | Bundled UI assets |
| GET | `/memory/<path>` | Memory inspector static page |
| GET | `/codefile?path=...` | Source file viewer |

## Updating this reference

The route table is the dispatch chain in
`ari-core/ari/viz/routes.py` — when you add a route, mirror it here.
A future improvement could auto-generate this page from the dispatch
chain (the master plan suggests OpenAPI generation for the same
reason).

## See also

- `docs/concepts/architecture.md` — viz package overview.
- `ari-core/ari/viz/__init__.py` — module-level docstring with the
  current sub-module map.
