// ARI Dashboard API – experiment lifecycle family.

import { post } from './client';

export async function runStage(
  stage: string,
): Promise<{ ok: boolean; pid?: number; error?: string }> {
  return post('/api/run-stage', { stage });
}

export async function stopExperiment(): Promise<any> {
  return post('/api/stop');
}

export async function launchExperiment(
  data: any,
): Promise<{ ok: boolean; pid?: number; error?: string; checkpoint_path?: string }> {
  return post('/api/launch', data);
}
