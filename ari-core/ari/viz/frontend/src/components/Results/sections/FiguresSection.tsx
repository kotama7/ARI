import React from 'react';
import { Badge } from '../../common/Badge';
import { Card } from '../../common/Card';
import type { CheckpointSummary } from '../../../types';

// ─── Figures grid (extracted from ResultsPage renderFigures) ──────────────
// Pure render of summary.figures_manifest (dict or legacy-list shape). Returns
// null when absent/empty. Body verbatim from the container.
export function renderFigures({
  summary,
}: {
  summary: CheckpointSummary | null;
}): React.ReactNode {
  if (!summary) return null;
  const fm = summary.figures_manifest as any;
  if (!fm || !fm.figures) return null;

  // plot-skill writes `figures` as a dict {name: path}; older runs may
  // have stored a list [{path, caption, ...}]. Normalize to a list here
  // so the grid works with both shapes.
  const kinds = (fm.figure_kinds || {}) as Record<string, string>;
  const snippets = (fm.latex_snippets || {}) as Record<string, string>;
  const extractCaption = (snip: string): string => {
    const m = snip.match(/\\caption\{([^}]+)\}/);
    return m ? m[1] : '';
  };
  const figs: Array<{ name: string; path: string; caption: string; kind: string }> =
    Array.isArray(fm.figures)
      ? fm.figures.map((fig: any, idx: number) => ({
          name: fig.name || `fig_${idx + 1}`,
          path: fig.path || fig,
          caption: fig.caption || '',
          kind: fig.kind || fig.figure_kind || '',
        }))
      : Object.entries(fm.figures as Record<string, string>).map(([name, path]) => ({
          name,
          path: String(path),
          caption: extractCaption(snippets[name] || ''),
          kind: kinds[name] || '',
        }));

  if (!figs.length) return null;

  return (
    <Card style={{ marginBottom: 16 }}>
      <div className="card-title">{'📈'} Figures</div>
      <div className="grid-2">
        {figs.map((fig, idx) => {
          const { path, caption, kind } = fig;
          const kindBadge: Record<string, string> = {
            plot: 'Plot',
            svg: 'Diagram',
          };
          return (
            <div key={idx}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                {kind && kindBadge[kind] && (
                  <Badge variant="blue">{kindBadge[kind]}</Badge>
                )}
                {caption && (
                  <span style={{ fontSize: '.8rem', color: 'var(--muted)' }}>
                    {caption}
                  </span>
                )}
              </div>
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
}
