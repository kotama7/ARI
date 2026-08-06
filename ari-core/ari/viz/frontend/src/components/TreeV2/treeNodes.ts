// ARI Dashboard – v1 tree pass-through -> TreeNode coercion (gui_refresh
// task 07 Wave 4c; plan 07 §Tree workspace / §Ideas, claims, and evidence).
//
// Extracted from TreeV2Page so the Ideas v2 workspace can reuse the SAME
// typed coercion over `TreeV1.nodes` without importing the D3 visualization
// chunk. Field-by-field type guards only — no value is invented (absent
// fields become null/''), and entries without a string id are dropped (they
// cannot be selected, drawn, or deep-linked).

import type { TreeNode } from '../../types';

export function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

export function str(v: unknown): string | null {
  return typeof v === 'string' ? v : null;
}

export function num(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

// ── RQGM score-sentinel extraction (typed, shared with the inspector) ───

/** RQGM score sentinels of one node's metrics dict (plan 07: score labels
 * carry the pre-penalty / validated-penalty / policy-hash / stale state).
 * Missing sentinels are null/false — never fabricated. Exported for tests
 * (historically via TreeV2Page, which re-exports it). */
export interface ScoreSentinels {
  scientificScore: number | null;
  prePenaltyScore: number | null;
  validatedAttackPenalty: number | null;
  utilityPolicyHash: string | null;
  stale: boolean;
}

export function sentinelsOf(
  metrics: Record<string, unknown> | null,
  fallbackScientificScore: number | null,
): ScoreSentinels {
  const m = metrics ?? {};
  return {
    scientificScore: num(m._scientific_score) ?? fallbackScientificScore,
    prePenaltyScore: num(m._pre_penalty_score),
    validatedAttackPenalty: num(m._validated_attack_penalty),
    utilityPolicyHash: str(m._utility_policy_hash),
    stale: m._stale === true,
  };
}

/** Non-sentinel scalar metrics (leading-underscore keys are RQGM/internal
 * bookkeeping and are rendered through their explicit labels instead). */
export function scalarMetricsOf(
  metrics: Record<string, unknown> | null,
): Array<[string, string]> {
  if (metrics === null) return [];
  const rows: Array<[string, string]> = [];
  for (const [key, value] of Object.entries(metrics)) {
    if (key.startsWith('_')) continue;
    if (typeof value === 'number' || typeof value === 'string' || typeof value === 'boolean') {
      rows.push([key, String(value)]);
    }
  }
  return rows;
}

/**
 * Coerce the byte-preserved v1 tree pass-through (`TreeV1.nodes`, raw dicts)
 * into the `TreeNode` shape the legacy components consume.
 */
export function toTreeNodes(raw: Array<Record<string, unknown>>): TreeNode[] {
  const nodes: TreeNode[] = [];
  for (const r of raw) {
    const id = str(r.id);
    if (id === null || id === '') continue;
    nodes.push({
      id,
      parent_id: str(r.parent_id),
      status: str(r.status) ?? '',
      label: str(r.label) ?? '',
      node_type: str(r.node_type) ?? '',
      depth: num(r.depth) ?? 0,
      name: str(r.name) ?? '',
      score: num(r.score),
      scientific_score: num(r.scientific_score),
      metrics: isRecord(r.metrics) ? r.metrics : null,
      error_log: str(r.error_log),
      eval_summary: str(r.eval_summary),
      hypothesis: str(r.hypothesis),
      description: str(r.description),
      trace_log: Array.isArray(r.trace_log)
        ? r.trace_log.filter((line): line is string => typeof line === 'string')
        : null,
      created_at: str(r.created_at),
      completed_at: str(r.completed_at),
      has_real_data: r.has_real_data === true,
    });
  }
  return nodes;
}
