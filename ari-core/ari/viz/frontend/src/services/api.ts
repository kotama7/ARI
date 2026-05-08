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

// ── Node report (v0.7.0) ───────────────────────────────────
export interface NodeReportFilesChanged {
  added: Array<{ path: string; sha256?: string }>;
  modified: Array<{
    path: string;
    sha256_before?: string;
    sha256_after?: string;
  }>;
  deleted: string[];
  inherited_unchanged: Array<{ path: string; from_node_id?: string }>;
}

export interface NodeReportSelfAssessment {
  succeeded?: boolean;
  headline?: string;
  concerns?: string[];
}

export interface NodeReport {
  schema_version: number;
  node_id: string;
  parent_id?: string | null;
  ancestor_ids?: string[];
  label?: string;
  raw_label?: string;
  depth?: number;
  status?: string;
  started_at?: string;
  completed_at?: string;
  original_direction?: string | null;
  files_changed: NodeReportFilesChanged;
  what_was_done?: string;
  delta_vs_parent?: string;
  metrics?: Record<string, unknown>;
  self_assessment?: NodeReportSelfAssessment;
  next_steps_hints?: string[];
  build_command?: string;
  run_command?: string;
  artifacts?: Array<{
    filename: string;
    role: string;
    size?: number;
    sha256?: string;
  }>;
  evaluator_reason?: string;
  trace_log_summary?: string;
  migration_source?: 'fresh' | 'auto';
}

export interface NodeReportResponse {
  run_id?: string;
  node_id?: string;
  report?: NodeReport;
  error?: string;
}

export async function fetchNodeReport(
  runId: string,
  nodeId: string,
): Promise<NodeReportResponse> {
  return get<NodeReportResponse>(
    `/api/nodes/${encodeURIComponent(runId)}/${encodeURIComponent(nodeId)}/report`,
  );
}

// ── EAR (Experiment Artifact Repository) ─────────
export interface EARFile {
  path: string;
  type: 'file' | 'dir';
  size?: number;
}

export interface EARPublishedSummary {
  ear_published_dir?: string;
  bundle_sha256?: string;
  file_count?: number;
  visibility?: string;
  excluded_count?: number;
  files?: string[];
  created_at?: string;
  error?: string;
}

export interface EARData {
  run_id?: string;
  ear_dir?: string;
  files?: EARFile[];
  readme?: string;
  results?: string;
  file_count?: number;
  publish_yaml_present?: boolean;
  published?: EARPublishedSummary | null;
  error?: string;
}

export async function fetchEAR(runId: string): Promise<EARData> {
  return get<EARData>(`/api/ear/${encodeURIComponent(runId)}`);
}

// ── Curate ───────────────
export interface EARCurateResult {
  ear_published_dir?: string;
  manifest_path?: string;
  bundle_sha256?: string;
  included_files?: string[];
  excluded_count?: number;
  skipped?: boolean;
  error?: string;
  kind?: string;
}

export async function curateEAR(runId: string): Promise<EARCurateResult> {
  return post<EARCurateResult>(`/api/ear/${encodeURIComponent(runId)}/curate`, {});
}

// ── publish.yaml editor ──────────
export interface PublishYamlData {
  include?: string[];
  exclude?: string[];
  max_file_mb?: number;
  license?: string;
  visibility?: string;
  required?: boolean;
  auto_promote?: boolean;
  _parse_error?: string;
  [k: string]: any;
}

export interface PublishYamlResponse {
  exists?: boolean;
  path?: string;
  text?: string;
  data?: PublishYamlData;
  error?: string;
  ok?: boolean;
}

export async function fetchPublishYaml(runId: string): Promise<PublishYamlResponse> {
  return get<PublishYamlResponse>(`/api/ear/${encodeURIComponent(runId)}/publish-yaml`);
}

export async function savePublishYaml(
  runId: string,
  payload: { text?: string; data?: PublishYamlData },
): Promise<PublishYamlResponse> {
  return post<PublishYamlResponse>(
    `/api/ear/${encodeURIComponent(runId)}/publish-yaml`,
    payload,
  );
}

// ── Clone-verify ───────────────
export interface CloneVerifyRequest {
  ref: string;
  dest: string;
  expect_sha256?: string;
  extract?: boolean;
}
export interface CloneVerifyResult {
  ref?: string;
  dest?: string;
  bundle_sha256?: string;
  file_count?: number;
  extracted?: boolean;
  error?: string;
  kind?: string;
}
export async function cloneVerifyBundle(req: CloneVerifyRequest): Promise<CloneVerifyResult> {
  return post<CloneVerifyResult>('/api/ear/clone-verify', req);
}

// ── Publish ───────────────
export interface PublishSettings {
  default_backend?: string;
  auto_promote?: boolean;
  registries?: Array<{ name: string; url: string; token?: string }>;
  zenodo_sandbox?: boolean;
  gh_user?: string;
  error?: string;
}

export interface PublishPreview {
  run_id?: string;
  ear_published_dir?: string;
  bundle_sha256?: string;
  files?: string[];
  file_count?: number;
  visibility?: string;
  license?: string;
  publish?: Record<string, unknown>;
  error?: string;
  needs_curate?: boolean;
}

export interface PublishRunRequest {
  backend?: string;
  visibility?: string;
  dry_run?: boolean;
  consent?: boolean;
  metadata?: Record<string, unknown>;
}

export interface PublishRunResult {
  backend?: string;
  ref?: string;
  bundle_sha256?: string;
  visibility?: string;
  dry_run?: boolean;
  extra?: Record<string, unknown>;
  timestamp?: string;
  error?: string;
  kind?: string;
}

export interface PublishRecord {
  published?: boolean;
  backend?: string;
  ref?: string;
  bundle_sha256?: string;
  visibility?: string;
  dry_run?: boolean;
  timestamp?: string;
  promoted_at?: string;
  promote_failed_at?: string;
  extra?: Record<string, unknown>;
  error?: string;
}

export async function fetchPublishSettings(): Promise<PublishSettings> {
  return get<PublishSettings>('/api/publish/settings');
}
export async function savePublishSettings(s: PublishSettings): Promise<{ ok?: boolean; error?: string }> {
  return post('/api/publish/settings', s);
}
export async function previewPublish(runId: string): Promise<PublishPreview> {
  return get<PublishPreview>(`/api/publish/${encodeURIComponent(runId)}/preview`);
}
export async function runPublish(runId: string, req: PublishRunRequest): Promise<PublishRunResult> {
  return post<PublishRunResult>(`/api/publish/${encodeURIComponent(runId)}`, req);
}
export async function promotePublish(runId: string, target: string): Promise<{ ref?: string; visibility?: string; error?: string }> {
  return post(`/api/publish/${encodeURIComponent(runId)}/promote`, { target });
}
export async function fetchPublishRecord(runId: string): Promise<PublishRecord> {
  return get<PublishRecord>(`/api/publish/${encodeURIComponent(runId)}/record`);
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

export async function fetchCheckpointFilecontent(
  id: string,
  path: string,
): Promise<{ name?: string; content?: string; error?: string }> {
  return get(`/api/checkpoint/${encodeURIComponent(id)}/filecontent?path=${encodeURIComponent(path)}`);
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
  // v0.7.0: surfaced when this sub-experiment was launched by lineage decision
  // switch_to_idea / fanout / opt-in inherit_idea_index. Lets the GUI
  // render lineage provenance on the Experiments page.
  inherit_idea_index?: number | null;
  parent_terminated?: boolean | null;
  parent_terminated_rationale?: string | null;
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
  inherit_idea_index?: number;
}): Promise<{ ok: boolean; run_id?: string; pid?: number; error?: string }> {
  return post('/api/sub-experiments/launch', data);
}

