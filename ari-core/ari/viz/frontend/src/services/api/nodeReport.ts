// ARI Dashboard API - node report resource (v0.7.0).

import { get } from './client';

export interface NodeReportFilesChanged {
  // `note` is the agent's optional one-line explanation of the file (finish
  // JSON `file_notes`), grafted on by the node_report builder.
  added: Array<{ path: string; sha256?: string; note?: string }>;
  modified: Array<{
    path: string;
    sha256_before?: string;
    sha256_after?: string;
    note?: string;
  }>;
  deleted: Array<{ path: string; note?: string }>;
  inherited_unchanged: Array<{ path: string; from_node_id?: string }>;
}

export interface NodeReportSelfAssessment {
  headline?: string;
  concerns?: string[];
}

export interface NodeReportEvaluationCase {
  valid: boolean;
  measurements: Record<string, number | boolean | string | null>;
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
  metrics?: Record<string, unknown>;
  measurement_valid?: boolean;
  evaluation_cases?: Record<string, NodeReportEvaluationCase>;
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
