// ARI Dashboard – shared react-query client (gui_refresh Wave 2b, plan 03
// §State ownership: server state lives in the query cache).
//
// Defaults (task 03 Wave 2b):
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
