// ARI Dashboard – typed /api/v1 client (gui_refresh Wave 2b, ADR-01/ADR-02).
//
// Read-only fetchers for the versioned dashboard API. DTO shapes come from
// src/services/api/v1types.gen.ts, generated from ari/viz/v1/openapi.json by
// `npm run gen:v1types` (drift-guarded by src/__tests__/v1TypesDrift.test.ts).
//
// Error contract (plan 03 §API client contract): every failure — typed
// ErrorEnvelopeV1 from the backend, network failure, or malformed body —
// surfaces as a thrown ApiErrorV1 normalized to
// {code, message, details, request_id, retryable}.
//
// Transport: the shared client.ts core, via its v1Get regime. The backend
// returns real non-2xx statuses whose body IS the typed envelope; the
// throwing get<T> regime would discard that body, so v1Get resolves with the
// parsed body and the envelope is detected/normalized here.

import { v1Get, v1Send } from './client';
import type { components } from './v1types.gen';

// ── generated DTO aliases (re-exported for consumers/hooks) ─────────────

export type ProjectV1 = components['schemas']['ProjectV1'];
export type ProjectListV1 = components['schemas']['ProjectListV1'];
export type RunSummaryV1 = components['schemas']['RunSummaryV1'];
export type RunDetailV1 = components['schemas']['RunDetailV1'];
export type RunListV1 = components['schemas']['RunListV1'];
export type TreeV1 = components['schemas']['TreeV1'];
// Ideas v2 workspace (gui_refresh Wave 4c — pure idea.json read, plan 07
// §Ideas, claims, and evidence).
export type RunIdeaV1 = components['schemas']['RunIdeaV1'];
// Results v2 workspace (gui_refresh task 07 Wave 4d — bounded result/EAR
// read models, plan 07 §Evidence, Results, and PaperBench).
export type ResultPaperV1 = components['schemas']['ResultPaperV1'];
export type ReviewDimensionV1 = components['schemas']['ReviewDimensionV1'];
export type ResultReviewV1 = components['schemas']['ResultReviewV1'];
export type ResultOrsV1 = components['schemas']['ResultOrsV1'];
export type ResultEarV1 = components['schemas']['ResultEarV1'];
export type RunResultsV1 = components['schemas']['RunResultsV1'];
export type EarFileV1 = components['schemas']['EarFileV1'];
export type EarManifestV1 = components['schemas']['EarManifestV1'];
export type EarPublishRecordV1 = components['schemas']['EarPublishRecordV1'];
export type RunEarV1 = components['schemas']['RunEarV1'];
// Cursor log explorer (gui_refresh task 07 tail — plan 07 §Artifacts, logs,
// and diagnostics: bounded byte-offset pages over {ckpt}/ari.log).
export type LogEntryV1 = components['schemas']['LogEntryV1'];
export type RunLogsV1 = components['schemas']['RunLogsV1'];
// Config browser (gui_refresh Wave 3b — read-only effective config).
export type ConfigFieldV1 = components['schemas']['ConfigFieldV1'];
export type ConfigSchemaV1 = components['schemas']['ConfigSchemaV1'];
export type ProvenanceEntryV1 = components['schemas']['ProvenanceEntryV1'];
export type SecretReferenceV1 = components['schemas']['SecretReferenceV1'];
export type ResolvedConfigV1 = components['schemas']['ResolvedConfigV1'];
// Configuration Studio (gui_refresh task 06 Wave 4d — config documents,
// secret readiness/assignment, server-side model catalog; plans 05/06).
export type ProjectConfigV1 = components['schemas']['ProjectConfigV1'];
export type RunTemplateSummaryV1 = components['schemas']['RunTemplateSummaryV1'];
export type RunTemplateListV1 = components['schemas']['RunTemplateListV1'];
export type RunTemplateV1 = components['schemas']['RunTemplateV1'];
export type RunDraftV1 = components['schemas']['RunDraftV1'];
export type SecretV1 = components['schemas']['SecretV1'];
export type SecretStatusV1 = components['schemas']['SecretStatusV1'];
export type SecretUpdatedV1 = components['schemas']['SecretUpdatedV1'];
export type ModelProviderV1 = components['schemas']['ModelProviderV1'];
export type ModelCatalogV1 = components['schemas']['ModelCatalogV1'];
// Studio launch flow (gui_refresh task 06 Wave 4e — plan 06 §Launch
// protocol: resolve-config -> validate -> immutable review -> idempotent
// POST /api/v1/runs -> canonical #/overview?run=<run_id> redirect).
export type NewRunProvenanceV1 = components['schemas']['NewRunProvenanceV1'];
export type ResolvedNewRunConfigV1 = components['schemas']['ResolvedNewRunConfigV1'];
export type DraftValidationErrorV1 = components['schemas']['DraftValidationErrorV1'];
export type DraftValidationV1 = components['schemas']['DraftValidationV1'];
export type RunLaunchRequestV1 = components['schemas']['RunLaunchRequestV1'];
export type RunLaunchedV1 = components['schemas']['RunLaunchedV1'];
/** The CLI --profile closed set (shared by resolve/validate/launch). */
export type LaunchProfileV1 = NonNullable<RunLaunchRequestV1['profile']>;
// Governance workspace (gui_refresh Wave 4a — read-only RQGM, plan 08).
export type RqgmCapabilitiesV1 = components['schemas']['RqgmCapabilitiesV1'];
export type RqgmIntegrityV1 = components['schemas']['RqgmIntegrityV1'];
export type RqgmOverviewV1 = components['schemas']['RqgmOverviewV1'];
export type RqgmComponentV1 = components['schemas']['RqgmComponentV1'];
export type RqgmPromptV1 = components['schemas']['RqgmPromptV1'];
export type RqgmRegistryV1 = components['schemas']['RqgmRegistryV1'];
export type RqgmAuditEntryV1 = components['schemas']['RqgmAuditEntryV1'];
export type RqgmAuditPageV1 = components['schemas']['RqgmAuditPageV1'];
export type RqgmScoreObservationV1 = components['schemas']['RqgmScoreObservationV1'];
export type RqgmRawAttackV1 = components['schemas']['RqgmRawAttackV1'];
export type RqgmValidatedAttackV1 = components['schemas']['RqgmValidatedAttackV1'];
export type RqgmNodeLineageV1 = components['schemas']['RqgmNodeLineageV1'];
export type RqgmScoreRewriteV1 = components['schemas']['RqgmScoreRewriteV1'];
export type RqgmScoreRewritesPageV1 = components['schemas']['RqgmScoreRewritesPageV1'];
export type RqgmPolicyV1 = components['schemas']['RqgmPolicyV1'];
export type RqgmPoliciesV1 = components['schemas']['RqgmPoliciesV1'];
export type RqgmEpochTransitionCountsV1 =
  components['schemas']['RqgmEpochTransitionCountsV1'];
export type RqgmEpochV1 = components['schemas']['RqgmEpochV1'];
export type RqgmEpochsV1 = components['schemas']['RqgmEpochsV1'];
export type RqgmTransactionRefV1 = components['schemas']['RqgmTransactionRefV1'];
export type RqgmEpochDetailV1 = components['schemas']['RqgmEpochDetailV1'];
export type RqgmEvolutionEntryV1 = components['schemas']['RqgmEvolutionEntryV1'];
export type RqgmEvolutionV1 = components['schemas']['RqgmEvolutionV1'];
export type RqgmPaperAnchorV1 = components['schemas']['RqgmPaperAnchorV1'];
export type RqgmPaperSelfPreferenceV1 =
  components['schemas']['RqgmPaperSelfPreferenceV1'];
export type RqgmPaperWinnerV1 = components['schemas']['RqgmPaperWinnerV1'];
export type RqgmPaperArchiveV1 = components['schemas']['RqgmPaperArchiveV1'];
export type ErrorBodyV1 = components['schemas']['ErrorBodyV1'];
export type ErrorEnvelopeV1 = components['schemas']['ErrorEnvelopeV1'];
/** Router-injected top-level request_id present on every 200 body. */
export type RequestIdV1 = components['schemas']['RequestIdV1'];

// ── normalized error (plan 03 §API client contract) ─────────────────────

/**
 * Normalized API error: {code, message, details, request_id, retryable}.
 *
 * Extends Error so existing `err.message` consumers (e.g. useApi-style
 * catch blocks and react-query error rendering) keep working unchanged.
 */
export class ApiErrorV1 extends Error {
  readonly code: ErrorBodyV1['code'];
  readonly details: unknown;
  readonly request_id: string;
  readonly retryable: boolean;

  constructor(body: ErrorBodyV1) {
    super(body.message);
    this.name = 'ApiErrorV1';
    this.code = body.code;
    this.details = body.details ?? null;
    this.request_id = body.request_id;
    this.retryable = body.retryable ?? false;
  }
}

function isErrorEnvelope(body: unknown): body is ErrorEnvelopeV1 {
  if (typeof body !== 'object' || body === null) return false;
  const err = (body as { error?: unknown }).error;
  return (
    typeof err === 'object' &&
    err !== null &&
    typeof (err as { code?: unknown }).code === 'string' &&
    typeof (err as { message?: unknown }).message === 'string'
  );
}

/**
 * Normalize any failure into an ApiErrorV1.
 *
 * - ApiErrorV1 passes through untouched.
 * - A typed ErrorEnvelopeV1 body keeps the server's code/details/request_id/
 *   retryable verbatim.
 * - Anything else (fetch rejection, JSON parse failure, unexpected body) maps
 *   to code 'internal', retryable true (transport hiccups are worth a retry),
 *   request_id '' (none was received).
 */
export function toApiError(input: unknown): ApiErrorV1 {
  if (input instanceof ApiErrorV1) return input;
  if (isErrorEnvelope(input)) return new ApiErrorV1(input.error);
  const message = input instanceof Error ? input.message : String(input);
  return new ApiErrorV1({
    code: 'internal',
    message,
    details: null,
    request_id: '',
    retryable: true,
  });
}

// ── fetchers ────────────────────────────────────────────────────────────

async function fetchV1<T>(path: string): Promise<T> {
  let body: unknown;
  try {
    body = await v1Get<unknown>(path);
  } catch (err) {
    throw toApiError(err);
  }
  if (isErrorEnvelope(body)) throw toApiError(body);
  return body as T;
}

export function fetchProjectsV1(): Promise<ProjectListV1 & RequestIdV1> {
  return fetchV1<ProjectListV1 & RequestIdV1>('/api/v1/projects');
}

export function fetchRunsV1(projectId: string): Promise<RunListV1 & RequestIdV1> {
  return fetchV1<RunListV1 & RequestIdV1>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/runs`,
  );
}

export function fetchRunV1(runId: string): Promise<RunDetailV1 & RequestIdV1> {
  return fetchV1<RunDetailV1 & RequestIdV1>(`/api/v1/runs/${encodeURIComponent(runId)}`);
}

export function fetchRunSummaryV1(runId: string): Promise<RunSummaryV1 & RequestIdV1> {
  return fetchV1<RunSummaryV1 & RequestIdV1>(
    `/api/v1/runs/${encodeURIComponent(runId)}/summary`,
  );
}

export function fetchRunTreeV1(runId: string): Promise<TreeV1 & RequestIdV1> {
  return fetchV1<TreeV1 & RequestIdV1>(`/api/v1/runs/${encodeURIComponent(runId)}/tree`);
}

/**
 * One run's idea.json read model (gui_refresh Wave 4c). Honest absence:
 * `present` is false when idea.json does not exist (never fabricated empty
 * strings); a malformed file is a 200 with `degraded_reasons`.
 */
export function fetchRunIdeaV1(runId: string): Promise<RunIdeaV1 & RequestIdV1> {
  return fetchV1<RunIdeaV1 & RequestIdV1>(`/api/v1/runs/${encodeURIComponent(runId)}/idea`);
}

/**
 * One run's bounded result read model (gui_refresh task 07 Wave 4d):
 * paper/review/ORS/EAR presence flags + scalars. Every block carries honest
 * absence flags; parse failures ride `degraded_reasons`, never a 500.
 */
export function fetchRunResultsV1(runId: string): Promise<RunResultsV1 & RequestIdV1> {
  return fetchV1<RunResultsV1 & RequestIdV1>(
    `/api/v1/runs/${encodeURIComponent(runId)}/results`,
  );
}

/**
 * One run's EAR listing metadata + curate/publish/promote lineage scalars
 * (gui_refresh task 07 Wave 4d). No file contents ever ride this endpoint —
 * the legacy #/results page stays the full editor workspace.
 */
export function fetchRunEarV1(runId: string): Promise<RunEarV1 & RequestIdV1> {
  return fetchV1<RunEarV1 & RequestIdV1>(
    `/api/v1/runs/${encodeURIComponent(runId)}/ear`,
  );
}

export interface RunLogsQuery {
  /** Raw byte offset into ari.log to resume from (default 0). */
  cursor?: number;
  /** Maximum matching lines per page, 1-1000 (server default 200). */
  limit?: number;
  /** Case-insensitive substring filter (cursor stability is filter-independent). */
  grep?: string;
}

/**
 * One bounded cursor page over the append-only `{ckpt}/ari.log`
 * (gui_refresh task 07 tail). The cursor is a RAW byte offset — pagination
 * never gaps or duplicates, under any grep filter. `next_cursor` is always
 * the resume offset (also at eof, for tail-follow polling); a missing log
 * file is an honest `present: false` (200), never a 404.
 */
export function fetchRunLogsV1(
  runId: string,
  query: RunLogsQuery = {},
): Promise<RunLogsV1 & RequestIdV1> {
  const params = new URLSearchParams();
  if (query.cursor !== undefined) params.set('cursor', String(query.cursor));
  if (query.limit !== undefined) params.set('limit', String(query.limit));
  if (query.grep) params.set('grep', query.grep);
  const qs = params.toString();
  return fetchV1<RunLogsV1 & RequestIdV1>(
    `/api/v1/runs/${encodeURIComponent(runId)}/logs${qs === '' ? '' : `?${qs}`}`,
  );
}

/** Canonical config-field registry (metadata only — never effective values). */
export function fetchConfigSchemaV1(): Promise<ConfigSchemaV1 & RequestIdV1> {
  return fetchV1<ConfigSchemaV1 & RequestIdV1>('/api/v1/config/schema');
}

// ── Configuration Studio (gui_refresh task 06 Wave 4d — plans 05/06) ────
//
// Config-document CRUD over the ADR-12 gui_store: every mutation resolves
// the same envelope regime as the reads (a typed error body throws as
// ApiErrorV1 — code 'invalid_request' carries the per-path validation
// errors in details.errors, code 'revision_conflict' is the stale If-Match
// 409). Secrets are WRITE-ONLY: putSecretV1 sends the value and receives a
// readiness row — no fetcher in this module can ever read a secret value.

async function sendV1<T>(
  path: string,
  opts: { method: 'POST' | 'PATCH' | 'PUT' | 'DELETE'; json?: unknown; ifMatch?: number },
): Promise<T> {
  let body: unknown;
  try {
    body = await v1Send<unknown>(path, opts);
  } catch (err) {
    throw toApiError(err);
  }
  if (isErrorEnvelope(body)) throw toApiError(body);
  return body as T;
}

/** One project's config document (revision 0 + empty values when unsaved). */
export function fetchProjectConfigV1(
  projectId = 'default',
): Promise<ProjectConfigV1 & RequestIdV1> {
  return fetchV1<ProjectConfigV1 & RequestIdV1>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/config`,
  );
}

/** Partial {dotted.path: value} update; If-Match is the current revision (0 creates). */
export function patchProjectConfigV1(
  values: Record<string, unknown>,
  ifMatch: number,
  projectId = 'default',
): Promise<ProjectConfigV1 & RequestIdV1> {
  return sendV1<ProjectConfigV1 & RequestIdV1>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/config`,
    { method: 'PATCH', json: { values }, ifMatch },
  );
}

export function fetchRunTemplatesV1(): Promise<RunTemplateListV1 & RequestIdV1> {
  return fetchV1<RunTemplateListV1 & RequestIdV1>('/api/v1/run-templates');
}

export function fetchRunTemplateV1(
  templateId: string,
): Promise<RunTemplateV1 & RequestIdV1> {
  return fetchV1<RunTemplateV1 & RequestIdV1>(
    `/api/v1/run-templates/${encodeURIComponent(templateId)}`,
  );
}

/** Create-only POST (a taken template_id throws code 'already_exists'). */
export function createRunTemplateV1(
  templateId: string,
  name: string,
  values: Record<string, unknown> = {},
): Promise<RunTemplateV1 & RequestIdV1> {
  return sendV1<RunTemplateV1 & RequestIdV1>('/api/v1/run-templates', {
    method: 'POST',
    json: { template_id: templateId, name, values },
  });
}

export function patchRunTemplateV1(
  templateId: string,
  values: Record<string, unknown>,
  ifMatch: number,
): Promise<RunTemplateV1 & RequestIdV1> {
  return sendV1<RunTemplateV1 & RequestIdV1>(
    `/api/v1/run-templates/${encodeURIComponent(templateId)}`,
    { method: 'PATCH', json: { values }, ifMatch },
  );
}

/**
 * Server generates the draft id; the template link is optional + immutable.
 * `goal` (Wave 4e, additive) is the free-text research goal a later
 * POST /api/v1/runs materializes as {ckpt}/experiment.md — set at create
 * only (PATCH is a values-merge and preserves it verbatim).
 */
export function createRunDraftV1(
  templateId?: string,
  values: Record<string, unknown> = {},
  goal?: string,
): Promise<RunDraftV1 & RequestIdV1> {
  const json: Record<string, unknown> = { values };
  if (templateId !== undefined) json.template_id = templateId;
  if (goal !== undefined) json.goal = goal;
  return sendV1<RunDraftV1 & RequestIdV1>('/api/v1/run-drafts', {
    method: 'POST',
    json,
  });
}

export function fetchRunDraftV1(draftId: string): Promise<RunDraftV1 & RequestIdV1> {
  return fetchV1<RunDraftV1 & RequestIdV1>(
    `/api/v1/run-drafts/${encodeURIComponent(draftId)}`,
  );
}

export function patchRunDraftV1(
  draftId: string,
  values: Record<string, unknown>,
  ifMatch: number,
): Promise<RunDraftV1 & RequestIdV1> {
  return sendV1<RunDraftV1 & RequestIdV1>(
    `/api/v1/run-drafts/${encodeURIComponent(draftId)}`,
    { method: 'PATCH', json: { values }, ifMatch },
  );
}

/** Secret READINESS (ADR-11): configured/source_class/last_updated — never values. */
export function fetchSecretsStatusV1(): Promise<SecretStatusV1 & RequestIdV1> {
  return fetchV1<SecretStatusV1 & RequestIdV1>('/api/v1/secrets/status');
}

/**
 * Write-only secret assignment (ADR-05): PUT the value, receive the
 * post-write READINESS row. The response type has no value field — echoing
 * the secret back is structurally impossible.
 */
export function putSecretV1(
  secretId: string,
  value: string,
): Promise<SecretUpdatedV1 & RequestIdV1> {
  return sendV1<SecretUpdatedV1 & RequestIdV1>(
    `/api/v1/secrets/${encodeURIComponent(secretId)}`,
    { method: 'PUT', json: { value } },
  );
}

/** Server-side model/provider catalog (plan 06: no frontend model constants). */
export function fetchModelCatalogV1(): Promise<ModelCatalogV1 & RequestIdV1> {
  return fetchV1<ModelCatalogV1 & RequestIdV1>('/api/v1/config/catalogs/models');
}

// ── launch protocol (gui_refresh task 06 Wave 4e — plan 06 §Launch
// protocol, MN-10 backend) ──────────────────────────────────────────────

/**
 * New-run resolved-manifest preview for one draft (plan 05): the effective
 * config + digest a launch of this draft would materialize. `run_id`
 * carries the DRAFT id — no run exists yet.
 */
export function resolveDraftConfigV1(
  draftId: string,
  profile?: LaunchProfileV1,
): Promise<ResolvedNewRunConfigV1 & RequestIdV1> {
  return sendV1<ResolvedNewRunConfigV1 & RequestIdV1>(
    `/api/v1/run-drafts/${encodeURIComponent(draftId)}/resolve-config`,
    { method: 'POST', json: profile === undefined ? {} : { profile } },
  );
}

/**
 * Draft validation distilled from the same resolution run: `errors` are the
 * draft-attributable rejections (strict), `warnings` the manifest warnings.
 */
export function validateRunDraftV1(
  draftId: string,
  profile?: LaunchProfileV1,
): Promise<DraftValidationV1 & RequestIdV1> {
  return sendV1<DraftValidationV1 & RequestIdV1>(
    `/api/v1/run-drafts/${encodeURIComponent(draftId)}/validate`,
    { method: 'POST', json: profile === undefined ? {} : { profile } },
  );
}

/**
 * The canonical idempotent launch (MN-10): validation-first POST that
 * returns the server-issued `run_id` + status URL before any slow work.
 * A duplicate `idempotency_key` replays the SAME run_id and spawns
 * nothing (double-click safety); a 400 'invalid_request' carries the
 * per-path launch errors (incl. missing_goal / mode_locked) in
 * details.errors.
 */
export function launchRunV1(request: {
  draftId: string;
  displayName?: string;
  profile?: LaunchProfileV1;
  idempotencyKey?: string;
}): Promise<RunLaunchedV1 & RequestIdV1> {
  const json: Record<string, unknown> = { draft_id: request.draftId };
  if (request.displayName !== undefined) json.display_name = request.displayName;
  if (request.profile !== undefined) json.profile = request.profile;
  if (request.idempotencyKey !== undefined) json.idempotency_key = request.idempotencyKey;
  return sendV1<RunLaunchedV1 & RequestIdV1>('/api/v1/runs', {
    method: 'POST',
    json,
  });
}

/** Resolved effective-config manifest of an existing run (plan 05). */
export function fetchRunResolvedConfigV1(
  runId: string,
): Promise<ResolvedConfigV1 & RequestIdV1> {
  return fetchV1<ResolvedConfigV1 & RequestIdV1>(
    `/api/v1/runs/${encodeURIComponent(runId)}/resolved-config`,
  );
}

// ── RQGM governance read models (gui_refresh Wave 4a, plan 08) ──────────
//
// Read-only: the whole GUI v1 RQGM surface is GET-only (no governance
// mutation endpoint exists in v1 — plan 08 §Non-goals).

function rqgmPath(runId: string, tail: string): string {
  return `/api/v1/runs/${encodeURIComponent(runId)}/rqgm/${tail}`;
}

/** RQGM capability detection (absence of artifacts == simple_bfts run). */
export function fetchRqgmCapabilitiesV1(
  runId: string,
): Promise<RqgmCapabilitiesV1 & RequestIdV1> {
  return fetchV1<RqgmCapabilitiesV1 & RequestIdV1>(rqgmPath(runId, 'capabilities'));
}

/** Bounded governance overview (committed-replay state + integrity flags). */
export function fetchRqgmOverviewV1(
  runId: string,
): Promise<RqgmOverviewV1 & RequestIdV1> {
  return fetchV1<RqgmOverviewV1 & RequestIdV1>(rqgmPath(runId, 'overview'));
}

/** Registry read model (committed replay; rollup used for `verified` only). */
export function fetchRqgmRegistryV1(
  runId: string,
): Promise<RqgmRegistryV1 & RequestIdV1> {
  return fetchV1<RqgmRegistryV1 & RequestIdV1>(rqgmPath(runId, 'registry'));
}

export interface RqgmAuditQuery {
  cursor?: number;
  limit?: number;
  recordType?: string;
  epoch?: string;
}

/** Cursor-paged audit log (stable byte-offset cursor — plan 08 §Audit). */
export function fetchRqgmAuditV1(
  runId: string,
  query: RqgmAuditQuery = {},
): Promise<RqgmAuditPageV1 & RequestIdV1> {
  const params = new URLSearchParams();
  if (query.cursor !== undefined) params.set('cursor', String(query.cursor));
  if (query.limit !== undefined) params.set('limit', String(query.limit));
  if (query.recordType) params.set('record_type', query.recordType);
  if (query.epoch) params.set('epoch', query.epoch);
  const qs = params.toString();
  return fetchV1<RqgmAuditPageV1 & RequestIdV1>(
    rqgmPath(runId, qs === '' ? 'audit' : `audit?${qs}`),
  );
}

/** Two-channel score lineage of one node (penalty vs policy — never merged). */
export function fetchRqgmNodeLineageV1(
  runId: string,
  nodeId: string,
): Promise<RqgmNodeLineageV1 & RequestIdV1> {
  return fetchV1<RqgmNodeLineageV1 & RequestIdV1>(
    rqgmPath(runId, `nodes/${encodeURIComponent(nodeId)}/lineage`),
  );
}

/** Epoch-boundary score rewrites (T20 supersession + erasure/rebuild). */
export function fetchRqgmScoreRewritesV1(
  runId: string,
  query: { cursor?: number; limit?: number } = {},
): Promise<RqgmScoreRewritesPageV1 & RequestIdV1> {
  const params = new URLSearchParams();
  if (query.cursor !== undefined) params.set('cursor', String(query.cursor));
  if (query.limit !== undefined) params.set('limit', String(query.limit));
  const qs = params.toString();
  return fetchV1<RqgmScoreRewritesPageV1 & RequestIdV1>(
    rqgmPath(runId, qs === '' ? 'score-rewrites' : `score-rewrites?${qs}`),
  );
}

/** Governed epoch utility policies (write-once bodies, hash-verified). */
export function fetchRqgmPoliciesV1(
  runId: string,
): Promise<RqgmPoliciesV1 & RequestIdV1> {
  return fetchV1<RqgmPoliciesV1 & RequestIdV1>(rqgmPath(runId, 'policies'));
}

// ── RQGM Wave 4b read models (plan 08 §Epoch Timeline / §Evolution and
// Frontier Repair / §Paper Archive — still GET-only) ────────────────────

/** Committed epochs from transitions replay (each with its policy hash). */
export function fetchRqgmEpochsV1(
  runId: string,
): Promise<RqgmEpochsV1 & RequestIdV1> {
  return fetchV1<RqgmEpochsV1 & RequestIdV1>(rqgmPath(runId, 'epochs'));
}

/** One epoch's committed detail (policy body, boundary transactions). */
export function fetchRqgmEpochDetailV1(
  runId: string,
  epochId: string,
): Promise<RqgmEpochDetailV1 & RequestIdV1> {
  return fetchV1<RqgmEpochDetailV1 & RequestIdV1>(
    rqgmPath(runId, `epochs/${encodeURIComponent(epochId)}`),
  );
}

/** Evolution lineage (raw candidates vs adopted — never conflated). */
export function fetchRqgmEvolutionV1(
  runId: string,
): Promise<RqgmEvolutionV1 & RequestIdV1> {
  return fetchV1<RqgmEvolutionV1 & RequestIdV1>(rqgmPath(runId, 'evolution'));
}

/** Paper-archive summary (bounded scalars with explicit absent flags). */
export function fetchRqgmPaperArchiveV1(
  runId: string,
): Promise<RqgmPaperArchiveV1 & RequestIdV1> {
  return fetchV1<RqgmPaperArchiveV1 & RequestIdV1>(rqgmPath(runId, 'paper-archive'));
}
