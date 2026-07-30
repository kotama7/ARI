# frontend/src/services

Client modules for talking to the `ari.viz` backend.

## Contents

- `README.md` — this file.
- `api.ts` — typed REST client (state, checkpoints, settings, GPU monitor, etc.).
- `websocket.ts` — websocket helper stub (connections now handled by `useWebSocket`).
- `__tests__/` — service-layer contract tests: the frozen API wire contract and the FE schema round-trip mirror.
  - `api.test.tsx` — pins the frozen wire contract — same-origin `API_BASE`, each wrapper's endpoint path, the throwing `get`/`post` vs swallowing `pbGet`/`pbPost` regimes, and the POST request-init shape.
  - `schema.test.tsx` — FE mirror of `tests/test_api_schema_contract.py`: typed `AppState`/`Checkpoint`/`Settings`/`WorkflowData` fixtures round-trip through a mocked fetch, asserting the always-present keys survive (additive-subset doctrine, `types/index.ts` is the source of truth).
- `api/` — the domain-partitioned endpoint wrappers and DTOs split out of the old 863-line `api.ts` god-module, all riding one shared transport core (`client.ts`).
  - `capabilities.ts` — `GET /api/capabilities` server feature flags (the `ARI_GUI_V2` shell kill-switch); callers must default `gui_v2` to ON when the fetch fails, so an API hiccup never bricks the dashboard into the fallback shell.
  - `catalog.ts` — profiles / rubrics / few-shot catalog family — `fetchProfiles`, `fetchRubrics`, and the few-shot list/sync/upload/delete wrappers.
  - `challenges.ts` — requests the server-issued confirmation challenge every dangerous operation (delete-checkpoint / stop-all / gpu-monitor stop) must carry: single-use, server-TTL-bounded, and bound to one action+target.
  - `checkpoints.ts` — checkpoint list / summary / lifecycle family; `deleteCheckpoint` is two-step and must carry a `delete-checkpoint` challenge id or the server refuses with HTTP 428.
  - `client.ts` — the shared same-origin transport (`API_BASE = ''`) behind one `request` primitive: throwing `get`/`post`, never-throwing `pbGet`/`pbPost`, envelope-preserving `v1Get`/`v1Send` (If-Match), plus the MN-8 bearer-token helpers.
  - `ear.ts` — Experiment Artifact Repository family — browse a run's EAR, `curateEAR` bundling, the `publish.yaml` read/save editor, and `cloneVerifyBundle` sha256 verification.
  - `experiment.ts` — experiment lifecycle family — `runStage`, `launchExperiment`, and `stopExperiment`, which needs a `stop-all` challenge id or the server refuses with HTTP 428.
  - `files.ts` — Overleaf-like checkpoint file management — file list/filetree/content reads, save/delete, the bespoke octet-stream `uploadCheckpointFile` (`X-Filename`), and `compileCheckpointPaper`.
  - `memory.ts` — Letta memory family — per-checkpoint entries grouped `by_node`, the read/write access log, `/api/memory/health`, and `restartLetta`.
  - `nodeReport.ts` — `fetchNodeReport` plus the v0.7.0 `NodeReport` DTO (files_changed, metrics, self_assessment, artifacts) served by `/api/nodes/{run}/{node}/report`.
  - `paperbench.ts` — PaperBench family on the no-throw `pbGet`/`pbPost` regime (the backend answers 200 + `{error}`): paper registry list/import/delete, arXiv metadata, cost estimate, run launch, results, report export.
  - `publish.ts` — publish family — registry settings, `previewPublish`, `runPublish` (dry-run/consent/visibility), `promotePublish`, and the stored `PublishRecord`.
  - `resources.ts` — infra probes — scheduler detect, SLURM partitions, Ollama/GPU resources, container info/images/pull, and `gpuMonitorAction` whose `stop` requires a `gpu-monitor-stop` challenge.
  - `settings.ts` — settings / env family — `/api/settings` read+write plus `fetchSecretsStatus`, which reports only WHETHER each allowlisted secret is configured, never its value.
  - `ssh.ts` — SSH / HPC probe family — the single `testSSH` wrapper over `POST /api/ssh/test`.
  - `state.ts` — state / tree / models family — the `/state` `AppState` poll, experiment-detail config, active checkpoint, resource metrics, and model list.
  - `subExperiments.ts` — recursive-orchestration family — list/fetch/launch sub-experiments, with the `SubExperiment` DTO carrying lineage provenance (`inherit_idea_index`, parent-termination fields).
  - `v1.ts` — typed read-only client for the versioned `/api/v1` API; every failure (typed `ErrorEnvelopeV1`, network error, malformed body) is normalized into a thrown `ApiErrorV1` `{code, message, details, request_id, retryable}`.
  - `v1types.gen.ts` — DTO/path types generated from `ari/viz/v1/openapi.json` by `npm run gen:v1types`; committed to the tree and byte-compared by `src/__tests__/v1TypesDrift.test.ts` — never hand-edited.
  - `wizard.ts` — wizard / chat / upload family — `chatGoal`, `generateConfig`, and the bespoke octet-stream `uploadFile` (`X-Filename` / `X-File-Type`) with its delete.
  - `workflow.ts` — skills + `workflow.yaml` family; writes are revision-aware (`base_revision`), and `isWorkflowRevisionConflict` recognizes the HTTP 409 stale-revision refusal surfaced by the throwing `post`.
