import React, { useEffect, useState, useCallback } from 'react';
import { useI18n } from '../../i18n';
import { useAppContext } from '../../context/AppContext';
import {
  fetchCheckpointSummary,
} from '../../services/api';
import type { CheckpointSummary } from '../../types';
import { Card } from '../common/Card';
import { Button } from '../common/Button';
import { Badge } from '../common/Badge';

export function ResultsPage() {
  const { t } = useI18n();
  const { state, checkpoints } = useAppContext();

  const [selectedId, setSelectedId] = useState<string>('');
  const [summary, setSummary] = useState<CheckpointSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [paperView, setPaperView] = useState<'pdf' | 'tex'>('pdf');

  // Pick initial selection
  const populateDropdown = useCallback(async () => {

    // Determine active checkpoint
    const activeId =
      state?.checkpoint_id ||
      String(state?.checkpoint_path || '')
        .split('/')
        .pop() ||
      '';

    // Check if there's a pre-selected checkpoint from Experiments page
    const storedId = sessionStorage.getItem('ari_selected_checkpoint');
    if (storedId) {
      sessionStorage.removeItem('ari_selected_checkpoint');
      setSelectedId(storedId);
      return storedId;
    }

    // Auto-select active checkpoint
    if (activeId) {
      setSelectedId(activeId);
      return activeId;
    }

    return '';
  }, [state?.checkpoint_id, state?.checkpoint_path]);

  // Load results for selected checkpoint
  const loadResults = useCallback(
    async (id: string) => {
      if (!id) {
        setSummary(null);
        setError(null);
        return;
      }

      setLoading(true);
      setError(null);
      setSummary(null);

      try {
        const d = await fetchCheckpointSummary(id);
        if (d.error) {
          setError(d.error);
        } else {
          setSummary(d);
          // Default to PDF if available, else TeX
          if (d.has_pdf) {
            setPaperView('pdf');
          } else if (d.paper_tex) {
            setPaperView('tex');
          }
        }
      } catch (e: any) {
        setError(e.toString());
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  // Initial load
  useEffect(() => {
    populateDropdown().then((id) => {
      if (id) loadResults(id);
    });
  }, [populateDropdown, loadResults]);

  // Re-fetch summary when experiment state changes (e.g. repro report generated)
  const prevHasRepro = React.useRef(state?.has_repro);
  const prevHasReview = React.useRef(state?.has_review);
  useEffect(() => {
    if (
      selectedId &&
      (state?.has_repro !== prevHasRepro.current ||
       state?.has_review !== prevHasReview.current)
    ) {
      prevHasRepro.current = state?.has_repro;
      prevHasReview.current = state?.has_review;
      loadResults(selectedId);
    }
  }, [state?.has_repro, state?.has_review, selectedId, loadResults]);

  // Re-load when selection changes
  const handleSelectChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const id = e.target.value;
    setSelectedId(id);
    loadResults(id);
  };

  // Render review scores section
  const renderReviewScores = () => {
    const rr = summary?.review_report;
    if (!rr) return null;

    const scores: [string, number | null][] = [
      [
        t('abstract'),
        rr.abstract_score ?? rr.scores?.abstract ?? null,
      ],
      [t('body'), rr.body_score ?? rr.scores?.body ?? null],
      [
        t('overall'),
        rr.overall_score ?? rr.score ?? null,
      ],
    ];

    return (
      <Card style={{ marginBottom: 16 }}>
        <div className="card-title">{t('review_scores')}</div>
        <div className="grid-3">
          {scores.map(([label, value]) => (
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
  };

  // Render paper viewer section
  const renderPaper = () => {
    if (!summary) return null;
    if (!summary.paper_tex && !summary.has_pdf) return null;

    return (
      <Card style={{ marginBottom: 16 }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: 8,
            marginBottom: 12,
          }}
        >
          <div className="card-title" style={{ margin: 0 }}>
            {t('paper_title')}
          </div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {summary.has_pdf && (
              <Button
                variant={paperView === 'pdf' ? 'primary' : 'outline'}
                size="sm"
                onClick={() => setPaperView('pdf')}
              >
                {'📑'} View PDF
              </Button>
            )}
            {summary.paper_tex && (
              <Button
                variant={paperView === 'tex' ? 'primary' : 'outline'}
                size="sm"
                onClick={() => setPaperView('tex')}
              >
                {'📝'} View TeX
              </Button>
            )}
            {summary.has_pdf && (
              <a
                className="btn btn-outline btn-sm"
                href={`/api/checkpoint/${encodeURIComponent(selectedId)}/paper.pdf`}
                download="paper.pdf"
              >
                {'⬇'} PDF
              </a>
            )}
            {summary.paper_tex && (
              <a
                className="btn btn-outline btn-sm"
                href={`/api/checkpoint/${encodeURIComponent(selectedId)}/paper.tex`}
                download="paper.tex"
              >
                {'⬇'} TeX
              </a>
            )}
          </div>
        </div>

        {summary.has_pdf && (
          <iframe
            src={`/api/checkpoint/${encodeURIComponent(selectedId)}/paper.pdf`}
            style={{
              width: '100%',
              height: 640,
              border: 'none',
              borderRadius: 6,
              display: paperView === 'pdf' ? 'block' : 'none',
            }}
            title="Paper PDF"
          />
        )}
        {summary.paper_tex && (
          <pre
            className="code"
            style={{
              maxHeight: 640,
              overflow: 'auto',
              display: paperView === 'tex' ? 'block' : 'none',
            }}
          >
            {summary.paper_tex.slice(0, 30000)}
          </pre>
        )}
      </Card>
    );
  };

  // Render verify / reproducibility section
  const renderRepro = () => {
    if (!summary) return null;

    const repro = summary.reproducibility_report || summary.repro;

    return (
      <Card style={{ marginBottom: 16 }}>
        <div className="card-title">{t('verify_title')}</div>
        {repro ? (
          (() => {
            const reproObj =
              typeof repro === 'string' ? tryParseJson(repro) : repro;

            if (!reproObj || typeof reproObj !== 'object') {
              // Plain string repro
              return (
                <div
                  style={{ fontSize: '.85rem', color: 'var(--muted)' }}
                >
                  {String(repro)}
                </div>
              );
            }

            const reproRecord = reproObj as Record<string, any>;

            // Handle skill-not-found error gracefully
            if (
              reproRecord.error &&
              (String(reproRecord.error).indexOf('not found') >= 0 ||
                String(reproRecord.error).indexOf('Tool') >= 0 ||
                String(reproRecord.error).indexOf('Available: []') >= 0)
            ) {
              return (
                <>
                  <div
                    style={{
                      color: 'var(--yellow)',
                      fontSize: '.85rem',
                      padding: 8,
                    }}
                  >
                    {t('repro_skill_unavail')}
                  </div>
                  <details>
                    <summary
                      style={{
                        fontSize: '.75rem',
                        color: 'var(--muted)',
                        cursor: 'pointer',
                      }}
                    >
                      {t('details')}
                    </summary>
                    <pre
                      style={{
                        fontSize: '.72rem',
                        color: 'var(--muted)',
                        marginTop: 4,
                      }}
                    >
                      {reproRecord.error}
                    </pre>
                  </details>
                </>
              );
            }

            const verdict =
              reproRecord.verdict ||
              reproRecord.status ||
              reproRecord.result ||
              'unknown';
            const badgeVariant =
              verdict === 'REPRODUCED' ||
              verdict === 'PASS' ||
              verdict === 'pass'
                ? 'green'
                : verdict === 'FAILED' ||
                    verdict === 'FAIL' ||
                    verdict === 'fail' ||
                    verdict === 'NOT_REPRODUCED'
                  ? 'red'
                  : verdict === 'ENVIRONMENT_MISMATCH'
                    ? 'yellow'
                    : 'yellow';

            const skip = new Set([
              'verdict',
              'status',
              'result',
              'summary',
            ]);

            return (
              <>
                <div style={{ fontSize: '1.1rem', marginBottom: 8 }}>
                  <Badge variant={badgeVariant}>{verdict}</Badge>
                </div>
                {reproRecord.summary && (
                  <div
                    style={{
                      fontSize: '.85rem',
                      color: 'var(--muted)',
                      marginBottom: 8,
                    }}
                  >
                    {reproRecord.summary}
                  </div>
                )}
                {Object.keys(reproRecord)
                  .filter((k) => !skip.has(k))
                  .slice(0, 8)
                  .map((k) => (
                    <div
                      key={k}
                      style={{ fontSize: '.8rem', marginTop: 4 }}
                    >
                      <span style={{ color: 'var(--muted)' }}>{k}:</span>{' '}
                      {JSON.stringify(reproRecord[k])}
                    </div>
                  ))}
              </>
            );
          })()
        ) : (
          <div style={{ color: 'var(--muted)', fontSize: '.85rem' }}>
            {t('no_repro')}
          </div>
        )}
      </Card>
    );
  };

  // Render experiment context
  const renderContext = () => {
    if (!summary) return null;
    const sd = summary.science_data;
    if (!sd || !(sd as any).experiment_context) return null;

    const ctx = (sd as any).experiment_context as Record<string, unknown>;

    return (
      <Card style={{ marginBottom: 16 }}>
        <div className="card-title">{t('exp_context')}</div>
        <div>
          {Object.entries(ctx).map(([k, v]) => {
            const text = String(
              typeof v === 'object'
                ? JSON.stringify(v, null, 2)
                : v,
            );
            return (
              <div key={k} style={{ marginBottom: 12 }}>
                <div style={{ color: 'var(--muted)', fontSize: '.75rem', marginBottom: 2, fontWeight: 600 }}>
                  {k}
                </div>
                {text.length <= 500 ? (
                  <div style={{ fontSize: '.8rem', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                    {text}
                  </div>
                ) : (
                  <details>
                    <summary style={{ cursor: 'pointer', color: 'var(--blue-light)', fontSize: '.75rem', listStyle: 'none', userSelect: 'none' }}>
                      {'▶ Show detail'}
                    </summary>
                    <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: '4px 0 0', fontSize: '.78rem', overflow: 'auto', maxHeight: 480 }}>
                      {text}
                    </pre>
                  </details>
                )}
              </div>
            );
          })}
        </div>
      </Card>
    );
  };

  // Render figures grid
  const renderFigures = () => {
    if (!summary) return null;
    const fm = summary.figures_manifest as any;
    if (!fm || !fm.figures || !fm.figures.length) return null;

    return (
      <Card style={{ marginBottom: 16 }}>
        <div className="card-title">{'📈'} Figures</div>
        <div className="grid-2">
          {fm.figures.map((fig: any, idx: number) => {
            const path = fig.path || fig;
            const caption = fig.caption || '';
            return (
              <div key={idx}>
                {caption && (
                  <div
                    style={{
                      fontSize: '.8rem',
                      color: 'var(--muted)',
                      marginBottom: 4,
                    }}
                  >
                    {caption}
                  </div>
                )}
                <img
                  className="figure-img"
                  src={`/codefile?path=${encodeURIComponent(path)}`}
                  alt="figure"
                  onError={(e) => {
                    (e.target as HTMLImageElement).style.display = 'none';
                  }}
                />
              </div>
            );
          })}
        </div>
      </Card>
    );
  };

  return (
    <div className="page active" style={{ display: 'block' }}>
      <h1>{t('results_title')}</h1>
      <p className="subtitle">{t('results_subtitle')}</p>

      {/* Checkpoint selector dropdown */}
      <div
        style={{
          display: 'flex',
          gap: 10,
          marginBottom: 20,
          alignItems: 'center',
        }}
      >
        <select
          style={{ width: 'auto', minWidth: 240 }}
          value={selectedId}
          onChange={handleSelectChange}
        >
          <option value="">{'—'} Select experiment {'—'}</option>
          {checkpoints.map((c) => {
            const scoreStr =
              c.review_score != null ? ` ✦${c.review_score}` : '';
            const label = c.id + scoreStr;
            return (
              <option key={c.id} value={c.id} title={c.id}>
                {label}
              </option>
            );
          })}
        </select>
        <Button variant="outline" size="sm" onClick={() => populateDropdown()}>
          {'↻'}
        </Button>
      </div>

      {/* Content */}
      <div>
        {loading && (
          <div style={{ color: 'var(--muted)' }}>
            <span className="spinner" /> {t('loading')}
          </div>
        )}

        {error && (
          <div style={{ color: 'var(--red)' }}>
            {t('error_prefix')}
            {error}
          </div>
        )}

        {!loading && !error && !selectedId && (
          <div className="empty-state">
            <div className="empty-icon">{'📊'}</div>
            <p>{t('select_exp')}</p>
          </div>
        )}

        {!loading && !error && summary && (
          <>
            {renderPaper()}
            {renderReviewScores()}
            {renderRepro()}
            {renderContext()}
            {renderFigures()}

            {/* If no content at all */}
            {!summary.paper_tex &&
              !summary.has_pdf &&
              !summary.review_report &&
              !summary.reproducibility_report &&
              !summary.repro &&
              !(summary.science_data as any)?.experiment_context &&
              !(summary.figures_manifest as any)?.figures?.length && (
                <div className="empty-state">
                  <div className="empty-icon">{'📊'}</div>
                  <p>No results data found in this checkpoint</p>
                </div>
              )}
          </>
        )}
      </div>
    </div>
  );
}

/** Attempt to parse a JSON string; return null on failure. */
function tryParseJson(s: any): any {
  if (typeof s !== 'string') return s;
  try {
    return JSON.parse(s);
  } catch {
    return null;
  }
}
