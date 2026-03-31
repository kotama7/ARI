// ARI Dashboard – useApi hook
// Generic data-fetching hook with loading / error / refetch support.

import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Fetch data via an async function and expose loading / error state.
 *
 * @param fetcher  An async function that returns the desired data (e.g. `() => fetchSettings()`).
 * @returns `{ data, loading, error, refetch }`
 */
export function useApi<T>(
  fetcher: () => Promise<T>,
): { data: T | null; loading: boolean; error: string | null; refetch: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Keep a stable reference to the latest fetcher to avoid re-triggering
  // the effect when the caller creates a new arrow function each render.
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const execute = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetcherRef.current();
      setData(result);
    } catch (err: any) {
      setError(err?.message ?? String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    execute();
  }, [execute]);

  return { data, loading, error, refetch: execute };
}
