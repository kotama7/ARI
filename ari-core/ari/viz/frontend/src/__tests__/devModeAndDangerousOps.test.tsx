import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest';
import { render, screen, waitFor, cleanup, fireEvent } from '@testing-library/react';
import type { TreeNode } from '../types';
import { LoadingState, EmptyState, ErrorState } from '../components/common';

const originalFetch = globalThis.fetch;

/**
 * Tier-2 sibling-gated invariants (subtask 073 §7.4). The two developer-mode
 * gates below were `it.todo` until subtask 071 (add_dashboard_developer_mode)
 * landed; they are now real assertions over the shipped gating. The remaining
 * three stay `it.todo` because their siblings (071 dangerous-ops backend audit /
 * 072 error-state kit / 073 ARIA) have NOT landed — enabling them would assert
 * behavior that does not exist yet.
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
  else if (url.includes('env-keys')) body = { keys: {} };
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

  // Converted from it.todo: 071 gates the /api/env-keys secret readback UI.
  it('hides the env-key Auto-read secret readback and does not auto-pull secrets on mount when developer mode is OFF', async () => {
    render(<StepResources {...stepResourcesProps()} />);
    // 'API Key' label renders in the non-ollama branch → mount gate.
    await waitFor(() => expect(screen.queryByText('API Key')).not.toBeNull());
    expect(screen.queryByRole('button', { name: /Auto-read/ })).toBeNull();
    // No secret readback fired on Wizard mount (069 §6 row 6): /api/env-keys
    // was never fetched.
    const hitEnvKeys = fetchMock.mock.calls.some((c) =>
      String(c[0]).includes('env-keys'),
    );
    expect(hitEnvKeys).toBe(false);
  });

  it('shows the env-key Auto-read button when developer mode is ON', async () => {
    localStorage.setItem('ari_dev_mode', '1');
    render(<StepResources {...stepResourcesProps()} />);
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /Auto-read/ })).not.toBeNull(),
    );
  });
});

/**
 * Still-pending Tier-2 invariants: their siblings have NOT landed, so they ship
 * as `it.todo` to keep the intent discoverable. Do NOT enable until the named
 * sibling lands.
 */
describe('dashboard UX invariants pending sibling refactors (Tier-2)', () => {
  // Un-skip when the dangerous-ops backend audit fixes the api.ts confirmed:true hardcode.
  it.todo(
    'sends confirmed:true only after an explicit user confirmation payload [enable with dangerous-ops audit]',
  );

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
