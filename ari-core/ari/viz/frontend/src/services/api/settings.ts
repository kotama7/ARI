// ARI Dashboard API – settings / env family.

import type { Settings } from '../../types';
import { get, post } from './client';

export async function fetchSettings(): Promise<Settings> {
  return get<Settings>('/api/settings');
}

export async function saveSettings(
  data: Partial<Settings>,
): Promise<{ ok: boolean; error?: string }> {
  return post('/api/settings', data);
}

// Secret READINESS (gui_refresh Wave 3a, RR-P0-2 / ADR-11 / MN-2).
// GET /api/v1/secrets/status reports WHETHER each allowlisted secret is
// configured — never its value. The legacy GET /api/env-keys is redacted
// server-side (values replaced by '***configured***') and no longer has a
// frontend reader; the POST write path (saveSettings api_key) is unchanged.
export interface SecretStatus {
  name: string;
  configured: boolean;
  source_class:
    | 'project_env'
    | 'repo_env'
    | 'user_env'
    | 'process_env'
    | null;
  last_updated: string | null;
}

export async function fetchSecretsStatus(): Promise<{
  schema_version: number;
  secrets: SecretStatus[];
}> {
  return get('/api/v1/secrets/status');
}
