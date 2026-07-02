// ARI Dashboard API – sub-experiments (recursive orchestration) family.

import { get, post } from './client';

export interface SubExperiment {
  run_id: string;
  parent_run_id?: string | null;
  recursion_depth: number;
  max_recursion_depth: number;
  created_at?: string;
  checkpoint_dir?: string;
  // v0.7.0: surfaced when this sub-experiment was launched by lineage decision
  // switch_to_idea / fanout / opt-in inherit_idea_index. Lets the GUI
  // render lineage provenance on the Experiments page.
  inherit_idea_index?: number | null;
  parent_terminated?: boolean | null;
  parent_terminated_rationale?: string | null;
}

export async function fetchSubExperiments(): Promise<{ sub_experiments: SubExperiment[] }> {
  return get('/api/sub-experiments');
}

export async function fetchSubExperiment(runId: string): Promise<SubExperiment> {
  return get(`/api/sub-experiments/${encodeURIComponent(runId)}`);
}

export async function launchSubExperiment(data: {
  experiment_md: string;
  max_recursion_depth?: number;
  parent_run_id?: string;
  recursion_depth?: number;
  inherit_idea_index?: number;
}): Promise<{ ok: boolean; run_id?: string; pid?: number; error?: string }> {
  return post('/api/sub-experiments/launch', data);
}
