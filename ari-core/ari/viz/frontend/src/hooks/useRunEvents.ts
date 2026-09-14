// ARI Dashboard – realtime → query-cache glue (gui_refresh Wave 2b, ADR-03;
// docs/concepts/gui_architecture.md, "6. Realtime is invalidation, not a
// source of truth").
//
// Subscribes the shared SSE client (shared/realtime/eventStream.ts) for the
// lifetime of the calling component and maps each stream event to a
// react-query invalidation. Events are invalidations, never data: the query
// cache refetches the /api/v1 snapshot, so duplicate or out-of-order events
// are harmless.
//
// Isolation — run-scoped queries and events are keyed by run_id, never by
// the mounted route, so two runs open in two tabs cannot step on each other:
// every invalidation is keyed by the EVENT'S run_id —
//   - topic 'tree' → ['v1', run_id, 'tree']
//   - topic 'run'  → ['v1', run_id, 'run'] + ['v1', run_id, 'summary'], plus
//     the project-scoped runs LISTS (['v1', <projectId>, 'runs']) whose rows
//     embed that run's summary (the event does not carry a project_id, so
//     every list is refreshed; lists are aggregates, not run-scoped state).
// An event for run B can therefore never touch run A's cache entries.
//
// The bounded polling fallback tick (SSE down > 60s) invalidates only the
// subscription's own scope: ['v1', runId] when run-filtered, the whole
// ['v1'] server state for an unfiltered (list) subscription — we missed an
// unknown set of events, so any of it may be stale; only mounted queries
// actually refetch.

import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  subscribe,
  type ConnectionState,
  type EventTopic,
  type StreamEvent,
} from '../shared/realtime/eventStream';
import { v1Keys } from './useV1';

export interface RunEventsState {
  /** 'live' | 'reconnecting' | 'offline' — drives the StaleDataBanner. */
  connectionState: ConnectionState;
  /** Epoch ms of the last delivered event; null before the first one. */
  lastEventAt: number | null;
}

/**
 * Keep the query cache fresh from `/api/v1/events/stream`.
 *
 * @param runId  server-side run filter; null subscribes unfiltered (lists).
 * @param topics topic filter ('run' | 'tree'); pass a stable or literal
 *               array — identity changes are absorbed via serialization.
 */
export function useRunEvents(
  runId: string | null,
  topics: readonly EventTopic[],
): RunEventsState {
  const queryClient = useQueryClient();
  const [connectionState, setConnectionState] = useState<ConnectionState>('live');
  const [lastEventAt, setLastEventAt] = useState<number | null>(null);
  // Effect identity from the VALUE of topics, not the array reference.
  const topicsKey = topics.join(',');

  useEffect(() => {
    const topicList =
      topicsKey === '' ? [] : (topicsKey.split(',') as EventTopic[]);

    const invalidate = (event: StreamEvent) => {
      if (event.topic === 'tree') {
        void queryClient.invalidateQueries({
          queryKey: v1Keys.runTree(event.run_id),
        });
        return;
      }
      // topic 'run' — the run's own detail + summary snapshots …
      void queryClient.invalidateQueries({ queryKey: v1Keys.run(event.run_id) });
      void queryClient.invalidateQueries({
        queryKey: v1Keys.runSummary(event.run_id),
      });
      // … plus any project runs list embedding that run's summary row
      // (key shape ['v1', projectId, 'runs'] — index 2 is 'runs' only for
      // lists, so run-scoped keys of OTHER runs can never match).
      void queryClient.invalidateQueries({
        predicate: (q) =>
          q.queryKey[0] === 'v1' && q.queryKey[2] === 'runs',
      });
    };

    const handle = subscribe(runId, topicList, {
      onEvent: (event) => {
        setLastEventAt(Date.now());
        invalidate(event);
      },
      onConnectionState: setConnectionState,
      onPollTick: () => {
        void queryClient.invalidateQueries({
          queryKey: runId ? ([...v1Keys.all, runId] as const) : v1Keys.all,
        });
      },
    });
    return () => handle.close();
  }, [runId, topicsKey, queryClient]);

  return { connectionState, lastEventAt };
}
