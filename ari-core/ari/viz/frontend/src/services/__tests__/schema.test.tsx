// FE schema/shape contract tests (subtask 065 — add_dashboard_contract_and_schema_tests).
//
// The frontend mirror of the Python additive-subset suite in
// ari-core/tests/test_api_schema_contract.py. Every fixture is annotated with
// its types/index.ts type, so a field rename/removal in 063 fails
// `tsc --noEmit` at compile time before it ever fails a runtime assertion — the
// types are the source of truth. The wrappers round-trip each fixture through a
// mocked fetch and we assert the always-present keys survive (extra keys allowed
// — additive-subset doctrine). This is also the pinning home for AppState/`/state`,
// which is inlined in routes.py:219-666 and not a pure importable builder today.
//
// Named *.test.tsx so the existing vitest.config.ts `include` glob discovers it.

import { describe, it, expect, vi, afterEach } from 'vitest';
import {
  fetchCheckpoints,
  fetchCheckpointSummary,
  fetchSettings,
  fetchState,
  fetchWorkflow,
  fetchResourceMetrics,
} from '../api';
import type {
  AppState,
  Checkpoint,
  CheckpointSummary,
  ResourceMetrics,
  Settings,
  WorkflowData,
} from '../../types';

function stub(body: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.resolve({ ok: true, status: 200, json: async () => body } as Response)),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

// ── typed fixtures (compile-time half of the contract) ─────────────────────

const CHECKPOINT: Checkpoint = {
  id: '20260101_x',
  path: '/w/20260101_x',
  status: 'completed',
  node_count: 3,
  review_score: null,
  mtime: 1_700_000_000,
  best_metric: null,
};

const SUMMARY: CheckpointSummary = {
  id: '20260101_x',
  path: '/w/20260101_x',
  nodes_tree: { nodes: [] },
  paper_tex: null,
  has_pdf: false,
  review_report: null,
  science_data: null,
  figures_manifest: null,
  error: null,
};

const SETTINGS: Settings = {
  llm_model: 'gpt-4o',
  llm_provider: 'openai',
  llm_backend: 'openai',
  llm_api_key: '',
  ollama_host: 'http://localhost:11434',
  temperature: 1.0,
  semantic_scholar_key: '',
  retrieval_backend: 'semantic_scholar',
  ssh_host: '',
  ssh_port: 22,
  ssh_user: '',
  ssh_path: '',
  ssh_key: '',
  slurm_partition: '',
  slurm_partitions: [],
  slurm_cpus: 0,
  slurm_memory_gb: 0,
  slurm_walltime: '04:00:00',
  language: 'en',
  model_idea: '',
  model_bfts: '',
  model_coding: '',
  model_eval: '',
  model_paper: '',
  model_review: '',
  container_mode: 'auto',
  container_image: '',
  container_pull: 'on_start',
  vlm_review_enabled: true,
  vlm_review_model: 'openai/gpt-4o',
  vlm_review_max_iter: 3,
  vlm_review_threshold: 0.7,
  letta_base_url: 'http://localhost:8283',
  letta_api_key: '',
  letta_embedding_config: 'letta-default',
};

const APP_STATE: AppState = {
  nodes: [],
  checkpoint_id: null,
  checkpoint_path: null,
  running_pid: null,
  is_running: false,
  status_label: 'idle',
  current_phase: '',
  has_paper: false,
  has_pdf: false,
  has_review: false,
  has_repro: false,
  llm_model_actual: '',
  actual_models: {},
  experiment_md_content: '',
  experiment_text: '',
  experiment_goal: '',
  experiment_context: '',
  experiment_config: {},
  node_count: 0,
  ideas: [],
  gap_analysis: '',
  idea_primary_metric: '',
  idea_metric_rationale: '',
};

const WORKFLOW: WorkflowData = {
  workflow: { pipeline: [], skills: [] },
  full_pipeline: [],
  bfts_pipeline: [],
  paper_pipeline: [],
  skill_mcp: {},
  disabled_tools: [],
  path: '/w/workflow.yaml',
  ok: true,
  error: null,
};

const METRICS: ResourceMetrics = {
  process_count: 1,
  memory_rss_mb: 10.5,
  cpu_load_1m: 0.1,
  cpu_load_5m: 0.1,
  cpu_load_15m: 0.1,
  cpu_count: 4,
  experiment_pid: null,
  timestamp: '2026-07-02T00:00:00+00:00',
};

// ── round-trip assertions ──────────────────────────────────────────────────

describe('api schema round-trip – types/index.ts is the source of truth', () => {
  it('Checkpoint[] keeps its always-present keys', async () => {
    stub([CHECKPOINT]);
    const out = await fetchCheckpoints();
    expect(Array.isArray(out)).toBe(true);
    for (const k of ['id', 'path', 'status', 'node_count', 'review_score', 'mtime'] as const) {
      expect(out[0]).toHaveProperty(k);
    }
  });

  it('CheckpointSummary keeps its always-present keys', async () => {
    stub(SUMMARY);
    const out = await fetchCheckpointSummary('20260101_x');
    for (const k of ['nodes_tree', 'paper_tex', 'has_pdf', 'review_report', 'error'] as const) {
      expect(out).toHaveProperty(k);
    }
    expect(out.nodes_tree).toHaveProperty('nodes');
  });

  it('Settings keeps its always-present keys', async () => {
    stub(SETTINGS);
    const out = await fetchSettings();
    for (const k of ['llm_model', 'llm_provider', 'ollama_host', 'temperature', 'retrieval_backend'] as const) {
      expect(out).toHaveProperty(k);
    }
  });

  it('AppState (/state) keeps its always-present keys', async () => {
    stub(APP_STATE);
    const out = await fetchState();
    for (const k of ['nodes', 'is_running', 'running_pid', 'status_label', 'checkpoint_id', 'node_count'] as const) {
      expect(out).toHaveProperty(k);
    }
  });

  it('WorkflowData keeps its always-present keys', async () => {
    stub(WORKFLOW);
    const out = await fetchWorkflow();
    for (const k of ['workflow', 'full_pipeline', 'bfts_pipeline', 'paper_pipeline', 'skill_mcp', 'disabled_tools', 'path', 'ok'] as const) {
      expect(out).toHaveProperty(k);
    }
    expect(out.workflow).toHaveProperty('pipeline');
    expect(out.workflow).toHaveProperty('skills');
  });

  it('ResourceMetrics keeps its always-present keys', async () => {
    stub(METRICS);
    const out = await fetchResourceMetrics();
    for (const k of ['process_count', 'memory_rss_mb', 'cpu_load_1m', 'cpu_load_5m', 'cpu_load_15m', 'cpu_count', 'experiment_pid', 'timestamp'] as const) {
      expect(out).toHaveProperty(k);
    }
  });
});
