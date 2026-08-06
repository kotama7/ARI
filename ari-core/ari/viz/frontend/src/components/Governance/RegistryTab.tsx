// ARI Dashboard – Governance Registry tab (gui_refresh task 08 Wave 4a;
// plan 08 §Institution / Registry).
//
// Committed-replay registry tables (components + prompts) with the closed
// 10-status lifecycle vocabulary rendered via RegistryStatusBadge (one
// `--reg-*` token per status — node score-state colors are a different
// family and are never used here). The `verified` tri-state compares the
// `rqgm_registry.json` rollup's `as_of_event_hash` against the replay tail:
// the rollup verifies, it never becomes current state (plan 08 §Truth
// rules). Active-set membership (active + probationary_active) carries an
// explicit marker.

import { useT } from '../../i18n';
import { useRqgmRegistryV1 } from '../../hooks/useV1';
import { Badge, Card, DegradedState, EmptyState, ErrorState, LoadingState } from '../common';
import { errorText, RegistryStatusBadge } from './shared';
import type { RqgmRegistryV1 } from '../../services/api/v1';

const ACTIVE_SET = new Set(['active', 'probationary_active']);

function VerifiedBadge({ verified }: { verified: boolean | null }) {
  const t = useT();
  if (verified === true) return <Badge variant="green">{t('gov_reg_verified')}</Badge>;
  if (verified === false) return <Badge variant="red">{t('gov_reg_mismatch')}</Badge>;
  return <Badge variant="yellow">{t('gov_reg_no_snapshot')}</Badge>;
}

function ActiveMarker({ status }: { status: string }) {
  const t = useT();
  if (!ACTIVE_SET.has(status)) return <span style={{ opacity: 0.4 }}>—</span>;
  return <Badge variant="blue">{t('gov_reg_active_set')}</Badge>;
}

function ComponentsTable({ registry }: { registry: RqgmRegistryV1 }) {
  const t = useT();
  const components = registry.components ?? [];
  if (components.length === 0) {
    return <EmptyState icon="🏛️" message={t('gov_reg_empty')} />;
  }
  return (
    <div style={{ overflowX: 'auto' }}>
      <table>
        <thead>
          <tr>
            <th>{t('gov_col_id')}</th>
            <th>{t('gov_col_role')}</th>
            <th>{t('gov_col_tier')}</th>
            <th>{t('gov_col_status')}</th>
            <th>{t('gov_reg_active_set')}</th>
            <th>{t('gov_col_epoch_registered')}</th>
            <th>{t('gov_col_source_events')}</th>
          </tr>
        </thead>
        <tbody>
          {components.map((c) => (
            <tr key={c.component_id}>
              <td>
                <code style={{ fontSize: '.78rem' }}>{c.component_id}</code>
              </td>
              <td>{c.role}</td>
              <td>{c.tier}</td>
              <td>
                <RegistryStatusBadge status={c.status} />
              </td>
              <td>
                <ActiveMarker status={c.status} />
              </td>
              <td>
                <code style={{ fontSize: '.75rem' }}>{c.epoch_id_registered}</code>
              </td>
              <td>
                <code style={{ fontSize: '.72rem' }}>
                  {(c.source_event_ids ?? []).join(', ')}
                </code>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PromptsTable({ registry }: { registry: RqgmRegistryV1 }) {
  const t = useT();
  const prompts = registry.prompts ?? [];
  if (prompts.length === 0) {
    return <EmptyState icon="🏛️" message={t('gov_reg_empty')} />;
  }
  return (
    <div style={{ overflowX: 'auto' }}>
      <table>
        <thead>
          <tr>
            <th>{t('gov_col_id')}</th>
            <th>{t('gov_col_role')}</th>
            <th>{t('gov_col_hash')}</th>
            <th>{t('gov_col_status')}</th>
            <th>{t('gov_reg_active_set')}</th>
            <th>{t('gov_col_epoch_registered')}</th>
            <th>{t('gov_col_source_events')}</th>
          </tr>
        </thead>
        <tbody>
          {prompts.map((p) => (
            <tr key={p.prompt_id}>
              <td>
                <code style={{ fontSize: '.78rem' }}>{p.prompt_id}</code>
              </td>
              <td>{p.role}</td>
              <td>
                <code style={{ fontSize: '.75rem' }}>{p.prompt_hash}</code>
              </td>
              <td>
                <RegistryStatusBadge status={p.status} />
              </td>
              <td>
                <ActiveMarker status={p.status} />
              </td>
              <td>
                <code style={{ fontSize: '.75rem' }}>{p.epoch_id_registered}</code>
              </td>
              <td>
                <code style={{ fontSize: '.72rem' }}>
                  {(p.source_event_ids ?? []).join(', ')}
                </code>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function RegistryTab({ runId }: { runId: string }) {
  const t = useT();
  const registryQ = useRqgmRegistryV1(runId, true);

  if (registryQ.isPending) return <LoadingState />;
  if (registryQ.isError && registryQ.data === undefined) {
    return (
      <ErrorState
        message={errorText(registryQ.error, t('gov_request_id'))}
        onRetry={() => void registryQ.refetch()}
      />
    );
  }
  const registry = registryQ.data;
  if (registry === undefined) return <LoadingState />;
  const reasons = registry.degraded_reasons ?? [];

  return (
    <div>
      <p style={{ fontSize: '.82rem', display: 'flex', gap: 8, alignItems: 'center' }}>
        <VerifiedBadge verified={registry.verified} />
        <span style={{ color: 'var(--text-muted)' }}>{t('gov_reg_replay_note')}</span>
      </p>
      {reasons.length > 0 && (
        <div style={{ margin: '8px 0' }}>
          <DegradedState title={t('gov_degraded_title')} detail={t('gov_degraded_note')}>
            <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
              {reasons.map((r, i) => (
                <li key={i} style={{ fontSize: '.8rem' }}>
                  {r}
                </li>
              ))}
            </ul>
          </DegradedState>
        </div>
      )}
      <Card title={t('gov_reg_components_title')}>
        <ComponentsTable registry={registry} />
      </Card>
      <Card title={t('gov_reg_prompts_title')}>
        <PromptsTable registry={registry} />
      </Card>
    </div>
  );
}
