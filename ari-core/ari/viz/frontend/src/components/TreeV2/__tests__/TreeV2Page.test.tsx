import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, act, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  TreeV2Page,
  NODE_STATUSES,
  NODE_LABELS,
  sentinelsOf,
  toTreeNodes,
} from '../TreeV2Page';
import { AppProvider } from '../../../context/AppContext';
import { Sidebar } from '../../Layout/Sidebar';
import {
  ApiErrorV1,
  fetchRunTreeV1,
  type RequestIdV1,
  type TreeV1,
} from '../../../services/api/v1';
import { fetchNodeReport } from '../../../services/api/nodeReport';
import type { TreeNode } from '../../../types';

/**
 * TreeV2Page (gui_refresh task 07 Wave 4c — v2 Tree workspace; plan 07
 * §Tree workspace, plan 01 §Route model).
 *
 * The typed v1 tree fetcher and the legacy node-report client are mocked at
 * the module boundary (react-query hooks and page logic stay REAL). The
 * shared D3 TreeVisualization is replaced with a lightweight stub so the
 * tests pin the PAGE contract — the v1-nodes -> TreeNode mapping handed to
 * the component and the selection wiring — not d3 internals (the real page
 * imports the legacy component unchanged; no forked D3 code exists to
 * test). Pins:
 *   - nodes from the mocked v1 tree pass-through reach the visualization
 *     (typed coercion via toTreeNodes — no ad-hoc reads);
 *   - URL node selection roundtrip: ?node= preselects the inspector, a
 *     click writes ?node= back to the hash (shareable URL), Close clears it;
 *   - frozen orchestrator vocabularies (NodeStatus/NodeLabel verbatim);
 *   - RQGM sentinel display for a penalized node: pre-penalty score,
 *     validated penalty, utility policy hash chip, stale marker — plus the
 *     honest absence contract (sentinelsOf never fabricates values);
 *   - node report via the legacy /api/nodes/{run}/{node}/report client;
 *   - deep links: Governance carries ONLY ?run= (GovernancePage reads no
 *     node from the URL — stated in the UI), Config browser carries ?run=;
 *   - realtime: subscription on topic 'tree' for the run; a dropped stream
 *     keeps the snapshot under a StaleDataBanner (never "run stopped");
 *   - typed error envelope -> ErrorState with request_id; no-run empty
 *     state;
 *   - nav takeover semantics: with gui_v2 on the Sidebar offers ONE Tree
 *     entry writing '#/tree2'; with it off, ONE Tree entry writing '#/tree'
 *     (legacy intact).
 */

vi.mock('../../../services/api/v1', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../services/api/v1')>();
  return {
    ...actual,
    fetchRunTreeV1: vi.fn(),
  };
});

vi.mock('../../../services/api/nodeReport', () => ({
  fetchNodeReport: vi.fn(),
}));

// Stub of the shared D3 component: renders one button per mapped node so the
// selection wiring is exercisable from jsdom (the real component draws SVG).
vi.mock('../../Tree/TreeVisualization', () => ({
  TreeVisualization: ({
    nodes,
    selectedNodeId,
    onSelectNode,
  }: {
    nodes: TreeNode[];
    selectedNodeId: string | null;
    onSelectNode: (id: string) => void;
  }) => (
    <div data-testid="tree-viz-stub" data-selected={selectedNodeId ?? ''}>
      {nodes.map((n) => (
        <button key={n.id} type="button" onClick={() => onSelectNode(n.id)}>
          {`viz-node-${n.id}`}
        </button>
      ))}
    </div>
  ),
}));

const treeMock = vi.mocked(fetchRunTreeV1);
const reportMock = vi.mocked(fetchNodeReport);

const RUN = 'run-tree2';

// ── payload builders ────────────────────────────────────────────────────

function makeTree(
  nodes: Array<Record<string, unknown>>,
): TreeV1 & RequestIdV1 {
  return {
    schema_version: 1,
    request_id: 'req-tree',
    run_id: RUN,
    revision: 7,
    nodes,
  };
}

// A penalized RQGM node: full sentinel set alongside a plain metric.
const PENALIZED_NODE: Record<string, unknown> = {
  id: 'n2',
  parent_id: 'n1',
  status: 'failed',
  label: 'debug',
  depth: 1,
  metrics: {
    _scientific_score: 0.42,
    _pre_penalty_score: 0.92,
    _validated_attack_penalty: 0.5,
    _utility_policy_hash: 'p0licyhash12',
    _stale: true,
    accuracy: 0.77,
  },
};

const BASE_NODES: Array<Record<string, unknown>> = [
  {
    id: 'n1',
    parent_id: null,
    status: 'success',
    label: 'draft',
    depth: 0,
    metrics: { _scientific_score: 0.5 },
  },
  PENALIZED_NODE,
];

// ── harness ─────────────────────────────────────────────────────────────

function makeClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0, refetchOnWindowFocus: false },
    },
  });
}

function renderPage(client: QueryClient = makeClient()) {
  return render(
    <QueryClientProvider client={client}>
      <TreeV2Page />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('ari_lang', 'en');
  window.location.hash = `#/tree2?run=${RUN}`;
  treeMock.mockReset();
  reportMock.mockReset();
  reportMock.mockResolvedValue({ error: 'no report' });
});

describe('TreeV2Page (gui_refresh Wave 4c v2 slice)', () => {
  it('feeds the mapped v1 tree nodes into the shared visualization', async () => {
    treeMock.mockResolvedValue(makeTree(BASE_NODES));
    renderPage();

    await waitFor(() =>
      expect(screen.getByTestId('tree-viz-stub')).toBeInTheDocument(),
    );
    expect(screen.getByText('viz-node-n1')).toBeInTheDocument();
    expect(screen.getByText('viz-node-n2')).toBeInTheDocument();
    // No selection yet: hint instead of inspector.
    expect(screen.queryByTestId('tree2-inspector')).toBeNull();
    expect(screen.getByText(/Select a node in the tree/)).toBeInTheDocument();
    expect(treeMock).toHaveBeenCalledWith(RUN);
  });

  it('toTreeNodes coerces the raw pass-through with type guards (no invented values)', () => {
    const mapped = toTreeNodes([
      { id: 'a', parent_id: null, status: 'success', label: 'draft', depth: 2 },
      { id: 'b', parent_id: 'a', depth: 'not-a-number', metrics: 'not-a-dict' },
      { parent_id: 'a' }, // no id: not drawable/selectable — dropped
    ]);
    expect(mapped.map((n) => n.id)).toEqual(['a', 'b']);
    expect(mapped[0].depth).toBe(2);
    expect(mapped[0].status).toBe('success');
    // Guarded fields fall back to honest defaults, never invented data.
    expect(mapped[1].depth).toBe(0);
    expect(mapped[1].metrics).toBeNull();
    expect(mapped[1].scientific_score).toBeNull();
  });

  it('preselects the inspector from ?node= and keeps the frozen status/label vocab verbatim', async () => {
    expect(NODE_STATUSES).toEqual(['pending', 'running', 'success', 'failed', 'abandoned']);
    expect(NODE_LABELS).toEqual(['draft', 'improve', 'debug', 'ablation', 'validation', 'other']);

    window.location.hash = `#/tree2?run=${RUN}&node=n2`;
    treeMock.mockResolvedValue(makeTree(BASE_NODES));
    renderPage();

    const inspector = await screen.findByTestId('tree2-inspector');
    expect(within(inspector).getByText('n2')).toBeInTheDocument();
    // Verbatim orchestrator tokens — never remapped display words.
    expect(within(inspector).getByText('failed')).toBeInTheDocument();
    expect(within(inspector).getByText('debug')).toBeInTheDocument();
    expect(screen.getByTestId('tree-viz-stub').getAttribute('data-selected')).toBe('n2');
  });

  it('roundtrips the selection through the URL: click writes ?node=, Close clears it', async () => {
    treeMock.mockResolvedValue(makeTree(BASE_NODES));
    renderPage();

    await waitFor(() =>
      expect(screen.getByText('viz-node-n1')).toBeInTheDocument(),
    );

    act(() => {
      screen.getByText('viz-node-n1').click();
    });
    // Shareable URL: the selection lands in the hash query …
    expect(window.location.hash).toBe(`#/tree2?run=${RUN}&node=n1`);
    // … and the hashchange round-trips back into the inspector.
    const inspector = await screen.findByTestId('tree2-inspector');
    expect(within(inspector).getByText('n1')).toBeInTheDocument();

    act(() => {
      within(inspector).getByRole('button', { name: 'Close' }).click();
    });
    expect(window.location.hash).toBe(`#/tree2?run=${RUN}`);
    await waitFor(() => expect(screen.queryByTestId('tree2-inspector')).toBeNull());
  });

  it('labels the RQGM sentinels of a penalized node (pre-penalty, validated penalty, policy hash chip, stale)', async () => {
    window.location.hash = `#/tree2?run=${RUN}&node=n2`;
    treeMock.mockResolvedValue(makeTree(BASE_NODES));
    renderPage();

    const inspector = await screen.findByTestId('tree2-inspector');
    expect(within(inspector).getByText('Scientific score')).toBeInTheDocument();
    expect(within(inspector).getByText('0.42')).toBeInTheDocument();
    expect(within(inspector).getByText('Pre-penalty score')).toBeInTheDocument();
    expect(within(inspector).getByText('0.92')).toBeInTheDocument();
    expect(within(inspector).getByText('Validated penalty')).toBeInTheDocument();
    expect(within(inspector).getByText('0.5')).toBeInTheDocument();
    expect(within(inspector).getByText('Utility policy')).toBeInTheDocument();
    expect(within(inspector).getByText('p0licyhash12')).toBeInTheDocument();
    expect(within(inspector).getByText('stale')).toBeInTheDocument();
    // Plain scalar metrics render under their own key.
    expect(within(inspector).getByText('accuracy')).toBeInTheDocument();
    expect(within(inspector).getByText('0.77')).toBeInTheDocument();

    // Honest-absence contract: missing sentinels stay null/false — never 0.
    expect(sentinelsOf(null, null)).toEqual({
      scientificScore: null,
      prePenaltyScore: null,
      validatedAttackPenalty: null,
      utilityPolicyHash: null,
      stale: false,
    });
    expect(sentinelsOf({ _scientific_score: 0.3 }, null).prePenaltyScore).toBeNull();
  });

  it('renders the node report from the legacy endpoint and the run-scoped deep links', async () => {
    window.location.hash = `#/tree2?run=${RUN}&node=n2`;
    treeMock.mockResolvedValue(makeTree(BASE_NODES));
    reportMock.mockResolvedValue({
      run_id: RUN,
      node_id: 'n2',
      report: {
        schema_version: 1,
        node_id: 'n2',
        files_changed: { added: [], modified: [], deleted: [], inherited_unchanged: [] },
        what_was_done: 'Fixed the data loader',
      },
    });
    renderPage();

    await waitFor(() =>
      expect(screen.getByText('Fixed the data loader')).toBeInTheDocument(),
    );
    expect(reportMock).toHaveBeenCalledWith(RUN, 'n2');

    // Governance deep link: ?run= ONLY (GovernancePage reads no node from
    // the URL today) — and the UI says so instead of implying preselect.
    expect(
      screen.getByText('Governance Score Lineage').getAttribute('href'),
    ).toBe(`#/governance?run=${RUN}`);
    expect(
      screen.getByText(/does not read a node from the URL/),
    ).toBeInTheDocument();
    expect(screen.getByText('Config browser').getAttribute('href')).toBe(
      `#/config?run=${RUN}`,
    );
  });

  it('subscribes topic tree for the run and keeps the snapshot under a StaleDataBanner on disconnect', async () => {
    class ControlES {
      static instances: ControlES[] = [];
      url: string;
      onopen: ((ev: Event) => void) | null = null;
      onerror: ((ev: Event) => void) | null = null;
      onmessage: ((ev: MessageEvent) => void) | null = null;
      constructor(url: string) {
        this.url = url;
        ControlES.instances.push(this);
      }
      addEventListener() {}
      removeEventListener() {}
      close() {}
    }
    vi.stubGlobal('EventSource', ControlES);

    treeMock.mockResolvedValue(makeTree(BASE_NODES));
    renderPage();

    await waitFor(() =>
      expect(screen.getByText('viz-node-n1')).toBeInTheDocument(),
    );
    const url = new URL(ControlES.instances[0].url, 'http://localhost');
    expect(url.pathname).toBe('/api/v1/events/stream');
    expect(url.searchParams.get('topics')).toBe('tree');
    expect(url.searchParams.get('run_id')).toBe(RUN);
    expect(screen.queryByText(/Showing last known data/)).toBeNull();

    act(() => {
      ControlES.instances[0].onerror?.(new Event('error'));
    });

    // Disconnected: the tree SURVIVES under the freshness banner (never
    // presented as "run stopped").
    expect(screen.getByText(/Showing last known data/)).toBeInTheDocument();
    expect(screen.getByText('viz-node-n1')).toBeInTheDocument();
  });

  it('surfaces a typed error envelope as ErrorState including the request_id', async () => {
    treeMock.mockRejectedValue(
      new ApiErrorV1({
        code: 'internal',
        message: 'tree loader exploded',
        details: null,
        request_id: 'req-err-9',
        retryable: true,
      }),
    );
    renderPage();

    await waitFor(() =>
      expect(screen.getByText(/tree loader exploded/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/req-err-9/)).toBeInTheDocument();
  });

  it('shows the empty state when no ?run= is present', async () => {
    window.location.hash = '#/tree2';
    renderPage();

    await waitFor(() =>
      expect(screen.getByText(/No run selected/)).toBeInTheDocument(),
    );
    expect(treeMock).not.toHaveBeenCalled();
  });
});

// ── Sidebar nav takeover (routeRegistry navReplaces — Wave 4c) ──────────

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

function renderSidebar(guiV2: boolean) {
  vi.stubGlobal('WebSocket', FakeWebSocket);
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const body: unknown = url.includes('/api/checkpoints')
        ? []
        : url.includes('/state')
          ? { nodes: [] }
          : {};
      return {
        ok: true,
        status: 200,
        json: async () => body,
        text: async () => JSON.stringify(body),
      } as unknown as Response;
    }),
  );
  return render(
    <AppProvider>
      <Sidebar guiV2={guiV2} />
    </AppProvider>,
  );
}

describe('Sidebar nav takeover (Wave 4c: tree2 replaces the tree slot)', () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem('ari_lang', 'en');
    window.location.hash = '#/home';
  });

  it('gui_v2 on: exactly one Tree entry and it writes #/tree2', () => {
    renderSidebar(true);
    const items = screen.getAllByText('Research tree');
    expect(items.length).toBe(1);
    act(() => {
      items[0].click();
    });
    expect(window.location.hash).toBe('#/tree2');
  });

  it('gui_v2 off: exactly one Tree entry and it writes the legacy #/tree', () => {
    renderSidebar(false);
    const items = screen.getAllByText('Research tree');
    expect(items.length).toBe(1);
    act(() => {
      items[0].click();
    });
    expect(window.location.hash).toBe('#/tree');
  });
});
