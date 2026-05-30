# Requirement: Frontend Remaining Large-Component Decomposition (follow-up to 03)

This is a **follow-up requirement spawned by `03`** (per `03` §11/§12, which
permit decomposing incrementally across multiple PRs and moving the remainder to
a follow-up file). `03` decomposed `ResultsPage.tsx`; this file owns the rest.

## 1. Purpose

- Decompose the remaining large frontend page components into smaller units.
- Continue separating container logic, presentational components, hooks, and
  utilities. Avoid visual redesign.

## 2. Current Problem

After `03`, these components are still large (verify counts against the tree;
these are as of 2026-05-30):

```text
components/Workflow/WorkflowPage.tsx      1720
components/Wizard/StepResources.tsx       1558
components/Settings/SettingsPage.tsx      1123
components/Tree/DetailPanel.tsx            938
components/Monitor/MonitorPage.tsx         857
```

Additionally, `03` extracted the ResultsPage presentational/utility layer into
`components/Results/resultSections.tsx` (~1161 lines). That file is cohesive and
purely presentational, but is itself a candidate for a finer split into
`resultHelpers.ts` (pure helpers + the RubricNode/LeafGrade/StageState/
OrsRenderInput types), `resultPrimitives.tsx` (KvList, CollapsibleText,
FileViewer/FileViewers, ScoreBar, ChainStage), and section files
(gradingTree/generationLogs/orsChain). The clean dependency DAG for that split is
recorded in `refactoring/notes/03_resultspage_decomposition.md`.

The `ResultsPage` **container** itself remains ~1857 lines. `03`'s analysis
identified safe seams inside it (see the notes file): low-risk pure render blocks
`renderReviewScores`, `renderFigures`, `renderContext`; medium-risk
`renderRepro` + a `useCheckpointResults` data hook; high-risk `renderPaper`
(PaperWorkspace) and `renderEAR` (with a `useEAR` hook that would also dedupe the
duplicated curate-EAR block at container lines ~1524 and ~1648). These are
in-scope here.

## 3. Scope

### In Scope

- Decomposing Workflow/StepResources/Settings/DetailPanel/Monitor page
  components (one component per PR; recommend MonitorPage or DetailPanel first).
- Optional finer split of `resultSections.tsx` per the recorded DAG.
- Optional extraction of the low/medium-risk seams from the `ResultsPage`
  container (start with the three low-risk pure render blocks).

### Out of Scope

- Visual redesign, styling, or backend endpoint changes.
- Global state/type redesign (that is `04`).
- API consolidation (`02`, done).

## 4. Files to Inspect First

```text
ari-core/ari/viz/frontend/src/components/Workflow/WorkflowPage.tsx
ari-core/ari/viz/frontend/src/components/Wizard/StepResources.tsx
ari-core/ari/viz/frontend/src/components/Settings/SettingsPage.tsx
ari-core/ari/viz/frontend/src/components/Tree/DetailPanel.tsx
ari-core/ari/viz/frontend/src/components/Monitor/MonitorPage.tsx
ari-core/ari/viz/frontend/src/components/Results/resultSections.tsx
refactoring/notes/03_resultspage_decomposition.md
```

Also inspect `hooks/`, `context/AppContext.tsx`, and `services/api.ts` so
extracted hooks reuse existing patterns.

## 5. Expected Changes / 6. Execution / 7. Compatibility

Same as `03`: extract presentational subcomponents and data hooks; keep page
components as thin containers; preserve props, rendered output, and behavior; no
endpoint changes; move code verbatim where possible. Verify behavior, not just
compilation (large components hide implicit effect/state ordering).

## 8. Tests and Smoke Checks

```bash
cd ari-core/ari/viz/frontend
npm run typecheck   # must add no NEW errors vs the pre-existing __tests__ baseline
npm run build
npm test -- --run   # must add no NEW failures (2 pre-existing brittle PaperBench tests)
```

## 9. Completion Criteria

Standard (see `GLOBAL_RULES.md`): all scoped changes implemented, behavior
preserved, checks pass, risks documented, follow-up moved to another requirement
file, completion recorded in `COMPLETED.md`, this file deleted in the same PR.
May be split across multiple PRs (one component each), each recorded separately;
delete this file only when all listed components are done or their remainder is
moved to a further follow-up.

## 10. Deletion Rule

Keep while incomplete; delete in the same PR that records completion (no partial
deletion).

## 11. Risks

- Same as `03`: effect/state ordering inside large containers; verify behavior.
- `StepResources.tsx` and `SettingsPage.tsx` contain heavy form state; extract
  presentational field groups before touching state wiring.

## 12. Follow-up Candidates

- Shared subcomponents that emerge may belong under `components/common/`.
- Coordinate the `ResultsPage` container hooks (`useCheckpointResults`, `useEAR`)
  with `04` (state/hooks/types cleanup) to avoid duplicated effort.
