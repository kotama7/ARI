import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { ensureLocale, isLocaleReady, storedLang } from './index';

/**
 * I18nProvider — startup ready-gate for the lazily loaded locale dicts
 * (gui_refresh task 09 §Performance architecture, Wave 4d main-chunk work).
 *
 * Holds the first render until the ACTIVE locale ('ari_lang', default 'ja')
 * and the `en` fallback dictionary have loaded (~50 ms locally), so every
 * component below can keep calling the synchronous `t()` from useI18n/useT
 * with the full dictionary present — no key flash, no per-call suspense.
 *
 * While loading it renders nothing: the gate sits above <Layout>, and the
 * common loading components themselves consume `t()`, so rendering them here
 * would flash raw keys. In tests the dicts are preloaded via registerDicts()
 * (vitest.setup.ts), making the initial `ready` computation true and the
 * whole gate synchronous.
 */
export function I18nProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState<boolean>(
    () => isLocaleReady(storedLang()) && isLocaleReady('en'),
  );

  useEffect(() => {
    if (ready) return;
    let cancelled = false;
    void Promise.all([ensureLocale(storedLang()), ensureLocale('en')]).then(
      () => {
        if (!cancelled) setReady(true);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [ready]);

  if (!ready) return null;
  return <>{children}</>;
}
