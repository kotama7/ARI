import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LogsPanel } from '../LogsPanel';
import {
  fetchRunLogsV1,
  type RequestIdV1,
  type RunLogsV1,
} from '../../../services/api/v1';

/**
 * LogsPanel (gui_refresh task 07 tail — plan 07 §Artifacts, logs, and
 * diagnostics; P4 layer of the Overview page).
 *
 * The typed v1 fetcher is mocked at the module boundary (panel logic stays
 * REAL). Pins:
 *   - lazy P4 layer: NOTHING is fetched while collapsed; expanding fetches
 *     one page from cursor 0;
 *   - [Load more] continues from the returned next_cursor and APPENDS with
 *     no duplicate (offset-keyed merge — even a replayed page adds nothing);
 *   - tail-follow: enabling the toggle + each delivered run event
 *     (lastEventAt prop change) triggers one next_cursor fetch — no timer;
 *   - grep filter: submitting the filter restarts the chain from cursor 0
 *     with the grep param and resets the shown entries;
 *   - honest absence: present=false renders the "no log yet" note, never an
 *     error.
 */

vi.mock('../../../services/api/v1', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../services/api/v1')>();
  return { ...actual, fetchRunLogsV1: vi.fn() };
});

const logsMock = vi.mocked(fetchRunLogsV1);

const RUN = 'run-logs';

function makePage(overrides: Partial<RunLogsV1> = {}): RunLogsV1 & RequestIdV1 {
  return {
    schema_version: 1,
    request_id: 'req-logs',
    run_id: RUN,
    present: true,
    entries: [],
    next_cursor: 0,
    eof: true,
    file_size: 0,
    degraded_reasons: [],
    ...overrides,
  };
}

function renderPanel(props: Partial<Parameters<typeof LogsPanel>[0]> = {}) {
  return render(
    <LogsPanel
      runId={RUN}
      lastEventAt={null}
      connectionState="live"
      {...props}
    />,
  );
}

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('ari_lang', 'en');
  logsMock.mockReset();
});

describe('LogsPanel (gui_refresh task 07 tail cursor log explorer)', () => {
  it('fetches nothing while collapsed; expanding loads page one from cursor 0', async () => {
    logsMock.mockResolvedValue(
      makePage({
        entries: [
          { offset: 0, line: 'alpha' },
          { offset: 6, line: 'beta' },
        ],
        next_cursor: 11,
        file_size: 11,
      }),
    );
    renderPanel();

    // Lazy P4 layer: collapsed panel has not touched the wire.
    expect(logsMock).not.toHaveBeenCalled();

    await userEvent.click(screen.getByText('Show logs'));
    await waitFor(() => expect(screen.getByText('alpha')).toBeInTheDocument());
    expect(screen.getByText('beta')).toBeInTheDocument();
    expect(logsMock).toHaveBeenCalledTimes(1);
    expect(logsMock).toHaveBeenCalledWith(RUN, { cursor: 0, grep: undefined });
    // eof: the end marker shows and there is no Load more button.
    expect(screen.getByText('End of committed log')).toBeInTheDocument();
    expect(screen.queryByText('Load more')).toBeNull();
  });

  it('[Load more] continues from next_cursor and appends without duplicates', async () => {
    logsMock
      .mockResolvedValueOnce(
        makePage({
          entries: [{ offset: 0, line: 'page1 line' }],
          next_cursor: 11,
          eof: false,
          file_size: 40,
        }),
      )
      // The second page REPLAYS the first entry (offset 0) plus a new one:
      // the offset-keyed merge must drop the duplicate.
      .mockResolvedValueOnce(
        makePage({
          entries: [
            { offset: 0, line: 'page1 line' },
            { offset: 11, line: 'page2 line' },
          ],
          next_cursor: 40,
          eof: true,
          file_size: 40,
        }),
      );
    renderPanel();

    await userEvent.click(screen.getByText('Show logs'));
    await waitFor(() =>
      expect(screen.getByText('page1 line')).toBeInTheDocument(),
    );
    expect(screen.getByText('1 lines loaded')).toBeInTheDocument();

    await userEvent.click(screen.getByText('Load more'));
    await waitFor(() =>
      expect(screen.getByText('page2 line')).toBeInTheDocument(),
    );
    // Cursor chain: the second fetch resumed exactly at page one's
    // next_cursor.
    expect(logsMock).toHaveBeenNthCalledWith(2, RUN, {
      cursor: 11,
      grep: undefined,
    });
    // No duplicate row: the replayed offset-0 entry appears exactly once.
    expect(screen.getAllByText('page1 line')).toHaveLength(1);
    expect(screen.getByText('2 lines loaded')).toBeInTheDocument();
  });

  it('follow mode fetches the next cursor page on each delivered run event', async () => {
    logsMock.mockResolvedValue(
      makePage({
        entries: [{ offset: 0, line: 'first' }],
        next_cursor: 6,
        file_size: 6,
      }),
    );
    const view = renderPanel({ lastEventAt: null });

    await userEvent.click(screen.getByText('Show logs'));
    await waitFor(() => expect(logsMock).toHaveBeenCalledTimes(1));

    // Follow off: an event alone must NOT fetch.
    view.rerender(
      <LogsPanel runId={RUN} lastEventAt={1000} connectionState="live" />,
    );
    await new Promise((r) => setTimeout(r, 0));
    expect(logsMock).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByText('Follow tail'));
    // Toggling follow with a delivered event catches up immediately …
    await waitFor(() => expect(logsMock).toHaveBeenCalledTimes(2));
    expect(logsMock).toHaveBeenNthCalledWith(2, RUN, {
      cursor: 6,
      grep: undefined,
    });

    // … and each subsequent event triggers exactly one more fetch.
    view.rerender(
      <LogsPanel runId={RUN} lastEventAt={2000} connectionState="live" />,
    );
    await waitFor(() => expect(logsMock).toHaveBeenCalledTimes(3));
    expect(logsMock).toHaveBeenNthCalledWith(3, RUN, {
      cursor: 6,
      grep: undefined,
    });
  });

  it('applying the grep filter restarts the chain from cursor 0 with the filter', async () => {
    logsMock
      .mockResolvedValueOnce(
        makePage({
          entries: [
            { offset: 0, line: 'noise line' },
            { offset: 11, line: 'ERROR boom' },
          ],
          next_cursor: 22,
          file_size: 22,
        }),
      )
      .mockResolvedValueOnce(
        makePage({
          entries: [{ offset: 11, line: 'ERROR boom' }],
          next_cursor: 22,
          file_size: 22,
        }),
      );
    renderPanel();

    await userEvent.click(screen.getByText('Show logs'));
    await waitFor(() =>
      expect(screen.getByText('noise line')).toBeInTheDocument(),
    );

    await userEvent.type(screen.getByLabelText('Log filter'), 'error{Enter}');
    // Restarted chain: cursor 0 with the grep needle.
    await waitFor(() =>
      expect(logsMock).toHaveBeenNthCalledWith(2, RUN, {
        cursor: 0,
        grep: 'error',
      }),
    );
    // The unfiltered rows were reset — only the match remains.
    await waitFor(() =>
      expect(screen.getByText('ERROR boom')).toBeInTheDocument(),
    );
    expect(screen.queryByText('noise line')).toBeNull();
  });

  it('renders the honest-absence note when the log does not exist yet', async () => {
    logsMock.mockResolvedValue(makePage({ present: false }));
    renderPanel();

    await userEvent.click(screen.getByText('Show logs'));
    await waitFor(() =>
      expect(
        screen.getByText(/ari\.log has not been written/),
      ).toBeInTheDocument(),
    );
    // Absence is not an error state.
    expect(screen.queryByText(/Retry/)).toBeNull();
  });

  it('shows the in-panel stale banner only while following with the stream down', async () => {
    logsMock.mockResolvedValue(makePage());
    const view = renderPanel({ connectionState: 'offline', lastEventAt: 500 });

    await userEvent.click(screen.getByText('Show logs'));
    await waitFor(() => expect(logsMock).toHaveBeenCalled());
    // Not following: no banner even though the stream is down.
    expect(screen.queryByText(/Showing last known data/)).toBeNull();

    await userEvent.click(screen.getByText('Follow tail'));
    expect(screen.getByText(/Showing last known data/)).toBeInTheDocument();

    view.rerender(
      <LogsPanel runId={RUN} lastEventAt={500} connectionState="live" />,
    );
    expect(screen.queryByText(/Showing last known data/)).toBeNull();
  });
});
