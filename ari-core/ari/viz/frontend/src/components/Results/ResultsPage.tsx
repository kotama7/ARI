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
import { RubricTreeVisualization } from './RubricTreeVisualization';

// ─── publish.yaml editor (per-checkpoint EAR allowlist) ───
interface PublishYamlEditorProps {
  runId: string;
  data: PublishYamlData | null;
  text: string;
  exists: boolean;
  mode: 'form' | 'raw';
  saving: boolean;
  msg: string;
  t: (k: string) => string;
  setMode: (m: 'form' | 'raw') => void;
  setData: (d: PublishYamlData) => void;
  setText: (s: string) => void;
  onSaved: (alsoCurate: boolean) => void;
}

function PublishYamlEditor({
  runId,
  data,
  text,
  exists,
  mode,
  saving,
  msg,
  t,
  setMode,
  setData,
  setText,
  onSaved,
}: PublishYamlEditorProps) {
  if (!runId) return null;
  const d: PublishYamlData = data || {};
  const includeArr: string[] = Array.isArray(d.include) ? d.include : [];
  const excludeArr: string[] = Array.isArray(d.exclude) ? d.exclude : [];
  const update = (patch: Partial<PublishYamlData>) =>
    setData({ ...d, ...patch });

  return (
    <div
      style={{
        marginTop: 10,
        padding: 10,
        border: '1px solid var(--border, #ccc)',
        borderRadius: 6,
        background: 'var(--surface-1, rgba(0,0,0,0.02))',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
        <strong>{t('py_editor_title')}</strong>
        <div style={{ display: 'flex', gap: 6 }}>
          <Button
            size="sm"
            variant={mode === 'form' ? 'primary' : 'outline'}
            onClick={() => setMode('form')}
          >
            {t('py_editor_form')}
          </Button>
          <Button
            size="sm"
            variant={mode === 'raw' ? 'primary' : 'outline'}
            onClick={() => setMode('raw')}
          >
            {t('py_editor_raw')}
          </Button>
        </div>
      </div>
      {!exists && (
        <div style={{ fontSize: '.78rem', color: 'var(--muted)', marginBottom: 8 }}>
          {t('py_editor_new_hint')}
        </div>
      )}
      {mode === 'form' ? (
        <div style={{ display: 'grid', gap: 8, fontSize: '.82rem' }}>
          <label>
            <div style={{ marginBottom: 2 }}>
              <strong>{t('py_editor_include')}</strong>{' '}
              <span style={{ color: 'var(--muted)' }}>{t('py_editor_glob_hint')}</span>
            </div>
            <textarea
              rows={3}
              value={includeArr.join('\n')}
              onChange={(e) =>
                update({
                  include: e.target.value.split('\n').map((s) => s.trim()).filter(Boolean),
                })
              }
              style={{ width: '100%', fontFamily: 'monospace' }}
            />
          </label>
          <label>
            <div style={{ marginBottom: 2 }}>
              <strong>{t('py_editor_exclude')}</strong>{' '}
              <span style={{ color: 'var(--muted)' }}>{t('py_editor_glob_hint')}</span>
            </div>
            <textarea
              rows={3}
              value={excludeArr.join('\n')}
              onChange={(e) =>
                update({
                  exclude: e.target.value.split('\n').map((s) => s.trim()).filter(Boolean),
                })
              }
              style={{ width: '100%', fontFamily: 'monospace' }}
            />
          </label>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            <label>
              <div><strong>{t('py_editor_license')}</strong></div>
              <input
                type="text"
                value={d.license || ''}
                placeholder="MIT"
                onChange={(e) => update({ license: e.target.value })}
                style={{ width: 140 }}
              />
            </label>
            <label>
              <div><strong>{t('py_editor_visibility')}</strong></div>
              <select
                value={d.visibility || 'staged'}
                onChange={(e) => update({ visibility: e.target.value })}
              >
                <option value="staged">staged</option>
                <option value="public">public</option>
                <option value="embargoed">embargoed</option>
              </select>
            </label>
            <label>
              <div><strong>{t('py_editor_max_file_mb')}</strong></div>
              <input
                type="number"
                min={1}
                value={d.max_file_mb ?? 100}
                onChange={(e) => update({ max_file_mb: Number(e.target.value) || 0 })}
                style={{ width: 80 }}
              />
            </label>
          </div>
        </div>
      ) : (
        <textarea
          rows={14}
          value={text}
          onChange={(e) => setText(e.target.value)}
          style={{ width: '100%', fontFamily: 'monospace', fontSize: '.78rem' }}
        />
      )}
      <div style={{ display: 'flex', gap: 6, marginTop: 8, alignItems: 'center' }}>
        <Button size="sm" disabled={saving} onClick={() => onSaved(false)}>
          {saving ? '…' : t('py_editor_save')}
        </Button>
        <Button size="sm" variant="outline" disabled={saving} onClick={() => onSaved(true)}>
          {saving ? '…' : t('py_editor_save_and_curate')}
        </Button>
        {msg && <span style={{ marginLeft: 6, fontFamily: 'monospace' }}>{msg}</span>}
      </div>
    </div>
  );
}

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
  const renderRepro = () => {
    if (!summary) return null;

    const repro = summary.reproducibility_report || summary.repro;
    const orsRubric = (summary as any).ors_rubric as Record<string, any> | undefined;
    const orsGrade = (summary as any).ors_grade as Record<string, any> | undefined;
    const orsPhase1 = (summary as any).ors_phase1 as Record<string, any> | undefined;
    const orsReplicator = (summary as any).ors_replicator as Record<string, any> | undefined;
    const orsSeed = (summary as any).ors_seed as Record<string, any> | undefined;
    const orsRubricMeta = (summary as any).ors_rubric_meta as Record<string, any> | undefined;
    const richMode = !!(orsRubric || orsGrade || orsPhase1 || orsReplicator || orsSeed || orsRubricMeta);

    const handleToggleReproLog = () => {
      if (reproLogOpen) { setReproLogOpen(false); return; }
      setReproLogOpen(true);
      if (selectedId) loadReproLog(selectedId);
    };
    const handleRefreshReproLog = () => {
      if (selectedId) loadReproLog(selectedId);
    };

    const reproLogPanel = reproLogOpen && (
      <div
        style={{
          border: '1px solid var(--border)',
          borderRadius: 4,
          marginBottom: 8,
          maxHeight: 320,
          overflow: 'auto',
          background: 'var(--bg)',
        }}
      >
        {reproLogPath && (
          <div
            style={{
              fontSize: '.7rem',
              color: 'var(--muted)',
              padding: '4px 8px',
              borderBottom: '1px solid var(--border)',
              fontFamily: 'monospace',
            }}
          >
            {reproLogPath}
          </div>
        )}
        {reproLogLoading ? (
          <div style={{ padding: 8, fontSize: '.8rem', color: 'var(--muted)' }}>
            {t('repro_log_loading')}
          </div>
        ) : reproLogContent ? (
          <pre
            style={{
              margin: 0, padding: '6px 10px',
              fontSize: '.72rem', lineHeight: 1.45,
              fontFamily: 'monospace',
              whiteSpace: 'pre-wrap', wordBreak: 'break-all',
              color: 'var(--text)',
            }}
          >
            {reproLogContent}
          </pre>
        ) : (
          <div style={{ padding: 8, fontSize: '.8rem', color: 'var(--muted)' }}>
            {t('repro_log_empty')}
          </div>
        )}
      </div>
    );

    const toolbar = (
      <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
        <Button
          onClick={handleToggleReproLog}
          style={{ fontSize: '.75rem', padding: '3px 10px' }}
        >
          {reproLogOpen ? t('repro_log_hide') : t('repro_log_show')}
        </Button>
        {reproLogOpen && (
          <Button
            onClick={handleRefreshReproLog}
            style={{ fontSize: '.75rem', padding: '3px 8px' }}
            disabled={reproLogLoading}
            title={t('repro_log_refresh')}
          >
            {t('repro_log_refresh')}
          </Button>
        )}
      </div>
    );

    if (richMode) {
      return (
        <Card style={{ marginBottom: 16 }}>
          <div className="card-title">{t('verify_title')}</div>
          {renderOrsChain({
            repro,
            orsRubric, orsGrade, orsPhase1, orsReplicator, orsSeed, orsRubricMeta,
            ckptId: selectedId || '',
            reproLog: {
              open: reproLogOpen,
              loading: reproLogLoading,
              content: reproLogContent,
              path: reproLogPath,
            },
            onToggleLog: handleToggleReproLog,
            onRefreshLog: handleRefreshReproLog,
            t,
          })}
        </Card>
      );
    }

    // ── Legacy renderer (pre-§4.1 reproducibility_report shape) ─────────
    return (
      <Card style={{ marginBottom: 16 }}>
        <div className="card-title">{t('verify_title')}</div>
        {toolbar}
        {reproLogPanel}
        {repro ? (
          renderLegacyRepro({ repro, t })
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

// ─── ORS chain (PaperBench-aware) renderer ──────────────────────────────
//
// Surface the per-stage status produced by the new ORS workflow:
//   ors_rubric_meta   ← generator metadata (model, leaves, expected_artifacts)
//   ors_replicator    ← LLM-driven replicator (paper → reproduce.sh)
//   ors_seed          ← fetch_code_bundle (EAR → repro_sandbox)
//   ors_phase1        ← run_reproduce (executed/exit_code/missing/sandbox)
//   ors_grade         ← SimpleJudge result (ors_score, leaf_grades[])
// Plus the synthesized ``reproducibility_report`` for the headline verdict.

type OrsRenderInput = {
  repro: any;
  orsRubric?: Record<string, any>;       // full rubric envelope (with .rubric tree)
  orsGrade?: Record<string, any>;
  orsPhase1?: Record<string, any>;
  orsReplicator?: Record<string, any>;
  orsSeed?: Record<string, any>;
  orsRubricMeta?: Record<string, any>;
  ckptId: string;
  reproLog: { open: boolean; loading: boolean; content: string | null; path: string | null };
  onToggleLog: () => void;
  onRefreshLog: () => void;
  t: (key: string) => string;
};

function renderOrsChain(input: OrsRenderInput): React.ReactNode {
  const {
    repro,
    orsRubric, orsGrade, orsPhase1, orsReplicator, orsSeed, orsRubricMeta,
    ckptId, reproLog, onToggleLog, onRefreshLog,
    t,
  } = input;

  // Headline verdict + score bar pulled from the synthesized report.
  const reproObj = (typeof repro === 'string' ? tryParseJson(repro) : repro) || {};
  const verdict = (reproObj.verdict || reproObj.status || reproObj.result || '').toString();
  const summaryText: string | undefined = reproObj.summary;

  const orsScore: number | undefined = typeof orsGrade?.ors_score === 'number'
    ? orsGrade.ors_score : undefined;
  const rawScore: number | undefined = typeof orsGrade?.raw_score === 'number'
    ? orsGrade.raw_score : undefined;
  const leafGrades: any[] = Array.isArray(orsGrade?.leaf_grades) ? orsGrade!.leaf_grades : [];
  const passed = leafGrades.filter((lg) => (lg.passed_runs ?? 0) > 0).length;
  const total = leafGrades.length;

  const badgeVariant =
    verdict === 'REPRODUCED' || verdict === 'PASS'
      ? 'green'
      : verdict === 'FAILED' || verdict === 'NOT_REPRODUCED'
        ? 'red'
        : 'yellow';

  return (
    <div>
      {/* Headline */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
        {verdict && <Badge variant={badgeVariant}>{verdict}</Badge>}
        {orsScore !== undefined && (
          <div style={{ fontSize: '.95rem', fontWeight: 600 }}>
            {(orsScore * 100).toFixed(1)}%
          </div>
        )}
        {total > 0 && (
          <div style={{ fontSize: '.78rem', color: 'var(--muted)' }}>
            {passed} / {total} {t('ors_leaves_passed_unit')}
          </div>
        )}
      </div>
      {orsScore !== undefined && (
        <ScoreBar weighted={orsScore} raw={rawScore} />
      )}
      {summaryText && (
        <div style={{ fontSize: '.85rem', color: 'var(--muted)', marginBottom: 10 }}>
          {summaryText}
        </div>
      )}

      {/* Chain stages */}
      <div style={{
        marginBottom: 12, marginTop: 12,
        fontSize: '.7rem', fontWeight: 700, color: 'var(--blue-light)',
        textTransform: 'uppercase', letterSpacing: '.04em',
      }}>
        {t('ors_chain_title')}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 12 }}>
        <ChainStage
          label={t('ors_stage_rubric')}
          state={orsRubricMeta ? 'ok' : 'pending'}
          detail={orsRubricMeta ? formatRubricStage(orsRubricMeta) : '—'}
        />
        <ChainStage
          label={t('ors_stage_replicator')}
          state={replicatorState(orsReplicator, orsSeed)}
          detail={formatReplicatorStage(orsReplicator, orsSeed)}
        />
        <ChainStage
          label={t('ors_stage_phase1')}
          state={phase1State(orsPhase1)}
          detail={formatPhase1Stage(orsPhase1)}
        />
        <ChainStage
          label={t('ors_stage_phase2')}
          state={phase2State(orsGrade)}
          detail={formatPhase2Stage(orsGrade)}
        />
      </div>

      {/* Grading tree (rebuilt from rubric tree + per-leaf grades) */}
      {orsRubric?.rubric && total > 0 && (
        <GradingTreeSection
          rubric={orsRubric.rubric as RubricNode}
          leafGrades={leafGrades}
          passed={passed}
          total={total}
          t={t}
        />
      )}
      {/* Fallback: flat per-leaf list when rubric tree is unavailable. */}
      {!orsRubric?.rubric && total > 0 && (
        <details style={{ marginBottom: 8 }}>
          <summary style={{
            cursor: 'pointer', fontSize: '.78rem', color: 'var(--muted)',
            userSelect: 'none', padding: '4px 0',
          }}>
            ▸ {t('ors_leaves_header')} ({passed} ✓ / {total - passed} ✗)
          </summary>
          <div style={{
            marginTop: 6, maxHeight: 360, overflowY: 'auto',
            border: '1px solid var(--border)', borderRadius: 4,
          }}>
            {leafGrades.map((lg, i) => (
              <LeafGradeRow key={lg.id || i} grade={lg}
                noExplanationLabel={t('ors_no_explanation')} />
            ))}
          </div>
        </details>
      )}

      {/* Generation Logs (per-stage view) */}
      <GenerationLogs
        ckptId={ckptId}
        orsRubricMeta={orsRubricMeta}
        orsRubric={orsRubric}
        orsReplicator={orsReplicator}
        orsSeed={orsSeed}
        orsPhase1={orsPhase1}
        reproLog={reproLog}
        onToggleLog={onToggleLog}
        onRefreshLog={onRefreshLog}
        t={t}
      />

      {/* Provenance footer */}
      <Provenance
        orsGrade={orsGrade}
        orsPhase1={orsPhase1}
        orsReplicator={orsReplicator}
        orsRubricMeta={orsRubricMeta}
      />
    </div>
  );
}

// ─── Grading tree section (list/tree view toggle) ────────────────────────

function GradingTreeSection({
  rubric, leafGrades, passed, total, t,
}: {
  rubric: RubricNode;
  leafGrades: any[];
  passed: number;
  total: number;
  t: (key: string) => string;
}): React.ReactNode {
  const [view, setView] = useState<'list' | 'tree'>('list');
  const gradesById = React.useMemo(() => buildGradeMap(leafGrades), [leafGrades]);
  const toggleBtn = (mode: 'list' | 'tree', label: string) => (
    <button
      type="button"
      onClick={() => setView(mode)}
      style={{
        padding: '2px 10px', fontSize: '.7rem', fontWeight: 600,
        cursor: 'pointer', border: '1px solid var(--border)',
        background: view === mode ? 'var(--blue-light, #60a5fa)' : 'transparent',
        color: view === mode ? '#0b1220' : 'var(--muted)',
        borderRadius: 4,
      }}
    >
      {label}
    </button>
  );
  return (
    <details open style={{ marginBottom: 8 }}>
      <summary
        style={{
          cursor: 'pointer', fontSize: '.78rem', color: 'var(--muted)',
          userSelect: 'none', padding: '4px 0',
        }}
      >
        ▸ {t('ors_tree_header')} ({passed} ✓ / {total - passed} ✗)
      </summary>
      <div style={{
        display: 'flex', gap: 4, marginTop: 4, marginBottom: 4,
      }}>
        {toggleBtn('list', t('ors_view_list'))}
        {toggleBtn('tree', t('ors_view_tree'))}
      </div>
      {view === 'list' ? (
        <div
          style={{
            marginTop: 6, maxHeight: 460, overflowY: 'auto',
            border: '1px solid var(--border)', borderRadius: 4,
            padding: '4px 0',
          }}
        >
          <RubricTreeNode
            node={rubric}
            gradesById={gradesById}
            depth={0}
            noExplanationLabel={t('ors_no_explanation')}
          />
        </div>
      ) : (
        <div
          style={{
            marginTop: 6,
            border: '1px solid var(--border)', borderRadius: 4,
            overflow: 'hidden',
          }}
        >
          <RubricTreeVisualization
            node={rubric}
            gradesById={gradesById}
            noExplanationLabel={t('ors_no_explanation')}
          />
        </div>
      )}
    </details>
  );
}

// ─── Rubric grading tree (recursive PaperBench TaskNode renderer) ────────

type RubricNode = {
  id?: string;
  requirements?: string;
  weight?: number;
  task_category?: string;
  finegrained_task_category?: string;
  sub_tasks?: RubricNode[];
};

type LeafGrade = Record<string, any>;

function buildGradeMap(leaves: LeafGrade[]): Map<string, LeafGrade> {
  const m = new Map<string, LeafGrade>();
  for (const lg of leaves) {
    if (lg.id) m.set(String(lg.id), lg);
  }
  return m;
}

/** Recursively aggregate weighted score over the subtree rooted at ``node``. */
function aggregateScore(
  node: RubricNode,
  gradesById: Map<string, LeafGrade>,
): { score: number | null; passed: number; total: number; valid: boolean } {
  const children = node.sub_tasks || [];
  if (children.length === 0) {
    // Leaf — read directly from the grade map.
    const g = node.id ? gradesById.get(String(node.id)) : undefined;
    if (!g) return { score: null, passed: 0, total: 1, valid: false };
    const mean = typeof g.mean_score === 'number' ? g.mean_score
      : (g.passed_runs ?? 0) > 0 ? 1 : 0;
    return {
      score: mean, passed: mean >= 0.5 ? 1 : 0, total: 1, valid: true,
    };
  }
  // Internal — weighted average of children.
  let totalWeight = 0;
  let weightedSum = 0;
  let passedLeaves = 0;
  let totalLeaves = 0;
  let anyValid = false;
  for (const c of children) {
    const cw = typeof c.weight === 'number' ? c.weight : 1;
    const sub = aggregateScore(c, gradesById);
    if (sub.valid && sub.score !== null) {
      totalWeight += cw;
      weightedSum += cw * sub.score;
      anyValid = true;
    }
    passedLeaves += sub.passed;
    totalLeaves += sub.total;
  }
  return {
    score: anyValid && totalWeight > 0 ? weightedSum / totalWeight : null,
    passed: passedLeaves,
    total: totalLeaves,
    valid: anyValid,
  };
}

function RubricTreeNode({
  node, gradesById, depth, noExplanationLabel,
}: {
  node: RubricNode;
  gradesById: Map<string, LeafGrade>;
  depth: number;
  noExplanationLabel: string;
}): React.ReactNode {
  const children = node.sub_tasks || [];
  const isLeaf = children.length === 0;
  const agg = aggregateScore(node, gradesById);
  const score = agg.score;
  const isPassed = score !== null && score >= 0.5;
  const indent = depth * 16;
  const grade = isLeaf && node.id ? gradesById.get(String(node.id)) : undefined;
  const explanation: string = String(grade?.explanation || '');

  // Color cue: green if pass, red if fail, yellow if partial
  const dotColor =
    score === null ? 'var(--muted)' :
    score >= 0.7 ? 'var(--green)' :
    score >= 0.3 ? 'var(--yellow)' :
    'var(--red)';

  const summaryRow = (
    <div
      style={{
        display: 'flex', gap: 6, alignItems: 'flex-start',
        padding: '4px 8px', paddingLeft: 8 + indent,
        fontSize: '.75rem',
        listStyle: 'none', userSelect: 'none',
      }}
    >
      <span
        style={{
          width: 10, height: 10, borderRadius: '50%',
          background: dotColor, flexShrink: 0,
          marginTop: 4,
        }}
        title={score !== null ? `score=${score.toFixed(3)}` : 'pending'}
      />
      {isLeaf && (
        <span style={{
          color: isPassed ? 'var(--green)' : 'var(--red)',
          fontWeight: 700, minWidth: 12,
        }}>
          {isPassed ? '✓' : '✗'}
        </span>
      )}
      {node.task_category && isLeaf && (
        <span style={{
          fontSize: '.62rem', color: 'var(--muted)',
          minWidth: 100, padding: '1px 4px',
          background: 'var(--surface-2, rgba(0,0,0,0.05))',
          borderRadius: 3, textAlign: 'center',
          alignSelf: 'flex-start',
        }}>
          {node.task_category}
        </span>
      )}
      <span style={{
        flex: 1, color: 'var(--text)', wordBreak: 'break-word',
        fontWeight: !isLeaf && depth === 0 ? 600 : 400,
      }}>
        {node.requirements || '(unnamed)'}
      </span>
      {!isLeaf && (
        <span style={{ fontSize: '.7rem', color: 'var(--muted)', whiteSpace: 'nowrap' }}>
          {agg.passed}/{agg.total}
          {score !== null && ` · ${(score * 100).toFixed(0)}%`}
        </span>
      )}
      {node.weight !== undefined && (
        <span style={{ fontSize: '.7rem', color: 'var(--muted)' }}>
          w={node.weight}
        </span>
      )}
    </div>
  );

  if (isLeaf) {
    return (
      <details style={{ borderBottom: '1px solid var(--border)' }}>
        <summary style={{ cursor: 'pointer', listStyle: 'none' }}>
          {summaryRow}
        </summary>
        <div style={{
          padding: `4px 8px 8px ${30 + indent}px`,
          fontSize: '.7rem', color: 'var(--muted)',
          whiteSpace: 'pre-wrap', wordBreak: 'break-word',
        }}>
          {explanation || noExplanationLabel}
        </div>
      </details>
    );
  }
  return (
    <details open={depth < 1} style={{ borderBottom: '1px solid var(--border)' }}>
      <summary style={{ cursor: 'pointer', listStyle: 'none' }}>
        {summaryRow}
      </summary>
      <div>
        {children.map((c, i) => (
          <RubricTreeNode
            key={c.id || i}
            node={c}
            gradesById={gradesById}
            depth={depth + 1}
            noExplanationLabel={noExplanationLabel}
          />
        ))}
      </div>
    </details>
  );
}

// ─── Stage-by-stage Generation Logs ───────────────────────────────────

function GenerationLogs(
  { ckptId, orsRubricMeta, orsRubric, orsReplicator, orsSeed, orsPhase1, reproLog, onToggleLog, onRefreshLog, t }:
  {
    ckptId: string;
    orsRubricMeta?: Record<string, any>;
    orsRubric?: Record<string, any>;
    orsReplicator?: Record<string, any>;
    orsSeed?: Record<string, any>;
    orsPhase1?: Record<string, any>;
    reproLog: { open: boolean; loading: boolean; content: string | null; path: string | null };
    onToggleLog: () => void;
    onRefreshLog: () => void;
    t: (key: string) => string;
  },
): React.ReactNode {
  return (
    <details style={{ marginTop: 12, marginBottom: 8 }}>
      <summary style={{
        cursor: 'pointer', fontSize: '.78rem',
        color: 'var(--blue-light)', fontWeight: 700,
        textTransform: 'uppercase', letterSpacing: '.04em',
        userSelect: 'none', padding: '4px 0',
      }}>
        📜 {t('ors_logs_title')}
      </summary>
      <div style={{
        marginTop: 4, display: 'flex', flexDirection: 'column', gap: 6,
      }}>
        {/* ① Rubric generation */}
        <LogStage
          label={t('ors_stage_rubric')}
          summary={
            orsRubricMeta
              ? `${orsRubricMeta.model || '?'} · ${orsRubricMeta.leaves_count ?? '?'} leaves`
              + (orsRubricMeta.target_leaf_count
                  ? ` · target=${orsRubricMeta.target_leaf_count}` : '')
              : '—'
          }
          warnings={(orsRubricMeta?.warnings as string[]) || []}
        >
          {orsRubricMeta && (
            <KvList
              items={[
                ['model', orsRubricMeta.model],
                ['leaves_count', orsRubricMeta.leaves_count],
                ['depth', orsRubricMeta.depth],
                ['target_leaf_count', orsRubricMeta.target_leaf_count],
                ['auto_computed_target', orsRubricMeta.auto_computed_target],
                ['paper_sha256', truncSha(orsRubricMeta.paper_sha256)],
                ['rubric_sha256', truncSha(orsRubricMeta.rubric_sha256)],
                ['prompt_sha256', truncSha(orsRubricMeta.prompt_sha256)],
              ]}
            />
          )}
          {orsRubricMeta?.category_breakdown && (
            <KvList items={
              Object.entries(orsRubricMeta.category_breakdown as Record<string, any>)
                .map(([k, v]) => [`category::${k}`, v])
            } />
          )}
          {orsRubric?.reproduce_contract && (
            <KvList items={[
              ['expected_artifacts',
                JSON.stringify(orsRubric.reproduce_contract.expected_artifacts || [])],
              ['max_runtime_sec', orsRubric.reproduce_contract.max_runtime_sec],
            ]} />
          )}
        </LogStage>

        {/* ② Replicator (or EAR seed) */}
        <LogStage
          label={t('ors_stage_replicator')}
          summary={(() => {
            if (orsSeed?.populated) {
              return `EAR-seeded · ${fileCount(orsSeed.files)} files`;
            }
            if (orsReplicator?.populated) {
              return `LLM (${orsReplicator.model || '?'}) · ${fileCount(orsReplicator.files)} files`;
            }
            return '—';
          })()}
          warnings={(orsReplicator?.warnings as string[]) || []}
        >
          {orsSeed?.populated && (
            <KvList items={[
              ['mode', 'EAR / curated bundle'],
              ['files', formatFiles(orsSeed.files)],
              ['bundle_sha256', truncSha(orsSeed.bundle_sha256)],
              ['dest', orsSeed.dest],
            ]} />
          )}
          {orsReplicator?.populated && (
            <>
              <KvList items={[
                ['mode', 'LLM (paper → reproduce.sh)'],
                ['model', orsReplicator.model],
                ['language', orsReplicator.language],
                ['max_runtime_sec', orsReplicator.max_runtime_sec],
                ['files', formatFiles(orsReplicator.files)],
                ['expected_artifacts',
                  JSON.stringify(orsReplicator.expected_artifacts || [])],
                ['prompt_sha256', truncSha(orsReplicator.prompt_sha256)],
              ]} />
              {orsReplicator.notes && (
                <CollapsibleText label="notes" content={String(orsReplicator.notes)} />
              )}
            </>
          )}
          {orsReplicator?.error && (
            <KvList items={[['error', String(orsReplicator.error)]]} />
          )}
          {/* File viewers — fetch reproduce.sh and any source on demand. */}
          {(orsReplicator?.populated || orsSeed?.populated) && ckptId && (
            <FileViewers
              ckptId={ckptId}
              files={asFileList(orsReplicator?.files ?? orsSeed?.files)}
              prefix="repro_sandbox"
            />
          )}
        </LogStage>

        {/* ③ Phase 1 (build/run) — folds the existing reproduce.log toggle */}
        <LogStage
          label={t('ors_stage_phase1')}
          summary={(() => {
            if (!orsPhase1) return '—';
            if (!orsPhase1.executed) return orsPhase1.skipped_reason || 'skipped';
            const sb = orsPhase1.sandbox_kind || '?';
            const part = orsPhase1.partition ? `:${orsPhase1.partition}` : '';
            return `${sb}${part} · exit ${orsPhase1.exit_code} `
              + `· ${typeof orsPhase1.elapsed_sec === 'number' ? orsPhase1.elapsed_sec.toFixed(1) : '?'}s`;
          })()}
        >
          {orsPhase1 && (
            <KvList items={[
              ['executed', orsPhase1.executed],
              ['exit_code', orsPhase1.exit_code],
              ['sandbox_kind', orsPhase1.sandbox_kind],
              ['partition', orsPhase1.partition],
              ['cpus', orsPhase1.cpus],
              ['walltime', orsPhase1.walltime],
              ['elapsed_sec', orsPhase1.elapsed_sec],
              ['missing', JSON.stringify(orsPhase1.missing || [])],
              ['artifacts', `${(orsPhase1.artifacts || []).length} files`],
            ]} />
          )}
          <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
            <Button onClick={onToggleLog} style={{ fontSize: '.7rem', padding: '2px 8px' }}>
              {reproLog.open ? t('repro_log_hide') : t('repro_log_show')}
            </Button>
            {reproLog.open && (
              <Button
                onClick={onRefreshLog}
                style={{ fontSize: '.7rem', padding: '2px 8px' }}
                disabled={reproLog.loading}
                title={t('repro_log_refresh')}
              >
                {t('repro_log_refresh')}
              </Button>
            )}
          </div>
          {reproLog.open && (
            <div style={{
              border: '1px solid var(--border)', borderRadius: 4,
              marginTop: 6, maxHeight: 320, overflow: 'auto',
              background: 'var(--bg)',
            }}>
              {reproLog.path && (
                <div style={{
                  fontSize: '.66rem', color: 'var(--muted)',
                  padding: '4px 8px', borderBottom: '1px solid var(--border)',
                  fontFamily: 'monospace',
                }}>
                  {reproLog.path}
                </div>
              )}
              {reproLog.loading ? (
                <div style={{ padding: 8, fontSize: '.72rem', color: 'var(--muted)' }}>
                  {t('repro_log_loading')}
                </div>
              ) : reproLog.content ? (
                <pre style={{
                  margin: 0, padding: '6px 10px',
                  fontSize: '.68rem', lineHeight: 1.45,
                  fontFamily: 'monospace',
                  whiteSpace: 'pre-wrap', wordBreak: 'break-all',
                  color: 'var(--text)',
                }}>
                  {reproLog.content}
                </pre>
              ) : (
                <div style={{ padding: 8, fontSize: '.72rem', color: 'var(--muted)' }}>
                  {t('repro_log_empty')}
                </div>
              )}
            </div>
          )}
        </LogStage>
      </div>
    </details>
  );
}

function LogStage(
  { label, summary, warnings, children }: {
    label: string;
    summary: string;
    warnings?: string[];
    children?: React.ReactNode;
  },
): React.ReactNode {
  return (
    <details style={{
      border: '1px solid var(--border)', borderRadius: 4,
      background: 'var(--surface-2, rgba(0,0,0,0.02))',
    }}>
      <summary style={{
        cursor: 'pointer', padding: '6px 10px',
        fontSize: '.75rem', userSelect: 'none',
        display: 'flex', gap: 8, alignItems: 'baseline',
      }}>
        <span style={{ fontWeight: 600, minWidth: 160 }}>{label}</span>
        <span style={{ flex: 1, color: 'var(--muted)' }}>{summary}</span>
        {warnings && warnings.length > 0 && (
          <span style={{ fontSize: '.7rem', color: 'var(--yellow)' }}>
            ⚠ {warnings.length}
          </span>
        )}
      </summary>
      <div style={{ padding: '4px 12px 8px 24px' }}>
        {children}
        {warnings && warnings.length > 0 && (
          <CollapsibleText
            label="warnings"
            content={warnings.map((w) => `• ${w}`).join('\n')}
          />
        )}
      </div>
    </details>
  );
}

function KvList({ items }: { items: Array<[string, any]> }): React.ReactNode {
  const visible = items.filter(([_, v]) => v !== undefined && v !== null && v !== '');
  if (visible.length === 0) return null;
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: 'auto 1fr',
      columnGap: 8, rowGap: 2, fontSize: '.7rem',
      fontFamily: 'monospace', marginTop: 4,
    }}>
      {visible.map(([k, v]) => (
        <React.Fragment key={k}>
          <span style={{ color: 'var(--muted)' }}>{k}:</span>
          <span style={{ wordBreak: 'break-all', color: 'var(--text)' }}>{String(v)}</span>
        </React.Fragment>
      ))}
    </div>
  );
}

function CollapsibleText({ label, content }: { label: string; content: string }): React.ReactNode {
  return (
    <details style={{ marginTop: 6 }}>
      <summary style={{
        cursor: 'pointer', fontSize: '.7rem', color: 'var(--muted)',
        userSelect: 'none',
      }}>
        ▸ {label}
      </summary>
      <pre style={{
        margin: '4px 0 0 0', padding: '6px 8px',
        fontSize: '.68rem', lineHeight: 1.45,
        fontFamily: 'monospace',
        whiteSpace: 'pre-wrap', wordBreak: 'break-word',
        background: 'var(--bg)',
        border: '1px solid var(--border)', borderRadius: 4,
        maxHeight: 240, overflow: 'auto',
      }}>
        {content}
      </pre>
    </details>
  );
}

function FileViewers(
  { ckptId, files, prefix }: { ckptId: string; files: string[]; prefix?: string },
): React.ReactNode {
  // Show a "Show <file>" button per file; lazily fetch + cache content.
  const codeFiles = files.filter((f) =>
    /\.(sh|py|cpp|c|h|hpp|js|ts|rs|go|java|R|jl|m|tex|md|txt|json|yaml|yml|toml)$/i.test(f)
  );
  if (codeFiles.length === 0) return null;
  return (
    <div style={{ marginTop: 6 }}>
      {codeFiles.map((f) => (
        <FileViewer
          key={f}
          ckptId={ckptId}
          path={prefix ? `${prefix}/${f}` : f}
          label={f}
        />
      ))}
    </div>
  );
}

function FileViewer(
  { ckptId, path, label }: { ckptId: string; path: string; label: string },
): React.ReactNode {
  const [open, setOpen] = useState(false);
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleToggle = async () => {
    if (open) { setOpen(false); return; }
    setOpen(true);
    if (content !== null) return;
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(
        `/api/checkpoint/${encodeURIComponent(ckptId)}/filecontent?path=${encodeURIComponent(path)}`,
      );
      if (!r.ok) {
        setError(`HTTP ${r.status}`);
      } else {
        const j = await r.json();
        setContent(typeof j.content === 'string' ? j.content : JSON.stringify(j, null, 2));
      }
    } catch (e: any) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ marginTop: 4 }}>
      <Button
        onClick={handleToggle}
        style={{ fontSize: '.7rem', padding: '2px 8px' }}
      >
        {open ? `▾ ${label}` : `▸ ${label}`}
      </Button>
      {open && (
        <div style={{
          marginTop: 4,
          border: '1px solid var(--border)', borderRadius: 4,
          maxHeight: 320, overflow: 'auto',
          background: 'var(--bg)',
        }}>
          {loading ? (
            <div style={{ padding: 8, fontSize: '.7rem', color: 'var(--muted)' }}>
              loading…
            </div>
          ) : error ? (
            <div style={{ padding: 8, fontSize: '.7rem', color: 'var(--red)' }}>
              {error}
            </div>
          ) : (
            <pre style={{
              margin: 0, padding: '6px 10px',
              fontSize: '.66rem', lineHeight: 1.4,
              fontFamily: 'monospace',
              whiteSpace: 'pre', overflow: 'auto',
              color: 'var(--text)',
            }}>
              {content}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

function truncSha(s: any): string | undefined {
  if (typeof s !== 'string' || !s) return undefined;
  return s.length > 16 ? `${s.slice(0, 16)}…` : s;
}

// `files` is either a list of paths (replicator) or an int file_count (EAR seed).
function fileCount(files: unknown): number {
  if (Array.isArray(files)) return files.length;
  if (typeof files === 'number' && Number.isFinite(files)) return files;
  return 0;
}

function asFileList(files: unknown): string[] {
  return Array.isArray(files) ? (files as string[]) : [];
}

function formatFiles(files: unknown): string {
  if (Array.isArray(files)) return files.join(', ');
  if (typeof files === 'number' && Number.isFinite(files)) return `${files} files`;
  return '';
}

function ScoreBar({ weighted, raw }: { weighted: number; raw?: number }): React.ReactNode {
  const wpct = Math.max(0, Math.min(1, weighted)) * 100;
  const rpct = raw !== undefined ? Math.max(0, Math.min(1, raw)) * 100 : null;
  const fillColor = wpct >= 70 ? 'var(--green)' : wpct >= 30 ? 'var(--yellow)' : 'var(--red)';
  return (
    <div style={{ marginBottom: 10 }}>
      <div
        style={{
          width: '100%', height: 8, background: 'var(--bg)',
          border: '1px solid var(--border)', borderRadius: 4, overflow: 'hidden',
          position: 'relative',
        }}
      >
        <div
          style={{
            width: `${wpct}%`, height: '100%',
            background: fillColor, transition: 'width 0.3s ease',
          }}
        />
        {rpct !== null && (
          <div
            style={{
              position: 'absolute', top: 0, left: `${rpct}%`,
              width: 2, height: '100%', background: 'var(--text)', opacity: 0.5,
            }}
            title={`raw=${(rpct).toFixed(1)}%`}
          />
        )}
      </div>
      <div style={{ fontSize: '.7rem', color: 'var(--muted)', marginTop: 2 }}>
        weighted {weighted.toFixed(3)}
        {raw !== undefined && ` · raw ${raw.toFixed(3)}`}
      </div>
    </div>
  );
}

type StageState = 'ok' | 'fail' | 'partial' | 'pending' | 'skipped';

function ChainStage(
  { label, state, detail }: { label: string; state: StageState; detail: React.ReactNode },
): React.ReactNode {
  const icon = state === 'ok' ? '✓' : state === 'fail' ? '✗' : state === 'partial' ? '◐' : '·';
  const color =
    state === 'ok' ? 'var(--green)' :
    state === 'fail' ? 'var(--red)' :
    state === 'partial' ? 'var(--yellow)' :
    'var(--muted)';
  return (
    <div
      style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '4px 8px',
        background: 'var(--surface-2, rgba(0,0,0,0.04))',
        borderRadius: 4,
      }}
    >
      <span
        style={{
          width: 18, height: 18, lineHeight: '18px',
          textAlign: 'center', borderRadius: '50%',
          background: color, color: 'var(--bg)',
          fontSize: '.7rem', fontWeight: 700, flexShrink: 0,
        }}
      >
        {icon}
      </span>
      <span style={{ fontSize: '.78rem', fontWeight: 600, minWidth: 160 }}>
        {label}
      </span>
      <span style={{ fontSize: '.75rem', color: 'var(--muted)', flex: 1, wordBreak: 'break-word' }}>
        {detail}
      </span>
    </div>
  );
}

function formatRubricStage(meta: Record<string, any>): React.ReactNode {
  const leaves = meta.leaves_count;
  const model = meta.model;
  const artifacts = (meta as any).expected_artifacts;
  const parts: string[] = [];
  if (typeof leaves === 'number') parts.push(`${leaves} leaves`);
  if (model) parts.push(String(model));
  if (Array.isArray(artifacts) && artifacts.length) {
    parts.push(`${artifacts.length} expected artifacts`);
  }
  return parts.join(' · ') || JSON.stringify(meta).slice(0, 120);
}

function replicatorState(
  replicator: Record<string, any> | undefined,
  seed: Record<string, any> | undefined,
): StageState {
  if (seed?.populated) return 'ok';            // EAR seed wins
  if (replicator?.populated) return 'ok';
  if (replicator?.error) return 'fail';
  return 'pending';
}

function formatReplicatorStage(
  replicator: Record<string, any> | undefined,
  seed: Record<string, any> | undefined,
): React.ReactNode {
  if (seed?.populated) {
    return `EAR-seeded · ${fileCount(seed.files)} files`
      + (seed.bundle_sha256 ? ` · ${String(seed.bundle_sha256).slice(0, 12)}…` : '');
  }
  if (replicator?.populated) {
    return `LLM (${replicator.model || '?'}) · ${fileCount(replicator.files)} files`;
  }
  if (replicator?.error) return `error: ${String(replicator.error).slice(0, 100)}`;
  if (replicator?.skipped_reason) return `skipped: ${replicator.skipped_reason}`;
  return '—';
}

function phase1State(p1: Record<string, any> | undefined): StageState {
  if (!p1) return 'pending';
  if (p1.executed === false) return 'skipped';
  if (p1.exit_code === 0 && (!p1.missing || p1.missing.length === 0)) return 'ok';
  if (p1.exit_code === 0) return 'partial';   // ran but artifacts missing
  return 'fail';
}

function formatPhase1Stage(p1: Record<string, any> | undefined): React.ReactNode {
  if (!p1) return '—';
  if (p1.executed === false) return p1.skipped_reason || 'skipped';
  const sandbox = p1.sandbox_kind || '?';
  const partition = p1.partition ? `:${p1.partition}` : '';
  const exit_ = p1.exit_code !== undefined ? `exit ${p1.exit_code}` : '';
  const elapsed = typeof p1.elapsed_sec === 'number' ? `${p1.elapsed_sec.toFixed(1)}s` : '';
  const missing = p1.missing && p1.missing.length ? `${p1.missing.length} missing` : '0 missing';
  return [`${sandbox}${partition}`, exit_, elapsed, missing].filter(Boolean).join(' · ');
}

function phase2State(grade: Record<string, any> | undefined): StageState {
  if (!grade) return 'pending';
  if (grade.error || grade._parse_error) return 'fail';
  if (grade.degraded) return 'partial';
  if (typeof grade.ors_score === 'number') {
    if (grade.ors_score >= 0.7) return 'ok';
    if (grade.ors_score >= 0.3) return 'partial';
    return 'fail';
  }
  return 'pending';
}

function formatPhase2Stage(grade: Record<string, any> | undefined): React.ReactNode {
  if (!grade) return '—';
  if (grade.error) return `error: ${String(grade.error).slice(0, 100)}`;
  const score = typeof grade.ors_score === 'number' ? `${(grade.ors_score * 100).toFixed(1)}%` : '?';
  const judge = grade.judge_model || '?';
  const nRuns = grade.n_runs ? `n_runs=${grade.n_runs}` : '';
  const elapsed = typeof grade.elapsed_sec === 'number' ? `${grade.elapsed_sec.toFixed(1)}s` : '';
  const degraded = grade.degraded ? '⚠ degraded' : '';
  return [score, judge, nRuns, elapsed, degraded].filter(Boolean).join(' · ');
}

function LeafGradeRow({ grade, noExplanationLabel }: {
  grade: Record<string, any>;
  noExplanationLabel?: string;
}): React.ReactNode {
  const passed = (grade.passed_runs ?? 0) > 0;
  const cat = grade.task_category || '—';
  const explanation: string = String(grade.explanation || '');
  return (
    <details style={{ borderBottom: '1px solid var(--border)' }}>
      <summary
        style={{
          cursor: 'pointer', padding: '6px 8px', display: 'flex',
          gap: 8, alignItems: 'flex-start', fontSize: '.75rem',
          listStyle: 'none', userSelect: 'none',
        }}
      >
        <span style={{
          color: passed ? 'var(--green)' : 'var(--red)',
          fontWeight: 700, minWidth: 14,
        }}>
          {passed ? '✓' : '✗'}
        </span>
        <span style={{
          fontSize: '.65rem', color: 'var(--muted)',
          minWidth: 110, padding: '1px 4px',
          background: 'var(--surface-2, rgba(0,0,0,0.05))',
          borderRadius: 3, textAlign: 'center',
          alignSelf: 'flex-start',
        }}>
          {cat}
        </span>
        <span style={{ flex: 1, color: 'var(--text)', wordBreak: 'break-word' }}>
          {grade.requirements}
        </span>
        {grade.weight !== undefined && (
          <span style={{ fontSize: '.7rem', color: 'var(--muted)' }}>
            w={grade.weight}
          </span>
        )}
      </summary>
      <div
        style={{
          padding: '4px 8px 8px 30px',
          fontSize: '.72rem', color: 'var(--muted)',
          whiteSpace: 'pre-wrap', wordBreak: 'break-word',
        }}
      >
        {explanation || noExplanationLabel || '(no explanation)'}
      </div>
    </details>
  );
}

function Provenance(
  { orsGrade, orsPhase1, orsReplicator, orsRubricMeta }:
  {
    orsGrade?: Record<string, any>;
    orsPhase1?: Record<string, any>;
    orsReplicator?: Record<string, any>;
    orsRubricMeta?: Record<string, any>;
  },
): React.ReactNode {
  const items: [string, string][] = [];
  if (orsGrade?.rubric_sha256) {
    items.push(['rubric_sha256', String(orsGrade.rubric_sha256).slice(0, 16) + '…']);
  }
  if (orsRubricMeta?.prompt_sha256) {
    items.push(['rubric_prompt_sha256', String(orsRubricMeta.prompt_sha256).slice(0, 16) + '…']);
  }
  if (orsReplicator?.prompt_sha256) {
    items.push(['replicator_prompt_sha256', String(orsReplicator.prompt_sha256).slice(0, 16) + '…']);
  }
  if (orsPhase1?.partition) {
    items.push(['partition', String(orsPhase1.partition)]);
  }
  if (orsPhase1?.cpus) {
    items.push(['cpus', String(orsPhase1.cpus)]);
  }
  if (orsPhase1?.walltime) {
    items.push(['walltime', String(orsPhase1.walltime)]);
  }
  if (!items.length) return null;
  return (
    <div
      style={{
        marginTop: 10, paddingTop: 8,
        borderTop: '1px solid var(--border)',
        fontSize: '.7rem', color: 'var(--muted)',
        fontFamily: 'monospace', display: 'grid',
        gridTemplateColumns: 'auto 1fr', columnGap: 8, rowGap: 2,
      }}
    >
      {items.map(([k, v]) => (
        <React.Fragment key={k}>
          <span>{k}:</span>
          <span style={{ wordBreak: 'break-all' }}>{v}</span>
        </React.Fragment>
      ))}
    </div>
  );
}

// ─── Legacy renderer (pre-§4.1 reproducibility_report shape) ───────────

function renderLegacyRepro({ repro, t }: { repro: any; t: (key: string) => string }): React.ReactNode {
  const reproObj = (typeof repro === 'string' ? tryParseJson(repro) : repro);

  if (!reproObj || typeof reproObj !== 'object') {
    return <div style={{ fontSize: '.85rem', color: 'var(--muted)' }}>{String(repro)}</div>;
  }

  const reproRecord = reproObj as Record<string, any>;

  // Skill-not-found error
  if (
    reproRecord.error &&
    (String(reproRecord.error).indexOf('not found') >= 0 ||
      String(reproRecord.error).indexOf('Tool') >= 0 ||
      String(reproRecord.error).indexOf('Available: []') >= 0)
  ) {
    return (
      <>
        <div style={{ color: 'var(--yellow)', fontSize: '.85rem', padding: 8 }}>
          {t('repro_skill_unavail')}
        </div>
        <details>
          <summary
            style={{ fontSize: '.75rem', color: 'var(--muted)', cursor: 'pointer' }}
          >
            {t('details')}
          </summary>
          <pre style={{ fontSize: '.72rem', color: 'var(--muted)', marginTop: 4 }}>
            {reproRecord.error}
          </pre>
        </details>
      </>
    );
  }

  const verdict = reproRecord.verdict || reproRecord.status || reproRecord.result || 'unknown';
  const badgeVariant =
    verdict === 'REPRODUCED' || verdict === 'PASS' || verdict === 'pass'
      ? 'green'
      : verdict === 'FAILED' || verdict === 'FAIL' || verdict === 'fail' || verdict === 'NOT_REPRODUCED'
        ? 'red'
        : 'yellow';

  const skip = new Set(['verdict', 'status', 'result', 'summary']);

  return (
    <>
      <div style={{ fontSize: '1.1rem', marginBottom: 8 }}>
        <Badge variant={badgeVariant}>{verdict}</Badge>
      </div>
      {reproRecord.summary && (
        <div style={{ fontSize: '.85rem', color: 'var(--muted)', marginBottom: 8 }}>
          {reproRecord.summary}
        </div>
      )}
      {Object.keys(reproRecord)
        .filter((k) => !skip.has(k))
        .slice(0, 8)
        .map((k) => (
          <div key={k} style={{ fontSize: '.8rem', marginTop: 4 }}>
            <span style={{ color: 'var(--muted)' }}>{k}:</span>{' '}
            {JSON.stringify(reproRecord[k])}
          </div>
        ))}
    </>
  );
}
