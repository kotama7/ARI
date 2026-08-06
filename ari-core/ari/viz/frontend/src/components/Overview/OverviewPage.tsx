// ARI Dashboard – v2 run Overview workspace (gui_refresh task 07 Wave 4b;
// plan 07 §Run Overview and Live Monitor, plan 01 §Global shell context).
//
// READ-ONLY. The plan-07 P1/P2 disclosure layers ONLY (P3+ land later):
//   P1 — lifecycle badge (run detail DTO `status`), current research phase
//        (the frozen /state vocabulary idle/starting/bfts/paper/review —
//        see RESEARCH_PHASES), last-update freshness, and a blocker surface
//        (DegradedState when the RQGM overview read model reports degraded
//        reasons or a broken integrity chain — RQGM runs only);
//   P2 — StatBoxes (node_count / review_score / best_metric from the run
//        summary DTO) and workspace links: Tree (legacy), Config browser
//        (#/config?run=), Governance (#/governance?run=, only when the run
//        detail DTO reports capabilities.rqgm).
//
// Truth rule (plan 07): research phase and governance stage are NEVER mixed —
// when the run is RQGM they render as two separate labelled rows, and the
// governance stage row never appears for a simple_bfts run. RQGM data is
// read through the plan-08 read models only (viz never imports ari.rqgm).
//
// Run scoping: reads `?run=` from the hash query (#/overview?run=<id>) — the
// ConfigBrowserPage pattern; no sessionStorage handoff. Realtime: topics
// 'run' + 'tree' via useRunEvents (events are invalidations, never data);
// a dropped stream keeps the last snapshot under a StaleDataBanner and is
// never presented as "run stopped" (plan 01 §Empty and degraded states).

import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useT } from '../../i18n';
import {
  useRqgmOverviewV1,
  useRunSummaryV1,
  useRunV1,
  v1Keys,
} from '../../hooks/useV1';
import { useRunEvents } from '../../hooks/useRunEvents';
import { LogsPanel } from './LogsPanel';
import type { EventTopic } from '../../shared/realtime/eventStream';
import {
  Badge,
  Card,
  DegradedState,
  EmptyState,
  ErrorState,
  LoadingState,
  StaleDataBanner,
  StatBox,
  StatusBadge,
} from '../common';
import type { ApiErrorV1, RqgmOverviewV1 } from '../../services/api/v1';

// ── helpers ─────────────────────────────────────────────────────────────

/** `run` query param of the current hash (#/overview?run=<run_id>) or ''. */
function runFromHash(): string {
  const query = window.location.hash.split('?')[1] ?? '';
  return new URLSearchParams(query).get('run') ?? '';
}

/** err.message plus the envelope's request_id (support handle, plan 04). */
function errorText(err: ApiErrorV1, requestIdLabel: string): string {
  const rid = err.request_id ? ` (${requestIdLabel}: ${err.request_id})` : '';
  return `${err.message}${rid}`;
}

/** mtime_utc (ISO 8601) -> locale string; raw value when unparseable. */
function formatFreshness(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

/**
 * The frozen research-phase vocabulary: /state `current_phase` values
 * (idle/starting/bfts/paper/review) which the new phase model must contain
 * (plan 07 parity requirement). The run detail DTO's `phase` carries
 * bfts/paper/review or null; null renders as 'idle' (nothing derived yet).
 * Exported for the OverviewPage vocabulary test.
 */
export const RESEARCH_PHASES = [
  'idle',
  'starting',
  'bfts',
  'paper',
  'review',
] as const;

/** Run detail `phase` -> research-phase token (never a governance term). */
export function researchPhaseOf(phase: string | null | undefined): string {
  return phase ?? 'idle';
}

/**
 * Blocker lines from the RQGM overview read model: verbatim degraded
 * reasons plus one line per broken/unverified integrity surface. Empty
 * array = no governance blockers. Presentation only — the reasons are the
 * backend's committed derivation, never re-computed here.
 */
export function governanceBlockers(overview: RqgmOverviewV1): string[] {
  const lines: string[] = [...(overview.degraded_reasons ?? [])];
  const integrity = overview.integrity;
  if (!integrity.transitions_chain_ok) lines.push('transitions chain: broken');
  if (!integrity.registry_verified) lines.push('registry snapshot: not verified');
  if (!integrity.audit_chain_ok) lines.push('audit chain: broken');
  return lines;
}

// ── page ────────────────────────────────────────────────────────────────

// Overview shows both run-level state and the tree-derived counters, so both
// topics keep it fresh (ADR-03 realtime adoption).
const RUN_TOPICS: readonly EventTopic[] = ['run', 'tree'];

/** One labelled P1 row (label left, value right — never merged rows). */
function LabeledRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'baseline',
        gap: 12,
        padding: '4px 0',
      }}
    >
      <span
        style={{
          color: 'var(--text-muted)',
          fontSize: '.78rem',
          fontWeight: 600,
          textTransform: 'uppercase',
          letterSpacing: '.05em',
          flex: '0 0 160px',
        }}
      >
        {label}
      </span>
      <span style={{ fontSize: '.85rem' }}>{children}</span>
    </div>
  );
}

export function OverviewPage() {
  const t = useT();

  // Route dispatch strips the query string, so the page owns the ?run param
  // itself (ConfigBrowserPage pattern — including in-place hash changes).
  const [runId, setRunId] = useState<string>(runFromHash);
  useEffect(() => {
    const onHashChange = () => setRunId(runFromHash());
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  const detailQ = useRunV1(runId);
  const summaryQ = useRunSummaryV1(runId);
  // capabilities.rqgm from the run detail DTO (artifact presence, plan 08).
  const rqgm = detailQ.data?.capabilities?.rqgm === true;
  const rqgmOverviewQ = useRqgmOverviewV1(runId, rqgm);

  const queryClient = useQueryClient();
  const { connectionState, lastEventAt } = useRunEvents(
    runId === '' ? null : runId,
    RUN_TOPICS,
  );
  // Realtime → rqgm cache glue (GovernancePage pattern): a delivered event is
  // an invalidation signal for this run's rqgm scope, never data (plan 04).
  useEffect(() => {
    if (lastEventAt !== null && runId !== '') {
      void queryClient.invalidateQueries({ queryKey: v1Keys.rqgm(runId) });
    }
  }, [lastEventAt, runId, queryClient]);

  // Hard error only when there is no snapshot to show; refetch failures over
  // cached data are freshness notices (plan 01 §Empty and degraded states).
  const hardError: ApiErrorV1 | null =
    detailQ.isError && detailQ.data === undefined
      ? detailQ.error
      : summaryQ.isError && summaryQ.data === undefined
        ? summaryQ.error
        : null;
  const stale =
    runId !== '' &&
    ((detailQ.data !== undefined && detailQ.isError) ||
      (summaryQ.data !== undefined && summaryQ.isError) ||
      connectionState !== 'live');
  const loading = runId !== '' && (detailQ.isPending || summaryQ.isPending);
  const lastUpdatedMs = Math.max(
    detailQ.dataUpdatedAt || 0,
    summaryQ.dataUpdatedAt || 0,
    lastEventAt ?? 0,
  );

  const refetchAll = () => {
    void detailQ.refetch();
    void summaryQ.refetch();
    if (runId !== '') {
      void queryClient.invalidateQueries({ queryKey: v1Keys.rqgm(runId) });
    }
  };

  const detail = detailQ.data;
  const summary = summaryQ.data;
  const rqgmOverview = rqgm ? rqgmOverviewQ.data : undefined;
  const blockers = rqgmOverview ? governanceBlockers(rqgmOverview) : [];

  let body;
  if (runId === '') {
    body = (
      <Card>
        <EmptyState icon="🧭" message={t('ov_no_run')} hint={t('ov_no_run_hint')} />
      </Card>
    );
  } else if (hardError) {
    body = (
      <ErrorState
        message={errorText(hardError, t('ov_request_id'))}
        onRetry={refetchAll}
      />
    );
  } else if (loading || detail === undefined || summary === undefined) {
    body = <LoadingState />;
  } else {
    body = (
      <>
        {/* P1 — blocker surface (governance record degraded/integrity-broken;
            describes the governance artifacts, never research failure). */}
        {blockers.length > 0 && (
          <div style={{ marginBottom: 16 }}>
            <DegradedState
              title={t('ov_blockers_title')}
              detail={t('ov_blockers_gov_note')}
            >
              <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
                {blockers.map((line, i) => (
                  <li key={i} style={{ fontSize: '.8rem' }}>
                    {line}
                  </li>
                ))}
              </ul>
            </DegradedState>
          </div>
        )}

        {/* P1 — lifecycle / research phase / (separate) governance stage /
            freshness. Research phase and governance stage are two separate
            labelled rows, never one merged row (plan 07). */}
        <Card>
          <LabeledRow label={t('ov_lifecycle')}>
            <StatusBadge status={detail.status} />
          </LabeledRow>
          <LabeledRow label={t('ov_research_phase')}>
            <Badge variant="blue">{researchPhaseOf(detail.phase)}</Badge>
          </LabeledRow>
          {rqgm && (
            <LabeledRow label={t('ov_governance_stage')}>
              <Badge variant="muted">
                {rqgmOverview?.current_epoch ?? t('gov_unknown')}
              </Badge>{' '}
              <span style={{ color: 'var(--text-muted)', fontSize: '.78rem' }}>
                {t('gov_overview_policy')}:{' '}
                <code style={{ fontSize: '.78rem' }}>
                  {rqgmOverview?.utility_policy_hash ?? t('gov_unknown')}
                </code>
              </span>
            </LabeledRow>
          )}
          <LabeledRow label={t('ov_last_update')}>
            {formatFreshness(detail.mtime_utc)}
          </LabeledRow>
          {rqgm && (
            <p
              style={{
                color: 'var(--text-muted)',
                fontSize: '.75rem',
                margin: '8px 0 0',
              }}
            >
              {t('ov_phase_gov_separate_note')}
            </p>
          )}
        </Card>

        {/* P2 — counters from the run summary DTO. */}
        <div className="grid-3" style={{ margin: '16px 0' }}>
          <StatBox value={summary.node_count} label={t('nodes_explored')} />
          <StatBox
            value={summary.review_score != null ? summary.review_score : '—'}
            label={t('review_score')}
          />
          <StatBox
            value={summary.best_metric != null ? summary.best_metric : '—'}
            label={t('best_metric')}
          />
        </div>

        {/* P2 — workspace links (deep links; run-explicit where v2). */}
        <Card title={t('ov_links_title')}>
          <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
            <a href="#/tree">{t('nav_tree')}</a>
            <a href={`#/config?run=${encodeURIComponent(runId)}`}>
              {t('nav_config')}
            </a>
            {rqgm && (
              <a href={`#/governance?run=${encodeURIComponent(runId)}`}>
                {t('nav_governance')}
              </a>
            )}
          </div>
        </Card>

        {/* P4 — collapsible cursor log explorer over {ckpt}/ari.log (task 07
            tail; plan 07 §Artifacts, logs, and diagnostics). Shares this
            page's single event-stream subscription for tail-follow. */}
        <div style={{ marginTop: 16 }}>
          <LogsPanel
            runId={runId}
            lastEventAt={lastEventAt}
            connectionState={connectionState}
          />
        </div>
      </>
    );
  }

  return (
    <div className="page active" style={{ display: 'block' }}>
      <h1>{t('ov_title')}</h1>
      <p className="subtitle">{t('ov_subtitle')}</p>

      {runId !== '' && (
        <p style={{ color: 'var(--text-muted)', fontSize: '.85rem' }}>
          {t('ov_run_label')}: <code style={{ fontSize: '.85rem' }}>{runId}</code>
        </p>
      )}

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

      {body}
    </div>
  );
}
