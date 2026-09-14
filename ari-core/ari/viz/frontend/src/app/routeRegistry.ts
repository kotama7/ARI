import type { ComponentType } from 'react';

/**
 * Single-source route registry (gui_refresh Wave 1). A route exists in exactly
 * one place — an entry in this array; both consumers are DERIVED from it, so a
 * route can never exist in the nav without existing in the router, or the
 * reverse. Each entry carries id, hash path, lazy loader, optional nav
 * metadata, legacy aliases and the migration markers `guiV2` / `navReplaces`
 * (docs/concepts/gui_architecture.md, "2. The route registry is the only place
 * a route exists").
 *
 * Mirrors the CURRENT router exactly: the lazy page imports of
 * `App.tsx` (PAGE_MAP) and the nav metadata/order of
 * `components/Layout/Sidebar.tsx` (NAV_ITEMS). Both are wired to this module
 * (gui_refresh Wave 1 task 03): App.tsx derives PAGE_MAP/dispatch from
 * ROUTE_REGISTRY + resolveRoute, and Sidebar.tsx derives NAV_ITEMS from
 * navItems(). The frozen-literal tests in `__tests__/routeRegistry.test.tsx`
 * and `src/__tests__/routeNavParity.test.tsx` pin the contract.
 *
 * Contract notes:
 * - Hash URLs (`#/<path>`) are the deployment contract and must not change.
 * - `new` is a legacy alias of `wizard` (App.tsx parseHash maps new -> wizard).
 * - `paperbench/import|run|results` are reachable in-page only (no nav entry).
 */
export type RouteDefinition = {
  id: string;
  path: string;
  load: () => Promise<{ default: ComponentType }>;
  navLabelKey?: string;
  navOrder?: number;
  /** Emoji shown before the nav label (Sidebar visual contract). */
  navIcon?: string;
  /**
   * Hash path the Sidebar writes when navigating to this route, when it
   * differs from `path`. The New item historically navigates to '#/new'
   * (the legacy alias) while the canonical route is 'wizard'; hash URLs are
   * the frozen deployment contract, so the Sidebar must keep emitting them.
   */
  navPath?: string;
  breadcrumbKey?: string;
  legacyAliases?: string[];
  requiredContext?: Array<'run'>;
  /**
   * v2-only route (gui_refresh Wave 2b): its nav entry is gated on the
   * gui_v2 capability (Sidebar filters it out when the flag is off) and its
   * path is listed in App.tsx V2_ONLY_ROUTES (dispatch falls back to Home).
   */
  guiV2?: boolean;
  /**
   * Nav takeover (gui_refresh Wave 4c). Flag switching happens at the nav
   * slot, not per route: a route names no flag of its own, the boolean
   * `guiV2` marker stands for the one environment switch behind the whole v2
   * surface, and promotion/rollback of a slice is granting or taking away its
   * sidebar slot. The value is the
   * id of the route whose Sidebar slot this v2 route takes while the gui_v2
   * flag is on. `navItems()` materializes the target's navLabelKey /
   * navOrder / navIcon onto this entry (the sidebar slot looks identical —
   * only the hash it writes changes), and the Sidebar hides the target at
   * render time. With the flag off, the guiV2 gate hides this entry instead
   * and the legacy slot is untouched. The target route itself always stays
   * registered, so its legacy hash URL keeps working in both modes.
   */
  navReplaces?: string;
};

export const ROUTE_REGISTRY: RouteDefinition[] = [
  {
    id: 'projects',
    path: 'projects',
    load: () =>
      import('../components/Projects/ProjectsPage').then((m) => ({ default: m.ProjectsPage })),
    navLabelKey: 'nav_projects',
    navOrder: 5,
    navIcon: '📁',
    guiV2: true,
  },
  {
    id: 'home',
    path: 'home',
    load: () => import('../components/Home/HomePage').then((m) => ({ default: m.HomePage })),
    navLabelKey: 'nav_home',
    navOrder: 10,
    navIcon: '🏠',
  },
  {
    id: 'experiments',
    path: 'experiments',
    load: () =>
      import('../components/Experiments/ExperimentsPage').then((m) => ({ default: m.ExperimentsPage })),
    navLabelKey: 'nav_experiments',
    navOrder: 20,
    navIcon: '🗂️',
  },
  {
    id: 'overview',
    path: 'overview',
    load: () =>
      import('../components/Overview/OverviewPage').then((m) => ({
        default: m.OverviewPage,
      })),
    navLabelKey: 'nav_overview',
    navOrder: 25,
    navIcon: '🧭',
    guiV2: true,
  },
  {
    id: 'monitor',
    path: 'monitor',
    load: () => import('../components/Monitor/MonitorPage').then((m) => ({ default: m.MonitorPage })),
    navLabelKey: 'nav_monitor',
    navOrder: 30,
    navIcon: '📡',
  },
  {
    id: 'tree',
    path: 'tree',
    load: () => import('../components/Tree/TreePage').then((m) => ({ default: m.TreePage })),
    navLabelKey: 'nav_tree',
    navOrder: 40,
    navIcon: '🌳',
  },
  {
    // v2 Tree workspace (gui_refresh Wave 4c): run-explicit, read-only node
    // graph whose selection lives in the hash (`#/tree2?run=&node=`).
    // Takes over the legacy 'tree' Sidebar slot while gui_v2 is on
    // (navReplaces); the legacy '#/tree' URL and TreePage stay untouched
    // and reachable in both modes (parity invariant).
    id: 'tree_v2',
    path: 'tree2',
    load: () =>
      import('../components/TreeV2/TreeV2Page').then((m) => ({
        default: m.TreeV2Page,
      })),
    guiV2: true,
    navReplaces: 'tree',
  },
  {
    id: 'governance',
    path: 'governance',
    load: () =>
      import('../components/Governance/GovernancePage').then((m) => ({
        default: m.GovernancePage,
      })),
    navLabelKey: 'nav_governance',
    navOrder: 45,
    navIcon: '🏛️',
    guiV2: true,
  },
  {
    id: 'results',
    path: 'results',
    load: () => import('../components/Results/ResultsPage').then((m) => ({ default: m.ResultsPage })),
    navLabelKey: 'nav_results',
    navOrder: 50,
    navIcon: '📊',
  },
  {
    // v2 Results/EAR workspace (gui_refresh Wave 4d): a run-explicit,
    // READ-ONLY view of evidence, review scores and publication lineage —
    // every mutation and the paper editor stay on the legacy page it links
    // out to. Takes over the legacy 'results' Sidebar
    // slot while gui_v2 is on (navReplaces); the legacy '#/results' URL and
    // ResultsPage (the full editor/PDF workspace and every EAR mutation)
    // stay untouched and reachable in both modes (parity invariant).
    id: 'results_v2',
    path: 'results2',
    load: () =>
      import('../components/ResultsV2/ResultsV2Page').then((m) => ({
        default: m.ResultsV2Page,
      })),
    guiV2: true,
    navReplaces: 'results',
  },
  {
    id: 'wizard',
    path: 'wizard',
    load: () => import('../components/Wizard/WizardPage').then((m) => ({ default: m.WizardPage })),
    navLabelKey: 'nav_new',
    navOrder: 60,
    navIcon: '✨',
    navPath: 'new',
    legacyAliases: ['new'],
  },
  {
    id: 'idea',
    path: 'idea',
    load: () => import('../components/Idea/IdeaPage'),
    navLabelKey: 'nav_idea',
    navOrder: 80,
    navIcon: '💡',
  },
  {
    // v2 Ideas workspace (gui_refresh Wave 4c): run-explicit, read-only view
    // of this run's ideas and hypotheses shown with the evidence behind them
    // (idea.json plus the nodes actually explored), never another run's.
    // Takes over the legacy 'idea' Sidebar slot while gui_v2 is
    // on (navReplaces — the Tree stage's mechanism); the legacy '#/idea'
    // URL and IdeaPage stay untouched and reachable in both modes (parity
    // invariant).
    id: 'ideas_v2',
    path: 'ideas2',
    load: () =>
      import('../components/IdeasV2/IdeasV2Page').then((m) => ({
        default: m.IdeasV2Page,
      })),
    guiV2: true,
    navReplaces: 'idea',
  },
  {
    id: 'workflow',
    path: 'workflow',
    load: () => import('../components/Workflow/WorkflowPage'),
    navLabelKey: 'nav_workflow',
    navOrder: 90,
    navIcon: '⚡',
  },
  {
    id: 'config',
    path: 'config',
    load: () =>
      import('../components/ConfigBrowser/ConfigBrowserPage').then((m) => ({
        default: m.ConfigBrowserPage,
      })),
    navLabelKey: 'nav_config',
    navOrder: 95,
    navIcon: '🔧',
    guiV2: true,
  },
  {
    // v2 Configuration Studio (gui_refresh task 06 Wave 4d). Configuration
    // editing only: RQGM governance and tuning parameters stay file-only, and
    // no screen can change the mode of a run that already exists.
    // Own nav slot right after the ConfigBrowser:
    // it does NOT replace the legacy 'settings' route yet (the Settings
    // page keeps working unchanged in parallel; cutover is a later slice).
    id: 'studio',
    path: 'studio',
    load: () =>
      import('../components/ConfigStudio/ConfigStudioPage').then((m) => ({
        default: m.ConfigStudioPage,
      })),
    navLabelKey: 'nav_studio',
    navOrder: 96,
    navIcon: '🎛️',
    guiV2: true,
  },
  {
    id: 'settings',
    path: 'settings',
    load: () => import('../components/Settings/SettingsPage'),
    navLabelKey: 'nav_settings',
    navOrder: 100,
    navIcon: '⚙️',
  },
  {
    id: 'paperbench',
    path: 'paperbench',
    load: () => import('../components/PaperBench').then((m) => ({ default: m.PaperRegistryPage })),
    navLabelKey: 'nav_paperbench',
    navOrder: 70,
    navIcon: '📚',
  },
  {
    id: 'paperbench/import',
    path: 'paperbench/import',
    load: () => import('../components/PaperBench').then((m) => ({ default: m.PaperImportDialog })),
  },
  {
    id: 'paperbench/run',
    path: 'paperbench/run',
    load: () => import('../components/PaperBench').then((m) => ({ default: m.PaperBenchWizard })),
  },
  {
    id: 'paperbench/results',
    path: 'paperbench/results',
    load: () => import('../components/PaperBench').then((m) => ({ default: m.ResultsView })),
  },
];

/**
 * Resolve a location hash (or bare path) to a route definition.
 *
 * Mirrors App.tsx parseHash(): strips the `#/` prefix and any query string
 * (so '#/paperbench/results?job=xyz' resolves to 'paperbench/results'),
 * treats an empty hash as 'home', and applies legacyAliases (new -> wizard).
 * Unknown paths return undefined — callers decide the fallback policy.
 */
export function resolveRoute(hash: string): RouteDefinition | undefined {
  const raw = hash.replace(/^#\/?/, '').split('?')[0];
  const path = raw || 'home';
  return ROUTE_REGISTRY.find(
    (route) => route.path === path || route.legacyAliases?.includes(path),
  );
}

/**
 * Routes with nav metadata, in Sidebar display order (ascending navOrder).
 *
 * A `navReplaces` entry (Wave 4c) inherits its target's navLabelKey /
 * navOrder / navIcon so it occupies the same sidebar slot; the sort is
 * stable, so the target (declared first in the registry) stays immediately
 * before its replacer and the Sidebar decides at render time which of the
 * two is visible for the current gui_v2 flag.
 */
export function navItems(): RouteDefinition[] {
  return ROUTE_REGISTRY.map((route) => {
    if (route.navReplaces === undefined) return route;
    const target = ROUTE_REGISTRY.find((r) => r.id === route.navReplaces);
    if (target === undefined) return route;
    return {
      ...route,
      navLabelKey: route.navLabelKey ?? target.navLabelKey,
      navOrder: route.navOrder ?? target.navOrder,
      navIcon: route.navIcon ?? target.navIcon,
    };
  })
    .filter(
      (route) => route.navLabelKey !== undefined && route.navOrder !== undefined,
    )
    .sort((a, b) => (a.navOrder ?? 0) - (b.navOrder ?? 0));
}
