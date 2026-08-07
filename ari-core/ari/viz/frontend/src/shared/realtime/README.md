# frontend/src/shared/realtime

Shared realtime client (gui_refresh Wave 2b, ADR-03 + plan 03 §Realtime
integration). Feature code never touches `EventSource` directly — it goes
through `hooks/useRunEvents.ts`, which consumes this client.

## Contents

- `README.md` — this file.
- `eventStream.ts` — `subscribe(runId, topics, callbacks)` wrapper over SSE
- `__tests__/` — realtime client unit tests.
  - `eventStream.test.ts` — FakeEventSource-driven: URL/filter
