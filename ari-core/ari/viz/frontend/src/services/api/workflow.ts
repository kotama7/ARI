// ARI Dashboard API – skills / workflow family.

import type { WorkflowData, WorkflowStage } from '../../types';
import { get, post } from './client';

export async function fetchSkills(): Promise<any[]> {
  return get<any[]>('/api/skills');
}

export async function fetchSkillDetail(name: string): Promise<any> {
  return get(`/api/skill/${encodeURIComponent(name)}`);
}

export async function fetchWorkflow(): Promise<WorkflowData> {
  return get<WorkflowData>('/api/workflow');
}

// Workflow saves are revision-aware (gui_refresh Wave 4d, plan 07 §Workflow
// Studio): GET /api/workflow serves a weak `revision` (sha256[:12] of the
// served workflow.yaml bytes); write calls MAY echo it back as
// `base_revision`. A stale base_revision is refused server-side with HTTP
// 409 without writing — the throwing `post` regime surfaces that as
// `Error('POST <path> failed: 409')` (documented client wire contract),
// which `isWorkflowRevisionConflict` recognizes. Successful writes return
// the `revision` of the just-written bytes so callers can chain saves.
export interface WorkflowSaveResult {
  ok: boolean;
  error?: string;
  revision?: string;
}

/** True when a thrown transport error is the 409 revision-conflict refusal. */
export function isWorkflowRevisionConflict(e: unknown): boolean {
  return e instanceof Error && / failed: 409$/.test(e.message);
}

export async function saveWorkflow(
  path: string,
  pipeline: WorkflowStage[],
  baseRevision?: string,
): Promise<WorkflowSaveResult> {
  return post(
    '/api/workflow',
    baseRevision ? { path, pipeline, base_revision: baseRevision } : { path, pipeline },
  );
}

// ── workflow flow (React Flow) ────────────────

export async function fetchWorkflowFlow(): Promise<any> {
  return get('/api/workflow/flow');
}

export async function saveWorkflowFlow(data: any): Promise<WorkflowSaveResult> {
  return post('/api/workflow/flow', data);
}

export async function fetchWorkflowDefault(): Promise<any> {
  return get('/api/workflow/default');
}

export async function saveSkillPhases(
  skills: { name: string; phase: string | string[] }[],
  baseRevision?: string,
): Promise<WorkflowSaveResult> {
  return post(
    '/api/workflow/skills',
    baseRevision ? { skills, base_revision: baseRevision } : { skills },
  );
}

export async function saveDisabledTools(
  disabled_tools: string[],
  baseRevision?: string,
): Promise<WorkflowSaveResult> {
  return post(
    '/api/workflow/disabled-tools',
    baseRevision ? { disabled_tools, base_revision: baseRevision } : { disabled_tools },
  );
}
