import { useState } from 'react';
import { useT } from '../../i18n';

interface LicenseAssessment {
  license: string;
  permissive: boolean;
  modifiable: boolean;
  redistributable: boolean;
  usable: boolean;
  note: string;
}

/**
 * PaperImportDialog — minimal form for registering an external paper.
 *
 * Posts to /api/paperbench/papers/import with the canonical body shape
 * (source_type / source / title / license / authors / year /
 * artifact_url). License input is locally classified through the same
 * endpoint set so the "✅ usable / ⚠ NOT usable" badge mirrors the
 * server-side determination.
 *
 * v0.7.4: source_type=upload now uploads the selected PDF via the existing
 * /api/upload endpoint and forwards the staged path as pdf_path so the
 * backend (_api_import_paper) materializes it under the registry directory.
 */
export function PaperImportDialog() {
  const t = useT();
  const [sourceType, setSourceType] = useState<'arxiv' | 'doi' | 'upload' | 'local'>('arxiv');
  const [source, setSource] = useState('');
  const [title, setTitle] = useState('');
  const [authors, setAuthors] = useState('');
  const [year, setYear] = useState<string>('');
  const [venue, setVenue] = useState('');
  const [licenseRaw, setLicenseRaw] = useState('CC BY 4.0');
  const [artifactUrl, setArtifactUrl] = useState('');
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [pdfStagedPath, setPdfStagedPath] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [fetching, setFetching] = useState(false);
  const [fetchInfo, setFetchInfo] = useState<string | null>(null);
  const [result, setResult] = useState<{ error?: string; paper_id?: string } | null>(null);

  // Optimistic local classification (the server returns the authoritative
  // assessment in the response). Mirrors the server's _classify_license.
  const usable = /^cc(\s|-)by(\s|-)?(4\.?0)?$|^(mit|apache|bsd|arxiv)/i.test(licenseRaw.trim());

  const fetchArxiv = async () => {
    if (!source) return;
    setFetching(true);
    setFetchInfo(null);
    try {
      const r = await fetch(`/api/paperbench/arxiv/${encodeURIComponent(source)}`).then((rr) =>
        rr.json(),
      );
      if (r.error) {
        setFetchInfo(`✗ ${r.error}`);
      } else {
        if (r.title) setTitle(r.title);
        if (Array.isArray(r.authors)) setAuthors(r.authors.join(', '));
        if (r.year) setYear(String(r.year));
        if (r.license) setLicenseRaw(r.license);
        setFetchInfo(`✓ ${r.title}`);
      }
    } catch (e) {
      setFetchInfo(`✗ ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setFetching(false);
    }
  };

  const stageUpload = async (file: File): Promise<string> => {
    const form = new FormData();
    form.append('file', file, file.name);
    const r = await fetch('/api/upload', { method: 'POST', body: form });
    const data: { ok?: boolean; path?: string; error?: string } = await r.json();
    if (!data.ok || !data.path) {
      throw new Error(data.error || 'upload failed');
    }
    return data.path;
  };

  const onPickFile = (file: File | null) => {
    setPdfFile(file);
    setPdfStagedPath(null);
    if (file && !source) {
      // Default the source identifier to the filename stem so the resulting
      // paper_id is human-readable when the user does not override it.
      setSource(file.name.replace(/\.pdf$/i, ''));
    }
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (sourceType === 'upload' && !pdfFile && !pdfStagedPath) {
      setResult({ error: t('pb_pdf_required') });
      return;
    }
    setSubmitting(true);
    setResult(null);
    try {
      let pdfPath = pdfStagedPath;
      if (sourceType === 'upload' && pdfFile && !pdfPath) {
        setUploading(true);
        try {
          pdfPath = await stageUpload(pdfFile);
          setPdfStagedPath(pdfPath);
        } finally {
          setUploading(false);
        }
      }
      const body: Record<string, unknown> = {
        source_type: sourceType,
        source,
        title,
        license: licenseRaw,
        authors: authors
          .split(/[,;]/)
          .map((a) => a.trim())
          .filter(Boolean),
        year: year ? parseInt(year, 10) : null,
        venue,
        artifact_url: artifactUrl,
      };
      if (pdfPath) body.pdf_path = pdfPath;
      const r = await fetch('/api/paperbench/papers/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data: LicenseAssessment & { paper_id?: string; error?: string } = await r.json();
      setResult(data);
      if (!data.error) {
        // Navigate back to the registry after success.
        setTimeout(() => (window.location.hash = '/paperbench'), 600);
      }
    } catch (err) {
      setResult({ error: err instanceof Error ? err.message : String(err) });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{ padding: 28, maxWidth: 720 }}>
      <h2>📥 {t('pb_import_title')}</h2>
      <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <label>
          {t('pb_source_type')}
          <select value={sourceType} onChange={(e) => setSourceType(e.target.value as 'arxiv' | 'doi' | 'upload' | 'local')}>
            <option value="arxiv">arXiv ID</option>
            <option value="doi">DOI</option>
            <option value="upload">Upload PDF</option>
            <option value="local">Local path</option>
          </select>
        </label>
        {sourceType === 'upload' && (
          <label>
            {t('pb_pdf_file')}
            <input
              type="file"
              accept="application/pdf,.pdf"
              aria-label={t('pb_pdf_file')}
              onChange={(e) => onPickFile(e.target.files?.[0] ?? null)}
            />
            {pdfFile && (
              <div style={{ fontSize: 12, marginTop: 4, color: '#333' }}>
                {pdfStagedPath ? `✓ ${t('pb_uploaded')}: ` : ''}
                <code>{pdfFile.name}</code>
                {uploading && <span style={{ marginLeft: 8 }}>{t('pb_uploading')}</span>}
              </div>
            )}
          </label>
        )}
        <label>
          {t('pb_source_id')}
          <div style={{ display: 'flex', gap: 8 }}>
            <input
              value={source}
              onChange={(e) => setSource(e.target.value)}
              required
              style={{ flex: 1 }}
            />
            {sourceType === 'arxiv' && (
              <button
                type="button"
                onClick={() => void fetchArxiv()}
                disabled={fetching || !source}
              >
                {fetching ? t('pb_fetching') : t('pb_fetch_metadata')}
              </button>
            )}
          </div>
          {fetchInfo && (
            <div
              style={{
                fontSize: 12,
                marginTop: 4,
                color: fetchInfo.startsWith('✓') ? '#080' : '#a40',
              }}
            >
              {fetchInfo}
            </div>
          )}
        </label>
        <label>
          {t('pb_title_field')}
          <input value={title} onChange={(e) => setTitle(e.target.value)} required />
        </label>
        <label>
          {t('pb_authors')} ({t('pb_comma_sep')})
          <input value={authors} onChange={(e) => setAuthors(e.target.value)} />
        </label>
        <div style={{ display: 'flex', gap: 12 }}>
          <label style={{ flex: 1 }}>
            {t('pb_venue')}
            <input value={venue} onChange={(e) => setVenue(e.target.value)} />
          </label>
          <label style={{ width: 120 }}>
            {t('pb_year')}
            <input value={year} onChange={(e) => setYear(e.target.value)} />
          </label>
        </div>
        <label>
          {t('pb_license_field')}
          <input value={licenseRaw} onChange={(e) => setLicenseRaw(e.target.value)} />
          <div style={{ fontSize: 12, color: usable ? '#080' : '#a40' }}>
            {usable ? `✅ ${t('pb_license_usable')}` : `⚠ ${t('pb_license_review')}`}
          </div>
        </label>
        <label>
          {t('pb_artifact_url')}
          <input value={artifactUrl} onChange={(e) => setArtifactUrl(e.target.value)} />
        </label>

        <div style={{ display: 'flex', gap: 12 }}>
          <button type="submit" disabled={submitting || uploading}>
            {uploading ? t('pb_uploading') : submitting ? t('pb_saving') : t('pb_save')}
          </button>
          <button type="button" onClick={() => (window.location.hash = '/paperbench')}>
            {t('pb_cancel')}
          </button>
        </div>

        {result?.error && (
          <div style={{ color: '#d33', padding: 12, background: '#fee' }}>{result.error}</div>
        )}
        {result?.paper_id && !result.error && (
          <div style={{ color: '#080', padding: 12, background: '#efe' }}>
            ✓ {t('pb_saved')}: {result.paper_id}
          </div>
        )}
      </form>
    </div>
  );
}
