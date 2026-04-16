import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useI18n } from '../../i18n';

// ── Types ──

export interface FileNode {
  name: string;
  path: string;
  type: 'file' | 'dir';
  size?: number;
  ext?: string;
  readable?: boolean;
  children?: FileNode[];
}

interface FileExplorerProps {
  checkpointId: string | null;
  nodeId?: string | null;
  onClose: () => void;
}

// ── Helpers ──

const EXT_ICONS: Record<string, string> = {
  '.py': '\u{1F40D}',
  '.json': '{ }',
  '.yaml': '\u2699',
  '.yml': '\u2699',
  '.tex': '\u{1F4DD}',
  '.md': '\u{1F4C4}',
  '.txt': '\u{1F4C4}',
  '.csv': '\u{1F4CA}',
  '.tsv': '\u{1F4CA}',
  '.log': '\u{1F4CB}',
  '.sh': '\u{1F4BB}',
  '.bash': '\u{1F4BB}',
  '.bib': '\u{1F4DA}',
  '.f90': '\u{1F9EE}',
  '.c': '\u{1F9EE}',
  '.cpp': '\u{1F9EE}',
  '.h': '\u{1F9EE}',
  '.toml': '\u2699',
  '.cfg': '\u2699',
  '.ini': '\u2699',
  '.env': '\u{1F511}',
  '.png': '\u{1F5BC}',
  '.jpg': '\u{1F5BC}',
  '.pdf': '\u{1F4D1}',
};

function getFileIcon(node: FileNode): string {
  if (node.type === 'dir') return '';
  return EXT_ICONS[node.ext || ''] || '\u{1F4C4}';
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ── Tree node row ──

interface TreeRowProps {
  node: FileNode;
  depth: number;
  expanded: Set<string>;
  onToggle: (path: string) => void;
  onFileClick: (path: string) => void;
  selectedFile: string | null;
}

function TreeRow({ node, depth, expanded, onToggle, onFileClick, selectedFile }: TreeRowProps) {
  const isDir = node.type === 'dir';
  const isOpen = expanded.has(node.path);
  const isSelected = selectedFile === node.path;

  const handleClick = useCallback(() => {
    if (isDir) {
      onToggle(node.path);
    } else if (node.readable) {
      onFileClick(node.path);
    }
  }, [isDir, node.path, node.readable, onToggle, onFileClick]);

  return (
    <>
      <div
        onClick={handleClick}
        style={{
          display: 'flex',
          alignItems: 'center',
          padding: '2px 6px 2px 0',
          paddingLeft: depth * 16 + 6,
          cursor: isDir || node.readable ? 'pointer' : 'default',
          background: isSelected ? 'rgba(59,130,246,.2)' : 'transparent',
          borderLeft: isSelected ? '2px solid #3b82f6' : '2px solid transparent',
          fontSize: '.78rem',
          lineHeight: '22px',
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          opacity: !isDir && !node.readable ? 0.45 : 1,
          color: 'var(--text)',
        }}
        title={`${node.path}${node.size != null ? ` (${formatSize(node.size)})` : ''}`}
        onMouseEnter={(e) => {
          if (!isSelected) (e.currentTarget.style.background = 'rgba(255,255,255,.05)');
        }}
        onMouseLeave={(e) => {
          if (!isSelected) (e.currentTarget.style.background = 'transparent');
        }}
      >
        {/* Chevron / spacer */}
        <span style={{ width: 16, flexShrink: 0, textAlign: 'center', fontSize: '.7rem', color: 'var(--muted)' }}>
          {isDir ? (isOpen ? '\u25BE' : '\u25B8') : ''}
        </span>
        {/* Icon */}
        <span style={{ width: 18, flexShrink: 0, textAlign: 'center', fontSize: '.72rem' }}>
          {isDir ? (isOpen ? '\u{1F4C2}' : '\u{1F4C1}') : getFileIcon(node)}
        </span>
        {/* Name */}
        <span style={{
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          fontWeight: isDir ? 600 : 400,
          color: isDir ? 'var(--text)' : (node.readable ? 'var(--text)' : 'var(--muted)'),
        }}>
          {node.name}
        </span>
        {/* File size */}
        {!isDir && node.size != null && (
          <span style={{ marginLeft: 'auto', paddingLeft: 8, fontSize: '.68rem', color: 'var(--muted)', flexShrink: 0 }}>
            {formatSize(node.size)}
          </span>
        )}
      </div>
      {/* Children (if expanded) */}
      {isDir && isOpen && node.children && node.children.map((child) => (
        <TreeRow
          key={child.path}
          node={child}
          depth={depth + 1}
          expanded={expanded}
          onToggle={onToggle}
          onFileClick={onFileClick}
          selectedFile={selectedFile}
        />
      ))}
    </>
  );
}

// ── Main FileExplorer Component ──

export function FileExplorer({ checkpointId, nodeId, onClose }: FileExplorerProps) {
  const { t } = useI18n();
  const [tree, setTree] = useState<FileNode[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [fileLoading, setFileLoading] = useState(false);
  const [width, setWidth] = useState(280);
  const panelRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);
  const startX = useRef(0);
  const startW = useRef(0);

  // Load file tree (node work_dir when nodeId is set, else full checkpoint)
  useEffect(() => {
    if (!checkpointId) return;
    setLoading(true);
    setError(null);
    setSelectedFile(null);
    setFileContent(null);
    const qs = nodeId ? `?node_id=${encodeURIComponent(nodeId)}` : '';
    fetch(`/api/checkpoint/${encodeURIComponent(checkpointId)}/filetree${qs}`)
      .then((r) => r.json())
      .then((data) => {
        if (data.error) {
          setError(data.error);
          setTree([]);
        } else {
          setTree(data.tree || []);
          // Auto-expand top level
          const topDirs = (data.tree || []).filter((n: FileNode) => n.type === 'dir').map((n: FileNode) => n.path);
          setExpanded(new Set(topDirs));
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [checkpointId, nodeId]);

  // Toggle directory expanded/collapsed
  const handleToggle = useCallback((path: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, []);

  // Load file content on click
  const handleFileClick = useCallback((path: string) => {
    if (!checkpointId) return;
    setSelectedFile(path);
    setFileContent(null);
    setFileLoading(true);
    const nodeQs = nodeId ? `&node_id=${encodeURIComponent(nodeId)}` : '';
    fetch(`/api/checkpoint/${encodeURIComponent(checkpointId)}/filecontent?path=${encodeURIComponent(path)}${nodeQs}`)
      .then((r) => r.json())
      .then((data) => {
        if (data.error) {
          setFileContent(`Error: ${data.error}`);
        } else {
          setFileContent(data.content || '');
        }
      })
      .catch((e) => setFileContent(`Error: ${e.message}`))
      .finally(() => setFileLoading(false));
  }, [checkpointId, nodeId]);

  // Close file viewer
  const handleCloseFile = useCallback(() => {
    setSelectedFile(null);
    setFileContent(null);
  }, []);

  // ── Resize drag handlers ──
  const onMouseDown = useCallback((e: React.MouseEvent) => {
    dragging.current = true;
    startX.current = e.clientX;
    startW.current = panelRef.current?.offsetWidth ?? 280;
    e.preventDefault();
  }, []);

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (!dragging.current) return;
      const dx = e.clientX - startX.current;
      const newW = Math.max(180, Math.min(startW.current + dx, window.innerWidth * 0.4));
      setWidth(newW);
    };
    const onMouseUp = () => { dragging.current = false; };
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
    return () => {
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
    };
  }, []);

  return (
    <div
      ref={panelRef}
      style={{
        width,
        minWidth: width,
        display: 'flex',
        flexDirection: 'column',
        borderRight: '1px solid var(--border)',
        background: 'var(--bg)',
        overflow: 'hidden',
        position: 'relative',
      }}
    >
      {/* Resize handle (right edge) */}
      <div
        onMouseDown={onMouseDown}
        style={{
          position: 'absolute',
          top: 0,
          right: 0,
          width: 5,
          height: '100%',
          cursor: 'col-resize',
          zIndex: 10,
        }}
      />

      {/* Header */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '8px 10px 6px',
          borderBottom: '1px solid var(--border)',
          flexShrink: 0,
        }}
      >
        <span style={{ fontWeight: 700, fontSize: '.8rem', display: 'flex', alignItems: 'center', gap: 4 }}>
          {t('file_explorer_title')}
        </span>
        <button
          onClick={onClose}
          style={{
            background: 'none',
            border: 'none',
            color: 'var(--muted)',
            cursor: 'pointer',
            fontSize: '1rem',
            padding: '0 4px',
          }}
        >
          {'\u2715'}
        </button>
      </div>

      {/* File tree or file content */}
      {selectedFile && fileContent !== null ? (
        // File content viewer
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {/* File header */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            padding: '6px 10px',
            borderBottom: '1px solid var(--border)',
            fontSize: '.75rem',
            color: 'var(--muted)',
            flexShrink: 0,
          }}>
            <button
              onClick={handleCloseFile}
              style={{
                background: 'none',
                border: '1px solid var(--border)',
                color: 'var(--text)',
                cursor: 'pointer',
                fontSize: '.7rem',
                padding: '1px 6px',
                borderRadius: 4,
              }}
            >
              {'\u2190'} {t('file_explorer_back')}
            </button>
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontFamily: 'monospace' }}>
              {selectedFile}
            </span>
          </div>
          {/* Content */}
          <div style={{ flex: 1, overflow: 'auto', padding: 0 }}>
            {fileLoading ? (
              <div style={{ padding: 16, color: 'var(--muted)', fontSize: '.8rem' }}>Loading...</div>
            ) : (
              <pre style={{
                margin: 0,
                padding: '8px 10px',
                fontSize: '.72rem',
                lineHeight: 1.5,
                fontFamily: 'monospace',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
                color: 'var(--text)',
                background: 'transparent',
              }}>
                {fileContent}
              </pre>
            )}
          </div>
        </div>
      ) : (
        // Tree view
        <div style={{ flex: 1, overflow: 'auto', padding: '4px 0' }}>
          {loading && (
            <div style={{ padding: 16, color: 'var(--muted)', fontSize: '.8rem' }}>Loading...</div>
          )}
          {error && (
            <div style={{ padding: 16, color: 'var(--red, #ef4444)', fontSize: '.8rem' }}>{error}</div>
          )}
          {!loading && !error && tree.length === 0 && (
            <div style={{ padding: 16, color: 'var(--muted)', fontSize: '.8rem' }}>
              {t('file_explorer_empty')}
            </div>
          )}
          {tree.map((node) => (
            <TreeRow
              key={node.path}
              node={node}
              depth={0}
              expanded={expanded}
              onToggle={handleToggle}
              onFileClick={handleFileClick}
              selectedFile={selectedFile}
            />
          ))}
        </div>
      )}
    </div>
  );
}
