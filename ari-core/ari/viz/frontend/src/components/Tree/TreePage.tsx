import { useCallback, useMemo, useState } from 'react';
import { useI18n } from '../../i18n';
import { useAppContext } from '../../context/AppContext';
import type { TreeNode } from '../../types';
import { TreeVisualization } from './TreeVisualization';
import { DetailPanel } from './DetailPanel';
import { FileExplorer } from './FileExplorer';

// ── Component ──

export function TreePage() {
  const { t } = useI18n();
  const { nodesData, refreshState, state, checkpoints } = useAppContext();

  const [filterStatus, setFilterStatus] = useState('');
  const [filterDepth, setFilterDepth] = useState('');
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  // Key to force TreeVisualization re-mount on Reset Layout
  const [layoutKey, setLayoutKey] = useState(0);
  // File explorer toggle
  const [showFileExplorer, setShowFileExplorer] = useState(true);

  // Use state.checkpoint_id when available; fallback to latest checkpoint from list
  const checkpointId = state?.checkpoint_id
    ?? (checkpoints.length > 0 ? checkpoints[0].id : null);

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

        {/* File explorer toggle */}
        <button
          onClick={() => setShowFileExplorer((v) => !v)}
          className="btn btn-outline btn-sm"
          style={{
            fontSize: '.8rem',
            background: showFileExplorer ? 'rgba(59,130,246,.15)' : undefined,
            borderColor: showFileExplorer ? '#3b82f6' : undefined,
          }}
        >
          {'\u{1F4C2}'} {t('file_explorer_btn')}
        </button>

        {/* Refresh button */}
        <button
          onClick={handleRefresh}
          className="btn btn-outline btn-sm"
          style={{ fontSize: '.8rem' }}
        >
          {'\u{1F504}'} Refresh
        </button>

        {/* Reset Layout button */}
        <button
          onClick={handleResetLayout}
          className="btn btn-outline btn-sm"
          style={{ fontSize: '.8rem' }}
        >
          {'\u21BA'} Reset Layout
        </button>
      </div>

      {/* Main area: file explorer + tree + detail panel */}
      <div
        style={{
          flex: 1,
          display: 'flex',
          overflow: 'hidden',
          padding: '0 20px 16px',
          minHeight: 0,
        }}
      >
        {/* File explorer (left sidebar, shown when toggled).
            When a node is selected, show that node's work_dir; else the
            full checkpoint directory. */}
        {showFileExplorer && (
          <FileExplorer
            checkpointId={checkpointId}
            nodeId={selectedNodeId}
            onClose={() => setShowFileExplorer(false)}
          />
        )}

        {/* Tree visualization (flex:1) */}
        <TreeVisualization
          key={layoutKey}
          nodes={filteredNodes}
          selectedNodeId={selectedNodeId}
          onSelectNode={handleSelectNode}
        />

        {/* Detail panel (320px, resizable, shown only when node selected) */}
        {selectedNode && (
          <DetailPanel
            node={selectedNode}
            allNodes={nodesData}
            checkpointId={checkpointId ?? undefined}
            onClose={handleCloseDetail}
          />
        )}
      </div>
    </div>
  );
}
