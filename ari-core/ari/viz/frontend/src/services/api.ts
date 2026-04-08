// ARI Dashboard – typed API service
// All fetch calls target the same origin (API_BASE = '').

import type {
  AppState,
  Checkpoint,
  CheckpointSummary,
  Settings,
  WorkflowData,
  WorkflowStage,
} from '../types';

const API_BASE = '';

// ── helpers ────────────────────────────────────

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return res.json();
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok) throw new Error(`POST ${path} failed: ${res.status}`);
  return res.json();
}

// ── state / checkpoints ────────────────────────

export async function fetchState(): Promise<AppState> {
  return get<AppState>('/state');
}

export async function fetchCheckpoints(): Promise<Checkpoint[]> {
  return get<Checkpoint[]>('/api/checkpoints');
}

export async function fetchCheckpointSummary(id: string): Promise<CheckpointSummary> {
  return get<CheckpointSummary>(`/api/checkpoint/${encodeURIComponent(id)}/summary`);
}

export async function deleteCheckpoint(
  id: string,
  path: string,
): Promise<{ ok: boolean; error?: string }> {
  return post('/api/delete-checkpoint', { id, path });
}

export async function switchCheckpoint(
  path: string,
): Promise<{ ok: boolean; error?: string }> {
  return post('/api/switch-checkpoint', { path });
}

export async function fetchActiveCheckpoint(): Promise<{ id?: string; path?: string }> {
  return get('/api/active-checkpoint');
}

// ── settings ───────────────────────────────────

export async function fetchSettings(): Promise<Settings> {
  return get<Settings>('/api/settings');
}

export async function saveSettings(
  data: Partial<Settings>,
): Promise<{ ok: boolean; error?: string }> {
  return post('/api/settings', data);
}

export async function fetchEnvKeys(): Promise<{ keys: Record<string, string> }> {
  return get('/api/env-keys');
}

export async function fetchProfiles(): Promise<string[]> {
  return get<string[]>('/api/profiles');
}

// ── skills / workflow ──────────────────────────

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

// ── experiment lifecycle ───────────────────────

export async function runStage(
  stage: string,
): Promise<{ ok: boolean; pid?: number; error?: string }> {
  return post('/api/run-stage', { stage });
}

export async function stopExperiment(): Promise<any> {
  return post('/api/stop');
}

export async function launchExperiment(
  data: any,
): Promise<{ ok: boolean; pid?: number; error?: string; checkpoint_path?: string }> {
  return post('/api/launch', data);
}

// ── wizard / chat ──────────────────────────────

export async function chatGoal(
  messages: any[],
): Promise<{ reply?: string; ready?: boolean; md?: string; error?: string }> {
  return post('/api/chat-goal', { messages });
}

export async function generateConfig(goal: string): Promise<any> {
  return post('/api/config/generate', { goal });
}

// ── file upload ────────────────────────────────

export async function uploadFile(
  file: File,
  fileType: string,
): Promise<{ ok: boolean; path?: string; filename?: string; error?: string }> {
  const res = await fetch(`${API_BASE}/api/upload`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/octet-stream',
      'X-Filename': file.name,
      'X-File-Type': fileType,
    },
    body: file,
  });
  if (!res.ok) throw new Error(`POST /api/upload failed: ${res.status}`);
  return res.json();
}

// ── SSH / HPC ──────────────────────────────────

export async function testSSH(
  data: any,
): Promise<{ ok: boolean; info?: string; error?: string }> {
  return post('/api/ssh/test', data);
}

export async function detectScheduler(): Promise<{ scheduler: string; partitions: any[] }> {
  return get('/api/scheduler/detect');
}

export async function fetchPartitions(): Promise<any[]> {
  return get<any[]>('/api/slurm/partitions');
}

// ── Ollama / GPU ───────────────────────────────

export async function fetchOllamaResources(): Promise<{ gpus: any[]; models: string[] }> {
  return get('/api/ollama-resources');
}

export async function fetchGpuMonitor(): Promise<{
  running: boolean;
  pid?: number;
  log?: string;
  ollama_host?: string;
}> {
  return get('/api/gpu-monitor');
}

export async function gpuMonitorAction(action: string): Promise<any> {
  return post('/api/gpu-monitor', { action, confirmed: true });
}

// ── models ─────────────────────────────────────

export async function fetchModels(): Promise<any> {
  return get('/api/models');
}
