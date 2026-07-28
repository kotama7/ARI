// ARI Dashboard – Projects workspace (gui_refresh Wave 2b; plans 01 §Route
// model, 07 §Projects and run portfolio).
//
// The FIRST v2 vertical slice: built ONLY from the typed /api/v1 react-query
// hooks (useV1: projects -> runs of the virtual 'default' project), the shared
// common components, and semantic CSS tokens (no hex literals). Read-only —
// NO governance data and NO run mutation live here (task 08 owns RQGM; launch
// stays in the wizard).
//
// Navigation handoff: the FIRST action per run row is the run-explicit
// Overview link ('#/overview?run=<run_id>' — gui_refresh Wave 4b; the URL
// shape that replaces implicit handoffs, plan 07 §Cross-workspace
// coordination). Row click still follows the existing legacy handoff used by
// ExperimentsPage.viewResults (sessionStorage 'ari_selected_checkpoint' + the
// '#/results' hash) so the legacy Results page picks the run up unchanged.
// TODO(gui_refresh Wave 4: run-explicit URL): replace the remaining
// sessionStorage Results handoff with the run-scoped route
// '#/runs/:runId/results' (plan 01 §Route model; plan 07 §Cross-workspace
// coordination bans implicit session-storage handoffs in the target state).

import { useT } from '../../i18n';
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
 * capabilities.rqgm from a run row. RunSummaryV1 does not (yet) declare the
 * capabilities map — only RunDetailV1 does — so read it defensively: the chip
 * renders as soon as the list payload carries `capabilities: {rqgm: true}`.
 * The chip is an execution-mode marker ONLY — RQGM accepted/rejected must
 * never be converted into an overall research success badge (plan 07).
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
  const t = useT();
  const projectsQ = useProjectsV1();
  // Wave 2a serves exactly one project: the virtual 'default' one (ADR-08).
  const projectId = projectsQ.data?.projects[0]?.project_id ?? '';
  const runsQ = useRunsV1(projectId);
  // Realtime invalidation + connection state (plan 03 §Realtime integration).
  const { connectionState, lastEventAt } = useRunEvents(null, LIST_TOPICS);

  const openRun = (runId: string) => {
    // Legacy handoff (see header TODO for the Wave-4 replacement).
    sessionStorage.setItem('ari_selected_checkpoint', runId);
    window.location.hash = '#/results';
  };

  // Hard error only when there is no snapshot to show; with cached data we
  // keep the table and show a freshness banner instead (plan 01 §Empty and
  // degraded states: never claim "stopped" while a snapshot exists).
  const hardError: ApiErrorV1 | null =
    projectsQ.isError && projectsQ.data === undefined
      ? projectsQ.error
      : runsQ.isError && runsQ.data === undefined
        ? runsQ.error
        : null;
  // Data-freshness banner: a refetch failure over cached data OR a dropped
  // event stream. Either way we keep showing the snapshot and say how fresh
  // it is — a disconnect is never presented as "run stopped" (plan 01
  // §Empty and degraded states; plan 04: never misreport stale state as
  // stopped/failed while SSE is down).
  const stale =
    (runsQ.data !== undefined && runsQ.isError) || connectionState !== 'live';
  const loading =
    projectsQ.isPending || (projectId !== '' && runsQ.isPending);
  // Freshest known instant: last successful fetch vs last realtime event.
  const lastUpdatedMs = Math.max(runsQ.dataUpdatedAt || 0, lastEventAt ?? 0);

  const runs = runsQ.data?.runs ?? [];

  return (
    <div className="page active" style={{ display: 'block' }}>
      <h1>{t('projects_title')}</h1>
      <p className="subtitle">{t('projects_subtitle')}</p>

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
        <Card>
          {runs.length === 0 ? (
            <div>
              <EmptyState icon={'📁'} message={t('projects_empty')} />
              {/* Next actions (plan 07 §Projects: create/import/resume).
                  Plain links; all three land on the launch surface for now. */}
              <div
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
            <table>
              <thead>
                <tr>
                  <th>{t('projects_run_id')}</th>
                  <th>{t('status')}</th>
                  <th>{t('projects_nodes')}</th>
                  <th>{t('review_score')}</th>
                  <th>{t('projects_best_metric')}</th>
                  <th>{t('projects_freshness')}</th>
                  <th>{t('projects_capabilities')}</th>
                  <th>{t('projects_overview_link')}</th>
                  <th>{t('projects_config_link')}</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr
                    key={run.run_id}
                    onClick={() => openRun(run.run_id)}
                    style={{ cursor: 'pointer' }}
                  >
                    <td>
                      <code style={{ fontSize: '.8rem' }}>{run.run_id}</code>
                    </td>
                    <td>
                      <StatusBadge status={run.status} />
                    </td>
                    <td>{run.node_count}</td>
                    <td>
                      {run.review_score != null ? (
                        <strong>{run.review_score}</strong>
                      ) : (
                        <span style={{ opacity: 0.4 }}>—</span>
                      )}
                    </td>
                    <td>
                      {run.best_metric != null ? (
                        run.best_metric
                      ) : (
                        <span style={{ opacity: 0.4 }}>—</span>
                      )}
                    </td>
                    <td style={{ color: 'var(--muted)', fontSize: '.8rem' }}>
                      {formatFreshness(run.mtime_utc)}
                    </td>
                    <td>
                      {hasRqgm(run) ? (
                        <Badge variant="blue">RQGM</Badge>
                      ) : (
                        <span style={{ opacity: 0.4 }}>—</span>
                      )}
                    </td>
                    <td>
                      {/* FIRST action (Wave 4b): the run-explicit v2 Overview
                          workspace — the URL shape replacing the sessionStorage
                          handoff direction (plan 07 §Cross-workspace
                          coordination). */}
                      <a
                        href={`#/overview?run=${encodeURIComponent(run.run_id)}`}
                        onClick={(e) => e.stopPropagation()}
                      >
                        {t('projects_overview_link')}
                      </a>
                    </td>
                    <td>
                      {/* Read-only effective-config browser (Wave 3b). The
                          run-explicit ?run= query IS the target-state URL
                          shape — no sessionStorage handoff here. */}
                      <a
                        href={`#/config?run=${encodeURIComponent(run.run_id)}`}
                        onClick={(e) => e.stopPropagation()}
                      >
                        {t('projects_config_link')}
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      )}
    </div>
  );
}
