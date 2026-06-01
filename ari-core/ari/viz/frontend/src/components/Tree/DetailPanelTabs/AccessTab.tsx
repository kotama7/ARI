// ARI Dashboard – DetailPanel "Access log" tab.
// Extracted verbatim from DetailPanel.tsx (refactor req 15): the access-tab JSX
// block. The `activeTab === 'access'` guard stays in the container; this renders
// the memory write/read event log. `t` is sourced via useI18n internally
// (behavior-identical to the container's closure over the same i18n context).

import { useI18n } from '../../../i18n';
import type { MemoryAccessResponse } from '../../../services/api';

interface AccessTabProps {
  accessLoading: boolean;
  accessError: string | null;
  accessData: MemoryAccessResponse | null;
}

export function AccessTab({ accessLoading, accessError, accessData }: AccessTabProps) {
  const { t } = useI18n();
  return (
    <div>
      {accessLoading && (
        <div style={{ fontSize: '.72rem', color: 'var(--muted)' }}>
          Loading access log…
        </div>
      )}
      {accessError && (
        <div style={{ fontSize: '.72rem', color: 'var(--red)' }}>
          {accessError}
        </div>
      )}
      {!accessLoading &&
        !accessError &&
        accessData &&
        accessData.writes.length === 0 &&
        accessData.reads.length === 0 && (
          <div style={{ fontSize: '.75rem', color: 'var(--muted)' }}>
            {t('memory_access_empty')}
          </div>
        )}
      {accessData && (accessData.writes.length > 0 || accessData.reads.length > 0) && (
        <div style={{ fontSize: '.72rem', color: 'var(--muted)', marginBottom: 6 }}>
          <span className="badge badge-blue" style={{ marginRight: 4 }}>
            {t('memory_access_writes')}: {accessData.writes.length}
          </span>
          <span className="badge badge-muted">
            {t('memory_access_reads')}: {accessData.reads.length}
          </span>
        </div>
      )}
      {accessData && accessData.writes.length > 0 && (
        <div style={{ marginBottom: 8 }}>
          <div
            style={{
              fontSize: '.7rem',
              color: 'var(--muted)',
              textTransform: 'uppercase',
              letterSpacing: '.04em',
              margin: '8px 0 4px',
            }}
          >
            {t('memory_access_writes')} ({accessData.writes.length})
          </div>
          {accessData.writes.map((ev, i) => (
            <div
              key={`w-${i}`}
              style={{
                borderLeft: '3px solid #60a5fa',
                background: 'rgba(59,130,246,.06)',
                padding: '6px 8px',
                margin: '4px 0',
                borderRadius: 3,
                fontSize: '.72rem',
              }}
            >
              <div style={{ color: 'var(--muted)', marginBottom: 3 }}>
                {ev.ts
                  ? new Date(Number(ev.ts) * 1000).toLocaleString()
                  : ''}
              </div>
              {ev.text_preview && (
                <div
                  style={{
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                    maxHeight: 120,
                    overflow: 'auto',
                  }}
                >
                  {ev.text_preview}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      {accessData && accessData.reads.length > 0 && (
        <div>
          <div
            style={{
              fontSize: '.7rem',
              color: 'var(--muted)',
              textTransform: 'uppercase',
              letterSpacing: '.04em',
              margin: '8px 0 4px',
            }}
          >
            {t('memory_access_reads')} ({accessData.reads.length})
          </div>
          {accessData.reads.map((ev, i) => (
            <div
              key={`r-${i}`}
              style={{
                borderLeft: '3px solid #86efac',
                background: 'rgba(134,239,172,.06)',
                padding: '6px 8px',
                margin: '4px 0',
                borderRadius: 3,
                fontSize: '.72rem',
              }}
            >
              <div
                style={{
                  color: 'var(--muted)',
                  marginBottom: 3,
                  display: 'flex',
                  gap: 6,
                  flexWrap: 'wrap',
                }}
              >
                {ev.ts && (
                  <span>{new Date(Number(ev.ts) * 1000).toLocaleString()}</span>
                )}
                {ev.results && (
                  <span>
                    {t('memory_access_hits')}: {ev.results.length}
                  </span>
                )}
              </div>
              {ev.query && (
                <div
                  style={{
                    fontFamily: 'monospace',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                  }}
                >
                  {t('memory_access_query')}: {ev.query}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
