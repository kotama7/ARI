// ARI Dashboard – DetailPanel "MCP Trace" tab.
// Extracted verbatim from DetailPanel.tsx (refactor req 15): the trace-tab JSX
// block. The `activeTab === 'trace' && traceLog.length > 0` guard stays in the
// container; this renders the block body for the given trace_log + tool names.

interface TraceTabProps {
  traceLog: string[];
  toolNames: string[];
}

export function TraceTab({ traceLog, toolNames }: TraceTabProps) {
  return (
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
  );
}
