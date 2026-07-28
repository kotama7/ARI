import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, act, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { IdeasV2Page, bestHypothesisNode, toIdeaEntries } from '../IdeasV2Page';
import { AppProvider } from '../../../context/AppContext';
import { Sidebar } from '../../Layout/Sidebar';
import {
  ApiErrorV1,
  fetchRunIdeaV1,
  fetchRunTreeV1,
  type RequestIdV1,
  type RunIdeaV1,
  type TreeV1,
} from '../../../services/api/v1';
import type { TreeNode } from '../../../types';

/**
 * IdeasV2Page (gui_refresh task 07 Wave 4c — v2 Ideas workspace; plan 07
 * §Ideas, claims, and evidence, plan 01 §Route model).
 *
 * The typed v1 idea and tree fetchers are mocked at the module boundary
 * (react-query hooks and page logic stay REAL); AppContext runs against a
 * stubbed global fetch. Pins:
 *   - happy path: gap analysis / primary metric + rationale / VirSci
 *     hypotheses (verbatim idea.json entries, scores only when present) /
 *     BFTS hypotheses / strategy distribution all render from the mocked
 *     payloads;
 *   - deep links: the best hypothesis (legacy selection logic — highest
 *     score among eval_summary carriers) links to the TreeV2 workspace at
 *     #/tree2?run=<id>&node=<id>;
 *   - research-goal identity gate: the AppContext /state goal renders ONLY
 *     when state.checkpoint_id equals ?run=; otherwise the explicit
 *     "active checkpoint only" note (never another run's goal);
 *   - honest absence: present=false without degraded reasons -> the
 *     "run has not generated ideas yet" EmptyState; present=false WITH
 *     degraded reasons -> DegradedState with the parser's reasons (absence
 *     and corruption never conflated);
 *   - typed error envelope -> ErrorState with request_id; no-run empty
 *     state without any fetch;
 *   - nav takeover semantics: with gui_v2 on the Sidebar offers ONE Idea
 *     entry writing '#/ideas2'; with it off, ONE Idea entry writing the
 *     legacy '#/idea' (legacy intact).
 */

vi.mock('../../../services/api/v1', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../services/api/v1')>();
  return {
    ...actual,
    fetchRunIdeaV1: vi.fn(),
    fetchRunTreeV1: vi.fn(),
  };
});

const ideaMock = vi.mocked(fetchRunIdeaV1);
const treeMock = vi.mocked(fetchRunTreeV1);

const RUN = 'run-ideas2';

// ── payload builders ────────────────────────────────────────────────────

function makeIdea(over: Partial<RunIdeaV1> = {}): RunIdeaV1 & RequestIdV1 {
  return {
    schema_version: 1,
    request_id: 'req-idea',
    run_id: RUN,
    present: true,
    ideas: [],
    gap_analysis: null,
    primary_metric: null,
    metric_rationale: null,
    degraded_reasons: [],
    ...over,
  };
}

const FULL_IDEA = makeIdea({
  gap_analysis: 'Prior work never measured X under Y.',
  primary_metric: 'val_accuracy',
  metric_rationale: 'Directly comparable across baselines.',
  ideas: [
    {
      title: 'Adaptive masking',
      description: 'Mask tokens by uncertainty.',
      novelty_score: 8,
      feasibility_score: 6,
      overall_score: 7,
      experiment_plan: ['train baseline', 'add masking'],
    },
    {
      // No title/scores: honest fallbacks, no invented score rows.
      description: 'Second idea without metadata.',
    },
  ],
});

function makeTree(nodes: Array<Record<string, unknown>>): TreeV1 & RequestIdV1 {
  return {
    schema_version: 1,
    request_id: 'req-tree',
    run_id: RUN,
    revision: 3,
    nodes,
  };
}

const TREE_NODES: Array<Record<string, unknown>> = [
  {
    id: 'n0',
    parent_id: null,
    status: 'success',
    label: 'draft',
    depth: 0,
    score: 0.4,
    eval_summary: 'Root hypothesis works',
  },
  {
    id: 'n1',
    parent_id: 'n0',
    status: 'success',
    label: 'improve',
    depth: 1,
    score: 0.9,
    eval_summary: 'Improved hypothesis wins',
  },
  // pending eval_summary carriers are excluded from the list; nodes without
  // an eval_summary only count toward the strategy distribution.
  { id: 'n2', parent_id: 'n0', status: 'pending', label: 'debug', depth: 1, eval_summary: 'wip' },
  { id: 'n3', parent_id: 'n0', status: 'failed', label: 'ablation', depth: 1 },
];

// ── harness ─────────────────────────────────────────────────────────────

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

/** Stub the legacy transport feeding AppContext (/state, /api/checkpoints). */
function stubLegacyFetch(stateBody: Record<string, unknown>): void {
  vi.stubGlobal('WebSocket', FakeWebSocket);
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const body: unknown = url.includes('/api/checkpoints')
        ? []
        : url.includes('/state')
          ? stateBody
          : {};
      return {
        ok: true,
        status: 200,
        json: async () => body,
        text: async () => JSON.stringify(body),
      } as unknown as Response;
    }),
  );
}

function makeClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0, refetchOnWindowFocus: false },
    },
  });
}

function renderPage(stateBody: Record<string, unknown> = { nodes: [] }) {
  stubLegacyFetch(stateBody);
  return render(
    <QueryClientProvider client={makeClient()}>
      <AppProvider>
        <IdeasV2Page />
      </AppProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('ari_lang', 'en');
  window.location.hash = `#/ideas2?run=${RUN}`;
  ideaMock.mockReset();
  treeMock.mockReset();
  treeMock.mockResolvedValue(makeTree([]));
});

describe('IdeasV2Page (gui_refresh Wave 4c v2 slice)', () => {
  it('renders gap analysis, primary metric, VirSci hypotheses, BFTS hypotheses, and the strategy distribution', async () => {
    ideaMock.mockResolvedValue(FULL_IDEA);
    treeMock.mockResolvedValue(makeTree(TREE_NODES));
    renderPage();

    // idea.json content (verbatim pass-through).
    await waitFor(() =>
      expect(screen.getByText('Prior work never measured X under Y.')).toBeInTheDocument(),
    );
    expect(screen.getByText('val_accuracy')).toBeInTheDocument();
    expect(screen.getByText('Directly comparable across baselines.')).toBeInTheDocument();
    expect(screen.getByText('Adaptive masking')).toBeInTheDocument();
    expect(screen.getByText('Mask tokens by uncertainty.')).toBeInTheDocument();
    // Scores render only when present (honest absence for the second idea).
    expect(screen.getByText('Novelty')).toBeInTheDocument();
    expect(screen.getByText('Hypothesis 2')).toBeInTheDocument();
    // Experiment plan is collapsed behind a details toggle.
    expect(screen.getByText('Experiment plan')).toBeInTheDocument();

    // BFTS hypotheses from the run tree. The best hypothesis text shows in
    // the best block AND in its list row — both are the same node's summary.
    const bfts = screen.getByTestId('ideas2-bfts');
    expect(within(bfts).getAllByText('Improved hypothesis wins').length).toBe(2);
    expect(within(bfts).getByText('Root hypothesis works')).toBeInTheDocument();
    // Pending carriers stay out of the list.
    expect(within(bfts).queryByText('wip')).toBeNull();

    // Strategy distribution over ALL nodes (label counts).
    const strategy = screen.getByTestId('ideas2-strategy');
    expect(within(strategy).getByText(/4\s*nodes explored/)).toBeInTheDocument();
    expect(within(strategy).getByText('draft ×1')).toBeInTheDocument();
    expect(within(strategy).getByText('improve ×1')).toBeInTheDocument();
    expect(within(strategy).getByText('debug ×1')).toBeInTheDocument();
    expect(within(strategy).getByText('ablation ×1')).toBeInTheDocument();

    expect(ideaMock).toHaveBeenCalledWith(RUN);
    expect(treeMock).toHaveBeenCalledWith(RUN);
  });

  it('deep-links the best hypothesis to its TreeV2 node (legacy selection logic)', async () => {
    ideaMock.mockResolvedValue(FULL_IDEA);
    treeMock.mockResolvedValue(makeTree(TREE_NODES));
    renderPage();

    // n1 wins: highest score among eval_summary carriers.
    const link = await screen.findByText('Open in Tree workspace');
    expect(link.getAttribute('href')).toBe(`#/tree2?run=${RUN}&node=n1`);

    // Every listed hypothesis row links its node id into the TreeV2 URL.
    const bfts = screen.getByTestId('ideas2-bfts');
    expect(within(bfts).getByText('n0').closest('a')?.getAttribute('href')).toBe(
      `#/tree2?run=${RUN}&node=n0`,
    );

    // Pure-helper contract: no eval_summary carriers -> no best node (the
    // deep link is only offered when a node id is resolvable).
    expect(bestHypothesisNode([])).toBeNull();
    const noSummary = { id: 'x', eval_summary: null } as unknown as TreeNode;
    expect(bestHypothesisNode([noSummary])).toBeNull();
  });

  it('shows the research goal only when the run is the active checkpoint (identity gate)', async () => {
    ideaMock.mockResolvedValue(FULL_IDEA);
    renderPage({
      nodes: [],
      checkpoint_id: RUN,
      experiment_goal: 'Reduce validation loss on X',
    });

    await waitFor(() =>
      expect(screen.getByText('Reduce validation loss on X')).toBeInTheDocument(),
    );
    expect(
      screen.queryByText(/served for the active checkpoint only/),
    ).toBeNull();
  });

  it('refuses to show another checkpoint\'s goal: identity mismatch renders the explicit note', async () => {
    ideaMock.mockResolvedValue(FULL_IDEA);
    renderPage({
      nodes: [],
      checkpoint_id: 'some-other-checkpoint',
      experiment_goal: 'A goal belonging to a different run',
    });

    await waitFor(() =>
      expect(
        screen.getByText(/served for the active checkpoint only/),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText('A goal belonging to a different run')).toBeNull();
  });

  it('renders the "run has not generated ideas yet" EmptyState when idea.json is absent', async () => {
    ideaMock.mockResolvedValue(makeIdea({ present: false }));
    renderPage();

    await waitFor(() =>
      expect(
        screen.getByText('This run has not generated ideas yet.'),
      ).toBeInTheDocument(),
    );
    // Absent means absent: no idea-derived section cards are fabricated.
    expect(screen.queryByText('Gap analysis')).toBeNull();
    expect(ideaMock).toHaveBeenCalledWith(RUN);
  });

  it('renders DegradedState (not the empty state) for a malformed idea.json', async () => {
    ideaMock.mockResolvedValue(
      makeIdea({
        present: false,
        degraded_reasons: ['idea.json is not valid JSON: line 1'],
      }),
    );
    renderPage();

    await waitFor(() =>
      expect(
        screen.getByText(/idea\.json is not valid JSON: line 1/),
      ).toBeInTheDocument(),
    );
    // Corruption is never presented as "no ideas yet".
    expect(screen.queryByText('This run has not generated ideas yet.')).toBeNull();
  });

  it('surfaces a typed error envelope as ErrorState including the request_id', async () => {
    ideaMock.mockRejectedValue(
      new ApiErrorV1({
        code: 'internal',
        message: 'idea loader exploded',
        details: null,
        request_id: 'req-err-7',
        retryable: true,
      }),
    );
    renderPage();

    await waitFor(() =>
      expect(screen.getByText(/idea loader exploded/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/req-err-7/)).toBeInTheDocument();
  });

  it('shows the empty state when no ?run= is present (no fetch fired)', async () => {
    window.location.hash = '#/ideas2';
    renderPage();

    await waitFor(() =>
      expect(screen.getByText(/No run selected/)).toBeInTheDocument(),
    );
    expect(ideaMock).not.toHaveBeenCalled();
    expect(treeMock).not.toHaveBeenCalled();
  });

  it('toIdeaEntries coerces verbatim idea dicts without inventing values', () => {
    const entries = toIdeaEntries([
      {
        title: 'A',
        novelty_score: 5,
        experiment_plan: { phase1: 'train', phase2: 'eval' },
      },
      { experiment_plan: 'just a sentence' },
    ]);
    expect(entries[0].title).toBe('A');
    expect(entries[0].noveltyScore).toBe('5');
    expect(entries[0].feasibilityScore).toBeNull(); // absent stays absent
    expect(entries[0].experimentPlan).toBe('phase1: train\nphase2: eval');
    expect(entries[1].title).toBe('Hypothesis 2');
    expect(entries[1].experimentPlan).toBe('just a sentence');
  });
});

// ── Sidebar nav takeover (routeRegistry navReplaces — Wave 4c) ──────────

function renderSidebar(guiV2: boolean) {
  stubLegacyFetch({ nodes: [] });
  return render(
    <AppProvider>
      <Sidebar guiV2={guiV2} />
    </AppProvider>,
  );
}

describe('Sidebar nav takeover (Wave 4c: ideas2 replaces the idea slot)', () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem('ari_lang', 'en');
    window.location.hash = '#/home';
  });

  it('gui_v2 on: exactly one Idea entry and it writes #/ideas2', () => {
    renderSidebar(true);
    const items = screen.getAllByText('Idea');
    expect(items.length).toBe(1);
    act(() => {
      items[0].click();
    });
    expect(window.location.hash).toBe('#/ideas2');
  });

  it('gui_v2 off: exactly one Idea entry and it writes the legacy #/idea', () => {
    renderSidebar(false);
    const items = screen.getAllByText('Idea');
    expect(items.length).toBe(1);
    act(() => {
      items[0].click();
    });
    expect(window.location.hash).toBe('#/idea');
  });
});
