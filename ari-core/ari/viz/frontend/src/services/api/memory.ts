// ARI Dashboard API – memory (Letta) family.

import { get, post } from './client';

export interface MemoryEntry {
  node_id: string;
  text: string;
  metadata: Record<string, unknown>;
  tags?: string[];
  ts?: number;
  source: 'mcp' | 'file_client' | 'global';
}

export interface MemoryResponse {
  id: string;
  entries: MemoryEntry[];
  by_node: Record<string, MemoryEntry[]>;
  global?: MemoryEntry[];
  global_path?: string;
  count: number;
  error?: string;
}

export async function fetchCheckpointMemory(id: string): Promise<MemoryResponse> {
  return get<MemoryResponse>(`/api/checkpoint/${encodeURIComponent(id)}/memory`);
}

export interface MemoryAccessEvent {
  ts: number;
  node_id: string;
  op: 'read' | 'write';
  query?: string;
  text_preview?: string;
  results?: Array<{ entry_id?: string; score?: number; [k: string]: unknown }>;
  [k: string]: unknown;
}

export interface MemoryAccessResponse {
  node_id: string;
  writes: MemoryAccessEvent[];
  reads: MemoryAccessEvent[];
  read_by_entry: Record<string, { count: number; last_ts: number }>;
  error?: string;
}

export async function fetchMemoryAccess(
  id: string,
  nodeId: string,
  op: 'read' | 'write' | 'all' = 'all',
  limit = 200,
): Promise<MemoryAccessResponse> {
  const q = new URLSearchParams({ node_id: nodeId, op, limit: String(limit) });
  return get<MemoryAccessResponse>(
    `/api/checkpoint/${encodeURIComponent(id)}/memory_access?${q.toString()}`,
  );
}

export interface MemoryHealth {
  status: string;
  latency_ms: number;
  namespace: string | null;
  server_version: string;
  detected_deployment: string;
  reason?: string;
  error?: string;
}

export async function fetchMemoryHealth(): Promise<MemoryHealth> {
  return get<MemoryHealth>('/api/memory/health');
}

export async function restartLetta(
  path: string = 'auto',
): Promise<{
  ok: boolean;
  start?: { ok: boolean; path?: string; stdout?: string; error?: string };
  stop?: { ok: boolean; attempts?: string[] };
  error?: string;
}> {
  return post('/api/memory/restart', { path });
}
