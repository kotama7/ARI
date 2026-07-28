// ARI Dashboard – Governance Accountability tab (gui_refresh task 08 Wave
// 4a; plan 08 §Accountability).
//
// The adversarial chain of one selected node, with EXPLICIT raw-vs-validated
// separation (plan 08 §Truth rules: raw attack severity is NOT a validated
// penalty):
//   - "Raw attacks": `atk_*` claims. The DTO (`RqgmRawAttackV1`) carries no
//     score/penalty field at all, and this table renders a fixed "no
//     penalty (unadjudicated)" cell — a raw row can structurally never show
//     a penalty number.
//   - "Validated attacks": adjudicated `vat_*` records with their chain
//     references (raw atk_ id → judgment jdg_ id) and the impeachment-facing
//     fields when present (target_component_id / affected_components).
// Zero attacks is NEVER presented as "healthy": with an exploration-only
// adversary roster (no paper_* roles in the registry) the impeachment chain
// is structurally inert and an explicit capability note says so (plan 08
// truth rule: "zero attacks" must never be shown as "no issues").

import { useT } from '../../i18n';
import { useRqgmNodeLineageV1, useRqgmRegistryV1 } from '../../hooks/useV1';
import { Badge, Card, DegradedState, EmptyState, ErrorState, LoadingState } from '../common';
import { errorText } from './shared';
import type { RqgmNodeLineageV1 } from '../../services/api/v1';

/** The only roles whose impeachment chain fires in production (plan 08
 * §Accountability: paper_self_preference → paper_reviewer/paper_writer). */
function hasImpeachableRoles(roles: string[]): boolean {
  return roles.some((r) => r.startsWith('paper_'));
}

function RawAttacksCard({ lineage }: { lineage: RqgmNodeLineageV1 }) {
  const t = useT();
  const raws = lineage.raw_attacks ?? [];
  return (
    <Card title={t('gov_acc_raw_title')}>
      <p style={{ color: 'var(--text-muted)', fontSize: '.78rem', marginBottom: 8 }}>
        {t('gov_acc_raw_note')}
      </p>
      <div data-testid="raw-attacks" style={{ overflowX: 'auto' }}>
        {raws.length === 0 ? (
          <EmptyState icon="⚔️" message={t('gov_acc_empty')} hint={t('gov_acc_zero_note')} />
        ) : (
          <table>
            <thead>
              <tr>
                <th>{t('gov_acc_col_raw_id')}</th>
                <th>{t('gov_acc_col_adversary')}</th>
                <th>{t('gov_acc_col_claimed')}</th>
                <th>{t('gov_acc_col_status')}</th>
                <th>{t('gov_acc_col_epoch')}</th>
                <th>{t('gov_lin_penalty')}</th>
              </tr>
            </thead>
            <tbody>
              {raws.map((a) => (
                <tr key={a.record_id}>
                  <td>
                    <Badge variant="yellow">{t('gov_acc_raw_badge')}</Badge>{' '}
                    <code style={{ fontSize: '.78rem' }}>{a.record_id}</code>
                  </td>
                  <td>{a.adversary_type ?? t('gov_unknown')}</td>
                  <td>
                    {/* The attacker's CLAIM — a label, never a score. */}
                    {a.severity_claimed ?? t('gov_unknown')}
                  </td>
                  <td>{a.status ?? t('gov_unknown')}</td>
                  <td>
                    <code style={{ fontSize: '.75rem' }}>{a.epoch_id ?? '—'}</code>
                  </td>
                  <td>
                    {/* Structurally fixed: raw attacks never carry a
                        penalty (plan 08 §Truth rules). */}
                    <span style={{ color: 'var(--text-muted)' }}>
                      {t('gov_acc_no_penalty')}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Card>
  );
}

function ValidatedAttacksCard({ lineage }: { lineage: RqgmNodeLineageV1 }) {
  const t = useT();
  const validated = lineage.validated_attacks ?? [];
  return (
    <Card title={t('gov_acc_validated_title')}>
      <p style={{ color: 'var(--text-muted)', fontSize: '.78rem', marginBottom: 8 }}>
        {t('gov_acc_validated_note')}
      </p>
      <div data-testid="validated-attacks" style={{ overflowX: 'auto' }}>
        {validated.length === 0 ? (
          <EmptyState icon="⚖️" message={t('gov_acc_empty')} hint={t('gov_acc_zero_note')} />
        ) : (
          <table>
            <thead>
              <tr>
                <th>{t('gov_acc_col_vat_id')}</th>
                <th>{t('gov_acc_col_raw_id')}</th>
                <th>{t('gov_acc_col_judgment')}</th>
                <th>{t('gov_acc_col_verdict')}</th>
                <th>{t('gov_acc_col_severity')}</th>
                <th>{t('gov_acc_col_target')}</th>
                <th>{t('gov_acc_col_affected')}</th>
              </tr>
            </thead>
            <tbody>
              {validated.map((v) => (
                <tr key={v.record_id}>
                  <td>
                    <Badge variant="green">{t('gov_acc_validated_badge')}</Badge>{' '}
                    <code style={{ fontSize: '.78rem' }}>{v.record_id}</code>
                  </td>
                  <td>
                    <code style={{ fontSize: '.75rem' }}>
                      {v.raw_attack_id ?? '—'}
                    </code>
                  </td>
                  <td>
                    <code style={{ fontSize: '.75rem' }}>
                      {v.judgment_id ?? '—'}
                    </code>
                  </td>
                  <td>{v.verdict ?? t('gov_unknown')}</td>
                  <td>{v.severity ?? t('gov_unknown')}</td>
                  <td>
                    <code style={{ fontSize: '.75rem' }}>
                      {v.target_component_id ?? '—'}
                    </code>
                  </td>
                  <td>
                    <code style={{ fontSize: '.72rem' }}>
                      {(v.affected_components ?? []).join(', ') || '—'}
                    </code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Card>
  );
}

export function AccountabilityTab({
  runId,
  nodeId,
}: {
  runId: string;
  nodeId: string;
}) {
  const t = useT();
  const lineageQ = useRqgmNodeLineageV1(runId, nodeId);
  // Registry roles decide whether the impeachment chain can fire at all
  // (cached across tabs — same query key as the Registry tab).
  const registryQ = useRqgmRegistryV1(runId, true);

  if (nodeId === '') {
    return <EmptyState icon="🧭" message={t('gov_node_placeholder')} />;
  }
  if (lineageQ.isPending) return <LoadingState />;
  if (lineageQ.isError && lineageQ.data === undefined) {
    return (
      <ErrorState
        message={errorText(lineageQ.error, t('gov_request_id'))}
        onRetry={() => void lineageQ.refetch()}
      />
    );
  }
  const lineage = lineageQ.data;
  if (lineage === undefined) return <LoadingState />;

  const roles = (registryQ.data?.components ?? []).map((c) => c.role);
  const zeroAttacks =
    (lineage.raw_attacks ?? []).length === 0 &&
    (lineage.validated_attacks ?? []).length === 0;
  const chainInert =
    zeroAttacks && registryQ.data !== undefined && !hasImpeachableRoles(roles);
  const reasons = lineage.degraded_reasons ?? [];

  return (
    <div>
      {reasons.length > 0 && (
        <div style={{ marginBottom: 8 }}>
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
      {chainInert && (
        // A capability state, NOT a success/health claim (plan 08).
        <div className="stale-banner" role="note" style={{ marginBottom: 12 }}>
          <span className="stale-banner-msg">
            <strong>{t('gov_acc_inert_title')}</strong> — {t('gov_acc_inert_note')}
          </span>
        </div>
      )}
      <RawAttacksCard lineage={lineage} />
      <ValidatedAttacksCard lineage={lineage} />
    </div>
  );
}
