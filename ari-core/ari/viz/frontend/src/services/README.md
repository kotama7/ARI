# frontend/src/services

Client modules for talking to the `ari.viz` backend.

## Contents

- `README.md` — this file.
- `api.ts` — typed REST client (state, checkpoints, settings, GPU monitor, etc.).
- `websocket.ts` — websocket helper stub (connections now handled by `useWebSocket`).
- `__tests__/` — TODO
  - `api.test.tsx` — TODO
  - `schema.test.tsx` — TODO
- `api/` — TODO
  - `capabilities.ts` — `GET /api/capabilities` server feature flags (the `ARI_GUI_V2` shell kill-switch); callers must default `gui_v2` to ON when the fetch fails, so an API hiccup never bricks the dashboard into the fallback shell.
  - `catalog.ts` — TODO
  - `challenges.ts` — requests the server-issued confirmation challenge every dangerous operation (delete-checkpoint / stop-all / gpu-monitor stop) must carry: single-use, server-TTL-bounded, and bound to one action+target.
  - `checkpoints.ts` — TODO
  - `client.ts` — TODO
  - `ear.ts` — TODO
  - `experiment.ts` — TODO
  - `files.ts` — TODO
  - `memory.ts` — TODO
  - `nodeReport.ts` — TODO
  - `paperbench.ts` — TODO
  - `publish.ts` — TODO
  - `resources.ts` — TODO
  - `settings.ts` — TODO
  - `ssh.ts` — TODO
  - `state.ts` — TODO
  - `subExperiments.ts` — TODO
  - `v1.ts` — typed read-only client for the versioned `/api/v1` API; every failure (typed `ErrorEnvelopeV1`, network error, malformed body) is normalized into a thrown `ApiErrorV1` `{code, message, details, request_id, retryable}`.
  - `v1types.gen.ts` — DTO/path types generated from `ari/viz/v1/openapi.json` by `npm run gen:v1types`; committed to the tree and byte-compared by `src/__tests__/v1TypesDrift.test.ts` — never hand-edited.
  - `wizard.ts` — TODO
  - `workflow.ts` — TODO
