// Phase C (v0.7.0) — extracted memory-entry render from DetailPanel.tsx.
// One memory record (own / inherited / global) → one card. The wrapping
// MemoryTab still lives in DetailPanel; this component is the most
// repeated, leaf-level visual chunk and benefits most from isolation.

import type { ReactNode } from 'react';

export interface MemoryEntryLike {
  node_id?: string;
  ts?: number | string;
  source?: string;
  text?: string;
  tags?: string[];
  metadata?: Record<string, unknown>;
}

interface Props {
  entry: MemoryEntryLike;
  variant: 'own' | 'inherited' | 'global';
  ancestorIndex?: number;     // depth in the lineage chain, -1 if not in chain
  labels: {
    fromNode: string;
    sourceMcp: string;
    sourceFile: string;
    sourceGlobal: string;
  };
}

export function MemoryEntryCard({
  entry,
  variant,
  ancestorIndex = -1,
  labels,
}: Props) {
  const isOwn = variant === 'own';
  const isGlobal = variant === 'global';

  const borderColor =
    isGlobal ? '#f59e0b'
    : isOwn ? '#60a5fa'
    : 'var(--border)';
  const background =
    isGlobal ? 'rgba(245,158,11,.06)'
    : isOwn ? 'rgba(59,130,246,.06)'
    : 'rgba(255,255,255,.03)';
  const headerColor =
    isGlobal ? '#f59e0b'
    : isOwn ? '#60a5fa'
    : 'var(--muted)';

  const tsStr = entry.ts
    ? new Date(Number(entry.ts) * 1000).toLocaleString()
    : '';

  const headerExtras: ReactNode[] = [];
  if (isGlobal) {
    headerExtras.push(
      <span key="src" style={{ color: headerColor }}>
        {labels.sourceGlobal}
      </span>,
    );
    if (entry.tags && entry.tags.length > 0) {
      headerExtras.push(<span key="tags">tags: {entry.tags.join(', ')}</span>);
    }
  } else {
    headerExtras.push(
      <span
        key="src-node"
        style={{ fontFamily: 'monospace', color: headerColor }}
      >
        {labels.fromNode} {entry.node_id || '—'}
        {ancestorIndex >= 0 && ` [${ancestorIndex}]`}
      </span>,
    );
    headerExtras.push(
      <span key="src-kind">
        {entry.source === 'mcp' ? labels.sourceMcp : labels.sourceFile}
      </span>,
    );
    if (
      entry.metadata
      && typeof entry.metadata === 'object'
      && Object.keys(entry.metadata).length > 0
    ) {
      headerExtras.push(
        <span key="md">
          {Object.entries(entry.metadata)
            .map(([k, v]) => `${k}=${String(v)}`)
            .join(' ')}
        </span>,
      );
    }
  }
  if (tsStr) headerExtras.push(<span key="ts">{tsStr}</span>);

  return (
    <div
      style={{
        borderLeft: `3px solid ${borderColor}`,
        background,
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
        {headerExtras}
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
        {entry.text}
      </div>
    </div>
  );
}
