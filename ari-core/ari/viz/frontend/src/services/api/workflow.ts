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

export async function saveWorkflow(
  path: string,
  pipeline: WorkflowStage[],
): Promise<{ ok: boolean; error?: string }> {
  return post('/api/workflow', { path, pipeline });
}

// ── workflow flow (React Flow) ────────────────

export async function fetchWorkflowFlow(): Promise<any> {
  return get('/api/workflow/flow');
}

export async function saveWorkflowFlow(data: any): Promise<{ ok: boolean; error?: string }> {
  return post('/api/workflow/flow', data);
}

export async function fetchWorkflowDefault(): Promise<any> {
  return get('/api/workflow/default');
}

export async function saveSkillPhases(
  skills: { name: string; phase: string | string[] }[],
): Promise<{ ok: boolean; error?: string }> {
  return post('/api/workflow/skills', { skills });
}

export async function saveDisabledTools(
  disabled_tools: string[],
): Promise<{ ok: boolean; error?: string }> {
  return post('/api/workflow/disabled-tools', { disabled_tools });
}
