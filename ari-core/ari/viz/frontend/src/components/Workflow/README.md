# frontend/src/components/Workflow

Workflow page — displays the run's workflow stages/pipeline.

## Contents

- `README.md` — this file.
- `index.ts` — barrel re-export.
- `workflowModals.tsx` — TODO
- `workflowNodes.tsx` — React Flow custom nodes + edit/skill/condition modals (extracted from WorkflowPage in req 15).
- `workflowNodeTypes.tsx` — TODO
- `WorkflowPage.tsx` — workflow view.
- `__tests__/` — component tests for this directory.
  - `WorkflowPage.revision.test.tsx` — revision-aware saving: every save sends the loaded `base_revision` and adopts the returned `revision`, the 2s debounce is unchanged, and a 409 pauses saving behind an explicit Reload instead of blindly overwriting.
