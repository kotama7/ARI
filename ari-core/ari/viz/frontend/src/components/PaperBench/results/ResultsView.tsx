import { useCallback, useEffect, useMemo, useState } from 'react';
import { useT } from '../../../i18n';

interface LeafGrade {
  id?: string;
  requirements: string;
  weight?: number;
  passed: boolean;
  task_category?: string;
  finegrained_task_category?: string;
}

interface RubricNode {
  id?: string;
  requirements?: string;
  weight?: number;
  task_category?: string;
  sub_tasks?: RubricNode[];
}

interface ResultsPayload {
  ors_score?: number;
  leaves?: LeafGrade[];
  rubric?: RubricNode;
  negative_control?: { empty?: number; boilerplate?: number; passed?: boolean };
}

interface JobSnapshot {
  job_id: string;
  paper_id: string;
  status: string;
  current_stage?: string | null;
}

const CATEGORY_COLORS: Record<string, string> = {
  'Code Development': '#bfdbfe',
  'Code Execution':   '#bbf7d0',
  'Result Analysis':  '#fde68a',
};

/**
 * ResultsView — rubric tree + per-leaf score visualization.
 *
 * URL format: ``#/paperbench/results?job=<job_id>``. Reads
 * ``/api/paperbench/run/<job_id>`` for status and
 * ``/.../results`` for the grade payload, then renders a colour-coded
 * tree (pass = green, fail = red, weighted by leaf weight). The
 * sidebar shows the aggregate ORS score and per-category pass rate;
 * the footer offers a "Download report" group that POSTs to
 * ``/api/paperbench/run/<job_id>/report`` and lists the resulting
 * en / ja / zh ⨯ pdf / html / md download URLs.
 */
export function ResultsView() {
  const t = useT();
  const jobId = useMemo(() => {
    const m = window.location.hash.match(/job=([^&]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }, []);

  const [snap, setSnap] = useState<JobSnapshot | null>(null);
  const [results, setResults] = useState<ResultsPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reportPaths, setReportPaths] = useState<Record<string, string>>({});
  const [reportBusy, setReportBusy] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [liveLogs, setLiveLogs] = useState<Array<{ ts: string; level: string; msg: string }>>([]);

  useEffect(() => {
    if (!jobId) return;
    const load = async () => {
      try {
        const s = await fetch(`/api/paperbench/run/${jobId}`).then((r) => r.json());
        if (s.error) {
          setError(s.error);
          return;
        }
        setSnap(s);
        if (s.status === 'completed') {
          const r = await fetch(`/api/paperbench/run/${jobId}/results`).then((rr) => rr.json());
          if (r.error) setError(r.error);
          else setResults(r);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    };
    void load();
  }, [jobId]);

  // SSE log stream — only active while the job is in flight.
  useEffect(() => {
    if (!jobId || !snap || snap.status === 'completed' || snap.status === 'failed') {
      return;
    }
    const es = new EventSource(`/api/paperbench/run/${jobId}/logs`);
    es.addEventListener('log', (ev) => {
      try {
        const row = JSON.parse((ev as MessageEvent).data);
        setLiveLogs((prev) => [...prev.slice(-1000), row]);
      } catch {
        /* ignore malformed payload */
      }
    });
    es.addEventListener('done', () => {
      es.close();
      void fetch(`/api/paperbench/run/${jobId}`)
        .then((r) => r.json())
        .then(setSnap);
    });
    es.onerror = () => es.close();
    return () => es.close();
  }, [jobId, snap]);

  const requestReport = useCallback(
    async (languages: string[], formats: string[]) => {
      if (!jobId) return;
      setReportBusy(true);
      try {
        const r = await fetch(`/api/paperbench/run/${jobId}/report`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ languages, formats }),
        }).then((rr) => rr.json());
        if (r.error) {
          setError(r.error);
        } else {
          setReportPaths(r.download_urls || {});
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setReportBusy(false);
      }
    },
    [jobId],
  );

  if (!jobId) {
    return (
      <div style={{ padding: 28 }}>
        <h2>{t('pb_results_title')}</h2>
        <p style={{ color: '#888' }}>{t('pb_results_no_job')}</p>
      </div>
    );
  }
  if (error) {
    return (
      <div style={{ padding: 28 }}>
        <div style={{ color: '#d33', padding: 12, background: '#fee' }}>{error}</div>
      </div>
    );
  }
  if (!snap) {
    return <div style={{ padding: 28 }}>{t('pb_loading')}</div>;
  }
  if (snap.status !== 'completed') {
    return (
      <div style={{ padding: 28 }}>
        <h2>{t('pb_results_title')}</h2>
        <p>
          <strong>{snap.job_id}</strong> — status: <code>{snap.status}</code>
          {snap.current_stage ? ` (${snap.current_stage})` : ''}
        </p>
        <p style={{ color: '#666' }}>{t('pb_results_wait')}</p>
        <h3 style={{ marginTop: 24 }}>{t('pb_results_live_logs')}</h3>
        <pre
          style={{
            background: '#0f172a',
            color: '#cbd5e1',
            padding: 12,
            borderRadius: 6,
            maxHeight: 480,
            overflow: 'auto',
            fontSize: 12,
            lineHeight: 1.45,
          }}
        >
          {liveLogs.length === 0 ? (
            <span style={{ color: '#64748b' }}>{t('pb_results_logs_empty')}</span>
          ) : (
            liveLogs.map((l, i) => {
              const color =
                l.level === 'error'
                  ? '#fda4af'
                  : l.level === 'warning'
                    ? '#fcd34d'
                    : l.level === 'success'
                      ? '#86efac'
                      : '#cbd5e1';
              return (
                <div key={i} style={{ color }}>
                  <span style={{ color: '#475569' }}>{l.ts}</span>{' '}
                  <span style={{ textTransform: 'uppercase', fontSize: 10 }}>[{l.level}]</span>{' '}
                  {l.msg}
                </div>
              );
            })
          )}
        </pre>
      </div>
    );
  }

  const orsPct = results?.ors_score != null ? (results.ors_score * 100).toFixed(1) : '—';
  const leaves = results?.leaves || [];
  const byCat: Record<string, { pass: number; total: number }> = {};
  for (const l of leaves) {
    const k = l.task_category || 'Uncategorized';
    if (!byCat[k]) byCat[k] = { pass: 0, total: 0 };
    byCat[k].total += 1;
    if (l.passed) byCat[k].pass += 1;
  }
  const leafLookup: Record<string, LeafGrade> = {};
  for (const l of leaves) {
    if (l.id) leafLookup[l.id] = l;
  }

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const renderNode = (node: RubricNode, depth: number): React.ReactNode => {
    const nid = node.id || `${depth}-${node.requirements?.slice(0, 24)}`;
    const isLeaf = !node.sub_tasks || node.sub_tasks.length === 0;
    const grade = isLeaf && node.id ? leafLookup[node.id] : null;
    const passColor = grade
      ? grade.passed
        ? 'rgba(34, 197, 94, 0.18)'
        : 'rgba(220, 38, 38, 0.18)'
      : 'rgba(0, 0, 0, 0.02)';
    const catColor = node.task_category ? CATEGORY_COLORS[node.task_category] : undefined;
    const isOpen = expanded.has(nid);
    return (
      <div
        key={nid}
        style={{
          paddingLeft: depth * 14,
          borderLeft: depth > 0 ? '1px solid #e5e7eb' : 'none',
          marginTop: 4,
        }}
      >
        <div
          style={{
            background: passColor,
            padding: '4px 10px',
            borderRadius: 4,
            cursor: !isLeaf ? 'pointer' : 'default',
            fontSize: 13,
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}
          onClick={() => !isLeaf && toggle(nid)}
        >
          <span style={{ width: 16, textAlign: 'center' }}>
            {isLeaf ? (grade ? (grade.passed ? '✓' : '✗') : '·') : isOpen ? '▾' : '▸'}
          </span>
          {catColor && (
            <span
              style={{
                background: catColor,
                padding: '0 6px',
                borderRadius: 3,
                fontSize: 10,
                color: '#1f2937',
              }}
              title={node.task_category}
            >
              {(node.task_category || '').replace('Code ', '').slice(0, 5)}
            </span>
          )}
          <span style={{ flex: 1 }}>{node.requirements}</span>
          {node.weight ? <span style={{ color: '#666', fontSize: 11 }}>w={node.weight}</span> : null}
        </div>
        {!isLeaf && isOpen && node.sub_tasks?.map((c) => renderNode(c, depth + 1))}
      </div>
    );
  };

  return (
    <div style={{ padding: 28, display: 'flex', gap: 24, maxWidth: 1400 }}>
      <div style={{ flex: 1 }}>
        <h2>{t('pb_results_title')}</h2>
        <div style={{ color: '#666', marginBottom: 14, fontSize: 13 }}>
          job <code>{snap.job_id}</code> · paper <code>{snap.paper_id}</code>
        </div>

        <h3 style={{ marginTop: 14 }}>{t('pb_results_rubric_tree')}</h3>
        {results?.rubric ? (
          renderNode(results.rubric, 0)
        ) : (
          <p style={{ color: '#666' }}>{t('pb_results_no_rubric')}</p>
        )}
      </div>

      <aside style={{ width: 320, padding: 16, background: '#f9fafb', borderRadius: 8 }}>
        <h3 style={{ marginBottom: 8 }}>{t('pb_results_summary')}</h3>
        <div
          style={{
            fontSize: 36,
            fontWeight: 700,
            color: '#1d4ed8',
            textAlign: 'center',
            padding: 16,
            background: '#fff',
            borderRadius: 6,
            marginBottom: 12,
          }}
        >
          {orsPct}%
        </div>

        <div style={{ fontSize: 13, color: '#555', marginBottom: 8 }}>
          {leaves.length} {t('pb_results_leaves_total')},{' '}
          {leaves.filter((l) => l.passed).length} {t('pb_results_leaves_passed')}
        </div>

        <h4 style={{ marginTop: 12, fontSize: 13 }}>{t('pb_results_by_category')}</h4>
        <table style={{ width: '100%', fontSize: 12 }}>
          <tbody>
            {Object.entries(byCat).map(([cat, v]) => (
              <tr key={cat}>
                <td style={{ padding: '2px 4px' }}>{cat}</td>
                <td style={{ padding: '2px 4px', textAlign: 'right' }}>
                  {v.pass}/{v.total}
                </td>
                <td style={{ padding: '2px 4px', textAlign: 'right', color: '#666' }}>
                  {v.total ? Math.round((100 * v.pass) / v.total) : 0}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {results?.negative_control && (
          <div style={{ marginTop: 14, fontSize: 12, color: '#555' }}>
            <strong>{t('pb_results_negative_control')}:</strong>
            <br />
            empty: {((results.negative_control.empty ?? 0) * 100).toFixed(1)}%, boilerplate:{' '}
            {((results.negative_control.boilerplate ?? 0) * 100).toFixed(1)}%
            {' — '}
            {results.negative_control.passed ? '✓' : '✗'}
          </div>
        )}

        <h4 style={{ marginTop: 18, fontSize: 13 }}>{t('pb_results_download_report')}</h4>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', fontSize: 12 }}>
          {(['en', 'ja', 'zh'] as const).map((lang) => (
            <button
              key={lang}
              disabled={reportBusy}
              onClick={() => void requestReport([lang], ['pdf', 'html', 'md'])}
              style={{
                padding: '6px 10px',
                background: '#fff',
                border: '1px solid #d1d5db',
                borderRadius: 4,
                cursor: reportBusy ? 'wait' : 'pointer',
              }}
            >
              {lang.toUpperCase()}
            </button>
          ))}
        </div>
        {reportBusy && (
          <div style={{ marginTop: 6, fontSize: 12, color: '#666' }}>
            {t('pb_results_rendering')}…
          </div>
        )}
        {Object.keys(reportPaths).length > 0 && (
          <ul style={{ marginTop: 10, fontSize: 12, listStyle: 'none', padding: 0 }}>
            {Object.entries(reportPaths).map(([k, p]) => (
              <li key={k} style={{ padding: '2px 0' }}>
                <a
                  href={`file://${p}`}
                  style={{ color: '#1d4ed8', textDecoration: 'underline' }}
                >
                  {k}
                </a>
              </li>
            ))}
          </ul>
        )}
      </aside>
    </div>
  );
}
