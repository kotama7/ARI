// ARI Dashboard – Overview LogsPanel (gui_refresh task 07 tail; plan 07
// §Artifacts, logs, and diagnostics + §Run Overview and Live Monitor P4).
//
// Collapsible cursor-based log explorer over the run's append-only
// `{ckpt}/ari.log`, embedded in the Overview page (P4 disclosure layer —
// no new route). Reads GET /api/v1/runs/{run_id}/logs, whose cursor is a
// RAW byte offset: [Load more] appends the next bounded page with no gap
// and no duplicate, and the server-side case-insensitive `grep` filter
// never destabilizes cursors (it selects returned lines, not consumed
// bytes). Committed lines only — a partial trailing line is served once
// its newline lands. Nothing here ever reads the whole file (plan 07: a
// 5 MB whole-file read must not be the primary UX).
//
// Tail-follow: the toggle wires the panel to the run event stream the
// OverviewPage already subscribes (topics run+tree) — each delivered event
// (`lastEventAt` prop) triggers one `next_cursor` fetch, so following is
// event-driven, not a timer. While following with the stream down the
// panel shows its own StaleDataBanner (the log view may lag; plan 01:
// never presented as "run stopped").

import { useCallback, useEffect, useRef, useState } from 'react';
import { useT } from '../../i18n';
import {
  fetchRunLogsV1,
  toApiError,
  type ApiErrorV1,
  type LogEntryV1,
} from '../../services/api/v1';
import type { ConnectionState } from '../../shared/realtime/eventStream';
import { Button, Card, ErrorState, StaleDataBanner } from '../common';

export interface LogsPanelProps {
  runId: string;
  /** Epoch ms of the last delivered run event (page's useRunEvents). */
  lastEventAt: number | null;
  /** Stream state — drives the in-panel stale banner while following. */
  connectionState: ConnectionState;
}

export function LogsPanel({ runId, lastEventAt, connectionState }: LogsPanelProps) {
  const t = useT();

  const [expanded, setExpanded] = useState(false);
  const [entries, setEntries] = useState<LogEntryV1[]>([]);
  // null = never fetched (collapsed panels fetch nothing — lazy P4 layer).
  const [present, setPresent] = useState<boolean | null>(null);
  const [eof, setEof] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiErrorV1 | null>(null);
  const [grepInput, setGrepInput] = useState('');
  const [follow, setFollow] = useState(false);

  // The resume cursor and applied filter live in refs so the fetch callback
  // stays identity-stable (no effect refire loops on every page).
  const cursorRef = useRef(0);
  const grepRef = useRef('');
  const busyRef = useRef(false);

  const fetchPage = useCallback(async () => {
    if (busyRef.current || runId === '') return;
    busyRef.current = true;
    setLoading(true);
    setError(null);
    try {
      const page = await fetchRunLogsV1(runId, {
        cursor: cursorRef.current,
        grep: grepRef.current || undefined,
      });
      cursorRef.current = page.next_cursor ?? cursorRef.current;
      setPresent(page.present ?? false);
      setEof(page.eof ?? true);
      // Append-only merge keyed by byte offset: the raw cursor already
      // guarantees no duplicates; the offset guard keeps the invariant
      // even across races (double-click, follow burst).
      setEntries((prev) => {
        const seen = new Set(prev.map((e) => e.offset));
        const add = (page.entries ?? []).filter((e) => !seen.has(e.offset));
        return add.length === 0 ? prev : [...prev, ...add];
      });
    } catch (err) {
      setError(toApiError(err));
    } finally {
      busyRef.current = false;
      setLoading(false);
    }
  }, [runId]);

  // Run switch: full reset (run-scoped state never bleeds across runs).
  useEffect(() => {
    cursorRef.current = 0;
    grepRef.current = '';
    setExpanded(false);
    setEntries([]);
    setPresent(null);
    setEof(true);
    setError(null);
    setGrepInput('');
    setFollow(false);
  }, [runId]);

  // Lazy first load: fetch only once the section is expanded.
  useEffect(() => {
    if (expanded && present === null && error === null) void fetchPage();
  }, [expanded, present, error, fetchPage]);

  // Tail-follow: every delivered run event triggers one next_cursor fetch
  // (events are invalidations, never data — plan 04).
  useEffect(() => {
    if (!expanded || !follow || lastEventAt === null) return;
    void fetchPage();
  }, [expanded, follow, lastEventAt, fetchPage]);

  const applyGrep = (e: { preventDefault: () => void }) => {
    e.preventDefault();
    grepRef.current = grepInput.trim();
    cursorRef.current = 0;
    setEntries([]);
    setPresent(null);
    setEof(true);
    setError(null);
    void fetchPage();
  };

  return (
    <Card title={t('ov_logs_title')}>
      <Button
        variant="outline"
        size="sm"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        {expanded ? t('ov_logs_hide') : t('ov_logs_show')}
      </Button>

      {expanded && (
        <div style={{ marginTop: 12 }}>
          {follow && connectionState !== 'live' && (
            <div style={{ marginBottom: 10 }}>
              <StaleDataBanner
                lastUpdated={
                  lastEventAt !== null
                    ? new Date(lastEventAt).toLocaleString()
                    : null
                }
                onRefresh={() => void fetchPage()}
              />
            </div>
          )}

          <form
            onSubmit={applyGrep}
            style={{
              display: 'flex',
              gap: 8,
              alignItems: 'center',
              flexWrap: 'wrap',
              marginBottom: 10,
            }}
          >
            <input
              type="text"
              value={grepInput}
              onChange={(e) => setGrepInput(e.target.value)}
              placeholder={t('ov_logs_grep_placeholder')}
              aria-label={t('ov_logs_grep_label')}
              style={{ flex: '1 1 220px', fontSize: '.8rem', padding: '4px 8px' }}
            />
            <Button variant="outline" size="sm" type="submit">
              {t('ov_logs_grep_apply')}
            </Button>
            <label
              style={{
                display: 'flex',
                gap: 6,
                alignItems: 'center',
                fontSize: '.8rem',
                color: 'var(--text-muted)',
              }}
            >
              <input
                type="checkbox"
                checked={follow}
                onChange={(e) => setFollow(e.target.checked)}
              />
              {t('ov_logs_follow')}
            </label>
          </form>

          {error !== null ? (
            <ErrorState message={error.message} onRetry={() => void fetchPage()} />
          ) : present === false ? (
            <p style={{ color: 'var(--text-muted)', fontSize: '.8rem' }}>
              {t('ov_logs_absent')}
            </p>
          ) : (
            <>
              <div
                style={{
                  fontFamily: 'var(--font-mono, monospace)',
                  fontSize: '.75rem',
                  lineHeight: 1.5,
                  maxHeight: 360,
                  overflow: 'auto',
                  border: '1px solid var(--border)',
                  borderRadius: 6,
                  padding: '6px 10px',
                }}
              >
                {entries.length === 0 && !loading ? (
                  <span style={{ color: 'var(--text-muted)' }}>
                    {t('ov_logs_empty')}
                  </span>
                ) : (
                  entries.map((e) => (
                    <div key={e.offset} style={{ whiteSpace: 'pre-wrap' }}>
                      {e.line}
                    </div>
                  ))
                )}
              </div>
              <div
                style={{
                  display: 'flex',
                  gap: 12,
                  alignItems: 'center',
                  marginTop: 8,
                  fontSize: '.75rem',
                  color: 'var(--text-muted)',
                }}
              >
                <span>
                  {entries.length} {t('ov_logs_lines_label')}
                </span>
                {loading && <span>{t('loading')}</span>}
                {!eof && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => void fetchPage()}
                    disabled={loading}
                  >
                    {t('ov_logs_load_more')}
                  </Button>
                )}
                {eof && present === true && <span>{t('ov_logs_eof')}</span>}
              </div>
            </>
          )}
        </div>
      )}
    </Card>
  );
}
