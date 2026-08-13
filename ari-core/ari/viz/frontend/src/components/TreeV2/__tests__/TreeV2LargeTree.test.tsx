import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, act, fireEvent, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TreeV2Page } from '../TreeV2Page';
import { toTreeNodes } from '../treeNodes';
import { computeVisibleRows, LOD_NODE_THRESHOLD, LOD_DEPTH_LIMIT } from '../treeLod';
import {
  fetchRunTreeV1,
  type RequestIdV1,
  type TreeV1,
} from '../../../services/api/v1';
import { fetchNodeReport } from '../../../services/api/nodeReport';
import type { TreeNode } from '../../../types';

/**
 * TreeV2 large-tree behavior (gui_refresh task 07 tail). Two rules under
 * test: a large tree is reduced only in what it RENDERS (level-of-detail,
 * windowed side table) while the full node list stays in hand, and the
 * reduction is never silent — a view showing less than it has says so, with
 * exact counts and an opt-in to expand.
 *
 * Synthetic 10k-node array (the backend 10k fixture is run_fixture_factory
 * territory — frontend perf tests use synthetic node arrays). The D3
 * TreeVisualization is mocked at the data layer (a stub recording the node
 * array it receives), so these tests pin the PAGE contract:
 *   - LOD default: >500 nodes collapse to structural depth <= 3 (+ the
 *     selected node's ancestor path and its children), with an explicit
 *     "showing N of M nodes (depth-limited)" banner — counts exact;
 *   - [expand all] opt-in renders the full set (canvas receives all M
 *     nodes) while the table DOM stays windowed;
 *   - windowed side table: bounded DOM row count (< 100) for 10k rows,
 *     including while scrolled mid-list;
 *   - keyboard walk (ArrowDown / ArrowRight / Enter) moves the roving
 *     tabindex, expands a collapsed subtree, and writes ?node= to the URL
 *     (inspector opens) — the hash stays the single source of truth;
 *   - aria tree semantics: role=tree/treeitem, aria-level, aria-expanded,
 *     aria-selected;
 *   - selection parity canvas<->table through the shared ?node= URL state;
 *   - perf smoke: building the 10k visible set stays well under 200 ms.
 *
 * Tree shape: complete 3-ary tree over ids n0..n9999 (parent of n_i is
 * n_floor((i-1)/3)); level sizes 1/3/9/27/... so the depth<=3 default view
 * holds exactly 40 nodes, and the deep leaf n9999 has the ancestor path
 * n0,n1,n4,n13,n40,n122,n369,n1110,n3332 (visible-with-context set = 58).
 * Every node carries depth:0 to prove structural levels are derived from
 * the parent links, not the orchestrator-reported depth field.
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

// Data-layer stub of the shared D3 component: records the node array it was
// handed (count + selection) and renders a click button for the first three
// nodes only, so a 10k pass-through never materializes 10k DOM elements.
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
    <div
      data-testid="tree-viz-stub"
      data-node-count={nodes.length}
      data-selected={selectedNodeId ?? ''}
    >
      {nodes.slice(0, 3).map((n) => (
        <button key={n.id} type="button" onClick={() => onSelectNode(n.id)}>
          {`viz-node-${n.id}`}
        </button>
      ))}
    </div>
  ),
}));

const treeMock = vi.mocked(fetchRunTreeV1);
const reportMock = vi.mocked(fetchNodeReport);

const RUN = 'run-big-tree';
const TOTAL = 10000;

function makeBigTree(total: number): Array<Record<string, unknown>> {
  const nodes: Array<Record<string, unknown>> = [];
  for (let i = 0; i < total; i++) {
    nodes.push({
      id: `n${i}`,
      parent_id: i === 0 ? null : `n${Math.floor((i - 1) / 3)}`,
      status: 'success',
      label: 'draft',
      depth: 0, // deliberately wrong: structure must come from parent links
    });
  }
  return nodes;
}

function makeTree(nodes: Array<Record<string, unknown>>): TreeV1 & RequestIdV1 {
  return {
    schema_version: 1,
    request_id: 'req-big-tree',
    run_id: RUN,
    revision: 1,
    nodes,
  };
}

function makeClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0, refetchOnWindowFocus: false },
    },
  });
}

function renderPage() {
  return render(
    <QueryClientProvider client={makeClient()}>
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
  treeMock.mockResolvedValue(makeTree(makeBigTree(TOTAL)));
});

describe('TreeV2 large-tree LOD (plan 07 §Tree workspace, task 07 tail)', () => {
  it('depth-limits >500-node trees to depth<=3 with an exact non-silent banner', async () => {
    renderPage();

    const banner = await screen.findByTestId('tree2-lod-banner');
    // Levels 0..3 of the 3-ary tree: 1+3+9+27 = 40 nodes.
    expect(banner.textContent).toContain(
      'Showing 40 of 10000 nodes (depth-limited)',
    );
    // The CANVAS is depth-limited too: filtering happened before the node
    // array was passed in.
    expect(screen.getByTestId('tree-viz-stub').getAttribute('data-node-count')).toBe('40');
    // Windowed table: rows exist but the DOM stays bounded.
    const items = screen.getAllByRole('treeitem');
    expect(items.length).toBeGreaterThan(0);
    expect(items.length).toBeLessThan(100);
  });

  it('[expand all] opt-in renders the full set while the table DOM stays windowed', async () => {
    renderPage();

    const banner = await screen.findByTestId('tree2-lod-banner');
    act(() => {
      within(banner).getByRole('button', { name: 'Expand all' }).click();
    });

    // Full set flag: the canvas now receives ALL nodes.
    await waitFor(() =>
      expect(
        screen.getByTestId('tree-viz-stub').getAttribute('data-node-count'),
      ).toBe('10000'),
    );
    // The depth-limited banner is replaced by an honest "showing all" note.
    expect(screen.queryByTestId('tree2-lod-banner')).toBeNull();
    expect(screen.getByText('Showing all 10000 nodes')).toBeInTheDocument();
    // Windowing keeps the table DOM bounded even at 10k rows.
    expect(screen.getAllByRole('treeitem').length).toBeLessThan(100);
  });

  it('keeps the DOM row count bounded while scrolled mid-list (10k rows)', async () => {
    renderPage();

    const banner = await screen.findByTestId('tree2-lod-banner');
    act(() => {
      within(banner).getByRole('button', { name: 'Expand all' }).click();
    });
    await waitFor(() =>
      expect(
        screen.getByTestId('tree-viz-stub').getAttribute('data-node-count'),
      ).toBe('10000'),
    );

    const tree = screen.getByRole('tree');
    tree.scrollTop = 100000; // ~row 3571 of 10000
    fireEvent.scroll(tree);

    const items = screen.getAllByRole('treeitem');
    expect(items.length).toBeLessThan(100);
    // The window actually moved: the root row left the DOM.
    expect(items[0].getAttribute('data-node-id')).not.toBe('n0');
    expect(screen.queryByTitle('n0')).toBeNull();
  });

  it('keyboard walk: ArrowDown moves the roving focus, ArrowRight expands, Enter selects into the URL', async () => {
    renderPage();
    await screen.findByTestId('tree2-lod-banner');
    const tree = screen.getByRole('tree');

    // DFS order: n0, n1, n4, n13 (first depth-3 row, collapsed by LOD).
    fireEvent.keyDown(tree, { key: 'ArrowDown' });
    fireEvent.keyDown(tree, { key: 'ArrowDown' });
    fireEvent.keyDown(tree, { key: 'ArrowDown' });
    const n13 = screen.getByTitle('n13');
    expect(document.activeElement).toBe(n13);
    expect(n13.getAttribute('aria-expanded')).toBe('false');
    expect(n13.getAttribute('tabindex')).toBe('0');

    // ArrowRight expands the collapsed subtree; the banner count updates.
    fireEvent.keyDown(tree, { key: 'ArrowRight' });
    await waitFor(() =>
      expect(screen.getByTitle('n13').getAttribute('aria-expanded')).toBe('true'),
    );
    expect(screen.getByTitle('n40')).toBeInTheDocument();
    expect(screen.getByTestId('tree2-lod-banner').textContent).toContain(
      'Showing 43 of 10000 nodes (depth-limited)',
    );

    // ArrowDown enters the freshly expanded subtree; Enter selects it.
    fireEvent.keyDown(tree, { key: 'ArrowDown' });
    expect(document.activeElement?.getAttribute('data-node-id')).toBe('n40');
    fireEvent.keyDown(tree, { key: 'Enter' });
    expect(window.location.hash).toBe(`#/tree2?run=${RUN}&node=n40`);

    // The URL round-trips into the inspector (single source of truth).
    const inspector = await screen.findByTestId('tree2-inspector');
    expect(within(inspector).getByText('n40')).toBeInTheDocument();
  });

  it('exposes aria tree semantics: role, level, expanded, selected', async () => {
    window.location.hash = `#/tree2?run=${RUN}&node=n9999`;
    renderPage();
    await screen.findByTestId('tree2-lod-banner');

    const tree = screen.getByRole('tree', { name: 'Tree table' });
    expect(tree).toBeInTheDocument();

    const root = screen.getByTitle('n0');
    expect(root.getAttribute('role')).toBe('treeitem');
    expect(root.getAttribute('aria-level')).toBe('1');
    expect(root.getAttribute('aria-expanded')).toBe('true');
    expect(root.getAttribute('aria-selected')).toBe('false');

    // Collapsed depth-3 row off the selection path.
    const n14 = screen.getByTitle('n14');
    expect(n14.getAttribute('aria-level')).toBe('4');
    expect(n14.getAttribute('aria-expanded')).toBe('false');

    // The deep selected leaf: on-path so visible, selected, and — having
    // no children — carrying NO aria-expanded at all.
    const leaf = screen.getByTitle('n9999');
    expect(leaf.getAttribute('aria-level')).toBe('10');
    expect(leaf.getAttribute('aria-selected')).toBe('true');
    expect(leaf.hasAttribute('aria-expanded')).toBe(false);
  });

  it('keeps canvas and table selection in parity through the shared ?node= URL', async () => {
    // Deep URL preselect: ancestor path + its children join the depth<=3
    // set (40 + 6 levels x 3 children = 58) in BOTH views.
    window.location.hash = `#/tree2?run=${RUN}&node=n9999`;
    renderPage();

    const banner = await screen.findByTestId('tree2-lod-banner');
    expect(banner.textContent).toContain('Showing 58 of 10000 nodes (depth-limited)');
    const stub = screen.getByTestId('tree-viz-stub');
    expect(stub.getAttribute('data-node-count')).toBe('58');
    expect(stub.getAttribute('data-selected')).toBe('n9999');
    expect(screen.getByTitle('n9999').getAttribute('aria-selected')).toBe('true');

    // Canvas -> table: a canvas click rewrites ?node=, the table follows.
    act(() => {
      screen.getByText('viz-node-n1').click();
    });
    expect(window.location.hash).toBe(`#/tree2?run=${RUN}&node=n1`);
    await waitFor(() =>
      expect(screen.getByTitle('n1').getAttribute('aria-selected')).toBe('true'),
    );

    // Table -> canvas: a row click rewrites ?node=, the canvas follows.
    act(() => {
      screen.getByTitle('n4').click();
    });
    expect(window.location.hash).toBe(`#/tree2?run=${RUN}&node=n4`);
    await waitFor(() =>
      expect(
        screen.getByTestId('tree-viz-stub').getAttribute('data-selected'),
      ).toBe('n4'),
    );
  });

  it('small trees (<= threshold) render fully with no banner', async () => {
    treeMock.mockResolvedValue(
      makeTree([
        { id: 'a', parent_id: null, status: 'success', label: 'draft', depth: 0 },
        { id: 'b', parent_id: 'a', status: 'running', label: 'improve', depth: 1 },
        { id: 'c', parent_id: 'b', status: 'pending', label: 'debug', depth: 2 },
      ]),
    );
    renderPage();

    await waitFor(() =>
      expect(screen.getAllByRole('treeitem').length).toBe(3),
    );
    expect(screen.queryByTestId('tree2-lod-banner')).toBeNull();
    expect(screen.queryByTestId('tree2-lod-banner-all')).toBeNull();
    expect(screen.getByTestId('tree-viz-stub').getAttribute('data-node-count')).toBe('3');
  });

  it('perf smoke: builds the 10k visible set well under 200ms (loose bound)', () => {
    const nodes = toTreeNodes(makeBigTree(TOTAL));
    expect(nodes.length).toBe(TOTAL);
    expect(LOD_NODE_THRESHOLD).toBe(500);
    expect(LOD_DEPTH_LIMIT).toBe(3);

    const t0 = performance.now();
    const visible = computeVisibleRows(nodes, 'n9999', false, new Map());
    const elapsedMs = performance.now() - t0;

    expect(visible.total).toBe(TOTAL);
    expect(visible.rows.length).toBe(58);
    expect(visible.limited).toBe(true);
    // Loose assertion for slow CI machines; locally this is single-digit ms.
    expect(elapsedMs).toBeLessThan(200);

    // Expand-all path is O(n) too and yields the untruncated set.
    const all = computeVisibleRows(nodes, null, true, new Map());
    expect(all.rows.length).toBe(TOTAL);
    expect(all.limited).toBe(false);
  });
});
