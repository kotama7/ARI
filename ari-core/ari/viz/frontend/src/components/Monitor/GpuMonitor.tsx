// ARI Dashboard – GPU Monitor card (React port of gpu monitor from dashboard.js)

import { useCallback, useEffect, useState } from 'react';
import { useI18n } from '../../i18n';
import { fetchGpuMonitor, gpuMonitorAction } from '../../services/api';

// ── Component ─────────────────────────────────────

export function GpuMonitor() {
  const { t } = useI18n();
  const [running, setRunning] = useState(false);
  const [_pid, setPid] = useState<number | null>(null);
  const [_ollamaHost, setOllamaHost] = useState<string>('');
  const [log, setLog] = useState<string>('—');
  const [statusText, setStatusText] = useState<string>('—');

  // ── Refresh status ───────────────────────────

  const refresh = useCallback(async () => {
    try {
      const r = await fetchGpuMonitor();
      setRunning(!!r.running);
      setPid(r.pid ?? null);
      setOllamaHost(r.ollama_host ?? '');
      if (r.running) {
        setStatusText(
          `🟢 Running (PID: ${r.pid}) | OLLAMA_HOST: ${r.ollama_host ?? '—'}`,
        );
      } else {
        setStatusText('⬛ Stopped');
      }
      if (r.log) setLog(r.log);
    } catch {
      setRunning(false);
      setStatusText('⬛ Stopped');
    }
  }, []);

  // Initial fetch
  useEffect(() => {
    refresh();
  }, [refresh]);

  // ── Start / Stop ─────────────────────────────

  const handleStart = useCallback(async () => {
    if (!window.confirm(t('gpu_confirm'))) return;
    setStatusText(t('gpu_starting'));
    try {
      await gpuMonitorAction('start');
    } catch {
      // ignore
    }
    setTimeout(refresh, 1000);
  }, [t, refresh]);

  const handleStop = useCallback(async () => {
    setStatusText(t('gpu_stopping'));
    try {
      await gpuMonitorAction('stop');
    } catch {
      // ignore
    }
    setTimeout(refresh, 1000);
  }, [t, refresh]);

  // ── Render ───────────────────────────────────

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="card-title">{'🖥️'} GPU Monitor (SLURM Auto-Resubmit)</div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
        <span
          style={{
            fontSize: '.8rem',
            color: running ? '#22c55e' : 'var(--muted)',
          }}
        >
          {statusText}
        </span>
        <button
          onClick={handleStart}
          style={{
            fontSize: '.75rem',
            padding: '3px 10px',
            background: 'var(--accent)',
            color: '#fff',
            border: 'none',
            borderRadius: 4,
            cursor: 'pointer',
          }}
        >
          {t('gpu_start')}
        </button>
        <button
          onClick={handleStop}
          style={{
            fontSize: '.75rem',
            padding: '3px 10px',
            background: 'var(--border)',
            color: 'var(--text)',
            border: 'none',
            borderRadius: 4,
            cursor: 'pointer',
          }}
        >
          {t('gpu_stop')}
        </button>
      </div>
      <pre
        style={{
          fontSize: '.72rem',
          background: 'var(--bg)',
          border: '1px solid var(--border)',
          borderRadius: 4,
          padding: 8,
          maxHeight: 120,
          overflowY: 'auto',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-all',
        }}
      >
        {log}
      </pre>
    </div>
  );
}

export default GpuMonitor;
