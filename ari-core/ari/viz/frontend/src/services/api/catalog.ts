// ARI Dashboard API – profiles / rubrics / few-shot catalog family.

import { get, post } from './client';

export async function fetchProfiles(): Promise<string[]> {
  return get<string[]>('/api/profiles');
}

export interface RubricSummary {
  id: string;
  venue: string;
  domain: string;
  version: string;
  closed_review?: boolean;
  path: string;
}

export async function fetchRubrics(): Promise<RubricSummary[]> {
  return get<RubricSummary[]>('/api/rubrics');
}

export interface FewshotExample {
  id: string;
  files: Array<{ ext: string; size: number }>;
  source: string;
  decision: string;
  overall: number | null;
}

export interface FewshotListing {
  rubric_id: string;
  count: number;
  examples: FewshotExample[];
  error?: string;
}

export async function fetchFewshot(rubricId: string): Promise<FewshotListing> {
  return get<FewshotListing>(`/api/fewshot/${encodeURIComponent(rubricId)}`);
}

export async function syncFewshot(rubricId: string): Promise<any> {
  return post(`/api/fewshot/${encodeURIComponent(rubricId)}/sync`, {});
}

export async function uploadFewshot(
  rubricId: string,
  payload: {
    example_id: string;
    review_json: string;
    paper_txt?: string;
    paper_pdf?: string;
  },
): Promise<any> {
  return post(`/api/fewshot/${encodeURIComponent(rubricId)}/upload`, payload);
}

export async function deleteFewshot(
  rubricId: string,
  exampleId: string,
): Promise<any> {
  return post(
    `/api/fewshot/${encodeURIComponent(rubricId)}/${encodeURIComponent(
      exampleId,
    )}/delete`,
    {},
  );
}
