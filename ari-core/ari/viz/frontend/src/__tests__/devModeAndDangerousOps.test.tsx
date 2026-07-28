import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest';
import { render, screen, waitFor, cleanup, fireEvent } from '@testing-library/react';
import type { TreeNode } from '../types';
import { LoadingState, EmptyState, ErrorState } from '../components/common';

const originalFetch = globalThis.fetch;

/**
 * Tier-2 sibling-gated invariants (subtask 073 §7.4). The two developer-mode
 * gates below were `it.todo` until subtask 071 (add_dashboard_developer_mode)
 * landed; they are now real assertions over the shipped gating. The 072
 * error-state kit and the dangerous-ops audit (gui_refresh task 09 Wave 5a,
 * MN-6) have also landed, so only the ARIA-tabs invariant stays `it.todo`
 * (its sibling 068/069/070 has NOT landed — enabling it would assert
 * behavior that does not exist yet).
 *
 * jest-dom matchers are intentionally avoided (they are not typed for
 * `tsc --noEmit` in this project — see SettingsContract.test.tsx); we use
 * queryBy* + toBeNull()/not.toBeNull().
 *
 * The env-key readback lives inside the StepResources god-component, so its two
 * heavy sub-sections are stubbed to null and the api module (a namespace import
 * in StepResources, a named import in DetailPanel's data hook) is fully mocked
 * so the mount is deterministic and offline.
 */

// The api layer (`services/api.ts`) is a thin `export *` barrel over `./api/*`
// submodules sharing one `fetch`-based transport (`./api/client`). Rather than
// fight the barrel's `export *` in the mock resolver, we stub the global
// `fetch` so the REAL wrappers run offline — every GET resolves to a benign,
// URL-appropriate body. This keeps the env-key readback path real so the gate
// can be observed end-to-end.
const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
  const url = String(input);
  let body: unknown = {};
  if (url.includes('rubric')) body = [];
  else if (url.includes('image')) body = [];
  // RR-P0-2 / ADR-11 / MN-2: legacy env-keys is redacted server-side …
  else if (url.includes('env-keys')) body = { keys: {}, source: {}, redacted: true };
  // … and the readiness endpoint reports configured/not-configured only.
  else if (url.includes('secrets/status'))
    body = {
      schema_version: 1,
      secrets: [
        {
          name: 'OPENAI_API_KEY',
          configured: true,
          source_class: 'repo_env',
          last_updated: '2026-07-23T00:00:00Z',
        },
        {
          name: 'ANTHROPIC_API_KEY',
          configured: false,
          source_class: null,
          last_updated: null,
        },
      ],
    };
  else if (url.includes('scheduler') || url.includes('detect'))
    body = { scheduler: 'local', partitions: [] };
  else if (url.includes('container')) body = { runtime: 'none' };
  return {
    ok: true,
    status: 200,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
});

vi.mock('../components/Wizard/stepResourcesSections', () => ({
  OrsModelPicker: () => null,
  FewshotManager: () => null,
}));

import { DetailPanel } from '../components/Tree/DetailPanel';
import { StepResources, ORS_DEFAULTS } from '../components/Wizard/StepResources';
import {
  requestConfirmationChallenge,
  deleteCheckpoint,
  stopExperiment,
  gpuMonitorAction,
} from '../services/api';

const NODE = { id: 'n1', label: 'draft' } as unknown as TreeNode;

// StepResources takes ~44 props; a permissive factory keeps this test resilient
// to unrelated prop churn (llm is non-ollama so the ollama effect is skipped).
function stepResourcesProps(): any {
  const noop = () => {};
  return {
    mode: 'single', setMode: noop,
    llm: 'openai', setLlm: noop,
    model: 'gpt-4o', setModel: noop,
    customModel: '', setCustomModel: noop,
    apiKey: '', setApiKey: noop,
    baseUrl: '', setBaseUrl: noop,
    ollamaGpu: 'auto', setOllamaGpu: noop,
    partition: '', setPartition: noop,
    hpcCpus: '8', setHpcCpus: noop,
    hpcMem: '32', setHpcMem: noop,
    hpcWall: '04:00:00', setHpcWall: noop,
    hpcGpus: '0', setHpcGpus: noop,
    phaseModels: {}, setPhaseModels: noop,
    containerImage: '', setContainerImage: noop,
    containerMode: 'auto', setContainerMode: noop,
    vlmReviewModel: 'openai/gpt-4o', setVlmReviewModel: noop,
    rubricId: 'neurips', setRubricId: noop,
    fewshotMode: 'static', setFewshotMode: noop,
    numReviewsEnsemble: 1, setNumReviewsEnsemble: noop,
    numReflections: 1, setNumReflections: noop,
    ors: ORS_DEFAULTS, setOrs: noop,
    onBack: noop, onNext: noop,
  };
}

describe('developer-mode gating of raw/debug/secret surfaces (071)', () => {
  beforeEach(() => {
    cleanup();
    localStorage.clear();
    localStorage.setItem('ari_lang', 'en');
    fetchMock.mockClear();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
  });

  afterAll(() => {
    globalThis.fetch = originalFetch;
  });

  // Converted from it.todo: 071 developer-mode gate has landed.
  it('hides the { } Raw node-JSON tab (DetailPanel) when developer mode is OFF and shows it when ON', () => {
    // OFF (default — ari_dev_mode absent).
    const { unmount } = render(<DetailPanel node={NODE} onClose={() => {}} />);
    expect(screen.queryByRole('button', { name: /Raw/ })).toBeNull();
    unmount();

    // ON.
    localStorage.setItem('ari_dev_mode', '1');
    render(<DetailPanel node={NODE} onClose={() => {}} />);
    expect(screen.queryByRole('button', { name: /Raw/ })).not.toBeNull();
  });

  // Converted from it.todo: 071 gates the env-key Auto-read UI. Since
  // RR-P0-2 / ADR-11 / MN-2 (Wave 3a) the gated surface is a READINESS
  // check (/api/v1/secrets/status) — secret values are not readable at all.
  it('hides the env-key Auto-read readiness check and does not probe secrets on mount when developer mode is OFF', async () => {
    render(<StepResources {...stepResourcesProps()} />);
    // 'API Key' label renders in the non-ollama branch → mount gate.
    await waitFor(() => expect(screen.queryByText('API Key')).not.toBeNull());
    expect(screen.queryByRole('button', { name: /Auto-read/ })).toBeNull();
    // Nothing secret-related fired on Wizard mount (069 §6 row 6): neither
    // the legacy /api/env-keys nor /api/v1/secrets/status was fetched.
    const hitSecretSurface = fetchMock.mock.calls.some(
      (c) =>
        String(c[0]).includes('env-keys') ||
        String(c[0]).includes('secrets/status'),
    );
    expect(hitSecretSurface).toBe(false);
  });

  // RR-P0-2 / ADR-11 / MN-2: dev-mode Auto-read is now readiness-only — it
  // calls /api/v1/secrets/status, never the legacy value endpoint, and never
  // prefills the API-key field (values can no longer be read over HTTP).
  it('shows the env-key Auto-read button when developer mode is ON and displays readiness without prefilling values', async () => {
    localStorage.setItem('ari_dev_mode', '1');
    const setApiKey = vi.fn();
    render(<StepResources {...stepResourcesProps()} setApiKey={setApiKey} />);
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /Auto-read/ })).not.toBeNull(),
    );
    // Mount auto-check (dev mode) resolves against the readiness endpoint:
    // llm='openai' → OPENAI_API_KEY, mocked configured via repo_env.
    await waitFor(() =>
      expect(
        screen.queryByText(/OPENAI_API_KEY configured \(repo_env\)/),
      ).not.toBeNull(),
    );
    expect(
      fetchMock.mock.calls.some((c) =>
        String(c[0]).includes('secrets/status'),
      ),
    ).toBe(true);
    // The legacy value endpoint is never consulted …
    expect(
      fetchMock.mock.calls.some((c) => String(c[0]).includes('env-keys')),
    ).toBe(false);
    // … and no value is ever written into the field.
    expect(setApiKey).not.toHaveBeenCalled();
  });
});

/**
 * Still-pending Tier-2 invariants: their siblings have NOT landed, so they ship
 * as `it.todo` to keep the intent discoverable. Do NOT enable until the named
 * sibling lands.
 */
describe('dashboard UX invariants pending sibling refactors (Tier-2)', () => {
  // Converted from it.todo: the dangerous-ops backend audit landed (gui_refresh
  // task 09 Wave 5a, MN-6 / RR-P0-6 / RR-P0-9). Destructive calls are two-step:
  // POST /api/v1/challenges issues a single-use server challenge bound to
  // action+target (its echo is the UI impact preview), and the destructive
  // endpoint only fires with that challenge_id. The api.ts confirmed:true
  // hardcode is gone — 'confirmed' rides only when a caller explicitly
  // confirmed (GpuMonitor start), and gpu-monitor stop uses a challenge.
  it('sends destructive calls only via the server-issued challenge two-step (MN-6)', async () => {
    const calls: Array<{ url: string; body: any }> = [];
    const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ url, body });
      let resBody: unknown = { ok: true };
      if (url.includes('/api/v1/challenges')) {
        resBody = {
          schema_version: 1,
          challenge_id: 'chg-abc123def456',
          action: body.action,
          target: body.target,
          expires_at: '2026-01-01T00:00:00Z',
          ttl_seconds: 60,
        };
      }
      return {
        ok: true,
        status: 200,
        json: async () => resBody,
        text: async () => JSON.stringify(resBody),
      } as unknown as Response;
    });
    globalThis.fetch = fn as unknown as typeof fetch;
    try {
      // delete-checkpoint: challenge echoes the exact target (impact preview) …
      const ch = await requestConfirmationChallenge(
        'delete-checkpoint',
        '/ckpts/run1',
      );
      expect(ch.challenge_id).toBe('chg-abc123def456');
      expect(ch.target).toBe('/ckpts/run1');
      // … and the destructive call carries the challenge back.
      await deleteCheckpoint('run1', '/ckpts/run1', ch.challenge_id);

      // stop-all: same two-step against target '*'.
      const st = await requestConfirmationChallenge('stop-all', '*');
      await stopExperiment(st.challenge_id);

      // gpu-monitor: no hardcoded confirmed:true; stop rides a challenge.
      await gpuMonitorAction('start');
      await gpuMonitorAction('start', { confirmed: true });
      const gm = await requestConfirmationChallenge('gpu-monitor-stop', '*');
      await gpuMonitorAction('stop', { challengeId: gm.challenge_id });

      expect(calls.map((c) => c.url)).toEqual([
        '/api/v1/challenges',
        '/api/delete-checkpoint',
        '/api/v1/challenges',
        '/api/stop',
        '/api/gpu-monitor',
        '/api/gpu-monitor',
        '/api/v1/challenges',
        '/api/gpu-monitor',
      ]);
      expect(calls[1].body.challenge_id).toBe('chg-abc123def456');
      expect(calls[3].body).toEqual({ challenge_id: 'chg-abc123def456' });
      expect(calls[4].body.confirmed).toBeUndefined();
      expect(calls[5].body.confirmed).toBe(true);
      expect(calls[7].body.challenge_id).toBe('chg-abc123def456');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  // Un-skip when 068/069/070 add ARIA tab semantics to Settings/DetailPanel tabs.
  it.todo(
    'Settings/DetailPanel tabs expose role=tab / role=tabpanel / aria-selected [enable with 068/069/070]',
  );

  // Converted from it.todo: 072 landed the shared empty/loading/error state kit
  // (components/common/{LoadingState,EmptyState,ErrorState}). This asserts the
  // three surfaces render and that ErrorState's Retry is wired (it consumes a
  // plain string from EITHER api error regime — get/post throw or pbGet/pbPost
  // {error} — without unifying them). Explicit labels keep it locale-independent.
  it('renders loading/empty/error states via the shared common/ state kit (072)', () => {
    cleanup();
    const onRetry = vi.fn();
    const { container } = render(
      <div>
        <LoadingState label="__kit_loading__" />
        <EmptyState icon="📭" message="__kit_empty__" />
        <ErrorState message="__kit_error__" onRetry={onRetry} retryLabel="__kit_retry__" />
      </div>,
    );
    expect(container.querySelector('.spinner')).not.toBeNull();
    expect(screen.queryByText('__kit_loading__')).not.toBeNull();
    expect(screen.queryByText('__kit_empty__')).not.toBeNull();
    expect(screen.queryByText('__kit_error__')).not.toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '__kit_retry__' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
