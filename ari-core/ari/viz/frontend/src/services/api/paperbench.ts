// ARI Dashboard API – PaperBench family (the pbGet/pbPost no-throw regime).
//
// These endpoints return 200 + {error} for application errors (routes.py
// _json defaults to status=200). Several PaperBench call sites read the
// response body unconditionally and have no try/catch, so pbGet/pbPost
// deliberately do NOT throw on non-2xx — they mirror the components' existing
// `fetch(...).then(r => r.json())` behavior exactly. URLs match the original
// call sites verbatim (encoded params only where the components encoded them).

import { pbGet, pbPost } from './client';

// papers is typed as any[] because each consumer applies its own richer local
// row type (e.g. PaperRegistryPage.PaperEntry); matches the prior untyped read.
export async function fetchPaperbenchPapers(): Promise<{
  papers?: any[];
  error?: string;
}> {
  return pbGet('/api/paperbench/papers');
}

export async function deletePaperbenchPaper(
  id: string,
): Promise<{ deleted?: boolean; error?: string; reason?: string }> {
  // Original call sent no body and no Content-Type header — preserved exactly.
  const res = await fetch(`/api/paperbench/papers/${encodeURIComponent(id)}/delete`, {
    method: 'POST',
  });
  return res.json();
}

export async function estimatePaperbenchCost(body: {
  rubric_config: unknown;
  reproduce_config: unknown;
  judge_config: unknown;
}): Promise<any> {
  return pbPost('/api/paperbench/cost-estimate', body);
}

export async function runPaperbench(
  body: unknown,
): Promise<{ job_ids?: string[]; error?: string }> {
  return pbPost('/api/paperbench/run', body);
}

export async function fetchArxivMetadata(source: string): Promise<{
  title?: string;
  authors?: string[];
  year?: number | string;
  license?: string;
  error?: string;
}> {
  return pbGet(`/api/paperbench/arxiv/${encodeURIComponent(source)}`);
}

export async function importPaperbenchPaper(body: Record<string, unknown>): Promise<any> {
  return pbPost('/api/paperbench/papers/import', body);
}

// jobId is NOT URL-encoded here to match the original call sites verbatim.
export async function fetchPaperbenchRun(jobId: string): Promise<any> {
  return pbGet(`/api/paperbench/run/${jobId}`);
}

export async function fetchPaperbenchRunResults(jobId: string): Promise<any> {
  return pbGet(`/api/paperbench/run/${jobId}/results`);
}

export async function requestPaperbenchReport(
  jobId: string,
  body: { languages: string[]; formats: string[] },
): Promise<{ download_urls?: Record<string, string>; error?: string }> {
  return pbPost(`/api/paperbench/run/${jobId}/report`, body);
}
