// ARI Dashboard – v2 Results/EAR workspace (gui_refresh task 07 Wave 4d).
// The route exists in exactly one place — its ROUTE_REGISTRY entry, which
// the router and the sidebar are both derived from — and like every v2
// workspace it is run-explicit: what it renders is a function of the URL
// alone, never of a process-wide active checkpoint
// (docs/guides/dashboard.md, "Run-explicit URLs and deep links").
//
// READ-ONLY. Run-explicit result summary over the typed v1 endpoints:
// GET /api/v1/runs/{run_id}/results (bounded paper/review/ORS/EAR scalars)
// and GET /api/v1/runs/{run_id}/ear (listing metadata + publish lineage
// digests). The legacy #/results page keeps running unchanged in parallel
// (parity invariant) and REMAINS the full editor/PDF workspace and the only
// place EAR mutations (curate / publish.yaml editing / publish / promote)
// fire — this page renders the lineage as a read-only badge chain and sends
// the user to the legacy page for any mutation. The migration runs
// read-first: a v2 workspace ships read-only beside its legacy counterpart
// and links out for writes until it can own them outright — it never forks
// a write path (TODO Wave 5: embed the paper workspace here).
//
// Sections:
//   - Result summary: review scores (rubric dimensions or the legacy
//     abstract/body/overall trio) + the ORS reproducibility verdict chip
//     with per-stage chain provenance (rubric → replicator → phase1 →
//     judge grade — the OrsChainSection lineage, re-sourced run-explicitly).
//   - EAR / publication lineage: curate → preview → publish → promote as a
//     read-only badge chain (traceability terminus: the chain ends at the
//     published bundle's digest, which is what a reader checks the
//     checkpoint contents against), bundle sha256 + visibility +
//     bounded file listing from the /ear read model.
//   - Deep links: Tree v2, Config, and (when the run's rqgm capability is
//     on) Governance; legacy #/results for the full workspace.
//
// Run scoping: reads `?run=` from the hash query (#/results2?run=<id> — the
// ConfigBrowser/TreeV2/IdeasV2 pattern). No write path exists on this page.

import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { useT } from '../../i18n';
import { useRunEarV1, useRunResultsV1, useRunV1 } from '../../hooks/useV1';
import {
  Badge,
  Card,
  DegradedState,
  EmptyState,
  ErrorState,
  LoadingState,
} from '../common';
import type {
  ApiErrorV1,
  ResultEarV1,
  ResultOrsV1,
  ResultPaperV1,
  ResultReviewV1,
} from '../../services/api/v1';

type BadgeVariant = 'green' | 'red' | 'blue' | 'yellow' | 'muted';

// Wire-optional blocks normalized to explicit absence (the backend always
// emits them; the generated types keep sub-models optional).
const EMPTY_PAPER: ResultPaperV1 = { pdf_present: false, tex_present: false };
const EMPTY_REVIEW: ResultReviewV1 = {
  report_present: false,
  overall_score: null,
  abstract_score: null,
  body_score: null,
  decision: null,
  confidence: null,
  rubric_id: null,
  dimensions: [],
};
const EMPTY_ORS: ResultOrsV1 = {
  chain_present: false,
  rubric_present: false,
  replicator_present: false,
  seed_present: false,
  phase1_present: false,
  grade_present: false,
  verdict: null,
  summary: null,
  ors_score: null,
  raw_score: null,
  passed_leaves: null,
  total_leaves: null,
  judge_model: null,
};
const EMPTY_EAR: ResultEarV1 = {
  present: false,
  curated: false,
  published: false,
  visibility: null,
  visibility_source: null,
  dry_run: null,
  promoted_at: null,
};

// ── hash query helper (#/results2?run=<id>) ─────────────────────────────

/** `run` query param of the current hash; '' when absent. */
function runFromHash(): string {
  const query = window.location.hash.split('?')[1] ?? '';
  return new URLSearchParams(query).get('run') ?? '';
}

// ── semantic maps (frozen vocabularies pick colors only; unknown tokens
// render muted verbatim — never remapped) ───────────────────────────────

/** Review decision → badge variant (ReviewScoresSection vocabulary). */
const DECISION_VARIANT: Record<string, BadgeVariant> = {
  accept: 'green',
  weak_accept: 'green',
  borderline: 'yellow',
  weak_reject: 'red',
  reject: 'red',
};

/** ORS synthesized verdict → badge variant (ear.py synthesis vocabulary). */
const VERDICT_VARIANT: Record<string, BadgeVariant> = {
  REPRODUCED: 'green',
  PARTIAL: 'yellow',
  NOT_REPRODUCED: 'red',
  ENVIRONMENT_MISMATCH: 'yellow',
  FAILED: 'red',
  PENDING: 'muted',
};

// ── EAR lineage derivation (exported for the page test) ─────────────────

export type EarStageState = 'done' | 'available' | 'pending';

export interface EarLineage {
  curate: EarStageState;
  preview: EarStageState;
  publish: EarStageState;
  promote: EarStageState;
  dryRun: boolean;
}

/**
 * Derive the read-only curate → preview → publish → promote chain from the
 * results EAR block. Facts only:
 *   - curate  'done' = manifest.lock exists; 'available' = an ear/ dir
 *     exists to curate; else 'pending'.
 *   - preview has no artifact of its own (it is an ephemeral inspection of
 *     the curated bundle), so it is 'available' once curated — never 'done'.
 *   - publish 'done' = publish_record.json exists (dry-run flagged aside).
 *   - promote 'done' = promoted_at recorded; 'available' once published.
 */
export function deriveEarLineage(ear: ResultEarV1): EarLineage {
  const curate: EarStageState = ear.curated
    ? 'done'
    : ear.present
      ? 'available'
      : 'pending';
  return {
    curate,
    preview: ear.curated ? 'available' : 'pending',
    publish: ear.published ? 'done' : ear.curated ? 'available' : 'pending',
    promote:
      ear.promoted_at != null && ear.promoted_at !== ''
        ? 'done'
        : ear.published
          ? 'available'
          : 'pending',
    dryRun: ear.dry_run === true,
  };
}

const STAGE_VARIANT: Record<EarStageState, BadgeVariant> = {
  done: 'green',
  available: 'blue',
  pending: 'muted',
};

/** First 12 hex of a bundle digest for chip display (full value in title). */
export function shortDigest(sha256: string | null | undefined): string | null {
  if (typeof sha256 !== 'string' || sha256 === '') return null;
  return sha256.length > 12 ? sha256.slice(0, 12) : sha256;
}

/** err.message plus the envelope's request_id — every /api/v1 response
 * carries that id precisely so a user can quote it in a bug report, so it is
 * surfaced rather than swallowed. */
function errorText(err: ApiErrorV1, requestIdLabel: string): string {
  const rid = err.request_id ? ` (${requestIdLabel}: ${err.request_id})` : '';
  return `${err.message}${rid}`;
}

// ── building blocks ─────────────────────────────────────────────────────

function MutedLine({ children }: { children: ReactNode }) {
  return (
    <p style={{ color: 'var(--text-muted)', fontSize: '.8rem', margin: 0 }}>{children}</p>
  );
}

function ScoreTile({ label, value }: { label: string; value: number | null | undefined }) {
  return (
    <div style={{ minWidth: 110 }}>
      <div style={{ fontSize: '.72rem', color: 'var(--text-muted)', marginBottom: 2 }}>
        {label}
      </div>
      <div style={{ fontSize: '1.3rem', fontWeight: 800 }}>
        {value != null ? String(value) : '—'}
      </div>
    </div>
  );
}

function ChainStageBadge({
  label,
  present,
}: {
  label: string;
  present: boolean;
}) {
  return <Badge variant={present ? 'green' : 'muted'}>{label}</Badge>;
}

/** ORS provenance chips: verdict + score + per-stage presence — a
 * reproducibility verdict is lineage, so it never renders bare; the stages
 * that produced it render beside it, and a missing stage shows as missing. */
function OrsSummary({ ors }: { ors: ResultOrsV1 }) {
  const t = useT();
  if (!ors.chain_present) {
    return <MutedLine>{t('results2_ors_absent')}</MutedLine>;
  }
  return (
    <div data-testid="results2-ors">
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        {ors.verdict != null ? (
          <Badge variant={VERDICT_VARIANT[ors.verdict] ?? 'muted'}>{ors.verdict}</Badge>
        ) : (
          <Badge variant="muted">{t('results2_ors_no_verdict')}</Badge>
        )}
        {ors.ors_score != null && (
          <span style={{ fontSize: '.95rem', fontWeight: 700 }}>
            {(ors.ors_score * 100).toFixed(1)}%
          </span>
        )}
        {ors.passed_leaves != null && ors.total_leaves != null && (
          <span style={{ fontSize: '.78rem', color: 'var(--text-muted)' }}>
            {ors.passed_leaves} / {ors.total_leaves} {t('results2_ors_leaves')}
          </span>
        )}
      </div>
      {ors.summary != null && (
        <div style={{ fontSize: '.8rem', color: 'var(--text-muted)', marginTop: 6 }}>
          {ors.summary}
        </div>
      )}
      <div
        style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}
        data-testid="results2-ors-chain"
      >
        <ChainStageBadge label={t('results2_ors_stage_rubric')} present={ors.rubric_present} />
        <ChainStageBadge
          label={t('results2_ors_stage_replicator')}
          present={ors.replicator_present}
        />
        <ChainStageBadge label={t('results2_ors_stage_phase1')} present={ors.phase1_present} />
        <ChainStageBadge label={t('results2_ors_stage_grade')} present={ors.grade_present} />
      </div>
      {ors.judge_model != null && (
        <div style={{ fontSize: '.72rem', color: 'var(--text-muted)', marginTop: 6 }}>
          {t('results2_ors_judge')}: <code>{ors.judge_model}</code>
        </div>
      )}
    </div>
  );
}

/** EAR lineage badge chain + digest scalars — strictly read-only; every
 * mutation (curate/publish/promote/publish.yaml edit) lives on the legacy
 * page the link below opens — this workspace fires no mutation at all. */
function EarLineageSection({
  runId,
  ear,
  earQ,
}: {
  runId: string;
  ear: ResultEarV1;
  earQ: ReturnType<typeof useRunEarV1>;
}) {
  const t = useT();
  const lineage = deriveEarLineage(ear);
  const stages: Array<[string, EarStageState]> = [
    [t('results2_ear_stage_curate'), lineage.curate],
    [t('results2_ear_stage_preview'), lineage.preview],
    [t('results2_ear_stage_publish'), lineage.publish],
    [t('results2_ear_stage_promote'), lineage.promote],
  ];
  const detail = earQ.data;
  const curated = detail?.curated;
  const publishRecord = detail?.published;
  const digest = shortDigest(curated?.bundle_sha256 ?? null);

  return (
    <Card title={t('results2_ear_title')}>
      <div data-testid="results2-ear">
        {!ear.present && !ear.curated && !ear.published ? (
          <MutedLine>{t('results2_ear_absent')}</MutedLine>
        ) : (
          <>
            <div
              style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}
              data-testid="results2-ear-chain"
            >
              {stages.map(([label, state], idx) => (
                <span
                  key={label}
                  style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
                >
                  {idx > 0 && (
                    <span style={{ color: 'var(--text-muted)', fontSize: '.8rem' }}>
                      {'→'}
                    </span>
                  )}
                  <Badge variant={STAGE_VARIANT[state]}>
                    {label}
                    {state === 'done' ? ' ✓' : ''}
                  </Badge>
                </span>
              ))}
              {lineage.dryRun && <Badge variant="yellow">{t('results2_ear_dry_run')}</Badge>}
            </div>

            <div
              style={{
                display: 'flex',
                gap: 12,
                flexWrap: 'wrap',
                marginTop: 10,
                fontSize: '.8rem',
              }}
            >
              {ear.visibility != null && (
                <span>
                  {t('results2_ear_visibility')}:{' '}
                  <Badge variant={ear.visibility === 'public' ? 'green' : 'blue'}>
                    {ear.visibility}
                  </Badge>{' '}
                  <span style={{ color: 'var(--text-muted)', fontSize: '.72rem' }}>
                    (
                    {ear.visibility_source === 'publish_record'
                      ? t('results2_ear_vis_from_record')
                      : t('results2_ear_vis_from_manifest')}
                    )
                  </span>
                </span>
              )}
              {ear.promoted_at != null && (
                <span style={{ color: 'var(--text-muted)' }}>
                  {t('results2_ear_promoted_at')}: {ear.promoted_at}
                </span>
              )}
            </div>

            {earQ.isError ? (
              <div style={{ marginTop: 8 }}>
                <MutedLine>{errorText(earQ.error, t('results2_request_id'))}</MutedLine>
              </div>
            ) : (
              detail !== undefined && (
                <div style={{ marginTop: 8, fontSize: '.8rem' }}>
                  {digest !== null && curated !== undefined && (
                    <div>
                      {t('results2_ear_bundle_digest')}:{' '}
                      <code title={curated.bundle_sha256 ?? ''}>
                        sha256:{digest}…
                      </code>
                      {curated.file_count != null && (
                        <span style={{ color: 'var(--text-muted)' }}>
                          {' '}
                          · {curated.file_count} {t('results2_ear_bundle_files')}
                          {curated.excluded_count != null &&
                            curated.excluded_count > 0 &&
                            ` (+${curated.excluded_count} ${t('results2_ear_excluded')})`}
                        </span>
                      )}
                    </div>
                  )}
                  <div style={{ color: 'var(--text-muted)', marginTop: 4 }}>
                    {t('results2_ear_files')}: {detail.file_count}
                    {detail.truncated && ` (${t('results2_ear_truncated')})`}
                    {' · publish.yaml: '}
                    {detail.publish_yaml_present
                      ? t('results2_present')
                      : t('results2_absent_flag')}
                  </div>
                  {publishRecord?.record_present === true &&
                    publishRecord.ref != null && (
                      <div style={{ marginTop: 4 }}>
                        {t('results2_ear_ref')}:{' '}
                        <code style={{ overflowWrap: 'anywhere' }}>
                          {publishRecord.ref}
                        </code>
                      </div>
                    )}
                </div>
              )
            )}
          </>
        )}

        {/* Mutations stay on the legacy page — this workspace fires none. */}
        <div style={{ marginTop: 10 }}>
          <a href={`#/results${runId !== '' ? `?run=${encodeURIComponent(runId)}` : ''}`}>
            {t('results2_ear_manage_link')}
          </a>
          <p style={{ color: 'var(--text-muted)', fontSize: '.72rem', margin: '2px 0 0' }}>
            {t('results2_ear_manage_note')}
          </p>
        </div>
      </div>
    </Card>
  );
}

// ── page ────────────────────────────────────────────────────────────────

export function ResultsV2Page() {
  const t = useT();

  // Route dispatch strips the query string, so the page owns ?run= itself
  // (ConfigBrowser/TreeV2/IdeasV2 pattern — including in-place changes).
  const [runId, setRunId] = useState(runFromHash);
  useEffect(() => {
    const onHashChange = () => setRunId(runFromHash());
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  const resultsQ = useRunResultsV1(runId);
  const earQ = useRunEarV1(runId);
  const runQ = useRunV1(runId);
  const rqgmEnabled = runQ.data?.capabilities?.rqgm === true;

  const degraded = useMemo(
    () => resultsQ.data?.degraded_reasons ?? [],
    [resultsQ.data],
  );

  let body: ReactNode;
  if (runId === '') {
    body = (
      <Card>
        <EmptyState
          icon="📊"
          message={t('results2_no_run')}
          hint={t('results2_no_run_hint')}
        />
      </Card>
    );
  } else if (resultsQ.isPending) {
    body = <LoadingState />;
  } else if (resultsQ.isError) {
    body = (
      <ErrorState
        message={errorText(resultsQ.error, t('results2_request_id'))}
        onRetry={() => void resultsQ.refetch()}
      />
    );
  } else {
    const data = resultsQ.data;
    const paper = data.paper ?? EMPTY_PAPER;
    const review = data.review ?? EMPTY_REVIEW;
    const dimensions = review.dimensions ?? [];
    const hasDimensions = dimensions.length > 0;
    body = (
      <>
        {degraded.length > 0 && (
          <div style={{ marginBottom: 12 }}>
            <DegradedState detail={degraded.join('; ')} />
          </div>
        )}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(min(320px, 100%), 1fr))',
            gap: 16,
            alignItems: 'start',
          }}
        >
          {/* ── Left column: result summary ── */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <Card title={t('results2_summary_title')}>
              <div data-testid="results2-review">
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
                  {paper.tex_present && (
                    <Badge variant="blue">{t('results2_paper_tex')}</Badge>
                  )}
                  {paper.pdf_present && (
                    <Badge variant="blue">{t('results2_paper_pdf')}</Badge>
                  )}
                  {review.decision != null && (
                    <Badge variant={DECISION_VARIANT[review.decision] ?? 'muted'}>
                      {t('results2_review_decision')}: {review.decision}
                    </Badge>
                  )}
                  {review.rubric_id != null && (
                    <Badge variant="muted">
                      {t('results2_review_rubric')}: {review.rubric_id}
                    </Badge>
                  )}
                </div>
                {(paper.pdf_present || paper.tex_present) && (
                  <div
                    style={{
                      display: 'flex',
                      gap: 8,
                      flexWrap: 'wrap',
                      margin: '4px 0 14px',
                    }}
                    data-testid="results2-paper-actions"
                  >
                    <a
                      className="btn btn-primary"
                      href={`#/results?run=${encodeURIComponent(runId)}`}
                    >
                      {t('results2_open_workspace')}
                    </a>
                    {paper.pdf_present && (
                      <a
                        className="btn btn-outline"
                        href={`/api/checkpoint/${encodeURIComponent(runId)}/paper.pdf`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {t('results2_view_pdf')}
                      </a>
                    )}
                  </div>
                )}
                {!review.report_present ? (
                  <MutedLine>{t('results2_review_absent')}</MutedLine>
                ) : (
                  <>
                    <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap' }}>
                      {hasDimensions ? (
                        dimensions.map((d) => (
                          <ScoreTile key={d.name} label={d.name} value={d.value} />
                        ))
                      ) : (
                        <>
                          <ScoreTile
                            label={t('results2_score_abstract')}
                            value={review.abstract_score}
                          />
                          <ScoreTile
                            label={t('results2_score_body')}
                            value={review.body_score}
                          />
                        </>
                      )}
                      <ScoreTile
                        label={t('results2_score_overall')}
                        value={review.overall_score}
                      />
                    </div>
                    {review.confidence != null && (
                      <div style={{ marginTop: 8, fontSize: '.8rem' }}>
                        {t('results2_review_confidence')}: <b>{review.confidence}</b>
                      </div>
                    )}
                  </>
                )}
              </div>
            </Card>

            <Card title={t('results2_ors_title')}>
              <OrsSummary ors={data.ors ?? EMPTY_ORS} />
            </Card>
          </div>

          {/* ── Right column: EAR lineage + deep links ── */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <EarLineageSection runId={runId} ear={data.ear ?? EMPTY_EAR} earQ={earQ} />

            <Card title={t('results2_links_title')}>
              <div
                style={{ display: 'flex', flexDirection: 'column', gap: 6 }}
                data-testid="results2-links"
              >
                <a href={`#/tree2?run=${encodeURIComponent(runId)}`}>
                  {t('results2_link_tree')}
                </a>
                <a href={`#/config?run=${encodeURIComponent(runId)}`}>
                  {t('results2_link_config')}
                </a>
                {rqgmEnabled && (
                  <a href={`#/governance?run=${encodeURIComponent(runId)}`}>
                    {t('results2_link_governance')}
                  </a>
                )}
                <a href={`#/results?run=${encodeURIComponent(runId)}`}>
                  {t('results2_link_legacy')}
                </a>
              </div>
            </Card>
          </div>
        </div>
      </>
    );
  }

  return (
    <div id="page-results2" className="page active">
      <h1 style={{ margin: 0 }}>{t('results2_title')}</h1>
      <p className="subtitle" style={{ margin: '4px 0 8px' }}>
        {t('results2_subtitle')}
      </p>
      {runId !== '' && (
        <p style={{ color: 'var(--text-muted)', fontSize: '.85rem', margin: '0 0 12px' }}>
          {t('results2_run_label')}: <code style={{ fontSize: '.85rem' }}>{runId}</code>
        </p>
      )}
      {body}
    </div>
  );
}
