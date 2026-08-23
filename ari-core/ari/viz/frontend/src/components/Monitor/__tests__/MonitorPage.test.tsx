import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { AppProvider } from '../../../context/AppContext';
import { MonitorPage } from '../MonitorPage';

/**
 * MonitorPage partial /api/resource-metrics regression. The client-side rule
 * this pins — every numeric field of that payload is optional — is stated in
 * docs/reference/rest_api.md §"State + dashboards".
 *
 * The legacy page used to call `.toFixed()` on resource-metrics fields
 * unconditionally, so a PARTIAL payload (sampler warm-up, scrape error,
 * older server) crashed the whole route with
 * `resourceMetrics.memory_rss_mb.toFixed is not a function`. The Wave-1
 * baselines papered over this with full-shape mocks — a mock-level
 * workaround, since removed. This test feeds the REAL page a partial
 * payload and pins the fix: present fields render, absent fields render a
 * placeholder, and nothing throws.
 */

const originalFetch = globalThis.fetch;

// Partial on purpose — memory_rss_mb, cpu_load_*, cpu_count, experiment_pid
// all absent. This exact shape crashed the pre-fix page.
const PARTIAL_RESOURCE_METRICS = { process_count: 3 };

const asResponse = (body: unknown): Response =>
  ({
    ok: true,
    status: 200,
    json: async () => body,
    text: async () => JSON.stringify(body),
  }) as unknown as Response;

// Same offline-transport strategy as routeRenderBaseline.test.tsx: stub
// global fetch, let the REAL services/api wrappers run.
const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
  const url = String(input);
  let body: unknown = {};
  if (url.includes('/api/scheduler/detect')) body = { scheduler: 'none', partitions: [] };
  else if (url.includes('/api/resource-metrics')) body = PARTIAL_RESOURCE_METRICS;
  else if (url.includes('/api/checkpoints')) body = [];
  else if (url.includes('/state')) body = { nodes: [] };
  return asResponse(body);
});

// AppProvider's useWebSocket constructs a real WebSocket; jsdom would try
// (and endlessly retry) a live connection.
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

function renderMonitor() {
  return render(
    <AppProvider>
      <MonitorPage />
    </AppProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('ari_lang', 'en');
  fetchMock.mockClear();
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});

afterAll(() => {
  globalThis.fetch = originalFetch;
});

describe('MonitorPage resource metrics (RR-D-1 partial-payload regression)', () => {
  it('renders the resource card from a partial payload without crashing', async () => {
    renderMonitor();

    // The card mounts once the (partial) metrics resolve.
    await waitFor(
      () => expect(screen.getByText('System Resources')).toBeInTheDocument(),
      { timeout: 10000 },
    );

    // Present field renders.
    const processBox = screen
      .getByText('User Processes')
      .closest('.stat-box') as HTMLElement;
    expect(processBox.querySelector('.stat-val')?.textContent).toBe('3');

    // Absent memory_rss_mb -> placeholder (the exact pre-fix crash site).
    const memoryBox = screen
      .getByText('Memory (RSS)')
      .closest('.stat-box') as HTMLElement;
    expect(memoryBox.querySelector('.stat-val')?.textContent).toBe('—');

    // Absent cpu_load_1m / cpu_count -> placeholders, tooltip defensive too.
    const cpuBox = screen
      .getByText('CPU Load')
      .closest('.stat-box') as HTMLElement;
    expect(cpuBox.querySelector('.stat-val')?.textContent).toBe('— / —');
    expect(cpuBox.querySelector('.stat-val')?.getAttribute('title')).toBe(
      '1m: — / 5m: — / 15m: — (— cores)',
    );

    // Absent experiment_pid -> no PID footer.
    expect(screen.queryByText(/Experiment PID/)).toBeNull();
  });
});
