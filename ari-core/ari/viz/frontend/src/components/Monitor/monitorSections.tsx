// ARI Dashboard – Monitor page presentational/helper layer.
// Extracted verbatim from MonitorPage.tsx (refactor req 15, follow-up to 03):
// the pure metric helper + the Experiment-Configuration card. The container
// (MonitorPage.tsx) imports computeBestMetrics + IdeaCardContent from here.

import type { ReactNode } from 'react';
import { useEffect, useState } from 'react';
import { useI18n } from '../../i18n';
import { useDevMode } from '../../hooks/useDevMode';
import { fetchExperimentDetail } from '../../services/api';
import type { AppState, TreeNode } from '../../types';

// ── Metric computation ────────────────────────────

export interface MetricDisplay {
  key: string;
  value: number;
}

export function computeBestMetrics(nodes: TreeNode[]): { displays: MetricDisplay[]; tooltip: string } {
  const metricMap: Record<string, number[]> = {};
  nodes.forEach((n) => {
    const m = (n.metrics as Record<string, unknown>) || {};
    Object.keys(m).forEach((k) => {
      if (typeof m[k] === 'number' && !k.startsWith('_')) {
        if (!metricMap[k]) metricMap[k] = [];
        metricMap[k].push(m[k] as number);
      }
    });
  });

  const metricKeys = Object.keys(metricMap);

  if (metricKeys.length === 0) {
    // Fallback: scientific_score
    const scores = nodes.map((n) => {
      const m = (n.metrics as Record<string, number>) || {};
      return n.scientific_score || m._scientific_score || 0;
    });
    const best = scores.length ? Math.max(...scores) : 0;
    return {
      displays: [{ key: 'scientific_score', value: best }],
      tooltip: 'scientific_score',
    };
  }

  // Find preferred key
  const preferred = ['accuracy', 'f1', 'score', 'metric_value', 'throughput', 'latency'];
  let bestKey = metricKeys[0];
  preferred.forEach((p) => {
    if (metricMap[p]) bestKey = p;
  });

  const displayKeys = metricKeys
    .filter((k) => !['_scientific_score'].includes(k))
    .slice(0, 4);

  const displays = displayKeys.map((k) => ({
    key: k,
    value: Math.max(...metricMap[k]),
  }));

  return { displays, tooltip: bestKey };
}

// ── Idea card content builder ─────────────────────

export function IdeaCardContent({ state }: { state: AppState }) {
  const { t } = useI18n();
  const { devMode } = useDevMode();
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [detailConfig, setDetailConfig] = useState('');

  useEffect(() => {
    if (!detailsOpen || detailConfig) return;
    let cancelled = false;
    fetchExperimentDetail()
      .then((s) => { if (!cancelled) setDetailConfig(s); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [detailsOpen, detailConfig]);

  const mdContent = state.experiment_md_content || state.experiment_text || '';
  const ctx = (state.experiment_context as unknown as Record<string, any>) || {};
  const cfg = (state.experiment_config as Record<string, any>) || {};

  // Derive checkpoint ID from nodes
  let ckptId = '';
  if (state.nodes && state.nodes.length) {
    const rootId = state.nodes[0]?.id || '';
    const mm = rootId.match(/^node_([a-f0-9]{8,})/);
    ckptId = mm ? mm[1] : rootId.split('_').slice(1).join('_').replace('_root', '');
  }
  const nodeCount = state.node_count || state.nodes?.length || 0;

  // Build summary HTML-like content as React elements
  const summaryElements: ReactNode[] = [];

  if (!state.checkpoint_id) {
    const md0 = state.experiment_md_content || state.experiment_text || '';
    if (md0) {
      return (
        <div>
          <div style={{ fontSize: '.85rem', color: 'var(--muted)' }}>{md0}</div>
        </div>
      );
    }
    return (
      <div style={{ fontSize: '.85rem', color: 'var(--muted)' }}>
        {t('select_active_project')}
      </div>
    );
  }

  // Header with checkpoint ID
  if (ckptId) {
    summaryElements.push(
      <div key="header" style={{ marginBottom: 8 }}>
        <code style={{ color: 'var(--blue-light)', fontSize: '.82rem' }}>{ckptId}</code>
        {nodeCount > 0 && (
          <span className="badge badge-muted" style={{ marginLeft: 6 }}>
            {nodeCount} nodes
          </span>
        )}
      </div>,
    );
  }

  // Markdown content sections
  if (mdContent) {
    const sections = mdContent.split(/\n(?=##? )/);
    const hasSections = sections.length > 1;
    if (hasSections) {
      sections.forEach((sec, idx) => {
        const trimmed = sec.trim();
        if (!trimmed) return;
        const lines = trimmed.split('\n');
        let heading = lines[0].replace(/^#+\s*/, '');
        let body = lines.slice(1).join('\n').trim();
        if (!body && lines.length === 1) {
          body = heading;
          heading = '';
        }
        summaryElements.push(
          <div key={`sec-${idx}`} style={{ marginBottom: 10 }}>
            {heading && (
              <div
                style={{
                  fontSize: '.72rem',
                  fontWeight: 700,
                  color: 'var(--blue-light)',
                  textTransform: 'uppercase',
                  letterSpacing: '.04em',
                  marginBottom: 3,
                }}
              >
                {heading}
              </div>
            )}
            <div
              style={{
                fontSize: '.83rem',
                lineHeight: 1.65,
                color: 'var(--text)',
                whiteSpace: 'pre-wrap',
              }}
            >
              {body || trimmed}
            </div>
          </div>,
        );
      });
    } else {
      summaryElements.push(
        <div
          key="md-single"
          style={{ fontSize: '.83rem', lineHeight: 1.65, whiteSpace: 'pre-wrap' }}
        >
          {mdContent}
        </div>,
      );
    }
  } else {
    // Reconstruct from science_data experiment_context
    const overview =
      typeof ctx.study_overview === 'object' ? ctx.study_overview : ({} as any);
    const hw =
      typeof ctx.hardware_software_context === 'object'
        ? ctx.hardware_software_context
        : ({} as any);
    const topic =
      overview.topic ||
      overview.goal ||
      ctx.goal ||
      ctx.research_goal ||
      '(not recorded)';

    summaryElements.push(
      <div key="goal" style={{ marginBottom: 8 }}>
        <div
          style={{
            fontSize: '.72rem',
            fontWeight: 700,
            color: 'var(--blue-light)',
            textTransform: 'uppercase',
            letterSpacing: '.04em',
            marginBottom: 3,
          }}
        >
          Research Goal
        </div>
        <div style={{ fontSize: '.83rem', lineHeight: 1.65 }}>{String(topic)}</div>
      </div>,
    );

    if (hw.cpu_model || hw.parallel_model) {
      const hwStr = [hw.cpu_model, hw.parallel_model].filter(Boolean).join(', ');
      summaryElements.push(
        <div key="platform" style={{ marginBottom: 8 }}>
          <div
            style={{
              fontSize: '.72rem',
              fontWeight: 700,
              color: 'var(--blue-light)',
              textTransform: 'uppercase',
              letterSpacing: '.04em',
              marginBottom: 3,
            }}
          >
            Platform
          </div>
          <div style={{ fontSize: '.83rem', lineHeight: 1.65 }}>{hwStr}</div>
          {hw.compilation_flags_reported?.length > 0 && (
            <div style={{ fontSize: '.72rem', color: 'var(--muted)', fontFamily: 'monospace' }}>
              {hw.compilation_flags_reported.join(' ')}
            </div>
          )}
        </div>,
      );
    }

    if (overview.validated_parameter_sweep) {
      const ps = JSON.stringify(overview.validated_parameter_sweep).slice(0, 150);
      summaryElements.push(
        <div
          key="sweep"
          style={{ marginTop: 6, fontSize: '.75rem', color: 'var(--muted)' }}
        >
          {'📊'} Sweep: {ps}
        </div>,
      );
    }
  }

  // CONFIG rows
  if (Object.keys(cfg).length > 0) {
    const dispBackend = cfg.llm_backend || '—';
    const dispConn =
      cfg.llm_backend === 'ollama'
        ? cfg.ollama_host || 'localhost:11434'
        : cfg.llm_backend === 'openai'
          ? 'OpenAI API'
          : cfg.llm_backend === 'anthropic'
            ? 'Anthropic API'
            : cfg.llm_backend === 'gemini'
              ? 'Google API'
              : dispBackend;
    const cfgRows: [string, string][] = [
      ['🤖 LLM', `${dispBackend} / ${cfg.llm_model || '?'}`],
      [t('cfg_connection'), dispConn],
      [
        t('cfg_max_nodes'),
        `${cfg.max_nodes || '?'} / ${t('cfg_depth')} ${cfg.max_depth || '?'} / ${t('cfg_parallel')} ${cfg.parallel || '?'}`,
      ],
      [
        t('cfg_algorithm'),
        `${cfg.frontier_score || 'scientific_plus_diversity'} / ${cfg.composite || 'harmonic_mean'} / ${cfg.axis_mode || 'dynamic'}`,
      ],
      [
        t('cfg_timeout'),
        cfg.timeout_node_s ? `${Math.round(cfg.timeout_node_s / 60)}min/node` : '—',
      ],
      [t('cfg_scheduler'), `${cfg.scheduler || 'local'} / ${cfg.partition || 'auto'}`],
      [
        '💻 CPU/Mem/GPU',
        `${cfg.cpus || 'auto'}CPU / ${cfg.memory_gb ? cfg.memory_gb + 'GB' : 'auto'} / ${cfg.gpus ? cfg.gpus + 'GPU' : 'none'}`,
      ],
      ['⌛ Walltime', cfg.walltime || 'auto'],
    ];

    summaryElements.push(
      <div
        key="config"
        style={{
          borderTop: '1px solid var(--border)',
          marginTop: 10,
          paddingTop: 8,
        }}
      >
        <div
          style={{
            fontSize: '.68rem',
            fontWeight: 700,
            color: 'var(--blue-light)',
            textTransform: 'uppercase',
            marginBottom: 6,
          }}
        >
          CONFIG
        </div>
        {cfgRows.map(([label, value], i) => (
          <div key={i} style={{ display: 'flex', gap: 8, marginBottom: 3 }}>
            <span
              style={{
                fontSize: '.72rem',
                color: 'var(--muted)',
                minWidth: 100,
                flexShrink: 0,
              }}
            >
              {label}
            </span>
            <span style={{ fontSize: '.75rem' }}>{value}</span>
          </div>
        ))}
      </div>,
    );
  }

  if (summaryElements.length === 0) {
    summaryElements.push(
      <span key="empty" style={{ color: 'var(--muted)', fontSize: '.8rem' }}>
        No configuration available
      </span>,
    );
  }

  // The raw experiment-context JSON dump is a developer-only fallback (071):
  // only surface it when Developer Mode is on. Formatted detail (detailConfig /
  // mdContent) stays visible to everyone.
  const detailText =
    detailConfig ||
    mdContent ||
    (devMode ? JSON.stringify(ctx, null, 2) : '') ||
    '(no detail)';

  return (
    <div>
      <div className="card-title" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span>{'💡'} Experiment Configuration</span>
        <button
          className="btn btn-outline btn-sm"
          onClick={() => setDetailsOpen(!detailsOpen)}
        >
          {detailsOpen ? '▲ Hide' : '▼ Details'}
        </button>
      </div>
      <div style={{ fontSize: '.85rem', color: 'var(--muted)' }}>{summaryElements}</div>
      {detailsOpen && (
        <div style={{ marginTop: 12 }}>
          <pre
            className="code"
            style={{ maxHeight: 200, overflow: 'auto', fontSize: '.78rem' }}
          >
            {detailText}
          </pre>
        </div>
      )}
    </div>
  );
}
