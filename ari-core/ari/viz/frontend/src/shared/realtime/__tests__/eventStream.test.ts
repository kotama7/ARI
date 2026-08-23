import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  subscribe,
  INITIAL_BACKOFF_MS,
  MAX_BACKOFF_MS,
  OFFLINE_AFTER_MS,
  POLL_INTERVAL_MS,
  STREAM_PATH,
  type ConnectionState,
  type StreamEvent,
} from '../eventStream';

/**
 * eventStream (gui_refresh Wave 2b, ADR-03): the single owner of realtime over
 * /api/v1. Pages call subscribe(runId, topics, callbacks) — normally through
 * the useRunEvents hook — and never construct an EventSource themselves, so the
 * backoff schedule, the last_event_id cursor, the three-state connection
 * machine and the offline poll tick exist once and are tested once, here.
 *
 * Drives the SSE wrapper through a controllable FakeEventSource (the global
 * one in vitest.setup.ts is a no-op — this one records instances and lets
 * tests fire open/message/error) under fake timers, pinning:
 *   - the subscription URL (topics + run_id query params) and event delivery
 *     with Last-Event-ID cursor tracking;
 *   - the jitterless exponential backoff sequence 1s, 2s, 4s … capped 30s;
 *   - `last_event_id` sent as a query param on manual reconnect (the browser
 *     header only travels on NATIVE auto-reconnect — routes.py accepts the
 *     param as a fallback);
 *   - connectionState live → reconnecting → offline (> 60s) → live again;
 *   - the bounded 10s polling fallback tick that engages ONLY after the
 *     60s persistent-failure window and stops on reconnect: 'offline' is the
 *     one connection state allowed to poll, and it polls only the
 *     subscription's own scope.
 */

class FakeES {
  static instances: FakeES[] = [];
  url: string;
  readyState = 0;
  closed = false;
  onopen: ((ev: Event) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  private listeners = new Map<string, Array<(ev: MessageEvent) => void>>();

  constructor(url: string) {
    this.url = url;
    FakeES.instances.push(this);
  }

  addEventListener(type: string, fn: (ev: MessageEvent) => void) {
    const arr = this.listeners.get(type) ?? [];
    arr.push(fn);
    this.listeners.set(type, arr);
  }

  removeEventListener(type: string, fn: (ev: MessageEvent) => void) {
    this.listeners.set(
      type,
      (this.listeners.get(type) ?? []).filter((f) => f !== fn),
    );
  }

  close() {
    this.closed = true;
    this.readyState = 2;
  }

  // ── test drivers ──────────────────────────────────────────────────────
  open() {
    this.readyState = 1;
    this.onopen?.(new Event('open'));
  }

  /** Deliver one named `resource.changed` frame (like the backend sends). */
  emit(event: Partial<StreamEvent> & { event_id: string }) {
    const full: StreamEvent = {
      run_id: 'run-x',
      topic: 'run',
      revision: 1,
      occurred_at: '2026-07-23T00:00:00Z',
      kind: 'resource.changed',
      resource: `/api/v1/runs/${event.run_id ?? 'run-x'}/summary`,
      payload: {},
      ...event,
    };
    const msg = {
      data: JSON.stringify(full),
      lastEventId: full.event_id,
    } as MessageEvent;
    for (const fn of this.listeners.get('resource.changed') ?? []) fn(msg);
  }

  error() {
    this.onerror?.(new Event('error'));
  }
}

const last = () => FakeES.instances[FakeES.instances.length - 1];

beforeEach(() => {
  FakeES.instances = [];
  vi.stubGlobal('EventSource', FakeES);
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('eventStream.subscribe', () => {
  it('opens the filtered stream URL and delivers parsed events', () => {
    const onEvent = vi.fn();
    const handle = subscribe('run-a', ['run', 'tree'], { onEvent });

    expect(FakeES.instances).toHaveLength(1);
    const url = new URL(last().url, 'http://localhost');
    expect(url.pathname).toBe(STREAM_PATH);
    expect(url.searchParams.get('topics')).toBe('run,tree');
    expect(url.searchParams.get('run_id')).toBe('run-a');
    expect(url.searchParams.get('last_event_id')).toBeNull(); // no cursor yet

    last().open();
    expect(handle.getConnectionState()).toBe('live');

    last().emit({ event_id: '7', run_id: 'run-a', topic: 'tree' });
    expect(onEvent).toHaveBeenCalledTimes(1);
    expect(onEvent.mock.calls[0][0]).toMatchObject({
      event_id: '7',
      run_id: 'run-a',
      topic: 'tree',
      kind: 'resource.changed',
    });
    expect(handle.getLastEventId()).toBe('7');
    handle.close();
  });

  it('reconnects with the tracked Last-Event-ID as a query param', () => {
    const handle = subscribe(null, ['run'], { onEvent: vi.fn() });
    last().open();
    last().emit({ event_id: '42' });

    last().error();
    vi.advanceTimersByTime(INITIAL_BACKOFF_MS);

    expect(FakeES.instances).toHaveLength(2);
    const url = new URL(last().url, 'http://localhost');
    expect(url.searchParams.get('last_event_id')).toBe('42');
    expect(url.searchParams.get('topics')).toBe('run');
    expect(url.searchParams.get('run_id')).toBeNull(); // unfiltered list mode
    handle.close();
  });

  it('backs off 1s, 2s, 4s, 8s … capped at 30s (jitterless)', () => {
    const handle = subscribe(null, ['run'], { onEvent: vi.fn() });
    expect(FakeES.instances).toHaveLength(1);

    const expected = [1_000, 2_000, 4_000, 8_000, 16_000, 30_000, 30_000];
    expect(expected[0]).toBe(INITIAL_BACKOFF_MS);
    expect(expected[expected.length - 1]).toBe(MAX_BACKOFF_MS);

    let count = 1;
    for (const delay of expected) {
      last().error();
      vi.advanceTimersByTime(delay - 1);
      expect(FakeES.instances).toHaveLength(count); // not yet
      vi.advanceTimersByTime(1);
      count += 1;
      expect(FakeES.instances).toHaveLength(count); // exactly at the delay
    }
    handle.close();
  });

  it('a successful open resets the backoff to 1s', () => {
    const handle = subscribe(null, ['run'], { onEvent: vi.fn() });
    last().error();
    vi.advanceTimersByTime(1_000);
    last().error();
    vi.advanceTimersByTime(2_000); // backoff has grown to 4s by now
    last().open(); // …but a live connection resets it

    last().error();
    vi.advanceTimersByTime(INITIAL_BACKOFF_MS - 1);
    expect(FakeES.instances).toHaveLength(3);
    vi.advanceTimersByTime(1);
    expect(FakeES.instances).toHaveLength(4); // reconnect after 1s again
    handle.close();
  });

  it('emits live → reconnecting → offline (>60s) → live transitions', () => {
    const states: ConnectionState[] = [];
    const handle = subscribe(null, ['run'], {
      onEvent: vi.fn(),
      onConnectionState: (s) => states.push(s),
    });
    last().open();
    expect(states).toEqual([]); // starts live: no change emitted

    last().error();
    expect(states).toEqual(['reconnecting']);
    expect(handle.getConnectionState()).toBe('reconnecting');

    vi.advanceTimersByTime(OFFLINE_AFTER_MS);
    expect(states).toEqual(['reconnecting', 'offline']);

    // A pending reconnect attempt finally succeeds.
    last().open();
    expect(states).toEqual(['reconnecting', 'offline', 'live']);
    handle.close();
  });

  it('engages the bounded 10s poll tick only after 60s of failure, and stops on reconnect', () => {
    const onPollTick = vi.fn();
    const handle = subscribe(null, ['run'], { onEvent: vi.fn(), onPollTick });
    last().open();
    last().error();

    // Within the 60s window: NO polling — 'reconnecting' is not 'offline', and
    // only 'offline' may fall back to polling.
    vi.advanceTimersByTime(OFFLINE_AFTER_MS - 1);
    expect(onPollTick).not.toHaveBeenCalled();

    vi.advanceTimersByTime(1); // offline boundary
    expect(onPollTick).not.toHaveBeenCalled(); // interval starts counting now
    vi.advanceTimersByTime(POLL_INTERVAL_MS);
    expect(onPollTick).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(POLL_INTERVAL_MS * 2);
    expect(onPollTick).toHaveBeenCalledTimes(3);

    // Reconnect succeeds → polling stops immediately.
    last().open();
    expect(handle.getConnectionState()).toBe('live');
    vi.advanceTimersByTime(POLL_INTERVAL_MS * 5);
    expect(onPollTick).toHaveBeenCalledTimes(3);
    handle.close();
  });

  it('close() tears down the socket and all timers', () => {
    const onPollTick = vi.fn();
    const onEvent = vi.fn();
    const handle = subscribe(null, ['run'], { onEvent, onPollTick });
    last().error();
    handle.close();
    expect(last().closed).toBe(true);

    vi.advanceTimersByTime(OFFLINE_AFTER_MS + POLL_INTERVAL_MS * 3);
    expect(FakeES.instances).toHaveLength(1); // no reconnect after close
    expect(onPollTick).not.toHaveBeenCalled();
    expect(handle.getConnectionState()).toBe('reconnecting'); // frozen state
  });
});
