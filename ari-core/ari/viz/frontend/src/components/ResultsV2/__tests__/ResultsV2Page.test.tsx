import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, act, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ResultsV2Page, deriveEarLineage, shortDigest } from '../ResultsV2Page';
import { AppProvider } from '../../../context/AppContext';
import { Sidebar } from '../../Layout/Sidebar';
import {
  ApiErrorV1,
  fetchRunEarV1,
  fetchRunResultsV1,
  fetchRunV1,
  type RequestIdV1,
  type ResultEarV1,
  type RunDetailV1,
  type RunEarV1,
  type RunResultsV1,
} from '../../../services/api/v1';

/**
 * ResultsV2Page (gui_refresh task 07 Wave 4d — v2 Results/EAR workspace;
 * plan 07 §Evidence, Results, and PaperBench, plan 01 §Route model).
 *
 * The typed v1 results/ear/run fetchers are mocked at the module boundary
 * (react-query hooks and page logic stay REAL). Pins over the four fixture
 * variants (bare / reviewed / ORS-graded / EAR-published):
 *   - honest absence: a bare run renders per-section absence lines, never
 *     fabricated scores/verdicts/lineage;
 *   - review scores: rubric dimensions + overall + decision badge;
 *   - ORS verdict chip with chain provenance (rubric → replicator → phase1
 *     → judge grade stage badges, judge model);
 *   - EAR lineage badge chain curate → preview → publish → promote is
 *     READ-ONLY: stage states derive from artifact facts, mutations are
 *     delegated to the legacy #/results page via an explicit link+note (no
 *     mutation fires here — this page has no POST path at all);
 *   - bundle digest / visibility provenance (publish record vs manifest);
 *   - deep links: TreeV2 + Config always, Governance only when the run's
 *     rqgm capability is on, legacy Results always;
 *   - typed error envelope -> ErrorState with request_id; degraded_reasons
 *     -> DegradedState; no-run empty state without any fetch;
 *   - nav takeover semantics: with gui_v2 on the Sidebar offers ONE
 *     Results entry writing '#/results2'; with it off, ONE Results entry
 *     writing the legacy '#/results' (legacy intact).
 */

vi.mock('../../../services/api/v1', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../services/api/v1')>();
  return {
    ...actual,
    fetchRunResultsV1: vi.fn(),
    fetchRunEarV1: vi.fn(),
    fetchRunV1: vi.fn(),
  };
});

const resultsMock = vi.mocked(fetchRunResultsV1);
const earMock = vi.mocked(fetchRunEarV1);
const runMock = vi.mocked(fetchRunV1);

const RUN = 'run-results2';

// ── payload builders ────────────────────────────────────────────────────

const BARE_EAR: ResultEarV1 = {
  present: false,
  curated: false,
  published: false,
  visibility: null,
  visibility_source: null,
  dry_run: null,
  promoted_at: null,
};

function makeResults(over: Partial<RunResultsV1> = {}): RunResultsV1 & RequestIdV1 {
  return {
    schema_version: 1,
    request_id: 'req-results',
    run_id: RUN,
    paper: { pdf_present: false, tex_present: false },
    review: {
      report_present: false,
      overall_score: null,
      abstract_score: null,
      body_score: null,
      decision: null,
      confidence: null,
      rubric_id: null,
      dimensions: [],
    },
    ors: {
      chain_present: false,
      rubric_present: false,
      replicator_present: false,
      seed_present: false,
      phase1_present: false,
      grade_present: false,
      verdict: null,
      summary: null,
      ors_score: null,
      raw_score: null,
      passed_leaves: null,
      total_leaves: null,
      judge_model: null,
    },
    ear: { ...BARE_EAR },
    degraded_reasons: [],
    ...over,
  };
}

const REVIEWED = makeResults({
  paper: { pdf_present: true, tex_present: true },
  review: {
    report_present: true,
    overall_score: 7.2,
    abstract_score: null,
    body_score: null,
    decision: 'accept',
    confidence: 3.5,
    rubric_id: 'neurips',
    dimensions: [
      { name: 'soundness', value: 6.5, scale_min: 0, scale_max: 10 },
      { name: 'novelty', value: 8, scale_min: 0, scale_max: 10 },
    ],
  },
  ors: {
    chain_present: true,
    rubric_present: true,
    replicator_present: true,
    seed_present: false,
    phase1_present: true,
    grade_present: true,
    verdict: 'REPRODUCED',
    summary: 'PaperBench grading: 3/4 leaves passed (weighted score 0.813).',
    ors_score: 0.8125,
    raw_score: 0.7313,
    passed_leaves: 3,
    total_leaves: 4,
    judge_model: 'claude-haiku-4-5',
  },
});

const PUBLISHED_EAR: ResultEarV1 = {
  present: true,
  curated: true,
  published: true,
  visibility: 'staged',
  visibility_source: 'publish_record',
  dry_run: false,
  promoted_at: null,
};

function makeEarDetail(over: Partial<RunEarV1> = {}): RunEarV1 & RequestIdV1 {
  return {
    schema_version: 1,
    request_id: 'req-ear',
    run_id: RUN,
    present: true,
    publish_yaml_present: true,
    files: [
      { path: 'README.md', kind: 'file', size: 42 },
      { path: 'publish.yaml', kind: 'file', size: 60 },
      { path: 'reproduce.sh', kind: 'file', size: 21 },
    ],
    file_count: 3,
    truncated: false,
    curated: {
      manifest_present: true,
      bundle_sha256: 'abcdef0123456789deadbeef0123456789abcdef0123456789abcdef012345',
      file_count: 2,
      excluded_count: 1,
      visibility: 'staged',
      created_at: '2026-07-23T00:00:00Z',
    },
    published: {
      record_present: true,
      backend: 'local_tarball',
      ref: 'ear://fixture/abcdef012345',
      bundle_sha256: 'abcdef0123456789deadbeef0123456789abcdef0123456789abcdef012345',
      visibility: 'staged',
      dry_run: false,
      timestamp: '2026-07-23T00:00:00Z',
      promoted_at: null,
    },
    degraded_reasons: [],
    ...over,
  };
}

function makeRunDetail(rqgm: boolean): RunDetailV1 & RequestIdV1 {
  return {
    schema_version: 1,
    request_id: 'req-run',
    run_id: RUN,
    project_id: 'default',
    display_name: 'results2',
    status: 'completed',
    node_count: 4,
    review_score: null,
    best_metric: null,
    mtime_utc: '2026-07-23T00:00:00Z',
    checkpoint_path: `/tmp/${RUN}`,
    has_paper: false,
    phase: 'review',
    capabilities: { rqgm },
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

function renderPage() {
  return render(
    <QueryClientProvider client={makeClient()}>
      <ResultsV2Page />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('ari_lang', 'en');
  window.location.hash = `#/results2?run=${RUN}`;
  resultsMock.mockReset();
  earMock.mockReset();
  runMock.mockReset();
  earMock.mockResolvedValue(makeEarDetail());
  runMock.mockResolvedValue(makeRunDetail(false));
});

describe('ResultsV2Page (gui_refresh Wave 4d v2 slice)', () => {
  it('bare run: honest per-section absence, no fabricated scores or lineage', async () => {
    resultsMock.mockResolvedValue(makeResults());
    earMock.mockResolvedValue(
      makeEarDetail({
        present: false,
        publish_yaml_present: false,
        files: [],
        file_count: 0,
        curated: {
          manifest_present: false,
          bundle_sha256: null,
          file_count: null,
          excluded_count: null,
          visibility: null,
          created_at: null,
        },
        published: {
          record_present: false,
          backend: null,
          ref: null,
          bundle_sha256: null,
          visibility: null,
          dry_run: null,
          timestamp: null,
          promoted_at: null,
        },
      }),
    );
    renderPage();

    await waitFor(() =>
      expect(
        screen.getByText('No review report recorded for this run yet.'),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByText('No ORS reproducibility chain recorded for this run.'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('No Experiment Artifact Record for this run yet.'),
    ).toBeInTheDocument();
    // No badge chain, no verdict, no digest is fabricated for absence.
    expect(screen.queryByTestId('results2-ear-chain')).toBeNull();
    expect(screen.queryByText(/sha256:/)).toBeNull();
    expect(resultsMock).toHaveBeenCalledWith(RUN);
  });

  it('reviewed + ORS-graded run: rubric dimensions, decision badge, verdict chip with chain provenance', async () => {
    resultsMock.mockResolvedValue(REVIEWED);
    renderPage();

    const review = await screen.findByTestId('results2-review');
    expect(within(review).getByText('soundness')).toBeInTheDocument();
    expect(within(review).getByText('6.5')).toBeInTheDocument();
    expect(within(review).getByText('novelty')).toBeInTheDocument();
    expect(within(review).getByText('Overall')).toBeInTheDocument();
    expect(within(review).getByText('7.2')).toBeInTheDocument();
    expect(within(review).getByText('Decision: accept')).toBeInTheDocument();
    expect(within(review).getByText('Rubric: neurips')).toBeInTheDocument();
    expect(within(review).getByText('paper .tex')).toBeInTheDocument();
    expect(within(review).getByText('paper .pdf')).toBeInTheDocument();
    const paperActions = screen.getByTestId('results2-paper-actions');
    expect(
      within(paperActions).getByText('Open original PDF').getAttribute('href'),
    ).toBe(
      `/api/checkpoint/${RUN}/paper.pdf`,
    );
    expect(
      within(paperActions).getByText('Preview / edit paper').getAttribute('href'),
    ).toBe(`#/results?run=${RUN}`);

    const ors = screen.getByTestId('results2-ors');
    expect(within(ors).getByText('REPRODUCED')).toBeInTheDocument();
    expect(within(ors).getByText('81.3%')).toBeInTheDocument();
    expect(within(ors).getByText(/3 \/ 4/)).toBeInTheDocument();
    expect(within(ors).getByText(/claude-haiku-4-5/)).toBeInTheDocument();
    // Chain provenance badges (seed stage is not part of the 4-chip chain).
    const chain = within(ors).getByTestId('results2-ors-chain');
    expect(within(chain).getByText('Rubric')).toBeInTheDocument();
    expect(within(chain).getByText('Replicator')).toBeInTheDocument();
    expect(within(chain).getByText('Phase 1 reproduce')).toBeInTheDocument();
    expect(within(chain).getByText('Judge grade')).toBeInTheDocument();
  });

  it('EAR-published run: read-only lineage chain, digest, visibility provenance, legacy mutation link', async () => {
    resultsMock.mockResolvedValue(makeResults({ ear: { ...PUBLISHED_EAR } }));
    renderPage();

    const chain = await screen.findByTestId('results2-ear-chain');
    // curate done, preview available, publish done, promote available.
    expect(within(chain).getByText('Curate ✓')).toBeInTheDocument();
    expect(within(chain).getByText('Preview')).toBeInTheDocument();
    expect(within(chain).getByText('Publish ✓')).toBeInTheDocument();
    expect(within(chain).getByText('Promote')).toBeInTheDocument();

    const ear = screen.getByTestId('results2-ear');
    expect(within(ear).getByText('staged')).toBeInTheDocument();
    expect(within(ear).getByText(/from publish record/)).toBeInTheDocument();
    expect(within(ear).getByText(/sha256:abcdef012345…/)).toBeInTheDocument();
    expect(within(ear).getByText(/2 bundled files/)).toBeInTheDocument();
    expect(within(ear).getByText(/ear:\/\/fixture\/abcdef012345/)).toBeInTheDocument();

    // Mutations are delegated to the legacy page — explicit link + note.
    const manage = within(ear).getByText('Curate / publish on the legacy Results page');
    expect(manage.getAttribute('href')).toBe(`#/results?run=${RUN}`);
    expect(
      within(ear).getByText(/This workspace is read-only/),
    ).toBeInTheDocument();
  });

  it('promoted run: promote stage done and public visibility', async () => {
    resultsMock.mockResolvedValue(
      makeResults({
        ear: {
          ...PUBLISHED_EAR,
          visibility: 'public',
          promoted_at: '2026-07-23T01:00:00Z',
        },
      }),
    );
    renderPage();

    const chain = await screen.findByTestId('results2-ear-chain');
    expect(within(chain).getByText('Promote ✓')).toBeInTheDocument();
    const ear = screen.getByTestId('results2-ear');
    expect(within(ear).getByText('public')).toBeInTheDocument();
    expect(within(ear).getByText(/2026-07-23T01:00:00Z/)).toBeInTheDocument();
  });

  it('deep links: TreeV2/Config/legacy always; Governance only when rqgm capability is on', async () => {
    resultsMock.mockResolvedValue(makeResults());
    runMock.mockResolvedValue(makeRunDetail(true));
    renderPage();

    const links = await screen.findByTestId('results2-links');
    await waitFor(() =>
      expect(within(links).getByText('Governance workspace')).toBeInTheDocument(),
    );
    expect(
      within(links).getByText('Tree workspace').getAttribute('href'),
    ).toBe(`#/tree2?run=${RUN}`);
    expect(
      within(links).getByText('Config browser').getAttribute('href'),
    ).toBe(`#/config?run=${RUN}`);
    expect(
      within(links).getByText('Governance workspace').getAttribute('href'),
    ).toBe(`#/governance?run=${RUN}`);
    expect(
      within(links)
        .getByText('Full paper workspace')
        .getAttribute('href'),
    ).toBe(`#/results?run=${RUN}`);
  });

  it('hides the Governance deep link for a simple_bfts run (rqgm off)', async () => {
    resultsMock.mockResolvedValue(makeResults());
    runMock.mockResolvedValue(makeRunDetail(false));
    renderPage();

    const links = await screen.findByTestId('results2-links');
    expect(within(links).getByText('Tree workspace')).toBeInTheDocument();
    expect(within(links).queryByText('Governance workspace')).toBeNull();
  });

  it('surfaces degraded_reasons as DegradedState alongside the sections', async () => {
    const base = makeResults();
    resultsMock.mockResolvedValue({
      ...base,
      review: { ...(base.review as NonNullable<typeof base.review>), report_present: true },
      degraded_reasons: ['review_report.json is not valid JSON: line 1'],
    });
    renderPage();

    await waitFor(() =>
      expect(
        screen.getByText(/review_report\.json is not valid JSON: line 1/),
      ).toBeInTheDocument(),
    );
    // The degraded banner does not suppress the sections themselves.
    expect(screen.getByTestId('results2-review')).toBeInTheDocument();
  });

  it('surfaces a typed error envelope as ErrorState including the request_id', async () => {
    resultsMock.mockRejectedValue(
      new ApiErrorV1({
        code: 'internal',
        message: 'results loader exploded',
        details: null,
        request_id: 'req-err-9',
        retryable: true,
      }),
    );
    renderPage();

    await waitFor(() =>
      expect(screen.getByText(/results loader exploded/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/req-err-9/)).toBeInTheDocument();
  });

  it('shows the empty state when no ?run= is present (no fetch fired)', async () => {
    window.location.hash = '#/results2';
    renderPage();

    await waitFor(() =>
      expect(screen.getByText(/No run selected/)).toBeInTheDocument(),
    );
    expect(resultsMock).not.toHaveBeenCalled();
    expect(earMock).not.toHaveBeenCalled();
  });

  it('deriveEarLineage / shortDigest pure-helper contract (facts only)', () => {
    // Nothing exists: everything pending.
    expect(deriveEarLineage(BARE_EAR)).toEqual({
      curate: 'pending',
      preview: 'pending',
      publish: 'pending',
      promote: 'pending',
      dryRun: false,
    });
    // ear/ exists but never curated: curate becomes available only.
    expect(deriveEarLineage({ ...BARE_EAR, present: true }).curate).toBe('available');
    // Curated: preview/publish open up; preview is NEVER 'done' (it has no
    // artifact of its own — an ephemeral inspection, not a recorded fact).
    const curated = deriveEarLineage({ ...BARE_EAR, present: true, curated: true });
    expect(curated).toEqual({
      curate: 'done',
      preview: 'available',
      publish: 'available',
      promote: 'pending',
      dryRun: false,
    });
    // Dry-run publish is flagged, not hidden.
    expect(
      deriveEarLineage({ ...PUBLISHED_EAR, dry_run: true }).dryRun,
    ).toBe(true);
    expect(shortDigest(null)).toBeNull();
    expect(shortDigest('')).toBeNull();
    expect(shortDigest('abcd')).toBe('abcd');
    expect(shortDigest('0123456789abcdef0123')).toBe('0123456789ab');
  });
});

// ── Sidebar nav takeover (routeRegistry navReplaces — Wave 4d) ──────────

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

describe('Sidebar nav takeover (Wave 4d: results2 replaces the results slot)', () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem('ari_lang', 'en');
    window.location.hash = '#/home';
  });

  it('gui_v2 on: exactly one Results entry and it writes #/results2', () => {
    renderSidebar(true);
    const items = screen.getAllByText('Paper & results');
    expect(items.length).toBe(1);
    act(() => {
      items[0].click();
    });
    expect(window.location.hash).toBe('#/results2');
  });

  it('gui_v2 off: exactly one Results entry and it writes the legacy #/results', () => {
    renderSidebar(false);
    const items = screen.getAllByText('Paper & results');
    expect(items.length).toBe(1);
    act(() => {
      items[0].click();
    });
    expect(window.location.hash).toBe('#/results');
  });
});
