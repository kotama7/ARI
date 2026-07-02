// ARI Dashboard – Workflow page node/modal layer (barrel).
//
// The React Flow custom-node renderers and the editor modals that used to live
// inline in this ~770-line file were extracted verbatim into two sibling files
// as part of the subtask-064 dashboard state/component-boundary split:
//
//   ./workflowNodeTypes.tsx → skillColor, nodeTypes (+ phase/condition/parallel nodes)
//   ./workflowModals.tsx     → ConditionModal, SkillDrawer, NodeEditModal, SkillModal, SkillMcpEntry
//
// This module is now a thin re-export barrel: the exported symbol names/types
// and the import path (`from './workflowNodes'`) are unchanged, so WorkflowPage
// keeps working with no edit. Rendered DOM/behavior is identical — pure code move.

export { skillColor, nodeTypes } from './workflowNodeTypes';
export { ConditionModal, SkillDrawer, NodeEditModal, SkillModal } from './workflowModals';
export type { SkillMcpEntry } from './workflowModals';
