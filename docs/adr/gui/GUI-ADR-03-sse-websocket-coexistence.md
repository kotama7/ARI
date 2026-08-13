---
sources:
  - path: ari-core/ari/viz/v1/events.py
    role: implementation
  - path: ari-core/ari/viz/routes.py
    role: implementation
  - path: ari-core/ari/viz/state_sync.py
    role: implementation
  - path: ari-core/ari/viz/websocket.py
    role: implementation
  - path: ari-core/ari/viz/server.py
    role: implementation
  - path: ari-core/ari/viz/health.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/shared/realtime/eventStream.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/hooks/useWebSocket.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/context/AppContext.tsx
    role: implementation
  - path: ari-core/tests/test_gui_v1_events.py
    role: test
  - path: ari-core/ari/viz/frontend/src/shared/realtime/__tests__/eventStream.test.ts
    role: test
  - path: ari-core/ari/viz/frontend/src/hooks/__tests__/useRunEvents.test.tsx
    role: test
  - path: docs/guides/gui_cutover_runbook.md
    role: doc
  - path: docs/guides/dashboard.md
    role: doc
last_verified: 2026-08-13
---

# GUI-ADR-03: SSE and legacy WebSocket coexistence

Status: accepted (2026-07-23), GUI refresh program, backend/realtime workstream.

Decision: the new realtime channel is `GET /api/v1/events/stream`, served as SSE
on the same origin and the same HTTP port, introduced in Wave 2b; the legacy
tree WebSocket on HTTP port + 1 keeps running in parallel rather than being cut
over. Removal of the WebSocket is a separate, one-way decision taken at the
legacy-removal gate (G6) on usage evidence, not at the moment SSE ships.

Alternatives: generalising the existing WebSocket into the program's realtime
channel lost because that socket is a single channel carrying a single message
type (`{"type": "update"}`), a read-only tree push driven by a one-second mtime
watcher, on a second port that proxies and portals do not forward — the reason
the charter listed "the coexistence period of SSE and the legacy WebSocket"
among the decisions to record as an ADR in the first place. Two SSE streams
already ran on the same origin — `GET /api/logs` and
`GET /api/paperbench/run/{job_id}/logs`, the latter with `Last-Event-ID` resume
with each connection capped at five minutes so a stuck job cannot hold a
worker thread, the browser reconnecting with `Last-Event-ID` when it needs
more — so the new stream generalises a proven pattern
instead of inventing one. Cutting the WebSocket over at introduction lost
because the plan required dual running until SSE parity was confirmed, and
because the charter promised to hold the tree-update contract until SSE was
stable; parity was to be established by shadow comparison against the existing
poll/WebSocket path before anything was deleted.

Consequences accepted: tree changes are published twice for the whole migration
— `state_sync._publish_tree_changed` fires on the same watcher tick as the
WebSocket `_broadcast`. The port + 1 dependency therefore survives until
removal, so the proxy/portal constraint SSE was chosen to escape is not actually
relieved until the socket is deleted, and the CSP `connect-src` must keep
allowing `ws://`/`wss://` until then. Duplicate, out-of-order, and reconnect
behaviour on the SSE side is carried by treating events as invalidations rather
than data: every event names a `/api/v1` resource the client refetches.

Compatibility: removal is gated, ordered, and documented in
`docs/guides/gui_cutover_runbook.md` under "6. Legacy removal", whose removal
table makes the port + 1 WebSocket (the `ws_serve` server, `websocket.py`, and
`hooks/useWebSocket.ts`) item 4, conditioned on every realtime consumer reading
`GET /api/v1/events/stream` first, and only then dropping the `ws://`/`wss://`
CSP sources. The user-facing behaviour of both channels is described in
`docs/guides/dashboard.md` under "Live updates, staleness, and reconnection".
Reversing this ADR means deleting the SSE bus and its publication hooks, which
would strand every v2 workspace on polling.

Divergences from the record, as of this migration. (1) The ADR said the
frontend would keep the WebSocket as the SSE fallback until removal; it does
not. `shared/realtime/eventStream.ts` falls back to a bounded ten-second poll
tick after sixty seconds offline (`POLL_INTERVAL_MS`, `OFFLINE_AFTER_MS`), and
`useWebSocket` is imported only by `context/AppContext.tsx`, the legacy shell,
whose own fallback is the five-second `/state` poll. The two channels run in
parallel with disjoint consumers; neither is the other's fallback. (2) No
shadow-comparison measurement exists. Parity is structural — the SSE `tree`
publish sits at the exact call site of the WebSocket broadcast — and is pinned
by a test, not by a measured comparison. (3) No WebSocket-fallback rate
telemetry exists to gate removal on. `GET /api/v1/diagnostics` reports SSE
scalars only (`sse.subscribers`, `buffer_len`, `last_event_id`) and the
`/health/ready` `websocket` check is a boolean "the WS server started";
WebSocket handshakes go through `ws_serve`, not the HTTP handler that writes
`viz_access.jsonl`, so the runbook's usage evidence covers legacy `/api/*`
traffic but not this socket.

Supersedes: nothing; this is the first decision on the realtime channel. Its
removal gate follows the feature-flag and legacy-removal policy of ADR-07.
Owning tests: `ari-core/tests/test_gui_v1_events.py` (event contract,
ring-buffer replay, `Last-Event-ID` resume, SSE framing, the endpoint branch,
and `test_watcher_publishes_tree_event_on_mtime_change`, which pins the
dual-running publication point), plus the frontend
`shared/realtime/__tests__/eventStream.test.ts` and
`hooks/__tests__/useRunEvents.test.tsx`.
