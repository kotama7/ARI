// ARI Dashboard – Results page "paper workspace" (Overleaf-like editor).
// Extracted from ResultsPage.tsx renderPaper (refactor req 15, optional §3, the
// most state-coupled seam). Its state is entangled with the container's
// loadResults/loadFiles/openFile data effects, so — unlike EarSection — the state
// STAYS in the container (incl. the activeAbsPath mid-body declaration and its
// data-reset effect) and is threaded in as a prop bundle. Only the render code
// moves: the pure file helpers (fileIcon/fmtSize/buildFileTree/isImage/
// isBinaryPdf/codefileUrl) are module-level; toggleDir/renderTreeNodes/
// handleFileClick are nested inside renderPaper (closing over the props) exactly
// as they did the container scope. Bodies are verbatim — behavior preserved.

import type React from 'react';
import { Card } from '../common/Card';
import { Button } from '../common/Button';
import type { CheckpointSummary } from '../../types';
import type { CheckpointFile } from '../../services/api';

  // File icon helper
  const fileIcon = (ext: string) => {
    if (ext === '.tex' || ext === '.bib' || ext === '.sty' || ext === '.cls') return '\u{1F4DD}';
    if (ext === '.pdf') return '\u{1F4D1}';
    if (ext === '.png' || ext === '.jpg' || ext === '.jpeg' || ext === '.svg') return '\u{1F5BC}';
    if (ext === '.json' || ext === '.yaml' || ext === '.yml') return '\u{2699}';
    if (ext === '.log' || ext === '.aux' || ext === '.bbl') return '\u{1F4CB}';
    return '\u{1F4C4}';
  };

  // Format file size
  const fmtSize = (b: number) => {
    if (b < 1024) return `${b} B`;
    if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
    return `${(b / (1024 * 1024)).toFixed(1)} MB`;
  };

  // Group flat path-name files (e.g. "figures/fig_1.pdf") into a directory tree.
  type FileTreeNode = {
    name: string;
    path: string;
    isDir: boolean;
    file?: CheckpointFile;
    children: FileTreeNode[];
  };
  const buildFileTree = (files: CheckpointFile[]): FileTreeNode[] => {
    const root: FileTreeNode = { name: '', path: '', isDir: true, children: [] };
    for (const f of files) {
      const segs = f.name.split('/').filter(Boolean);
      let cur = root;
      for (let i = 0; i < segs.length; i++) {
        const seg = segs[i];
        const isLast = i === segs.length - 1;
        const path = segs.slice(0, i + 1).join('/');
        let child = cur.children.find((c) => c.name === seg && c.isDir === !isLast);
        if (!child) {
          child = { name: seg, path, isDir: !isLast, children: [] };
          if (isLast) child.file = f;
          cur.children.push(child);
        }
        cur = child;
      }
    }
    const sortRec = (n: FileTreeNode) => {
      n.children.sort((a, b) => {
        if (a.isDir !== b.isDir) return a.isDir ? -1 : 1;
        return a.name.localeCompare(b.name);
      });
      n.children.forEach(sortRec);
    };
    sortRec(root);
    return root.children;
  };

  const isImage = (ext: string) => ['.png', '.jpg', '.jpeg', '.svg', '.tiff', '.eps'].includes(ext);
  const isBinaryPdf = (ext: string) => ext === '.pdf';

  // Build URL for binary file preview via existing /codefile endpoint
  const codefileUrl = (absPath: string) =>
    `/codefile?path=${encodeURIComponent(absPath)}`;

export function renderPaper({
  summary, selectedId, t,
  paperView, setPaperView,
  activeFile, setActiveFile,
  editorContent, setEditorContent, editorDirty, setEditorDirty,
  editorSaving, editorMsg, setEditorMsg, fileLoading, setFileLoading,
  compiling, compileLog, setCompileLog,
  ckptFiles, collapsedDirs, setCollapsedDirs,
  activeAbsPath, setActiveAbsPath, uploadRef,
  openFile, handleSave, handleUpload, handleDeleteFile, handleCompile,
}: {
  summary: CheckpointSummary | null;
  selectedId: string;
  t: (key: string) => string;
  paperView: 'pdf' | 'editor';
  setPaperView: (v: 'pdf' | 'editor') => void;
  activeFile: string | null;
  setActiveFile: (v: string | null) => void;
  editorContent: string;
  setEditorContent: (v: string) => void;
  editorDirty: boolean;
  setEditorDirty: (v: boolean) => void;
  editorSaving: boolean;
  editorMsg: string;
  setEditorMsg: (v: string) => void;
  fileLoading: boolean;
  setFileLoading: (v: boolean) => void;
  compiling: boolean;
  compileLog: string | null;
  setCompileLog: (v: string | null) => void;
  ckptFiles: CheckpointFile[];
  collapsedDirs: Set<string>;
  setCollapsedDirs: (updater: (prev: Set<string>) => Set<string>) => void;
  activeAbsPath: string;
  setActiveAbsPath: (v: string) => void;
  uploadRef: React.RefObject<HTMLInputElement>;
  openFile: (filename: string) => void;
  handleSave: () => void;
  handleUpload: (e: React.ChangeEvent<HTMLInputElement>) => void;
  handleDeleteFile: (filename: string) => void;
  handleCompile: () => void;
}): React.ReactNode {

  const toggleDir = (path: string) => {
    setCollapsedDirs((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path); else next.add(path);
      return next;
    });
  };

  const renderTreeNodes = (nodes: FileTreeNode[], depth: number): React.ReactNode =>
    nodes.map((n) => {
      if (n.isDir) {
        const collapsed = collapsedDirs.has(n.path);
        return (
          <div key={'d:' + n.path}>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 4,
                padding: '3px 4px',
                paddingLeft: 4 + depth * 12,
                borderRadius: 4,
                cursor: 'pointer',
                color: 'var(--text, #eee)',
              }}
              onClick={() => toggleDir(n.path)}
              title={n.path}
            >
              <span style={{ flexShrink: 0, width: 10, fontSize: '.7rem', color: 'var(--muted)' }}>
                {collapsed ? '▶' : '▼'}
              </span>
              <span style={{ flexShrink: 0 }}>{collapsed ? '\u{1F4C1}' : '\u{1F4C2}'}</span>
              <span
                style={{
                  flex: 1,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  fontWeight: 600,
                }}
              >
                {n.name}
              </span>
              <span style={{ color: 'var(--muted)', fontSize: '.65rem', flexShrink: 0 }}>
                {n.children.length}
              </span>
            </div>
            {!collapsed && renderTreeNodes(n.children, depth + 1)}
          </div>
        );
      }
      const f = n.file!;
      return (
        <div
          key={'f:' + f.name}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 4,
            padding: '3px 4px',
            paddingLeft: 4 + depth * 12,
            borderRadius: 4,
            cursor: 'pointer',
            background: activeFile === f.name ? 'var(--blue-light, #3b82f6)22' : 'transparent',
            borderLeft: activeFile === f.name ? '2px solid var(--blue-light, #3b82f6)' : '2px solid transparent',
          }}
          onClick={() => handleFileClick(f)}
        >
          <span style={{ flexShrink: 0, width: 10 }} />
          <span style={{ flexShrink: 0 }}>{fileIcon(f.ext)}</span>
          <span
            style={{
              flex: 1,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              color: 'var(--text, #eee)',
            }}
            title={f.name}
          >
            {n.name}
          </span>
          <span style={{ color: 'var(--muted)', fontSize: '.65rem', flexShrink: 0 }}>
            {fmtSize(f.size)}
          </span>
          <button
            onClick={(e) => { e.stopPropagation(); handleDeleteFile(f.name); }}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--muted, #666)',
              cursor: 'pointer',
              fontSize: '.72rem',
              padding: '0 2px',
              flexShrink: 0,
              opacity: 0.5,
            }}
            onMouseEnter={(e) => { (e.target as HTMLElement).style.opacity = '1'; (e.target as HTMLElement).style.color = 'var(--red, #ef4444)'; }}
            onMouseLeave={(e) => { (e.target as HTMLElement).style.opacity = '0.5'; (e.target as HTMLElement).style.color = 'var(--muted, #666)'; }}
            title={`Delete ${f.name}`}
          >
            {'✕'}
          </button>
        </div>
      );
    });

  // Click handler for sidebar files
  const handleFileClick = (f: CheckpointFile) => {
    setEditorContent('');
    setEditorDirty(false);
    setEditorMsg('');
    setFileLoading(false);
    setActiveAbsPath(f.abs_path || '');
    if (f.editable) {
      openFile(f.name);
    } else {
      setActiveFile(f.name);
      setPaperView('editor');
    }
  };

    if (!summary) return null;
    if (!summary.paper_tex && !summary.has_pdf && ckptFiles.length === 0) return null;

    return (
      <Card style={{ marginBottom: 16 }}>
        {/* Header toolbar */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: 8,
            marginBottom: 12,
          }}
        >
          <div className="card-title" style={{ margin: 0 }}>
            {t('paper_title')}
          </div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
            {summary.has_pdf && (
              <Button
                variant={paperView === 'pdf' ? 'primary' : 'outline'}
                size="sm"
                onClick={() => setPaperView('pdf')}
              >
                PDF
              </Button>
            )}
            {(summary.paper_tex || activeFile) && (
              <Button
                variant={paperView === 'editor' ? 'primary' : 'outline'}
                size="sm"
                onClick={() => {
                  setPaperView('editor');
                  if (!activeFile && summary.paper_tex) openFile('full_paper.tex');
                }}
              >
                Editor
              </Button>
            )}
            {editorDirty && (
              <Button
                variant="primary"
                size="sm"
                onClick={handleSave}
                disabled={editorSaving}
              >
                {editorSaving ? 'Saving...' : 'Save'}
              </Button>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={() => uploadRef.current?.click()}
            >
              Upload
            </Button>
            <input
              ref={uploadRef}
              type="file"
              style={{ display: 'none' }}
              onChange={handleUpload}
            />
            <Button
              variant="outline"
              size="sm"
              onClick={handleCompile}
              disabled={compiling}
            >
              {compiling ? 'Compiling...' : 'Compile'}
            </Button>
            {summary.has_pdf && (
              <a
                className="btn btn-outline btn-sm"
                href={`/api/checkpoint/${encodeURIComponent(selectedId)}/paper.pdf`}
                download="paper.pdf"
              >
                {'⬇'} PDF
              </a>
            )}
            {editorMsg && (
              <span style={{ fontSize: '.78rem', color: editorMsg.startsWith('Save') || editorMsg.startsWith('Upload') || editorMsg.startsWith('Delete') || editorMsg.startsWith('Compile OK') ? 'var(--green)' : 'var(--red)' }}>
                {editorMsg}
              </span>
            )}
          </div>
        </div>

        {/* Main content: sidebar + viewer/editor */}
        <div style={{ display: 'flex', gap: 0, minHeight: 500 }}>
          {/* File tree sidebar */}
          <div
            style={{
              width: 220,
              minWidth: 220,
              borderRight: '1px solid var(--border, #333)',
              overflowY: 'auto',
              maxHeight: 600,
              fontSize: '.78rem',
              paddingRight: 8,
            }}
          >
            <div style={{ fontWeight: 700, marginBottom: 6, color: 'var(--muted)', fontSize: '.72rem', textTransform: 'uppercase', letterSpacing: '.5px' }}>
              Files ({ckptFiles.length})
            </div>
            {renderTreeNodes(buildFileTree(ckptFiles), 0)}
            {ckptFiles.length === 0 && (
              <div style={{ color: 'var(--muted)', fontSize: '.75rem', padding: 8 }}>
                No files
              </div>
            )}
          </div>

          {/* Viewer / Editor panel */}
          <div style={{ flex: 1, minWidth: 0, paddingLeft: 12 }}>
            {/* Main paper PDF view */}
            {paperView === 'pdf' && summary.has_pdf && (
              <iframe
                src={`/api/checkpoint/${encodeURIComponent(selectedId)}/paper.pdf`}
                style={{ width: '100%', height: 580, border: 'none', borderRadius: 6 }}
                title="Paper PDF"
              />
            )}
            {paperView === 'pdf' && !summary.has_pdf && (
              <div style={{ textAlign: 'center', color: 'var(--muted)', padding: 40 }}>
                No PDF available.
                {summary.paper_tex && (
                  <div style={{ marginTop: 8 }}>
                    <Button variant="outline" size="sm" onClick={() => { setPaperView('editor'); openFile('full_paper.tex'); }}>
                      Open TeX Editor
                    </Button>
                  </div>
                )}
              </div>
            )}

            {/* Editor mode: file type determines display */}
            {paperView === 'editor' && fileLoading && (
              <div style={{ color: 'var(--muted)', padding: 20 }}>
                <span className="spinner" /> Loading file...
              </div>
            )}
            {paperView === 'editor' && !fileLoading && activeFile && isImage('.' + (activeFile.split('.').pop()?.toLowerCase() || '')) && (
              <div>
                <div style={{ fontSize: '.78rem', color: 'var(--muted)', marginBottom: 6, fontFamily: 'monospace' }}>
                  {activeFile}
                </div>
                <img
                  src={codefileUrl(activeAbsPath)}
                  alt={activeFile}
                  style={{
                    maxWidth: '100%',
                    maxHeight: 540,
                    borderRadius: 6,
                    border: '1px solid var(--border, #333)',
                    background: '#fff',
                  }}
                />
              </div>
            )}
            {paperView === 'editor' && !fileLoading && activeFile && isBinaryPdf('.' + (activeFile.split('.').pop()?.toLowerCase() || '')) && (
              <div>
                <div style={{ fontSize: '.78rem', color: 'var(--muted)', marginBottom: 6, fontFamily: 'monospace' }}>
                  {activeFile}
                </div>
                <iframe
                  src={codefileUrl(activeAbsPath)}
                  style={{ width: '100%', height: 540, border: 'none', borderRadius: 6 }}
                  title={activeFile}
                />
              </div>
            )}
            {paperView === 'editor' && !fileLoading && activeFile && !isImage('.' + (activeFile.split('.').pop()?.toLowerCase() || '')) && !isBinaryPdf('.' + (activeFile.split('.').pop()?.toLowerCase() || '')) && (
              <div style={{ position: 'relative' }}>
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  marginBottom: 6,
                  fontSize: '.78rem',
                  color: 'var(--muted)',
                }}>
                  <span style={{ fontFamily: 'monospace' }}>
                    {activeFile}
                    {editorDirty && <span style={{ color: 'var(--yellow, #f59e0b)', marginLeft: 4 }}>(unsaved)</span>}
                  </span>
                  <span style={{ fontSize: '.7rem' }}>Ctrl+S to save</span>
                </div>
                <textarea
                  value={editorContent}
                  onChange={(e) => { setEditorContent(e.target.value); setEditorDirty(true); }}
                  onKeyDown={(e) => {
                    if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); handleSave(); }
                  }}
                  spellCheck={false}
                  style={{
                    width: '100%',
                    height: 540,
                    fontFamily: '"Fira Code", "Consolas", "Monaco", monospace',
                    fontSize: '.82rem',
                    lineHeight: 1.5,
                    padding: '10px 12px',
                    background: 'var(--bg, #111)',
                    color: 'var(--text, #eee)',
                    border: '1px solid var(--border, #333)',
                    borderRadius: 6,
                    resize: 'vertical',
                    tabSize: 2,
                    outline: 'none',
                  }}
                />
              </div>
            )}
            {paperView === 'editor' && !fileLoading && !activeFile && (
              <div style={{ textAlign: 'center', color: 'var(--muted)', padding: 40 }}>
                <p>Select a file from the sidebar</p>
                {summary.paper_tex && (
                  <Button variant="outline" size="sm" onClick={() => openFile('full_paper.tex')}>
                    Open full_paper.tex
                  </Button>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Compile log */}
        {compileLog != null && (
          <details open style={{ marginTop: 10 }}>
            <summary
              style={{
                cursor: 'pointer',
                fontSize: '.78rem',
                fontWeight: 600,
                color: 'var(--muted)',
                userSelect: 'none',
              }}
            >
              Compile Log
              <button
                onClick={(e) => { e.preventDefault(); setCompileLog(null); }}
                style={{
                  background: 'none',
                  border: 'none',
                  color: 'var(--muted)',
                  cursor: 'pointer',
                  marginLeft: 8,
                  fontSize: '.72rem',
                }}
              >
                {'\u2715'}
              </button>
            </summary>
            <pre
              style={{
                fontSize: '.72rem',
                lineHeight: 1.4,
                maxHeight: 260,
                overflow: 'auto',
                background: 'var(--bg, #111)',
                border: '1px solid var(--border, #333)',
                borderRadius: 6,
                padding: '8px 10px',
                marginTop: 6,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              }}
            >
              {compileLog}
            </pre>
          </details>
        )}
      </Card>
    );
}
