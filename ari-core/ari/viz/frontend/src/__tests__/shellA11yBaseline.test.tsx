import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest';
import { render, waitFor, within, screen, cleanup } from '@testing-library/react';
import axe from 'axe-core';
import App from '../App';

/**
 * Wave-1 shell accessibility baseline (gui_refresh Wave 1 exit gate).
 *
 * Pins the CURRENT a11y state of the registry-driven shell — it does NOT fix
 * components (that is task 02's remediation scope in a later wave). Two kinds
 * of pins:
 *
 *   1. Positive invariants that already hold (one nav landmark, focusable nav
 *      items, labelled hamburger) — these must never regress.
 *   2. Frozen violation baselines (axe violation ids; per-route h1 counts) —
 *      a RATCHET: the test fails if a NEW violation appears, and when task 02
 *      fixes one, the frozen literal here must be shrunk to match (a stale
 *      baseline entry also fails the ratchet).
 *
 * KNOWN Wave-1 heading violations frozen below for task 02's remediation:
 *   - paperbench, settings, workflow: page title is an <h2> with NO <h1>.
 *   - idea: no heading element at all (Card titles are plain divs).
 * Every other nav route renders exactly one <h1>.
 */

const originalFetch = globalThis.fetch;

// Same offline strategy as routeRenderBaseline.test.tsx / devModeAndDangerousOps:
// stub global fetch with URL-appropriate benign bodies so the REAL api wrappers
// run deterministically.
const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
  const url = String(input);
  let body: unknown = {};
  if (url.includes('/api/capabilities')) body = { gui_v2: true, server_version: 'test' };
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
  return {
    ok: true,
    status: 200,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
});

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

class FakeResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal('ResizeObserver', FakeResizeObserver);

// Marker per nav route (duplicated from routeRenderBaseline.test.tsx on
// purpose — importing a sibling test file would re-register its tests here).
// 'projects' (Wave 2b), 'overview' (Wave 4b), 'governance' (Wave 4a), and
// 'config' (Wave 3b) are the v2-only routes (gui_v2 is on in the mock above).
const ROUTE_MARKERS: Array<{ key: string; marker: () => Element | null }> = [
  { key: 'projects', marker: () => screen.queryByRole('heading', { level: 1, name: 'Projects' }) },
  { key: 'home', marker: () => screen.queryByRole('heading', { level: 1, name: 'Welcome to ARI' }) },
  { key: 'experiments', marker: () => screen.queryByRole('heading', { level: 1, name: 'Experiments' }) },
  { key: 'overview', marker: () => screen.queryByRole('heading', { level: 1, name: 'Run Overview' }) },
  { key: 'monitor', marker: () => document.getElementById('page-monitor') },
  { key: 'tree', marker: () => screen.queryByRole('heading', { level: 1, name: 'Experiment Tree' }) },
  // Wave 4c v2 route (DOM id marker — shares its h1 text with legacy tree).
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
  { key: 'idea', marker: () => screen.queryByText('⚙️ Experiment Configuration') },
  // Wave 4c v2 Ideas route (DOM id marker).
  { key: 'ideas2', marker: () => document.getElementById('page-ideas2') },
  { key: 'workflow', marker: () => screen.queryByRole('heading', { level: 2, name: 'Workflow Editor' }) },
  { key: 'config', marker: () => screen.queryByRole('heading', { level: 1, name: 'Configuration' }) },
  // task 06 Wave 4d v2 Configuration Studio (DOM id marker).
  { key: 'studio', marker: () => document.getElementById('page-studio') },
  { key: 'settings', marker: () => screen.queryByRole('heading', { level: 2, name: 'Settings' }) },
];

// ── Frozen baselines (Wave 1 — shrink only, never grow; see header) ──

// h1 elements per nav route. 0 = KNOWN violation (task 02 remediation list).
const H1_BASELINE: Record<string, number> = {
  projects: 1, // Wave 2b v2 slice — ships compliant
  home: 1,
  experiments: 1,
  overview: 1, // Wave 4b v2 slice — ships compliant
  monitor: 1,
  tree: 1,
  tree2: 1, // Wave 4c v2 slice — ships compliant
  governance: 1, // Wave 4a v2 slice — ships compliant
  results: 1,
  results2: 1, // Wave 4d v2 slice — ships compliant
  new: 1,
  paperbench: 0, // h2 only
  idea: 0, // no heading at all
  ideas2: 1, // Wave 4c v2 slice — ships compliant
  workflow: 0, // h2 only
  config: 1, // Wave 3b v2 slice — ships compliant
  studio: 1, // task 06 Wave 4d v2 slice — ships compliant
  settings: 0, // h2 only
};

// axe-core violation ids on the shell at #/home. color-contrast is disabled
// (jsdom has no canvas/paint, so the rule cannot compute results there).
// KNOWN Wave-1 violations frozen for task 02's remediation:
//   - 'region':      page content (#main, sidebar logo/switcher) is not
//                    contained in landmarks (no <main>, <header>, etc.).
//   - 'select-name': the sidebar #project-select has a visual <label> that is
//                    not programmatically associated (no htmlFor/aria-label).
const AXE_VIOLATION_BASELINE: string[] = ['region', 'select-name'];

async function renderRoute(key: string): Promise<void> {
  window.location.hash = `#/${key}`;
  const entry = ROUTE_MARKERS.find((r) => r.key === key)!;
  render(<App />);
  await waitFor(() => expect(entry.marker()).not.toBeNull(), { timeout: 10000 });
}

describe('shell a11y baseline (Wave 1 — positive invariants + violation ratchet)', () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem('ari_lang', 'en');
    fetchMock.mockClear();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
  });

  afterAll(() => {
    globalThis.fetch = originalFetch;
  });

  it('exposes exactly one nav landmark with 15 keyboard-focusable nav items', async () => {
    await renderRoute('home');

    const navs = screen.getAllByRole('navigation');
    expect(navs.length).toBe(1);

    // Sidebar nav items are div[role=button][tabIndex=0] with Enter handling —
    // every one of the 15 visible entries (10 legacy + the gui_v2-gated
    // 'projects' (Wave 2b), 'overview' (Wave 4b), 'governance' (Wave 4a),
    // 'config' (Wave 3b), and 'studio' (task 06 Wave 4d — its OWN slot, the
    // legacy settings entry stays) entries, which the mock's gui_v2:true
    // keeps visible) must stay reachable and activatable by keyboard. The
    // count is unaffected by Waves 4c/4d takeovers: 'tree2' REPLACES the
    // 'tree' slot, 'ideas2' REPLACES the 'idea' slot, and 'results2'
    // REPLACES the 'results' slot while gui_v2 is on (navReplaces), so a
    // replacer and its target are never both visible.
    const items = within(navs[0]).getAllByRole('button');
    expect(items.length).toBe(15);
    for (const item of items) {
      expect(item.getAttribute('tabindex')).toBe('0');
    }
  });

  it('labels the mobile hamburger button for screen readers', async () => {
    await renderRoute('home');
    const hamburger = document.getElementById('btn-hamburger');
    expect(hamburger).not.toBeNull();
    expect(hamburger!.getAttribute('aria-label')).toBe('Menu');
  });

  it(
    'matches the frozen per-route h1 baseline (ratchet — see header for the violation list)',
    async () => {
      const counts: Record<string, number> = {};
      for (const { key } of ROUTE_MARKERS) {
        await renderRoute(key);
        counts[key] = document.querySelectorAll('h1').length;
        // Unmount between routes so heading counts never bleed across pages.
        cleanup();
      }
      expect(counts).toEqual(H1_BASELINE);
    },
    60000,
  );

  it(
    'matches the frozen axe-core violation-id baseline on the shell (ratchet)',
    async () => {
      await renderRoute('home');
      const results = await axe.run(document.body, {
        rules: {
          // jsdom cannot paint, so contrast cannot be computed there.
          'color-contrast': { enabled: false },
        },
      });
      const ids = results.violations.map((v) => v.id).sort();
      expect(ids).toEqual([...AXE_VIOLATION_BASELINE].sort());
    },
    30000,
  );
});
