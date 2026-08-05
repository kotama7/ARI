// Read-only, run-frozen Knowledge/Provider/Assurance projection.

import { get } from './client';

export type KcaRecord = Record<string, unknown>;

export interface KcaSnapshot {
  schema_version: 'ari.viz-kca/v1';
  run_id: string;
  present: boolean;
  modes: Record<string, string>;
  knowledge: {
    catalog_digest: string | null;
    catalog_entries: KcaRecord[];
    active_lock_digest: string | null;
    active_skills: KcaRecord[];
    node_use_records: KcaRecord[];
  };
  providers: {
    catalog_digest: string | null;
    catalog_entries: KcaRecord[];
    provider_lock_digest: string | null;
    locked_tools: KcaRecord[];
    binding_lock_digest: string | null;
    bindings: KcaRecord[];
    unsatisfied: KcaRecord[];
  };
  assurance: {
    verification_contract_digest: string | null;
    requirements: KcaRecord[];
    catalog_digest: string | null;
    catalog_entries: KcaRecord[];
    baseline_lock_digest: string | null;
    active_harnesses: KcaRecord[];
    unsatisfied_atom_digests: string[];
    attestations: KcaRecord[];
  };
  degraded_reasons: string[];
  error?: string;
}

export async function fetchKcaSnapshot(runId: string): Promise<KcaSnapshot> {
  return get<KcaSnapshot>(`/api/checkpoint/${encodeURIComponent(runId)}/kca`);
}
