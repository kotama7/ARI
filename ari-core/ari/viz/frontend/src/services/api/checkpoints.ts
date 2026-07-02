// ARI Dashboard API – checkpoint list + summary + lifecycle family.

import type { Checkpoint, CheckpointSummary } from '../../types';
import { get, post } from './client';

export async function fetchCheckpoints(): Promise<Checkpoint[]> {
  return get<Checkpoint[]>('/api/checkpoints');
}

export async function fetchCheckpointSummary(id: string): Promise<CheckpointSummary> {
  return get<CheckpointSummary>(`/api/checkpoint/${encodeURIComponent(id)}/summary`);
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
