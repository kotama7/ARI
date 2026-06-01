// ARI Dashboard – Results page pure helpers.
// Extracted verbatim from resultSections.tsx (refactor req 15 finer split,
// per refactoring/notes/03 DAG). Pure logic / string formatters (the format*
// helpers return plain strings typed as React.ReactNode). No JSX, no components.

import type React from 'react';
import type { RubricNode, LeafGrade, StageState } from './resultTypes';

/** Attempt to parse a JSON string; return null on failure. */
export function tryParseJson(s: any): any {
  if (typeof s !== 'string') return s;
  try {
    return JSON.parse(s);
  } catch {
    return null;
  }
}

export function buildGradeMap(leaves: LeafGrade[]): Map<string, LeafGrade> {
  const m = new Map<string, LeafGrade>();
  for (const lg of leaves) {
    if (lg.id) m.set(String(lg.id), lg);
  }
  return m;
}

/** Recursively aggregate weighted score over the subtree rooted at ``node``. */
export function aggregateScore(
  node: RubricNode,
  gradesById: Map<string, LeafGrade>,
): { score: number | null; passed: number; total: number; valid: boolean } {
  const children = node.sub_tasks || [];
  if (children.length === 0) {
    // Leaf — read directly from the grade map.
    const g = node.id ? gradesById.get(String(node.id)) : undefined;
    if (!g) return { score: null, passed: 0, total: 1, valid: false };
    const mean = typeof g.mean_score === 'number' ? g.mean_score
      : (g.passed_runs ?? 0) > 0 ? 1 : 0;
    return {
      score: mean, passed: mean >= 0.5 ? 1 : 0, total: 1, valid: true,
    };
  }
  // Internal — weighted average of children.
  let totalWeight = 0;
  let weightedSum = 0;
  let passedLeaves = 0;
  let totalLeaves = 0;
  let anyValid = false;
  for (const c of children) {
    const cw = typeof c.weight === 'number' ? c.weight : 1;
    const sub = aggregateScore(c, gradesById);
    if (sub.valid && sub.score !== null) {
      totalWeight += cw;
      weightedSum += cw * sub.score;
      anyValid = true;
    }
    passedLeaves += sub.passed;
    totalLeaves += sub.total;
  }
  return {
    score: anyValid && totalWeight > 0 ? weightedSum / totalWeight : null,
    passed: passedLeaves,
    total: totalLeaves,
    valid: anyValid,
  };
}

export function truncSha(s: any): string | undefined {
  if (typeof s !== 'string' || !s) return undefined;
  return s.length > 16 ? `${s.slice(0, 16)}…` : s;
}

// `files` is either a list of paths (replicator) or an int file_count (EAR seed).
export function fileCount(files: unknown): number {
  if (Array.isArray(files)) return files.length;
  if (typeof files === 'number' && Number.isFinite(files)) return files;
  return 0;
}

export function asFileList(files: unknown): string[] {
  return Array.isArray(files) ? (files as string[]) : [];
}

export function formatFiles(files: unknown): string {
  if (Array.isArray(files)) return files.join(', ');
  if (typeof files === 'number' && Number.isFinite(files)) return `${files} files`;
  return '';
}

export function formatRubricStage(meta: Record<string, any>): React.ReactNode {
  const leaves = meta.leaves_count;
  const model = meta.model;
  const artifacts = (meta as any).expected_artifacts;
  const parts: string[] = [];
  if (typeof leaves === 'number') parts.push(`${leaves} leaves`);
  if (model) parts.push(String(model));
  if (Array.isArray(artifacts) && artifacts.length) {
    parts.push(`${artifacts.length} expected artifacts`);
  }
  return parts.join(' · ') || JSON.stringify(meta).slice(0, 120);
}

export function replicatorState(
  replicator: Record<string, any> | undefined,
  seed: Record<string, any> | undefined,
): StageState {
  if (seed?.populated) return 'ok';            // EAR seed wins
  if (replicator?.populated) return 'ok';
  if (replicator?.error) return 'fail';
  return 'pending';
}

export function formatReplicatorStage(
  replicator: Record<string, any> | undefined,
  seed: Record<string, any> | undefined,
): React.ReactNode {
  if (seed?.populated) {
    return `EAR-seeded · ${fileCount(seed.files)} files`
      + (seed.bundle_sha256 ? ` · ${String(seed.bundle_sha256).slice(0, 12)}…` : '');
  }
  if (replicator?.populated) {
    return `LLM (${replicator.model || '?'}) · ${fileCount(replicator.files)} files`;
  }
  if (replicator?.error) return `error: ${String(replicator.error).slice(0, 100)}`;
  if (replicator?.skipped_reason) return `skipped: ${replicator.skipped_reason}`;
  return '—';
}

export function phase1State(p1: Record<string, any> | undefined): StageState {
  if (!p1) return 'pending';
  if (p1.executed === false) return 'skipped';
  if (p1.exit_code === 0 && (!p1.missing || p1.missing.length === 0)) return 'ok';
  if (p1.exit_code === 0) return 'partial';   // ran but artifacts missing
  return 'fail';
}

export function formatPhase1Stage(p1: Record<string, any> | undefined): React.ReactNode {
  if (!p1) return '—';
  if (p1.executed === false) return p1.skipped_reason || 'skipped';
  const sandbox = p1.sandbox_kind || '?';
  const partition = p1.partition ? `:${p1.partition}` : '';
  const exit_ = p1.exit_code !== undefined ? `exit ${p1.exit_code}` : '';
  const elapsed = typeof p1.elapsed_sec === 'number' ? `${p1.elapsed_sec.toFixed(1)}s` : '';
  const missing = p1.missing && p1.missing.length ? `${p1.missing.length} missing` : '0 missing';
  return [`${sandbox}${partition}`, exit_, elapsed, missing].filter(Boolean).join(' · ');
}

export function phase2State(grade: Record<string, any> | undefined): StageState {
  if (!grade) return 'pending';
  if (grade.error || grade._parse_error) return 'fail';
  if (grade.degraded) return 'partial';
  if (typeof grade.ors_score === 'number') {
    if (grade.ors_score >= 0.7) return 'ok';
    if (grade.ors_score >= 0.3) return 'partial';
    return 'fail';
  }
  return 'pending';
}

export function formatPhase2Stage(grade: Record<string, any> | undefined): React.ReactNode {
  if (!grade) return '—';
  if (grade.error) return `error: ${String(grade.error).slice(0, 100)}`;
  const score = typeof grade.ors_score === 'number' ? `${(grade.ors_score * 100).toFixed(1)}%` : '?';
  const judge = grade.judge_model || '?';
  const nRuns = grade.n_runs ? `n_runs=${grade.n_runs}` : '';
  const elapsed = typeof grade.elapsed_sec === 'number' ? `${grade.elapsed_sec.toFixed(1)}s` : '';
  const degraded = grade.degraded ? '⚠ degraded' : '';
  return [score, judge, nRuns, elapsed, degraded].filter(Boolean).join(' · ');
}
