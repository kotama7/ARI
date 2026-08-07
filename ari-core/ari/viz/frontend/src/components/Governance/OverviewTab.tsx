// ARI Dashboard – Governance Overview tab (gui_refresh task 08 Wave 4a;
// plan 08 §Workspace tabs / Overview).
//
// Bounded committed-replay summary: current epoch, epoch utility policy
// hash, constitution hash, by-status registry counts, and the tri-state
// integrity flags (true = verified, false = broken, null = source missing —
// a missing source is never shown as clean). A broken chain renders the
// shared DegradedState with the backend's degraded_reasons; the wording
// keeps governance degradation distinct from research failure (plan 08
// §Truth rules: governance blocked ≠ research failed).

import { useT } from '../../i18n';
import { useRqgmOverviewV1 } from '../../hooks/useV1';
import { Badge, Card, DegradedState, ErrorState, LoadingState, StatBox } from '../common';
import { errorText, PolicyHashLabel, RegistryStatusBadge } from './shared';

function IntegrityBadge({ value }: { value: boolean | null }) {
  const t = useT();
  if (value === true) return <Badge variant="green">{t('gov_integrity_verified')}</Badge>;
  if (value === false) return <Badge variant="red">{t('gov_integrity_broken')}</Badge>;
  return <Badge variant="yellow">{t('gov_integrity_missing')}</Badge>;
}

function StatusCounts({ counts }: { counts: Record<string, number> }) {
  const entries = Object.entries(counts);
  if (entries.length === 0) return <span style={{ opacity: 0.4 }}>—</span>;
  return (
    <span style={{ display: 'inline-flex', gap: 6, flexWrap: 'wrap' }}>
      {entries.map(([status, count]) => (
        <span key={status} style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
          <RegistryStatusBadge status={status} />
          <code style={{ fontSize: '.75rem' }}>{count}</code>
        </span>
      ))}
    </span>
  );
}

export function OverviewTab({ runId }: { runId: string }) {
  const t = useT();
  const overviewQ = useRqgmOverviewV1(runId, true);

  if (overviewQ.isPending) return <LoadingState />;
  if (overviewQ.isError && overviewQ.data === undefined) {
    return (
      <ErrorState
        message={errorText(overviewQ.error, t('gov_request_id'))}
        onRetry={() => void overviewQ.refetch()}
      />
    );
  }
  const overview = overviewQ.data;
  if (overview === undefined) return <LoadingState />;

  const integrity = overview.integrity;
  const broken =
    integrity.transitions_chain_ok === false ||
    integrity.registry_verified === false ||
    integrity.audit_chain_ok === false;
  const reasons = overview.degraded_reasons ?? [];

  return (
    <div>
      {(broken || reasons.length > 0) && (
        <div style={{ marginBottom: 12 }}>
          <DegradedState title={t('gov_degraded_title')} detail={t('gov_degraded_note')}>
            {reasons.length > 0 && (
              <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
                {reasons.map((r, i) => (
                  <li key={i} style={{ fontSize: '.8rem' }}>
                    {r}
                  </li>
                ))}
              </ul>
            )}
          </DegradedState>
        </div>
      )}

      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
        <StatBox
          label={t('gov_overview_current_epoch')}
          value={overview.current_epoch ?? t('gov_unknown')}
        />
        <StatBox
          label={t('gov_overview_policy')}
          value={overview.utility_policy_hash ?? t('gov_unknown')}
        />
        <StatBox
          label={t('gov_overview_constitution')}
          value={overview.constitution_hash ?? t('gov_unknown')}
        />
      </div>

      <Card title={t('gov_overview_integrity_title')}>
        <table>
          <tbody>
            <tr>
              <td>{t('gov_integrity_transitions')}</td>
              <td>
                <IntegrityBadge value={integrity.transitions_chain_ok} />
              </td>
            </tr>
            <tr>
              <td>{t('gov_integrity_registry')}</td>
              <td>
                <IntegrityBadge value={integrity.registry_verified} />
              </td>
            </tr>
            <tr>
              <td>{t('gov_integrity_audit')}</td>
              <td>
                <IntegrityBadge value={integrity.audit_chain_ok} />
              </td>
            </tr>
          </tbody>
        </table>
      </Card>

      <Card title={t('gov_overview_registry_title')}>
        <table>
          <tbody>
            <tr>
              <td>
                {t('gov_overview_components')} (
                {overview.registry_summary.component_count})
              </td>
              <td>
                <StatusCounts counts={overview.registry_summary.components_by_status ?? {}} />
              </td>
            </tr>
            <tr>
              <td>
                {t('gov_overview_prompts')} ({overview.registry_summary.prompt_count})
              </td>
              <td>
                <StatusCounts counts={overview.registry_summary.prompts_by_status ?? {}} />
              </td>
            </tr>
          </tbody>
        </table>
        <p style={{ color: 'var(--text-muted)', fontSize: '.78rem', marginTop: 8 }}>
          {t('gov_overview_last_commit')}:{' '}
          {overview.last_committed_transition_at ?? t('gov_unknown')}
          {' — '}
          {t('gov_overview_policy')}: <PolicyHashLabel hash={overview.utility_policy_hash} />
        </p>
      </Card>
    </div>
  );
}
