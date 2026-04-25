// ARI Dashboard – typed API service
// All fetch calls target the same origin (API_BASE = '').

import type {
  AppState,
  Checkpoint,
  CheckpointSummary,
  ResourceMetrics,
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

export async function fetchExperimentDetail(): Promise<string> {
  const d = await get<{ experiment_detail_config?: string }>('/api/experiment-detail');
  return d.experiment_detail_config ?? '';
}

export async function fetchCheckpoints(): Promise<Checkpoint[]> {
  return get<Checkpoint[]>('/api/checkpoints');
}

export async function fetchCheckpointSummary(id: string): Promise<CheckpointSummary> {
  return get<CheckpointSummary>(`/api/checkpoint/${encodeURIComponent(id)}/summary`);
}

export interface MemoryEntry {
  node_id: string;
  text: string;
  metadata: Record<string, unknown>;
  tags?: string[];
  ts?: number;
  source: 'mcp' | 'file_client' | 'global';
}

export interface MemoryResponse {
  id: string;
  entries: MemoryEntry[];
  by_node: Record<string, MemoryEntry[]>;
  global?: MemoryEntry[];
  global_path?: string;
  count: number;
  error?: string;
}

export async function fetchCheckpointMemory(id: string): Promise<MemoryResponse> {
  return get<MemoryResponse>(`/api/checkpoint/${encodeURIComponent(id)}/memory`);
}

export interface MemoryAccessEvent {
  ts: number;
  node_id: string;
  op: 'read' | 'write';
  query?: string;
  text_preview?: string;
  results?: Array<{ entry_id?: string; score?: number; [k: string]: unknown }>;
  [k: string]: unknown;
}

export interface MemoryAccessResponse {
  node_id: string;
  writes: MemoryAccessEvent[];
  reads: MemoryAccessEvent[];
  read_by_entry: Record<string, { count: number; last_ts: number }>;
  error?: string;
}

export async function fetchMemoryAccess(
  id: string,
  nodeId: string,
  op: 'read' | 'write' | 'all' = 'all',
  limit = 200,
): Promise<MemoryAccessResponse> {
  const q = new URLSearchParams({ node_id: nodeId, op, limit: String(limit) });
  return get<MemoryAccessResponse>(
    `/api/checkpoint/${encodeURIComponent(id)}/memory_access?${q.toString()}`,
  );
}

// ── EAR (Experiment Artifact Repository) ─────────
export interface EARFile {
  path: string;
  type: 'file' | 'dir';
  size?: number;
}

export interface EARData {
  run_id?: string;
  ear_dir?: string;
  files?: EARFile[];
  readme?: string;
  results?: string;
  file_count?: number;
  error?: string;
}

export async function fetchEAR(runId: string): Promise<EARData> {
  return get<EARData>(`/api/ear/${encodeURIComponent(runId)}`);
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

// ── memory (Letta) lifecycle ───────────────────

export interface MemoryHealth {
  status: string;
  latency_ms: number;
  namespace: string | null;
  server_version: string;
  detected_deployment: string;
  reason?: string;
  error?: string;
}

export async function fetchMemoryHealth(): Promise<MemoryHealth> {
  return get<MemoryHealth>('/api/memory/health');
}

export async function restartLetta(
  path: string = 'auto',
): Promise<{
  ok: boolean;
  start?: { ok: boolean; path?: string; stdout?: string; error?: string };
  stop?: { ok: boolean; attempts?: string[] };
  error?: string;
}> {
  return post('/api/memory/restart', { path });
}

export async function fetchProfiles(): Promise<string[]> {
  return get<string[]>('/api/profiles');
}

export interface RubricSummary {
  id: string;
  venue: string;
  domain: string;
  version: string;
  closed_review?: boolean;
  path: string;
}

export async function fetchRubrics(): Promise<RubricSummary[]> {
  return get<RubricSummary[]>('/api/rubrics');
}

export interface FewshotExample {
  id: string;
  files: Array<{ ext: string; size: number }>;
  source: string;
  decision: string;
  overall: number | null;
}

export interface FewshotListing {
  rubric_id: string;
  count: number;
  examples: FewshotExample[];
  error?: string;
}

export async function fetchFewshot(rubricId: string): Promise<FewshotListing> {
  return get<FewshotListing>(`/api/fewshot/${encodeURIComponent(rubricId)}`);
}

export async function syncFewshot(rubricId: string): Promise<any> {
  return post(`/api/fewshot/${encodeURIComponent(rubricId)}/sync`, {});
}

export async function uploadFewshot(
  rubricId: string,
  payload: {
    example_id: string;
    review_json: string;
    paper_txt?: string;
    paper_pdf?: string;
  },
): Promise<any> {
  return post(`/api/fewshot/${encodeURIComponent(rubricId)}/upload`, payload);
}

export async function deleteFewshot(
  rubricId: string,
  exampleId: string,
): Promise<any> {
  return post(
    `/api/fewshot/${encodeURIComponent(rubricId)}/${encodeURIComponent(
      exampleId,
    )}/delete`,
    {},
  );
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

export async function deleteUploadedFile(
  filename: string,
): Promise<{ ok: boolean; error?: string }> {
  return post('/api/upload/delete', { filename });
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

// ── resource metrics ──────────────────────────

export async function fetchResourceMetrics(): Promise<ResourceMetrics> {
  return get<ResourceMetrics>('/api/resource-metrics');
}

// ── container ─────────────────────────────────

export async function fetchContainerInfo(): Promise<{
  runtime: string;
  version: string;
  available: boolean;
}> {
  return get('/api/container/info');
}

export interface ContainerImage {
  name: string;
  size: string;
}

export async function fetchContainerImages(): Promise<{ images: ContainerImage[] }> {
  return get('/api/container/images');
}

export async function pullContainerImage(
  image: string,
  mode?: string,
): Promise<{ ok: boolean; error?: string }> {
  return post('/api/container/pull', { image, mode: mode || 'auto' });
}

// ── checkpoint file management (Overleaf-like) ──

export interface CheckpointFile {
  name: string;
  size: number;
  editable: boolean;
  ext: string;
  abs_path: string;
}

export async function fetchCheckpointFiles(
  id: string,
): Promise<{ id: string; path: string; files: CheckpointFile[]; error?: string }> {
  return get(`/api/checkpoint/${encodeURIComponent(id)}/files`);
}

export async function fetchCheckpointFileContent(
  id: string,
  filename: string,
): Promise<{ name: string; content: string; error?: string }> {
  return get(`/api/checkpoint/${encodeURIComponent(id)}/file?name=${encodeURIComponent(filename)}`);
}

export async function saveCheckpointFile(
  checkpointId: string,
  filename: string,
  content: string,
): Promise<{ ok: boolean; error?: string }> {
  return post('/api/checkpoint/file/save', {
    checkpoint_id: checkpointId,
    filename,
    content,
  });
}

export async function uploadCheckpointFile(
  checkpointId: string,
  file: File,
): Promise<{ ok: boolean; name?: string; error?: string }> {
  const res = await fetch(`/api/checkpoint/${encodeURIComponent(checkpointId)}/file/upload`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/octet-stream',
      'X-Filename': file.name,
    },
    body: file,
  });
  if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
  return res.json();
}

export async function deleteCheckpointFile(
  checkpointId: string,
  filename: string,
): Promise<{ ok: boolean; error?: string }> {
  return post('/api/checkpoint/file/delete', {
    checkpoint_id: checkpointId,
    filename,
  });
}

export async function compileCheckpointPaper(
  checkpointId: string,
  mainFile?: string,
): Promise<{ ok: boolean; log: string }> {
  return post('/api/checkpoint/compile', {
    checkpoint_id: checkpointId,
    main_file: mainFile || 'full_paper.tex',
  });
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

// ── models ─────────────────────────────────────

export async function fetchModels(): Promise<any> {
  return get('/api/models');
}

// ── sub-experiments (recursive orchestration) ──

export interface SubExperiment {
  run_id: string;
  parent_run_id?: string | null;
  recursion_depth: number;
  max_recursion_depth: number;
  created_at?: string;
  checkpoint_dir?: string;
}

export async function fetchSubExperiments(): Promise<{ sub_experiments: SubExperiment[] }> {
  return get('/api/sub-experiments');
}

export async function fetchSubExperiment(runId: string): Promise<SubExperiment> {
  return get(`/api/sub-experiments/${encodeURIComponent(runId)}`);
}

export async function launchSubExperiment(data: {
  experiment_md: string;
  max_recursion_depth?: number;
  parent_run_id?: string;
  recursion_depth?: number;
}): Promise<{ ok: boolean; run_id?: string; pid?: number; error?: string }> {
  return post('/api/sub-experiments/launch', data);
}
