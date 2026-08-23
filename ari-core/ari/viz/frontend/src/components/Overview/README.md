# frontend/src/components/Overview

v2 run Overview workspace — gui_refresh task 07 Wave 4b. Read-only; gated on
the `gui_v2` capability. This is the one screen built explicitly to the
disclosure ladder, and it is run-explicit: its content is a function of its
`?run=` URL alone, never of the shell's process-wide checkpoint selection.

Route `#/overview?run=<run_id>`. The P1/P2 rungs only (P3+ land later): P1 =
lifecycle badge, current research phase (frozen
idle/starting/bfts/paper/review vocabulary), last-update freshness, and a
blocker surface (governance record degraded/integrity-broken via the
read-only RQGM overview read model, RQGM runs only); P2 = node/review/best-metric
StatBoxes from the run summary DTO plus workspace deep links (Tree,
Config browser `#/config?run=`, Governance `#/governance?run=` when
`capabilities.rqgm`). Research phase and governance stage render as two
separate labelled rows and are never merged. Realtime: `useRunEvents`
topics `run`+`tree`; a dropped stream shows a `StaleDataBanner`, never
"run stopped".

The task 07 tail adds the P4 rung: `LogsPanel`, a collapsible cursor-based
explorer over the run's append-only `{ckpt}/ari.log`
(`GET /api/v1/runs/{run_id}/logs` — raw byte-offset cursor, server-side
case-insensitive `grep`, committed lines only, ≤1 MiB scanned per request, so
opening the panel never costs a whole-file read). Collapsed = zero fetches —
a rung that renders and then hides its content is not a rung; tail-follow is
event-driven off the page's existing stream subscription. See
`docs/concepts/gui_architecture.md`, "11. Disclosure levels: what a screen
shows before you ask".

## Contents

- `README.md` — this file.
- `index.ts` — barrel re-export.
- `LogsPanel.tsx` — collapsible cursor log explorer (P4): [Load more]
- `OverviewPage.tsx` — the P1/P2 Overview workspace (typed `/api/v1`
- `__tests__/` — component tests for this directory.
  - `LogsPanel.test.tsx` — tests for `LogsPanel.tsx` (lazy collapsed
  - `OverviewPage.test.tsx` — tests for `OverviewPage.tsx` (P1/P2 render,
