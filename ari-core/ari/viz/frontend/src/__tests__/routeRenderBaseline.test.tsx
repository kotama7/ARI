import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest';
import { render, waitFor, screen, within } from '@testing-library/react';
import App from '../App';

/**
 * Wave-1 route render baseline (gui_refresh Wave 1 exit gate).
 *
 * For each of the 10 nav routes, this sets `window.location.hash`, mounts the
 * FULL App (registry-driven shell: AppProvider + Layout + lazy route dispatch)
 * with all network I/O mocked to minimal benign payloads, and asserts that the
 * page's stable top-level marker element renders. This pins the baseline that
 * every nav route mounts without crashing under the registry-driven shell, so
 * later waves that touch the shell (chrome, workspaces, resolution screens)
 * cannot silently break a route's mount path.
 *
 * Marker choice per route: one stable, user-visible selector per page taken
 * from the existing component source (an id the page has always carried, or
 * its title heading via the en locale — tests set ari_lang=en, matching the
 * existing devModeAndDangerousOps.test.tsx convention).
 */

const originalFetch = globalThis.fetch;

// Same strategy as devModeAndDangerousOps.test.tsx: the api layer is a thin
// barrel over one fetch-based transport, so we stub global fetch and let the
// REAL wrappers run offline. Every GET resolves to a benign, URL-appropriate
// body (shapes copied from the services/api/* return types). Order matters
// where one path is a prefix of another (workflow/flow before workflow;
// /api/v1/projects/*/runs before /api/v1/projects). `guiV2` parameterizes the
// capabilities body so the Wave-2b gating test can render the flag-off shell.
const routeBody = (url: string, guiV2: boolean): unknown => {
  let body: unknown = {};
  if (url.includes('/api/capabilities')) body = { gui_v2: guiV2, server_version: 'test' };
  else if (url.includes('/api/v1/config/schema'))
    body = {
      schema_version: 1,
      request_id: 'test',
      resolver_version: 'legacy-compatible-1',
      fields: [],
    };
  // task 06 Wave 4d (Studio): config-document + catalog reads, before the
  // /api/v1/projects prefix branches below can shadow the /config tail.
  else if (url.includes('/api/v1/projects/') && url.includes('/config'))
    body = { schema_version: 1, request_id: 'test', revision: 0, values: {}, updated_paths_count: 0 };
  else if (url.includes('/api/v1/run-templates'))
    body = { schema_version: 1, request_id: 'test', templates: [] };
  else if (url.includes('/api/v1/config/catalogs/models'))
    body = { schema_version: 1, request_id: 'test', providers: [] };
  else if (url.includes('/api/v1/projects/') && url.includes('/runs'))
    body = { schema_version: 1, request_id: 'test', project_id: 'default', runs: [] };
  else if (url.includes('/api/v1/projects'))
    body = {
      schema_version: 1,
      request_id: 'test',
      projects: [
        { schema_version: 1, project_id: 'default', name: 'Default', checkpoint_roots: [], run_count: 0 },
      ],
    };
  else if (url.includes('/api/checkpoints')) body = [];
  else if (url.includes('/api/sub-experiments')) body = { sub_experiments: [] };
  else if (url.includes('/api/paperbench/papers')) body = { papers: [] };
  else if (url.includes('/api/workflow/flow')) body = { ok: true, flow: { nodes: [], edges: [] }, path: '' };
  else if (url.includes('/api/workflow')) body = { ok: true, skill_mcp: {}, disabled_tools: [] };
  else if (url.includes('/api/skills')) body = [];
  else if (url.includes('/api/slurm/partitions')) body = [];
  else if (url.includes('/api/scheduler/detect')) body = { scheduler: 'local', partitions: [] };
  else if (url.includes('/api/container')) body = { runtime: 'none', version: '', available: false };
  else if (url.includes('/api/resource-metrics'))
    // Deliberately PARTIAL payload (RR-D-1 closed, Wave 4b): MonitorPage now
    // guards every resource-metrics field, so the route must mount even when
    // most fields are missing (the old full-shape mock was a workaround for
    // the unguarded .toFixed() crash — do not restore it).
    body = { process_count: 0 };
  else if (url.includes('/api/experiment-detail')) body = { experiment_detail_config: '' };
  // RR-P0-2 / ADR-11 / MN-2: env-keys is redacted; readiness lives in v1.
  else if (url.includes('/api/env-keys')) body = { keys: {}, source: {}, redacted: true };
  else if (url.includes('secrets/status')) body = { schema_version: 1, secrets: [] };
  else if (url.includes('/api/models')) body = {};
  else if (url.includes('/state')) body = { nodes: [] };
  return body;
};

const asResponse = (body: unknown): Response =>
  ({
    ok: true,
    status: 200,
    json: async () => body,
    text: async () => JSON.stringify(body),
  }) as unknown as Response;

const fetchMock = vi.fn(async (input: RequestInfo | URL) =>
  asResponse(routeBody(String(input), true)),
);

// AppProvider's useWebSocket constructs a real WebSocket; jsdom would try (and
// endlessly retry) a live connection. A silent no-op keeps mounts deterministic.
class FakeWebSocket {
  onopen: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  onclose: ((ev: Event) => void) | null = null;
  constructor(_url: string) {}
  send() {}
  close() {}
  addEventListener() {}
  removeEventListener() {}
}
vi.stubGlobal('WebSocket', FakeWebSocket);

// reactflow (WorkflowPage) requires ResizeObserver, which jsdom lacks.
class FakeResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal('ResizeObserver', FakeResizeObserver);

// The 18 nav-reachable routes (Sidebar order — pinned by
// routeNavParity.test.tsx) with one stable marker each. Headings use the en
// locale text of the component's title; monitor, tree2, ideas2, results2,
// and studio use the page's DOM id ('tree2' shares its h1 text with the
// legacy tree page; 'results2'/'studio' have their own h1 but the DOM id is
// the stabler marker).
// 'projects' (Wave 2b), 'overview' (Wave 4b), 'tree2' and 'ideas2' (Wave
// 4c), 'results2' and 'studio' (Wave 4d), 'governance' (Wave 4a), and
// 'config' (Wave 3b) are the v2-only routes — the capabilities mock above
// reports gui_v2 on.
// 'tree', 'idea', and 'results' stay mounted at their legacy hashes even
// though the Wave-4c/4d nav shows 'tree2'/'ideas2'/'results2' in their slots
// (URL parity invariant).
const ROUTE_MARKERS: Array<{ key: string; marker: () => Element | null }> = [
  { key: 'projects', marker: () => screen.queryByRole('heading', { level: 1, name: 'Projects' }) },
  { key: 'home', marker: () => screen.queryByRole('heading', { level: 1, name: 'Welcome to ARI' }) },
  { key: 'experiments', marker: () => screen.queryByRole('heading', { level: 1, name: 'Experiments' }) },
  { key: 'overview', marker: () => screen.queryByRole('heading', { level: 1, name: 'Run Overview' }) },
  { key: 'monitor', marker: () => document.getElementById('page-monitor') },
  { key: 'tree', marker: () => screen.queryByRole('heading', { level: 1, name: 'Experiment Tree' }) },
  { key: 'tree2', marker: () => document.getElementById('page-tree2') },
  { key: 'governance', marker: () => screen.queryByRole('heading', { level: 1, name: 'Governance' }) },
  { key: 'results', marker: () => screen.queryByRole('heading', { level: 1, name: 'Results Viewer' }) },
  // Wave 4d v2 Results route (DOM id marker).
  { key: 'results2', marker: () => document.getElementById('page-results2') },
  { key: 'new', marker: () => screen.queryByRole('heading', { level: 1, name: 'New Experiment' }) },
  {
    key: 'paperbench',
    marker: () => screen.queryByRole('heading', { level: 2, name: 'PaperBench — External Paper Registry' }),
  },
  // IdeaPage has no heading element; its stable top-level marker is the first
  // config Card's title (rendered once /state resolves).
  { key: 'idea', marker: () => screen.queryByText('⚙️ Experiment Configuration') },
  { key: 'ideas2', marker: () => document.getElementById('page-ideas2') },
  { key: 'workflow', marker: () => screen.queryByRole('heading', { level: 2, name: 'Workflow Editor' }) },
  { key: 'config', marker: () => screen.queryByRole('heading', { level: 1, name: 'Configuration' }) },
  // task 06 Wave 4d v2 Configuration Studio (DOM id marker).
  { key: 'studio', marker: () => document.getElementById('page-studio') },
  { key: 'settings', marker: () => screen.queryByRole('heading', { level: 2, name: 'Settings' }) },
];

describe('route render baseline (Wave 1: every nav route mounts under the registry shell)', () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem('ari_lang', 'en');
    fetchMock.mockClear();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
  });

  afterAll(() => {
    globalThis.fetch = originalFetch;
  });

  for (const { key, marker } of ROUTE_MARKERS) {
    it(
      `renders the ${key} page marker at #/${key}`,
      async () => {
        window.location.hash = `#/${key}`;
        render(<App />);
        // Lazy chunks (d3, reactflow) can take a moment to import in jsdom.
        await waitFor(() => expect(marker()).not.toBeNull(), { timeout: 10000 });
      },
      15000,
    );
  }

  it('sanity: the marker table covers exactly the 18 nav-reachable routes', () => {
    expect(ROUTE_MARKERS.map((r) => r.key)).toEqual([
      'projects', // gui_v2-only (Wave 2b)
      'home',
      'experiments',
      'overview', // gui_v2-only (Wave 4b)
      'monitor',
      'tree',
      'tree2', // gui_v2-only (Wave 4c — replaces the tree nav slot, hash parity kept)
      'governance', // gui_v2-only (Wave 4a)
      'results',
      'results2', // gui_v2-only (Wave 4d — replaces the results nav slot, hash parity kept)
      'new',
      'paperbench',
      'idea',
      'ideas2', // gui_v2-only (Wave 4c — replaces the idea nav slot, hash parity kept)
      'workflow',
      'config', // gui_v2-only (Wave 3b)
      'studio', // gui_v2-only (task 06 Wave 4d — own slot, settings NOT replaced)
      'settings',
    ]);
  });

  it(
    'gui_v2 off: #/projects falls back to Home and the projects nav entry is hidden',
    async () => {
      // Same offline transport, but the server reports gui_v2: false (the
      // ARI_GUI_V2 kill-switch). The v2-only route must resolve like an
      // unknown hash (Home) and the Sidebar must not offer it.
      globalThis.fetch = vi.fn(async (input: RequestInfo | URL) =>
        asResponse(routeBody(String(input), false)),
      ) as unknown as typeof fetch;
      window.location.hash = '#/projects';
      render(<App />);
      await waitFor(
        () =>
          expect(
            screen.queryByRole('heading', { level: 1, name: 'Welcome to ARI' }),
          ).not.toBeNull(),
        { timeout: 10000 },
      );
      const nav = screen.getByRole('navigation');
      expect(within(nav).queryByText('Projects')).toBeNull();
      // Wave 3b: the v2-only 'config' entry is hidden the same way.
      expect(within(nav).queryByText('Config')).toBeNull();
      // task 06 Wave 4d: the v2-only 'studio' entry is hidden the same way.
      expect(within(nav).queryByText('Studio')).toBeNull();
      // Wave 4a: the v2-only 'governance' entry is hidden the same way.
      expect(within(nav).queryByText('Governance')).toBeNull();
      // Wave 4b: the v2-only 'overview' entry is hidden the same way.
      expect(within(nav).queryByText('Overview')).toBeNull();
      // The 10 legacy entries stay (e.g. Dashboard is still offered), and the
      // Wave-4c takeovers are inert: exactly ONE Tree entry and ONE Idea
      // entry (the legacy ones).
      expect(within(nav).queryByText('Dashboard')).not.toBeNull();
      expect(within(nav).getAllByText('Research tree').length).toBe(1);
      expect(within(nav).getAllByText('Idea').length).toBe(1);
    },
    15000,
  );

  it(
    'gui_v2 off: #/ideas2 falls back to Home while legacy #/idea still mounts (Wave 4c)',
    async () => {
      globalThis.fetch = vi.fn(async (input: RequestInfo | URL) =>
        asResponse(routeBody(String(input), false)),
      ) as unknown as typeof fetch;
      window.location.hash = '#/ideas2';
      render(<App />);
      await waitFor(
        () =>
          expect(
            screen.queryByRole('heading', { level: 1, name: 'Welcome to ARI' }),
          ).not.toBeNull(),
        { timeout: 10000 },
      );
      expect(document.getElementById('page-ideas2')).toBeNull();
    },
    15000,
  );

  it(
    'gui_v2 off: #/results2 falls back to Home while legacy #/results still mounts (Wave 4d)',
    async () => {
      globalThis.fetch = vi.fn(async (input: RequestInfo | URL) =>
        asResponse(routeBody(String(input), false)),
      ) as unknown as typeof fetch;
      window.location.hash = '#/results2';
      render(<App />);
      await waitFor(
        () =>
          expect(
            screen.queryByRole('heading', { level: 1, name: 'Welcome to ARI' }),
          ).not.toBeNull(),
        { timeout: 10000 },
      );
      expect(document.getElementById('page-results2')).toBeNull();
    },
    15000,
  );

  it(
    'gui_v2 off: #/studio falls back to Home while legacy #/settings still mounts (task 06 Wave 4d)',
    async () => {
      globalThis.fetch = vi.fn(async (input: RequestInfo | URL) =>
        asResponse(routeBody(String(input), false)),
      ) as unknown as typeof fetch;
      window.location.hash = '#/studio';
      render(<App />);
      await waitFor(
        () =>
          expect(
            screen.queryByRole('heading', { level: 1, name: 'Welcome to ARI' }),
          ).not.toBeNull(),
        { timeout: 10000 },
      );
      expect(document.getElementById('page-studio')).toBeNull();
    },
    15000,
  );

  it(
    'gui_v2 off: #/tree2 falls back to Home while legacy #/tree still mounts (Wave 4c)',
    async () => {
      globalThis.fetch = vi.fn(async (input: RequestInfo | URL) =>
        asResponse(routeBody(String(input), false)),
      ) as unknown as typeof fetch;
      window.location.hash = '#/tree2';
      render(<App />);
      await waitFor(
        () =>
          expect(
            screen.queryByRole('heading', { level: 1, name: 'Welcome to ARI' }),
          ).not.toBeNull(),
        { timeout: 10000 },
      );
      expect(document.getElementById('page-tree2')).toBeNull();
    },
    15000,
  );
});
