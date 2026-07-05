// Contract tests for services/api.ts (subtask 065 — add_dashboard_contract_and_schema_tests).
//
// Pins the wire contract that downstream refactor 063
// (refactor_dashboard_frontend_api_client_and_types) must preserve:
//   - API_BASE is same-origin ('') — wrappers hit bare paths, no host prefix.
//   - The two error regimes: get/post THROW on non-2xx; pbGet/pbPost SWALLOW and
//     return the {error} body verbatim (documented at api.ts:780-785).
//   - POST request-init shape: method / Content-Type / JSON.stringify(body ?? {}).
//   - The endpoint path each representative wrapper hits.
//
// Behavior is PINNED, not modified. Named *.test.tsx (not *.test.ts) so the
// existing vitest.config.ts `include` glob discovers it without a config change.

import { describe, it, expect, vi, afterEach } from 'vitest';
import {
  fetchState,
  fetchCheckpoints,
  fetchSettings,
  fetchWorkflow,
  fetchResourceMetrics,
  fetchCheckpointSummary,
  fetchNodeReport,
  saveSettings,
  stopExperiment,
  fetchPaperbenchPapers,
  runPaperbench,
} from '../api';

/** Stub global fetch with a single canned response and return the mock.
 * The parameters mirror `fetch`'s signature (unused here, hence `_`-prefixed) so
 * `fn.mock.calls[i]` is typed as `[input, init?]` and the URL/init are readable. */
function mockFetch(body: unknown, okFlag = true, status = 200) {
  const fn = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) =>
    Promise.resolve({ ok: okFlag, status, json: async () => body } as Response),
  );
  vi.stubGlobal('fetch', fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('api.ts – same-origin (API_BASE === "") + endpoint paths', () => {
  it('fetchState hits /state with no host prefix', async () => {
    const fn = mockFetch({});
    await fetchState();
    expect(fn).toHaveBeenCalledTimes(1);
    expect(fn.mock.calls[0][0]).toBe('/state');
  });

  it('representative wrappers hit their pinned endpoint paths', async () => {
    const cases: Array<[() => Promise<unknown>, string]> = [
      [() => fetchCheckpoints(), '/api/checkpoints'],
      [() => fetchSettings(), '/api/settings'],
      [() => fetchWorkflow(), '/api/workflow'],
      [() => fetchResourceMetrics(), '/api/resource-metrics'],
      [() => fetchCheckpointSummary('ck 1'), '/api/checkpoint/ck%201/summary'],
      [() => fetchNodeReport('r 1', 'n 1'), '/api/nodes/r%201/n%201/report'],
      [() => fetchPaperbenchPapers(), '/api/paperbench/papers'],
    ];
    for (const [call, path] of cases) {
      const fn = mockFetch({});
      await call();
      expect(fn.mock.calls[0][0]).toBe(path);
      vi.unstubAllGlobals();
    }
  });
});

describe('api.ts – two error regimes (documented contract, api.ts:780-785)', () => {
  it('get/post REJECT on non-2xx', async () => {
    mockFetch({ error: 'boom' }, false, 500);
    await expect(fetchState()).rejects.toThrow(/failed: 500/);
    await expect(saveSettings({ llm_model: 'x' })).rejects.toThrow(/failed: 500/);
  });

  it('pbGet/pbPost RESOLVE with the {error} body on non-2xx', async () => {
    mockFetch({ error: 'nope' }, false, 500);
    await expect(fetchPaperbenchPapers()).resolves.toEqual({ error: 'nope' });
    await expect(runPaperbench({})).resolves.toEqual({ error: 'nope' });
  });
});

describe('api.ts – POST request-init shape', () => {
  it('post() sends method / JSON content-type / stringified body', async () => {
    const fn = mockFetch({ ok: true });
    await saveSettings({ llm_model: 'x' });
    const init = fn.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe('POST');
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json');
    expect(init.body).toBe(JSON.stringify({ llm_model: 'x' }));
  });

  it('post() with no body defaults to JSON "{}" (body ?? {})', async () => {
    const fn = mockFetch({});
    await stopExperiment();
    const init = fn.mock.calls[0][1] as RequestInit;
    expect(init.body).toBe('{}');
  });

  it('adds no Authorization / CSRF header (same-origin unauth contract)', async () => {
    const fn = mockFetch({ ok: true });
    await saveSettings({ llm_model: 'x' });
    const init = fn.mock.calls[0][1] as RequestInit;
    const headers = (init.headers ?? {}) as Record<string, string>;
    expect(headers['Authorization']).toBeUndefined();
    expect(headers['X-CSRF-Token']).toBeUndefined();
  });
});
