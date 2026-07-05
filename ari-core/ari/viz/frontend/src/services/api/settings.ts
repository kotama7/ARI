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

export async function fetchEnvKeys(): Promise<{ keys: Record<string, string> }> {
  return get('/api/env-keys');
}
