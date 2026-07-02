import React from 'react';
import { Badge } from '../../common/Badge';
import { Card } from '../../common/Card';
import type { CheckpointSummary } from '../../../types';

// ─── Review-scores card (extracted from ResultsPage renderReviewScores) ───
// Pure render of summary.review_report (rubric-driven or legacy schema). The
// decisionVariant/decisionLabel/renderDimension helpers were container-local
// and used only here, so they are nested verbatim (decisionLabel/renderDimension
// close over the t param exactly as they did the container's t). Returns null
// when no review_report. Body verbatim from the container.
export function renderReviewScores({
  summary,
  t,
}: {
  summary: CheckpointSummary | null;
  t: (key: string) => string;
}): React.ReactNode {
  // Decision → badge variant mapping
  const decisionVariant = (
    d?: string,
  ): 'green' | 'red' | 'yellow' | 'muted' => {
    if (!d) return 'muted';
    if (d === 'accept' || d === 'weak_accept') return 'green';
    if (d === 'reject' || d === 'weak_reject') return 'red';
    if (d === 'borderline') return 'yellow';
    return 'muted';
  };

  const decisionLabel = (d?: string): string => {
    if (!d) return '—';
    const key = `review_${d}`;
    const localized = t(key);
    return localized === key ? d : localized;
  };

  // Render one dimensional score (rubric-driven)
  const renderDimension = (
    name: string,
    value: number | null | undefined,
    scale: [number, number] | undefined,
  ) => {
    const [lo, hi] = scale ?? [0, 10];
    const range = hi - lo || 1;
    const pct =
      value != null ? Math.max(0, Math.min(100, ((value - lo) / range) * 100)) : 0;
    return (
      <div key={name}>
        <div
          style={{
            fontSize: '.8rem',
            color: 'var(--muted)',
            marginBottom: 4,
            textTransform: 'capitalize',
          }}
        >
          {name.replace(/_/g, ' ')}
        </div>
        <div style={{ fontSize: '1.4rem', fontWeight: 800 }}>
          {value != null ? value : '—'}{' '}
          <span style={{ fontSize: '.9rem', color: 'var(--muted)' }}>
            /{hi}
          </span>
        </div>
        {value != null && (
          <div className="score-bar">
            <div className="score-fill" style={{ width: `${pct}%` }} />
          </div>
        )}
      </div>
    );
  };

  const rr = summary?.review_report;
  if (!rr) return null;

  // Rubric-driven path: new schema with score_dimensions
  const hasRubric =
    !!rr.rubric_id || (rr.score_dimensions && rr.score_dimensions.length > 0);

  const legacyScores: [string, number | null][] = [
    [t('abstract'), rr.abstract_score ?? rr.scores?.abstract ?? null],
    [t('body'), rr.body_score ?? rr.scores?.body ?? null],
    [t('overall'), rr.overall_score ?? rr.score ?? null],
  ];

  const textSections: Array<{ key: string; label: string; body?: string }> = [
    { key: 'strengths', label: t('review_strengths'), body: rr.strengths },
    { key: 'weaknesses', label: t('review_weaknesses'), body: rr.weaknesses },
    { key: 'questions', label: t('review_questions'), body: rr.questions },
    {
      key: 'limitations',
      label: t('review_limitations'),
      body: rr.limitations,
    },
  ].filter((s) => s.body && s.body.trim().length > 0);

  return (
    <Card style={{ marginBottom: 16 }}>
      <div
        className="card-title"
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 8,
          flexWrap: 'wrap',
        }}
      >
        <span>{t('review_scores')}</span>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {rr.rubric_id && (
            <Badge variant="muted">
              {t('review_rubric')}: {rr.rubric_id}
              {rr.rubric_version ? ` @${rr.rubric_version}` : ''}
            </Badge>
          )}
          {rr.venue && <Badge variant="muted">{rr.venue}</Badge>}
          {rr.decision && (
            <Badge variant={decisionVariant(rr.decision)}>
              {t('review_decision')}: {decisionLabel(rr.decision)}
            </Badge>
          )}
        </div>
      </div>

      {hasRubric && rr.score_dimensions && rr.score_dimensions.length > 0 ? (
        <div
          className="grid-3"
          style={{
            gridTemplateColumns: `repeat(${Math.min(
              rr.score_dimensions.length,
              5,
            )}, minmax(0, 1fr))`,
          }}
        >
          {rr.score_dimensions.map((d) =>
            renderDimension(d.name, d.value, d.scale),
          )}
        </div>
      ) : (
        <div className="grid-3">
          {legacyScores.map(([label, value]) => (
            <div key={label}>
              <div
                style={{
                  fontSize: '.8rem',
                  color: 'var(--muted)',
                  marginBottom: 4,
                }}
              >
                {label}
              </div>
              <div style={{ fontSize: '1.4rem', fontWeight: 800 }}>
                {value != null ? value : '—'}{' '}
                <span style={{ fontSize: '.9rem', color: 'var(--muted)' }}>
                  /10
                </span>
              </div>
              {value != null && (
                <div className="score-bar">
                  <div
                    className="score-fill"
                    style={{ width: `${(value as number) * 10}%` }}
                  />
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {rr.confidence != null && (
        <div style={{ marginTop: 12, fontSize: '.9rem' }}>
          {t('review_confidence')}:{' '}
          <strong>{rr.confidence}</strong>
        </div>
      )}

      {textSections.length > 0 && (
        <div style={{ marginTop: 16, display: 'grid', gap: 12 }}>
          {textSections.map((s) => (
            <div key={s.key}>
              <div
                style={{
                  fontSize: '.85rem',
                  fontWeight: 700,
                  marginBottom: 4,
                }}
              >
                {s.label}
              </div>
              <div
                style={{
                  whiteSpace: 'pre-wrap',
                  fontSize: '.85rem',
                  lineHeight: 1.5,
                  color: 'var(--muted)',
                }}
              >
                {s.body}
              </div>
            </div>
          ))}
        </div>
      )}

      {rr.issues && rr.issues.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: '.85rem', fontWeight: 700, marginBottom: 4 }}>
            {t('review_issues')}
          </div>
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: '.85rem' }}>
            {rr.issues.map((x, i) => (
              <li key={i}>{x}</li>
            ))}
          </ul>
        </div>
      )}

      {rr.recommendations && rr.recommendations.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: '.85rem', fontWeight: 700, marginBottom: 4 }}>
            {t('review_recommendations')}
          </div>
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: '.85rem' }}>
            {rr.recommendations.map((x, i) => (
              <li key={i}>{x}</li>
            ))}
          </ul>
        </div>
      )}

      {rr.figure_caption_issues && rr.figure_caption_issues.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: '.85rem', fontWeight: 700, marginBottom: 4 }}>
            {t('review_figure_caption_issues')}
          </div>
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: '.85rem' }}>
            {rr.figure_caption_issues.map((x, i) => (
              <li key={i}>{x}</li>
            ))}
          </ul>
        </div>
      )}

      {rr.ensemble_reviews && rr.ensemble_reviews.length > 1 && (
        <div style={{ marginTop: 16 }}>
          <div style={{ fontSize: '.85rem', fontWeight: 700, marginBottom: 6 }}>
            {t('review_ensemble')} ({rr.ensemble_reviews.length})
          </div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {rr.ensemble_reviews.map((er, i) => (
              <Badge key={i} variant={decisionVariant(er.decision)}>
                #{i + 1}:{' '}
                {er.overall_score ?? er.score ?? '—'}{' '}
                {er.decision ? `(${decisionLabel(er.decision)})` : ''}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {rr.meta_review && (
        <div style={{ marginTop: 12, padding: 10, border: '1px solid var(--border)', borderRadius: 6 }}>
          <div style={{ fontSize: '.85rem', fontWeight: 700, marginBottom: 4 }}>
            {t('review_meta')}
          </div>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            {rr.meta_review.decision && (
              <Badge variant={decisionVariant(rr.meta_review.decision)}>
                {decisionLabel(rr.meta_review.decision)}
              </Badge>
            )}
            <span style={{ fontSize: '.9rem' }}>
              {t('overall')}:{' '}
              <strong>
                {rr.meta_review.overall_score ?? rr.meta_review.score ?? '—'}
              </strong>
            </span>
          </div>
        </div>
      )}

      {rr.fewshot_sources && rr.fewshot_sources.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: '.85rem', fontWeight: 700, marginBottom: 4 }}>
            {t('review_fewshot_sources')}
          </div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {rr.fewshot_sources.map((fs, i) => (
              <Badge key={i} variant="muted">
                {fs.title ?? fs.id}
                {fs.score != null ? ` (${fs.score.toFixed(2)})` : ''}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {rr.citation_ok != null && (
        <div style={{ marginTop: 12 }}>
          {t('citations')}:{' '}
          {rr.citation_ok ? (
            <Badge variant="green">{'✓'} {t('ok_label')}</Badge>
          ) : (
            <Badge variant="red">{'✗'} {t('issues_label')}</Badge>
          )}
        </div>
      )}
    </Card>
  );
}
