// ARI Dashboard – v2 Tree workspace (gui_refresh task 07 Wave 4c + task-07
// tail large-tree work). The tree workspace is run-explicit and read-only,
// and its rendered content is a function of its URL alone: the route exists
// only as a ROUTE_REGISTRY entry, dispatch ignores the query string, and this
// page owns `?run=` / `?node=` itself.
//
// READ-ONLY. Run-explicit tree exploration over the typed v1 tree endpoint
// (`useRunTreeV1`), REUSING the legacy D3 `TreeVisualization` component —
// the D3 zoom/pan/select code is imported, never forked. The legacy #/tree
// page keeps running unchanged in parallel (parity invariant); while the
// gui_v2 flag is on this route takes over the 'Tree' sidebar slot
// (routeRegistry navReplaces).
//
// Run/node scoping: reads `?run=` and `?node=` from the hash query
// (#/tree2?run=<id>&node=<id>). Selecting a node — by canvas click, table
// click, or table Enter — WRITES `?node=` back to the hash, so a selection
// is a shareable URL and BOTH views (canvas and table) re-render from the
// same URL state; the hash is the single source of truth for the selection.
//
// Large trees stay legible without hiding anything silently — level-of-detail
// + virtualized side table + keyboard navigation, the table being the
// equivalent tabular hierarchy for anyone not driving the canvas:
//   - Above LOD_NODE_THRESHOLD nodes the view default-collapses to
//     structural depth <= LOD_DEPTH_LIMIT plus the selected node's
//     ancestor path and its children. The filtering happens BEFORE the
//     node array reaches the legacy TreeVisualization (computeVisibleRows
//     in ./treeLod — a DFS that emits a node only when every ancestor is
//     expanded, so parent links inside the visible set stay intact and the
//     legacy component needs no changes).
//   - The reduction is NEVER silent — a subset is never presented as if it
//     were the whole tree, and the reader is always told how to see the
//     rest: an explicit
//     "showing N of M nodes (depth-limited)" banner with an [expand all]
//     opt-in appears whenever visible < total, and an expanded oversized
//     tree states "showing all M" with a way back to the depth limit.
//   - The side table (./TreeTablePanel) renders the SAME visible rows as
//     a windowed, depth-indented ARIA tree (role=tree/treeitem,
//     aria-level/expanded/selected) with roving tabindex, ArrowUp/Down to
//     move, ArrowLeft/Right to collapse/expand a subtree, Enter to select.
//
// Inspector (right panel, ./TreeV2Inspector): node summary using the
// FROZEN orchestrator vocabularies (NODE_STATUSES / NODE_LABELS —
// `ari.orchestrator.node` NodeStatus/NodeLabel verbatim; unknown values
// render verbatim, never remapped), metrics including `_scientific_score`
// and the RQGM sentinels (`_pre_penalty_score`, `_validated_attack_penalty`,
// `_utility_policy_hash` as a hash chip, `_stale`) with explicit labels,
// the node report via the existing legacy `/api/nodes/{run}/{node}/report`
// client, and deep links:
//   - Governance Score Lineage: #/governance?run=<id> — GovernancePage reads
//     ONLY `?run=` today (its node selection is component state), so the
//     link intentionally carries no node preselect and the UI says so.
//   - Config browser: #/config?run=<id>.
//
// Realtime: topic 'tree' via useRunEvents — the shared hook already maps a
// tree event to a runTree invalidation (events are invalidations, never
// data); a dropped stream keeps the last snapshot under a StaleDataBanner
// and is never presented as "run stopped" — a stalled stream and a stopped
// run are different facts, and a degraded read says "this view may lag"
// rather than changing the run's reported state.

import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { useT } from '../../i18n';
import { useRunTreeV1 } from '../../hooks/useV1';
import { useRunEvents } from '../../hooks/useRunEvents';
import type { EventTopic } from '../../shared/realtime/eventStream';
import { Button, Card, EmptyState, ErrorState, LoadingState, StaleDataBanner } from '../common';
import { TreeVisualization } from '../Tree/TreeVisualization';
import { toTreeNodes, sentinelsOf } from './treeNodes';
import { computeVisibleRows, LOD_NODE_THRESHOLD } from './treeLod';
import { TreeTablePanel } from './TreeTablePanel';
import { Inspector } from './TreeV2Inspector';
import type { ApiErrorV1 } from '../../services/api/v1';

// ── frozen orchestrator vocabularies ────────────────────────────────────
//
// The workspace renders the orchestrator's own status/label words verbatim
// and never invents a display vocabulary of its own: these lists mirror
// `ari.orchestrator.node`, and a value outside them is shown as it arrived
// rather than remapped into a known one.

/** Node status vocabulary — verbatim `ari.orchestrator.node.NodeStatus`. */
export const NODE_STATUSES = [
  'pending',
  'running',
  'success',
  'failed',
  'abandoned',
] as const;

/** Node label vocabulary — verbatim `ari.orchestrator.node.NodeLabel`
 * ('other' is the catch-all for LLM-invented labels; the raw string is
 * preserved server-side on `raw_label`). */
export const NODE_LABELS = [
  'draft',
  'improve',
  'debug',
  'ablation',
  'validation',
  'other',
] as const;

// ── hash query helpers (#/tree2?run=<id>&node=<id>) ─────────────────────

/** `run` / `node` query params of the current hash; '' when absent. */
function selectionFromHash(): { runId: string; nodeId: string } {
  const query = window.location.hash.split('?')[1] ?? '';
  const params = new URLSearchParams(query);
  return {
    runId: params.get('run') ?? '',
    nodeId: params.get('node') ?? '',
  };
}

/** Write the selection back to the hash: the URL is the only carrier of the
 *  selection, so copying the address bar shares the exact node in view and
 *  both the canvas and the table re-render from that one URL. */
function writeSelectionToHash(runId: string, nodeId: string | null): void {
  const params = new URLSearchParams();
  if (runId !== '') params.set('run', runId);
  if (nodeId !== null && nodeId !== '') params.set('node', nodeId);
  const qs = params.toString();
  window.location.hash = qs === '' ? '#/tree2' : `#/tree2?${qs}`;
}

// ── historical test surface re-exports ──────────────────────────────────
//
// The typed coercion (`toTreeNodes` + guards) and the RQGM sentinel
// extraction (`sentinelsOf`) live in ./treeNodes so the Ideas v2 workspace
// and the inspector can reuse them without importing the D3 chunk; they
// are re-exported here to keep this page's historical test surface stable.

export { toTreeNodes, sentinelsOf };
export type { ScoreSentinels } from './treeNodes';

/** err.message plus the envelope's request_id. Every /api/v1 failure carries
 *  a `req-<12 hex>` request_id minted per dispatch; surfacing it is what lets
 *  a user quote one handle that matches the server log. */
function errorText(err: ApiErrorV1, requestIdLabel: string): string {
  const rid = err.request_id ? ` (${requestIdLabel}: ${err.request_id})` : '';
  return `${err.message}${rid}`;
}

/** Fill {shown}/{total} into a dictionary string (local convention — the
 * i18n layer has no interpolation). */
function fillCounts(template: string, shown: number, total: number): string {
  return template
    .replace('{shown}', String(shown))
    .replace('{total}', String(total));
}

// ── page ────────────────────────────────────────────────────────────────

// The tree topic keeps the runTree query fresh (useRunEvents maps a tree
// event for this run to a runTree invalidation — ADR-03).
const TREE_TOPICS: readonly EventTopic[] = ['tree'];

export function TreeV2Page() {
  const t = useT();

  // Route dispatch strips the query string, so the page owns ?run= and
  // ?node= itself (ConfigBrowserPage pattern — including in-place hash
  // changes). The hash is the single source of truth for the selection.
  const [selection, setSelection] = useState(selectionFromHash);
  useEffect(() => {
    const onHashChange = () => setSelection(selectionFromHash());
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);
  const { runId, nodeId } = selection;

  const treeQ = useRunTreeV1(runId);
  const { connectionState, lastEventAt } = useRunEvents(
    runId === '' ? null : runId,
    TREE_TOPICS,
  );

  const nodes = useMemo(
    () => toTreeNodes(treeQ.data?.nodes ?? []),
    [treeQ.data],
  );
  const selectedNode = useMemo(
    () => (nodeId === '' ? null : (nodes.find((n) => n.id === nodeId) ?? null)),
    [nodes, nodeId],
  );

  // ── level-of-detail state (task-07 tail; reset per run) ───────────────
  const [expandAll, setExpandAll] = useState(false);
  const [overrides, setOverrides] = useState<ReadonlyMap<string, boolean>>(
    () => new Map(),
  );
  useEffect(() => {
    setExpandAll(false);
    setOverrides(new Map());
  }, [runId]);

  const visible = useMemo(
    () =>
      computeVisibleRows(nodes, nodeId === '' ? null : nodeId, expandAll, overrides),
    [nodes, nodeId, expandAll, overrides],
  );
  const visibleNodes = useMemo(
    () => visible.rows.map((r) => r.node),
    [visible],
  );
  const onToggle = (id: string, expand: boolean): void => {
    setOverrides((prev) => {
      const next = new Map(prev);
      next.set(id, expand);
      return next;
    });
  };

  const stale =
    runId !== '' &&
    ((treeQ.data !== undefined && treeQ.isError) || connectionState !== 'live');
  const lastUpdatedMs = Math.max(treeQ.dataUpdatedAt || 0, lastEventAt ?? 0);

  let body: ReactNode;
  if (runId === '') {
    body = (
      <Card>
        <EmptyState icon="🌳" message={t('tree2_no_run')} hint={t('tree2_no_run_hint')} />
      </Card>
    );
  } else if (treeQ.isPending) {
    body = <LoadingState />;
  } else if (treeQ.isError && treeQ.data === undefined) {
    body = (
      <ErrorState
        message={errorText(treeQ.error, t('tree2_request_id'))}
        onRetry={() => void treeQ.refetch()}
      />
    );
  } else if (nodes.length === 0) {
    body = (
      <Card>
        <EmptyState icon="🌳" message={t('tree2_empty')} />
      </Card>
    );
  } else {
    body = (
      <>
        {visible.limited && (
          <div
            data-testid="tree2-lod-banner"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              margin: '0 0 8px',
              fontSize: '.8rem',
              color: 'var(--text-muted)',
            }}
          >
            <span>{fillCounts(t('tree2_lod_banner'), visible.rows.length, visible.total)}</span>
            <Button
              variant="outline"
              size="sm"
              style={{ fontSize: '.72rem' }}
              onClick={() => {
                setExpandAll(true);
                setOverrides(new Map());
              }}
            >
              {t('tree2_lod_expand_all')}
            </Button>
          </div>
        )}
        {!visible.limited && expandAll && visible.total > LOD_NODE_THRESHOLD && (
          <div
            data-testid="tree2-lod-banner-all"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              margin: '0 0 8px',
              fontSize: '.8rem',
              color: 'var(--text-muted)',
            }}
          >
            <span>{fillCounts(t('tree2_lod_showing_all'), visible.total, visible.total)}</span>
            <Button
              variant="outline"
              size="sm"
              style={{ fontSize: '.72rem' }}
              onClick={() => {
                setExpandAll(false);
                setOverrides(new Map());
              }}
            >
              {t('tree2_lod_restore')}
            </Button>
          </div>
        )}
        <div
          className="tree2-workspace"
          style={{ flex: 1, display: 'flex', minHeight: 0 }}
        >
          <TreeVisualization
            nodes={visibleNodes}
            selectedNodeId={nodeId === '' ? null : nodeId}
            onSelectNode={(id) => writeSelectionToHash(runId, id)}
          />
          <TreeTablePanel
            rows={visible.rows}
            selectedId={nodeId === '' ? null : nodeId}
            onSelect={(id) => writeSelectionToHash(runId, id)}
            onToggle={onToggle}
          />
          {selectedNode !== null ? (
            <Inspector
              runId={runId}
              node={selectedNode}
              onClose={() => writeSelectionToHash(runId, null)}
            />
          ) : (
            <p
              style={{
                color: 'var(--text-muted)',
                fontSize: '.8rem',
                alignSelf: 'flex-start',
                margin: '4px 0 0 12px',
                maxWidth: 200,
              }}
            >
              {t('tree2_select_hint')}
            </p>
          )}
        </div>
      </>
    );
  }

  return (
    <div
      id="page-tree2"
      className="page active"
      style={{ display: 'flex', flexDirection: 'column', height: '100%' }}
    >
      <h1 style={{ margin: 0 }}>{t('tree_title')}</h1>
      <p className="subtitle" style={{ margin: '4px 0 8px' }}>
        {t('tree2_subtitle')}
      </p>

      {runId !== '' && (
        <p style={{ color: 'var(--text-muted)', fontSize: '.85rem', margin: '0 0 8px' }}>
          {t('tree2_run_label')}: <code style={{ fontSize: '.85rem' }}>{runId}</code>
        </p>
      )}

      {stale && (
        <div style={{ marginBottom: 12 }}>
          <StaleDataBanner
            lastUpdated={
              lastUpdatedMs > 0 ? new Date(lastUpdatedMs).toLocaleString() : null
            }
            onRefresh={() => void treeQ.refetch()}
          />
        </div>
      )}

      {body}
    </div>
  );
}
