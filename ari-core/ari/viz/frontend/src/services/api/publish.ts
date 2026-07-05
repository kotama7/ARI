// ARI Dashboard API – publish family.

import { get, post } from './client';

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
