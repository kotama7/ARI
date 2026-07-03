// ARI Dashboard – Developer Mode gate (subtask 071).
//
// A single client-only flag that hides the raw/debug/secret/dangerous UI
// affordances (Raw JSON tab, env-key readback, SLURM auto-resubmit, raw-YAML
// editor, full stack traces) behind an opt-in toggle. Default OFF gives a
// product-safe view; ON restores every diagnostic.
//
// The flag lives ONLY in localStorage['ari_dev_mode'] ('1' = ON, absent/'0' =
// OFF) — nothing on the wire changes, no /api/settings key, no Settings type
// field. This mirrors the `ari_lang` language-persistence pattern
// (i18n/index.ts) but FIXES its cross-instance weakness: a same-tab custom
// event plus the cross-tab `storage` event keep every mounted hook instance in
// sync, so flipping the toggle updates all gated surfaces without a reload.

import { useCallback, useEffect, useState } from 'react';

const DEV_MODE_KEY = 'ari_dev_mode';
const DEV_MODE_EVENT = 'ari-dev-mode-change';

/**
 * isDevMode — read the developer-mode flag directly from localStorage. Safe to
 * call OUTSIDE the React tree (e.g. the top-level ErrorBoundary in main.tsx,
 * which cannot use hooks). Never throws.
 */
export function isDevMode(): boolean {
  try {
    return localStorage.getItem(DEV_MODE_KEY) === '1';
  } catch {
    return false;
  }
}

/**
 * useDevMode — reactive developer-mode flag + setter.
 *
 * Returns `{ devMode, setDevMode }`. `setDevMode(on)` persists to localStorage
 * and broadcasts a `DEV_MODE_EVENT` so every other mounted `useDevMode`
 * instance re-reads the flag and re-renders its gated surfaces immediately.
 */
export function useDevMode(): { devMode: boolean; setDevMode: (on: boolean) => void } {
  const [devMode, setDevModeState] = useState<boolean>(() => isDevMode());

  useEffect(() => {
    const sync = () => setDevModeState(isDevMode());
    window.addEventListener(DEV_MODE_EVENT, sync);
    window.addEventListener('storage', sync);
    return () => {
      window.removeEventListener(DEV_MODE_EVENT, sync);
      window.removeEventListener('storage', sync);
    };
  }, []);

  const setDevMode = useCallback((on: boolean) => {
    try {
      localStorage.setItem(DEV_MODE_KEY, on ? '1' : '0');
    } catch {
      // ignore storage failures (e.g. private mode); local state still updates
    }
    setDevModeState(on);
    window.dispatchEvent(new Event(DEV_MODE_EVENT));
  }, []);

  return { devMode, setDevMode };
}
