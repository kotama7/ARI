import { useState, useCallback } from 'react';

type Dict = Record<string, string>;

// ── per-locale lazy loading (gui_refresh task 09 §Performance architecture) ──
//
// The three dictionaries (~118 KB of source, ~20 KB gzip) used to be imported
// statically here, which pulled ALL of them into the main chunk for every
// visitor. They are now code-split via dynamic import: at startup the
// I18nProvider (./I18nProvider.tsx) loads only the ACTIVE locale plus the
// `en` fallback and holds the first render (~50 ms locally) until both
// resolve, so `t()` stays fully synchronous for every component underneath.
//
// The dictionary modules themselves are untouched: they keep their static
// default exports, so the key-set parity test (and any tooling) can still
// import them directly (`import en from './en'`).
//
// Tests: vitest.setup.ts imports all three dicts eagerly and calls
// registerDicts(), so component tests render final strings synchronously
// without needing the provider or any async act() dance.

const DICT_LOADERS: Record<string, () => Promise<{ default: Dict }>> = {
  en: () => import('./en'),
  ja: () => import('./ja'),
  zh: () => import('./zh'),
};

// Module-level cache shared by every hook instance. Filled by ensureLocale()
// (production) or registerDicts() (tests / eager environments).
const loadedDicts: Record<string, Dict> = {};

const pendingLoads: Record<string, Promise<void>> = {};

/** True once `lang` needs no further loading (cached, or unknown → en path). */
export function isLocaleReady(lang: string): boolean {
  return Boolean(loadedDicts[lang]) || !DICT_LOADERS[lang];
}

/**
 * Load `lang`'s dictionary into the module cache (idempotent, deduped).
 * Unknown locales resolve immediately — `t()` then falls back to `en`/key,
 * exactly like the previous static lookup did. A failed chunk fetch also
 * resolves (the app must render, degrading to `en`/keys) rather than reject.
 */
export function ensureLocale(lang: string): Promise<void> {
  if (isLocaleReady(lang)) return Promise.resolve();
  if (!pendingLoads[lang]) {
    pendingLoads[lang] = DICT_LOADERS[lang]()
      .then((mod) => {
        loadedDicts[lang] = mod.default;
      })
      .catch(() => {
        /* degrade to en/key fallback; a later ensureLocale may retry */
        delete pendingLoads[lang];
      });
  }
  return pendingLoads[lang];
}

/**
 * Synchronously seed the dictionary cache. Test setup (vitest.setup.ts)
 * uses this so `t()` resolves real strings without any async loading.
 */
export function registerDicts(dicts: Record<string, Dict>): void {
  Object.assign(loadedDicts, dicts);
}

/** The persisted UI language ('ari_lang', default 'ja') — shared reader. */
export function storedLang(): string {
  return localStorage.getItem('ari_lang') || 'ja';
}

export function useI18n() {
  const [currentLang, setCurrentLangState] = useState<string>(storedLang);

  const t = useCallback(
    (key: string): string => {
      const dict = loadedDicts[currentLang] || loadedDicts.en || {};
      return dict[key] || (loadedDicts.en || {})[key] || key;
    },
    [currentLang],
  );

  const setLanguage = useCallback((lang: string) => {
    localStorage.setItem('ari_lang', lang);
    if (isLocaleReady(lang)) {
      // Cached (or unknown) locale: switch synchronously, exactly like the
      // pre-split behavior — tests and repeat switches take this path.
      setCurrentLangState(lang);
    } else {
      // First switch to a not-yet-loaded locale: fetch the chunk, then flip
      // the state so the re-render sees the full dictionary (no key flash).
      void ensureLocale(lang).then(() => setCurrentLangState(lang));
    }
  }, []);

  return { t, setLanguage, currentLang };
}

/**
 * useT — convenience hook returning only the `t` function from useI18n.
 *
 * Component code that doesn't need to mutate the language can write
 * ``const t = useT()`` instead of ``const { t } = useI18n()``. Mirrors
 * the conventional `useTranslation()` → `t` pattern from react-i18next.
 */
export function useT() {
  return useI18n().t;
}
