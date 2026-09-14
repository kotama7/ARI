import { describe, it, expect } from 'vitest';
import { PAGE_MAP } from '../App';
import { NAV_ITEMS } from '../components/Layout/Sidebar';

/**
 * Tier-1 route <-> nav parity (subtask 073 §7.4; gates the 067 route-registry
 * work and the Problem #4 manual drift where Sidebar omitted paperbench/*).
 *
 * gui_refresh Wave 1 task 03: PAGE_MAP (App.tsx) and NAV_ITEMS (Sidebar.tsx)
 * are now derived from src/app/routeRegistry.ts and exported, so this test
 * imports the real runtime tables instead of raw-parsing the source text (the
 * pre-registry approach, needed only while the tables were module-local
 * literals). The frozen expectations below are unchanged — they now guard the
 * registry — plus the full nav table (keys, icons, labels, order) is pinned
 * byte-for-byte against the pre-registry literal so deriving from the registry
 * cannot drift the rendered sidebar or the '#/new' hash URL.
 */

const HIDDEN_ROUTES = new Set([
  'wizard',
  'paperbench/import',
  'paperbench/run',
  'paperbench/results',
]);

describe('route <-> nav parity (Tier-1; gates route-registry drift)', () => {
  it('every PAGE_MAP route has a nav entry or is an explicit hidden route', () => {
    const routes = Object.keys(PAGE_MAP);
    const nav = new Set(NAV_ITEMS.map((item) => item.key));
    const orphans = routes.filter((r) => !nav.has(r) && !HIDDEN_ROUTES.has(r));
    expect(orphans).toEqual([]);
  });

  it('exposes the expected route + nav key sets', () => {
    const routes = Object.keys(PAGE_MAP);
    // Guards against the derivation silently producing nothing (which would
    // make the orphan check vacuously pass).
    expect(routes).toContain('home');
    expect(routes).toContain('new'); // legacy alias key stays dispatchable
    expect(routes).toContain('paperbench/import');
    expect(routes.length).toBeGreaterThanOrEqual(12);
    const nav = NAV_ITEMS.map((item) => item.key);
    expect(nav).toContain('home');
    expect(nav).not.toContain('nav_home'); // keys are hash paths, not labelKeys
    expect(nav.length).toBeGreaterThanOrEqual(10);
  });

  it('derives the exact pre-registry nav table (keys, icons, labels, order)', () => {
    // 18 entries since gui_refresh task 06 Wave 4d: the 10 frozen legacy
    // entries plus the v2-only 'projects' (Wave 2b), 'overview' (Wave 4b),
    // 'tree2' and 'ideas2' (Wave 4c), 'results2' and 'studio' (Wave 4d),
    // 'governance' (Wave 4a), and 'config' (Wave 3b) entries, explicitly
    // marked guiV2 (the Sidebar renders them only while the gui_v2
    // capability is on; the legacy 10 must stay byte-identical).
    // 'tree2'/'ideas2'/'results2' additionally carry navReplaces: while the
    // flag is on each takes its legacy slot ('tree'/'idea'/'results' —
    // identical icon/label inherited from the target) and the Sidebar hides
    // the target; while the flag is off, the replacer is hidden and the
    // legacy entry stays.
    expect(NAV_ITEMS).toEqual([
      { key: 'projects', icon: '📁', labelKey: 'nav_projects', guiV2: true },
      { key: 'home', icon: '🏠', labelKey: 'nav_home' },
      { key: 'experiments', icon: '🗂️', labelKey: 'nav_experiments' },
      { key: 'overview', icon: '🧭', labelKey: 'nav_overview', guiV2: true },
      { key: 'monitor', icon: '📡', labelKey: 'nav_monitor' },
      { key: 'tree', icon: '🌳', labelKey: 'nav_tree' },
      { key: 'tree2', icon: '🌳', labelKey: 'nav_tree', guiV2: true, navReplaces: 'tree' },
      { key: 'governance', icon: '🏛️', labelKey: 'nav_governance', guiV2: true },
      { key: 'results', icon: '📊', labelKey: 'nav_results' },
      { key: 'results2', icon: '📊', labelKey: 'nav_results', guiV2: true, navReplaces: 'results' },
      { key: 'new', icon: '✨', labelKey: 'nav_new' },
      { key: 'paperbench', icon: '📚', labelKey: 'nav_paperbench' },
      { key: 'idea', icon: '💡', labelKey: 'nav_idea' },
      { key: 'ideas2', icon: '💡', labelKey: 'nav_idea', guiV2: true, navReplaces: 'idea' },
      { key: 'workflow', icon: '⚡', labelKey: 'nav_workflow' },
      { key: 'config', icon: '🔧', labelKey: 'nav_config', guiV2: true },
      // task 06 Wave 4d: own slot — 'settings' is deliberately NOT replaced.
      { key: 'studio', icon: '🎛️', labelKey: 'nav_studio', guiV2: true },
      { key: 'settings', icon: '⚙️', labelKey: 'nav_settings' },
    ]);
  });
});
