import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ScientificAssuranceTab } from '../ScientificAssuranceTab';
import { fetchKcaSnapshot, type KcaSnapshot } from '../../../services/api';

vi.mock('../../../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../services/api')>();
  return { ...actual, fetchKcaSnapshot: vi.fn() };
});

const fetchMock = vi.mocked(fetchKcaSnapshot);

const snapshot: KcaSnapshot = {
  schema_version: 'ari.viz-kca/v1',
  run_id: 'run-kca',
  present: true,
  modes: { knowledge: 'enforce', capability_binding: 'enforce', assurance: 'enforce' },
  knowledge: {
    catalog_digest: `sha256:${'1'.repeat(64)}`,
    catalog_entries: [{ manifest: { id: 'hpc.gemm', version: '1.0.0', composition: { slot: 'domain-method' } }, status: 'verified' }],
    active_lock_digest: `sha256:${'2'.repeat(64)}`,
    active_skills: [{}],
    node_use_records: [{}],
  },
  providers: {
    catalog_digest: `sha256:${'3'.repeat(64)}`,
    catalog_entries: [{ provider_id: 'ari.coding', package_version: '0.8.0', provider_status: 'verified', tool_refs: ['coding--run'] }],
    provider_lock_digest: `sha256:${'4'.repeat(64)}`,
    locked_tools: [{}],
    binding_lock_digest: `sha256:${'5'.repeat(64)}`,
    bindings: [{}],
    unsatisfied: [],
  },
  assurance: {
    verification_contract_digest: `sha256:${'6'.repeat(64)}`,
    requirements: [{}],
    catalog_digest: `sha256:${'7'.repeat(64)}`,
    catalog_entries: [{ id: 'hpc/gemm-correctness', version: '1.0.0', status: 'verified', kind: 'artifact_verifier' }],
    baseline_lock_digest: `sha256:${'8'.repeat(64)}`,
    active_harnesses: [{}],
    unsatisfied_atom_digests: [],
    attestations: [{}],
  },
  degraded_reasons: [],
};

describe('ScientificAssuranceTab', () => {
  it('renders three authority domains as distinct catalog tables', async () => {
    fetchMock.mockResolvedValue(snapshot);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ScientificAssuranceTab runId="run-kca" />
      </QueryClientProvider>,
    );

    expect(await screen.findByTestId('kca-separated-view')).toBeInTheDocument();
    expect(screen.getByTestId('knowledge-catalog')).toHaveTextContent('hpc.gemm');
    expect(screen.getByTestId('provider-catalog')).toHaveTextContent('ari.coding');
    expect(screen.getByTestId('harness-catalog')).toHaveTextContent('hpc/gemm-correctness');
    expect(screen.getByText(/MCP.*transport/)).toBeInTheDocument();
  });
});
