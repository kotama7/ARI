// ARI Dashboard – Projects workspace (gui_refresh Wave 2b). The run
// portfolio: every run under the checkpoint search roots, listed as one
// virtual 'default' project.
//
// Two structural rules this page obeys. (1) The route exists in exactly one
// place — its ROUTE_REGISTRY entry; App.tsx dispatch and the Sidebar nav are
// both DERIVED from that entry, so a route can never exist in the nav but not
// the router. (2) Navigation state lives in the URL: every link out carries
// its run in the hash query, so a view is reloadable and shareable and two
// tabs on two runs cannot step on each other.
//
// The FIRST v2 vertical slice: built ONLY from the typed /api/v1 react-query
// hooks (useV1: projects -> runs of the virtual 'default' project), the shared
// common components, and semantic CSS tokens (no hex literals). Read-only —
// NO governance data and NO run mutation live here (the Governance workspace
// owns RQGM; launch stays in the wizard).
//
// Navigation handoff: every workspace link carries an explicit run query.
// The paper/results action opens the complete PDF/editor workspace at
// '#/results?run=<run_id>'; the legacy sessionStorage handoff remains only as
// a compatibility fallback for older callers.

import { useI18n } from '../../i18n';
import { useProjectsV1, useRunsV1 } from '../../hooks/useV1';
import { useRunEvents } from '../../hooks/useRunEvents';
import type { EventTopic } from '../../shared/realtime/eventStream';
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  StaleDataBanner,
  StatusBadge,
} from '../common';
import type { ApiErrorV1, RunSummaryV1 } from '../../services/api/v1';

// ── helpers ─────────────────────────────────────────────────────────────

/** err.message plus the envelope's request_id. Every /api/v1 failure carries
 *  a `req-<12 hex>` request_id minted per dispatch; surfacing it is what lets
 *  a user quote one handle that matches the server log. */
function errorText(err: ApiErrorV1, requestIdLabel: string): string {
  const rid = err.request_id ? ` (${requestIdLabel}: ${err.request_id})` : '';
  return `${err.message}${rid}`;
}

/** mtime_utc (ISO 8601) -> compact locale string; raw value when unparseable. */
function formatFreshness(iso: string, language: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const locale =
    language === 'ja' ? 'ja-JP' : language === 'zh' ? 'zh-CN' : 'en-US';
  return new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(d);
}

function readableRunName(run: RunSummaryV1): string {
  return (run.display_name || run.run_id).replace(/_/g, ' ');
}

/**
 * capabilities.rqgm from a run row. RunSummaryV1 does not (yet) declare the
 * capabilities map — only RunDetailV1 does — so read it defensively: the chip
 * renders as soon as the list payload carries `capabilities: {rqgm: true}`.
 * The chip is an execution-mode marker ONLY — RQGM accepted/rejected must
 * never be converted into an overall research success badge: governance
 * standing is a capability state, not a verdict on the science.
 */
function hasRqgm(run: RunSummaryV1): boolean {
  const caps = (run as { capabilities?: Record<string, boolean> }).capabilities;
  return caps?.rqgm === true;
}

// ── page ────────────────────────────────────────────────────────────────

// Module-level literal: the whole run portfolio, so no run_id filter — every
// run's 'run' events refresh the list (ADR-03 realtime adoption).
const LIST_TOPICS: readonly EventTopic[] = ['run'];

export function ProjectsPage() {
  const { t, currentLang } = useI18n();
  const projectsQ = useProjectsV1();
  // Wave 2a serves exactly one project: the virtual 'default' one (ADR-08).
  const projectId = projectsQ.data?.projects[0]?.project_id ?? '';
  const runsQ = useRunsV1(projectId);
  // Realtime invalidation + connection state: an SSE event for these runs maps
  // to a query-cache invalidation and a refetch of the typed snapshot, never
  // to a direct state write — nothing on screen is rendered from an event, so
  // duplicate or out-of-order events are harmless.
  const { connectionState, lastEventAt } = useRunEvents(null, LIST_TOPICS);

  const openRun = (runId: string) => {
    // Keep the old handoff for compatibility while using the explicit,
    // bookmarkable run URL as the primary contract.
    sessionStorage.setItem('ari_selected_checkpoint', runId);
    window.location.hash = `#/results?run=${encodeURIComponent(runId)}`;
  };

  // Hard error only when there is no snapshot to show; with cached data we
  // keep the table and show a freshness banner instead — a degraded read is
  // reported as "this view may lag", never as "the run stopped", so an error
  // screen is reserved for the case where there is genuinely nothing to show.
  const hardError: ApiErrorV1 | null =
    projectsQ.isError && projectsQ.data === undefined
      ? projectsQ.error
      : runsQ.isError && runsQ.data === undefined
        ? runsQ.error
        : null;
  // Data-freshness banner: a refetch failure over cached data OR a dropped
  // event stream. Either way we keep showing the snapshot and say how fresh
  // it is — a stalled stream and a stopped run are different facts, and this
  // page never converts one into the other. A dropped stream is a freshness
  // problem, so the last snapshot stays on screen under the banner and no run
  // is relabelled stopped/failed because the transport went away.
  const stale =
    (runsQ.data !== undefined && runsQ.isError) || connectionState !== 'live';
  const loading =
    projectsQ.isPending || (projectId !== '' && runsQ.isPending);
  // Freshest known instant: last successful fetch vs last realtime event.
  const lastUpdatedMs = Math.max(runsQ.dataUpdatedAt || 0, lastEventAt ?? 0);

  const runs = runsQ.data?.runs ?? [];
  const activeCount = runs.filter((run) => run.status === 'running').length;
  const completeCount = runs.filter((run) =>
    ['completed', 'success'].includes(run.status),
  ).length;
  const attentionCount = runs.filter((run) =>
    ['failed', 'stopped', 'unknown'].includes(run.status),
  ).length;

  return (
    <div className="page active projects-page" style={{ display: 'block' }}>
      <header className="workspace-header">
        <div>
          <div className="workspace-eyebrow">{t('nav_group_portfolio')}</div>
          <h1>{t('projects_title')}</h1>
          <p className="subtitle">{t('projects_subtitle')}</p>
        </div>
        <a className="btn btn-primary workspace-primary-action" href="#/new">
          <span aria-hidden="true">{'＋'}</span>
          {t('nav_new')}
        </a>
      </header>

      {stale && (
        <div style={{ marginBottom: 16 }}>
          <StaleDataBanner
            lastUpdated={
              lastUpdatedMs > 0 ? new Date(lastUpdatedMs).toLocaleString() : null
            }
            onRefresh={() => {
              void projectsQ.refetch();
              void runsQ.refetch();
            }}
          />
        </div>
      )}

      {hardError ? (
        <ErrorState
          message={errorText(hardError, t('projects_request_id'))}
          onRetry={() => {
            void projectsQ.refetch();
            void runsQ.refetch();
          }}
        />
      ) : loading ? (
        <LoadingState />
      ) : (
        <>
          <section
            className="projects-summary-grid"
            aria-label={t('projects_title')}
          >
            <div className="projects-summary-item">
              <span>{t('projects_summary_all')}</span>
              <strong>{runs.length}</strong>
            </div>
            <div className="projects-summary-item is-active">
              <span>{t('projects_summary_active')}</span>
              <strong>{activeCount}</strong>
            </div>
            <div className="projects-summary-item is-complete">
              <span>{t('projects_summary_complete')}</span>
              <strong>{completeCount}</strong>
            </div>
            <div className="projects-summary-item is-attention">
              <span>{t('projects_summary_attention')}</span>
              <strong>{attentionCount}</strong>
            </div>
          </section>

          <Card className="projects-portfolio-card">
            <div className="projects-section-header">
              <div>
                <h2>{t('projects_runs_heading')}</h2>
                <span>{runs.length}</span>
              </div>
            </div>
          {runs.length === 0 ? (
            <div>
              <EmptyState icon={'📁'} message={t('projects_empty')} />
              {/* Next actions: an empty portfolio names what to do next
                  (create / import / resume) instead of dead-ending on an
                  empty state. Plain links; all three land on the launch
                  surface for now. */}
              <div
                className="projects-empty-actions"
                style={{
                  display: 'flex',
                  gap: 16,
                  justifyContent: 'center',
                  paddingBottom: 16,
                }}
              >
                <a href="#/new">{t('projects_action_create')}</a>
                <a href="#/new">{t('projects_action_import')}</a>
                <a href="#/new">{t('projects_action_resume')}</a>
              </div>
            </div>
          ) : (
            <table className="projects-table">
              <thead>
                <tr>
                  <th>{t('projects_run_id')}</th>
                  <th>{t('status')}</th>
                  <th>{t('projects_nodes')}</th>
                  <th>{t('review_score')}</th>
                  <th>{t('projects_best_metric')}</th>
                  <th>{t('projects_freshness')}</th>
                  <th>{t('projects_actions')}</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => {
                  const readableName = readableRunName(run);
                  return (
                    <tr
                      key={run.run_id}
                      onClick={() => openRun(run.run_id)}
                      className="projects-run-row"
                    >
                    <td data-label={t('projects_run_id')}>
                      <div className="projects-run-identity">
                        {readableName !== run.run_id && (
                          <strong className="projects-run-name">
                            {readableName}
                          </strong>
                        )}
                        <code>{run.run_id}</code>
                        {hasRqgm(run) && (
                          <Badge variant="blue">RQGM</Badge>
                        )}
                        {run.has_paper && (
                          <Badge variant="green">{t('projects_paper_badge')}</Badge>
                        )}
                      </div>
                    </td>
                    <td data-label={t('status')}>
                      <StatusBadge status={run.status} />
                    </td>
                    <td data-label={t('projects_nodes')}>{run.node_count}</td>
                    <td data-label={t('review_score')}>
                      {run.review_score != null ? (
                        <strong>{run.review_score}</strong>
                      ) : (
                        <span style={{ opacity: 0.4 }}>—</span>
                      )}
                    </td>
                    <td data-label={t('projects_best_metric')}>
                      {run.best_metric != null ? (
                        run.best_metric
                      ) : (
                        <span style={{ opacity: 0.4 }}>—</span>
                      )}
                    </td>
                    <td
                      data-label={t('projects_freshness')}
                      style={{ color: 'var(--muted)', fontSize: '.8rem' }}
                    >
                      {formatFreshness(run.mtime_utc, currentLang)}
                    </td>
                    <td
                      className="projects-actions-cell"
                      data-label={t('projects_actions')}
                    >
                      <div className="projects-action-links">
                      {/* FIRST action (Wave 4b): the run-explicit v2 Overview
                          workspace. Cross-workspace handoff travels in the
                          URL — one workspace hands another its run as `?run=`
                          — replacing the implicit sessionStorage handoff the
                          legacy pages use. */}
                      <a
                        href={`#/overview?run=${encodeURIComponent(run.run_id)}`}
                        onClick={(e) => e.stopPropagation()}
                      >
                        {t('projects_overview_link')}
                      </a>
                      {/* Complete generated-paper and result workspace. This
                          stays visible for every run; the label makes an
                          existing paper explicit when the API reports one. */}
                      <a
                        href={`#/results?run=${encodeURIComponent(run.run_id)}`}
                        onClick={(e) => e.stopPropagation()}
                      >
                        {run.has_paper
                          ? t('projects_paper_link')
                          : t('projects_results_link')}
                      </a>
                      {/* Read-only effective-config browser (Wave 3b). The
                          run-explicit ?run= query IS the target-state URL
                          shape — no sessionStorage handoff here. */}
                      <a
                        href={`#/config?run=${encodeURIComponent(run.run_id)}`}
                        onClick={(e) => e.stopPropagation()}
                      >
                        {t('projects_config_link')}
                      </a>
                      </div>
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          )}
          </Card>
        </>
      )}
    </div>
  );
}
