// ARI Dashboard – EAR (Experiment Artifact Repository) section.
// Extracted from ResultsPage.tsx renderEAR (refactor req 15, optional §3 high-risk
// seam). JSX body is verbatim; the curate/publish/py-editor state now comes from
// useEAR() and the data-spine bits (ear/earLoading/selectedId/setEar) + t are
// props. Rendered unconditionally where renderEAR() was called, so it stays
// mounted across ear transitions — action-state persistence is unchanged.

import { useEAR } from './useEAR';
import { Card } from '../common/Card';
import { Button } from '../common/Button';
import { Badge } from '../common/Badge';
import { LoadingState } from '../common';
import { PublishYamlEditor } from './PublishYamlEditor';
import {
  curateEAR,
  fetchEAR,
  fetchPublishYaml,
  savePublishYaml,
  runPublish,
  fetchPublishRecord,
  promotePublish,
} from '../../services/api';
import type { EARData, EARCurateResult, PublishRunResult } from '../../services/api';

export function EarSection({
  ear,
  earLoading,
  selectedId,
  setEar,
  t,
}: {
  ear: EARData | null;
  earLoading: boolean;
  selectedId: string;
  setEar: (e: EARData | null) => void;
  t: (key: string) => string;
}) {
  const {
    curating, setCurating, curateMsg, setCurateMsg,
    publishing, setPublishing, publishMsg, setPublishMsg,
    publishRecord, setPublishRecord, publishBackend, setPublishBackend,
    publishConsent, setPublishConsent,
    pyEditorOpen, setPyEditorOpen, pyData, setPyData,
    pyText, setPyText, pyExists, setPyExists,
    pyMode, setPyMode, pySaving, setPySaving, pyMsg, setPyMsg,
  } = useEAR();

    if (earLoading) {
      return (
        <Card style={{ marginBottom: 16 }}>
          <div className="card-title">{'📦'} Artifact Repository</div>
          <LoadingState inline label={t('loading_ear')} />
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
}
