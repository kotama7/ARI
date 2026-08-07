import { lazy, Suspense, useEffect, useState } from 'react';
import type { LazyExoticComponent, ComponentType } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { AppProvider } from './context/AppContext';
import { I18nProvider } from './i18n/I18nProvider';
import { queryClient } from './app/queryClient';
import { Layout } from './components/Layout';
import { LoadingState } from './components/common';
import { ROUTE_REGISTRY, resolveRoute } from './app/routeRegistry';
import { fetchCapabilities } from './services/api';
import './styles/dashboard.css';

// ── route dispatch (derived from the single-source route registry) ──

// PAGE_MAP is built from ROUTE_REGISTRY (gui_refresh Wave 1 task 03): one
// React.lazy component per route, created once at module scope so
// code-splitting chunks and component identity stay stable across renders
// (the registry stores plain load thunks). Legacy aliases (new -> wizard)
// share the canonical route's lazy instance, preserving the historical key
// set. Exported for the route <-> nav parity test.
export const PAGE_MAP: Record<string, LazyExoticComponent<ComponentType>> = (() => {
  const map: Record<string, LazyExoticComponent<ComponentType>> = {};
  for (const route of ROUTE_REGISTRY) {
    const Page = lazy(route.load);
    map[route.path] = Page;
    for (const alias of route.legacyAliases ?? []) {
      map[alias] = Page;
    }
  }
  return map;
})();

// ── ARI_GUI_V2 capability gate (gui_refresh Wave 1) ──

// Route ids that exist only in the v2 shell. When the server reports
// gui_v2: false (ARI_GUI_V2=0/false — the env kill-switch; owner: task 03,
// removal gate: G6), these resolve to Home exactly like an unknown hash, so
// the legacy surface stays fully reachable without a redeploy.
// Wave 2b: 'projects' (the first v2 vertical slice, plan 07 §Projects and
// run portfolio) hangs off this gate; its nav entry is filtered in Sidebar
// via the registry's guiV2 marker.
// Wave 3b: 'config' (read-only effective-config browser, plans 05/06) joins
// the same gate.
// Wave 4a: 'governance' (read-only RQGM governance & score lineage
// workspace, plan 08) joins the same gate.
// Wave 4b: 'overview' (v2 run Overview workspace, plan 07 §Run Overview and
// Live Monitor) joins the same gate.
// Wave 4c: 'tree2' (v2 Tree workspace, plan 07 §Tree workspace — route id
// 'tree_v2') joins the same gate. The set holds DISPATCH KEYS (route paths,
// which parseHash returns); for every earlier entry path === id, tree_v2 is
// the first route where they differ.
// Wave 4c (Ideas): 'ideas2' (v2 Ideas workspace, plan 07 §Ideas, claims,
// and evidence — route id 'ideas_v2') joins the same gate.
// Wave 4d (Results): 'results2' (v2 Results/EAR workspace, plan 07
// §Evidence, Results, and PaperBench — route id 'results_v2') joins the
// same gate.
// Wave 4d (task 06): 'studio' (Configuration Studio non-governance slice,
// plan 06) joins the same gate. It gets its OWN nav slot — the legacy
// 'settings' route is NOT replaced yet (cutover is a later slice).
export const V2_ONLY_ROUTES: ReadonlySet<string> = new Set<string>([
  'projects',
  'overview',
  'tree2',
  'ideas2',
  'results2',
  'config',
  'studio',
  'governance',
]);

// ── helpers ──

function parseHash(): string {
  // resolveRoute strips the '#/' prefix and any query string (so
  // '#/paperbench/results?job=xyz' resolves to 'paperbench/results'), treats
  // an empty hash as 'home', and maps the legacy 'new' hash to its canonical
  // route ('wizard').
  // Returns the route PATH — the PAGE_MAP dispatch key. Identical to the id
  // for every route except 'tree_v2' (path 'tree2'), 'ideas_v2' (path
  // 'ideas2') — the gui_refresh Wave 4c routes — and 'results_v2' (path
  // 'results2', Wave 4d), whose id and path differ.
  // Unknown hashes silently fall back to Home — UNCHANGED in Wave 1.
  // TODO(gui_refresh Wave 2+): explicit resolution screen for unknown hashes.
  return resolveRoute(window.location.hash)?.path ?? 'home';
}

// ── inner router (uses context) ──

function Router({ guiV2 }: { guiV2: boolean }) {
  const [page, setPage] = useState<string>(parseHash);

  useEffect(() => {
    const onHashChange = () => setPage(parseHash());
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  // Legacy fallback: with gui_v2 off, v2-only routes fall back to Home (the
  // registry serves both shells — legacy routes/URLs are shared, so nothing
  // else changes). With the flag on (the default) this is a no-op.
  const effectivePage = !guiV2 && V2_ONLY_ROUTES.has(page) ? 'home' : page;
  const PageComponent = PAGE_MAP[effectivePage] ?? PAGE_MAP['home'];

  return (
    <Layout guiV2={guiV2}>
      <Suspense
        fallback={
          <div style={{ flex: 1, padding: 28, textAlign: 'center', paddingTop: 80 }}>
            <LoadingState />
          </div>
        }
      >
        <PageComponent />
      </Suspense>
    </Layout>
  );
}

// ── App ──

export default function App() {
  // Fetched once on mount. Defaults ON, and STAYS on when the fetch fails:
  // this is a loopback tool, so an API hiccup must never drop the user into
  // the fallback shell (gui_refresh feature-flag policy, plan 10 §Wave 1).
  const [guiV2, setGuiV2] = useState<boolean>(true);

  useEffect(() => {
    let cancelled = false;
    fetchCapabilities()
      .then((caps) => {
        if (!cancelled && caps.gui_v2 === false) setGuiV2(false);
      })
      .catch(() => {
        /* default ON — see comment above */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // QueryClientProvider (gui_refresh Wave 2b): server-state cache seam for
  // the typed /api/v1 hooks (src/hooks/useV1.ts). Transparent to Wave-1
  // pages — no page consumes queries until the Slice stage adopts them.
  // I18nProvider (gui_refresh Wave 4d, task 09): ready-gate that lazy-loads
  // the active locale dict (+ en fallback) before the shell renders, keeping
  // the three i18n dictionaries out of the main chunk.
  return (
    <QueryClientProvider client={queryClient}>
      <AppProvider>
        <I18nProvider>
          <Router guiV2={guiV2} />
        </I18nProvider>
      </AppProvider>
    </QueryClientProvider>
  );
}
