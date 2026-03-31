import { useCallback, useMemo, useState } from 'react';
import { useI18n } from '../../i18n';
import { useAppContext } from '../../context/AppContext';
import type { TreeNode } from '../../types';
import { TreeVisualization } from './TreeVisualization';
import { DetailPanel } from './DetailPanel';

// ── Component ──

export function TreePage() {
  const { t } = useI18n();
  const { nodesData, refreshState } = useAppContext();

  const [filterStatus, setFilterStatus] = useState('');
  const [filterDepth, setFilterDepth] = useState('');
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  // Key to force TreeVisualization re-mount on Reset Layout
  const [layoutKey, setLayoutKey] = useState(0);

  // Apply filters (same logic as original renderTreeD3)
  const filteredNodes = useMemo(() => {
    let nodes = nodesData.slice();
    if (filterStatus) {
      nodes = nodes.filter((n) => (n.status || '') === filterStatus);
    }
    if (filterDepth !== '') {
      const fd = parseInt(filterDepth, 10);
      if (fd === 3) {
        nodes = nodes.filter((n) => (n.depth || 0) >= 3);
      } else {
        nodes = nodes.filter((n) => (n.depth || 0) === fd);
      }
    }
    return nodes;
  }, [nodesData, filterStatus, filterDepth]);

  // Selected node object
  const selectedNode: TreeNode | null = useMemo(() => {
    if (!selectedNodeId) return null;
    return nodesData.find((n) => n.id === selectedNodeId) ?? null;
  }, [nodesData, selectedNodeId]);

  const handleSelectNode = useCallback((id: string) => {
    setSelectedNodeId(id);
  }, []);

  const handleCloseDetail = useCallback(() => {
    setSelectedNodeId(null);
  }, []);

  const handleRefresh = useCallback(() => {
    refreshState();
  }, [refreshState]);

  const handleResetLayout = useCallback(() => {
    setLayoutKey((k) => k + 1);
  }, []);

  return (
    <div
      className="page active"
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        padding: 0,
      }}
    >
      {/* Title + subtitle */}
      <div style={{ padding: '16px 20px 0' }}>
        <h1 style={{ margin: 0 }}>{t('tree_title')}</h1>
        <p className="subtitle" style={{ margin: '4px 0 12px' }}>
          {t('tree_subtitle')}
        </p>
      </div>

      {/* Filter controls bar */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: '0 20px 10px',
          flexWrap: 'wrap',
        }}
      >
        {/* Status filter */}
        <select
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value)}
          style={{
            background: 'var(--card-bg, rgba(30,41,59,.6))',
            color: 'var(--text)',
            border: '1px solid var(--border)',
            borderRadius: 6,
            padding: '4px 8px',
            fontSize: '.8rem',
          }}
        >
          <option value="">All Status</option>
          <option value="success">Completed</option>
          <option value="running">Running</option>
          <option value="failed">Failed</option>
        </select>

        {/* Depth filter */}
        <select
          value={filterDepth}
          onChange={(e) => setFilterDepth(e.target.value)}
          style={{
            background: 'var(--card-bg, rgba(30,41,59,.6))',
            color: 'var(--text)',
            border: '1px solid var(--border)',
            borderRadius: 6,
            padding: '4px 8px',
            fontSize: '.8rem',
          }}
        >
          <option value="">All Depths</option>
          <option value="0">Depth 0</option>
          <option value="1">Depth 1</option>
          <option value="2">Depth 2</option>
          <option value="3">Depth 3+</option>
        </select>

        {/* Refresh button */}
        <button
          onClick={handleRefresh}
          className="btn btn-outline btn-sm"
          style={{ fontSize: '.8rem' }}
        >
          {'🔄'} Refresh
        </button>

        {/* Reset Layout button */}
        <button
          onClick={handleResetLayout}
          className="btn btn-outline btn-sm"
          style={{ fontSize: '.8rem' }}
        >
          {'↺'} Reset Layout
        </button>
      </div>

      {/* Main area: tree + detail panel */}
      <div
        style={{
          flex: 1,
          display: 'flex',
          overflow: 'hidden',
          padding: '0 20px 16px',
          minHeight: 0,
        }}
      >
        {/* Tree visualization (flex:1) */}
        <TreeVisualization
          key={layoutKey}
          nodes={filteredNodes}
          selectedNodeId={selectedNodeId}
          onSelectNode={handleSelectNode}
        />

        {/* Detail panel (320px, resizable, shown only when node selected) */}
        {selectedNode && (
          <DetailPanel node={selectedNode} onClose={handleCloseDetail} />
        )}
      </div>
    </div>
  );
}
