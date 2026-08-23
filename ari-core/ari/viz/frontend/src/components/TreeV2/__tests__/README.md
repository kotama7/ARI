# frontend/src/components/TreeV2/__tests__

Unit/component tests for the parent `TreeV2/` directory.

## Contents

- `README.md` — this file.
- `TreeV2LargeTree.test.tsx` — tests for the task-07-tail large-tree behavior (`treeLod.ts` + `TreeTablePanel.tsx`) over a synthetic 10k-node 3-ary array: LOD depth<=3 default with exact "showing N of M (depth-limited)" banner counts (40/58 of 10000), [expand all] full-set flag while the table DOM stays windowed, bounded DOM row count (< 100) while scrolled mid-list, keyboard walk (ArrowDown/ArrowRight/Enter) driving roving tabindex + subtree expand + `?node=` URL/inspector, aria tree semantics (tree/treeitem/aria-level/aria-expanded/aria-selected), canvas<->table selection parity through the shared URL, and a loose <200 ms perf smoke for `computeVisibleRows` on 10k nodes.
- `TreeV2Page.test.tsx` — tests for `TreeV2Page.tsx` (gui_refresh task 07 Wave 4c): v1-nodes -> `TreeNode` coercion into the shared D3 visualization, `?node=` URL selection roundtrip (preselect / click-writes / Close-clears), frozen orchestrator status+label vocabularies, RQGM sentinel display and honest-absence contract, legacy node-report endpoint, run-scoped Governance/Config deep links, topic-`tree` realtime with StaleDataBanner on disconnect, typed error envelope, no-run empty state, and Sidebar nav takeover (`#/tree2` with gui_v2 on, legacy `#/tree` off).
