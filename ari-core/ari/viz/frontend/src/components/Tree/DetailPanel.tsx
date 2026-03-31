import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useI18n } from '../../i18n';
import type { TreeNode } from '../../types';

// ── Colour constants (same as original dashboard.js) ──

const LABEL_COLORS: Record<string, string> = {
  draft: '#3b82f6',
  improve: '#8b5cf6',
  ablation: '#f59e0b',
  debug: '#ef4444',
  validation: '#10b981',
};

// ── Types ──

type TabName = 'overview' | 'trace' | 'code' | 'raw';

interface DetailPanelProps {
  node: TreeNode | null;
  onClose: () => void;
}

// ── Component ──

export function DetailPanel({ node, onClose }: DetailPanelProps) {
  const { t } = useI18n();
  const [width, setWidth] = useState(320);
  const [activeTab, setActiveTab] = useState<TabName>('overview');
  const panelRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);
  const startX = useRef(0);
  const startW = useRef(0);

  // Reset tab when node changes
  useEffect(() => {
    setActiveTab('overview');
  }, [node?.id]);

  // ── Resize drag handlers ──

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    dragging.current = true;
    startX.current = e.clientX;
    startW.current = panelRef.current?.offsetWidth ?? 320;
    e.preventDefault();
  }, []);

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (!dragging.current) return;
      const dx = startX.current - e.clientX; // drag left => wider
      const newW = Math.max(180, Math.min(startW.current + dx, window.innerWidth * 0.6));
      setWidth(newW);
    };
    const onMouseUp = () => {
      dragging.current = false;
    };
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
    return () => {
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
    };
  }, []);

  if (!node) return null;

  // ── Derived data ──

  const lbl = (node.label || node.node_type || '').toLowerCase();
  const col = LABEL_COLORS[lbl] || 'var(--muted)';
  const m = node.metrics || {};
  const mKeys = Object.keys(m).filter((k) => !k.startsWith('_'));
  const score =
    node.scientific_score ??
    (m as Record<string, unknown>)._scientific_score ??
    null;

  const evalText = node.eval_summary || node.hypothesis || node.description || node.name || '';

  // Extract tool names + code snippets from trace_log
  const traceLog = node.trace_log || [];
  const toolNames: string[] = [];
  const codeSnippets: string[] = [];

  traceLog.forEach((entry) => {
    const s = typeof entry === 'string' ? entry : JSON.stringify(entry);
    const mm = s.match(/^[->]\s*(\w+)\(/);
    if (mm && !toolNames.includes(mm[1])) toolNames.push(mm[1]);

    // Extract run_code snippets
    const cm = s.match(/→\s*run_code\((.+)/);
    if (cm) {
      try {
        const arg = JSON.parse(cm[1].replace(/\)$/, '').trim());
        if (arg.code) codeSnippets.push(arg.code);
      } catch {
        const cm2 = s.match(/"code":\s*"((?:[^"\\]|\\[\s\S])*?)"/);
        if (cm2) {
          try {
            codeSnippets.push(JSON.parse('"' + cm2[1] + '"'));
          } catch {
            codeSnippets.push(cm2[1].replace(/\\n/g, '\n'));
          }
        }
      }
    }
  });

  // ── Status badge variant ──

  const statusVariant =
    node.status === 'success'
      ? 'green'
      : node.status === 'running'
        ? 'blue'
        : node.status === 'failed'
          ? 'red'
          : 'muted';

  // ── Tab button style ──

  const tabBtn = (tab: TabName, label: string, count?: number) => {
    const active = activeTab === tab;
    return (
      <button
        key={tab}
        onClick={() => setActiveTab(tab)}
        style={{
          background: active ? 'rgba(255,255,255,.12)' : 'none',
          border: '1px solid var(--border)',
          color: active ? 'var(--text)' : 'var(--muted)',
          padding: '3px 10px',
          borderRadius: 5,
          cursor: 'pointer',
          fontSize: '.75rem',
        }}
      >
        {label}
        {count != null ? ` (${count})` : ''}
      </button>
    );
  };

  return (
    <div
      ref={panelRef}
      className="detail-panel open"
      style={{
        width,
        minWidth: width,
        position: 'relative',
        display: 'flex',
        flexDirection: 'column',
        borderLeft: '1px solid var(--border)',
        background: 'var(--bg)',
        overflow: 'hidden',
      }}
    >
      {/* Resize handle (left edge) */}
      <div
        onMouseDown={onMouseDown}
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          width: 5,
          height: '100%',
          cursor: 'col-resize',
          zIndex: 10,
        }}
      />

      {/* Header with close button */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '10px 14px 6px',
          borderBottom: '1px solid var(--border)',
        }}
      >
        <span style={{ fontWeight: 700, fontSize: '.85rem' }}>
          {t('node_detail')}
        </span>
        <button
          onClick={onClose}
          style={{
            background: 'none',
            border: 'none',
            color: 'var(--muted)',
            cursor: 'pointer',
            fontSize: '1.1rem',
            padding: '0 4px',
          }}
        >
          {'✕'}
        </button>
      </div>

      {/* Scrollable content */}
      <div style={{ flex: 1, overflow: 'auto', padding: '10px 14px' }}>
        {/* Status / depth / score badges */}
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
          {node.status && (
            <span className={`badge badge-${statusVariant}`}>{node.status}</span>
          )}
          {node.depth != null && (
            <span className="badge badge-muted">depth: {node.depth}</span>
          )}
          {score != null && (
            <span className="badge badge-blue">
              score: {Number(score).toFixed(3)}
            </span>
          )}
          {node.has_real_data && (
            <span className="badge badge-green">real data</span>
          )}
        </div>

        {/* ID */}
        <div className="detail-field">
          <div className="detail-key">ID</div>
          <div
            className="detail-val"
            style={{ fontFamily: 'monospace', fontSize: '.75rem' }}
          >
            {node.id}
          </div>
        </div>

        {/* Label (colored) */}
        <div className="detail-field">
          <div className="detail-key">LABEL</div>
          <div className="detail-val">
            <strong style={{ color: col }}>{lbl || '—'}</strong>
          </div>
        </div>

        {/* Eval / Hypothesis text */}
        {evalText && (
          <div className="detail-field">
            <div className="detail-key">{'📝'} EVAL / HYPOTHESIS</div>
            <div
              className="detail-val"
              style={{
                whiteSpace: 'pre-wrap',
                maxHeight: 180,
                overflow: 'auto',
                fontSize: '.78rem',
              }}
            >
              {String(evalText)}
            </div>
          </div>
        )}

        {/* Metrics table */}
        {mKeys.length > 0 && (
          <div className="detail-field">
            <div className="detail-key">{'📊'} METRICS</div>
            <div className="detail-val">
              <table
                style={{
                  width: '100%',
                  borderCollapse: 'collapse',
                  fontSize: '.8rem',
                }}
              >
                <tbody>
                  {mKeys.map((k) => {
                    const v = (m as Record<string, unknown>)[k];
                    const vs =
                      typeof v === 'number'
                        ? v.toFixed(4)
                        : JSON.stringify(v);
                    return (
                      <tr key={k}>
                        <td style={{ color: 'var(--muted)', padding: '2px 8px 2px 0' }}>
                          {k}
                        </td>
                        <td>
                          <strong>{vs}</strong>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Error log */}
        {node.error_log && (
          <div className="detail-field">
            <div className="detail-key" style={{ color: 'var(--red)' }}>
              {'❌'} ERROR
            </div>
            <div className="detail-val">
              <pre
                className="code"
                style={{
                  maxHeight: 100,
                  overflow: 'auto',
                  color: 'var(--red)',
                  fontSize: '.72rem',
                }}
              >
                {String(node.error_log).slice(0, 800)}
              </pre>
            </div>
          </div>
        )}

        {/* Timestamps */}
        {(node.created_at || node.completed_at) && (
          <div style={{ fontSize: '.72rem', color: 'var(--muted)', marginTop: 6 }}>
            {node.created_at && (
              <>Created: {new Date(Number(node.created_at) * 1000).toLocaleString()}{'  '}</>
            )}
            {node.completed_at && (
              <>Done: {new Date(Number(node.completed_at) * 1000).toLocaleString()}</>
            )}
          </div>
        )}

        {/* ── Tabs ── */}
        <div style={{ marginTop: 6 }}>
          <div style={{ display: 'flex', gap: 4, marginBottom: 6, flexWrap: 'wrap' }}>
            {tabBtn('overview', '📋 Overview')}
            {traceLog.length > 0 && tabBtn('trace', '🔧 MCP Trace', traceLog.length)}
            {codeSnippets.length > 0 && tabBtn('code', '💻 Code', codeSnippets.length)}
            {tabBtn('raw', '{ } Raw')}
          </div>

          {/* Overview tab (empty content area, matches original) */}
          {activeTab === 'overview' && <div />}

          {/* MCP Trace tab */}
          {activeTab === 'trace' && traceLog.length > 0 && (
            <div>
              {/* Tool pills */}
              <div style={{ marginBottom: 6, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                {toolNames.map((tn) => (
                  <span
                    key={tn}
                    style={{
                      fontSize: '.7rem',
                      padding: '1px 7px',
                      borderRadius: 6,
                      background: 'rgba(59,130,246,.15)',
                      color: '#60a5fa',
                    }}
                  >
                    {tn}
                  </span>
                ))}
              </div>
              <pre
                className="code"
                style={{
                  maxHeight: 300,
                  overflow: 'auto',
                  fontSize: '.7rem',
                  lineHeight: 1.4,
                }}
              >
                {traceLog.map((entry, i) => {
                  const s =
                    typeof entry === 'string' ? entry : JSON.stringify(entry, null, 2);
                  const lineCol = s.startsWith('→') || s.startsWith('->')
                    ? '#60a5fa'
                    : s.startsWith('  ←') || s.startsWith('  <-')
                      ? '#86efac'
                      : 'inherit';
                  return (
                    <span key={i} style={{ color: lineCol }}>
                      {s}{'\n'}
                    </span>
                  );
                })}
              </pre>
            </div>
          )}

          {/* Code tab */}
          {activeTab === 'code' && codeSnippets.length > 0 && (
            <div>
              {codeSnippets.map((c, i) => (
                <React.Fragment key={i}>
                  <div
                    style={{
                      fontSize: '.72rem',
                      color: 'var(--muted)',
                      margin: '6px 0 2px',
                    }}
                  >
                    --- Snippet {i + 1} / {codeSnippets.length} ---
                  </div>
                  <pre
                    className="code"
                    style={{
                      maxHeight: 400,
                      overflow: 'auto',
                      fontSize: '.72rem',
                      lineHeight: 1.5,
                      marginBottom: 8,
                    }}
                  >
                    {c}
                  </pre>
                </React.Fragment>
              ))}
            </div>
          )}

          {/* Raw JSON tab */}
          {activeTab === 'raw' && (
            <div>
              <pre
                className="code"
                style={{ maxHeight: 350, overflow: 'auto', fontSize: '.68rem' }}
              >
                {JSON.stringify(node, null, 2).slice(0, 6000)}
              </pre>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
