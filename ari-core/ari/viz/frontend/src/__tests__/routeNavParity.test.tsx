import { describe, it, expect } from 'vitest';
// Vite's ?raw suffix inlines a file's source text as a string (resolved by the
// vitest/vite transform pipeline). PAGE_MAP (App.tsx) and NAV_ITEMS
// (Sidebar.tsx) are module-local (not exported), so this reads the real source
// and parses the declarations statically — an honest test of current behavior
// without touching runtime code. node:fs is avoided because @types/node is not
// installed (would break `tsc --noEmit`).
import appSrc from '../App.tsx?raw';
import sidebarSrc from '../components/Layout/Sidebar.tsx?raw';

// `?raw` module types come from vite/client (src/vite-env.d.ts), so no local
// ambient declaration is needed.

/**
 * Tier-1 route <-> nav parity (subtask 073 §7.4; gates the 067 route-registry
 * work and the Problem #4 manual drift where Sidebar omits paperbench/*). Every
 * PAGE_MAP route must have a NAV_ITEMS entry or be an explicit hidden route (the
 * new->wizard alias target + the paperbench/* sub-routes, App.tsx:37/47-56).
 */

function pageMapKeys(src: string): string[] {
  const start = src.indexOf('PAGE_MAP');
  const block = src.slice(start, src.indexOf('};', start));
  const keys: string[] = [];
  for (const line of block.split('\n')) {
    const m = line.match(/^\s*(?:'([^']+)'|"([^"]+)"|([A-Za-z_$][\w$]*))\s*:/);
    if (!m) continue;
    const key = m[1] ?? m[2] ?? m[3];
    if (key === 'PAGE_MAP') continue; // the `Record<...>` type annotation line
    keys.push(key);
  }
  return keys;
}

function navKeys(src: string): string[] {
  const start = src.indexOf('NAV_ITEMS');
  const block = src.slice(start, src.indexOf('];', start));
  const keys: string[] = [];
  const re = /(?<![A-Za-z])key\s*:\s*'([^']+)'/g; // not labelKey
  let m: RegExpExecArray | null;
  while ((m = re.exec(block)) !== null) keys.push(m[1]);
  return keys;
}

const HIDDEN_ROUTES = new Set([
  'wizard',
  'paperbench/import',
  'paperbench/run',
  'paperbench/results',
]);

describe('route <-> nav parity (Tier-1; gates 067 route-registry drift)', () => {
  it('every PAGE_MAP route has a nav entry or is an explicit hidden route', () => {
    const routes = pageMapKeys(appSrc);
    const nav = new Set(navKeys(sidebarSrc));
    const orphans = routes.filter((r) => !nav.has(r) && !HIDDEN_ROUTES.has(r));
    expect(orphans).toEqual([]);
  });

  it('extracts the expected route + nav key sets', () => {
    const routes = pageMapKeys(appSrc);
    const nav = navKeys(sidebarSrc);
    // Guards against the parser silently matching nothing (which would make the
    // orphan check vacuously pass).
    expect(routes).toContain('home');
    expect(routes).toContain('paperbench/import');
    expect(routes.length).toBeGreaterThanOrEqual(12);
    expect(nav).toContain('home');
    expect(nav).not.toContain('nav_home'); // labelKey values are excluded
    expect(nav.length).toBeGreaterThanOrEqual(10);
  });
});
