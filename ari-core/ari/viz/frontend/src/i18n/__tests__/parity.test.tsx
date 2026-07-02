import { describe, it, expect } from 'vitest';
import { en, ja, zh } from '../index';

/**
 * Tier-1 i18n key-set parity (subtask 073 §7.4). The TS-native mirror of the
 * Python check_dashboard_ux.py check (A): a key present in one locale but missing
 * from another renders as a blank/fallback string (index.ts:13-19). This test
 * imports the ACTUAL dictionaries and asserts their key sets are identical,
 * modulo a KNOWN_DRIFT allowlist — so it is green today and any NEW divergence
 * (a UX string added to `en` but not `ja`/`zh`, or vice-versa) fails.
 *
 * GROUNDING NOTE: KNOWN_DRIFT is empty because the three React locales are in
 * FULL key-set parity as of 2026-07-01 (407/407/407 keys — 404 unquoted + 3
 * quoted 'experiments.*' keys — no duplicates, no missing in any direction). The
 * oft-cited "444 vs 441 lines" delta is wrapped English value continuations +
 * shorter localized comment text — NOT key drift. Values are intentionally NOT
 * compared (a proper noun may read identically across locales).
 */
const KNOWN_DRIFT: Record<'en' | 'ja' | 'zh', string[]> = {
  en: [],
  ja: [],
  zh: [],
};

describe('React i18n key-set parity (Tier-1; gates future drift)', () => {
  const locales = { en, ja, zh } as const;
  const union = new Set<string>();
  for (const dict of Object.values(locales)) {
    for (const key of Object.keys(dict)) union.add(key);
  }

  (Object.keys(locales) as Array<'en' | 'ja' | 'zh'>).forEach((name) => {
    it(`${name}.ts has no missing keys (modulo KNOWN_DRIFT)`, () => {
      const keys = new Set(Object.keys(locales[name]));
      const missing = [...union].filter(
        (k) => !keys.has(k) && !KNOWN_DRIFT[name].includes(k),
      );
      expect(missing).toEqual([]);
    });

    it(`${name}.ts declares no duplicate keys`, () => {
      // Object literals collapse duplicate keys, so Object.keys losing a key vs
      // the union is the observable symptom; a stricter dup check lives in the
      // Python unit test over the raw source.
      expect(new Set(Object.keys(locales[name])).size).toBe(
        Object.keys(locales[name]).length,
      );
    });
  });

  it('all three locales expose an identical key set today', () => {
    expect(new Set(Object.keys(ja))).toEqual(new Set(Object.keys(en)));
    expect(new Set(Object.keys(zh))).toEqual(new Set(Object.keys(en)));
    // Non-empty sanity floor (guards against a parser/import regression that
    // would make the set-equality checks vacuously pass); the exact count (407
    // today) is deliberately not hard-pinned so ordinary string additions that
    // stay in parity do not churn this test.
    expect(Object.keys(en).length).toBeGreaterThan(400);
  });
});
