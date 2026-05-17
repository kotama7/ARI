import { useCallback, useEffect, useState } from 'react';
import { useT } from '../../i18n';

interface PaperEntry {
  paper_id: string;
  title: string;
  authors?: string[];
  venue?: string;
  year?: number | null;
  source_type: string;
  source: string;
  artifact_url?: string;
  license: string;
  license_assessment: {
    usable: boolean;
    permissive: boolean;
    note: string;
  };
  imported_at: string;
}

/**
 * PaperRegistryPage — lists external papers registered for PaperBench runs.
 *
 * Reads from GET /api/paperbench/papers. The "Import" CTA opens
 * PaperImportDialog; "Run PaperBench" opens the 5-step wizard
 * (PaperBenchWizard). Both are stubs in this scaffold — the surface is
 * present so the URL + nav wiring can land without blocking on the full
 * wizard implementation.
 */
export function PaperRegistryPage() {
  const t = useT();
  const [papers, setPapers] = useState<PaperEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch('/api/paperbench/papers');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setPapers(data.papers || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const deletePaper = async (id: string) => {
    if (!confirm(t('pb_confirm_delete'))) return;
    const r = await fetch(`/api/paperbench/papers/${encodeURIComponent(id)}/delete`, {
      method: 'POST',
    });
    const data = await r.json();
    if (data.deleted) {
      void refresh();
    } else {
      alert(data.error || data.reason || 'delete failed');
    }
  };

  return (
    <div style={{ padding: 28, maxWidth: 1100 }}>
      <h2 style={{ marginBottom: 4 }}>{t('pb_title')}</h2>
      <div style={{ color: '#888', marginBottom: 18 }}>{t('pb_subtitle')}</div>

      <div style={{ marginBottom: 14 }}>
        <button onClick={() => (window.location.hash = '/paperbench/import')}>
          {t('pb_import_btn')}
        </button>{' '}
        <button
          disabled={selected.size === 0}
          onClick={() => (window.location.hash = '/paperbench/run')}
        >
          {t('pb_run_btn')} ({selected.size})
        </button>{' '}
        <button onClick={() => void refresh()}>{t('pb_refresh')}</button>
      </div>

      {loading && <div>{t('pb_loading')}</div>}
      {error && (
        <div style={{ color: '#d33', padding: 12, background: '#fee' }}>
          {t('pb_load_error')}: {error}
        </div>
      )}
      {!loading && !error && papers.length === 0 && (
        <div style={{ color: '#666', padding: 28, textAlign: 'center' }}>
          {t('pb_no_papers')}
        </div>
      )}

      {papers.length > 0 && (
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #ccc' }}>
              <th></th>
              <th style={{ textAlign: 'left', padding: 6 }}>{t('pb_col_id')}</th>
              <th style={{ textAlign: 'left', padding: 6 }}>{t('pb_col_title')}</th>
              <th style={{ textAlign: 'left', padding: 6 }}>{t('pb_col_license')}</th>
              <th style={{ textAlign: 'left', padding: 6 }}>{t('pb_col_source')}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {papers.map((p) => (
              <tr key={p.paper_id} style={{ borderBottom: '1px solid #eee' }}>
                <td style={{ padding: 6 }}>
                  <input
                    type="checkbox"
                    checked={selected.has(p.paper_id)}
                    onChange={() => toggle(p.paper_id)}
                  />
                </td>
                <td style={{ padding: 6, fontFamily: 'monospace' }}>{p.paper_id}</td>
                <td style={{ padding: 6 }}>{p.title}</td>
                <td style={{ padding: 6 }}>
                  <span
                    style={{
                      padding: '2px 8px',
                      borderRadius: 4,
                      background: p.license_assessment?.usable ? '#cfc' : '#fcc',
                      fontSize: 12,
                    }}
                    title={p.license_assessment?.note}
                  >
                    {p.license || t('pb_license_unknown')}
                    {p.license_assessment?.usable ? ' ✅' : ' ⚠'}
                  </span>
                </td>
                <td style={{ padding: 6, fontSize: 12, color: '#666' }}>
                  {p.source_type}: {p.source}
                </td>
                <td style={{ padding: 6 }}>
                  <button
                    onClick={() => void deletePaper(p.paper_id)}
                    style={{ fontSize: 12, color: '#a00' }}
                  >
                    {t('pb_delete')}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
