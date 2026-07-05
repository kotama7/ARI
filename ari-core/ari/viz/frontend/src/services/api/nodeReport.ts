// ARI Dashboard API – node report family (v0.7.0).

import { get } from './client';

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
