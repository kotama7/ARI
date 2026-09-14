// ARI Dashboard – shared react-query client (gui_refresh Wave 2b).
//
// State ownership: every `/api/v1` read goes through this ONE client, so all
// server state lives in the query cache and nowhere else. Keys are
// `['v1', <projectId | runId>, <resource>]` — the identifier sits INSIDE the
// key, so two runs can never share an entry and dropping `['v1', runId]`
// drops exactly one run's server state. View state (which tab is open, a
// filter box's text) stays local and ephemeral; navigation state stays in the
// URL. Mutations are never optimistic: the server's answer is what the UI
// adopts, and the affected keys are invalidated instead of being written
// through. See docs/concepts/gui_architecture.md, "4. Server state lives in a
// cache, keyed by run".
//
// Defaults (gui_refresh Wave 2b):
//   - staleTime 5000ms: matches the historical /state 5s polling cadence, so
//     remounts within that window serve cache instead of refetching.
//   - retry 1: one retry for transient loopback hiccups; typed 404s are not
//     worth hammering (per-query overrides can inspect ApiErrorV1.retryable).
//   - refetchOnWindowFocus false: this is a local dashboard — focus flapping
//     must not trigger request storms against the checkpoint scanner.
//
// `createQueryClient` exists so tests can build an isolated client per render;
// the app singleton below is what App.tsx hands to QueryClientProvider.

import { QueryClient } from '@tanstack/react-query';

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 5000,
        retry: 1,
        refetchOnWindowFocus: false,
      },
    },
  });
}

/** App-wide singleton handed to QueryClientProvider in App.tsx. */
export const queryClient = createQueryClient();
