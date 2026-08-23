import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, act, within } from '@testing-library/react';
import WorkflowPage from '../WorkflowPage';

/**
 * Revision-aware workflow saving (gui_refresh Wave 4d).
 *
 * The rule: a workflow save states which version it edits, so a save that was
 * composed against stale bytes is REFUSED rather than applied on top of
 * someone else's write. That retires the old autosave, whose 2s timer pushed
 * the editor's buffer over whatever happened to be on disk. `revision` here is
 * a digest of the bytes the GET served and `base_revision` echoes it back on
 * the write (docs/reference/rest_api.md, "Behaviour changes on the legacy
 * surface (MN notes)", MN-3) — a different mechanism from the `gui_store/`
 * documents' integer revision + `If-Match`, but the same refusal semantics.
 * What the tests pin:
 *
 * - every save POSTs the `base_revision` loaded from GET /api/workflow and
 *   adopts the `revision` returned by a successful write (chained saves);
 * - the debounce cadence is unchanged (2s after the last edit);
 * - a 409 puts the page into 'conflict': a banner appears, saving pauses
 *   (no blind retry), and the explicit Reload action refetches — nothing
 *   is merged or reapplied silently.
 *
 * Real API wrappers run against a stubbed global fetch (same strategy as
 * routeRenderBaseline.test.tsx). Only setTimeout/clearTimeout are faked so
 * reactflow's rendering internals keep their real timers.
 */

// One phase node whose skill has one MCP tool; clicking the tool button in
// the node detail card is the deterministic edit used to trigger autosave.
const FLOW = {
  nodes: [
    {
      id: 'stage_a',
      type: 'phase',
      position: { x: 0, y: 0 },
      data: {
        label: 'Stage A',
        skill: 'idea-skill',
        enabled: true,
        tool: '',
        phase: 'bfts',
        description: '',
      },
    },
  ],
  edges: [],
};

const SKILL_MCP = {
  'idea-skill': {
    name: 'idea-skill',
    description: '',
    tools: ['tool_x'],
    version: '',
    dir: 'ari-skill-idea',
  },
};

const CONFLICT_ERROR =
  'workflow changed on disk since you loaded it (revision mismatch); reload before saving';

const asResponse = (body: unknown, status = 200): Response =>
  ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  }) as unknown as Response;

// Mutable per-test wiring for the stubbed transport.
let servedRevision: string;
let postCalls: Array<{ url: string; body: any }>;
let postResponse: () => { status: number; body: unknown };

const fetchStub = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(input);
  if (init?.method === 'POST') {
    postCalls.push({ url, body: JSON.parse(String(init.body)) });
    const r = postResponse();
    return asResponse(r.body, r.status);
  }
  if (url.includes('/api/workflow/flow')) {
    return asResponse({ ok: true, flow: FLOW, path: '/ckpt/workflow.yaml' });
  }
  if (url.includes('/api/workflow')) {
    return asResponse({
      ok: true,
      skill_mcp: SKILL_MCP,
      disabled_tools: [],
      revision: servedRevision,
    });
  }
  return asResponse({});
});

// reactflow needs ResizeObserver, which jsdom lacks.
class FakeResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal('ResizeObserver', FakeResizeObserver);

/** Flush pending microtasks (promise chains) inside act. */
const flush = async () => {
  await act(async () => {});
  await act(async () => {});
};

const renderLoaded = async () => {
  render(<WorkflowPage />);
  await flush();
  // The node detail card is plain JSX (independent of the reactflow canvas).
  expect(screen.getByText('stage_a')).toBeInTheDocument();
};

/** Expand the node card and toggle its MCP tool — a debounced-autosave edit.
 * getByRole (not findByRole): the expand re-render is synchronous, and the
 * async find* helpers poll via the faked setTimeout and would hang. */
const editNodeTool = async () => {
  // Expanding toggles, so only click the header when the card is collapsed.
  if (!screen.queryByRole('button', { name: /tool_x/ })) {
    fireEvent.click(screen.getByText('stage_a'));
    await flush();
  }
  fireEvent.click(screen.getByRole('button', { name: /tool_x/ }));
};

beforeEach(() => {
  localStorage.setItem('ari_lang', 'en');
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  servedRevision = 'rev1rev1rev1';
  postCalls = [];
  postResponse = () => ({ status: 200, body: { ok: true, revision: 'rev2rev2rev2' } });
  fetchStub.mockClear();
  globalThis.fetch = fetchStub as unknown as typeof fetch;
});

afterEach(() => {
  vi.useRealTimers();
});

describe('WorkflowPage revision-aware saving (Wave 4d)', () => {
  it('debounced autosave (2s) sends base_revision and adopts the returned revision', async () => {
    await renderLoaded();
    await editNodeTool();

    // Edit marks the page dirty; the save is debounced, not immediate.
    expect(screen.getByText('Unsaved changes')).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(1999);
    });
    expect(postCalls.length).toBe(0);

    // …and fires at the unchanged 2s cadence WITH the loaded revision.
    act(() => {
      vi.advanceTimersByTime(1);
    });
    await flush();
    expect(postCalls.length).toBe(1);
    expect(postCalls[0].url).toContain('/api/workflow/flow');
    expect(postCalls[0].body.base_revision).toBe('rev1rev1rev1');
    expect(postCalls[0].body.flow.nodes[0].data.tool).toBe('tool_x');
    expect(screen.getByText(/Saved/)).toBeInTheDocument();

    // A second edit chains on the revision returned by the first write.
    await editNodeTool();
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    await flush();
    expect(postCalls.length).toBe(2);
    expect(postCalls[1].body.base_revision).toBe('rev2rev2rev2');
  });

  it('manual Save posts immediately with base_revision', async () => {
    await renderLoaded();
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await flush();
    expect(postCalls.length).toBe(1);
    expect(postCalls[0].url).toContain('/api/workflow/flow');
    expect(postCalls[0].body.base_revision).toBe('rev1rev1rev1');
  });

  it('409 shows the conflict banner, pauses saving, and Reload refetches', async () => {
    await renderLoaded();
    postResponse = () => ({
      status: 409,
      body: { ok: false, error: CONFLICT_ERROR },
    });

    await editNodeTool();
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    await flush();
    expect(postCalls.length).toBe(1);

    // Conflict state: banner + chip, and NO blind retry of the save.
    const banner = screen.getByRole('alert');
    expect(within(banner).getByText('Workflow changed on disk')).toBeInTheDocument();
    expect(screen.getByText(/Conflict/)).toBeInTheDocument();

    // Further edits stay local while in conflict — nothing is posted.
    await editNodeTool();
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    await flush();
    expect(postCalls.length).toBe(1);
    // The manual Save path is paused too.
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await flush();
    expect(postCalls.length).toBe(1);

    // Reload refetches the latest state; nothing is reapplied silently.
    servedRevision = 'rev3rev3rev3';
    postResponse = () => ({ status: 200, body: { ok: true, revision: 'rev4rev4rev4' } });
    fireEvent.click(within(banner).getByRole('button', { name: 'Reload' }));
    await flush();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    // Post-reload saves carry the freshly served revision.
    await editNodeTool();
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    await flush();
    expect(postCalls.length).toBe(2);
    expect(postCalls[1].body.base_revision).toBe('rev3rev3rev3');
  });
});
