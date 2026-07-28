# IdeasV2 — v2 Ideas workspace (gui_refresh Wave 4c)

Run-explicit, read-only idea/hypothesis route (`#/ideas2?run=<id>`, route id
`ideas_v2`) over the typed v1 endpoints:

- `GET /api/v1/runs/{run_id}/idea` (`useRunIdeaV1`) — pure `idea.json` read
  with honest absence semantics: `present=false` without degraded reasons
  renders the "run has not generated ideas yet" `EmptyState`; a malformed
  file (`degraded_reasons`) renders `DegradedState` instead (absence and
  corruption are never conflated).
- `GET /api/v1/runs/{run_id}/tree` (`useRunTreeV1`) — via the shared
  `../TreeV2/treeNodes` coercion — feeds the BFTS hypothesis list, the best
  hypothesis, and the idea-strategy (label) distribution.

Information parity with the legacy `#/idea` page (which stays untouched and
reachable in both modes): research goal (AppContext `/state`, shown only when
`state.checkpoint_id` equals `?run=` — run-identity gate), gap analysis,
primary metric + rationale, VirSci hypotheses, BFTS hypotheses, strategy
distribution. Deep links open the TreeV2 workspace at
`#/tree2?run=<id>&node=<id>` for the best hypothesis and every listed node.

While the `gui_v2` capability is on, this route takes over the `Idea`
sidebar slot (`navReplaces: 'idea'` in `src/app/routeRegistry.ts` — the same
mechanism the Tree stage introduced).

## Contents

- `README.md` — this file.
- `IdeasV2Page.tsx` — the page component plus exported pure helpers
  (`toIdeaEntries`, `bestHypothesisNode`).
- `index.ts` — barrel re-export.
- `__tests__/` — component tests for this directory.
  - `IdeasV2Page.test.tsx` — page contract tests (happy/absent/degraded/
    error/no-run, deep links, nav takeover).
