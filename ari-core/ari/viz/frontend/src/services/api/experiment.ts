// ARI Dashboard API – experiment lifecycle family.

import { post } from './client';

export async function runStage(
  stage: string,
): Promise<{ ok: boolean; pid?: number; error?: string }> {
  return post('/api/run-stage', { stage });
}

// MN-6 (RR-P0-6/RR-P0-9): stopping is two-step — request a confirmation
// challenge for action 'stop-all' + target '*' first (see ./challenges),
// then pass its challenge_id here. Without a valid unexpired single-use
// challenge the server refuses with HTTP 428.
export async function stopExperiment(challengeId: string): Promise<any> {
  return post('/api/stop', { challenge_id: challengeId });
}

export async function launchExperiment(
  data: any,
): Promise<{ ok: boolean; pid?: number; error?: string; checkpoint_path?: string }> {
  return post('/api/launch', data);
}
