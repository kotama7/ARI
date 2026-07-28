// ARI Dashboard – Governance Epoch Timeline tab (gui_refresh task 08 Wave
// 4b; plan 08 §Epoch Timeline / §Truth and presentation rules).
//
// Committed epochs from the transitions replay as a vertical timeline.
// Each epoch renders as its OWN facet (the Score Lineage faceting pattern):
// there is deliberately NO cross-epoch score comparison UI — every epoch
// carries its own utility policy hash, and scores under different policy
// hashes are never joined into one series (plan 08: epoch comparison only
// after policy compatibility is confirmed; this v1 tab refuses it outright
// and says so). Absence stays absence:
//   - a still-open epoch has transition_counts=null and renders an explicit
//     "no committed boundary" note — never a row of zeros;
//   - `fallbacks` is null unless the real epoch_transition audit record
//     supplied the array — rendered as unknown, never 0.
// Selecting an epoch loads the committed detail: the write-once policy body
// (the 5 governed keys), the opening/closing boundary transactions with
// their raw-source offsets, and governance-report presence.

import { useState } from 'react';
import { useT } from '../../i18n';
import { useRqgmEpochDetailV1, useRqgmEpochsV1 } from '../../hooks/useV1';
import { Badge, Button, Card, DegradedState, EmptyState, ErrorState, LoadingState } from '../common';
import { errorText, PolicyHashLabel } from './shared';
import type {
  RqgmEpochTransitionCountsV1,
  RqgmEpochV1,
  RqgmTransactionRefV1,
} from '../../services/api/v1';

const TRANSITIONS_SOURCE_FILE = 'rqgm_transitions.jsonl';

/** The 5 governed keys of a sealed utility policy body (plan 08 §Score
 * Lineage: `{composite, axis_weights, frontier_score, depth_penalty_lambda,
 * ucb_c}`). Rendered in this canonical order. */
const POLICY_BODY_KEYS = [
  'composite',
  'axis_weights',
  'frontier_score',
  'depth_penalty_lambda',
  'ucb_c',
] as const;

// Structured rendering instead of a raw JSON dump (check_dashboard_ux
// json_dump rule): axis_weights is a flat axis->weight map, so render it as
// readable pairs. An EMPTY map is shown distinctly from an absent value
// (plan 08 truth rule: missing / empty are different states).
function bodyValueText(value: unknown, emptyLabel: string): string {
  if (value === undefined) return '—';
  if (typeof value === 'object' && value !== null) {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return emptyLabel;
    return entries.map(([k, v]) => `${k}=${String(v)}`).join(', ');
  }
  return String(value);
}

/** Boundary status-change counts — real events only. A null counts object
 * (open epoch) never reaches this component. */
function TransitionCountBadges({ counts }: { counts: RqgmEpochTransitionCountsV1 }) {
  const t = useT();
  return (
    <span style={{ display: 'inline-flex', gap: 6, flexWrap: 'wrap' }}>
      <Badge variant={counts.adoptions > 0 ? 'green' : 'muted'}>
        {t('gov_epoch_count_adoptions')}: {counts.adoptions}
      </Badge>
      <Badge variant={counts.sanctions > 0 ? 'yellow' : 'muted'}>
        {t('gov_epoch_count_sanctions')}: {counts.sanctions}
      </Badge>
      <Badge variant={counts.retirements > 0 ? 'blue' : 'muted'}>
        {t('gov_epoch_count_retirements')}: {counts.retirements}
      </Badge>
      <Badge variant={counts.bans > 0 ? 'red' : 'muted'}>
        {t('gov_epoch_count_bans')}: {counts.bans}
      </Badge>
      {counts.fallbacks === null ? (
        // No audit-record source for fallbacks — unknown, never 0.
        <Badge variant="muted">{t('gov_epoch_fallbacks_unknown')}</Badge>
      ) : (
        <Badge variant={counts.fallbacks > 0 ? 'yellow' : 'muted'}>
          {t('gov_epoch_count_fallbacks')}: {counts.fallbacks}
        </Badge>
      )}
    </span>
  );
}

function TransactionRow({
  label,
  tx,
}: {
  label: string;
  tx: RqgmTransactionRefV1 | null | undefined;
}) {
  const t = useT();
  return (
    <tr>
      <td>{label}</td>
      {tx == null ? (
        <td colSpan={3}>
          <span style={{ opacity: 0.55 }}>{t('gov_epoch_tx_absent')}</span>
        </td>
      ) : (
        <>
          <td>
            <code style={{ fontSize: '.75rem' }}>{tx.transition_id ?? tx.kind}</code>
          </td>
          <td>
            <code style={{ fontSize: '.72rem' }}>
              {tx.event_count} {t('gov_epoch_tx_events')}
              {tx.committed_at ? ` — ${tx.committed_at}` : ''}
            </code>
          </td>
          <td>
            {/* Raw-source drill-down handle (plan 08 §Truth rules). */}
            <code style={{ fontSize: '.72rem' }}>
              {TRANSITIONS_SOURCE_FILE}@{tx.byte_offset}
            </code>
          </td>
        </>
      )}
    </tr>
  );
}

function EpochDetailCard({ runId, epochId }: { runId: string; epochId: string }) {
  const t = useT();
  const detailQ = useRqgmEpochDetailV1(runId, epochId);
  if (detailQ.isPending) return <LoadingState inline />;
  if (detailQ.isError && detailQ.data === undefined) {
    return (
      <ErrorState
        message={errorText(detailQ.error, t('gov_request_id'))}
        onRetry={() => void detailQ.refetch()}
        inline
      />
    );
  }
  const detail = detailQ.data;
  if (detail === undefined) return <LoadingState inline />;
  const reasons = detail.degraded_reasons ?? [];
  const body = detail.policy_body;

  return (
    <div data-testid={`epoch-detail-${epochId}`}>
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

      <Card title={`${t('gov_epoch_detail_title')}: ${epochId}`}>
        <table>
          <tbody>
            <tr>
              <td>{t('gov_epoch_detail_seq')}</td>
              <td>
                <code style={{ fontSize: '.78rem' }}>
                  {detail.epoch_seq ?? t('gov_unknown')}
                </code>
              </td>
              <td>{t('gov_epoch_detail_status')}</td>
              <td>{detail.status ?? t('gov_unknown')}</td>
            </tr>
            <tr>
              <td>{t('gov_epoch_detail_nodes_at_open')}</td>
              <td>
                <code style={{ fontSize: '.78rem' }}>
                  {detail.node_count_at_open ?? t('gov_unknown')}
                </code>
              </td>
              <td>{t('gov_epoch_detail_previous')}</td>
              <td>
                <code style={{ fontSize: '.78rem' }}>
                  {detail.previous_epoch_id ?? '—'}
                </code>
              </td>
            </tr>
            <tr>
              <td>{t('gov_epoch_detail_registry_version')}</td>
              <td>
                <code style={{ fontSize: '.78rem' }}>
                  {detail.registry_version ?? t('gov_unknown')}
                </code>
              </td>
              <td>{t('gov_epoch_detail_fingerprint')}</td>
              <td>
                <code style={{ fontSize: '.78rem' }}>
                  {detail.epoch_fingerprint ?? t('gov_unknown')}
                </code>
              </td>
            </tr>
          </tbody>
        </table>
      </Card>

      <Card title={t('gov_epoch_policy_title')}>
        <p style={{ display: 'flex', gap: 12, flexWrap: 'wrap', fontSize: '.8rem' }}>
          <span>
            {t('gov_lin_under_policy')}:{' '}
            <PolicyHashLabel hash={detail.epoch.utility_policy_hash} />
          </span>
          <span>
            {t('gov_col_id')}:{' '}
            <code style={{ fontSize: '.75rem' }}>{detail.policy_prompt_id ?? '—'}</code>
          </span>
        </p>
        {body === null || body === undefined ? (
          // Unresolved body — refused, never guessed (plan 08 §Truth rules).
          <p style={{ color: 'var(--status-warning)', fontSize: '.8rem' }}>
            {t('gov_epoch_policy_missing')}
          </p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table data-testid="epoch-policy-body">
              <thead>
                <tr>
                  <th>{t('gov_epoch_policy_key')}</th>
                  <th>{t('gov_col_value')}</th>
                </tr>
              </thead>
              <tbody>
                {POLICY_BODY_KEYS.map((key) => (
                  <tr key={key}>
                    <td>
                      <code style={{ fontSize: '.78rem' }}>{key}</code>
                    </td>
                    <td>
                      <code style={{ fontSize: '.75rem' }}>
                        {bodyValueText(body[key], t('gov_value_empty'))}
                      </code>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title={t('gov_epoch_tx_title')}>
        <div style={{ overflowX: 'auto' }}>
          <table>
            <tbody>
              <TransactionRow
                label={t('gov_epoch_tx_opening')}
                tx={detail.opening_transaction}
              />
              <TransactionRow
                label={t('gov_epoch_tx_closing')}
                tx={detail.closing_transaction}
              />
            </tbody>
          </table>
        </div>
        <p style={{ fontSize: '.8rem', marginTop: 8 }}>
          {detail.governance_report_present ? (
            <>
              <Badge variant="green">{t('gov_epoch_report_present')}</Badge>{' '}
              <code style={{ fontSize: '.75rem' }}>
                {detail.governance_report_record_id ?? ''}
              </code>
            </>
          ) : (
            <Badge variant="muted">{t('gov_epoch_report_absent')}</Badge>
          )}
        </p>
      </Card>
    </div>
  );
}

function EpochRow({
  epoch,
  isCurrent,
  selected,
  onSelect,
}: {
  epoch: RqgmEpochV1;
  isCurrent: boolean;
  selected: boolean;
  onSelect: () => void;
}) {
  const t = useT();
  return (
    <li className="gov-facet" data-testid={`epoch-facet-${epoch.epoch_id}`}>
      <div
        className="gov-facet-title"
        style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}
      >
        <span>{epoch.epoch_id}</span>
        {isCurrent && <Badge variant="blue">{t('gov_epoch_current')}</Badge>}
        {/* Per-epoch policy identity: the reason cross-epoch comparison is
            refused without a compatibility check (plan 08). */}
        <span>
          {t('gov_lin_under_policy')}:{' '}
          <PolicyHashLabel hash={epoch.utility_policy_hash} />
        </span>
        {epoch.boundary_committed ? (
          <Badge variant="green">{t('gov_epoch_boundary_committed')}</Badge>
        ) : (
          <Badge variant="yellow">{t('gov_epoch_open')}</Badge>
        )}
        <Button variant="outline" size="sm" onClick={onSelect} aria-pressed={selected}>
          {t('gov_epoch_select')}
        </Button>
      </div>
      <div style={{ fontSize: '.8rem' }}>
        {epoch.transition_counts === null || epoch.transition_counts === undefined ? (
          // Boundary not committed — counts do not exist yet, and an absent
          // source is never rendered as zero activity (plan 08 §Truth rules).
          <span style={{ color: 'var(--text-muted)' }}>
            {t('gov_epoch_counts_absent')}
          </span>
        ) : (
          <TransitionCountBadges counts={epoch.transition_counts} />
        )}
      </div>
      <p style={{ color: 'var(--text-muted)', fontSize: '.72rem', margin: '6px 0 0' }}>
        {t('gov_epoch_opened_by')}:{' '}
        <code style={{ fontSize: '.72rem' }}>
          {epoch.opened_by_transition_id ?? t('gov_unknown')}
        </code>
        {' — '}
        {t('gov_epoch_closed_by')}:{' '}
        <code style={{ fontSize: '.72rem' }}>{epoch.closed_by_transition_id ?? '—'}</code>
      </p>
    </li>
  );
}

export function EpochTimelineTab({ runId }: { runId: string }) {
  const t = useT();
  const epochsQ = useRqgmEpochsV1(runId, true);
  const [selectedEpoch, setSelectedEpoch] = useState('');

  if (epochsQ.isPending) return <LoadingState />;
  if (epochsQ.isError && epochsQ.data === undefined) {
    return (
      <ErrorState
        message={errorText(epochsQ.error, t('gov_request_id'))}
        onRetry={() => void epochsQ.refetch()}
      />
    );
  }
  const data = epochsQ.data;
  if (data === undefined) return <LoadingState />;
  const epochs = data.epochs ?? [];
  const reasons = data.degraded_reasons ?? [];

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

      <Card title={t('gov_epoch_title')}>
        {/* Explicit refusal of naive cross-epoch score comparison — the
            plan-08 truth rule, stated instead of a comparison widget. */}
        <p style={{ color: 'var(--text-muted)', fontSize: '.78rem', marginBottom: 8 }}>
          {t('gov_epoch_compare_note')}
        </p>
        {epochs.length === 0 ? (
          <EmptyState icon="🕰️" message={t('gov_epoch_empty')} />
        ) : (
          <ol style={{ listStyle: 'none', margin: 0, padding: 0 }}>
            {epochs.map((epoch) => (
              <EpochRow
                key={epoch.epoch_id}
                epoch={epoch}
                isCurrent={data.current_epoch === epoch.epoch_id}
                selected={selectedEpoch === epoch.epoch_id}
                onSelect={() => setSelectedEpoch(epoch.epoch_id)}
              />
            ))}
          </ol>
        )}
      </Card>

      {selectedEpoch !== '' && <EpochDetailCard runId={runId} epochId={selectedEpoch} />}
    </div>
  );
}
