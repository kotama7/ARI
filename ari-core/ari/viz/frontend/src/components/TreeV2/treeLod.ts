// ARI Dashboard – TreeV2 level-of-detail visible-set computation
// (gui_refresh task 07 tail; plan 07 §Tree workspace: large trees use
// level-of-detail, viewport culling, and a virtualized side table).
//
// Pure functions only — the page owns the expand state and calls
// computeVisibleRows() to derive ONE visible set shared by BOTH views:
// the D3 canvas (which receives the filtered node array — the legacy
// TreeVisualization component is reused unchanged; depth-filtering happens
// BEFORE the nodes are passed in, with parent links preserved because the
// DFS emits a node only when every ancestor is expanded) and the
// virtualized side table (which renders the same list as flat rows).
//
// LOD rule (task 07 tail): when the tree holds more than
// LOD_NODE_THRESHOLD drawable nodes, default-collapse everything deeper
// than LOD_DEPTH_LIMIT — i.e. render structural depth <= 3 — PLUS the
// selected node's ancestor path and the selected node's children, so a
// deep URL selection is always visible with its context. The reduction is
// never silent (plan 02 truth rules): the page shows an explicit
// "showing N of M nodes (depth-limited)" banner with an [expand all]
// opt-in whenever rows.length < total.
//
// Per-node overrides (table ArrowLeft/ArrowRight, chevron clicks) beat
// the LOD default in both directions; "expand all" clears them.

import type { TreeNode } from '../../types';

/** Above this many drawable nodes the depth-limited default kicks in. */
export const LOD_NODE_THRESHOLD = 500;

/** Structural depth rendered by default under LOD (root = depth 0). */
export const LOD_DEPTH_LIMIT = 3;

/** One row of the flattened visible tree (DFS pre-order). */
export interface VisibleRow {
  node: TreeNode;
  /** Structural depth from its root (root = 0) — NOT the node.depth field,
   * which is orchestrator-reported and may disagree with the link graph. */
  level: number;
  hasChildren: boolean;
  /** Whether this row's children are currently emitted below it. */
  expanded: boolean;
}

export interface VisibleTree {
  /** DFS pre-order rows; parents always precede (and include) children. */
  rows: VisibleRow[];
  /** Drawable nodes in the full array (the M of "showing N of M"). */
  total: number;
  /** True when rows.length < total — the banner MUST be shown. */
  limited: boolean;
}

/**
 * Compute the visible rows of `nodes` under the LOD default + overrides.
 *
 * - `selectedId` — current `?node=` selection ('' / null for none); its
 *   ancestor path and its own children are always kept visible.
 * - `expandAll` — the banner opt-in: every node expanded unless an
 *   explicit override collapses it.
 * - `overrides` — per-node user toggles (true = expand, false = collapse);
 *   they beat the LOD default in both directions.
 *
 * O(n): one children-map pass plus one iterative DFS (no recursion, so a
 * 10k-deep chain cannot overflow the stack). Nodes unreachable from a
 * root (defensive: cyclic parent links) are simply not emitted.
 */
export function computeVisibleRows(
  nodes: TreeNode[],
  selectedId: string | null,
  expandAll: boolean,
  overrides: ReadonlyMap<string, boolean>,
  threshold: number = LOD_NODE_THRESHOLD,
): VisibleTree {
  const total = nodes.length;
  const byId = new Map<string, TreeNode>();
  for (const n of nodes) byId.set(n.id, n);

  // Children in input order; roots = no parent, or parent not in the set
  // (same rule the legacy TreeVisualization uses to pick its root).
  const children = new Map<string, TreeNode[]>();
  const roots: TreeNode[] = [];
  for (const n of nodes) {
    if (n.parent_id && byId.has(n.parent_id) && n.parent_id !== n.id) {
      const list = children.get(n.parent_id);
      if (list) list.push(n);
      else children.set(n.parent_id, [n]);
    } else {
      roots.push(n);
    }
  }

  // Ancestor path of the selection (cycle-guarded walk to the root).
  const selectionAncestors = new Set<string>();
  if (selectedId) {
    let cur = byId.get(selectedId);
    const seen = new Set<string>([selectedId]);
    while (cur && cur.parent_id && byId.has(cur.parent_id)) {
      if (seen.has(cur.parent_id)) break;
      seen.add(cur.parent_id);
      selectionAncestors.add(cur.parent_id);
      cur = byId.get(cur.parent_id);
    }
  }

  const lodActive = total > threshold && !expandAll;
  const isExpanded = (id: string, level: number): boolean => {
    const override = overrides.get(id);
    if (override !== undefined) return override;
    if (!lodActive) return true;
    return (
      level < LOD_DEPTH_LIMIT || id === selectedId || selectionAncestors.has(id)
    );
  };

  // Iterative pre-order DFS over the expanded frontier.
  const rows: VisibleRow[] = [];
  const stack: Array<{ node: TreeNode; level: number }> = [];
  const visited = new Set<string>();
  for (let i = roots.length - 1; i >= 0; i--) {
    stack.push({ node: roots[i], level: 0 });
  }
  while (stack.length > 0) {
    const { node, level } = stack.pop() as { node: TreeNode; level: number };
    if (visited.has(node.id)) continue;
    visited.add(node.id);
    const kids = children.get(node.id);
    const hasChildren = kids !== undefined && kids.length > 0;
    const expanded = hasChildren && isExpanded(node.id, level);
    rows.push({ node, level, hasChildren, expanded });
    if (expanded && kids) {
      for (let i = kids.length - 1; i >= 0; i--) {
        stack.push({ node: kids[i], level: level + 1 });
      }
    }
  }

  return { rows, total, limited: rows.length < total };
}
