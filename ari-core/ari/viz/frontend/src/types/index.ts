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
}

export interface Settings {
  llm_model: string;
  llm_provider: string;
  llm_backend: string;
  llm_api_key: string;
  ollama_host: string;
  temperature: number;
  semantic_scholar_key: string;
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
  experiment_detail_config: Record<string, unknown>;
  cost: number;
  node_count: number;
  ideas: unknown[];
  gap_analysis: string;
  idea_primary_metric: string;
  idea_metric_rationale: string;
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
  phase: string;
  skip_if_exists: string | null;
  loop_back_to: string | null;
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
  path: string;
  ok: boolean;
  error: string | null;
}

export interface ReviewReport {
  abstract_score: number | null;
  body_score: number | null;
  overall_score: number | null;
  score: number | null;
  scores: Record<string, number>;
  citation_ok: boolean;
}

export interface CheckpointSummary {
  nodes_tree: {
    nodes: TreeNode[];
  };
  paper_tex: string | null;
  has_pdf: boolean;
  review_report: ReviewReport | null;
  reproducibility_report: string | null;
  repro: string | null;
  science_data: Record<string, unknown> | null;
  figures_manifest: unknown[] | null;
  error: string | null;
}
