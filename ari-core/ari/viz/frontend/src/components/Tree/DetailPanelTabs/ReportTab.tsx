// ARI Dashboard – DetailPanel "Report" tab.
// Extracted verbatim from DetailPanel.tsx (refactor req 15): the report-tab JSX
// block (node_report.json structured view, v0.7.0). The `activeTab === 'report'`
// guard stays in the container; this renders the report body. `t` is sourced via
// useI18n internally (behavior-identical to the container's i18n closure).

import { useI18n } from '../../../i18n';
import { LoadingState, ErrorState } from '../../common';
import type { NodeReport } from '../../../services/api';

interface ReportTabProps {
  reportLoading: boolean;
  reportError: string | null;
  reportData: NodeReport | null;
}

export function ReportTab({ reportLoading, reportError, reportData }: ReportTabProps) {
  const { t } = useI18n();
  return (
    <div style={{ fontSize: '.78rem' }}>
      {reportLoading && <LoadingState inline />}
      {reportError && <ErrorState message={reportError} inline />}
      {reportData && (
        <div>
          {reportData.delta_vs_parent && (
            <div style={{ marginBottom: 8 }}>
              <div style={{ color: 'var(--muted)', marginBottom: 2 }}>
                {t('report_delta_vs_parent')}
              </div>
              <div>{reportData.delta_vs_parent}</div>
            </div>
          )}
          {reportData.self_assessment?.headline && (
            <div style={{ marginBottom: 8 }}>
              <div style={{ color: 'var(--muted)', marginBottom: 2 }}>
                {t('report_headline')}
              </div>
              <div>{reportData.self_assessment.headline}</div>
            </div>
          )}
          {(reportData.self_assessment?.concerns ?? []).length > 0 && (
            <div style={{ marginBottom: 8 }}>
              <div style={{ color: '#f59e0b', marginBottom: 2 }}>
                ⚠ {t('report_concerns')}
              </div>
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {reportData.self_assessment!.concerns!.map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ul>
            </div>
          )}
          {(reportData.next_steps_hints ?? []).length > 0 && (
            <div style={{ marginBottom: 8 }}>
              <div style={{ color: 'var(--muted)', marginBottom: 2 }}>
                {t('report_next_steps')}
              </div>
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {reportData.next_steps_hints!.map((h, i) => (
                  <li key={i}>{h}</li>
                ))}
              </ul>
            </div>
          )}
          <div style={{ marginBottom: 8 }}>
            <div style={{ color: 'var(--muted)', marginBottom: 2 }}>
              {t('report_files_changed')}
            </div>
            <div style={{ fontSize: '.72rem' }}>
              {([
                { key: 'added', color: '#10b981', label: '+ added' },
                { key: 'modified', color: '#3b82f6', label: '~ modified' },
                { key: 'deleted', color: '#ef4444', label: '− deleted' },
              ] as const).map(({ key, color, label }) => {
                const entries = reportData.files_changed[key];
                if (!entries || entries.length === 0) return null;
                return (
                  <div key={key} style={{ marginBottom: 3 }}>
                    <span style={{ color }}>{label}:</span>
                    <ul style={{ margin: '1px 0 0 14px', padding: 0, listStyle: 'none' }}>
                      {entries.map((e) => (
                        <li key={e.path}>
                          <code>{e.path}</code>
                          {e.note ? (
                            <span style={{ color: 'var(--muted)' }}> — {e.note}</span>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  </div>
                );
              })}
              {reportData.files_changed.added.length === 0 &&
                reportData.files_changed.modified.length === 0 &&
                reportData.files_changed.deleted.length === 0 && (
                  <div style={{ color: 'var(--muted)' }}>
                    {t('report_no_changes')}
                  </div>
                )}
            </div>
          </div>
          {(reportData.build_command || reportData.run_command) && (
            <div style={{ marginBottom: 8 }}>
              <div style={{ color: 'var(--muted)', marginBottom: 2 }}>
                {t('report_commands')}
              </div>
              <pre
                className="code"
                style={{
                  fontSize: '.7rem',
                  padding: 6,
                  maxHeight: 120,
                  overflow: 'auto',
                }}
              >
                {reportData.build_command ? reportData.build_command + '\n' : ''}
                {reportData.run_command || ''}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
