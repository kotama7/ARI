// ARI Dashboard – Governance Evolution tab (gui_refresh task 08 Wave 4b;
// plan 08 §Evolution and Frontier Repair).
//
// Evolution lineage grouped by kind (prompt / utility_policy / meta) with
// the plan-08 separation kept visual and structural:
//   - every row IS a raw candidate record (its own candidate-vocabulary
//     status), labeled "candidate (not adopted)" unless the committed
//     registry replay says otherwise;
//   - validation runs are counted separately (evidence of validation, not
//     adoption);
//   - `adopted` comes ONLY from joining the proposed hash against the
//     committed registry replay — an adopted row cites its transition
//     (`adopted_via`) and gets the success badge;
//   - meta outputs have adopted=null and render as inert provenance (an
//     unadoptable observation), never as a failed candidate.
// Presence flags are explicit: a missing log renders as "not present" —
// never as an empty-but-healthy table (plan 08 §Truth rules).

import { useMemo } from 'react';
import { useT } from '../../i18n';
import { useRqgmEvolutionV1 } from '../../hooks/useV1';
import { Badge, Card, DegradedState, EmptyState, ErrorState, LoadingState } from '../common';
import { errorText, PolicyHashLabel } from './shared';
import type { RqgmEvolutionEntryV1 } from '../../services/api/v1';

const KIND_ORDER = ['prompt', 'utility_policy', 'meta'] as const;
type EvolutionKind = (typeof KIND_ORDER)[number];

const KIND_TITLE_KEYS: Record<EvolutionKind, string> = {
  prompt: 'gov_evo_group_prompt',
  utility_policy: 'gov_evo_group_utility_policy',
  meta: 'gov_evo_group_meta',
};

const SOURCE_FILES: Record<RqgmEvolutionEntryV1['source'], string> = {
  prompt_evolution: 'prompt_evolution.jsonl',
  meta_outputs: 'rqgm_meta_outputs.jsonl',
};

/** Adoption cell — the three structurally separate outcomes. */
function AdoptionCell({ entry }: { entry: RqgmEvolutionEntryV1 }) {
  const t = useT();
  if (entry.adopted === true) {
    return (
      <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <Badge variant="green">{t('gov_evo_adopted')}</Badge>
        <code style={{ fontSize: '.72rem' }}>
          {t('gov_col_adopted_via')}: {entry.adopted_via ?? t('gov_unknown')}
          {entry.adopted_prompt_id ? ` (${entry.adopted_prompt_id})` : ''}
        </code>
      </span>
    );
  }
  if (entry.adopted === false) {
    // Explicit label — a raw candidate is never displayed as an adopted
    // policy, and never silently blank (plan 08: raw candidate, validated
    // candidate and adopted policy must not be conflated).
    return (
      <span style={{ color: 'var(--text-muted)' }}>
        {t('gov_evo_candidate_not_adopted')}
      </span>
    );
  }
  // adopted === null: meta output — inert provenance, not adoptable.
  return <span style={{ opacity: 0.55 }}>{t('gov_evo_inert')}</span>;
}

function EvolutionGroupCard({
  kind,
  entries,
  sourcePresent,
  absentMessage,
}: {
  kind: EvolutionKind;
  entries: RqgmEvolutionEntryV1[];
  sourcePresent: boolean;
  absentMessage: string;
}) {
  const t = useT();
  return (
    <Card title={t(KIND_TITLE_KEYS[kind])}>
      <div data-testid={`evo-group-${kind}`}>
        {!sourcePresent ? (
          // Absent artifact, not an empty-but-healthy log (plan 08).
          <EmptyState icon="🧬" message={absentMessage} />
        ) : entries.length === 0 ? (
          <EmptyState icon="🧬" message={t('gov_evo_group_empty')} />
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th>{t('gov_evo_col_record')}</th>
                  <th>{t('gov_evo_col_adoption')}</th>
                  <th>{t('gov_col_role')}</th>
                  <th>{t('gov_evo_col_mutation')}</th>
                  <th>{t('gov_evo_col_status')}</th>
                  <th>{t('gov_acc_col_epoch')}</th>
                  <th>{t('gov_evo_col_validation')}</th>
                  <th>{t('gov_evo_col_parent')}</th>
                  <th>{t('gov_evo_col_proposed_hash')}</th>
                  <th>{t('gov_evo_col_source')}</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => (
                  <tr key={`${entry.source}-${entry.record_id}`}>
                    <td>
                      <code style={{ fontSize: '.75rem' }}>{entry.record_id}</code>
                      {entry.candidate_id && (
                        <>
                          {' '}
                          <code style={{ fontSize: '.7rem', opacity: 0.7 }}>
                            {entry.candidate_id}
                          </code>
                        </>
                      )}
                    </td>
                    <td>
                      <AdoptionCell entry={entry} />
                    </td>
                    <td>{entry.role ?? entry.target_role ?? '—'}</td>
                    <td>
                      {kind === 'meta'
                        ? entry.output_kind ?? '—'
                        : entry.mutation_kind ?? '—'}
                    </td>
                    <td>{entry.status ?? '—'}</td>
                    <td>
                      <code style={{ fontSize: '.75rem' }}>{entry.epoch_id ?? '—'}</code>
                    </td>
                    <td>
                      <code style={{ fontSize: '.75rem' }}>
                        {entry.validation_passed_count} / {entry.validation_record_count}
                      </code>
                    </td>
                    <td>
                      {/* Parent lineage link (candidate ancestry). */}
                      <code style={{ fontSize: '.72rem' }}>{entry.parent_ref ?? '—'}</code>
                    </td>
                    <td>
                      <PolicyHashLabel
                        hash={entry.proposed_policy_hash ?? entry.proposed_prompt_hash}
                      />
                    </td>
                    <td>
                      {/* Raw-source drill-down: file + line offset. */}
                      <code style={{ fontSize: '.72rem' }}>
                        {SOURCE_FILES[entry.source]}@{entry.source_offset}
                      </code>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Card>
  );
}

export function EvolutionTab({ runId }: { runId: string }) {
  const t = useT();
  const evolutionQ = useRqgmEvolutionV1(runId, true);

  const grouped = useMemo(() => {
    const byKind: Record<EvolutionKind, RqgmEvolutionEntryV1[]> = {
      prompt: [],
      utility_policy: [],
      meta: [],
    };
    for (const entry of evolutionQ.data?.entries ?? []) {
      byKind[entry.kind].push(entry);
    }
    return byKind;
  }, [evolutionQ.data]);

  if (evolutionQ.isPending) return <LoadingState />;
  if (evolutionQ.isError && evolutionQ.data === undefined) {
    return (
      <ErrorState
        message={errorText(evolutionQ.error, t('gov_request_id'))}
        onRetry={() => void evolutionQ.refetch()}
      />
    );
  }
  const data = evolutionQ.data;
  if (data === undefined) return <LoadingState />;
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

      <p style={{ color: 'var(--text-muted)', fontSize: '.78rem', marginBottom: 8 }}>
        {t('gov_evo_note')}
      </p>

      <EvolutionGroupCard
        kind="prompt"
        entries={grouped.prompt}
        sourcePresent={data.evolution_present}
        absentMessage={t('gov_evo_log_absent')}
      />
      <EvolutionGroupCard
        kind="utility_policy"
        entries={grouped.utility_policy}
        sourcePresent={data.evolution_present}
        absentMessage={t('gov_evo_log_absent')}
      />
      <EvolutionGroupCard
        kind="meta"
        entries={grouped.meta}
        sourcePresent={data.meta_outputs_present}
        absentMessage={t('gov_evo_meta_absent')}
      />
    </div>
  );
}
