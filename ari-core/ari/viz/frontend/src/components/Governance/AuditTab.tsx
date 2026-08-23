// ARI Dashboard – Governance Audit tab (gui_refresh task 08 Wave 4a).
// Answers "show me the raw log" — see docs/guides/rqgm_gui.md, 'Audit —
// "show me the raw log"'.
//
// Cursor-paged table over `rqgm_audit.jsonl` with record_type/epoch filters
// and a "load more" appender. The cursor is the backend's stable byte
// offset, so appended pages never duplicate rows of the append-only log;
// every row names its raw source (`rqgm_audit.jsonl` + byte offset) so the
// UI aggregate stays traceable to the artifact: every aggregate view must
// carry a drill-down handle back to the raw bytes it summarizes, and a
// filter change starts a fresh page chain so a filtered view can never
// inherit rows from a differently-filtered one. A broken hash chain flips the
// shared DegradedState — the rows still render, honestly flagged.

import { useState } from 'react';
import { useT } from '../../i18n';
import { useRqgmAuditV1 } from '../../hooks/useV1';
import { Button, Card, DegradedState, EmptyState, ErrorState, LoadingState } from '../common';
import { errorText } from './shared';
import type { RqgmAuditEntryV1 } from '../../services/api/v1';

const AUDIT_SOURCE_FILE = 'rqgm_audit.jsonl';

function summaryText(entry: RqgmAuditEntryV1): string {
  const summary = entry.summary ?? {};
  return Object.entries(summary)
    .filter(([k]) => !['record_id', 'record_type', 'epoch_id'].includes(k))
    .map(([k, v]) => `${k}=${String(v)}`)
    .join(' ');
}

export function AuditTab({ runId }: { runId: string }) {
  const t = useT();
  // Filters live inside the query key (useRqgmAuditV1): changing one
  // starts a fresh page chain, so a filtered view can never inherit rows
  // from a differently-filtered chain.
  const [recordType, setRecordType] = useState('');
  const [epoch, setEpoch] = useState('');
  const auditQ = useRqgmAuditV1(runId, { recordType, epoch }, true);

  if (auditQ.isPending) return <LoadingState />;
  if (auditQ.isError && auditQ.data === undefined) {
    return (
      <ErrorState
        message={errorText(auditQ.error, t('gov_request_id'))}
        onRetry={() => void auditQ.refetch()}
      />
    );
  }
  const pages = auditQ.data?.pages ?? [];
  const entries = pages.flatMap((p) => p.entries ?? []);
  const last = pages[pages.length - 1];
  const chainOk = last?.chain_ok ?? null;
  const totalEntries = last?.total_entries ?? entries.length;
  const reasons = last?.degraded_reasons ?? [];

  return (
    <div>
      <div style={{ display: 'flex', gap: 12, alignItems: 'end', margin: '4px 0 12px', flexWrap: 'wrap' }}>
        <label style={{ fontSize: '.8rem', display: 'grid', gap: 4 }}>
          {t('gov_audit_filter_type')}
          <input
            type="text"
            value={recordType}
            onChange={(e) => setRecordType(e.target.value)}
            style={{ width: 220 }}
          />
        </label>
        <label style={{ fontSize: '.8rem', display: 'grid', gap: 4 }}>
          {t('gov_audit_filter_epoch')}
          <input
            type="text"
            value={epoch}
            onChange={(e) => setEpoch(e.target.value)}
            style={{ width: 160 }}
          />
        </label>
        <span style={{ color: 'var(--text-muted)', fontSize: '.8rem' }}>
          {entries.length} / {totalEntries} {t('gov_audit_total')}
        </span>
      </div>

      {(chainOk === false || reasons.length > 0) && (
        <div style={{ marginBottom: 8 }}>
          <DegradedState title={t('gov_degraded_title')} detail={t('gov_degraded_note')}>
            {reasons.length > 0 && (
              <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
                {reasons.map((r, i) => (
                  <li key={i} style={{ fontSize: '.8rem' }}>
                    {r}
                  </li>
                ))}
              </ul>
            )}
          </DegradedState>
        </div>
      )}

      <Card>
        {entries.length === 0 ? (
          <EmptyState icon="📑" message={t('gov_audit_empty')} />
        ) : (
          <div data-testid="audit-table" style={{ overflowX: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th>{t('gov_audit_col_event')}</th>
                  <th>{t('gov_audit_col_type')}</th>
                  <th>{t('gov_audit_col_record_type')}</th>
                  <th>{t('gov_audit_col_epoch')}</th>
                  <th>{t('gov_audit_col_time')}</th>
                  <th>{t('gov_audit_col_summary')}</th>
                  <th>{t('gov_audit_col_source')}</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e) => (
                  <tr key={`${e.byte_offset}-${e.event_id}`}>
                    <td>
                      <code style={{ fontSize: '.75rem' }}>{e.event_id}</code>
                    </td>
                    <td>{e.event_type}</td>
                    <td>{e.record_type ?? '—'}</td>
                    <td>
                      <code style={{ fontSize: '.75rem' }}>{e.epoch_id ?? '—'}</code>
                    </td>
                    <td>
                      <code style={{ fontSize: '.72rem' }}>{e.ts_iso ?? '—'}</code>
                    </td>
                    <td>
                      <code style={{ fontSize: '.72rem' }}>{summaryText(e)}</code>
                    </td>
                    <td>
                      {/* Raw-source link target: artifact name + byte
                          offset + event hash (the drill-down handle). */}
                      <code
                        style={{ fontSize: '.72rem' }}
                        title={`event_hash ${e.event_hash}`}
                      >
                        {AUDIT_SOURCE_FILE}@{e.byte_offset}
                      </code>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div style={{ marginTop: 10 }}>
          {auditQ.hasNextPage ? (
            <Button
              variant="outline"
              size="sm"
              onClick={() => void auditQ.fetchNextPage()}
              disabled={auditQ.isFetchingNextPage}
            >
              {t('gov_audit_load_more')}
            </Button>
          ) : (
            <span style={{ color: 'var(--text-muted)', fontSize: '.78rem' }}>
              {t('gov_audit_end')}
            </span>
          )}
        </div>
      </Card>
    </div>
  );
}
