# frontend/src/components/Workflow

Workflow page — displays the run's workflow stages/pipeline.

## Contents

- `README.md` — this file.
- `index.ts` — barrel re-export.
- `workflowModals.tsx` — edge-`ConditionModal`, skill-selector `SkillDrawer`, `NodeEditModal`, skill-detail `SkillModal` + the shared `inputStyle`/`SkillMcpEntry`; split verbatim out of `workflowNodes.tsx` in subtask-064 and re-exported from it.
- `workflowNodes.tsx` — React Flow custom nodes + edit/skill/condition modals (extracted from WorkflowPage in req 15).
- `workflowNodeTypes.tsx` — React Flow custom node renderers and the `phase`/`condition`/`parallel` `nodeTypes` map + deterministic `skillColor` hash; split verbatim out of `workflowNodes.tsx` in subtask-064 and re-exported from it.
- `WorkflowPage.tsx` — workflow view.
- `__tests__/` — component tests for this directory.
  - `WorkflowPage.revision.test.tsx` — revision-aware saving: every save sends the loaded `base_revision` and adopts the returned `revision`, the 2s debounce is unchanged, and a 409 pauses saving behind an explicit Reload instead of blindly overwriting.
