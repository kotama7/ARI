// ARI Dashboard – react-query hooks for the typed /api/v1 client
// (gui_refresh Wave 2b). State ownership is split by kind: server state is
// cached and invalidated here, view state is local and ephemeral, and
// navigation state lives in the URL — no piece of state has two owners
// (docs/concepts/gui_architecture.md, "4. Server state lives in a cache,
// keyed by run").
//
// The client contract these hooks sit on: no hook calls fetch. Every read
// goes through a fetcher in services/api/v1.ts over the shared v1Get/v1Send
// transport, which resolves with the PARSED BODY even on a non-2xx status —
// the throwing get/post regime would discard the body with the status, and
// on /api/v1 that body IS the typed error envelope. The fetcher then
// normalizes every failure — typed envelope, network rejection, malformed
// body — into one ApiErrorV1 {code, message, details, request_id,
// retryable}, which is why every hook below is typed on that single error
// type and a caller can branch on the frozen `code` and quote `request_id`
// instead of parsing `message`
// (docs/reference/rest_api.md, "Error envelope").
//
// Query keys are ['v1', projectId?, runId?, resource] with any filter that
// narrows the resource appended — the project/run id sits INSIDE the key, so
// run-scoped entries
// are isolated per run (switching runs can never bleed a previous run's
// cached delta into the current UI) and `queryClient.invalidateQueries({
// queryKey: ['v1', runId] })` drops exactly one run's server state.
//
// No page consumes these yet — Wave 2b lands the platform seam only; the
// Slice stage adopts them per feature.

import {
  useInfiniteQuery,
  useQuery,
  type InfiniteData,
  type UseInfiniteQueryResult,
  type UseQueryResult,
} from '@tanstack/react-query';
import {
  fetchConfigSchemaV1,
  fetchModelCatalogV1,
  fetchProjectConfigV1,
  fetchProjectsV1,
  fetchRqgmAuditV1,
  fetchRqgmCapabilitiesV1,
  fetchRqgmEpochDetailV1,
  fetchRqgmEpochsV1,
  fetchRqgmEvolutionV1,
  fetchRqgmNodeLineageV1,
  fetchRqgmOverviewV1,
  fetchRqgmPaperArchiveV1,
  fetchRqgmPoliciesV1,
  fetchRqgmRegistryV1,
  fetchRqgmScoreRewritesV1,
  fetchRunDraftV1,
  fetchRunEarV1,
  fetchRunIdeaV1,
  fetchRunResolvedConfigV1,
  fetchRunResultsV1,
  fetchRunsV1,
  fetchRunTemplatesV1,
  fetchRunTemplateV1,
  fetchRunV1,
  fetchRunSummaryV1,
  fetchRunTreeV1,
  fetchSecretsStatusV1,
  type ApiErrorV1,
  type ConfigSchemaV1,
  type ModelCatalogV1,
  type ProjectConfigV1,
  type ProjectListV1,
  type RequestIdV1,
  type ResolvedConfigV1,
  type RqgmAuditPageV1,
  type RqgmCapabilitiesV1,
  type RqgmEpochDetailV1,
  type RqgmEpochsV1,
  type RqgmEvolutionV1,
  type RqgmNodeLineageV1,
  type RqgmOverviewV1,
  type RqgmPaperArchiveV1,
  type RqgmPoliciesV1,
  type RqgmRegistryV1,
  type RqgmScoreRewritesPageV1,
  type RunDetailV1,
  type RunDraftV1,
  type RunEarV1,
  type RunIdeaV1,
  type RunListV1,
  type RunResultsV1,
  type RunSummaryV1,
  type RunTemplateListV1,
  type RunTemplateV1,
  type SecretStatusV1,
  type TreeV1,
} from '../services/api/v1';

// ── query-key factory (single source for hooks and invalidation) ────────

export const v1Keys = {
  /** All /api/v1 server state (root for a blanket invalidation). */
  all: ['v1'] as const,
  /** Global project listing — no project/run scope. */
  projects: () => ['v1', 'projects'] as const,
  /** Runs of one project — projectId inside the key (run isolation). */
  runs: (projectId: string) => ['v1', projectId, 'runs'] as const,
  /** One run's detail — runId inside the key. */
  run: (runId: string) => ['v1', runId, 'run'] as const,
  /** One run's summary card — runId inside the key. */
  runSummary: (runId: string) => ['v1', runId, 'summary'] as const,
  /** One run's node tree — runId inside the key. */
  runTree: (runId: string) => ['v1', runId, 'tree'] as const,
  /** One run's idea.json read model — runId inside the key (Wave 4c). */
  runIdea: (runId: string) => ['v1', runId, 'idea'] as const,
  /** One run's bounded results read model — runId inside the key (Wave 4d). */
  runResults: (runId: string) => ['v1', runId, 'results'] as const,
  /** One run's EAR listing/lineage read model — runId inside the key (Wave 4d). */
  runEar: (runId: string) => ['v1', runId, 'ear'] as const,
  /** Canonical config-field registry — global, no project/run scope. */
  configSchema: () => ['v1', 'config-schema'] as const,
  /** One run's resolved effective-config manifest — runId inside the key. */
  runResolvedConfig: (runId: string) => ['v1', runId, 'resolved-config'] as const,
  // ── Configuration Studio (gui_refresh task 06 Wave 4d) ────────────────
  /** The project config document — projectId inside the key (ADR-08: 'default'). */
  projectConfig: (projectId: string) => ['v1', projectId, 'project-config'] as const,
  /** Run-template listing — global. */
  runTemplates: () => ['v1', 'run-templates'] as const,
  /** One run template — templateId inside the key. */
  runTemplate: (templateId: string) => ['v1', 'run-templates', templateId] as const,
  /** One run draft — draftId inside the key. */
  runDraft: (draftId: string) => ['v1', 'run-drafts', draftId] as const,
  /** Secret readiness (ADR-11) — global, values structurally absent. */
  secretsStatus: () => ['v1', 'secrets-status'] as const,
  /** Server-side model/provider catalog — global static suggestions. */
  modelCatalog: () => ['v1', 'model-catalog'] as const,
  /** Every RQGM read-model entry of one run (blanket rqgm invalidation). */
  rqgm: (runId: string) => ['v1', runId, 'rqgm'] as const,
  rqgmCapabilities: (runId: string) => ['v1', runId, 'rqgm', 'capabilities'] as const,
  rqgmOverview: (runId: string) => ['v1', runId, 'rqgm', 'overview'] as const,
  rqgmRegistry: (runId: string) => ['v1', runId, 'rqgm', 'registry'] as const,
  rqgmPolicies: (runId: string) => ['v1', runId, 'rqgm', 'policies'] as const,
  rqgmScoreRewrites: (runId: string) =>
    ['v1', runId, 'rqgm', 'score-rewrites'] as const,
  rqgmNodeLineage: (runId: string, nodeId: string) =>
    ['v1', runId, 'rqgm', 'lineage', nodeId] as const,
  rqgmEpochs: (runId: string) => ['v1', runId, 'rqgm', 'epochs'] as const,
  rqgmEpochDetail: (runId: string, epochId: string) =>
    ['v1', runId, 'rqgm', 'epochs', epochId] as const,
  rqgmEvolution: (runId: string) => ['v1', runId, 'rqgm', 'evolution'] as const,
  rqgmPaperArchive: (runId: string) =>
    ['v1', runId, 'rqgm', 'paper-archive'] as const,
  /** Filters inside the key: changing a filter starts a fresh page chain. */
  rqgmAudit: (runId: string, recordType: string, epoch: string) =>
    ['v1', runId, 'rqgm', 'audit', recordType, epoch] as const,
};

// ── hooks ───────────────────────────────────────────────────────────────

export function useProjectsV1(): UseQueryResult<ProjectListV1 & RequestIdV1, ApiErrorV1> {
  return useQuery<ProjectListV1 & RequestIdV1, ApiErrorV1>({
    queryKey: v1Keys.projects(),
    queryFn: () => fetchProjectsV1(),
  });
}

export function useRunsV1(projectId: string): UseQueryResult<RunListV1 & RequestIdV1, ApiErrorV1> {
  return useQuery<RunListV1 & RequestIdV1, ApiErrorV1>({
    queryKey: v1Keys.runs(projectId),
    queryFn: () => fetchRunsV1(projectId),
    enabled: projectId !== '',
  });
}

export function useRunV1(runId: string): UseQueryResult<RunDetailV1 & RequestIdV1, ApiErrorV1> {
  return useQuery<RunDetailV1 & RequestIdV1, ApiErrorV1>({
    queryKey: v1Keys.run(runId),
    queryFn: () => fetchRunV1(runId),
    enabled: runId !== '',
  });
}

export function useRunSummaryV1(
  runId: string,
): UseQueryResult<RunSummaryV1 & RequestIdV1, ApiErrorV1> {
  return useQuery<RunSummaryV1 & RequestIdV1, ApiErrorV1>({
    queryKey: v1Keys.runSummary(runId),
    queryFn: () => fetchRunSummaryV1(runId),
    enabled: runId !== '',
  });
}

export function useRunTreeV1(runId: string): UseQueryResult<TreeV1 & RequestIdV1, ApiErrorV1> {
  return useQuery<TreeV1 & RequestIdV1, ApiErrorV1>({
    queryKey: v1Keys.runTree(runId),
    queryFn: () => fetchRunTreeV1(runId),
    enabled: runId !== '',
  });
}

/** One run's idea.json read model (gui_refresh Wave 4c — Ideas v2). */
export function useRunIdeaV1(runId: string): UseQueryResult<RunIdeaV1 & RequestIdV1, ApiErrorV1> {
  return useQuery<RunIdeaV1 & RequestIdV1, ApiErrorV1>({
    queryKey: v1Keys.runIdea(runId),
    queryFn: () => fetchRunIdeaV1(runId),
    enabled: runId !== '',
  });
}

/** One run's bounded results read model (gui_refresh Wave 4d — Results v2). */
export function useRunResultsV1(
  runId: string,
): UseQueryResult<RunResultsV1 & RequestIdV1, ApiErrorV1> {
  return useQuery<RunResultsV1 & RequestIdV1, ApiErrorV1>({
    queryKey: v1Keys.runResults(runId),
    queryFn: () => fetchRunResultsV1(runId),
    enabled: runId !== '',
  });
}

/** One run's EAR listing/lineage read model (gui_refresh Wave 4d). */
export function useRunEarV1(
  runId: string,
): UseQueryResult<RunEarV1 & RequestIdV1, ApiErrorV1> {
  return useQuery<RunEarV1 & RequestIdV1, ApiErrorV1>({
    queryKey: v1Keys.runEar(runId),
    queryFn: () => fetchRunEarV1(runId),
    enabled: runId !== '',
  });
}

export function useConfigSchemaV1(): UseQueryResult<ConfigSchemaV1 & RequestIdV1, ApiErrorV1> {
  return useQuery<ConfigSchemaV1 & RequestIdV1, ApiErrorV1>({
    queryKey: v1Keys.configSchema(),
    queryFn: () => fetchConfigSchemaV1(),
  });
}

export function useRunResolvedConfigV1(
  runId: string,
): UseQueryResult<ResolvedConfigV1 & RequestIdV1, ApiErrorV1> {
  return useQuery<ResolvedConfigV1 & RequestIdV1, ApiErrorV1>({
    queryKey: v1Keys.runResolvedConfig(runId),
    queryFn: () => fetchRunResolvedConfigV1(runId),
    enabled: runId !== '',
  });
}

// ── Configuration Studio hooks (gui_refresh task 06 Wave 4d) ────────────
//
// Read side only — mutations (PATCH with If-Match, the write-only secret
// PUT) are dispatched imperatively by the Studio page, which then
// invalidates these keys so every consumer refetches the new revision.

/** The single default project's config document (revision 0 when unsaved). */
export function useProjectConfigV1(
  projectId = 'default',
): UseQueryResult<ProjectConfigV1 & RequestIdV1, ApiErrorV1> {
  return useQuery<ProjectConfigV1 & RequestIdV1, ApiErrorV1>({
    queryKey: v1Keys.projectConfig(projectId),
    queryFn: () => fetchProjectConfigV1(projectId),
  });
}

export function useRunTemplatesV1(): UseQueryResult<
  RunTemplateListV1 & RequestIdV1,
  ApiErrorV1
> {
  return useQuery<RunTemplateListV1 & RequestIdV1, ApiErrorV1>({
    queryKey: v1Keys.runTemplates(),
    queryFn: () => fetchRunTemplatesV1(),
  });
}

export function useRunTemplateV1(
  templateId: string,
): UseQueryResult<RunTemplateV1 & RequestIdV1, ApiErrorV1> {
  return useQuery<RunTemplateV1 & RequestIdV1, ApiErrorV1>({
    queryKey: v1Keys.runTemplate(templateId),
    queryFn: () => fetchRunTemplateV1(templateId),
    enabled: templateId !== '',
  });
}

export function useRunDraftV1(
  draftId: string,
): UseQueryResult<RunDraftV1 & RequestIdV1, ApiErrorV1> {
  return useQuery<RunDraftV1 & RequestIdV1, ApiErrorV1>({
    queryKey: v1Keys.runDraft(draftId),
    queryFn: () => fetchRunDraftV1(draftId),
    enabled: draftId !== '',
  });
}

/** Secret readiness (ADR-11 — configured/source only, never a value). */
export function useSecretsStatusV1(): UseQueryResult<
  SecretStatusV1 & RequestIdV1,
  ApiErrorV1
> {
  return useQuery<SecretStatusV1 & RequestIdV1, ApiErrorV1>({
    queryKey: v1Keys.secretsStatus(),
    queryFn: () => fetchSecretsStatusV1(),
  });
}

/** Server-side model/provider catalog: the choices a control offers come from
 * the server's metadata, never from a frontend constant, so adding a model
 * needs no frontend change. */
export function useModelCatalogV1(): UseQueryResult<
  ModelCatalogV1 & RequestIdV1,
  ApiErrorV1
> {
  return useQuery<ModelCatalogV1 & RequestIdV1, ApiErrorV1>({
    queryKey: v1Keys.modelCatalog(),
    queryFn: () => fetchModelCatalogV1(),
  });
}

// ── RQGM governance hooks (gui_refresh Wave 4a) — read-only by contract:
//    there is NO mutation endpoint on this surface, so the GUI can observe
//    governance but never perform it. ─────────────────────────────────────

export function useRqgmCapabilitiesV1(
  runId: string,
): UseQueryResult<RqgmCapabilitiesV1 & RequestIdV1, ApiErrorV1> {
  return useQuery<RqgmCapabilitiesV1 & RequestIdV1, ApiErrorV1>({
    queryKey: v1Keys.rqgmCapabilities(runId),
    queryFn: () => fetchRqgmCapabilitiesV1(runId),
    enabled: runId !== '',
  });
}

export function useRqgmOverviewV1(
  runId: string,
  enabled: boolean,
): UseQueryResult<RqgmOverviewV1 & RequestIdV1, ApiErrorV1> {
  return useQuery<RqgmOverviewV1 & RequestIdV1, ApiErrorV1>({
    queryKey: v1Keys.rqgmOverview(runId),
    queryFn: () => fetchRqgmOverviewV1(runId),
    enabled: runId !== '' && enabled,
  });
}

export function useRqgmRegistryV1(
  runId: string,
  enabled: boolean,
): UseQueryResult<RqgmRegistryV1 & RequestIdV1, ApiErrorV1> {
  return useQuery<RqgmRegistryV1 & RequestIdV1, ApiErrorV1>({
    queryKey: v1Keys.rqgmRegistry(runId),
    queryFn: () => fetchRqgmRegistryV1(runId),
    enabled: runId !== '' && enabled,
  });
}

export function useRqgmPoliciesV1(
  runId: string,
  enabled: boolean,
): UseQueryResult<RqgmPoliciesV1 & RequestIdV1, ApiErrorV1> {
  return useQuery<RqgmPoliciesV1 & RequestIdV1, ApiErrorV1>({
    queryKey: v1Keys.rqgmPolicies(runId),
    queryFn: () => fetchRqgmPoliciesV1(runId),
    enabled: runId !== '' && enabled,
  });
}

export function useRqgmScoreRewritesV1(
  runId: string,
  enabled: boolean,
): UseQueryResult<RqgmScoreRewritesPageV1 & RequestIdV1, ApiErrorV1> {
  return useQuery<RqgmScoreRewritesPageV1 & RequestIdV1, ApiErrorV1>({
    queryKey: v1Keys.rqgmScoreRewrites(runId),
    queryFn: () => fetchRqgmScoreRewritesV1(runId, { limit: 100 }),
    enabled: runId !== '' && enabled,
  });
}

export function useRqgmNodeLineageV1(
  runId: string,
  nodeId: string,
): UseQueryResult<RqgmNodeLineageV1 & RequestIdV1, ApiErrorV1> {
  return useQuery<RqgmNodeLineageV1 & RequestIdV1, ApiErrorV1>({
    queryKey: v1Keys.rqgmNodeLineage(runId, nodeId),
    queryFn: () => fetchRqgmNodeLineageV1(runId, nodeId),
    enabled: runId !== '' && nodeId !== '',
  });
}

// ── RQGM Wave 4b hooks — epochs / evolution / paper archive, read-only ──

export function useRqgmEpochsV1(
  runId: string,
  enabled: boolean,
): UseQueryResult<RqgmEpochsV1 & RequestIdV1, ApiErrorV1> {
  return useQuery<RqgmEpochsV1 & RequestIdV1, ApiErrorV1>({
    queryKey: v1Keys.rqgmEpochs(runId),
    queryFn: () => fetchRqgmEpochsV1(runId),
    enabled: runId !== '' && enabled,
  });
}

export function useRqgmEpochDetailV1(
  runId: string,
  epochId: string,
): UseQueryResult<RqgmEpochDetailV1 & RequestIdV1, ApiErrorV1> {
  return useQuery<RqgmEpochDetailV1 & RequestIdV1, ApiErrorV1>({
    queryKey: v1Keys.rqgmEpochDetail(runId, epochId),
    queryFn: () => fetchRqgmEpochDetailV1(runId, epochId),
    enabled: runId !== '' && epochId !== '',
  });
}

export function useRqgmEvolutionV1(
  runId: string,
  enabled: boolean,
): UseQueryResult<RqgmEvolutionV1 & RequestIdV1, ApiErrorV1> {
  return useQuery<RqgmEvolutionV1 & RequestIdV1, ApiErrorV1>({
    queryKey: v1Keys.rqgmEvolution(runId),
    queryFn: () => fetchRqgmEvolutionV1(runId),
    enabled: runId !== '' && enabled,
  });
}

export function useRqgmPaperArchiveV1(
  runId: string,
  enabled: boolean,
): UseQueryResult<RqgmPaperArchiveV1 & RequestIdV1, ApiErrorV1> {
  return useQuery<RqgmPaperArchiveV1 & RequestIdV1, ApiErrorV1>({
    queryKey: v1Keys.rqgmPaperArchive(runId),
    queryFn: () => fetchRqgmPaperArchiveV1(runId),
    enabled: runId !== '' && enabled,
  });
}

export type RqgmAuditInfiniteData = InfiniteData<
  RqgmAuditPageV1 & RequestIdV1,
  number
>;

/**
 * Cursor-paged audit log ("load more" appends).
 *
 * The page param is the backend's stable byte-offset cursor: page N+1 asks
 * for `next_cursor` of page N (entries with `byte_offset >= cursor`), so
 * appended pages can never duplicate rows of an append-only log. Filters
 * live inside the query key — changing one starts a fresh page chain.
 */
export function useRqgmAuditV1(
  runId: string,
  filters: { recordType: string; epoch: string },
  enabled: boolean,
): UseInfiniteQueryResult<RqgmAuditInfiniteData, ApiErrorV1> {
  return useInfiniteQuery<
    RqgmAuditPageV1 & RequestIdV1,
    ApiErrorV1,
    RqgmAuditInfiniteData,
    ReturnType<typeof v1Keys.rqgmAudit>,
    number
  >({
    queryKey: v1Keys.rqgmAudit(runId, filters.recordType, filters.epoch),
    queryFn: ({ pageParam }) =>
      fetchRqgmAuditV1(runId, {
        cursor: pageParam,
        recordType: filters.recordType || undefined,
        epoch: filters.epoch || undefined,
      }),
    initialPageParam: 0,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    enabled: runId !== '' && enabled,
  });
}
