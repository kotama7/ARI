// ARI Dashboard – shared realtime SSE client (gui_refresh Wave 2b, ADR-03).
// Design rule: docs/concepts/gui_architecture.md, "6. Realtime is
// invalidation, not a source of truth". Wire contract — event fields, topic
// vocabulary, replay, heartbeat, cursor: docs/reference/rest_api.md,
// "Realtime: `GET /api/v1/events/stream` (SSE)".
//
// Wraps a browser `EventSource` on `GET /api/v1/events/stream`. Events are
// notifications/invalidations, NEVER a source of truth: the consumer maps
// each event to a query-cache invalidation and refetches the snapshot
// resource (useRunEvents.ts does exactly that).
//
// Contract implemented here:
//   - subscribe(runId, topics, callbacks): one stream per subscription;
//     topic/run filtering happens server-side via query params so background
//     surfaces don't pay for events they never render — a subscription
//     follows the mounted route and its run, and dies with it.
//   - Last-Event-ID cursor: the browser only resends the `Last-Event-ID`
//     HEADER on its own native auto-reconnect. Our manual backoff reconnect
//     creates a NEW EventSource, so the cursor is carried as the
//     `last_event_id` query param instead (routes.py accepts it as a header
//     fallback). Combined with the consumer's snapshot refetch that is the
//     whole reconnect recipe — resume from the cursor, then refetch the
//     snapshot — which is why an event evicted from the server's ring
//     buffer costs nothing: the refetch covers the gap.
//   - Reconnect: exponential backoff 1s → 2s → 4s … capped at 30s,
//     deliberately jitterless so tests can pin the exact sequence.
//   - connectionState: 'live' | 'reconnecting' | 'offline'. Starts 'live'
//     (optimistic: the page just fetched its HTTP snapshot, so nothing is
//     stale yet and the banner must not flash on mount); first error flips
//     to 'reconnecting'; errors persisting > 60s flip to 'offline'.
//   - Polling fallback: ONLY once 'offline' — polling is the bounded last
//     resort for when SSE cannot hold, never a second channel running
//     alongside a healthy stream. A bounded 10s tick fires `onPollTick` so the
//     consumer can invalidate its subscribed scope; reconnect attempts keep
//     running underneath and a successful open stops the polling again.

import { getGuiToken } from '../../services/api/client';

export type EventTopic = 'run' | 'tree';
export type ConnectionState = 'live' | 'reconnecting' | 'offline';

/** Frozen wire shape of one stream event — the server is the authority for
 * it, this is a mirror (see ari/viz/v1/events.py). */
export interface StreamEvent {
  event_id: string;
  run_id: string;
  topic: EventTopic;
  revision: number;
  occurred_at: string;
  kind: string;
  resource: string;
  payload: Record<string, unknown>;
}

export interface EventStreamCallbacks {
  /** One parsed stream event. Unparseable frames are dropped silently. */
  onEvent: (event: StreamEvent) => void;
  /** Fired on every state CHANGE (never with the same state twice in a row). */
  onConnectionState?: (state: ConnectionState) => void;
  /** Bounded polling fallback tick — fires every POLL_INTERVAL_MS while offline. */
  onPollTick?: () => void;
}

export interface EventStreamHandle {
  /** Tear the stream down (timers + socket). Idempotent. */
  close: () => void;
  getConnectionState: () => ConnectionState;
  /** Cursor of the last delivered event (null before the first delivery). */
  getLastEventId: () => string | null;
}

export const STREAM_PATH = '/api/v1/events/stream';
export const INITIAL_BACKOFF_MS = 1_000;
export const MAX_BACKOFF_MS = 30_000;
export const OFFLINE_AFTER_MS = 60_000;
export const POLL_INTERVAL_MS = 10_000;

/** The one SSE event name the backend publishes (`event:` field); topic, not
 * event name, is what distinguishes a frame. */
const EVENT_NAME = 'resource.changed';

function buildUrl(
  runId: string | null,
  topics: readonly EventTopic[],
  lastEventId: string | null,
): string {
  const params = new URLSearchParams();
  if (topics.length > 0) params.set('topics', topics.join(','));
  if (runId) params.set('run_id', runId);
  if (lastEventId !== null) params.set('last_event_id', lastEventId);
  // MN-8 (ADR-13): EventSource cannot set an Authorization header, so the
  // remote-mode token rides the query string; unset in the loopback default.
  const token = getGuiToken();
  if (token !== null) params.set('token', token);
  const qs = params.toString();
  return qs === '' ? STREAM_PATH : `${STREAM_PATH}?${qs}`;
}

export function subscribe(
  runId: string | null,
  topics: readonly EventTopic[],
  callbacks: EventStreamCallbacks,
): EventStreamHandle {
  let es: EventSource | null = null;
  let state: ConnectionState = 'live';
  let lastEventId: string | null = null;
  let backoffMs = INITIAL_BACKOFF_MS;
  let closed = false;

  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let offlineTimer: ReturnType<typeof setTimeout> | null = null;
  let pollTimer: ReturnType<typeof setInterval> | null = null;

  const setState = (next: ConnectionState) => {
    if (closed || next === state) return;
    state = next;
    callbacks.onConnectionState?.(next);
  };

  const stopPolling = () => {
    if (pollTimer !== null) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  };

  const clearOfflineTimer = () => {
    if (offlineTimer !== null) {
      clearTimeout(offlineTimer);
      offlineTimer = null;
    }
  };

  const handleOpen = () => {
    if (closed) return;
    backoffMs = INITIAL_BACKOFF_MS;
    clearOfflineTimer();
    stopPolling();
    setState('live');
  };

  const handleMessage = (ev: MessageEvent) => {
    if (closed) return;
    let event: StreamEvent;
    try {
      event = JSON.parse(String(ev.data)) as StreamEvent;
    } catch {
      return; // malformed frame: the snapshot refetch covers any gap
    }
    lastEventId = ev.lastEventId || event.event_id || lastEventId;
    callbacks.onEvent(event);
  };

  const goOffline = () => {
    offlineTimer = null;
    if (closed) return;
    setState('offline');
    if (pollTimer === null) {
      pollTimer = setInterval(() => callbacks.onPollTick?.(), POLL_INTERVAL_MS);
    }
  };

  const handleError = () => {
    if (closed) return;
    // Manual reconnect: drop the native auto-retry (it could not carry our
    // query-param cursor anyway) and rebuild the source after the backoff.
    es?.close();
    es = null;
    if (state !== 'offline') {
      setState('reconnecting');
      if (offlineTimer === null) {
        offlineTimer = setTimeout(goOffline, OFFLINE_AFTER_MS);
      }
    }
    reconnectTimer = setTimeout(connect, backoffMs);
    backoffMs = Math.min(backoffMs * 2, MAX_BACKOFF_MS);
  };

  const connect = () => {
    reconnectTimer = null;
    if (closed) return;
    const source = new EventSource(buildUrl(runId, topics, lastEventId));
    es = source;
    source.onopen = handleOpen;
    source.onerror = handleError;
    // The backend frames events with `event: resource.changed`; onmessage
    // additionally covers any unnamed frame a proxy might rewrite.
    source.addEventListener(EVENT_NAME, handleMessage as EventListener);
    source.onmessage = handleMessage;
  };

  connect();

  return {
    close: () => {
      if (closed) return;
      closed = true;
      if (reconnectTimer !== null) clearTimeout(reconnectTimer);
      clearOfflineTimer();
      stopPolling();
      es?.close();
      es = null;
    },
    getConnectionState: () => state,
    getLastEventId: () => lastEventId,
  };
}
