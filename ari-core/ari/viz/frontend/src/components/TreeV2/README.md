# TreeV2 — v2 Tree workspace (gui_refresh Wave 4c)

Run-explicit tree exploration route (`#/tree2?run=<id>&node=<id>`, route id
`tree_v2`) over the typed v1 tree endpoint (`useRunTreeV1`). Reuses the
legacy D3 `TreeVisualization` component from `../Tree/` — the D3 code is
imported, never forked — and adds:

- shareable URL selection: `?node=` is read from and written back to the
  hash query (plan 07 §Tree workspace);
- a right-hand inspector: node summary using the frozen orchestrator
  status/label vocabularies, `_scientific_score` plus the RQGM sentinels
  (`_pre_penalty_score`, `_validated_attack_penalty`, `_utility_policy_hash`
  chip, `_stale`), the legacy node report endpoint, and deep links to the
  Governance and Config workspaces;
- realtime: topic `tree` via `useRunEvents` with a `StaleDataBanner` on
  disconnect (a dropped stream is a freshness notice, never "run stopped");
- large-tree level-of-detail (task 07 tail; plan 07 §Tree workspace): above
  500 nodes the view default-collapses to structural depth <= 3 plus the
  selected node's ancestor path and its children. The filtering happens in
  `treeLod.ts` BEFORE the node array reaches the legacy D3 component
  (parent links stay intact inside the visible set, so the component needs
  no changes), and the reduction is never silent — an explicit
  "showing N of M nodes (depth-limited)" banner offers [expand all]
  (plan 02 truth rules);
- a virtualized side table (`TreeTablePanel.tsx`): the same visible rows as
  a windowed (scrollTop-sliced, ~40 DOM rows for 10k nodes, no new
  dependency), depth-indented ARIA tree — role=tree/treeitem with
  aria-level/aria-expanded/aria-selected, roving tabindex, ArrowUp/Down to
  move, ArrowLeft/Right to collapse/expand a subtree, Enter to select into
  `?node=` (the equivalent tabular hierarchy + keyboard navigation of
  plan 07). Canvas clicks and table selection share the `?node=` URL state.

While the `gui_v2` capability is on, this route takes over the `Tree`
sidebar slot (`navReplaces: 'tree'` in `src/app/routeRegistry.ts`); the
legacy `#/tree` page stays registered and unchanged in both modes (parity
invariant).
