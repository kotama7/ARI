import React from 'react';
import { Card } from '../../common/Card';
import type { CheckpointSummary } from '../../../types';

// ─── Experiment-context card (extracted from ResultsPage renderContext) ───
// Pure render of summary.science_data.experiment_context. Returns null when
// absent. Body verbatim from the container.
export function renderContext({
  summary,
  t,
}: {
  summary: CheckpointSummary | null;
  t: (key: string) => string;
}): React.ReactNode {
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
}
