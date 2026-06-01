// ARI Dashboard – Monitor page (React port of page-monitor from dashboard.js)

import { useCallback, useEffect, useRef, useState } from 'react';
import { useI18n } from '../../i18n';
import { useAppContext } from '../../context/AppContext';
import {
  runStage as apiRunStage,
  stopExperiment,
  detectScheduler,
  fetchResourceMetrics,
} from '../../services/api';
import type { ResourceMetrics } from '../../types';
import PhaseStepper from './PhaseStepper';
import GpuMonitor from './GpuMonitor';
import { TreeVisualization } from '../Tree/TreeVisualization';
import { computeBestMetrics, IdeaCardContent } from './monitorSections';

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
      // Justified direct-fetch exception (req 02): server-sent log stream read
      // via res.body.getReader(); not a JSON request, cannot use services/api.ts.
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
