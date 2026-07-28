// ARI Dashboard API – infra probes: scheduler / SLURM / Ollama / GPU / container.

import { get, post } from './client';

export async function detectScheduler(): Promise<{ scheduler: string; partitions: any[] }> {
  return get('/api/scheduler/detect');
}

export async function fetchPartitions(): Promise<any[]> {
  return get<any[]>('/api/slurm/partitions');
}

// ── Ollama / GPU ───────────────────────────────

export async function fetchOllamaResources(): Promise<{ gpus: any[]; models: string[] }> {
  return get('/api/ollama-resources');
}

export async function fetchGpuMonitor(): Promise<{
  running: boolean;
  pid?: number;
  log?: string;
  ollama_host?: string;
}> {
  return get('/api/gpu-monitor');
}

// MN-6 (RR-P0-6/RR-P0-9): the confirmed flag is no longer hardcoded —
// 'start' callers forward the user's explicit confirmation result, and
// 'stop' is two-step (a 'gpu-monitor-stop' challenge for target '*'
// from ./challenges, echoed back as challenge_id; else the server
// refuses with HTTP 428).
export async function gpuMonitorAction(
  action: string,
  opts?: { confirmed?: boolean; challengeId?: string },
): Promise<any> {
  const body: Record<string, unknown> = { action };
  if (opts?.confirmed !== undefined) body.confirmed = opts.confirmed;
  if (opts?.challengeId !== undefined) body.challenge_id = opts.challengeId;
  return post('/api/gpu-monitor', body);
}

// ── container ─────────────────────────────────

export async function fetchContainerInfo(): Promise<{
  runtime: string;
  version: string;
  available: boolean;
}> {
  return get('/api/container/info');
}

export interface ContainerImage {
  name: string;
  size: string;
}

export async function fetchContainerImages(): Promise<{ images: ContainerImage[] }> {
  return get('/api/container/images');
}

export async function pullContainerImage(
  image: string,
  mode?: string,
): Promise<{ ok: boolean; error?: string }> {
  return post('/api/container/pull', { image, mode: mode || 'auto' });
}
