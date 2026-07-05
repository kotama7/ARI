import React, { useEffect, useState, useCallback, useRef } from 'react';
import { useI18n } from '../../i18n';
import { useAppContext } from '../../context/AppContext';
import {
  fetchCheckpointSummary,
  fetchEAR,
  fetchCheckpointFiles,
  fetchCheckpointFileContent,
  fetchCheckpointFilecontent,
  saveCheckpointFile,
  uploadCheckpointFile,
  deleteCheckpointFile,
  compileCheckpointPaper,
} from '../../services/api';
import type {
  EARData, CheckpointFile,
} from '../../services/api';
import type { CheckpointSummary } from '../../types';
import { Button } from '../common/Button';
import { LoadingState, EmptyState, ErrorState } from '../common';
import { EarSection } from './EarSection';
import { renderPaper } from './PaperWorkspace';
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


  // State for absolute path of the active file (for binary preview via /codefile)
  const [activeAbsPath, setActiveAbsPath] = useState('');


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
        {loading && <LoadingState inline />}

        {error && (
          <ErrorState message={`${t('error_prefix')}${error}`} />
        )}

        {!loading && !error && !selectedId && (
          <EmptyState icon={'📊'} message={t('select_exp')} />
        )}

        {!loading && !error && summary && (
          <>
            {renderPaper({
              summary, selectedId, t,
              paperView, setPaperView,
              activeFile, setActiveFile,
              editorContent, setEditorContent, editorDirty, setEditorDirty,
              editorSaving, editorMsg, setEditorMsg, fileLoading, setFileLoading,
              compiling, compileLog, setCompileLog,
              ckptFiles, collapsedDirs, setCollapsedDirs,
              activeAbsPath, setActiveAbsPath, uploadRef,
              openFile, handleSave, handleUpload, handleDeleteFile, handleCompile,
            })}
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
            <EarSection
              ear={ear}
              earLoading={earLoading}
              selectedId={selectedId}
              setEar={setEar}
              t={t}
            />
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
                <EmptyState icon={'📊'} message={t('results_empty')} />
              )}
          </>
        )}
      </div>
    </div>
  );
}

