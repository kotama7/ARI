import React, { useEffect, useState, useCallback, useRef } from 'react';
import { useI18n } from '../../i18n';
import { useAppContext } from '../../context/AppContext';
import {
  fetchCheckpointSummary,
  fetchEAR,
  curateEAR,
  runPublish,
  promotePublish,
  fetchPublishRecord,
  fetchCheckpointFiles,
  fetchCheckpointFileContent,
  fetchCheckpointFilecontent,
  saveCheckpointFile,
  uploadCheckpointFile,
  deleteCheckpointFile,
  compileCheckpointPaper,
  fetchPublishYaml,
  savePublishYaml,
} from '../../services/api';
import type {
  EARData, EARCurateResult, CheckpointFile,
  PublishRecord, PublishRunResult,
  PublishYamlData,
} from '../../services/api';
import type { CheckpointSummary } from '../../types';
import { Card } from '../common/Card';
import { Button } from '../common/Button';
import { Badge } from '../common/Badge';
import { PublishYamlEditor } from './PublishYamlEditor';
import { renderContext, renderFigures, renderReviewScores, renderRepro } from './resultSections';


export function ResultsPage() {
  const { t } = useI18n();
  const { state, checkpoints } = useAppContext();

  const [selectedId, setSelectedId] = useState<string>('');
  const [summary, setSummary] = useState<CheckpointSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [paperView, setPaperView] = useState<'pdf' | 'editor'>('pdf');
  const [ear, setEar] = useState<EARData | null>(null);
  const [earLoading, setEarLoading] = useState(false);
  const [curating, setCurating] = useState(false);
  const [curateMsg, setCurateMsg] = useState<string>('');
  const [publishing, setPublishing] = useState(false);
  const [publishMsg, setPublishMsg] = useState<string>('');
  const [publishRecord, setPublishRecord] = useState<PublishRecord | null>(null);
  const [publishBackend, setPublishBackend] = useState<string>('local-tarball');
  const [publishConsent, setPublishConsent] = useState<boolean>(false);

  // publish.yaml editor state
  const [pyEditorOpen, setPyEditorOpen] = useState(false);
  const [pyData, setPyData] = useState<PublishYamlData | null>(null);
  const [pyText, setPyText] = useState<string>('');
  const [pyExists, setPyExists] = useState<boolean>(false);
  const [pyMode, setPyMode] = useState<'form' | 'raw'>('form');
  const [pySaving, setPySaving] = useState(false);
  const [pyMsg, setPyMsg] = useState<string>('');

  // Overleaf-like file management state
  const [ckptFiles, setCkptFiles] = useState<CheckpointFile[]>([]);
  const [collapsedDirs, setCollapsedDirs] = useState<Set<string>>(new Set());
  const [activeFile, setActiveFile] = useState<string | null>(null);
  const [editorContent, setEditorContent] = useState('');
  const [editorDirty, setEditorDirty] = useState(false);
  const [editorSaving, setEditorSaving] = useState(false);
  const [editorMsg, setEditorMsg] = useState('');
  const [fileLoading, setFileLoading] = useState(false);
  const [compiling, setCompiling] = useState(false);
  const [compileLog, setCompileLog] = useState<string | null>(null);
  const uploadRef = useRef<HTMLInputElement>(null);

  // Reproducibility run-log inline viewer
  const [reproLogOpen, setReproLogOpen] = useState(false);
  const [reproLogContent, setReproLogContent] = useState<string | null>(null);
  const [reproLogPath, setReproLogPath] = useState<string | null>(null);
  const [reproLogLoading, setReproLogLoading] = useState(false);

  // Pick initial selection
  const populateDropdown = useCallback(async () => {

    // Determine active checkpoint
    const activeId =
      state?.checkpoint_id ||
      String(state?.checkpoint_path || '')
        .split('/')
        .pop() ||
      '';

    // Check if there's a pre-selected checkpoint from Experiments page
    const storedId = sessionStorage.getItem('ari_selected_checkpoint');
    if (storedId) {
      sessionStorage.removeItem('ari_selected_checkpoint');
      setSelectedId(storedId);
      return storedId;
    }

    // Auto-select active checkpoint
    if (activeId) {
      setSelectedId(activeId);
      return activeId;
    }

    return '';
  }, [state?.checkpoint_id, state?.checkpoint_path]);

  // Load results for selected checkpoint
  const loadResults = useCallback(
    async (id: string) => {
      if (!id) {
        setSummary(null);
        setError(null);
        setEar(null);
        return;
      }

      setLoading(true);
      setError(null);
      setSummary(null);
      setEar(null);

      try {
        const d = await fetchCheckpointSummary(id);
        if (d.error) {
          setError(d.error);
        } else {
          setSummary(d);
          // Default to PDF if available, else TeX
          if (d.has_pdf) {
            setPaperView('pdf');
          } else if (d.paper_tex) {
            setPaperView('editor');
          }
        }
      } catch (e: any) {
        setError(e.toString());
      } finally {
        setLoading(false);
      }

      // Best-effort EAR fetch — non-blocking, doesn't affect main loading flag
      setEarLoading(true);
      try {
        const e = await fetchEAR(id);
        setEar(e && !e.error ? e : null);
      } catch {
        setEar(null);
      } finally {
        setEarLoading(false);
      }
    },
    [],
  );

  // Load reproducibility run log — try candidate paths in order, use first one
  // that exists. Called by the "Show run log" button in renderRepro.
  const loadReproLog = useCallback(async (id: string) => {
    if (!id) return;
    const candidates = [
      // PaperBench-format run log (written by run_reproduce in
      // ari-skill-paper-re); preferred when present.
      'repro_sandbox/reproduce.log',
      // Legacy candidates kept as fallback for older runs.
      'repro_sandbox/run.log',
      'repro_sandbox/react_log.json',
      'repro/repro_output.log',
    ];
    setReproLogLoading(true);
    setReproLogContent(null);
    setReproLogPath(null);
    try {
      for (const p of candidates) {
        const r = await fetchCheckpointFilecontent(id, p);
        if (!r.error && typeof r.content === 'string') {
          setReproLogContent(r.content);
          setReproLogPath(p);
          return;
        }
      }
      setReproLogContent('');
      setReproLogPath(null);
    } finally {
      setReproLogLoading(false);
    }
  }, []);

  // Load checkpoint file list
  const loadFiles = useCallback(async (id: string) => {
    if (!id) { setCkptFiles([]); return; }
    try {
      const r = await fetchCheckpointFiles(id);
      if (r.files) setCkptFiles(r.files);
    } catch { setCkptFiles([]); }
  }, []);

  // Open a file in the editor
  const openFile = useCallback(async (filename: string) => {
    if (!selectedId) return;
    setFileLoading(true);
    setEditorMsg('');
    try {
      const r = await fetchCheckpointFileContent(selectedId, filename);
      if (r.error) {
        setEditorMsg(r.error);
      } else {
        setActiveFile(filename);
        setEditorContent(r.content);
        setEditorDirty(false);
        setPaperView('editor');
      }
    } catch (e: any) {
      setEditorMsg(e.toString());
    } finally {
      setFileLoading(false);
    }
  }, [selectedId]);

  // Save current editor content
  const handleSave = useCallback(async () => {
    if (!selectedId || !activeFile) return;
    setEditorSaving(true);
    setEditorMsg('');
    try {
      const r = await saveCheckpointFile(selectedId, activeFile, editorContent);
      if (r.ok) {
        setEditorDirty(false);
        setEditorMsg('Saved');
        setTimeout(() => setEditorMsg(''), 2000);
        // Refresh summary to reflect tex changes
        loadResults(selectedId);
        loadFiles(selectedId);
      } else {
        setEditorMsg(r.error || 'Save failed');
      }
    } catch (e: any) {
      setEditorMsg(e.toString());
    } finally {
      setEditorSaving(false);
    }
  }, [selectedId, activeFile, editorContent, loadResults, loadFiles]);

  // Upload file
  const handleUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !selectedId) return;
    setEditorMsg('');
    try {
      const r = await uploadCheckpointFile(selectedId, file);
      if (r.ok) {
        setEditorMsg(`Uploaded: ${r.name}`);
        setTimeout(() => setEditorMsg(''), 2000);
        loadFiles(selectedId);
        loadResults(selectedId);
      } else {
        setEditorMsg(r.error || 'Upload failed');
      }
    } catch (e: any) {
      setEditorMsg(e.toString());
    }
    // Reset input so same file can be re-uploaded
    if (uploadRef.current) uploadRef.current.value = '';
  }, [selectedId, loadFiles, loadResults]);

  // Delete file
  const handleDeleteFile = useCallback(async (filename: string) => {
    if (!selectedId) return;
    if (!window.confirm(`Delete "${filename}"?`)) return;
    setEditorMsg('');
    try {
      const r = await deleteCheckpointFile(selectedId, filename);
      if (r.ok) {
        if (activeFile === filename) {
          setActiveFile(null);
          setEditorContent('');
          setEditorDirty(false);
        }
        loadFiles(selectedId);
        loadResults(selectedId);
        setEditorMsg(`Deleted: ${filename}`);
        setTimeout(() => setEditorMsg(''), 2000);
      } else {
        setEditorMsg(r.error || 'Delete failed');
      }
    } catch (e: any) {
      setEditorMsg(e.toString());
    }
  }, [selectedId, activeFile, loadFiles, loadResults]);

  // Compile LaTeX
  const handleCompile = useCallback(async () => {
    if (!selectedId) return;
    setCompiling(true);
    setCompileLog(null);
    setEditorMsg('');
    try {
      const r = await compileCheckpointPaper(selectedId);
      setCompileLog(r.log || '');
      if (r.ok) {
        setEditorMsg('Compile OK');
        setTimeout(() => setEditorMsg(''), 3000);
        loadResults(selectedId);
        loadFiles(selectedId);
      } else {
        setEditorMsg('Compile failed — see log');
      }
    } catch (e: any) {
      setEditorMsg(e.toString());
    } finally {
      setCompiling(false);
    }
  }, [selectedId, loadResults, loadFiles]);

  // Initial load
  useEffect(() => {
    populateDropdown().then((id) => {
      if (id) {
        loadResults(id);
        loadFiles(id);
      }
    });
  }, [populateDropdown, loadResults, loadFiles]);

  // Re-fetch summary when experiment state changes (e.g. repro report generated)
  const prevHasRepro = React.useRef(state?.has_repro);
  const prevHasReview = React.useRef(state?.has_review);
  useEffect(() => {
    if (
      selectedId &&
      (state?.has_repro !== prevHasRepro.current ||
       state?.has_review !== prevHasReview.current)
    ) {
      prevHasRepro.current = state?.has_repro;
      prevHasReview.current = state?.has_review;
      loadResults(selectedId);
    }
  }, [state?.has_repro, state?.has_review, selectedId, loadResults]);

  // Re-load when selection changes
  const handleSelectChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const id = e.target.value;
    setSelectedId(id);
    setActiveFile(null);
    setActiveAbsPath('');
    setEditorContent('');
    setEditorDirty(false);
    setEditorMsg('');
    loadResults(id);
    loadFiles(id);
  };

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

  const isImage = (ext: string) => ['.png', '.jpg', '.jpeg', '.svg', '.tiff', '.eps'].includes(ext);
  const isBinaryPdf = (ext: string) => ext === '.pdf';

  // State for absolute path of the active file (for binary preview via /codefile)
  const [activeAbsPath, setActiveAbsPath] = useState('');

  // Build URL for binary file preview via existing /codefile endpoint
  const codefileUrl = (absPath: string) =>
    `/codefile?path=${encodeURIComponent(absPath)}`;

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

  // Render Overleaf-like paper editor
  const renderPaper = () => {
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
  };

  // Render verify / reproducibility section.
  //
  // Two render modes:
  //   - "rich": when any of the PaperBench-format ORS payloads is present
  //     (ors_grade / ors_phase1 / ors_replicator). Shows verdict + score bar
  //     + 4 chain stage cards (Rubric → Replicator → Phase 1 → Phase 2) +
  //     expandable per-leaf judge results + provenance footer.
  //   - "legacy": when only ``reproducibility_report`` (the legacy
  //     pre-§4.1 format) is present. Falls back to the previous flat
  //     verdict + key-value layout.
  // Render experiment context
  // Render Experiment Artifact Repository (EAR) section — issue #4
  const renderEAR = () => {
    if (earLoading) {
      return (
        <Card style={{ marginBottom: 16 }}>
          <div className="card-title">{'📦'} Artifact Repository</div>
          <div style={{ color: 'var(--muted)' }}>
            <span className="spinner" /> Loading EAR...
          </div>
        </Card>
      );
    }
    if (!ear) return null;

    const files = ear.files || [];
    const downloadUrl = ear.ear_dir
      ? `/codefile?path=${encodeURIComponent(ear.ear_dir)}`
      : '';

    return (
      <Card style={{ marginBottom: 16 }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: 12,
          }}
        >
          <div className="card-title" style={{ margin: 0 }}>
            {'📦'} Artifact Repository
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <Badge variant="green">{ear.file_count ?? files.length} files</Badge>
            {downloadUrl && (
              <a
                className="btn btn-outline btn-sm"
                href={downloadUrl}
                title="Open EAR directory"
                target="_blank"
                rel="noreferrer"
              >
                {'⬇'} Open
              </a>
            )}
          </div>
        </div>
        <div style={{ fontSize: '.75rem', color: 'var(--muted)', marginBottom: 8 }}>
          {ear.ear_dir}
        </div>
        {/* ── Curation panel ───────── */}
        {ear && (
          <div
            style={{
              background: 'var(--surface-2, rgba(0,0,0,0.04))',
              padding: 10,
              borderRadius: 6,
              marginBottom: 12,
              fontSize: '.82rem',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <strong>{t('curation_title')}</strong>
              <Button
                size="sm"
                disabled={curating || !selectedId}
                onClick={async () => {
                  if (!selectedId) return;
                  setCurating(true);
                  setCurateMsg('');
                  try {
                    const r: EARCurateResult = await curateEAR(selectedId);
                    if (r.error) {
                      setCurateMsg(`✘ ${r.error}`);
                    } else if (r.skipped) {
                      setCurateMsg('publish.yaml absent — skipped');
                    } else {
                      setCurateMsg(
                        `✓ curated ${(r.included_files || []).length} file(s) — sha256 ${(
                          r.bundle_sha256 || ''
                        ).slice(0, 16)}…`,
                      );
                      // Refresh /api/ear/<id> to surface the new published block.
                      try {
                        const fresh = await fetchEAR(selectedId);
                        setEar(fresh);
                      } catch {}
                    }
                  } catch (e: any) {
                    setCurateMsg(`✘ ${e?.message ?? String(e)}`);
                  } finally {
                    setCurating(false);
                  }
                }}
              >
                {curating ? '…' : t('curate_now')}
              </Button>
            </div>
            {ear.published && !ear.published.error && (
              <div style={{ marginTop: 6, color: 'var(--muted)' }}>
                <div>
                  <strong>sha256:</strong>{' '}
                  <code>{(ear.published.bundle_sha256 || '').slice(0, 32)}…</code>
                </div>
                <div>
                  <strong>files:</strong> {ear.published.file_count ?? 0} ·{' '}
                  <strong>visibility:</strong> {ear.published.visibility ?? 'staged'} ·{' '}
                  <strong>excluded:</strong> {ear.published.excluded_count ?? 0}
                </div>
              </div>
            )}
            {ear.published?.error && (
              <div style={{ color: 'var(--red, crimson)', marginTop: 6 }}>
                manifest error: {ear.published.error}
              </div>
            )}
            {!ear.publish_yaml_present && (
              <div style={{ color: 'var(--muted)', marginTop: 6, fontStyle: 'italic' }}>
                {t('publish_yaml_missing')}
              </div>
            )}
            {/* publish.yaml editor toggle */}
            <div style={{ marginTop: 8 }}>
              <Button
                size="sm"
                variant="outline"
                onClick={async () => {
                  if (!selectedId) return;
                  const next = !pyEditorOpen;
                  setPyEditorOpen(next);
                  if (next && pyData == null) {
                    setPyMsg('');
                    try {
                      const r = await fetchPublishYaml(selectedId);
                      if (r.error) {
                        setPyMsg(`✘ ${r.error}`);
                      } else {
                        setPyData(r.data || {});
                        setPyText(r.text || '');
                        setPyExists(!!r.exists);
                      }
                    } catch (e: any) {
                      setPyMsg(`✘ ${e?.message ?? String(e)}`);
                    }
                  }
                }}
              >
                {pyEditorOpen
                  ? t('py_editor_hide')
                  : ear.publish_yaml_present
                    ? t('py_editor_edit')
                    : t('py_editor_create')}
              </Button>
            </div>
            {pyEditorOpen && (
              <PublishYamlEditor
                runId={selectedId}
                data={pyData}
                text={pyText}
                exists={pyExists}
                mode={pyMode}
                setMode={setPyMode}
                setData={setPyData}
                setText={setPyText}
                saving={pySaving}
                msg={pyMsg}
                t={t}
                onSaved={async (alsoCurate) => {
                  if (!selectedId) return;
                  setPySaving(true);
                  setPyMsg('');
                  try {
                    const payload =
                      pyMode === 'raw'
                        ? { text: pyText }
                        : { data: pyData || {} };
                    const r = await savePublishYaml(selectedId, payload);
                    if (r.error) {
                      setPyMsg(`✘ ${r.error}`);
                      return;
                    }
                    setPyExists(true);
                    setPyData(r.data || pyData);
                    setPyText(r.text || pyText);
                    setPyMsg(`✓ ${t('py_editor_saved')}`);
                    // Refresh /api/ear so publish_yaml_present flips true.
                    try {
                      const fresh = await fetchEAR(selectedId);
                      setEar(fresh);
                    } catch {}
                    if (alsoCurate) {
                      setCurating(true);
                      setCurateMsg('');
                      try {
                        const cr: EARCurateResult = await curateEAR(selectedId);
                        if (cr.error) {
                          setCurateMsg(`✘ ${cr.error}`);
                        } else if (cr.skipped) {
                          setCurateMsg('publish.yaml absent — skipped');
                        } else {
                          setCurateMsg(
                            `✓ curated ${(cr.included_files || []).length} file(s) — sha256 ${(
                              cr.bundle_sha256 || ''
                            ).slice(0, 16)}…`,
                          );
                          try {
                            const fresh = await fetchEAR(selectedId);
                            setEar(fresh);
                          } catch {}
                        }
                      } catch (ce: any) {
                        setCurateMsg(`✘ ${ce?.message ?? String(ce)}`);
                      } finally {
                        setCurating(false);
                      }
                    }
                  } catch (e: any) {
                    setPyMsg(`✘ ${e?.message ?? String(e)}`);
                  } finally {
                    setPySaving(false);
                  }
                }}
              />
            )}
            {curateMsg && (
              <div style={{ marginTop: 6, fontFamily: 'monospace' }}>{curateMsg}</div>
            )}
            {/* Publish row — only shown once curated */}
            {ear.published && !ear.published.error && (
              <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px dashed var(--border, #ccc)' }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                  <strong>{t('publish_title')}</strong>
                  <select
                    value={publishBackend}
                    onChange={(e) => setPublishBackend(e.target.value)}
                    style={{ padding: '2px 6px', fontSize: '.78rem' }}
                  >
                    <option value="local-tarball">local-tarball</option>
                    <option value="ari-registry">ari-registry</option>
                    <option value="zenodo">zenodo</option>
                    <option value="gh">gh</option>
                  </select>
                  <label style={{ fontSize: '.78rem', display: 'flex', alignItems: 'center', gap: 4 }}>
                    <input
                      type="checkbox"
                      checked={publishConsent}
                      onChange={(e) => setPublishConsent(e.target.checked)}
                    />
                    {t('publish_consent')}
                  </label>
                  <Button
                    size="sm"
                    disabled={publishing || !selectedId}
                    onClick={async () => {
                      if (!selectedId) return;
                      setPublishing(true);
                      setPublishMsg('');
                      try {
                        const r: PublishRunResult = await runPublish(selectedId, {
                          backend: publishBackend,
                          dry_run: !publishConsent,
                          consent: publishConsent,
                        });
                        if (r.error) {
                          setPublishMsg(`✘ ${r.error}`);
                        } else {
                          setPublishMsg(
                            `${r.dry_run ? '(dry-run) ' : ''}✓ ref=${r.ref} sha=${(r.bundle_sha256 || '').slice(0, 16)}…`,
                          );
                          try {
                            const rec = await fetchPublishRecord(selectedId);
                            setPublishRecord(rec);
                          } catch {}
                        }
                      } catch (e: any) {
                        setPublishMsg(`✘ ${e?.message ?? String(e)}`);
                      } finally {
                        setPublishing(false);
                      }
                    }}
                  >
                    {publishing ? '…' : (publishConsent ? t('publish_now') : t('publish_dry_run'))}
                  </Button>
                  {publishRecord?.published && !publishRecord.error && (
                    <Button
                      size="sm"
                      onClick={async () => {
                        if (!selectedId) return;
                        const r = await promotePublish(selectedId, 'public');
                        setPublishMsg(r.error ? `✘ ${r.error}` : `${t('promote_done')}: ${r.visibility}`);
                        try {
                          const rec = await fetchPublishRecord(selectedId);
                          setPublishRecord(rec);
                        } catch {}
                      }}
                    >
                      {t('promote_btn')}
                    </Button>
                  )}
                </div>
                {publishMsg && (
                  <div style={{ marginTop: 4, fontFamily: 'monospace', fontSize: '.78rem' }}>{publishMsg}</div>
                )}
                {publishRecord?.published && (
                  <div style={{ marginTop: 4, fontSize: '.78rem', color: 'var(--muted)' }}>
                    record: backend={publishRecord.backend} · ref={publishRecord.ref} · visibility={publishRecord.visibility}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
        {ear.readme && (
          <details open style={{ marginBottom: 12 }}>
            <summary style={{ cursor: 'pointer', fontWeight: 600 }}>README.md</summary>
            <pre
              className="code"
              style={{
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                maxHeight: 360,
                overflow: 'auto',
                marginTop: 8,
              }}
            >
              {ear.readme}
            </pre>
          </details>
        )}
        {ear.results && (
          <details style={{ marginBottom: 12 }}>
            <summary style={{ cursor: 'pointer', fontWeight: 600 }}>RESULTS.md</summary>
            <pre
              className="code"
              style={{
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                maxHeight: 360,
                overflow: 'auto',
                marginTop: 8,
              }}
            >
              {ear.results}
            </pre>
          </details>
        )}
        {files.length > 0 && (
          <details>
            <summary style={{ cursor: 'pointer', fontWeight: 600 }}>
              Directory tree ({files.length})
            </summary>
            <div
              style={{
                fontSize: '.78rem',
                fontFamily: 'monospace',
                maxHeight: 260,
                overflow: 'auto',
                marginTop: 8,
              }}
            >
              {files.map((f) => {
                const isDir = f.type === 'dir';
                const filePath = ear.ear_dir
                  ? `${ear.ear_dir}/${f.path}`
                  : f.path;
                return (
                  <div key={f.path} style={{ padding: '2px 0' }}>
                    {isDir ? (
                      <span style={{ color: 'var(--blue-light)' }}>
                        📁 {f.path}/
                      </span>
                    ) : (
                      <a
                        href={`/codefile?path=${encodeURIComponent(filePath)}`}
                        target="_blank"
                        rel="noreferrer"
                        style={{ color: 'var(--text)', textDecoration: 'none' }}
                      >
                        📄 {f.path}
                        {f.size != null && (
                          <span style={{ color: 'var(--muted)', marginLeft: 8 }}>
                            ({f.size} B)
                          </span>
                        )}
                      </a>
                    )}
                  </div>
                );
              })}
            </div>
          </details>
        )}
      </Card>
    );
  };

  // Render figures grid
  return (
    <div className="page active" style={{ display: 'block' }}>
      <h1>{t('results_title')}</h1>
      <p className="subtitle">{t('results_subtitle')}</p>

      {/* Checkpoint selector dropdown */}
      <div
        style={{
          display: 'flex',
          gap: 10,
          marginBottom: 20,
          alignItems: 'center',
        }}
      >
        <select
          style={{ width: 'auto', minWidth: 240 }}
          value={selectedId}
          onChange={handleSelectChange}
        >
          <option value="">{'—'} Select experiment {'—'}</option>
          {checkpoints.map((c) => {
            const scoreStr =
              c.review_score != null ? ` ✦${c.review_score}` : '';
            const label = c.id + scoreStr;
            return (
              <option key={c.id} value={c.id} title={c.id}>
                {label}
              </option>
            );
          })}
        </select>
        <Button variant="outline" size="sm" onClick={() => populateDropdown()}>
          {'↻'}
        </Button>
      </div>

      {/* Content */}
      <div>
        {loading && (
          <div style={{ color: 'var(--muted)' }}>
            <span className="spinner" /> {t('loading')}
          </div>
        )}

        {error && (
          <div style={{ color: 'var(--red)' }}>
            {t('error_prefix')}
            {error}
          </div>
        )}

        {!loading && !error && !selectedId && (
          <div className="empty-state">
            <div className="empty-icon">{'📊'}</div>
            <p>{t('select_exp')}</p>
          </div>
        )}

        {!loading && !error && summary && (
          <>
            {renderPaper()}
            {renderReviewScores({ summary, t })}
            {renderRepro({
              summary,
              selectedId,
              reproLogOpen,
              reproLogContent,
              reproLogPath,
              reproLogLoading,
              setReproLogOpen,
              loadReproLog,
              t,
            })}
            {renderEAR()}
            {renderContext({ summary, t })}
            {renderFigures({ summary })}

            {/* If no content at all */}
            {!summary.paper_tex &&
              !summary.has_pdf &&
              !summary.review_report &&
              !summary.reproducibility_report &&
              !summary.repro &&
              !(summary.science_data as any)?.experiment_context &&
              !(() => {
                const figs = (summary.figures_manifest as any)?.figures;
                if (Array.isArray(figs)) return figs.length > 0;
                if (figs && typeof figs === 'object') return Object.keys(figs).length > 0;
                return false;
              })() && (
                <div className="empty-state">
                  <div className="empty-icon">{'📊'}</div>
                  <p>No results data found in this checkpoint</p>
                </div>
              )}
          </>
        )}
      </div>
    </div>
  );
}

