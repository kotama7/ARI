// ARI Dashboard TypeScript type definitions

export interface TreeNode {
  id: string;
  parent_id: string | null;
  status: string;
  label: string;
  node_type: string;
  depth: number;
  name: string;
  score: number | null;
  scientific_score: number | null;
  metrics: Record<string, unknown> | null;
  error_log: string | null;
  eval_summary: string | null;
  hypothesis: string | null;
  description: string | null;
  trace_log: string[] | null;
  created_at: string | null;
  completed_at: string | null;
  has_real_data: boolean;
}

export interface Checkpoint {
  id: string;
  path: string;
  status: string;
  node_count: number;
  review_score: number | null;
  mtime: number;
  // Always emitted by the backend (`_api_checkpoints`) but never reassigned
  // from its `null` init — documented here so the contract is explicit.
  best_metric?: number | null;
  // Conditional: only present when tree nodes carry metrics._scientific_score.
  best_scientific_score?: number;
}

export interface Settings {
  llm_model: string;
  llm_provider: string;
  llm_backend: string;
  llm_api_key: string;
  ollama_host: string;
  llm_base_url?: string;
  temperature: number;
  semantic_scholar_key: string;
  retrieval_backend: string;
  ssh_host: string;
  ssh_port: number;
  ssh_user: string;
  ssh_path: string;
  ssh_key: string;
  slurm_partition: string;
  slurm_partitions: string[];
  slurm_cpus: number;
  slurm_memory_gb: number;
  slurm_walltime: string;
  language: string;
  model_idea: string;
  model_bfts: string;
  model_coding: string;
  model_eval: string;
  model_paper: string;
  model_review: string;
  container_mode: string;
  container_image: string;
  container_pull: string;
  vlm_review_enabled: boolean;
  vlm_review_model: string;
  vlm_review_max_iter: number;
  vlm_review_threshold: number;
  letta_base_url: string;
  letta_api_key: string;
  letta_embedding_config: string;
}

// Shape of {checkpoint}/cost_summary.json, surfaced verbatim as AppState.cost
// (written by ari/cost_tracker.py::_write_summary).
export interface CostSummary {
  total_cost_usd: number;
  total_tokens: number;
  call_count: number;
  by_phase: Record<string, { cost_usd: number; tokens: number }>;
  by_model: Record<string, { cost_usd: number; tokens: number }>;
}

export interface AppState {
  nodes: TreeNode[];
  checkpoint_id: string | null;
  checkpoint_path: string | null;
  running_pid: number | null;
  is_running: boolean;
  status_label: string;
  current_phase: string;
  has_paper: boolean;
  has_pdf: boolean;
  has_review: boolean;
  has_repro: boolean;
  llm_model_actual: string;
  actual_models: Record<string, string>;
  experiment_md_content: string;
  experiment_text: string;
  experiment_goal: string;
  experiment_context: string;
  experiment_config: Record<string, unknown>;
  // Backend emits the parsed cost_summary.json object here (NOT a number);
  // optional because it's only present when that file exists. Read via
  // optional chaining in MonitorPage. Corrected from the prior `number` type.
  cost?: CostSummary;
  node_count: number;
  ideas: unknown[];
  gap_analysis: string;
  idea_primary_metric: string;
  idea_metric_rationale: string;
  // ── Always present in the /state payload (set unconditionally by the
  //    routes.py builder tail), but historically omitted from this type. ──
  exit_code?: number | null;
  running?: boolean; // JS-compat alias of is_running
  pid?: number | null; // JS-compat alias of running_pid
  llm_model?: string;
  // ── Conditional (only inside the _ckpt_valid block of the builder). ──
  phase_flags?: { idea: boolean; bfts: boolean; paper: boolean; review: boolean };
  experiment_md_path?: string;
  workflow_yaml?: string;
  best_nodes?: Array<Record<string, unknown>>;
  all_metric_keys?: string[];
  summary_stats?: Record<string, unknown>;
  typed_split_sources?: string[];
}

export interface WizardState {
  step: number;
  mode: string;
  llm: string;
  scopeVal: string;
}

export interface WorkflowStage {
  stage: string;
  skill: string;
  tool: string;
  depends_on: string[];
  enabled: boolean;
  description: string;
  inputs: Record<string, unknown>;
  outputs: Record<string, unknown>;
  load_inputs: string[];
  // Stage `phase` is still a single string ("bfts" | "paper" | …). Skill-level
  // phase (SkillMcpEntry) is the one that can be string | string[].
  phase: string;
  skip_if_exists: string | null;
  loop_back_to: string | null;
  // React-driver stages declare these instead of (or alongside) `tool`.
  pre_tool?: string;
  post_tool?: string;
  react?: Record<string, unknown> | null;
}

export interface WorkflowData {
  workflow: {
    pipeline: WorkflowStage[];
    skills: WorkflowStage[];
  };
  full_pipeline: WorkflowStage[];
  bfts_pipeline: WorkflowStage[];
  paper_pipeline: WorkflowStage[];
  skill_mcp: Record<string, unknown>;
  disabled_tools: string[];
  path: string;
  ok: boolean;
  error: string | null;
}

export interface ResourceMetrics {
  process_count: number;
  memory_rss_mb: number;
  cpu_load_1m: number;
  cpu_load_5m: number;
  cpu_load_15m: number;
  cpu_count: number;
  experiment_pid: number | null;
  timestamp: string;
}

export interface ReviewScoreDimension {
  name: string;
  value: number | null;
  scale: [number, number];
  description?: string;
}

// Documented review verdict. The trailing `| string` is intentional: it keeps
// the resolved type as plain `string` (so all existing `decision: string`
// consumers compile unchanged) while documenting the known values for
// readability/autocomplete. Do NOT remove `| string` — see refactoring req 04.
export type ReviewDecision =
  | 'accept'
  | 'reject'
  | 'weak_accept'
  | 'weak_reject'
  | 'borderline'
  | string;

export interface ReviewReport {
  abstract_score: number | null;
  body_score: number | null;
  overall_score: number | null;
  score: number | null;
  scores: Record<string, number>;
  citation_ok: boolean;
  rubric_id?: string;
  rubric_version?: string;
  rubric_hash?: string;
  venue?: string;
  score_dimensions?: ReviewScoreDimension[];
  strengths?: string;
  weaknesses?: string;
  questions?: string;
  limitations?: string;
  decision?: ReviewDecision;
  confidence?: number | null;
  reflection_trace?: unknown[];
  fewshot_sources?: Array<{ id: string; title?: string; score?: number; license?: string }>;
  ensemble_reviews?: ReviewReport[];
  meta_review?: ReviewReport | null;
  issues?: string[];
  recommendations?: string[];
  figure_caption_issues?: string[];
}

// Reproducibility report: legacy runs stored a string; post-§4.1 runs (and the
// ORS-synthesized verdict) store a parsed-JSON object. Consumed loosely
// (renderOrsChain/renderLegacyRepro take `any`), so a permissive union is both
// correct and safe.
export type ReproReport = string | Record<string, unknown>;

export interface CheckpointSummary {
  // Echoed back by _api_checkpoint_summary (the requested id + resolved path).
  id?: string;
  path?: string;
  nodes_tree: {
    nodes: TreeNode[];
  };
  paper_tex: string | null;
  has_pdf: boolean;
  review_report: ReviewReport | null;
  // Corrected: backend emits the parsed report object (or, for legacy runs, a
  // string), and only when present — hence optional ReproReport, not string.
  reproducibility_report?: ReproReport | null;
  // Vestigial alias kept for back-compat; the backend no longer emits `repro`.
  repro?: string | null;
  science_data: Record<string, unknown> | null;
  figures_manifest: unknown[] | null;
  // ORS-chain payloads surfaced alongside the synthesized verdict (PaperBench
  // runs). Each is the parsed JSON, or a {_parse_error} envelope. Optional.
  ors_rubric?: unknown;
  ors_rubric_meta?: unknown;
  ors_replicator?: unknown;
  ors_seed?: unknown;
  ors_phase1?: unknown;
  ors_grade?: unknown;
  vlm_review?: unknown;
  error: string | null;
}
