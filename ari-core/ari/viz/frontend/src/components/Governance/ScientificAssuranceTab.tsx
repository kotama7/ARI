/** Separate, read-only views of Knowledge, executable Providers, and Harnesses. */

import { useQuery } from '@tanstack/react-query';
import { useT } from '../../i18n';
import { fetchKcaSnapshot, type KcaRecord } from '../../services/api';
import { Badge, Card, DegradedState, EmptyState, ErrorState, LoadingState } from '../common';

function object(value: unknown): KcaRecord {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as KcaRecord)
    : {};
}

function scalar(value: unknown): string {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : '—';
}

function digest(value: string | null | undefined): string {
  return value ? value.slice(0, 19) : '—';
}

function CatalogTable({ kind, rows }: { kind: 'knowledge' | 'provider' | 'harness'; rows: KcaRecord[] }) {
  const t = useT();
  if (rows.length === 0) return <EmptyState message={t('gov_kca_empty')} />;
  return (
    <div style={{ overflowX: 'auto' }}>
      <table data-testid={`${kind}-catalog`}>
        <thead>
          <tr>
            <th>{t('gov_col_id')}</th>
            <th>{t('gov_kca_version')}</th>
            <th>{t('gov_col_status')}</th>
            <th>{t('gov_kca_scope')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const manifest = object(row.manifest);
            const item = kind === 'knowledge' ? manifest : row;
            const id = kind === 'provider' ? item.provider_id : item.id;
            const version = kind === 'provider' ? item.package_version : item.version;
            const status = kind === 'knowledge' ? row.status : (item.provider_status ?? item.status);
            const scope = kind === 'provider'
              ? `${Array.isArray(item.tool_refs) ? item.tool_refs.length : 0} tools`
              : kind === 'harness'
                ? scalar(item.kind)
                : scalar(object(item.composition).slot);
            return (
              <tr key={`${scalar(id)}-${scalar(version)}-${index}`}>
                <td><code>{scalar(id)}</code></td>
                <td>{scalar(version)}</td>
                <td><Badge variant={status === 'verified' ? 'green' : 'muted'}>{scalar(status)}</Badge></td>
                <td>{scope}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function IdentityLine({ label, value }: { label: string; value: string | null }) {
  return (
    <p style={{ fontSize: '.78rem', color: 'var(--text-muted)', overflowWrap: 'anywhere' }}>
      {label}: <code title={value ?? ''}>{digest(value)}</code>
    </p>
  );
}

export function ScientificAssuranceTab({ runId }: { runId: string }) {
  const t = useT();
  const query = useQuery({
    queryKey: ['kca-view', runId],
    queryFn: () => fetchKcaSnapshot(runId),
    enabled: runId !== '',
  });
  if (query.isPending) return <LoadingState />;
  if (query.isError) {
    return <ErrorState message={String(query.error)} onRetry={() => void query.refetch()} />;
  }
  const data = query.data;
  if (!data.present) {
    return <EmptyState message={t('gov_kca_not_enabled')} hint={data.error} />;
  }
  return (
    <div data-testid="kca-separated-view">
      {data.degraded_reasons.length > 0 && (
        <DegradedState title={t('gov_degraded_title')} detail={data.degraded_reasons.join('; ')} />
      )}

      <Card title={t('gov_kca_knowledge_title')}>
        <p>{t('gov_kca_knowledge_note')}</p>
        <IdentityLine label={t('gov_kca_catalog_digest')} value={data.knowledge.catalog_digest} />
        <IdentityLine label={t('gov_kca_active_lock')} value={data.knowledge.active_lock_digest} />
        <p>{data.knowledge.active_skills.length} {t('gov_kca_active_items')} · {data.knowledge.node_use_records.length} {t('gov_kca_use_records')}</p>
        <CatalogTable kind="knowledge" rows={data.knowledge.catalog_entries} />
      </Card>

      <Card title={t('gov_kca_provider_title')}>
        <p>{t('gov_kca_provider_note')}</p>
        <IdentityLine label={t('gov_kca_provider_lock')} value={data.providers.provider_lock_digest} />
        <IdentityLine label={t('gov_kca_binding_lock')} value={data.providers.binding_lock_digest} />
        <p>{data.providers.bindings.length} {t('gov_kca_bindings')} · {data.providers.unsatisfied.length} {t('gov_kca_unsatisfied')}</p>
        <CatalogTable kind="provider" rows={data.providers.catalog_entries} />
      </Card>

      <Card title={t('gov_kca_assurance_title')}>
        <p>{t('gov_kca_assurance_note')}</p>
        <IdentityLine label={t('gov_kca_verification_contract')} value={data.assurance.verification_contract_digest} />
        <IdentityLine label={t('gov_kca_harness_lock')} value={data.assurance.baseline_lock_digest} />
        <p>{data.assurance.requirements.length} {t('gov_kca_requirements')} · {data.assurance.attestations.length} {t('gov_kca_attestations')}</p>
        <CatalogTable kind="harness" rows={data.assurance.catalog_entries} />
      </Card>
    </div>
  );
}
