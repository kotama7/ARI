import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, act, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  OverviewPage,
  RESEARCH_PHASES,
  governanceBlockers,
  researchPhaseOf,
} from '../OverviewPage';
import {
  ApiErrorV1,
  fetchRqgmOverviewV1,
  fetchRunSummaryV1,
  fetchRunV1,
  type RequestIdV1,
  type RqgmOverviewV1,
  type RunDetailV1,
  type RunSummaryV1,
} from '../../../services/api/v1';

/**
 * OverviewPage (gui_refresh task 07 Wave 4b — the v2 run Overview workspace:
 * the P1/P2 disclosure surface for ONE run, opened run-explicitly as
 * '#/overview?run=<run_id>'. It reads its run from the hash query string, never
 * from a hidden global selection, so without ?run= it shows an explicit prompt
 * instead of adopting somebody else's run).
 *
 * The typed v1 fetchers are mocked at the module boundary (react-query
 * hooks and page logic stay REAL). Pins:
 *   - the P1 row (lifecycle badge, research phase, last update) and P2
 *     StatBoxes/links rendered from the run detail + summary DTOs;
 *   - the RQGM variant: a governance stage row that is a SEPARATE labelled
 *     row from the research phase row (governance status and research status
 *     are two different state machines and are never mixed into one field or
 *     one legend) plus the #/governance?run= link;
 *   - the simple_bfts variant: NO governance stage row and NO governance
 *     link (capability-gated, not an error);
 *   - the research-phase vocabulary staying inside the frozen /state set
 *     (idle/starting/bfts/paper/review; null -> idle);
 *   - the blocker surface: degraded reasons / broken integrity from the
 *     rqgm overview read model render as a DegradedState, and its absence
 *     renders nothing;
 *   - realtime adoption: subscription on topics run+tree for the run, and
 *     a dropped stream keeping the snapshot under a StaleDataBanner — a
 *     disconnect is NEVER presented as "run stopped" — a stalled stream and a
 *     stopped run are different facts, and the banner claims staleness of the
 *     view, never a change of run state;
 *   - the typed error envelope surfacing as ErrorState WITH request_id;
 *   - the no-run empty state (#/overview without ?run=).
 */

vi.mock('../../../services/api/v1', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../services/api/v1')>();
  return {
    ...actual,
    fetchRunV1: vi.fn(),
    fetchRunSummaryV1: vi.fn(),
    fetchRqgmOverviewV1: vi.fn(),
  };
});

const detailMock = vi.mocked(fetchRunV1);
const summaryMock = vi.mocked(fetchRunSummaryV1);
const rqgmOverviewMock = vi.mocked(fetchRqgmOverviewV1);

const RUN = 'run-ov';

// ── payload builders (shapes from v1types.gen.ts) ───────────────────────

function makeSummary(overrides: Partial<RunSummaryV1> = {}): RunSummaryV1 & RequestIdV1 {
  return {
    schema_version: 1,
    request_id: 'req-summary',
    run_id: RUN,
    project_id: 'default',
    display_name: RUN,
    checkpoint_path: `/tmp/ckpts/${RUN}`,
    status: 'completed',
    node_count: 12,
    review_score: 7.5,
    best_metric: 0.91,
    mtime_utc: '2026-07-23T00:00:00+00:00',
    has_paper: false,
    ...overrides,
  };
}

function makeDetail(overrides: Partial<RunDetailV1> = {}): RunDetailV1 & RequestIdV1 {
  return {
    ...makeSummary(),
    request_id: 'req-detail',
    has_paper: false,
    phase: 'bfts',
    capabilities: { rqgm: false },
    ...overrides,
  };
}

function makeRqgmOverview(
  overrides: Partial<RqgmOverviewV1> = {},
): RqgmOverviewV1 & RequestIdV1 {
  return {
    schema_version: 1,
    request_id: 'req-rqgm-ov',
    run_id: RUN,
    current_epoch: 'epoch_2',
    utility_policy_hash: 'aaaaaaaaaaaa',
    constitution_hash: 'bbbbbbbbbbbb',
    registry_summary: {
      component_count: 1,
      prompt_count: 4,
      components_by_status: { active: 1 },
      prompts_by_status: { active: 4 },
    },
    last_committed_transition_at: '2026-07-20T00:00:00+00:00',
    integrity: {
      transitions_chain_ok: true,
      registry_verified: true,
      audit_chain_ok: true,
    },
    degraded_reasons: [],
    ...overrides,
  };
}

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
      <OverviewPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('ari_lang', 'en');
  window.location.hash = `#/overview?run=${RUN}`;
  detailMock.mockReset();
  summaryMock.mockReset();
  rqgmOverviewMock.mockReset();
});

describe('OverviewPage (gui_refresh Wave 4b v2 slice)', () => {
  it('renders the P1 row and P2 stat boxes/links for a simple_bfts run', async () => {
    detailMock.mockResolvedValue(makeDetail());
    summaryMock.mockResolvedValue(makeSummary());
    renderPage();

    // P1: lifecycle badge via the shared StatusBadge mapping + phase row.
    await waitFor(() => expect(screen.getByText(/Done/)).toBeInTheDocument());
    expect(screen.getByText('Lifecycle')).toBeInTheDocument();
    expect(screen.getByText('Research phase')).toBeInTheDocument();
    expect(screen.getByText('bfts')).toBeInTheDocument();
    expect(screen.getByText('Last update')).toBeInTheDocument();

    // P2: stat boxes from the run summary DTO.
    expect(screen.getByText('12')).toBeInTheDocument();
    expect(screen.getByText('7.5')).toBeInTheDocument();
    expect(screen.getByText('0.91')).toBeInTheDocument();

    // P2: workspace links — Research tree (legacy) + run-explicit Run config.
    expect(screen.getByText('Research tree').getAttribute('href')).toBe('#/tree');
    expect(screen.getByText('Run config').getAttribute('href')).toBe(
      `#/config?run=${RUN}`,
    );

    // simple_bfts: NO governance stage row, NO governance link, no rqgm fetch.
    expect(screen.queryByText('Governance stage')).toBeNull();
    expect(screen.queryByText('Governance')).toBeNull();
    expect(rqgmOverviewMock).not.toHaveBeenCalled();
  });

  it('RQGM run: governance stage is a SEPARATE labelled row, never mixed into the phase row', async () => {
    detailMock.mockResolvedValue(makeDetail({ capabilities: { rqgm: true } }));
    summaryMock.mockResolvedValue(makeSummary());
    rqgmOverviewMock.mockResolvedValue(makeRqgmOverview());
    renderPage();

    await waitFor(() =>
      expect(screen.getByText('Governance stage')).toBeInTheDocument(),
    );
    await waitFor(() => expect(screen.getByText('epoch_2')).toBeInTheDocument());

    // Two distinct labelled rows — governance status and research status are
    // separate state machines that never merge into one field: the phase row
    // holds the phase token and NOT the epoch; the governance-stage row holds
    // the epoch and NOT the phase token.
    const phaseRow = screen.getByText('Research phase').closest('div')!;
    const govRow = screen.getByText('Governance stage').closest('div')!;
    expect(phaseRow).not.toBe(govRow);
    expect(within(phaseRow as HTMLElement).getByText('bfts')).toBeInTheDocument();
    expect(within(phaseRow as HTMLElement).queryByText('epoch_2')).toBeNull();
    expect(within(govRow as HTMLElement).getByText('epoch_2')).toBeInTheDocument();
    expect(within(govRow as HTMLElement).queryByText('bfts')).toBeNull();
    // Policy hash rides on the governance row only.
    expect(
      within(govRow as HTMLElement).getByText('aaaaaaaaaaaa'),
    ).toBeInTheDocument();

    // The separation is also stated explicitly.
    expect(
      screen.getByText(/separate timelines — neither implies the other/),
    ).toBeInTheDocument();

    // Governance deep link appears for the RQGM run.
    expect(screen.getByText('Governance').getAttribute('href')).toBe(
      `#/governance?run=${RUN}`,
    );
  });

  it('keeps the rendered research phase inside the frozen vocabulary (null -> idle)', async () => {
    expect(RESEARCH_PHASES).toEqual(['idle', 'starting', 'bfts', 'paper', 'review']);
    expect(researchPhaseOf(null)).toBe('idle');
    expect(researchPhaseOf(undefined)).toBe('idle');
    for (const phase of ['bfts', 'paper', 'review']) {
      expect(RESEARCH_PHASES).toContain(researchPhaseOf(phase));
    }

    detailMock.mockResolvedValue(makeDetail({ phase: null }));
    summaryMock.mockResolvedValue(makeSummary());
    renderPage();

    await waitFor(() => expect(screen.getByText('idle')).toBeInTheDocument());
    const phaseRow = screen.getByText('Research phase').closest('div')!;
    const token = within(phaseRow as HTMLElement).getByText('idle').textContent;
    expect(RESEARCH_PHASES).toContain(token);
  });

  it('surfaces degraded/integrity-broken governance state as the P1 blocker surface', async () => {
    detailMock.mockResolvedValue(makeDetail({ capabilities: { rqgm: true } }));
    summaryMock.mockResolvedValue(makeSummary());
    rqgmOverviewMock.mockResolvedValue(
      makeRqgmOverview({
        degraded_reasons: ['transitions log torn tail'],
        integrity: {
          transitions_chain_ok: false,
          registry_verified: true,
          audit_chain_ok: true,
        },
      }),
    );
    renderPage();

    await waitFor(() => expect(screen.getByText('Blockers')).toBeInTheDocument());
    expect(screen.getByText('transitions log torn tail')).toBeInTheDocument();
    expect(screen.getByText('transitions chain: broken')).toBeInTheDocument();
    // Degraded governance record != research failure (explicit framing).
    expect(
      screen.getByText(/not research failure/),
    ).toBeInTheDocument();

    // Pure-helper contract: clean overview -> no blocker lines.
    expect(governanceBlockers(makeRqgmOverview())).toEqual([]);
  });

  it('renders NO blocker surface when the governance record is clean', async () => {
    detailMock.mockResolvedValue(makeDetail({ capabilities: { rqgm: true } }));
    summaryMock.mockResolvedValue(makeSummary());
    rqgmOverviewMock.mockResolvedValue(makeRqgmOverview());
    renderPage();

    await waitFor(() =>
      expect(screen.getByText('Governance stage')).toBeInTheDocument(),
    );
    expect(screen.queryByText('Blockers')).toBeNull();
  });

  it('subscribes run+tree topics and keeps the snapshot under a StaleDataBanner on disconnect', async () => {
    // Controllable EventSource (the global vitest.setup fake is a no-op).
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

    detailMock.mockResolvedValue(makeDetail());
    summaryMock.mockResolvedValue(makeSummary());
    renderPage();

    await waitFor(() => expect(screen.getByText(/Done/)).toBeInTheDocument());
    // ADR-03 adoption: run-scoped subscription over both overview topics.
    const url = new URL(ControlES.instances[0].url, 'http://localhost');
    expect(url.pathname).toBe('/api/v1/events/stream');
    expect(url.searchParams.get('topics')).toBe('run,tree');
    expect(url.searchParams.get('run_id')).toBe(RUN);
    // Live connection: no freshness banner.
    expect(screen.queryByText(/Showing last known data/)).toBeNull();

    act(() => {
      ControlES.instances[0].onerror?.(new Event('error'));
    });

    // Disconnected: the P1/P2 content SURVIVES under the banner (never
    // presented as "run stopped") and the banner carries a timestamp.
    expect(screen.getByText(/Showing last known data/)).toBeInTheDocument();
    expect(screen.getByText(/Last updated/)).toBeInTheDocument();
    expect(screen.getByText(/Done/)).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();
  });

  it('surfaces a typed error envelope as ErrorState including the request_id', async () => {
    detailMock.mockRejectedValue(
      new ApiErrorV1({
        code: 'internal',
        message: 'scanner exploded',
        details: null,
        request_id: 'req-err-7',
        retryable: true,
      }),
    );
    summaryMock.mockResolvedValue(makeSummary());
    renderPage();

    await waitFor(() =>
      expect(screen.getByText(/scanner exploded/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/req-err-7/)).toBeInTheDocument();
  });

  it('shows the empty state when no ?run= is present', async () => {
    window.location.hash = '#/overview';
    renderPage();

    await waitFor(() =>
      expect(screen.getByText(/No run selected/)).toBeInTheDocument(),
    );
    expect(detailMock).not.toHaveBeenCalled();
    expect(summaryMock).not.toHaveBeenCalled();
  });
});
