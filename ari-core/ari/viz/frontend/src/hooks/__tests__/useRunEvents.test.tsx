import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useRunEvents } from '../useRunEvents';
import { v1Keys } from '../useV1';
import {
  OFFLINE_AFTER_MS,
  POLL_INTERVAL_MS,
  type StreamEvent,
} from '../../shared/realtime/eventStream';

/**
 * useRunEvents (gui_refresh Wave 2b, ADR-03): realtime is invalidation, not a
 * source of truth. An SSE event for a run maps to a query-cache invalidation of
 * that run's keys followed by a refetch of the HTTP snapshot — never to a
 * direct state write — so duplicate or reordered events are harmless and
 * nothing on screen is ever assembled from an event payload.
 *
 * Renders the hook against a seeded QueryClient and a controllable
 * FakeEventSource, pinning the event → invalidation glue:
 *   - topic 'tree' invalidates ONLY that run's ['v1', run_id, 'tree'] key;
 *   - topic 'run' invalidates that run's detail/summary keys plus the
 *     project runs lists (rows embed the run's summary);
 *   - two-run isolation: an event for run B never invalidates run A keys;
 *   - connectionState + lastEventAt are exposed for the StaleDataBanner;
 *   - the offline poll tick invalidates only the subscription's own scope;
 *   - unmount closes the stream (no invalidation after teardown).
 */

class FakeES {
  static instances: FakeES[] = [];
  url: string;
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

  removeEventListener() {}

  close() {
    this.closed = true;
  }

  open() {
    this.onopen?.(new Event('open'));
  }

  emit(event: Partial<StreamEvent> & { event_id: string; run_id: string }) {
    const full = {
      topic: 'run',
      revision: 1,
      occurred_at: '2026-07-23T00:00:00Z',
      kind: 'resource.changed',
      resource: `/api/v1/runs/${event.run_id}/summary`,
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

function makeClient(): QueryClient {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  // Seed cache entries whose invalidation flags we assert on.
  client.setQueryData(v1Keys.runSummary('run-a'), { run_id: 'run-a' });
  client.setQueryData(v1Keys.runSummary('run-b'), { run_id: 'run-b' });
  client.setQueryData(v1Keys.run('run-b'), { run_id: 'run-b' });
  client.setQueryData(v1Keys.runTree('run-a'), { nodes: [] });
  client.setQueryData(v1Keys.runTree('run-b'), { nodes: [] });
  client.setQueryData(v1Keys.runs('proj-1'), { runs: [] });
  client.setQueryData(v1Keys.projects(), { projects: [] });
  return client;
}

const invalidated = (client: QueryClient, key: readonly unknown[]) =>
  client.getQueryState(key as unknown[])?.isInvalidated ?? false;

function renderRunEvents(
  client: QueryClient,
  runId: string | null,
  topics: Array<'run' | 'tree'>,
) {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return renderHook(() => useRunEvents(runId, topics), { wrapper });
}

beforeEach(() => {
  FakeES.instances = [];
  vi.stubGlobal('EventSource', FakeES);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('useRunEvents', () => {
  it("invalidates run B's keys and the runs lists on a 'run' event — run A untouched", () => {
    const client = makeClient();
    renderRunEvents(client, null, ['run']);

    act(() => {
      last().open();
      last().emit({ event_id: '1', run_id: 'run-b', topic: 'run' });
    });

    // Run B: detail + summary invalidated; lists refreshed.
    expect(invalidated(client, v1Keys.run('run-b'))).toBe(true);
    expect(invalidated(client, v1Keys.runSummary('run-b'))).toBe(true);
    expect(invalidated(client, v1Keys.runs('proj-1'))).toBe(true);
    // Isolation: run A's cache entries are untouched, as is B's tree.
    expect(invalidated(client, v1Keys.runSummary('run-a'))).toBe(false);
    expect(invalidated(client, v1Keys.runTree('run-a'))).toBe(false);
    expect(invalidated(client, v1Keys.runTree('run-b'))).toBe(false);
    expect(invalidated(client, v1Keys.projects())).toBe(false);
  });

  it("invalidates ONLY that run's tree key on a 'tree' event", () => {
    const client = makeClient();
    renderRunEvents(client, 'run-b', ['tree']);

    act(() => {
      last().open();
      last().emit({ event_id: '1', run_id: 'run-b', topic: 'tree' });
    });

    expect(invalidated(client, v1Keys.runTree('run-b'))).toBe(true);
    expect(invalidated(client, v1Keys.runTree('run-a'))).toBe(false);
    expect(invalidated(client, v1Keys.runSummary('run-b'))).toBe(false);
    expect(invalidated(client, v1Keys.runs('proj-1'))).toBe(false);
  });

  it('exposes connectionState and lastEventAt for the StaleDataBanner', () => {
    const client = makeClient();
    const { result } = renderRunEvents(client, null, ['run']);

    expect(result.current.connectionState).toBe('live');
    expect(result.current.lastEventAt).toBeNull();

    const before = Date.now();
    act(() => {
      last().open();
      last().emit({ event_id: '1', run_id: 'run-a', topic: 'run' });
    });
    expect(result.current.lastEventAt).toBeGreaterThanOrEqual(before);

    act(() => {
      last().error();
    });
    expect(result.current.connectionState).toBe('reconnecting');
  });

  it('offline poll tick invalidates only the subscribed run scope', () => {
    vi.useFakeTimers();
    const client = makeClient();
    renderRunEvents(client, 'run-b', ['run', 'tree']);

    act(() => {
      last().open();
      last().error();
      vi.advanceTimersByTime(OFFLINE_AFTER_MS + POLL_INTERVAL_MS);
    });

    // Everything under ['v1', 'run-b'] is stale; run A and lists are not.
    expect(invalidated(client, v1Keys.run('run-b'))).toBe(true);
    expect(invalidated(client, v1Keys.runSummary('run-b'))).toBe(true);
    expect(invalidated(client, v1Keys.runTree('run-b'))).toBe(true);
    expect(invalidated(client, v1Keys.runSummary('run-a'))).toBe(false);
    expect(invalidated(client, v1Keys.runTree('run-a'))).toBe(false);
    expect(invalidated(client, v1Keys.runs('proj-1'))).toBe(false);
  });

  it('unmount closes the stream and stops invalidating', () => {
    const client = makeClient();
    const { unmount } = renderRunEvents(client, null, ['run']);
    const es = last();

    act(() => {
      es.open();
    });
    unmount();
    expect(es.closed).toBe(true);

    es.emit({ event_id: '9', run_id: 'run-b', topic: 'run' });
    expect(invalidated(client, v1Keys.runSummary('run-b'))).toBe(false);
  });
});
