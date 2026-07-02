// ARI Dashboard API – EAR (Experiment Artifact Repository) family.

import { get, post } from './client';

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
