# frontend/src/hooks

Custom React hooks.

## Contents

- `README.md` — this file.
- `useApi.ts` — generic async data-fetch hook with loading/error/refetch.
- `useDevMode.ts` — persisted developer-mode flag (localStorage `ari_dev_mode`, default OFF) with same-tab + cross-tab sync; gates raw/debug/dangerous UI surfaces.
- `useRunEvents.ts` — subscribes the shared SSE client for the caller's lifetime and maps each event to a react-query invalidation keyed by the EVENT's `run_id` (events are invalidations, never data — an event for run B can never touch run A's cache); exposes `connectionState`/`lastEventAt` for the `StaleDataBanner` and a bounded poll fallback once the stream is offline.
- `useV1.ts` — react-query hooks over the typed `/api/v1` client; query keys are `['v1', projectId?, runId?, resource]`, so run-scoped entries stay isolated per run and one run's server state can be dropped in a single `invalidateQueries`.
- `useWebSocket.ts` — streams real-time tree updates with auto-reconnect.
- `__tests__/` — hook unit tests.
  - `useDevMode.test.tsx` — default-OFF, persistence, and cross-instance sync for `useDevMode`.
  - `useRunEvents.test.tsx` — event → invalidation glue against a fake `EventSource`: per-topic keys, two-run isolation, connection state and the offline poll tick.
