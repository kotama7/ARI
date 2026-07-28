import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ProjectsPage } from '../ProjectsPage';
import {
  ApiErrorV1,
  fetchProjectsV1,
  fetchRunsV1,
  type ProjectListV1,
  type RequestIdV1,
  type RunListV1,
  type RunSummaryV1,
} from '../../../services/api/v1';

/**
 * ProjectsPage (gui_refresh Wave 2b — the first v2 vertical slice; plans 01
 * §Route model, 07 §Projects and run portfolio).
 *
 * The typed v1 fetchers are mocked at the module boundary (the react-query
 * hooks and the ApiErrorV1 normalization stay REAL), so these tests pin:
 *   - the run-portfolio table rendered from v1 payloads (status badge,
 *     counts, scores, freshness, RQGM capability chip);
 *   - the empty state with the plan-01 create/import/resume next actions;
 *   - the typed error envelope surfacing as ErrorState WITH request_id;
 *   - two-run isolation: after the mocked backend switches from run A to
 *     run B, no run-A value remains (query keys carry projectId/runId);
 *   - the legacy ExperimentsPage-style handoff on row click (sessionStorage
 *     'ari_selected_checkpoint' + '#/results' — Wave 4 replaces this with a
 *     run-explicit URL);
 *   - the run-explicit Overview link ('#/overview?run=<id>', Wave 4b) as the
 *     FIRST per-row action — the URL-shaped replacement direction for the
 *     sessionStorage handoff (plan 07 §Cross-workspace coordination);
 *   - realtime adoption (Wave 2b, ADR-03): when the /api/v1/events/stream
 *     connection drops, the table stays up under a StaleDataBanner — a
 *     disconnect is NEVER presented as "run stopped" (plan 01 §Empty and
 *     degraded states).
 */

vi.mock('../../../services/api/v1', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../services/api/v1')>();
  return {
    ...actual,
    fetchProjectsV1: vi.fn(),
    fetchRunsV1: vi.fn(),
  };
});

const projectsMock = vi.mocked(fetchProjectsV1);
const runsMock = vi.mocked(fetchRunsV1);

// ── payload builders (shapes from v1types.gen.ts) ───────────────────────

function makeProjects(projectId: string): ProjectListV1 & RequestIdV1 {
  return {
    schema_version: 1,
    request_id: 'req-projects',
    projects: [
      {
        schema_version: 1,
        project_id: projectId,
        name: projectId,
        checkpoint_roots: ['/tmp/ckpts'],
        run_count: 1,
      },
    ],
  };
}

function makeRun(overrides: Partial<RunSummaryV1> & { rqgm?: boolean }): RunSummaryV1 {
  const { rqgm, ...rest } = overrides;
  const base = {
    schema_version: 1,
    run_id: 'run-x',
    project_id: 'default',
    display_name: 'run-x',
    checkpoint_path: '/tmp/ckpts/run-x',
    status: 'completed',
    node_count: 0,
    review_score: null,
    best_metric: null,
    mtime_utc: '2026-07-23T00:00:00+00:00',
    ...rest,
  };
  // RunSummaryV1 does not (yet) declare capabilities — the page reads it
  // defensively from the wire payload, so the mock injects it the same way.
  return (rqgm === undefined
    ? base
    : { ...base, capabilities: { rqgm } }) as unknown as RunSummaryV1;
}

function makeRuns(projectId: string, runs: RunSummaryV1[]): RunListV1 & RequestIdV1 {
  return { schema_version: 1, request_id: 'req-runs', project_id: projectId, runs };
}

// ── harness ─────────────────────────────────────────────────────────────

function makeClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0, refetchOnWindowFocus: false } },
  });
}

function renderPage(client: QueryClient) {
  return render(
    <QueryClientProvider client={client}>
      <ProjectsPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('ari_lang', 'en');
  sessionStorage.clear();
  window.location.hash = '';
  projectsMock.mockReset();
  runsMock.mockReset();
});

describe('ProjectsPage (gui_refresh Wave 2b v2 slice)', () => {
  it('renders one table row per run from the mocked v1 payloads', async () => {
    projectsMock.mockResolvedValue(makeProjects('default'));
    runsMock.mockResolvedValue(
      makeRuns('default', [
        makeRun({
          run_id: 'run-2026a',
          status: 'running',
          node_count: 12,
          review_score: 7.5,
          best_metric: 0.91,
          rqgm: true,
        }),
        makeRun({
          run_id: 'run-2026b',
          status: 'completed',
          node_count: 3,
          rqgm: false,
        }),
      ]),
    );
    const { container } = renderPage(makeClient());

    await waitFor(() => expect(screen.getByText('run-2026a')).toBeInTheDocument());
    expect(screen.getByText('run-2026b')).toBeInTheDocument();
    expect(runsMock).toHaveBeenCalledWith('default');

    // Status badges via the shared StatusBadge mapping.
    expect(screen.getByText(/Running/)).toBeInTheDocument();
    expect(screen.getByText(/Done/)).toBeInTheDocument();
    // Counts and scores.
    expect(screen.getByText('12')).toBeInTheDocument();
    expect(screen.getByText('7.5')).toBeInTheDocument();
    expect(screen.getByText('0.91')).toBeInTheDocument();
    // Exactly ONE RQGM capability chip (run-2026a only).
    expect(screen.getAllByText('RQGM')).toHaveLength(1);
    // Two data rows.
    expect(container.querySelectorAll('tbody tr')).toHaveLength(2);
  });

  it('offers the run-explicit Overview link as the FIRST row action (Wave 4b)', async () => {
    projectsMock.mockResolvedValue(makeProjects('default'));
    runsMock.mockResolvedValue(makeRuns('default', [makeRun({ run_id: 'run-first' })]));
    const { container } = renderPage(makeClient());

    await waitFor(() => expect(screen.getByText('run-first')).toBeInTheDocument());
    // Row action order: Overview (run-explicit v2 workspace) FIRST, then the
    // Wave-3b Config link.
    const links = Array.from(container.querySelectorAll('tbody tr a'));
    expect(links.map((a) => a.getAttribute('href'))).toEqual([
      '#/overview?run=run-first',
      '#/config?run=run-first',
    ]);
    // The link swallows the click (stopPropagation) — the legacy row-click
    // results handoff must NOT fire.
    fireEvent.click(links[0]);
    expect(sessionStorage.getItem('ari_selected_checkpoint')).toBeNull();
  });

  it('row click performs the legacy results handoff (sessionStorage + #/results)', async () => {
    projectsMock.mockResolvedValue(makeProjects('default'));
    runsMock.mockResolvedValue(makeRuns('default', [makeRun({ run_id: 'run-click' })]));
    renderPage(makeClient());

    await waitFor(() => expect(screen.getByText('run-click')).toBeInTheDocument());
    fireEvent.click(screen.getByText('run-click'));

    expect(sessionStorage.getItem('ari_selected_checkpoint')).toBe('run-click');
    expect(window.location.hash).toBe('#/results');
  });

  it('shows the empty state with create/import/resume links to #/new', async () => {
    projectsMock.mockResolvedValue(makeProjects('default'));
    runsMock.mockResolvedValue(makeRuns('default', []));
    renderPage(makeClient());

    await waitFor(() => expect(screen.getByText('No runs yet')).toBeInTheDocument());
    for (const label of ['Create a run', 'Import', 'Resume']) {
      const link = screen.getByText(label);
      expect(link.getAttribute('href')).toBe('#/new');
    }
  });

  it('surfaces a typed error envelope as ErrorState including the request_id', async () => {
    projectsMock.mockRejectedValue(
      new ApiErrorV1({
        code: 'internal',
        message: 'scanner exploded',
        details: null,
        request_id: 'req-err-42',
        retryable: true,
      }),
    );
    runsMock.mockResolvedValue(makeRuns('default', []));
    renderPage(makeClient());

    await waitFor(() =>
      expect(screen.getByText(/scanner exploded/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/req-err-42/)).toBeInTheDocument();
  });

  it('keeps the table under a StaleDataBanner when the event stream drops', async () => {
    // Controllable EventSource (the global vitest.setup fake is a no-op, so
    // the page stays 'live' in every other test — no banner flash there).
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

    projectsMock.mockResolvedValue(makeProjects('default'));
    runsMock.mockResolvedValue(makeRuns('default', [makeRun({ run_id: 'run-live' })]));
    renderPage(makeClient());

    await waitFor(() => expect(screen.getByText('run-live')).toBeInTheDocument());
    // ADR-03 adoption: the list subscribes topic 'run' with no run_id filter.
    const url = new URL(ControlES.instances[0].url, 'http://localhost');
    expect(url.pathname).toBe('/api/v1/events/stream');
    expect(url.searchParams.get('topics')).toBe('run');
    expect(url.searchParams.get('run_id')).toBeNull();
    // Live connection: no freshness banner.
    expect(screen.queryByText(/Showing last known data/)).toBeNull();

    act(() => {
      ControlES.instances[0].onerror?.(new Event('error'));
    });

    // Disconnected: the table row SURVIVES under the banner (never "stopped")
    // and the banner carries a Last updated timestamp.
    expect(screen.getByText(/Showing last known data/)).toBeInTheDocument();
    expect(screen.getByText(/Last updated/)).toBeInTheDocument();
    expect(screen.getByText('run-live')).toBeInTheDocument();
  });

  it('two-run isolation: after switching to run B, no run-A value remains', async () => {
    // Shared client across both mounts — the run/project ids INSIDE the query
    // keys (plan 03) are what keeps run A's cache from bleeding into run B.
    const client = makeClient();

    projectsMock.mockResolvedValue(makeProjects('proj-a'));
    runsMock.mockImplementation(async (projectId: string) => {
      if (projectId === 'proj-a') {
        return makeRuns('proj-a', [
          makeRun({ run_id: 'run-alpha', project_id: 'proj-a', node_count: 42, best_metric: 0.11 }),
        ]);
      }
      return makeRuns('proj-b', [
        makeRun({ run_id: 'run-beta', project_id: 'proj-b', node_count: 7, best_metric: 0.99 }),
      ]);
    });

    const first = renderPage(client);
    await waitFor(() => expect(screen.getByText('run-alpha')).toBeInTheDocument());
    first.unmount();

    // Backend now reports project B; remount with the SAME query client.
    projectsMock.mockResolvedValue(makeProjects('proj-b'));
    renderPage(client);

    await waitFor(() => expect(screen.getByText('run-beta')).toBeInTheDocument());
    expect(screen.queryByText('run-alpha')).toBeNull();
    expect(screen.queryByText('42')).toBeNull();
    expect(screen.queryByText('0.11')).toBeNull();
    expect(runsMock).toHaveBeenCalledWith('proj-b');
  });
});
