import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ConfigBrowserPage } from '../ConfigBrowserPage';
import {
  ApiErrorV1,
  fetchConfigSchemaV1,
  fetchRunResolvedConfigV1,
  type ConfigFieldV1,
  type ConfigSchemaV1,
  type RequestIdV1,
  type ResolvedConfigV1,
} from '../../../services/api/v1';

/**
 * ConfigBrowserPage (gui_refresh Wave 3b — read-only effective-config
 * browser; plans 05 §Purpose / §Resolved manifest, 06 §Effective
 * configuration).
 *
 * The typed v1 fetchers are mocked at the module boundary (the react-query
 * hooks and ApiErrorV1 normalization stay REAL), so these tests pin:
 *   - SCHEMA-ONLY mode (#/config, no run param): the full 144-field count
 *     renders (matching the real registry size), grouped by category, with
 *     defaults in the value column, NO resolved-config fetch, and the
 *     search box filtering by path/category;
 *   - RUN mode (#/config?run=<id>): provenance source badges, the
 *     low-confidence marker, resolver warnings verbatim, and the
 *     secret-reference redaction row ('secret (reference only)' — never a
 *     value);
 *   - a typed error envelope surfacing as ErrorState WITH request_id.
 */

vi.mock('../../../services/api/v1', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../services/api/v1')>();
  return {
    ...actual,
    fetchConfigSchemaV1: vi.fn(),
    fetchRunResolvedConfigV1: vi.fn(),
  };
});

const schemaMock = vi.mocked(fetchConfigSchemaV1);
const resolvedMock = vi.mocked(fetchRunResolvedConfigV1);

// ── payload builders (shapes from v1types.gen.ts) ───────────────────────

function makeField(overrides: Partial<ConfigFieldV1> & { path: string }): ConfigFieldV1 {
  return {
    applies_when: null,
    category: 'Governance',
    default: null,
    enum: null,
    env_override: null,
    level: 'basic',
    mutability: 'new_run_only',
    notes: null,
    required: false,
    scope: 'run',
    sensitivity: 'public',
    source: 'pydantic',
    value_type: 'str',
    ...overrides,
  };
}

/**
 * 144 fields — the size of the real registry (GET /api/v1/config/schema),
 * so the count line pins the number a user actually sees: 3 handcrafted
 * fields + 141 Governance filler leaves.
 */
function makeSchema(): ConfigSchemaV1 & RequestIdV1 {
  const fields: ConfigFieldV1[] = [
    makeField({
      path: 'llm.model',
      category: 'Models',
      default: 'default-model',
    }),
    makeField({
      path: 'llm.api_key',
      category: 'Models',
      sensitivity: 'secret_reference',
      mutability: 'draft',
    }),
    makeField({
      path: 'search.num_workers',
      category: 'Search (BFTS)',
      default: 3,
      value_type: 'int',
      applies_when: 'agent.search strategy is bfts',
    }),
  ];
  for (let i = 0; i < 141; i += 1) {
    fields.push(makeField({ path: `governance.filler_${i}` }));
  }
  return {
    schema_version: 1,
    request_id: 'req-schema',
    resolver_version: 'legacy-compatible-1',
    fields,
  };
}

function makeResolved(
  overrides: Partial<ResolvedConfigV1> = {},
): ResolvedConfigV1 & RequestIdV1 {
  return {
    schema_version: 1,
    request_id: 'req-resolved',
    run_id: 'run-x',
    resolver_version: 'legacy-compatible-1',
    digest: 'sha256:abc123',
    resolved_at: '2026-07-20T00:00:00+00:00',
    source_stack: ['defaults', 'workflow.yaml', 'env'],
    values: {
      'llm.model': 'workflow-model',
      'search.num_workers': 5,
    },
    provenance: {
      'llm.model': { source: 'workflow', confidence: 'high', mutable: false },
      'search.num_workers': { source: 'env', confidence: 'low', mutable: true },
    },
    secret_references: {
      'llm.api_key': { configured: true, provider: 'env' },
    },
    warnings: ['profile "laptop" ignored non-execution key: llm.model'],
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

function renderPage() {
  return render(
    <QueryClientProvider client={makeClient()}>
      <ConfigBrowserPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('ari_lang', 'en');
  window.location.hash = '';
  schemaMock.mockReset();
  resolvedMock.mockReset();
});

describe('ConfigBrowserPage (gui_refresh Wave 3b read-only config browser)', () => {
  it('schema-only mode: renders the 144-field count, defaults, and no resolved fetch', async () => {
    window.location.hash = '#/config';
    schemaMock.mockResolvedValue(makeSchema());
    renderPage();

    await waitFor(() =>
      expect(screen.getByText('144 / 144 fields')).toBeInTheDocument(),
    );
    // Schema-only notice, no run context.
    expect(
      screen.getByText(/No run selected — showing the configuration schema/),
    ).toBeInTheDocument();
    // Defaults render in the value column (metadata only — never effective).
    expect(screen.getByText('llm.model')).toBeInTheDocument();
    expect(screen.getByText('default-model')).toBeInTheDocument();
    // Category groups from registry metadata.
    expect(screen.getByText('Models')).toBeInTheDocument();
    expect(screen.getByText('Search (BFTS)')).toBeInTheDocument();
    expect(screen.getByText('Governance')).toBeInTheDocument();
    // applies_when note.
    expect(
      screen.getByText(/Applies when: agent\.search strategy is bfts/),
    ).toBeInTheDocument();
    // Mutability badges come from the registry.
    expect(screen.getAllByText('new_run_only').length).toBeGreaterThan(0);
    // No run param — the resolved-config endpoint is never called.
    expect(resolvedMock).not.toHaveBeenCalled();
  });

  it('schema-only mode: the search box filters by path and by category', async () => {
    window.location.hash = '#/config';
    schemaMock.mockResolvedValue(makeSchema());
    renderPage();

    await waitFor(() =>
      expect(screen.getByText('144 / 144 fields')).toBeInTheDocument(),
    );

    const input = screen.getByLabelText('Search fields');

    // Path filter: exactly one match.
    fireEvent.change(input, { target: { value: 'llm.model' } });
    expect(screen.getByText('1 / 144 fields')).toBeInTheDocument();
    expect(screen.getByText('llm.model')).toBeInTheDocument();
    expect(screen.queryByText('governance.filler_0')).toBeNull();
    expect(screen.queryByText('search.num_workers')).toBeNull();

    // Category filter (plan 06: fields stay discoverable via search).
    fireEvent.change(input, { target: { value: 'Search (BFTS)' } });
    expect(screen.getByText('1 / 144 fields')).toBeInTheDocument();
    expect(screen.getByText('search.num_workers')).toBeInTheDocument();
    expect(screen.queryByText('llm.model')).toBeNull();

    // No matches: empty state, nothing silently dropped.
    fireEvent.change(input, { target: { value: 'zz-no-such-field' } });
    expect(screen.getByText('0 / 144 fields')).toBeInTheDocument();
    expect(
      screen.getByText('No fields match the current search.'),
    ).toBeInTheDocument();
  });

  it('run mode: provenance badges, low-confidence marker, warnings, and secret redaction', async () => {
    window.location.hash = '#/config?run=run-x';
    schemaMock.mockResolvedValue(makeSchema());
    resolvedMock.mockResolvedValue(makeResolved());
    renderPage();

    await waitFor(() =>
      expect(screen.getByText('workflow-model')).toBeInTheDocument(),
    );
    expect(resolvedMock).toHaveBeenCalledWith('run-x');
    // Run context line.
    expect(screen.getByText('run-x')).toBeInTheDocument();
    expect(screen.getByText(/2026-07-20T00:00:00\+00:00/)).toBeInTheDocument();
    // Effective values override schema defaults.
    expect(screen.getByText('5')).toBeInTheDocument();
    expect(screen.queryByText('default-model')).toBeNull();
    // Provenance source badges (plan 05 §Resolved manifest).
    expect(screen.getByText('workflow')).toBeInTheDocument();
    expect(screen.getByText('env')).toBeInTheDocument();
    // Exactly one low-confidence marker (the env-sourced leaf).
    expect(screen.getAllByText('low confidence')).toHaveLength(1);
    // Resolver warnings verbatim.
    expect(screen.getByText('Resolver warnings', { exact: false })).toBeInTheDocument();
    expect(
      screen.getByText('profile "laptop" ignored non-execution key: llm.model'),
    ).toBeInTheDocument();
    // Secret reference: the marker text renders, a value NEVER does — the
    // row shows neither the configured flag nor any provider-shaped value.
    expect(screen.getByText('secret (reference only)')).toBeInTheDocument();
    expect(screen.getByText('llm.api_key')).toBeInTheDocument();
    expect(screen.queryByText(/sk-/)).toBeNull();
  });

  it('surfaces a typed error envelope as ErrorState including the request_id', async () => {
    window.location.hash = '#/config?run=run-broken';
    schemaMock.mockResolvedValue(makeSchema());
    resolvedMock.mockRejectedValue(
      new ApiErrorV1({
        code: 'not_found',
        message: 'no manifest for run',
        details: null,
        request_id: 'req-err-7',
        retryable: false,
      }),
    );
    renderPage();

    await waitFor(() =>
      expect(screen.getByText(/no manifest for run/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/req-err-7/)).toBeInTheDocument();
  });
});
