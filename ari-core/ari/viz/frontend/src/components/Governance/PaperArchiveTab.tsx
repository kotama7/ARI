// ARI Dashboard – Governance Paper Archive tab (gui_refresh task 08 Wave
// 4b; plan 08 §Paper Archive).
//
// Bounded paper-archive summary with the two independence rules enforced in
// the UI:
//   - execution mode (ari.mode) and paper mode (paper.mode) are INDEPENDENT
//     axes: both chips render side by side, always, with an explicit note
//     (the bare word "mode" is never used alone);
//   - the best-belief draft is a REVIEWED selection — never equated with
//     the governance winner or the research result.
// Absence stays absence (plan 08 §Truth rules):
//   - paper_archive_state.json absent => the linear chip is shown WITH the
//     "derived from absence" note (state_present=false is surfaced, the
//     derivation is transparent);
//   - an absent draft archive renders "not present" — draft_count=null is
//     never rendered as 0;
//   - anchor.enabled=null (no frozen paper utility policy) is unknown, and
//     anchor.enabled=false carries the plan-08 note verbatim: the archive
//     is reviewed best-of-N and writer sanctions cannot fire.

import { useT } from '../../i18n';
import { useRqgmPaperArchiveV1 } from '../../hooks/useV1';
import { Badge, Card, DegradedState, EmptyState, ErrorState, LoadingState } from '../common';
import { errorText, ScoreValue } from './shared';
import type { RqgmPaperArchiveV1 } from '../../services/api/v1';

function ModeChips({
  executionMode,
  archive,
}: {
  executionMode: string;
  archive: RqgmPaperArchiveV1;
}) {
  const t = useT();
  const paperMode = archive.paper_mode ?? 'linear';
  return (
    <div data-testid="paper-mode-strip" style={{ marginBottom: 12 }}>
      <p
        style={{
          display: 'flex',
          gap: 12,
          flexWrap: 'wrap',
          alignItems: 'center',
          fontSize: '.82rem',
          marginBottom: 4,
        }}
      >
        <span>
          {t('gov_execution_mode')}: <Badge variant="green">{executionMode}</Badge>
        </span>
        <span>
          {t('gov_paper_mode')}:{' '}
          <Badge variant={paperMode === 'rqgm_archive' ? 'blue' : 'muted'}>
            {paperMode}
          </Badge>
        </span>
        {archive.mode_source !== null && archive.mode_source !== undefined && (
          <span>
            {t('gov_mode_source')}:{' '}
            <code style={{ fontSize: '.78rem' }}>{archive.mode_source}</code>
          </span>
        )}
      </p>
      <p style={{ color: 'var(--text-muted)', fontSize: '.78rem', marginBottom: 4 }}>
        {t('gov_paper_independence_note')}
      </p>
      {!archive.state_present && (
        // Transparent derivation: absence of the state file MEANS linear by
        // the source contract — but the absence itself is surfaced, never
        // silently rendered as recorded state (plan 08 §Truth rules).
        <p style={{ color: 'var(--status-warning)', fontSize: '.78rem' }}>
          {t('gov_paper_state_absent')}
        </p>
      )}
    </div>
  );
}

function ArchiveCard({ archive }: { archive: RqgmPaperArchiveV1 }) {
  const t = useT();
  return (
    <Card title={t('gov_paper_archive_title')}>
      <div data-testid="paper-archive-card">
        {!archive.archive_present ? (
          <EmptyState icon="📄" message={t('gov_paper_archive_absent')} />
        ) : (
          <table>
            <tbody>
              <tr>
                <td>{t('gov_paper_draft_count')}</td>
                <td data-testid="paper-draft-count">
                  {archive.draft_count === null ? (
                    // Absent draft-archive file: unknown, never 0.
                    <span style={{ opacity: 0.55 }}>{t('gov_paper_not_present')}</span>
                  ) : (
                    <code style={{ fontSize: '.78rem' }}>{archive.draft_count}</code>
                  )}
                </td>
              </tr>
              <tr>
                <td>{t('gov_paper_epochs')}</td>
                <td>
                  <code style={{ fontSize: '.75rem' }}>
                    {(archive.epochs ?? []).join(', ') || '—'}
                  </code>
                </td>
              </tr>
              <tr>
                <td>{t('gov_paper_fingerprint')}</td>
                <td>
                  <code style={{ fontSize: '.75rem' }}>
                    {archive.paper_epoch_fingerprint ?? t('gov_unknown')}
                  </code>
                </td>
              </tr>
            </tbody>
          </table>
        )}
      </div>
    </Card>
  );
}

function AnchorCard({ archive }: { archive: RqgmPaperArchiveV1 }) {
  const t = useT();
  const anchor = archive.anchor ?? { enabled: null, corpus_present: false };
  return (
    <Card title={t('gov_paper_anchor_title')}>
      <div data-testid="paper-anchor-card">
        <p style={{ display: 'flex', gap: 8, flexWrap: 'wrap', fontSize: '.82rem' }}>
          {anchor.enabled === true && (
            <Badge variant="green">{t('gov_paper_anchor_enabled')}</Badge>
          )}
          {anchor.enabled === false && (
            <Badge variant="yellow">{t('gov_paper_anchor_disabled')}</Badge>
          )}
          {(anchor.enabled === null || anchor.enabled === undefined) && (
            // No frozen paper utility policy => unknown, never guessed.
            <Badge variant="muted">{t('gov_paper_anchor_unknown')}</Badge>
          )}
          <Badge variant={anchor.corpus_present ? 'blue' : 'muted'}>
            {anchor.corpus_present
              ? t('gov_paper_corpus_present')
              : t('gov_paper_corpus_absent')}
          </Badge>
        </p>
        {anchor.enabled === false && (
          // The plan-08 §Paper Archive note: with the anchor disabled the
          // archive is reviewed best-of-N and writer sanctions cannot fire.
          <p style={{ color: 'var(--text-muted)', fontSize: '.78rem', marginTop: 6 }}>
            {t('gov_paper_anchor_disabled_note')}
          </p>
        )}
      </div>
    </Card>
  );
}

function SelfPreferenceCard({ archive }: { archive: RqgmPaperArchiveV1 }) {
  const t = useT();
  const stat = archive.self_preference ?? { stat_present: false };
  return (
    <Card title={t('gov_paper_selfpref_title')}>
      <div data-testid="paper-selfpref-card">
        {!stat.stat_present ? (
          <EmptyState icon="⚖️" message={t('gov_paper_selfpref_absent')} />
        ) : (
          <table>
            <tbody>
              <tr>
                <td>{t('gov_acc_col_epoch')}</td>
                <td>
                  <code style={{ fontSize: '.75rem' }}>
                    {stat.epoch_id ?? t('gov_unknown')}
                  </code>
                </td>
                <td>{t('gov_paper_selfpref_samples')}</td>
                <td>
                  <ScoreValue value={stat.sample_count} />
                </td>
              </tr>
              <tr>
                <td>{t('gov_paper_selfpref_margin')}</td>
                <td>
                  <ScoreValue value={stat.margin} />
                </td>
                <td>{t('gov_paper_selfpref_ai')}</td>
                <td>
                  <ScoreValue value={stat.ai_mean} />
                </td>
              </tr>
              <tr>
                <td>{t('gov_paper_selfpref_human')}</td>
                <td>
                  <ScoreValue value={stat.human_mean} />
                </td>
                <td />
                <td />
              </tr>
            </tbody>
          </table>
        )}
      </div>
    </Card>
  );
}

function WinnerCard({ archive }: { archive: RqgmPaperArchiveV1 }) {
  const t = useT();
  const winner = archive.winner ?? { node_id: null, materialized: false };
  return (
    <Card title={t('gov_paper_winner_title')}>
      <div data-testid="paper-winner-card">
        {/* Reviewed selection != governance winner != research result
            (plan 08 §Paper Archive) — the note renders unconditionally. */}
        <p style={{ color: 'var(--text-muted)', fontSize: '.78rem', marginBottom: 6 }}>
          {t('gov_paper_winner_note')}
        </p>
        {winner.node_id === null || winner.node_id === undefined ? (
          <EmptyState icon="🗂️" message={t('gov_paper_winner_absent')} />
        ) : (
          <p style={{ display: 'flex', gap: 10, flexWrap: 'wrap', fontSize: '.82rem' }}>
            <code style={{ fontSize: '.78rem' }}>{winner.node_id}</code>
            <Badge variant={winner.materialized ? 'green' : 'muted'}>
              {winner.materialized
                ? t('gov_paper_winner_materialized')
                : t('gov_paper_winner_not_materialized')}
            </Badge>
          </p>
        )}
      </div>
    </Card>
  );
}

export function PaperArchiveTab({
  runId,
  executionMode,
}: {
  runId: string;
  executionMode: string;
}) {
  const t = useT();
  const archiveQ = useRqgmPaperArchiveV1(runId, true);

  if (archiveQ.isPending) return <LoadingState />;
  if (archiveQ.isError && archiveQ.data === undefined) {
    return (
      <ErrorState
        message={errorText(archiveQ.error, t('gov_request_id'))}
        onRetry={() => void archiveQ.refetch()}
      />
    );
  }
  const archive = archiveQ.data;
  if (archive === undefined) return <LoadingState />;
  const reasons = archive.degraded_reasons ?? [];

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

      <ModeChips executionMode={executionMode} archive={archive} />
      <ArchiveCard archive={archive} />
      <AnchorCard archive={archive} />
      <SelfPreferenceCard archive={archive} />
      <WinnerCard archive={archive} />
    </div>
  );
}
