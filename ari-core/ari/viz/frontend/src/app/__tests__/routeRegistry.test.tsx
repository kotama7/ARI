import { describe, it, expect } from 'vitest';
import { ROUTE_REGISTRY, resolveRoute, navItems } from '../routeRegistry';

/**
 * gui_refresh Wave 1 route parity (plan 03).
 *
 * Freezes the route registry against the CURRENT router contract as literals:
 * the exact id/path set (15 routes, App.tsx PAGE_MAP), the exact nav order and
 * i18n keys (12 entries, Sidebar.tsx NAV_ITEMS), the new -> wizard legacy
 * alias, query-string stripping, and explicit undefined for unknown hashes.
 * Any registry drift from the deployed hash-URL contract must fail here.
 * Wave 2b adds the v2-only 'projects' route (guiV2 marker; plans 01/07).
 * Wave 3b adds the v2-only 'config' route (read-only effective-config
 * browser; plans 05/06).
 * Wave 4a adds the v2-only 'governance' route (read-only RQGM governance
 * workspace; plan 08).
 * Wave 4b adds the v2-only 'overview' route (v2 run Overview workspace;
 * plan 07 §Run Overview and Live Monitor).
 * Wave 4c adds the v2-only 'tree_v2' route (path 'tree2' — the FIRST route
 * whose id and path differ) which REPLACES the legacy 'tree' nav slot while
 * gui_v2 is on (navReplaces; plan 07 §Tree workspace, plan 10 route-level
 * flag switching). The legacy 'tree' route/hash stays untouched.
 * Wave 4c (Ideas) adds the v2-only 'ideas_v2' route (path 'ideas2') which
 * REPLACES the legacy 'idea' nav slot the same way (plan 07 §Ideas, claims,
 * and evidence). The legacy 'idea' route/hash stays untouched.
 * Wave 4d (Results) adds the v2-only 'results_v2' route (path 'results2')
 * which REPLACES the legacy 'results' nav slot the same way (plan 07
 * §Evidence, Results, and PaperBench). The legacy 'results' route/hash —
 * the full editor/PDF/EAR-mutation workspace — stays untouched.
 * Wave 4d (task 06) adds the v2-only 'studio' route (Configuration Studio
 * non-governance slice, plan 06) with its OWN nav slot (navOrder 96) — it
 * does NOT replace the legacy 'settings' route (cutover is a later slice).
 */

describe('routeRegistry (gui_refresh Wave 1 route parity, plan 03)', () => {
  it('covers exactly the current 21 routes with id === path (tree_v2/ideas_v2/results_v2 excepted)', () => {
    expect(ROUTE_REGISTRY.map((r) => r.id)).toEqual([
      'projects', // gui_v2-only (Wave 2b)
      'home',
      'experiments',
      'overview', // gui_v2-only (Wave 4b)
      'monitor',
      'tree',
      'tree_v2', // gui_v2-only (Wave 4c, path 'tree2', replaces the tree nav slot)
      'governance', // gui_v2-only (Wave 4a)
      'results',
      'results_v2', // gui_v2-only (Wave 4d, path 'results2', replaces the results nav slot)
      'wizard',
      'idea',
      'ideas_v2', // gui_v2-only (Wave 4c, path 'ideas2', replaces the idea nav slot)
      'workflow',
      'config', // gui_v2-only (Wave 3b)
      'studio', // gui_v2-only (task 06 Wave 4d, own slot — settings NOT replaced)
      'settings',
      'paperbench',
      'paperbench/import',
      'paperbench/run',
      'paperbench/results',
    ]);
    const ID_PATH_DIVERGENCES: Record<string, string> = {
      // Wave 4c/4d: the id/path divergences — hash URLs are
      // '#/tree2'/'#/ideas2'/'#/results2'.
      tree_v2: 'tree2',
      ideas_v2: 'ideas2',
      results_v2: 'results2',
    };
    for (const route of ROUTE_REGISTRY) {
      expect(route.path).toBe(ID_PATH_DIVERGENCES[route.id] ?? route.id);
    }
  });

  it('reproduces the current Sidebar nav order and i18n keys exactly', () => {
    expect(navItems().map((r) => [r.id, r.navLabelKey])).toEqual([
      ['projects', 'nav_projects'], // gui_v2-only (Wave 2b, navOrder 5)
      ['home', 'nav_home'],
      ['experiments', 'nav_experiments'],
      ['overview', 'nav_overview'], // gui_v2-only (Wave 4b, navOrder 25)
      ['monitor', 'nav_monitor'],
      ['tree', 'nav_tree'],
      ['tree_v2', 'nav_tree'], // gui_v2-only (Wave 4c) — inherits the tree slot
      ['governance', 'nav_governance'], // gui_v2-only (Wave 4a, navOrder 45)
      ['results', 'nav_results'],
      ['results_v2', 'nav_results'], // gui_v2-only (Wave 4d) — inherits the results slot
      ['wizard', 'nav_new'],
      ['paperbench', 'nav_paperbench'],
      ['idea', 'nav_idea'],
      ['ideas_v2', 'nav_idea'], // gui_v2-only (Wave 4c) — inherits the idea slot
      ['workflow', 'nav_workflow'],
      ['config', 'nav_config'], // gui_v2-only (Wave 3b, navOrder 95)
      ['studio', 'nav_studio'], // gui_v2-only (task 06 Wave 4d, navOrder 96)
      ['settings', 'nav_settings'],
    ]);
  });

  // Wave 4c/4d nav takeovers: tree_v2 over 'tree', ideas_v2 over 'idea',
  // results_v2 over 'results'.
  for (const [v2Id, targetId] of [
    ['tree_v2', 'tree'],
    ['ideas_v2', 'idea'],
    ['results_v2', 'results'],
  ] as const) {
    it(`${v2Id} replaces the ${targetId} nav slot: inherited label/order/icon, stable order (Wave 4c/4d)`, () => {
      const registryEntry = ROUTE_REGISTRY.find((r) => r.id === v2Id)!;
      // The registry entry declares ONLY the takeover — nav metadata is
      // inherited from the target at navItems() time, so the two slots can
      // never drift apart.
      expect(registryEntry.navReplaces).toBe(targetId);
      expect(registryEntry.guiV2).toBe(true);
      expect(registryEntry.navLabelKey).toBeUndefined();
      expect(registryEntry.navOrder).toBeUndefined();

      const items = navItems();
      const target = items.find((r) => r.id === targetId)!;
      const replacer = items.find((r) => r.id === v2Id)!;
      expect(replacer.navLabelKey).toBe(target.navLabelKey);
      expect(replacer.navOrder).toBe(target.navOrder);
      expect(replacer.navIcon).toBe(target.navIcon);
      // Stable sort: the legacy target stays immediately before its replacer.
      expect(items.indexOf(replacer)).toBe(items.indexOf(target) + 1);
    });
  }

  it('gives paperbench sub-routes no nav metadata (in-page reachable only)', () => {
    for (const id of ['paperbench/import', 'paperbench/run', 'paperbench/results']) {
      const route = ROUTE_REGISTRY.find((r) => r.id === id);
      expect(route).toBeDefined();
      expect(route?.navLabelKey).toBeUndefined();
      expect(route?.navOrder).toBeUndefined();
    }
  });

  it('marks exactly projects (2b), overview (4b), tree_v2/ideas_v2 (4c), results_v2/studio (4d), governance (4a), and config (3b) as gui_v2-only routes', () => {
    expect(
      ROUTE_REGISTRY.filter((r) => r.guiV2 === true).map((r) => r.id),
    ).toEqual([
      'projects',
      'overview',
      'tree_v2',
      'governance',
      'results_v2',
      'ideas_v2',
      'config',
      'studio',
    ]);
  });

  it('resolves #/studio (query-string tolerant) while #/settings stays legacy (task 06 Wave 4d)', () => {
    expect(resolveRoute('#/studio')?.id).toBe('studio');
    expect(resolveRoute('#/studio?template=t1')?.id).toBe('studio');
    expect(resolveRoute('#/studio?draft=draft-abc123def456')?.path).toBe('studio');
    // The Studio does NOT replace the legacy settings route in this slice.
    expect(resolveRoute('#/settings')?.id).toBe('settings');
    expect(ROUTE_REGISTRY.find((r) => r.id === 'studio')?.navReplaces).toBeUndefined();
  });

  it('resolves the legacy alias new -> wizard', () => {
    expect(resolveRoute('#/new')?.id).toBe('wizard');
    expect(resolveRoute('new')?.id).toBe('wizard');
    expect(ROUTE_REGISTRY.find((r) => r.id === 'wizard')?.legacyAliases).toEqual(['new']);
  });

  it('strips query strings before matching (parseHash parity)', () => {
    expect(resolveRoute('#/paperbench/results?job=xyz')?.id).toBe('paperbench/results');
    expect(resolveRoute('#/tree?node=n1&epoch=2')?.id).toBe('tree');
  });

  it('resolves #/tree2 to tree_v2 while #/tree stays on the legacy route (Wave 4c parity)', () => {
    expect(resolveRoute('#/tree2')?.id).toBe('tree_v2');
    expect(resolveRoute('#/tree2?run=r1&node=n1')?.id).toBe('tree_v2');
    expect(resolveRoute('#/tree2?run=r1&node=n1')?.path).toBe('tree2');
    // Legacy URL parity: the v2 route never captures the legacy hash.
    expect(resolveRoute('#/tree')?.id).toBe('tree');
  });

  it('resolves #/ideas2 to ideas_v2 while #/idea stays on the legacy route (Wave 4c parity)', () => {
    expect(resolveRoute('#/ideas2')?.id).toBe('ideas_v2');
    expect(resolveRoute('#/ideas2?run=r1')?.id).toBe('ideas_v2');
    expect(resolveRoute('#/ideas2?run=r1')?.path).toBe('ideas2');
    // Legacy URL parity: the v2 route never captures the legacy hash.
    expect(resolveRoute('#/idea')?.id).toBe('idea');
  });

  it('resolves #/results2 to results_v2 while #/results stays on the legacy route (Wave 4d parity)', () => {
    expect(resolveRoute('#/results2')?.id).toBe('results_v2');
    expect(resolveRoute('#/results2?run=r1')?.id).toBe('results_v2');
    expect(resolveRoute('#/results2?run=r1')?.path).toBe('results2');
    // Legacy URL parity: the v2 route never captures the legacy hash.
    expect(resolveRoute('#/results')?.id).toBe('results');
  });

  it('returns undefined for unknown hashes (no silent Home fallback)', () => {
    expect(resolveRoute('#/does-not-exist')).toBeUndefined();
    expect(resolveRoute('#/paperbench/unknown')).toBeUndefined();
  });

  it('treats an empty hash as home (parseHash parity)', () => {
    expect(resolveRoute('')?.id).toBe('home');
    expect(resolveRoute('#/')?.id).toBe('home');
  });
});
