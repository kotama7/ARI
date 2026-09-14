// ARI Dashboard API - server-issued confirmation challenges (MN-6,
// RR-P0-6/RR-P0-9). Dangerous operations (delete-checkpoint / stop-all /
// gpu-monitor stop) are two-step: request a challenge bound to one
// action+target, show the server's echo to the user (impact preview),
// then send the challenge_id with the destructive call. Challenges are
// single-use and expire server-side after ttl_seconds.

import { post } from './client';

export type ChallengeAction = 'delete-checkpoint' | 'stop-all' | 'gpu-monitor-stop';

export interface ConfirmationChallenge {
  schema_version: number;
  challenge_id: string;
  action: ChallengeAction;
  target: string;
  /** Display-only wall-clock expiry; the server enforces a monotonic TTL. */
  expires_at: string;
  ttl_seconds: number;
}

export async function requestConfirmationChallenge(
  action: ChallengeAction,
  target: string,
): Promise<ConfirmationChallenge> {
  return post('/api/v1/challenges', { action, target });
}
