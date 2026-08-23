/**
 * The served model/provider catalog, fetched once per page load.
 *
 * The server owns this list (`ari/viz/v1/catalogs.py`, re-serving the exact
 * `/api/models` payload). Frontend copies of it drifted: the Wizard table and
 * the Settings table disagreed with the server and with each other about which
 * OpenAI models exist, and nothing could notice, because each screen only ever
 * read its own copy.
 *
 * Failures are not fatal. An empty provider list makes every screen fall back
 * to its free-text model entry, which is the same path a provider the catalog
 * serves no models for already takes — the operator can still type a model,
 * they just lose the suggestions.
 */
import { useEffect, useState } from 'react';

import { fetchModelCatalogV1 } from '../services/api/v1';
import type { ModelProviderV1 } from '../services/api/v1';

/**
 * The model `<select>`'s "type it yourself" option. A UI mode marker, never a
 * model id — every screen resolves it to the free-text field's value before
 * saving or launching.
 */
export const CUSTOM_MODEL_VALUE = '__custom__';

// One in-flight request shared by every mount. Each screen mounting its own
// fetch is how a single catalog turned into several, one per component.
let cached: ModelProviderV1[] | null = null;
let inFlight: Promise<ModelProviderV1[]> | null = null;

function load(): Promise<ModelProviderV1[]> {
  if (cached) return Promise.resolve(cached);
  if (!inFlight) {
    inFlight = fetchModelCatalogV1()
      .then((envelope) => {
        cached = envelope.providers ?? [];
        return cached;
      })
      .catch(() => {
        // Not cached: a transient failure must not pin an empty catalog for
        // the rest of the session.
        inFlight = null;
        return [];
      });
  }
  return inFlight;
}

export interface ModelCatalog {
  providers: ModelProviderV1[];
  loaded: boolean;
  /** The models this provider serves, or `[]` for one it does not describe. */
  modelsFor: (providerId: string) => string[];
}

export function useModelCatalog(): ModelCatalog {
  const [providers, setProviders] = useState<ModelProviderV1[]>(cached ?? []);
  const [loaded, setLoaded] = useState(cached !== null);

  useEffect(() => {
    let cancelled = false;
    load().then((rows) => {
      if (cancelled) return;
      setProviders(rows);
      setLoaded(true);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return {
    providers,
    loaded,
    modelsFor: (providerId: string) =>
      providers.find((p) => p.id === providerId)?.models ?? [],
  };
}

/** Test seam: drop the shared cache so a suite can serve its own catalog. */
export function __resetModelCatalogCache(): void {
  cached = null;
  inFlight = null;
}
