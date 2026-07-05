// ARI Dashboard API – state / tree / models family.

import type { AppState, ResourceMetrics } from '../../types';
import { get } from './client';

export async function fetchState(): Promise<AppState> {
  return get<AppState>('/state');
}

export async function fetchExperimentDetail(): Promise<string> {
  const d = await get<{ experiment_detail_config?: string }>('/api/experiment-detail');
  return d.experiment_detail_config ?? '';
}

export async function fetchActiveCheckpoint(): Promise<{ id?: string; path?: string }> {
  return get('/api/active-checkpoint');
}

export async function fetchResourceMetrics(): Promise<ResourceMetrics> {
  return get<ResourceMetrics>('/api/resource-metrics');
}

export async function fetchModels(): Promise<any> {
  return get('/api/models');
}
