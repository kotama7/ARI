// ARI Dashboard – read-only effective-config browser (gui_refresh Wave 3b).
// Purpose: show what one run's configuration actually resolved to — every
// leaf with its effective value and where that value came from — and offer no
// way to change it. See docs/guides/configuration_studio.md, "Inspecting
// effective configuration (`#/config?run=`)".
//
// READ-ONLY. Two typed /api/v1 data sources via the react-query hooks
// (src/hooks/useV1.ts):
//   - GET /api/v1/config/schema — the canonical field registry (metadata +
//     defaults; never an effective value), always fetched;
//   - GET /api/v1/runs/{run_id}/resolved-config — the resolved launch
//     manifest (values + provenance + secret_references + warnings, with
//     secret leaves structurally absent from values, so there is no value to
//     print), fetched only when the hash query string carries ?run=<id>
//     (#/config?run=<run_id>). With no run param this page is a SCHEMA
//     browser only.
//
// Rendering contract — an effective value is never shown without its
// provenance, and a manifest leaf the registry does not know is still shown
// (grouped under 'Other') rather than dropped:
//   - fields grouped by registry category, collapsible per group;
//   - per-leaf row: path (monospace), effective value (or schema default in
//     schema-only mode), provenance source badge, low-confidence marker,
//     mutability badge, applies_when note;
//   - secret_reference rows show 'secret (reference only)' — NEVER a value
//     (the backend redacts defaults/values structurally; this page must not
//     invent a place to print one);
//   - a search box filters by path/category — every field stays discoverable
//     via search, so none is reachable only by guessing its category;
//   - resolver warnings are listed verbatim in a warnings panel;
//   - freshness via StaleDataBanner when a refetch fails over cached data
//     (a stale snapshot is a freshness notice, never an error state: the
//     error state is only for having nothing to show — see
//     docs/guides/dashboard.md, "Live updates, staleness, and reconnection").
//
// Studio EDITING is Wave 4 — nothing here mutates anything.

import { useEffect, useMemo, useState } from 'react';
import { useT } from '../../i18n';
import { useConfigSchemaV1, useRunResolvedConfigV1 } from '../../hooks/useV1';
import {
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  StaleDataBanner,
} from '../common';
import type { ApiErrorV1, ProvenanceEntryV1 } from '../../services/api/v1';
// The single read-only row renderer, shared with the Configuration Studio's
// ADR-09 Execution section (see ConfigReadOnlyTable.tsx).
import { ConfigReadOnlyTable, type ConfigReadOnlyRow } from './ConfigReadOnlyTable';

// ── helpers ─────────────────────────────────────────────────────────────

/** `run` query param of the current hash (#/config?run=<run_id>) or ''. */
function runFromHash(): string {
  const query = window.location.hash.split('?')[1] ?? '';
  return new URLSearchParams(query).get('run') ?? '';
}

/**
 * err.message plus the envelope's request_id — the per-dispatch support handle
 * a user can quote in a bug report, which is why it is surfaced rather than
 * logged. See docs/reference/rest_api.md, "Error envelope".
 */
function errorText(err: ApiErrorV1, requestIdLabel: string): string {
  const rid = err.request_id ? ` (${requestIdLabel}: ${err.request_id})` : '';
  return `${err.message}${rid}`;
}

/** One display row: the shared read-only row plus this page's grouping key. */
interface ConfigRow extends ConfigReadOnlyRow {
  category: string;
  provenance: ProvenanceEntryV1 | null;
}

const FALLBACK_CATEGORY = 'Other';

// ── page ────────────────────────────────────────────────────────────────

export function ConfigBrowserPage() {
  const t = useT();

  // Route dispatch strips the query string, so the page owns the ?run param
  // itself (and tracks in-place hash changes, e.g. Projects row links while
  // already on #/config).
  const [runId, setRunId] = useState<string>(runFromHash);
  useEffect(() => {
    const onHashChange = () => setRunId(runFromHash());
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  const [search, setSearch] = useState('');

  const schemaQ = useConfigSchemaV1();
  // enabled: runId !== '' inside the hook — schema-only mode fetches nothing.
  const resolvedQ = useRunResolvedConfigV1(runId);

  const runMode = runId !== '';
  const schema = schemaQ.data;
  const resolved = runMode ? resolvedQ.data : undefined;

  // Row model: every registry field, plus any resolved leaf/secret the
  // registry does not know (defensive — grouped under 'Other').
  const rows = useMemo<ConfigRow[]>(() => {
    const fields = schema?.fields ?? [];
    const values = resolved?.values ?? {};
    const provenance = resolved?.provenance ?? {};
    const secrets = resolved?.secret_references ?? {};
    const known = new Set(fields.map((f) => f.path));
    const out: ConfigRow[] = fields.map((f) => ({
      path: f.path,
      category: f.category,
      field: f,
      value:
        runMode && Object.prototype.hasOwnProperty.call(values, f.path)
          ? values[f.path]
          : f.default,
      hasValue:
        (runMode && Object.prototype.hasOwnProperty.call(values, f.path)) ||
        f.default != null,
      provenance: provenance[f.path] ?? null,
      secret:
        f.sensitivity === 'secret_reference' ||
        Object.prototype.hasOwnProperty.call(secrets, f.path),
    }));
    const extras = new Set<string>([
      ...Object.keys(values),
      ...Object.keys(secrets),
    ]);
    for (const path of [...extras].sort()) {
      if (known.has(path)) continue;
      out.push({
        path,
        category: FALLBACK_CATEGORY,
        field: null,
        value: values[path],
        hasValue: Object.prototype.hasOwnProperty.call(values, path),
        provenance: provenance[path] ?? null,
        secret: Object.prototype.hasOwnProperty.call(secrets, path),
      });
    }
    return out;
  }, [schema, resolved, runMode]);

  // Search filter: path OR category substring, case-insensitive — matching on
  // both is what keeps every field discoverable without knowing its category.
  const needle = search.trim().toLowerCase();
  const visibleRows = useMemo(
    () =>
      needle === ''
        ? rows
        : rows.filter(
            (r) =>
              r.path.toLowerCase().includes(needle) ||
              r.category.toLowerCase().includes(needle),
          ),
    [rows, needle],
  );

  // Group by category, registry (schema) order; 'Other' last.
  const groups = useMemo(() => {
    const byCategory = new Map<string, ConfigRow[]>();
    for (const row of visibleRows) {
      const list = byCategory.get(row.category) ?? [];
      list.push(row);
      byCategory.set(row.category, list);
    }
    const ordered = [...byCategory.entries()].filter(
      ([category]) => category !== FALLBACK_CATEGORY,
    );
    const extras = byCategory.get(FALLBACK_CATEGORY);
    if (extras) ordered.push([FALLBACK_CATEGORY, extras]);
    return ordered;
  }, [visibleRows]);

  // Hard error only when there is no snapshot to show; a refetch failure over
  // cached data is a freshness notice, not an error — a degraded read never
  // replaces data that is already on screen.
  const hardError: ApiErrorV1 | null =
    schemaQ.isError && schemaQ.data === undefined
      ? schemaQ.error
      : runMode && resolvedQ.isError && resolvedQ.data === undefined
        ? resolvedQ.error
        : null;
  const stale =
    (schemaQ.data !== undefined && schemaQ.isError) ||
    (runMode && resolvedQ.data !== undefined && resolvedQ.isError);
  const loading = schemaQ.isPending || (runMode && resolvedQ.isPending);
  const lastUpdatedMs = Math.max(
    schemaQ.dataUpdatedAt || 0,
    runMode ? resolvedQ.dataUpdatedAt || 0 : 0,
  );

  const refetchAll = () => {
    void schemaQ.refetch();
    if (runMode) void resolvedQ.refetch();
  };

  const warnings = resolved?.warnings ?? [];

  return (
    <div className="page active" style={{ display: 'block' }}>
      <h1>{t('config_title')}</h1>
      <p className="subtitle">{t('config_subtitle')}</p>

      {stale && (
        <div style={{ marginBottom: 16 }}>
          <StaleDataBanner
            lastUpdated={
              lastUpdatedMs > 0 ? new Date(lastUpdatedMs).toLocaleString() : null
            }
            onRefresh={refetchAll}
          />
        </div>
      )}

      {hardError ? (
        <ErrorState
          message={errorText(hardError, t('config_request_id'))}
          onRetry={refetchAll}
        />
      ) : loading ? (
        <LoadingState />
      ) : (
        <>
          {/* Context line: run identity or the schema-only notice. */}
          {runMode ? (
            <p style={{ color: 'var(--muted)', fontSize: '.85rem' }}>
              {t('config_run_label')}:{' '}
              <code style={{ fontSize: '.85rem' }}>{runId}</code>
              {resolved?.resolved_at && (
                <>
                  {' — '}
                  {t('config_resolved_at')}: {resolved.resolved_at}
                </>
              )}
            </p>
          ) : (
            <p style={{ color: 'var(--muted)', fontSize: '.85rem' }}>
              {t('config_schema_only_note')}
            </p>
          )}

          {/* Resolver warnings, verbatim: the manifest's warnings are listed
              as the resolver emitted them, never summarized or dropped. */}
          {warnings.length > 0 && (
            <Card title={`⚠️ ${t('config_warnings_title')}`}>
              <ul style={{ margin: 0, paddingLeft: 20 }}>
                {warnings.map((w, i) => (
                  <li key={i} style={{ fontSize: '.85rem' }}>
                    {w}
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {/* Search: the filter is what keeps every field discoverable, so it
              stays on the page rather than behind a disclosure. */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              margin: '12px 0',
            }}
          >
            <input
              type="search"
              aria-label={t('config_search_label')}
              placeholder={t('config_search_placeholder')}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{ flex: '0 1 320px' }}
            />
            <span style={{ color: 'var(--muted)', fontSize: '.8rem' }}>
              {visibleRows.length} / {rows.length} {t('config_fields')}
            </span>
          </div>

          {visibleRows.length === 0 ? (
            <Card>
              <EmptyState icon={'🔍'} message={t('config_no_matches')} />
            </Card>
          ) : (
            groups.map(([category, categoryRows]) => (
              <details key={category} open>
                <summary style={{ cursor: 'pointer', padding: '6px 0' }}>
                  <strong>{category}</strong>{' '}
                  <span style={{ color: 'var(--muted)', fontSize: '.8rem' }}>
                    ({categoryRows.length})
                  </span>
                </summary>
                <Card>
                  <ConfigReadOnlyTable rows={categoryRows} />
                </Card>
              </details>
            ))
          )}
        </>
      )}
    </div>
  );
}
