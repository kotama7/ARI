# Requirement: Frontend Large Component Decomposition

## 1. Purpose

- Decompose large frontend page components into smaller units.
- Reduce per-component complexity.
- Separate container logic, presentational components, hooks, and utilities.
- Avoid visual redesign.

## 2. Current Problem

Several page components are very large (line counts confirmed in the current
tree):

```text
components/Results/ResultsPage.tsx        3177
components/Workflow/WorkflowPage.tsx      1720
components/Wizard/StepResources.tsx       1558
components/Settings/SettingsPage.tsx      1123
components/Tree/DetailPanel.tsx            938
components/Monitor/MonitorPage.tsx         857
```

These mix data loading, state, domain logic, and presentation, making them hard
to review, test, and change safely.

## 3. Scope

### In Scope

- Extracting subcomponents, hooks (data loading / state transitions), and pure
  utility functions out of the targeted page components.
- Preserving existing props and behavior.

### Out of Scope

- Visual redesign or styling changes.
- Backend endpoint changes.
- API consolidation (depends on `02` being done first).
- Global state/type redesign (that is `04`).

## 4. Files to Inspect First

```text
ari-core/ari/viz/frontend/src/components/Results/ResultsPage.tsx
ari-core/ari/viz/frontend/src/components/Workflow/WorkflowPage.tsx
ari-core/ari/viz/frontend/src/components/Wizard/StepResources.tsx
ari-core/ari/viz/frontend/src/components/Settings/SettingsPage.tsx
ari-core/ari/viz/frontend/src/components/Tree/DetailPanel.tsx
ari-core/ari/viz/frontend/src/components/Monitor/MonitorPage.tsx
```

Also inspect `hooks/`, `context/AppContext.tsx`, and `services/api.ts` so
extracted hooks reuse existing patterns rather than inventing new ones.

## 5. Expected Changes

- Extract small subcomponents (presentational where possible).
- Extract hooks for data loading and state transitions where appropriate.
- Preserve existing props and behavior of the page component.
- Avoid endpoint changes.
- Avoid unrelated styling changes.

## 6. Step-by-Step Execution Plan

1. Start with **one** component per PR (recommend `ResultsPage.tsx` last, since
   it is the largest and highest-risk; consider `MonitorPage.tsx` or
   `DetailPanel.tsx` first).
2. Identify cohesive blocks: a render section, a data-loading effect, a piece of
   derived state.
3. Extract pure render blocks into presentational subcomponents with explicit
   props.
4. Extract data-loading/state-transition logic into hooks under `hooks/`.
5. Keep the page component as a thin container wiring hooks to subcomponents.
6. Run section 8 checks after each extraction.

## 7. Compatibility Requirements

- Public props of the page components remain compatible with their call sites.
- Rendered output and user-visible behavior are unchanged.
- No endpoint or payload changes.

## 8. Tests and Smoke Checks

```bash
cd ari-core/ari/viz/frontend
npm run typecheck
npm run build
npm test -- --run
```

If dependencies are unavailable, document the attempted commands and failure
reason.

## 9. Completion Criteria

The requirement is complete only when:

- all scoped changes are implemented
- existing behavior is preserved
- tests or smoke checks pass
- risks are documented
- follow-up work is moved to another requirement file
- completion is recorded in `refactoring/COMPLETED.md`
- this requirement file is deleted in the same PR

## 10. Deletion Rule

This file must remain in `refactoring/requirements/` while the requirement is
incomplete.

When all completion criteria are satisfied, record the completion in
`refactoring/COMPLETED.md`, then delete this file in the same PR.

Do not delete this file for partial completion.

## 11. Risks

- Large components often hide implicit ordering between effects and state;
  extraction can reorder them. Verify behavior, not just compilation.
- `ResultsPage.tsx` (3177 lines) is high-risk; decompose it incrementally,
  possibly across multiple PRs, each recorded separately if split.

## 12. Follow-up Candidates

- If a component still exceeds a sensible size after one pass, open a follow-up
  for the remainder.
- Shared subcomponents that emerge may belong under `components/common/`.
