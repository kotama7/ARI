import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useI18n } from '../../i18n';
import type { TreeNode } from '../../types';
import { fetchCheckpointMemory, type MemoryEntry } from '../../services/api';

// ── Colour constants (same as original dashboard.js) ──

const LABEL_COLORS: Record<string, string> = {
  draft: '#3b82f6',
  improve: '#8b5cf6',
  ablation: '#f59e0b',
  debug: '#ef4444',
  validation: '#10b981',
};

// ── Types ──

type TabName = 'overview' | 'trace' | 'code' | 'memory' | 'raw';

interface DetailPanelProps {
  node: TreeNode | null;
  allNodes?: TreeNode[];
  checkpointId?: string;
  onClose: () => void;
}

// ── Component ──

export function DetailPanel({ node, allNodes, checkpointId, onClose }: DetailPanelProps) {
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

  // ── Memory data ──
  const [memEntries, setMemEntries] = useState<MemoryEntry[] | null>(null);
  const [globalEntries, setGlobalEntries] = useState<MemoryEntry[]>([]);
  const [memLoading, setMemLoading] = useState(false);
  const [memError, setMemError] = useState<string | null>(null);

  // Ancestor chain (root → ... → self) computed from parent_id walk
  const ancestorIds = useMemo<string[]>(() => {
    if (!node || !allNodes) return node ? [node.id] : [];
    const byId = new Map<string, TreeNode>();
    allNodes.forEach((n) => byId.set(n.id, n));
    const chain: string[] = [];
    let cur: TreeNode | undefined = byId.get(node.id);
    const seen = new Set<string>();
    while (cur && !seen.has(cur.id)) {
      seen.add(cur.id);
      chain.unshift(cur.id);
      const pid = cur.parent_id;
      cur = pid ? byId.get(pid) : undefined;
    }
    return chain;
  }, [node, allNodes]);

  useEffect(() => {
    if (!checkpointId || !node) {
      setMemEntries(null);
      return;
    }
    let aborted = false;
    setMemLoading(true);
    setMemError(null);
    fetchCheckpointMemory(checkpointId)
      .then((r) => {
        if (aborted) return;
        if (r.error) {
          setMemError(r.error);
          setMemEntries([]);
          setGlobalEntries([]);
        } else {
          setMemEntries(r.entries || []);
          setGlobalEntries(r.global || []);
        }
      })
      .catch((e) => {
        if (aborted) return;
        setMemError(String(e));
        setMemEntries([]);
      })
      .finally(() => {
        if (!aborted) setMemLoading(false);
      });
    return () => {
      aborted = true;
    };
  }, [checkpointId, node?.id]);

  const visibleMemory = useMemo(() => {
    if (!memEntries || !node) return [] as MemoryEntry[];
    const allowed = new Set(ancestorIds);
    return memEntries.filter((e) => allowed.has(e.node_id));
  }, [memEntries, node, ancestorIds]);

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
            {tabBtn('memory', `🧠 ${t('memory_tab')}`, visibleMemory.length + globalEntries.length)}
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

          {/* Memory tab */}
          {activeTab === 'memory' && (
            <div>
              {memLoading && (
                <div style={{ fontSize: '.72rem', color: 'var(--muted)' }}>
                  Loading memory…
                </div>
              )}
              {memError && (
                <div style={{ fontSize: '.72rem', color: 'var(--red)' }}>
                  {memError}
                </div>
              )}
              {!memLoading &&
                !memError &&
                visibleMemory.length === 0 &&
                globalEntries.length === 0 && (
                  <div style={{ fontSize: '.75rem', color: 'var(--muted)' }}>
                    {t('memory_empty')}
                  </div>
                )}
              {!memLoading && visibleMemory.length > 0 && (
                <div
                  style={{
                    fontSize: '.72rem',
                    color: 'var(--muted)',
                    marginBottom: 6,
                  }}
                >
                  <span className="badge badge-blue" style={{ marginRight: 4 }}>
                    {t('memory_own')}
                  </span>
                  <span className="badge badge-muted">
                    {t('memory_inherited')}
                  </span>
                </div>
              )}
              {globalEntries.length > 0 && (
                <div style={{ marginBottom: 8 }}>
                  <div
                    style={{
                      fontSize: '.7rem',
                      color: 'var(--muted)',
                      textTransform: 'uppercase',
                      letterSpacing: '.04em',
                      margin: '8px 0 4px',
                    }}
                  >
                    {t('memory_global_header')} ({globalEntries.length})
                  </div>
                  {globalEntries.map((e, i) => (
                    <div
                      key={`g-${i}`}
                      style={{
                        borderLeft: '3px solid #f59e0b',
                        background: 'rgba(245,158,11,.06)',
                        padding: '6px 8px',
                        margin: '4px 0',
                        borderRadius: 3,
                      }}
                    >
                      <div
                        style={{
                          fontSize: '.68rem',
                          color: 'var(--muted)',
                          display: 'flex',
                          gap: 6,
                          flexWrap: 'wrap',
                          marginBottom: 3,
                        }}
                      >
                        <span style={{ color: '#f59e0b' }}>
                          {t('memory_source_global')}
                        </span>
                        {e.tags && e.tags.length > 0 && (
                          <span>tags: {e.tags.join(', ')}</span>
                        )}
                        {e.ts && (
                          <span>
                            {new Date(Number(e.ts) * 1000).toLocaleString()}
                          </span>
                        )}
                      </div>
                      <div
                        style={{
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-word',
                          fontSize: '.75rem',
                          maxHeight: 160,
                          overflow: 'auto',
                        }}
                      >
                        {e.text}
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {visibleMemory.map((e, i) => {
                const own = e.node_id === node.id;
                const depthIdx = ancestorIds.indexOf(e.node_id);
                const tsStr = e.ts
                  ? new Date(Number(e.ts) * 1000).toLocaleString()
                  : '';
                return (
                  <div
                    key={i}
                    style={{
                      borderLeft: `3px solid ${own ? '#60a5fa' : 'var(--border)'}`,
                      background: own
                        ? 'rgba(59,130,246,.06)'
                        : 'rgba(255,255,255,.03)',
                      padding: '6px 8px',
                      margin: '4px 0',
                      borderRadius: 3,
                    }}
                  >
                    <div
                      style={{
                        fontSize: '.68rem',
                        color: 'var(--muted)',
                        display: 'flex',
                        gap: 6,
                        flexWrap: 'wrap',
                        marginBottom: 3,
                      }}
                    >
                      <span
                        style={{
                          fontFamily: 'monospace',
                          color: own ? '#60a5fa' : 'var(--muted)',
                        }}
                      >
                        {t('memory_from_node')} {e.node_id || '—'}
                        {depthIdx >= 0 && ` [${depthIdx}]`}
                      </span>
                      <span>
                        {e.source === 'mcp'
                          ? t('memory_source_mcp')
                          : t('memory_source_file')}
                      </span>
                      {e.metadata &&
                        typeof e.metadata === 'object' &&
                        Object.keys(e.metadata).length > 0 && (
                          <span>
                            {Object.entries(e.metadata)
                              .map(([k, v]) => `${k}=${String(v)}`)
                              .join(' ')}
                          </span>
                        )}
                      {tsStr && <span>{tsStr}</span>}
                    </div>
                    <div
                      style={{
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                        fontSize: '.75rem',
                        maxHeight: 160,
                        overflow: 'auto',
                      }}
                    >
                      {e.text}
                    </div>
                  </div>
                );
              })}
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
