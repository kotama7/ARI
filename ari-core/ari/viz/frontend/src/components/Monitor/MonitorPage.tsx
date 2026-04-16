// ARI Dashboard – Monitor page (React port of page-monitor from dashboard.js)

import type { ReactNode } from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useI18n } from '../../i18n';
import { useAppContext } from '../../context/AppContext';
import {
  runStage as apiRunStage,
  stopExperiment,
  detectScheduler,
  fetchExperimentDetail,
  fetchResourceMetrics,
} from '../../services/api';
import type { AppState, ResourceMetrics, TreeNode } from '../../types';
import PhaseStepper from './PhaseStepper';
import GpuMonitor from './GpuMonitor';
import { TreeVisualization } from '../Tree/TreeVisualization';

// ── Metric computation ────────────────────────────

interface MetricDisplay {
  key: string;
  value: number;
}

function computeBestMetrics(nodes: TreeNode[]): { displays: MetricDisplay[]; tooltip: string } {
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

function IdeaCardContent({ state }: { state: AppState }) {
  const { t } = useI18n();
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

  const detailText =
    detailConfig ||
    mdContent ||
    JSON.stringify(ctx, null, 2) ||
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

// ── Main MonitorPage ──────────────────────────────

export function MonitorPage() {
  const { t } = useI18n();
  const { state, nodesData, refreshState } = useAppContext();

  // GPU monitor visibility
  const [gpuVisible, setGpuVisible] = useState(false);
  const [hasSlurm, setHasSlurm] = useState(false);

  // Resource metrics
  const [resourceMetrics, setResourceMetrics] = useState<ResourceMetrics | null>(null);

  // Stage execution status
  const [stageStatus, setStageStatus] = useState('');

  // Log streaming
  const [logLines, setLogLines] = useState<string[]>([]);
  const [logStatus, setLogStatus] = useState<'disconnected' | 'streaming' | 'done' | 'error'>(
    'disconnected',
  );
  const logReaderRef = useRef<ReadableStreamDefaultReader<Uint8Array> | null>(null);
  const logOutputRef = useRef<HTMLDivElement>(null);

  // ── Detect SLURM on mount ─────────────────

  useEffect(() => {
    detectScheduler()
      .then((d) => {
        setHasSlurm(!!d?.scheduler && d.scheduler !== 'none');
      })
      .catch(() => setHasSlurm(false));
  }, []);

  // ── Resource metrics polling ───────────────

  useEffect(() => {
    let cancelled = false;
    const poll = () => {
      fetchResourceMetrics()
        .then((m) => { if (!cancelled) setResourceMetrics(m); })
        .catch(() => {});
    };
    poll();
    const timer = setInterval(poll, 5000);
    return () => { cancelled = true; clearInterval(timer); };
  }, []);

  // ── Compute stats ─────────────────────────

  const nodeCount = nodesData.length;
  const { displays: metricDisplays } = computeBestMetrics(nodesData);

  // Cost display
  const costData = state?.cost as any;
  const costUsd = costData?.total_cost_usd;
  const costTokens = costData?.total_tokens;
  const costText = costUsd != null ? `$${costUsd.toFixed(2)}` : '—';
  const costTooltip =
    costTokens != null
      ? `${(costTokens / 1000).toFixed(0)}K tokens | ${costData?.call_count ?? 0} calls`
      : '';

  // Model badge
  const modelName =
    state?.llm_model_actual ||
    (state?.actual_models
      ? Object.values(state.actual_models)
          .filter((v, i, a) => a.indexOf(v) === i)
          .join(', ')
      : '') ||
    (state?.experiment_config as any)?.llm_model ||
    '—';

  // Running state
  const isRunning = !!(state?.is_running || (state as any)?.running);

  // ── Stage execution ───────────────────────

  const handleRunStage = useCallback(
    async (stage: string) => {
      try {
        const d = await apiRunStage(stage);
        if (d.ok) {
          setStageStatus(`${stage} started (PID ${d.pid})`);
        } else {
          setStageStatus(`${t('error_prefix')}${d.error || ''}`);
        }
      } catch (e: any) {
        setStageStatus(`${t('error_prefix')}${e.message}`);
      }
      refreshState();
    },
    [t, refreshState],
  );

  const handleStop = useCallback(async () => {
    setStageStatus('Stop requested (may need manual kill on server)');
    try {
      const data = await stopExperiment();
      if (data?.report) {
        const rpt = data.report;
        const parts = [`main: ${rpt.main}`, `gpu: ${rpt.gpu_monitor}`];
        if (rpt.survivors?.length > 0) {
          parts.push(
            'WARNING survivors: ' +
              rpt.survivors
                .map((s: any) => `${s.pattern}(${s.pids.join(',')})`)
                .join(', '),
          );
        }
        setStageStatus(`Stop requested — ${parts.join(' | ')}`);
      }
    } catch (e: any) {
      console.error('[stop] error:', e);
    }
    refreshState();
  }, [refreshState]);

  // ── GPU monitor toggle ────────────────────

  const toggleGpuMonitor = useCallback(() => {
    setGpuVisible((v) => !v);
  }, []);

  // ── Log streaming ─────────────────────────

  const startLogStream = useCallback(async () => {
    // Cancel previous reader
    if (logReaderRef.current) {
      try {
        logReaderRef.current.cancel();
      } catch {
        // ignore
      }
      logReaderRef.current = null;
    }

    setLogLines([]);
    setLogStatus('streaming');

    let res: Response | null = null;
    try {
      res = await fetch('/api/logs');
    } catch {
      setLogStatus('error');
      return;
    }

    if (!res || !res.body) {
      setLogStatus('error');
      return;
    }

    const reader = res.body.getReader();
    logReaderRef.current = reader;
    const dec = new TextDecoder();
    let buf = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value);
        const lines = buf.split('\n\n');
        buf = lines.pop() || '';
        lines.forEach((line) => {
          const m = line.match(/^data: (.+)$/m);
          if (m) {
            try {
              const msg = JSON.parse(m[1]);
              if (msg.msg) {
                setLogLines((prev) => [...prev, msg.msg]);
              }
            } catch {
              // ignore parse error
            }
          }
        });
      }
    } catch {
      // stream interrupted
    }

    setLogStatus('done');
    logReaderRef.current = null;
  }, []);

  const clearLogs = useCallback(() => {
    setLogLines([]);
  }, []);

  // Auto-scroll logs
  useEffect(() => {
    if (logOutputRef.current) {
      logOutputRef.current.scrollTop = logOutputRef.current.scrollHeight;
    }
  }, [logLines]);

  // Auto-connect log stream on mount
  useEffect(() => {
    startLogStream();
    return () => {
      if (logReaderRef.current) {
        try {
          logReaderRef.current.cancel();
        } catch {
          // ignore
        }
      }
    };
  }, [startLogStream]);

  // ── Render ────────────────────────────────

  const logBadgeClass =
    logStatus === 'streaming'
      ? 'badge badge-yellow'
      : logStatus === 'error'
        ? 'badge badge-red'
        : 'badge badge-muted';

  return (
    <div className="page active" id="page-monitor">
      <h1 data-i18n="monitor_title">{t('monitor_title')}</h1>
      <p className="subtitle" data-i18n="monitor_subtitle">
        {t('monitor_subtitle')}
      </p>

      {/* Phase Stepper */}
      <PhaseStepper />

      {/* GPU Monitor Card (hidden by default) */}
      {gpuVisible && <GpuMonitor />}

      {/* Experiment Control Card */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <div className="card-title">Experiment Control</div>
          <span
            id="mon-model-badge"
            style={{
              fontSize: '.75rem',
              color: 'var(--muted)',
              background: 'var(--bg)',
              border: '1px solid var(--border)',
              borderRadius: 6,
              padding: '2px 8px',
            }}
          >
            model: {modelName}
          </span>
        </div>
        <div
          style={{
            display: 'flex',
            gap: 10,
            flexWrap: 'wrap',
            alignItems: 'center',
            marginBottom: 10,
          }}
        >
          {/* Resume / Paper / Review buttons: visible when NOT running */}
          {!isRunning && (
            <>
              <button
                id="btn-resume"
                className="btn btn-primary"
                onClick={() => handleRunStage('resume')}
                title="Resume BFTS tree exploration from checkpoint"
              >
                {'▶'} Resume Experiment
              </button>
              <button className="btn btn-outline" onClick={() => handleRunStage('paper')}>
                {'📝'} {t('btn_run_paper')}
              </button>
              <button className="btn btn-outline" onClick={() => handleRunStage('review')}>
                {'🔍'} {t('btn_run_review')}
              </button>
            </>
          )}
          {/* Stop button: visible when running */}
          {isRunning && (
            <button
              className="btn btn-outline btn-sm"
              id="btn-stop"
              onClick={handleStop}
            >
              {'⏹'} Stop
            </button>
          )}
          {/* GPU Monitor toggle button: visible when SLURM detected */}
          {hasSlurm && (
            <button
              id="btn-show-gpu-monitor"
              className="btn btn-outline btn-sm"
              onClick={toggleGpuMonitor}
            >
              {gpuVisible ? t('gpu_monitor_hide') : '🖥 GPU Monitor'}
            </button>
          )}
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span
            id="stage-status"
            style={{ fontSize: '.82rem', color: 'var(--muted)' }}
          >
            {stageStatus}
          </span>
        </div>
      </div>

      {/* Experiment Configuration Card (Idea Card) */}
      <div className="card" style={{ marginBottom: 16 }} id="mon-idea-card">
        {state ? (
          <IdeaCardContent state={state} />
        ) : (
          <div style={{ fontSize: '.85rem', color: 'var(--muted)' }}>
            {t('select_active_project')}
          </div>
        )}
      </div>

      {/* Stats Grid */}
      <div className="grid-3" style={{ marginBottom: 16 }}>
        <div className="stat-box">
          <div className="stat-val" id="mon-node-count">
            {nodeCount}
          </div>
          <div className="stat-label" data-i18n="mon_nodes">
            {t('mon_nodes')}
          </div>
        </div>
        <div className="stat-box">
          <div className="stat-val" id="mon-best-metric">
            {metricDisplays.length > 1 ? (
              <div
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 2,
                  fontSize: '.8rem',
                }}
              >
                {metricDisplays.map((d) => (
                  <div key={d.key} style={{ lineHeight: 1.3 }}>
                    <span style={{ fontSize: '.65rem', color: 'var(--muted)' }}>
                      {d.key}
                    </span>
                    <br />
                    <strong style={{ fontSize: '.85rem' }}>
                      {d.value > 100 ? d.value.toFixed(0) : d.value.toFixed(2)}
                    </strong>
                  </div>
                ))}
              </div>
            ) : metricDisplays.length === 1 ? (
              metricDisplays[0].value > 0
                ? metricDisplays[0].value.toFixed(3)
                : '—'
            ) : (
              '—'
            )}
          </div>
          <div className="stat-label" data-i18n="mon_best">
            {t('mon_best')}
          </div>
        </div>
        <div className="stat-box">
          <div className="stat-val" id="mon-cost" title={costTooltip}>
            {costText}
          </div>
          <div className="stat-label">LLM Cost</div>
        </div>
      </div>

      {/* Resource Metrics Card */}
      {resourceMetrics && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="card-title">{t('resource_metrics')}</div>
          <div className="grid-3">
            <div className="stat-box">
              <div
                className="stat-val"
                style={{
                  color: resourceMetrics.process_count > 500
                    ? '#f44'
                    : resourceMetrics.process_count > 200
                      ? '#fa0'
                      : undefined,
                }}
              >
                {resourceMetrics.process_count}
              </div>
              <div className="stat-label">{t('res_process_count')}</div>
            </div>
            <div className="stat-box">
              <div className="stat-val">
                {resourceMetrics.memory_rss_mb >= 1024
                  ? `${(resourceMetrics.memory_rss_mb / 1024).toFixed(1)} GB`
                  : `${resourceMetrics.memory_rss_mb.toFixed(0)} MB`}
              </div>
              <div className="stat-label">{t('res_memory')}</div>
            </div>
            <div className="stat-box">
              <div
                className="stat-val"
                title={`1m: ${resourceMetrics.cpu_load_1m} / 5m: ${resourceMetrics.cpu_load_5m} / 15m: ${resourceMetrics.cpu_load_15m} (${resourceMetrics.cpu_count} cores)`}
              >
                {resourceMetrics.cpu_load_1m.toFixed(1)}
                <span style={{ fontSize: '.65rem', color: 'var(--muted)' }}>
                  {' '}/ {resourceMetrics.cpu_count}
                </span>
              </div>
              <div className="stat-label">{t('res_cpu_load')}</div>
            </div>
          </div>
          {resourceMetrics.experiment_pid && (
            <div style={{ fontSize: '.75rem', color: 'var(--muted)', marginTop: 6 }}>
              Experiment PID: {resourceMetrics.experiment_pid}
            </div>
          )}
        </div>
      )}

      {/* Node Tree Mini-View */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-title">{t('node_tree')}</div>
        <div
          id="tree-canvas-monitor"
          style={{ height: 400, display: 'flex', position: 'relative', overflow: 'hidden' }}
        >
          <TreeVisualization
            nodes={nodesData}
            selectedNodeId={null}
            onSelectNode={() => {}}
            borderless
          />
        </div>
      </div>

      {/* Live Logs */}
      <div className="card">
        <div
          className="card-title"
          style={{ display: 'flex', alignItems: 'center', gap: 8 }}
        >
          <span data-i18n="live_logs">{t('live_logs')}</span>
          <span id="log-status" className={logBadgeClass}>
            {logStatus}
          </span>
        </div>
        <div
          id="log-output"
          ref={logOutputRef}
          style={{ maxHeight: 400, overflow: 'auto' }}
        >
          {logLines.map((line, i) => (
            <div key={i} className="log-line">
              {line}
            </div>
          ))}
        </div>
        <div style={{ marginTop: 10, display: 'flex', gap: 8 }}>
          <button className="btn btn-outline btn-sm" onClick={startLogStream}>
            {'▶'} Connect
          </button>
          <button className="btn btn-outline btn-sm" onClick={clearLogs}>
            {'🗑'} Clear
          </button>
        </div>
      </div>
    </div>
  );
}

export default MonitorPage;
