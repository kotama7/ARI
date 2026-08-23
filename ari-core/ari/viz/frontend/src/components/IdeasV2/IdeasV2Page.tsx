// ARI Dashboard – v2 Ideas workspace (gui_refresh task 07 Wave 4c).
// The route exists in exactly one place — its ROUTE_REGISTRY entry, which
// the router and the sidebar are both derived from — and like every v2
// workspace it is run-explicit: what it renders is a function of the URL
// alone, never of a process-wide active checkpoint
// (docs/guides/dashboard.md, "Run-explicit URLs and deep links").
//
// READ-ONLY. Run-explicit idea/hypothesis exploration over the typed v1
// endpoints: GET /api/v1/runs/{run_id}/idea (useRunIdeaV1 — a pure
// idea.json read with honest absence semantics) plus the run tree
// (useRunTreeV1) for the BFTS hypothesis list and the idea-strategy
// distribution. The legacy #/idea page keeps running unchanged in parallel
// (parity invariant); while the gui_v2 flag is on this route takes over the
// 'Idea' sidebar slot (routeRegistry navReplaces — the Tree stage's
// mechanism).
//
// Information parity with the legacy IdeaPage (its /state-derived cards),
// re-sourced run-explicitly:
//   - Research goal: NOT exposed by any run-scoped v1 endpoint (the legacy
//     /state serves it for the ACTIVE checkpoint only, from results.json/
//     experiment.md). The card therefore shows the AppContext /state goal
//     ONLY when state.checkpoint_id equals ?run= (run-identity gate) and
//     otherwise an explicit "active checkpoint only" note — honest absence,
//     never another run's goal.
//   - Gap analysis / primary metric + rationale / generated (VirSci)
//     hypotheses: RunIdeaV1 verbatim. present=false without degraded
//     reasons renders the EmptyState ("run has not generated ideas yet");
//     a malformed idea.json (present=false WITH degraded_reasons) renders
//     DegradedState with the parser's reasons — absence and corruption are
//     never conflated: "no idea.json" and "an idea.json that would not
//     parse" are different diagnostics and each is reported as itself,
//     never as an empty result.
//   - BFTS hypotheses + best hypothesis + strategy distribution: run tree
//     nodes (same selection logic as the legacy page: eval_summary carriers;
//     label counts over all nodes). Deep links: every listed node id — and
//     the best hypothesis explicitly — opens the TreeV2 workspace at
//     #/tree2?run=<id>&node=<id> when the node id is resolvable.
//
// Run scoping: reads `?run=` from the hash query (#/ideas2?run=<id> — the
// ConfigBrowser/TreeV2 pattern). No write path exists on this page.

import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { useT } from '../../i18n';
import { useAppContext } from '../../context/AppContext';
import { useRunIdeaV1, useRunTreeV1 } from '../../hooks/useV1';
import {
  Badge,
  Card,
  DegradedState,
  EmptyState,
  ErrorState,
  LoadingState,
} from '../common';
import { toTreeNodes } from '../TreeV2/treeNodes';
import type { TreeNode } from '../../types';
import type { ApiErrorV1 } from '../../services/api/v1';

// ── visual maps (semantic Badge variants — no raw hex; frozen orchestrator
// vocabularies pick colors only, unknown tokens render muted verbatim) ────

type BadgeVariant = 'green' | 'red' | 'blue' | 'yellow' | 'muted';

const STATUS_VARIANT: Record<string, BadgeVariant> = {
  pending: 'muted',
  running: 'blue',
  success: 'green',
  failed: 'red',
  abandoned: 'yellow',
};

const LABEL_VARIANT: Record<string, BadgeVariant> = {
  draft: 'blue',
  improve: 'green',
  debug: 'yellow',
  ablation: 'muted',
  validation: 'green',
};

// ── hash query helper (#/ideas2?run=<id>) ───────────────────────────────

/** `run` query param of the current hash; '' when absent. */
function runFromHash(): string {
  const query = window.location.hash.split('?')[1] ?? '';
  return new URLSearchParams(query).get('run') ?? '';
}

// ── typed views over the verbatim idea.json pass-through ────────────────

/** Scalar score as display text; null when absent/non-scalar (honest). */
function scoreText(v: unknown): string | null {
  if (typeof v === 'number' && Number.isFinite(v)) return String(v);
  if (typeof v === 'string' && v !== '') return v;
  return null;
}

/** One VirSci idea entry coerced for display — nothing is invented. */
export interface IdeaEntryView {
  title: string;
  description: string;
  noveltyScore: string | null;
  feasibilityScore: string | null;
  overallScore: string | null;
  experimentPlan: string;
}

/**
 * Coerce the on-disk VirSci idea dicts (RunIdeaV1.ideas, loose schema by
 * design) into display rows. Mirrors the legacy IdeaPage rendering: the
 * experiment plan may be a list (numbered lines), an object (key: value
 * lines), or a scalar. Exported for the page test.
 */
export function toIdeaEntries(raw: Array<Record<string, unknown>>): IdeaEntryView[] {
  return raw.map((idea, idx) => {
    let planText = '';
    const plan = idea.experiment_plan;
    if (Array.isArray(plan)) {
      planText = plan.map((s, i) => `${i + 1}. ${String(s)}`).join('\n');
    } else if (typeof plan === 'object' && plan !== null) {
      planText = Object.entries(plan as Record<string, unknown>)
        .map(([k, v]) => `${k}: ${String(v)}`)
        .join('\n');
    } else if (plan !== undefined && plan !== null && plan !== '') {
      planText = String(plan);
    }
    return {
      title:
        typeof idea.title === 'string' && idea.title !== ''
          ? idea.title
          : `Hypothesis ${idx + 1}`,
      description: typeof idea.description === 'string' ? idea.description : '',
      noveltyScore: scoreText(idea.novelty_score),
      feasibilityScore: scoreText(idea.feasibility_score),
      overallScore: scoreText(idea.overall_score),
      experimentPlan: planText,
    };
  });
}

// ── BFTS hypothesis selection (legacy IdeaPage logic, unchanged) ────────

/**
 * Best hypothesis node: highest score among eval_summary carriers (a node
 * without a numeric score counts 1 when success, else 0 — the legacy
 * tie-break). Null when no node carries an eval_summary. Exported for the
 * page test.
 */
export function bestHypothesisNode(nodes: TreeNode[]): TreeNode | null {
  let best: TreeNode | null = null;
  let bestScore = -Infinity;
  for (const n of nodes) {
    if (n.eval_summary === null || n.eval_summary === '') continue;
    const sc = typeof n.score === 'number' ? n.score : n.status === 'success' ? 1 : 0;
    if (sc > bestScore) {
      bestScore = sc;
      best = n;
    }
  }
  return best;
}

/** Nodes listed as hypotheses: eval_summary carriers not still pending. */
function hypothesisNodes(nodes: TreeNode[]): TreeNode[] {
  return nodes.filter(
    (n) => n.eval_summary !== null && n.eval_summary !== '' && n.status !== 'pending',
  );
}

/** Label -> count over ALL nodes (the legacy strategy distribution). */
function labelCounts(nodes: TreeNode[]): Array<[string, number]> {
  const counts = new Map<string, number>();
  for (const n of nodes) {
    const label = n.label !== '' ? n.label : 'unknown';
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return [...counts.entries()];
}

/** err.message plus the envelope's request_id — every /api/v1 response
 * carries that id precisely so a user can quote it in a bug report, so it is
 * surfaced rather than swallowed. */
function errorText(err: ApiErrorV1, requestIdLabel: string): string {
  const rid = err.request_id ? ` (${requestIdLabel}: ${err.request_id})` : '';
  return `${err.message}${rid}`;
}

/** Deep link into the TreeV2 workspace at one node — a node reference is
 * always a URL, so "look at this node" survives copy/paste and reload
 * instead of being a sequence of clicks. */
function treeNodeHref(runId: string, nodeId: string): string {
  return `#/tree2?run=${encodeURIComponent(runId)}&node=${encodeURIComponent(nodeId)}`;
}

// ── section building blocks ─────────────────────────────────────────────

function MutedLine({ children }: { children: ReactNode }) {
  return (
    <p style={{ color: 'var(--text-muted)', fontSize: '.8rem', margin: 0 }}>{children}</p>
  );
}

function HypothesisRow({ runId, node }: { runId: string; node: TreeNode }) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
        padding: '8px 0',
        borderTop: '1px solid var(--border)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
        <Badge variant={LABEL_VARIANT[node.label] ?? 'muted'}>{node.label || 'other'}</Badge>
        <Badge variant={STATUS_VARIANT[node.status] ?? 'muted'}>
          {node.status || 'unknown'}
        </Badge>
        <a href={treeNodeHref(runId, node.id)}>
          <code style={{ fontSize: '.72rem' }}>{node.id}</code>
        </a>
        {typeof node.score === 'number' && (
          <code style={{ fontSize: '.75rem', color: 'var(--status-success)' }}>
            {String(node.score)}
          </code>
        )}
      </div>
      <div style={{ fontSize: '.8rem', lineHeight: 1.5 }}>{node.eval_summary}</div>
    </div>
  );
}

/** Research goal card — run-identity-gated legacy /state source (header). */
function ResearchGoalCard({ runId }: { runId: string }) {
  const t = useT();
  const { state } = useAppContext();
  const isActiveRun = state !== null && state.checkpoint_id === runId;
  const goal = isActiveRun ? state.experiment_goal || '' : '';
  const goalFull = isActiveRun ? state.experiment_md_content || '' : '';

  let body: ReactNode;
  if (!isActiveRun) {
    body = <MutedLine>{t('ideas2_goal_unavailable')}</MutedLine>;
  } else if (goal === '' && goalFull === '') {
    body = <MutedLine>{t('ideas2_goal_absent')}</MutedLine>;
  } else {
    body = (
      <>
        {goal !== '' && (
          <div style={{ fontSize: '.88rem', lineHeight: 1.6 }}>{goal}</div>
        )}
        {goalFull !== '' && (
          <details style={{ marginTop: goal !== '' ? 8 : 0 }}>
            <summary
              style={{ cursor: 'pointer', fontSize: '.78rem', color: 'var(--accent)' }}
            >
              {t('show_details')}
            </summary>
            <pre
              style={{
                fontSize: '.78rem',
                whiteSpace: 'pre-wrap',
                marginTop: 6,
                padding: 8,
                background: 'var(--bg)',
                border: '1px solid var(--border)',
                borderRadius: 4,
                maxHeight: 400,
                overflow: 'auto',
              }}
            >
              {goalFull}
            </pre>
          </details>
        )}
      </>
    );
  }
  return (
    <Card title={t('ideas2_goal_title')}>
      <div data-testid="ideas2-goal">{body}</div>
    </Card>
  );
}

// ── page ────────────────────────────────────────────────────────────────

export function IdeasV2Page() {
  const t = useT();

  // Route dispatch strips the query string, so the page owns ?run= itself
  // (ConfigBrowser/TreeV2 pattern — including in-place hash changes).
  const [runId, setRunId] = useState(runFromHash);
  useEffect(() => {
    const onHashChange = () => setRunId(runFromHash());
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  const ideaQ = useRunIdeaV1(runId);
  const treeQ = useRunTreeV1(runId);

  const nodes = useMemo(() => toTreeNodes(treeQ.data?.nodes ?? []), [treeQ.data]);
  const ideaEntries = useMemo(
    () => toIdeaEntries(ideaQ.data?.ideas ?? []),
    [ideaQ.data],
  );
  const bestNode = useMemo(() => bestHypothesisNode(nodes), [nodes]);
  const hypotheses = useMemo(() => hypothesisNodes(nodes), [nodes]);
  const strategy = useMemo(() => labelCounts(nodes), [nodes]);

  let body: ReactNode;
  if (runId === '') {
    body = (
      <Card>
        <EmptyState
          icon="💡"
          message={t('ideas2_no_run')}
          hint={t('ideas2_no_run_hint')}
        />
      </Card>
    );
  } else if (ideaQ.isPending) {
    body = <LoadingState />;
  } else if (ideaQ.isError) {
    body = (
      <ErrorState
        message={errorText(ideaQ.error, t('ideas2_request_id'))}
        onRetry={() => void ideaQ.refetch()}
      />
    );
  } else if (!ideaQ.data.present) {
    const reasons = ideaQ.data.degraded_reasons ?? [];
    body =
      reasons.length > 0 ? (
        // Malformed idea.json: a diagnostics surface, NOT the "no ideas yet"
        // empty state — absence and corruption are never conflated.
        <DegradedState detail={reasons.join('; ')} onRetry={() => void ideaQ.refetch()} />
      ) : (
        <Card>
          <EmptyState
            icon="💡"
            message={t('ideas2_absent')}
            hint={t('ideas2_absent_hint')}
          />
        </Card>
      );
  } else {
    const idea = ideaQ.data;
    const degraded = idea.degraded_reasons ?? [];
    body = (
      <>
        {degraded.length > 0 && (
          <div style={{ marginBottom: 12 }}>
            <DegradedState detail={degraded.join('; ')} />
          </div>
        )}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(min(320px, 100%), 1fr))',
            gap: 16,
            alignItems: 'start',
          }}
        >
          {/* ── Left column: goal / gap / metric ── */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <ResearchGoalCard runId={runId} />

            <Card title={t('ideas2_gap_title')}>
              {idea.gap_analysis !== null && idea.gap_analysis !== '' ? (
                <div
                  data-testid="ideas2-gap"
                  style={{ fontSize: '.85rem', whiteSpace: 'pre-wrap', lineHeight: 1.5 }}
                >
                  {idea.gap_analysis}
                </div>
              ) : (
                <MutedLine>{t('ideas2_gap_absent')}</MutedLine>
              )}
            </Card>

            <Card title={t('ideas2_metric_title')}>
              {idea.primary_metric !== null && idea.primary_metric !== '' ? (
                <div data-testid="ideas2-metric">
                  <b style={{ fontSize: '.88rem' }}>{idea.primary_metric}</b>
                  {idea.metric_rationale !== null && idea.metric_rationale !== '' && (
                    <div
                      style={{
                        fontSize: '.78rem',
                        color: 'var(--text-muted)',
                        marginTop: 4,
                      }}
                    >
                      {idea.metric_rationale}
                    </div>
                  )}
                </div>
              ) : (
                <MutedLine>{t('ideas2_metric_absent')}</MutedLine>
              )}
            </Card>
          </div>

          {/* ── Right column: hypotheses / BFTS / strategy ── */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <Card title={t('ideas2_hyp_title')}>
              {ideaEntries.length === 0 ? (
                <MutedLine>{t('ideas2_hyp_empty')}</MutedLine>
              ) : (
                ideaEntries.map((entry, idx) => (
                  <div
                    key={idx}
                    style={
                      idx > 0
                        ? {
                            marginTop: 12,
                            paddingTop: 12,
                            borderTop: '1px solid var(--border)',
                          }
                        : undefined
                    }
                  >
                    <div style={{ fontWeight: 700, fontSize: '.88rem' }}>{entry.title}</div>
                    <div
                      style={{
                        display: 'flex',
                        gap: 12,
                        fontSize: '.78rem',
                        color: 'var(--text-muted)',
                        marginTop: 4,
                      }}
                    >
                      {entry.noveltyScore !== null && (
                        <span>
                          {t('ideas2_score_novelty')} <b>{entry.noveltyScore}</b>
                        </span>
                      )}
                      {entry.feasibilityScore !== null && (
                        <span>
                          {t('ideas2_score_feasibility')} <b>{entry.feasibilityScore}</b>
                        </span>
                      )}
                      {entry.overallScore !== null && (
                        <span>
                          {t('ideas2_score_overall')} <b>{entry.overallScore}</b>
                        </span>
                      )}
                    </div>
                    {entry.description !== '' && (
                      <div style={{ fontSize: '.82rem', marginTop: 6, lineHeight: 1.5 }}>
                        {entry.description}
                      </div>
                    )}
                    {entry.experimentPlan !== '' && (
                      <details style={{ marginTop: 8 }}>
                        <summary
                          style={{
                            cursor: 'pointer',
                            fontSize: '.78rem',
                            color: 'var(--accent)',
                          }}
                        >
                          {t('ideas2_experiment_plan')}
                        </summary>
                        <pre
                          style={{
                            fontSize: '.78rem',
                            whiteSpace: 'pre-wrap',
                            marginTop: 4,
                            padding: 8,
                            background: 'var(--bg)',
                            border: '1px solid var(--border)',
                            borderRadius: 4,
                          }}
                        >
                          {entry.experimentPlan}
                        </pre>
                      </details>
                    )}
                  </div>
                ))
              )}
            </Card>

            <Card title={t('ideas2_bfts_title')}>
              {treeQ.isError ? (
                <MutedLine>{errorText(treeQ.error, t('ideas2_request_id'))}</MutedLine>
              ) : bestNode === null ? (
                <MutedLine>{t('ideas2_bfts_empty')}</MutedLine>
              ) : (
                <div data-testid="ideas2-bfts">
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                      flexWrap: 'wrap',
                      marginBottom: 6,
                    }}
                  >
                    <span
                      style={{
                        color: 'var(--text-muted)',
                        fontSize: '.72rem',
                        fontWeight: 600,
                        textTransform: 'uppercase',
                        letterSpacing: '.05em',
                      }}
                    >
                      {t('ideas2_best_label')}
                    </span>
                    <Badge variant={LABEL_VARIANT[bestNode.label] ?? 'muted'}>
                      {bestNode.label || 'other'}
                    </Badge>
                    {typeof bestNode.score === 'number' && (
                      <code style={{ fontSize: '.78rem' }}>{String(bestNode.score)}</code>
                    )}
                  </div>
                  <div style={{ fontSize: '.85rem', lineHeight: 1.6 }}>
                    {bestNode.eval_summary}
                  </div>
                  {/* Deep link: the best hypothesis opens the TreeV2 node
                      (node id resolvable — toTreeNodes drops id-less rows). */}
                  <div style={{ marginTop: 8 }}>
                    <a href={treeNodeHref(runId, bestNode.id)}>
                      {t('ideas2_best_open_tree')}
                    </a>
                  </div>
                  {hypotheses.length > 0 && (
                    <div style={{ marginTop: 12 }}>
                      <div
                        style={{
                          color: 'var(--text-muted)',
                          fontSize: '.72rem',
                          fontWeight: 600,
                          textTransform: 'uppercase',
                          letterSpacing: '.05em',
                          marginBottom: 2,
                        }}
                      >
                        {t('ideas2_bfts_all_label')} ({hypotheses.length})
                      </div>
                      {hypotheses.map((n) => (
                        <HypothesisRow key={n.id} runId={runId} node={n} />
                      ))}
                    </div>
                  )}
                </div>
              )}
            </Card>

            <Card title={t('ideas2_strategy_title')}>
              {nodes.length === 0 ? (
                <MutedLine>{t('ideas2_tree_empty')}</MutedLine>
              ) : (
                <div data-testid="ideas2-strategy">
                  <div
                    style={{
                      fontSize: '.78rem',
                      color: 'var(--text-muted)',
                      marginBottom: 8,
                    }}
                  >
                    {nodes.length} {t('ideas2_strategy_explored')}
                  </div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                    {strategy.map(([label, count]) => (
                      <Badge key={label} variant={LABEL_VARIANT[label] ?? 'muted'}>
                        {label} ×{count}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
            </Card>
          </div>
        </div>
      </>
    );
  }

  return (
    <div id="page-ideas2" className="page active">
      <h1 style={{ margin: 0 }}>{t('ideas2_title')}</h1>
      <p className="subtitle" style={{ margin: '4px 0 8px' }}>
        {t('ideas2_subtitle')}
      </p>
      {runId !== '' && (
        <p style={{ color: 'var(--text-muted)', fontSize: '.85rem', margin: '0 0 12px' }}>
          {t('ideas2_run_label')}: <code style={{ fontSize: '.85rem' }}>{runId}</code>
        </p>
      )}
      {body}
    </div>
  );
}
