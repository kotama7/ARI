# frontend/src/shared/realtime

Shared realtime client (gui_refresh Wave 2b, ADR-03). Realtime integration
rule: an SSE event for a run is a notification, so it maps to a query-cache
invalidation plus a refetch of the HTTP snapshot, never to a direct state
write. Nothing is rendered from an event, which is why duplicates and
reordering are harmless and a dropped stream is a freshness problem rather
than a state change. Feature code never touches `EventSource` directly — it
goes through `hooks/useRunEvents.ts`, which consumes this client.

## Contents

- `README.md` — this file.
- `eventStream.ts` — `subscribe(runId, topics, callbacks)` wrapper over SSE
- `__tests__/` — realtime client unit tests.
  - `eventStream.test.ts` — FakeEventSource-driven: URL/filter
