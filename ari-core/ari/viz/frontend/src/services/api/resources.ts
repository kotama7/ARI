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

export async function gpuMonitorAction(action: string): Promise<any> {
  return post('/api/gpu-monitor', { action, confirmed: true });
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
