// ARI Dashboard API – checkpoint list + summary + lifecycle family.

import type { Checkpoint, CheckpointSummary } from '../../types';
import { get, post } from './client';

export async function fetchCheckpoints(): Promise<Checkpoint[]> {
  return get<Checkpoint[]>('/api/checkpoints');
}

export async function fetchCheckpointSummary(id: string): Promise<CheckpointSummary> {
  return get<CheckpointSummary>(`/api/checkpoint/${encodeURIComponent(id)}/summary`);
}

// MN-6 (RR-P0-6/RR-P0-9): deletion is two-step — request a confirmation
// challenge for action 'delete-checkpoint' + this exact path first (see
// ./challenges), then pass its challenge_id here. Without a valid unexpired
// single-use challenge the server refuses with HTTP 428.
export async function deleteCheckpoint(
  id: string,
  path: string,
  challengeId: string,
): Promise<{ ok: boolean; error?: string }> {
  return post('/api/delete-checkpoint', { id, path, challenge_id: challengeId });
}

export async function switchCheckpoint(
  path: string,
): Promise<{ ok: boolean; error?: string }> {
  return post('/api/switch-checkpoint', { path });
}
