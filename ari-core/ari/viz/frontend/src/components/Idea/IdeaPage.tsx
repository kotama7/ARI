import type { ReactNode } from 'react';
import { useEffect, useState } from 'react';
import { useI18n } from '../../i18n';
import { useAppContext } from '../../context/AppContext';
import { fetchState } from '../../services/api';
import type { AppState, TreeNode } from '../../types';
import { Card } from '../common';

// ── label / status color maps ────────────────────────

const LABEL_COLORS: Record<string, string> = {
  draft: '#8b5cf6',
  debug: '#06b6d4',
  ablation: '#f59e0b',
  validation: '#10b981',
  improve: '#ec4899',
};

const STATUS_COLORS: Record<string, string> = {
  success: '#22c55e',
  failed: '#ef4444',
  running: '#3b82f6',
};

const STRATEGY_COLORS: Record<string, string> = {
  draft: '#3b82f6',
  improve: '#8b5cf6',
  ablation: '#f59e0b',
  debug: '#ef4444',
  validation: '#10b981',
};

// ── helpers ──────────────────────────────────────────

function connectionDisplay(cfg: Record<string, unknown>): string {
  const backend = cfg.llm_backend as string | undefined;
  if (backend === 'ollama') return (cfg.ollama_host as string) || 'localhost:11434';
  if (backend === 'openai') return 'OpenAI API';
  if (backend === 'anthropic') return 'Anthropic API';
  if (backend === 'gemini') return 'Google API';
  return backend || '—';
}

// ── component ────────────────────────────────────────

export default function IdeaPage() {
  const { t } = useI18n();
  const { state: ctxState } = useAppContext();
  const [state, setState] = useState<AppState | null>(null);

  // Always fetch fresh state on mount so ideas / gap_analysis are present
  useEffect(() => {
    fetchState()
      .then((s) => setState(s))
      .catch(() => {
        if (ctxState) setState(ctxState);
      });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (!state) return <p style={{ color: 'var(--muted)' }}>{t('loading')}</p>;

  const cfg = (state.experiment_config || {}) as Record<string, unknown>;
  const hasCfg = Object.keys(cfg).length > 0;

  // Config rows
  const dispBackend = (cfg.llm_backend as string) || '—';
  const configRows: [string, string][] = hasCfg
    ? [
        ['🤖 LLM', `${dispBackend} / ${(cfg.llm_model as string) || '—'}`],
        [t('cfg_connection'), connectionDisplay(cfg)],
        [
          t('cfg_max_nodes'),
          `${cfg.max_nodes ?? '—'} / ${t('cfg_depth')} ${cfg.max_depth ?? '—'} / ${t('cfg_parallel')} ${cfg.parallel ?? '—'}`,
        ],
        [
          t('cfg_timeout'),
          cfg.timeout_node_s
            ? `${Math.round((cfg.timeout_node_s as number) / 60)}min/node`
            : '—',
        ],
        [t('cfg_scheduler'), `${cfg.scheduler || 'local'} / ${cfg.partition || 'auto'}`],
        [
          '💻 CPU/Mem/GPU',
          `${cfg.cpus || 'auto'}CPU / ${cfg.memory_gb ? `${cfg.memory_gb}GB` : 'auto'} / ${cfg.gpus ? `${cfg.gpus}GPU` : 'none'}`,
        ],
        ['⌛ Walltime', (cfg.walltime as string) || 'auto'],
      ]
    : [];

  // Experiment detail content
  const detailParts: string[] = [];
  if (state.experiment_md_content) {
    detailParts.push('=== experiment.md ===\n' + state.experiment_md_content.trim());
  }
  if (state.experiment_detail_config) {
    detailParts.push(
      '\n=== config (merged) ===\n' +
        (typeof state.experiment_detail_config === 'string'
          ? state.experiment_detail_config
          : JSON.stringify(state.experiment_detail_config, null, 2)
        ).trim(),
    );
  }

  // Goal
  const ctx = (state.experiment_context || {}) as Record<string, string>;
  const goal = state.experiment_goal || ctx.goal || ctx.research_goal || '';

  // Nodes
  const nodes: TreeNode[] = state.nodes || [];

  // Best hypothesis
  let bestNode: TreeNode | null = null;
  let bestScore = -Infinity;
  nodes.forEach((n) => {
    if (n.eval_summary) {
      const sc = typeof n.score === 'number' ? n.score : n.status === 'success' ? 1 : 0;
      if (sc > bestScore) {
        bestScore = sc;
        bestNode = n;
      }
    }
  });

  const root = nodes.find((n) => !n.parent_id || n.depth === 0) || null;

  let rootIdea: string;
  if (bestNode) {
    const bn = bestNode as TreeNode;
    const badge = `[${(bn.label || '?').toUpperCase()}] `;
    const scoreStr = typeof bn.score === 'number' ? ` (score: ${bn.score})` : '';
    rootIdea = badge + bn.eval_summary + scoreStr;
  } else if (root?.eval_summary) {
    rootIdea = root.eval_summary;
  } else {
    rootIdea = '(hypothesis not yet generated — BFTS root node failed before idea generation)';
  }

  // All hypotheses list
  const hyps = nodes.filter((n) => n.eval_summary && n.status !== 'pending');

  // Strategy: label distribution
  const labelCount: Record<string, number> = {};
  nodes.forEach((n) => {
    const l = n.label || 'unknown';
    labelCount[l] = (labelCount[l] || 0) + 1;
  });

  // Best success node
  const bestSuccess = nodes
    .filter((n) => n.status === 'success')
    .sort((a, b) => {
      const sa = (a.metrics as Record<string, number> | null)?._scientific_score ?? 0;
      const sb = (b.metrics as Record<string, number> | null)?._scientific_score ?? 0;
      return sb - sa;
    })[0] || null;

  // VirSci ideas
  const ideas = (state.ideas || []) as Array<Record<string, unknown>>;
  const gapAnalysis = state.gap_analysis || '';
  const primaryMetric = state.idea_primary_metric || '';
  const metricRationale = state.idea_metric_rationale || '';

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
      {/* ── Left Column ────────────────────── */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        {/* Experiment Configuration */}
        <Card title="⚙️ Experiment Configuration">
          {hasCfg ? (
            <div>
              {configRows.map(([label, value], i) => (
                <div key={i} style={{ marginBottom: '2px' }}>
                  <span
                    style={{
                      display: 'inline-block',
                      minWidth: '130px',
                      color: 'var(--muted)',
                      fontSize: '.75rem',
                    }}
                  >
                    {label}
                  </span>
                  <span style={{ fontSize: '.78rem' }}>{value}</span>
                </div>
              ))}
            </div>
          ) : (
            <span style={{ fontSize: '.85rem', color: 'var(--muted)' }}>
              {state.checkpoint_id || '(not recorded)'}
            </span>
          )}

          {/* Collapsible experiment.md / config details */}
          <details style={{ marginTop: '10px' }}>
            <summary style={{ cursor: 'pointer', fontSize: '.78rem', color: 'var(--accent)' }}>
              {t('show_details')}
            </summary>
            <pre
              style={{
                fontSize: '.78rem',
                whiteSpace: 'pre-wrap',
                marginTop: '6px',
                padding: '8px',
                background: 'var(--bg)',
                border: '1px solid var(--border)',
                borderRadius: '4px',
              }}
            >
              {detailParts.length ? detailParts.join('\n') : '(not available)'}
            </pre>
          </details>
        </Card>

        {/* Research Goal */}
        <Card title="🎯 Research Goal">
          <div style={{ fontSize: '.88rem', lineHeight: 1.6 }}>{goal || '(not available)'}</div>
        </Card>

        {/* Gap Analysis (hidden if no data) */}
        {gapAnalysis && (
          <Card title="🔍 Gap Analysis">
            <div style={{ fontSize: '.85rem', whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>
              {gapAnalysis}
            </div>
          </Card>
        )}

        {/* Primary Metric (hidden if no data) */}
        {primaryMetric && (
          <Card title="📊 Primary Metric">
            <div>
              <b>{primaryMetric}</b>
              {metricRationale && (
                <div style={{ fontSize: '.78rem', color: 'var(--muted)', marginTop: '4px' }}>
                  {metricRationale}
                </div>
              )}
            </div>
          </Card>
        )}
      </div>

      {/* ── Right Column ───────────────────── */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        {/* VirSci Hypotheses */}
        <Card title="🧪 VirSci Hypotheses">
        {ideas.length === 0 ? (
          <div style={{ color: 'var(--muted)', fontSize: '.85rem' }}>
            No VirSci hypotheses available. VirSci deliberation may not have run yet, or idea.json is empty.
          </div>
        ) : (
            ideas.map((idea, idx) => {
              const scores: ReactNode[] = [];
              if (idea.novelty_score != null)
                scores.push(
                  <span key="n" style={{ marginRight: '12px' }}>
                    Novelty <b>{String(idea.novelty_score)}</b>
                  </span>,
                );
              if (idea.feasibility_score != null)
                scores.push(
                  <span key="f" style={{ marginRight: '12px' }}>
                    Feasibility <b>{String(idea.feasibility_score)}</b>
                  </span>,
                );
              if (idea.overall_score != null)
                scores.push(
                  <span key="o">
                    Overall <b>{String(idea.overall_score)}</b>
                  </span>,
                );

              // Experiment plan
              let epStr = '';
              const ep = idea.experiment_plan;
              if (Array.isArray(ep)) {
                epStr = ep.map((s, i) => `${i + 1}. ${s}`).join('\n');
              } else if (ep && typeof ep === 'object') {
                epStr = Object.entries(ep as Record<string, unknown>)
                  .map(([k, v]) => `${k}: ${v}`)
                  .join('\n');
              } else if (ep) {
                epStr = String(ep);
              }

              return (
                <div
                  key={idx}
                  style={
                    idx > 0
                      ? {
                          marginTop: '12px',
                          paddingTop: '12px',
                          borderTop: '1px solid var(--border)',
                        }
                      : undefined
                  }
                >
                  <div style={{ fontWeight: 700, fontSize: '.88rem' }}>
                    {(idea.title as string) || `Hypothesis ${idx + 1}`}
                  </div>
                  <div style={{ fontSize: '.78rem', color: 'var(--muted)', marginTop: '4px' }}>
                    {scores}
                  </div>
                  {idea.description ? (
                    <div style={{ fontSize: '.82rem', marginTop: '6px', lineHeight: 1.5 }}>
                      {String(idea.description)}
                    </div>
                  ) : null}
                  {epStr && (
                    <details style={{ marginTop: '8px' }}>
                      <summary
                        style={{ cursor: 'pointer', fontSize: '.78rem', color: 'var(--accent)' }}
                      >
                        Experiment Plan
                      </summary>
                      <pre
                        style={{
                          fontSize: '.78rem',
                          whiteSpace: 'pre-wrap',
                          marginTop: '4px',
                          padding: '8px',
                          background: 'var(--bg)',
                          border: '1px solid var(--border)',
                          borderRadius: '4px',
                        }}
                      >
                        {epStr}
                      </pre>
                    </details>
                  )}
                </div>
              );
            })
        )}
        </Card>

        {/* Best Hypothesis (BFTS) */}
        <Card title="🌳 Best Hypothesis (BFTS)">
          <div style={{ fontSize: '.85rem', lineHeight: 1.6 }}>{rootIdea}</div>

          {/* All hypotheses list */}
          {hyps.length > 1 && (
            <div style={{ marginTop: '12px' }}>
              <div style={{ fontSize: '.75rem', color: 'var(--muted)', marginBottom: '6px' }}>
                ALL HYPOTHESES ({hyps.length} nodes)
              </div>
              {hyps.map((n) => {
                const lc = LABEL_COLORS[n.label] || '#888';
                const sc = STATUS_COLORS[n.status] || '#888';
                return (
                  <div
                    key={n.id}
                    style={{
                      borderLeft: `2px solid ${lc}`,
                      padding: '6px 10px',
                      marginBottom: '6px',
                      background: 'var(--card)',
                    }}
                  >
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                        marginBottom: '3px',
                      }}
                    >
                      <span style={{ color: lc, fontSize: '.68rem', fontWeight: 600 }}>
                        {n.label || '?'}
                      </span>
                      <span
                        style={{
                          color: 'var(--muted)',
                          fontSize: '.68rem',
                          fontFamily: 'monospace',
                        }}
                      >
                        {(n.id || '').slice(-8)}
                      </span>
                      <span style={{ color: sc, fontSize: '.68rem' }}>{'●'}</span>
                      {typeof n.score === 'number' && (
                        <span style={{ color: '#22c55e', fontWeight: 600, marginLeft: '6px' }}>
                          {n.score}
                        </span>
                      )}
                    </div>
                    <div style={{ fontSize: '.78rem', lineHeight: 1.5, color: 'var(--text)' }}>
                      {n.eval_summary}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </Card>

        {/* Idea Generation Strategy */}
        <Card title="💡 Idea Generation Strategy">
          <div style={{ marginBottom: '8px', fontSize: '.78rem', color: 'var(--muted)' }}>
            {nodes.length} nodes explored
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
            {Object.entries(labelCount).map(([l, c]) => {
              const col = STRATEGY_COLORS[l] || '#64748b';
              return (
                <div
                  key={l}
                  style={{
                    background: `${col}22`,
                    border: `1px solid ${col}`,
                    borderRadius: '8px',
                    padding: '4px 12px',
                    fontSize: '.8rem',
                  }}
                >
                  <strong style={{ color: col }}>{l}</strong>{' '}
                  <span style={{ color: 'var(--muted)' }}>{'×'}{c}</span>
                </div>
              );
            })}
          </div>

          {/* Best node metrics */}
          {bestSuccess && (
            <div style={{ marginTop: '12px' }}>
              <div style={{ fontSize: '.78rem', color: 'var(--muted)', marginBottom: '4px' }}>
                Best node: <strong>{bestSuccess.id}</strong> ({bestSuccess.label})
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                {Object.entries((bestSuccess.metrics as Record<string, unknown>) || {})
                  .filter(([k]) => !k.startsWith('_'))
                  .map(([k, v]) => {
                    const vs =
                      typeof v === 'number'
                        ? v > 100
                          ? v.toFixed(0)
                          : v.toFixed(3)
                        : String(v).slice(0, 20);
                    return (
                      <span key={k} className="badge badge-blue">
                        {k}: <strong>{vs}</strong>
                      </span>
                    );
                  })}
              </div>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
