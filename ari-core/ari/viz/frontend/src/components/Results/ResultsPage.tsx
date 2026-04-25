import React, { useEffect, useState, useCallback, useRef } from 'react';
import { useI18n } from '../../i18n';
import { useAppContext } from '../../context/AppContext';
import {
  fetchCheckpointSummary,
  fetchEAR,
  fetchCheckpointFiles,
  fetchCheckpointFileContent,
  saveCheckpointFile,
  uploadCheckpointFile,
  deleteCheckpointFile,
  compileCheckpointPaper,
} from '../../services/api';
import type { EARData, CheckpointFile } from '../../services/api';
import type { CheckpointSummary } from '../../types';
import { Card } from '../common/Card';
import { Button } from '../common/Button';
import { Badge } from '../common/Badge';

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

  // Decision → badge variant mapping
  const decisionVariant = (
    d?: string,
  ): 'green' | 'red' | 'yellow' | 'muted' => {
    if (!d) return 'muted';
    if (d === 'accept' || d === 'weak_accept') return 'green';
    if (d === 'reject' || d === 'weak_reject') return 'red';
    if (d === 'borderline') return 'yellow';
    return 'muted';
  };

  const decisionLabel = (d?: string): string => {
    if (!d) return '—';
    const key = `review_${d}`;
    const localized = t(key);
    return localized === key ? d : localized;
  };

  // Render one dimensional score (rubric-driven)
  const renderDimension = (
    name: string,
    value: number | null | undefined,
    scale: [number, number] | undefined,
  ) => {
    const [lo, hi] = scale ?? [0, 10];
    const range = hi - lo || 1;
    const pct =
      value != null ? Math.max(0, Math.min(100, ((value - lo) / range) * 100)) : 0;
    return (
      <div key={name}>
        <div
          style={{
            fontSize: '.8rem',
            color: 'var(--muted)',
            marginBottom: 4,
            textTransform: 'capitalize',
          }}
        >
          {name.replace(/_/g, ' ')}
        </div>
        <div style={{ fontSize: '1.4rem', fontWeight: 800 }}>
          {value != null ? value : '—'}{' '}
          <span style={{ fontSize: '.9rem', color: 'var(--muted)' }}>
            /{hi}
          </span>
        </div>
        {value != null && (
          <div className="score-bar">
            <div className="score-fill" style={{ width: `${pct}%` }} />
          </div>
        )}
      </div>
    );
  };

  // Render review scores section
  const renderReviewScores = () => {
    const rr = summary?.review_report;
    if (!rr) return null;

    // Rubric-driven path: new schema with score_dimensions
    const hasRubric =
      !!rr.rubric_id || (rr.score_dimensions && rr.score_dimensions.length > 0);

    const legacyScores: [string, number | null][] = [
      [t('abstract'), rr.abstract_score ?? rr.scores?.abstract ?? null],
      [t('body'), rr.body_score ?? rr.scores?.body ?? null],
      [t('overall'), rr.overall_score ?? rr.score ?? null],
    ];

    const textSections: Array<{ key: string; label: string; body?: string }> = [
      { key: 'strengths', label: t('review_strengths'), body: rr.strengths },
      { key: 'weaknesses', label: t('review_weaknesses'), body: rr.weaknesses },
      { key: 'questions', label: t('review_questions'), body: rr.questions },
      {
        key: 'limitations',
        label: t('review_limitations'),
        body: rr.limitations,
      },
    ].filter((s) => s.body && s.body.trim().length > 0);

    return (
      <Card style={{ marginBottom: 16 }}>
        <div
          className="card-title"
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: 8,
            flexWrap: 'wrap',
          }}
        >
          <span>{t('review_scores')}</span>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            {rr.rubric_id && (
              <Badge variant="muted">
                {t('review_rubric')}: {rr.rubric_id}
                {rr.rubric_version ? ` @${rr.rubric_version}` : ''}
              </Badge>
            )}
            {rr.venue && <Badge variant="muted">{rr.venue}</Badge>}
            {rr.decision && (
              <Badge variant={decisionVariant(rr.decision)}>
                {t('review_decision')}: {decisionLabel(rr.decision)}
              </Badge>
            )}
          </div>
        </div>

        {hasRubric && rr.score_dimensions && rr.score_dimensions.length > 0 ? (
          <div
            className="grid-3"
            style={{
              gridTemplateColumns: `repeat(${Math.min(
                rr.score_dimensions.length,
                5,
              )}, minmax(0, 1fr))`,
            }}
          >
            {rr.score_dimensions.map((d) =>
              renderDimension(d.name, d.value, d.scale),
            )}
          </div>
        ) : (
          <div className="grid-3">
            {legacyScores.map(([label, value]) => (
              <div key={label}>
                <div
                  style={{
                    fontSize: '.8rem',
                    color: 'var(--muted)',
                    marginBottom: 4,
                  }}
                >
                  {label}
                </div>
                <div style={{ fontSize: '1.4rem', fontWeight: 800 }}>
                  {value != null ? value : '—'}{' '}
                  <span style={{ fontSize: '.9rem', color: 'var(--muted)' }}>
                    /10
                  </span>
                </div>
                {value != null && (
                  <div className="score-bar">
                    <div
                      className="score-fill"
                      style={{ width: `${(value as number) * 10}%` }}
                    />
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {rr.confidence != null && (
          <div style={{ marginTop: 12, fontSize: '.9rem' }}>
            {t('review_confidence')}:{' '}
            <strong>{rr.confidence}</strong>
          </div>
        )}

        {textSections.length > 0 && (
          <div style={{ marginTop: 16, display: 'grid', gap: 12 }}>
            {textSections.map((s) => (
              <div key={s.key}>
                <div
                  style={{
                    fontSize: '.85rem',
                    fontWeight: 700,
                    marginBottom: 4,
                  }}
                >
                  {s.label}
                </div>
                <div
                  style={{
                    whiteSpace: 'pre-wrap',
                    fontSize: '.85rem',
                    lineHeight: 1.5,
                    color: 'var(--muted)',
                  }}
                >
                  {s.body}
                </div>
              </div>
            ))}
          </div>
        )}

        {rr.issues && rr.issues.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: '.85rem', fontWeight: 700, marginBottom: 4 }}>
              {t('review_issues')}
            </div>
            <ul style={{ margin: 0, paddingLeft: 18, fontSize: '.85rem' }}>
              {rr.issues.map((x, i) => (
                <li key={i}>{x}</li>
              ))}
            </ul>
          </div>
        )}

        {rr.recommendations && rr.recommendations.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: '.85rem', fontWeight: 700, marginBottom: 4 }}>
              {t('review_recommendations')}
            </div>
            <ul style={{ margin: 0, paddingLeft: 18, fontSize: '.85rem' }}>
              {rr.recommendations.map((x, i) => (
                <li key={i}>{x}</li>
              ))}
            </ul>
          </div>
        )}

        {rr.figure_caption_issues && rr.figure_caption_issues.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: '.85rem', fontWeight: 700, marginBottom: 4 }}>
              {t('review_figure_caption_issues')}
            </div>
            <ul style={{ margin: 0, paddingLeft: 18, fontSize: '.85rem' }}>
              {rr.figure_caption_issues.map((x, i) => (
                <li key={i}>{x}</li>
              ))}
            </ul>
          </div>
        )}

        {rr.ensemble_reviews && rr.ensemble_reviews.length > 1 && (
          <div style={{ marginTop: 16 }}>
            <div style={{ fontSize: '.85rem', fontWeight: 700, marginBottom: 6 }}>
              {t('review_ensemble')} ({rr.ensemble_reviews.length})
            </div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {rr.ensemble_reviews.map((er, i) => (
                <Badge key={i} variant={decisionVariant(er.decision)}>
                  #{i + 1}:{' '}
                  {er.overall_score ?? er.score ?? '—'}{' '}
                  {er.decision ? `(${decisionLabel(er.decision)})` : ''}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {rr.meta_review && (
          <div style={{ marginTop: 12, padding: 10, border: '1px solid var(--border)', borderRadius: 6 }}>
            <div style={{ fontSize: '.85rem', fontWeight: 700, marginBottom: 4 }}>
              {t('review_meta')}
            </div>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              {rr.meta_review.decision && (
                <Badge variant={decisionVariant(rr.meta_review.decision)}>
                  {decisionLabel(rr.meta_review.decision)}
                </Badge>
              )}
              <span style={{ fontSize: '.9rem' }}>
                {t('overall')}:{' '}
                <strong>
                  {rr.meta_review.overall_score ?? rr.meta_review.score ?? '—'}
                </strong>
              </span>
            </div>
          </div>
        )}

        {rr.fewshot_sources && rr.fewshot_sources.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: '.85rem', fontWeight: 700, marginBottom: 4 }}>
              {t('review_fewshot_sources')}
            </div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {rr.fewshot_sources.map((fs, i) => (
                <Badge key={i} variant="muted">
                  {fs.title ?? fs.id}
                  {fs.score != null ? ` (${fs.score.toFixed(2)})` : ''}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {rr.citation_ok != null && (
          <div style={{ marginTop: 12 }}>
            {t('citations')}:{' '}
            {rr.citation_ok ? (
              <Badge variant="green">{'✓'} {t('ok_label')}</Badge>
            ) : (
              <Badge variant="red">{'✗'} {t('issues_label')}</Badge>
            )}
          </div>
        )}
      </Card>
    );
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

  // Render verify / reproducibility section
  const renderRepro = () => {
    if (!summary) return null;

    const repro = summary.reproducibility_report || summary.repro;

    return (
      <Card style={{ marginBottom: 16 }}>
        <div className="card-title">{t('verify_title')}</div>
        {repro ? (
          (() => {
            const reproObj =
              typeof repro === 'string' ? tryParseJson(repro) : repro;

            if (!reproObj || typeof reproObj !== 'object') {
              // Plain string repro
              return (
                <div
                  style={{ fontSize: '.85rem', color: 'var(--muted)' }}
                >
                  {String(repro)}
                </div>
              );
            }

            const reproRecord = reproObj as Record<string, any>;

            // Handle skill-not-found error gracefully
            if (
              reproRecord.error &&
              (String(reproRecord.error).indexOf('not found') >= 0 ||
                String(reproRecord.error).indexOf('Tool') >= 0 ||
                String(reproRecord.error).indexOf('Available: []') >= 0)
            ) {
              return (
                <>
                  <div
                    style={{
                      color: 'var(--yellow)',
                      fontSize: '.85rem',
                      padding: 8,
                    }}
                  >
                    {t('repro_skill_unavail')}
                  </div>
                  <details>
                    <summary
                      style={{
                        fontSize: '.75rem',
                        color: 'var(--muted)',
                        cursor: 'pointer',
                      }}
                    >
                      {t('details')}
                    </summary>
                    <pre
                      style={{
                        fontSize: '.72rem',
                        color: 'var(--muted)',
                        marginTop: 4,
                      }}
                    >
                      {reproRecord.error}
                    </pre>
                  </details>
                </>
              );
            }

            const verdict =
              reproRecord.verdict ||
              reproRecord.status ||
              reproRecord.result ||
              'unknown';
            const badgeVariant =
              verdict === 'REPRODUCED' ||
              verdict === 'PASS' ||
              verdict === 'pass'
                ? 'green'
                : verdict === 'FAILED' ||
                    verdict === 'FAIL' ||
                    verdict === 'fail' ||
                    verdict === 'NOT_REPRODUCED'
                  ? 'red'
                  : verdict === 'ENVIRONMENT_MISMATCH'
                    ? 'yellow'
                    : 'yellow';

            const skip = new Set([
              'verdict',
              'status',
              'result',
              'summary',
            ]);

            return (
              <>
                <div style={{ fontSize: '1.1rem', marginBottom: 8 }}>
                  <Badge variant={badgeVariant}>{verdict}</Badge>
                </div>
                {reproRecord.summary && (
                  <div
                    style={{
                      fontSize: '.85rem',
                      color: 'var(--muted)',
                      marginBottom: 8,
                    }}
                  >
                    {reproRecord.summary}
                  </div>
                )}
                {Object.keys(reproRecord)
                  .filter((k) => !skip.has(k))
                  .slice(0, 8)
                  .map((k) => (
                    <div
                      key={k}
                      style={{ fontSize: '.8rem', marginTop: 4 }}
                    >
                      <span style={{ color: 'var(--muted)' }}>{k}:</span>{' '}
                      {JSON.stringify(reproRecord[k])}
                    </div>
                  ))}
              </>
            );
          })()
        ) : (
          <div style={{ color: 'var(--muted)', fontSize: '.85rem' }}>
            {t('no_repro')}
          </div>
        )}
      </Card>
    );
  };

  // Render experiment context
  const renderContext = () => {
    if (!summary) return null;
    const sd = summary.science_data;
    if (!sd || !(sd as any).experiment_context) return null;

    const ctx = (sd as any).experiment_context as Record<string, unknown>;

    return (
      <Card style={{ marginBottom: 16 }}>
        <div className="card-title">{t('exp_context')}</div>
        <div>
          {Object.entries(ctx).map(([k, v]) => {
            const text = String(
              typeof v === 'object'
                ? JSON.stringify(v, null, 2)
                : v,
            );
            return (
              <div key={k} style={{ marginBottom: 12 }}>
                <div style={{ color: 'var(--muted)', fontSize: '.75rem', marginBottom: 2, fontWeight: 600 }}>
                  {k}
                </div>
                {text.length <= 500 ? (
                  <div style={{ fontSize: '.8rem', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                    {text}
                  </div>
                ) : (
                  <details>
                    <summary style={{ cursor: 'pointer', color: 'var(--blue-light)', fontSize: '.75rem', listStyle: 'none', userSelect: 'none' }}>
                      {'▶ Show detail'}
                    </summary>
                    <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: '4px 0 0', fontSize: '.78rem', overflow: 'auto', maxHeight: 480 }}>
                      {text}
                    </pre>
                  </details>
                )}
              </div>
            );
          })}
        </div>
      </Card>
    );
  };

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
  const renderFigures = () => {
    if (!summary) return null;
    const fm = summary.figures_manifest as any;
    if (!fm || !fm.figures) return null;

    // plot-skill writes `figures` as a dict {name: path}; older runs may
    // have stored a list [{path, caption, ...}]. Normalize to a list here
    // so the grid works with both shapes.
    const kinds = (fm.figure_kinds || {}) as Record<string, string>;
    const snippets = (fm.latex_snippets || {}) as Record<string, string>;
    const extractCaption = (snip: string): string => {
      const m = snip.match(/\\caption\{([^}]+)\}/);
      return m ? m[1] : '';
    };
    const figs: Array<{ name: string; path: string; caption: string; kind: string }> =
      Array.isArray(fm.figures)
        ? fm.figures.map((fig: any, idx: number) => ({
            name: fig.name || `fig_${idx + 1}`,
            path: fig.path || fig,
            caption: fig.caption || '',
            kind: fig.kind || fig.figure_kind || '',
          }))
        : Object.entries(fm.figures as Record<string, string>).map(([name, path]) => ({
            name,
            path: String(path),
            caption: extractCaption(snippets[name] || ''),
            kind: kinds[name] || '',
          }));

    if (!figs.length) return null;

    return (
      <Card style={{ marginBottom: 16 }}>
        <div className="card-title">{'📈'} Figures</div>
        <div className="grid-2">
          {figs.map((fig, idx) => {
            const { path, caption, kind } = fig;
            const kindBadge: Record<string, string> = {
              plot: 'Plot',
              svg: 'Diagram',
            };
            return (
              <div key={idx}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                  {kind && kindBadge[kind] && (
                    <Badge variant="blue">{kindBadge[kind]}</Badge>
                  )}
                  {caption && (
                    <span style={{ fontSize: '.8rem', color: 'var(--muted)' }}>
                      {caption}
                    </span>
                  )}
                </div>
                <img
                  className="figure-img"
                  src={`/codefile?path=${encodeURIComponent(path)}`}
                  alt="figure"
                  onError={(e) => {
                    (e.target as HTMLImageElement).style.display = 'none';
                  }}
                />
              </div>
            );
          })}
        </div>
      </Card>
    );
  };

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
            {renderReviewScores()}
            {renderRepro()}
            {renderEAR()}
            {renderContext()}
            {renderFigures()}

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

/** Attempt to parse a JSON string; return null on failure. */
function tryParseJson(s: any): any {
  if (typeof s !== 'string') return s;
  try {
    return JSON.parse(s);
  } catch {
    return null;
  }
}
