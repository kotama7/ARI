// ARI Dashboard – Governance Score Lineage tab (gui_refresh task 08 Wave
// 4a; plan 08 §Score Lineage / §Direct answer).
//
// The TWO independent score channels of one node, never merged:
//   - Channel 1 (adversarial penalty, within an epoch): a waterfall table —
//     base score → validated penalty → final score — from UtilityRecord
//     observations (evidence = the adjudicated `vat_*` ids they cite) plus
//     the node's sentinel snapshot. Every score row names its policy hash
//     (a score is never shown without policy identity).
//   - Channel 2 (epoch-boundary utility-policy history, run-wide):
//     observations are FACETED by policy hash — one `.gov-facet` container
//     per hash, never a single continuous series across two hashes — with
//     invalidation/recompute markers from the erasure/rebuild events.
// Run-wide context below: the governed epoch utility policies (write-once
// bodies) and the committed score rewrites (T20 supersessions joined with
// their erasure/rebuild consequences).

import { useMemo } from 'react';
import { useT } from '../../i18n';
import {
  useRqgmNodeLineageV1,
  useRqgmPoliciesV1,
  useRqgmScoreRewritesV1,
} from '../../hooks/useV1';
import { Card, DegradedState, EmptyState, ErrorState, LoadingState } from '../common';
import { errorText, NodeStateBadge, PolicyHashLabel, RegistryStatusBadge, ScoreValue } from './shared';
import type { RqgmScoreObservationV1 } from '../../services/api/v1';

function PenaltyChannelCard({
  observations,
}: {
  observations: RqgmScoreObservationV1[];
}) {
  const t = useT();
  return (
    <Card title={t('gov_lin_channel1_title')}>
      <div data-testid="penalty-channel" style={{ overflowX: 'auto' }}>
        {observations.length === 0 ? (
          <EmptyState icon="🧮" message={t('gov_lin_penalty_empty')} />
        ) : (
          <table>
            <thead>
              <tr>
                <th>{t('gov_lin_under_policy')}</th>
                <th>{t('gov_acc_col_epoch')}</th>
                <th>{t('gov_lin_base')}</th>
                <th>{t('gov_lin_penalty')}</th>
                <th>{t('gov_lin_final')}</th>
                <th>{t('gov_lin_state')}</th>
                <th>{t('gov_lin_evidence')}</th>
              </tr>
            </thead>
            <tbody>
              {observations.map((obs, i) => {
                const v = obs.values ?? {};
                const base =
                  obs.source === 'node_metrics' ? v._pre_penalty_score : v.base_score;
                const penalty =
                  obs.source === 'node_metrics'
                    ? v._validated_attack_penalty
                    : v.penalty;
                const final =
                  obs.source === 'node_metrics' ? v._scientific_score : v.final_score;
                const vatIds = obs.validated_attack_ids ?? [];
                return (
                  <tr key={obs.record_id ?? `${obs.source}-${i}`}>
                    <td>
                      <PolicyHashLabel hash={obs.policy_hash} />
                    </td>
                    <td>
                      <code style={{ fontSize: '.75rem' }}>{obs.epoch_id ?? '—'}</code>
                    </td>
                    <td>
                      <ScoreValue value={base} />
                    </td>
                    <td>
                      {/* Only adjudicated evidence can put a number here —
                          the DTO's validated penalty, never a raw claim. */}
                      <span style={{ color: 'var(--score-penalty)' }}>
                        <ScoreValue value={penalty} />
                      </span>
                    </td>
                    <td>
                      <ScoreValue value={final} />
                    </td>
                    <td>
                      <NodeStateBadge state={obs.state} />
                    </td>
                    <td>
                      <code style={{ fontSize: '.72rem' }}>
                        {vatIds.join(', ') || (obs.source === 'node_metrics' ? obs.source : '—')}
                      </code>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </Card>
  );
}

function PolicyChannelCard({
  observations,
}: {
  observations: RqgmScoreObservationV1[];
}) {
  const t = useT();
  // Facet by policy hash (file order preserved inside each facet). A
  // hash-less observation facets under 'unknown' — never merged into a
  // hashed facet.
  const facets = useMemo(() => {
    const byHash = new Map<string, RqgmScoreObservationV1[]>();
    for (const obs of observations) {
      const key = obs.policy_hash ?? 'unknown';
      const list = byHash.get(key) ?? [];
      list.push(obs);
      byHash.set(key, list);
    }
    return [...byHash.entries()];
  }, [observations]);

  return (
    <Card title={t('gov_lin_channel2_title')}>
      <p style={{ color: 'var(--text-muted)', fontSize: '.78rem', marginBottom: 8 }}>
        {t('gov_lin_facet_note')}
      </p>
      {facets.length === 0 ? (
        <EmptyState icon="📜" message={t('gov_lin_policy_empty')} />
      ) : (
        facets.map(([hash, list]) => (
          <div key={hash} className="gov-facet" data-testid={`policy-facet-${hash}`}>
            <div className="gov-facet-title">
              {t('gov_lin_under_policy')}:{' '}
              <PolicyHashLabel hash={hash === 'unknown' ? null : hash} />
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table>
                <thead>
                  <tr>
                    <th>{t('gov_acc_col_epoch')}</th>
                    <th>{t('gov_lin_state')}</th>
                    <th>{t('gov_audit_col_summary')}</th>
                    <th>{t('gov_lin_evidence')}</th>
                  </tr>
                </thead>
                <tbody>
                  {list.map((obs, i) => (
                    <tr key={obs.record_id ?? `${obs.source}-${i}`}>
                      <td>
                        <code style={{ fontSize: '.75rem' }}>{obs.epoch_id ?? '—'}</code>
                      </td>
                      <td>
                        <NodeStateBadge state={obs.state} />
                      </td>
                      <td>
                        <code style={{ fontSize: '.72rem' }}>
                          {Object.entries(obs.values ?? {})
                            .map(([k, v]) => `${k}=${String(v)}`)
                            .join(' ')}
                        </code>
                      </td>
                      <td>
                        <code style={{ fontSize: '.72rem' }}>
                          {obs.record_id ?? obs.source}
                        </code>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ))
      )}
    </Card>
  );
}

function PoliciesCard({ runId }: { runId: string }) {
  const t = useT();
  const policiesQ = useRqgmPoliciesV1(runId, true);
  if (policiesQ.isPending) return <LoadingState inline />;
  if (policiesQ.isError && policiesQ.data === undefined) {
    return (
      <ErrorState
        message={errorText(policiesQ.error, t('gov_request_id'))}
        onRetry={() => void policiesQ.refetch()}
        inline
      />
    );
  }
  const policies = policiesQ.data?.policies ?? [];
  return (
    <Card title={t('gov_lin_policies_title')}>
      {policies.length === 0 ? (
        <EmptyState icon="📜" message={t('gov_lin_rewrites_empty')} />
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table>
            <thead>
              <tr>
                <th>{t('gov_col_hash')}</th>
                <th>{t('gov_col_status')}</th>
                <th>{t('gov_col_epochs_used')}</th>
                <th>{t('gov_col_adopted_via')}</th>
                <th>{t('gov_audit_col_summary')}</th>
              </tr>
            </thead>
            <tbody>
              {policies.map((p) => (
                <tr key={p.prompt_id}>
                  <td>
                    <PolicyHashLabel hash={p.policy_hash} />
                  </td>
                  <td>
                    <RegistryStatusBadge status={p.status} />
                  </td>
                  <td>
                    <code style={{ fontSize: '.72rem' }}>
                      {(p.epochs_used ?? []).join(', ') || '—'}
                    </code>
                  </td>
                  <td>
                    <code style={{ fontSize: '.72rem' }}>{p.adopted_via ?? '—'}</code>
                  </td>
                  <td>
                    {p.body === null ? (
                      <span style={{ color: 'var(--status-warning)' }}>
                        {t('gov_lin_policy_body_withheld')}
                      </span>
                    ) : (
                      <code style={{ fontSize: '.72rem' }}>
                        {Object.entries(p.body)
                          .map(([k, v]) => `${k}=${typeof v === 'object' ? '…' : String(v)}`)
                          .join(' ')}
                      </code>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function RewritesCard({ runId }: { runId: string }) {
  const t = useT();
  const rewritesQ = useRqgmScoreRewritesV1(runId, true);
  if (rewritesQ.isPending) return <LoadingState inline />;
  if (rewritesQ.isError && rewritesQ.data === undefined) {
    return (
      <ErrorState
        message={errorText(rewritesQ.error, t('gov_request_id'))}
        onRetry={() => void rewritesQ.refetch()}
        inline
      />
    );
  }
  const rewrites = rewritesQ.data?.entries ?? [];
  return (
    <Card title={t('gov_lin_rewrites_title')}>
      {rewrites.length === 0 ? (
        <EmptyState icon="♻️" message={t('gov_lin_rewrites_empty')} />
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table>
            <thead>
              <tr>
                <th>{t('gov_col_id')}</th>
                <th>{t('gov_acc_col_epoch')}</th>
                <th>{t('gov_col_from_policy')}</th>
                <th>{t('gov_col_to_policy')}</th>
                <th>{t('gov_col_invalidated')}</th>
                <th>{t('gov_col_recomputed')}</th>
                <th>{t('gov_col_frontier_removed')}</th>
                <th>{t('gov_col_frontier_reinstated')}</th>
                <th>{t('gov_col_source_events')}</th>
              </tr>
            </thead>
            <tbody>
              {rewrites.map((r) => (
                <tr key={r.rewrite_id}>
                  <td>
                    <code style={{ fontSize: '.75rem' }}>{r.rewrite_id}</code>
                  </td>
                  <td>
                    <code style={{ fontSize: '.75rem' }}>{r.epoch_id ?? '—'}</code>
                  </td>
                  <td>
                    <PolicyHashLabel hash={r.from_policy_hash} />
                  </td>
                  <td>
                    <PolicyHashLabel hash={r.to_policy_hash} />
                  </td>
                  <td>
                    <code style={{ fontSize: '.75rem' }}>
                      {(r.invalidated_node_ids ?? []).length}
                    </code>
                  </td>
                  <td>
                    <code style={{ fontSize: '.75rem' }}>
                      {(r.recompute_node_ids ?? []).length}
                    </code>
                  </td>
                  <td>
                    <code style={{ fontSize: '.75rem' }}>
                      {(r.frontier_removed_node_ids ?? []).length}
                    </code>
                  </td>
                  <td>
                    <code style={{ fontSize: '.75rem' }}>
                      {(r.frontier_reinstated_node_ids ?? []).length}
                    </code>
                  </td>
                  <td>
                    <code style={{ fontSize: '.72rem' }}>
                      {(r.source_event_ids ?? []).join(', ') || '—'}
                    </code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

export function ScoreLineageTab({
  runId,
  nodeId,
}: {
  runId: string;
  nodeId: string;
}) {
  const t = useT();
  const lineageQ = useRqgmNodeLineageV1(runId, nodeId);

  let nodeSection;
  if (nodeId === '') {
    nodeSection = <EmptyState icon="🧭" message={t('gov_node_placeholder')} />;
  } else if (lineageQ.isPending) {
    nodeSection = <LoadingState />;
  } else if (lineageQ.isError && lineageQ.data === undefined) {
    nodeSection = (
      <ErrorState
        message={errorText(lineageQ.error, t('gov_request_id'))}
        onRetry={() => void lineageQ.refetch()}
      />
    );
  } else if (lineageQ.data !== undefined) {
    const lineage = lineageQ.data;
    const reasons = lineage.degraded_reasons ?? [];
    nodeSection = (
      <>
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
        <PenaltyChannelCard observations={lineage.penalty_channel ?? []} />
        <PolicyChannelCard observations={lineage.policy_channel ?? []} />
      </>
    );
  } else {
    nodeSection = <LoadingState />;
  }

  return (
    <div>
      {nodeSection}
      <PoliciesCard runId={runId} />
      <RewritesCard runId={runId} />
    </div>
  );
}
