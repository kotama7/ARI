# frontend/src/components/Overview

v2 run Overview workspace — gui_refresh task 07 Wave 4b (plan 07 §Run Overview
and Live Monitor; plan 01 §Global shell context). Read-only; gated on the
`gui_v2` capability.

Route `#/overview?run=<run_id>`. The plan-07 P1/P2 disclosure layers only
(P3+ land later): P1 = lifecycle badge, current research phase (frozen
idle/starting/bfts/paper/review vocabulary), last-update freshness, and a
blocker surface (governance record degraded/integrity-broken via the plan-08
RQGM overview read model, RQGM runs only); P2 = node/review/best-metric
StatBoxes from the run summary DTO plus workspace deep links (Tree,
Config browser `#/config?run=`, Governance `#/governance?run=` when
`capabilities.rqgm`). Research phase and governance stage render as two
separate labelled rows and are never merged. Realtime: `useRunEvents`
topics `run`+`tree`; a dropped stream shows a `StaleDataBanner`, never
"run stopped".

The task 07 tail adds the P4 disclosure layer: `LogsPanel`, a collapsible
cursor-based explorer over the run's append-only `{ckpt}/ari.log`
(`GET /api/v1/runs/{run_id}/logs` — raw byte-offset cursor, server-side
case-insensitive `grep`, committed lines only, ≤1 MiB scanned per request;
plan 07 §Artifacts, logs, and diagnostics). Collapsed = zero fetches;
tail-follow is event-driven off the page's existing stream subscription.

## Contents

- `README.md` — this file.
- `index.ts` — barrel re-export.
- `OverviewPage.tsx` — the P1/P2 Overview workspace (typed `/api/v1`
  react-query hooks + common components only) + the embedded P4 `LogsPanel`.
- `LogsPanel.tsx` — collapsible cursor log explorer (P4): [Load more]
  append with offset-keyed no-duplicate merge, grep filter restart,
  event-driven tail-follow, in-panel `StaleDataBanner` while following
  with the stream down, honest `present=false` absence note.
- `__tests__/` — component tests for this directory.
  - `OverviewPage.test.tsx` — tests for `OverviewPage.tsx` (P1/P2 render,
    RQGM vs simple_bfts variants, stale banner, phase/governance row
    separation, blocker surface).
  - `LogsPanel.test.tsx` — tests for `LogsPanel.tsx` (lazy collapsed
    no-fetch, cursor append no-dup, follow-on-event fetch, grep restart
    from cursor 0, absence note, follow-only stale banner).
