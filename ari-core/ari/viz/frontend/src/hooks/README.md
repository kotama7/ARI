# frontend/src/hooks

Custom React hooks.

## Contents

- `README.md` — this file.
- `useApi.ts` — generic async data-fetch hook with loading/error/refetch.
- `useDevMode.ts` — persisted developer-mode flag (localStorage `ari_dev_mode`, default OFF) with same-tab + cross-tab sync; gates raw/debug/dangerous UI surfaces.
- `useWebSocket.ts` — streams real-time tree updates with auto-reconnect.
- `__tests__/` — hook unit tests.
  - `useDevMode.test.tsx` — default-OFF, persistence, and cross-instance sync for `useDevMode`.
