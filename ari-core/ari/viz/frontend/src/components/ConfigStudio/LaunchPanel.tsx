// ARI Dashboard – Studio launch flow (gui_refresh task 06 Wave 4e; backend
// MN-10 POST /api/v1/runs). The launch order is fixed and each step's output
// is the next step's input: resolve -> validate -> immutable review ->
// idempotent create -> canonical redirect. No step may be skipped, nothing
// spawns before validation, and the run identity always comes back from the
// server rather than being inferred on the client.
//
// The DRAFT-scope extension of the ConfigStudioPage: the full 9-state run
// draft machine narrows to what exists in this slice — draft editing is
// the Studio form above; this panel adds goal -> review -> launch:
//
//   1. [Resolve & validate] — POST resolve-config + validate for the
//      draft (+optional --profile). Renders the effective-config diff vs
//      defaults (ConfigBrowser badge maps + table shape, so the config
//      surfaces cannot drift), the draft-attributable validation errors
//      (ValidationSummary — same details.errors row shape), the resolver
//      warnings verbatim, secret readiness rows (existing status hook —
//      never a value), and the ADR-09 locked-governance note.
//   2. Immutable review — read-only summary (display name, run_id intent
//      'server-issued', profile, RESOLVED execution/paper mode,
//      changed-fields count, digest) behind an explicit confirm checkbox.
//      Checking it mints ONE idempotency key (crypto.randomUUID) per review
//      approval; edits that invalidate the review (profile/display-name/draft
//      revision) clear both.
//   3. [Launch] — enabled only when the draft validated clean, the goal
//      exists, and the review is confirmed. POST /api/v1/runs with the
//      minted key; the button is disabled in flight and a retry after a
//      failure reuses the SAME key (double-click / retry send one spawn).
//      Success redirects to the canonical '#/overview?run=<run_id>' — the
//      server-issued run_id, never mtime/latest-checkpoint polling.
//      Failure renders the typed error envelope (message + request_id +
//      per-path details.errors, incl. missing_goal / mode_locked).
//
// ADR-09 (accepted 2026-07-27): the two mode INTENTS are selected in the
// Studio form above (ExecutionSection.tsx). This panel is where they become
// auditable: the review shows the RESOLVED execution/paper mode read off the
// resolve-config manifest — never the raw selection — because the runtime
// resolver warn-and-falls-back on a mismatched pair. When the manifest says
// the requested mode was NOT honored, a prominent alert names the requested
// value, the resolved value, and the resolver's warning verbatim. The other
// ~96 rqgm.* governance leaves stay locked (mode_locked) and this panel keeps
// explaining that lock.

import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import { useT } from '../../i18n';
import { useSecretsStatusV1 } from '../../hooks/useV1';
import {
  launchRunV1,
  resolveDraftConfigV1,
  toApiError,
  validateRunDraftV1,
  type ApiErrorV1,
  type ConfigFieldV1,
  type DraftValidationV1,
  type LaunchProfileV1,
  type ResolvedNewRunConfigV1,
} from '../../services/api/v1';
import { Badge, Button, Card } from '../common';
import {
  MUTABILITY_VARIANT,
  SOURCE_VARIANT,
  type BadgeVariant,
} from '../ConfigBrowser/ConfigReadOnlyTable';
import {
  MODE_INTENT_LABEL_KEY,
  MODE_INTENT_PAIRS,
  readConfigLeaf,
} from './modeIntents';
import { ValidationSummary, patchErrorsFromDetails } from './ValidationSummary';

// New-run provenance sources beyond the ConfigBrowser map. A new-run
// resolution has more layers than a post-hoc one (profile/project/template/
// draft on top of default/workflow/env), but every leaf still names the layer
// it came from; the ConfigBrowser exports stay the base so badge semantics
// for the shared sources cannot drift between the two screens.
const NEW_RUN_SOURCE_VARIANT: Record<string, BadgeVariant> = {
  ...SOURCE_VARIANT,
  profile: 'blue',
  project: 'green',
  template: 'blue',
  draft: 'yellow',
};

/** Same deterministic value formatting discipline as the ConfigBrowser. */
function formatValue(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'string') return v === '' ? "''" : v;
  if (typeof v === 'number' || typeof v === 'boolean') return String(v);
  if (Array.isArray(v)) return `[${v.map(formatValue).join(', ')}]`;
  if (typeof v === 'object') {
    const entries = Object.entries(v as Record<string, unknown>);
    return `{${entries.map(([k, val]) => `${k}: ${formatValue(val)}`).join(', ')}}`;
  }
  return String(v);
}

function errorText(err: ApiErrorV1, requestIdLabel: string): string {
  const rid = err.request_id ? ` (${requestIdLabel}: ${err.request_id})` : '';
  return `${err.message}${rid}`;
}

const PROFILES: LaunchProfileV1[] = ['laptop', 'hpc', 'cloud'];

interface LaunchPanelProps {
  draftId: string;
  /** The draft's goal (create-time document field) or null. */
  goal: string | null;
  /** Saved draft revision — a save invalidates any resolved preview. */
  revision: number;
  /** Registry fields (defaults for the diff; secret classification). */
  fields: ConfigFieldV1[];
}

export function LaunchPanel({ draftId, goal, revision, fields }: LaunchPanelProps) {
  const t = useT();
  const secretsQ = useSecretsStatusV1();

  const [profile, setProfile] = useState<'' | LaunchProfileV1>('');
  const [displayName, setDisplayName] = useState('');

  // Narrowed state machine: draft -> validating -> ready -> launching ->
  // launched | failed (goal..governance steps are the Studio form itself).
  const [resolving, setResolving] = useState(false);
  const [resolved, setResolved] = useState<ResolvedNewRunConfigV1 | null>(null);
  const [validation, setValidation] = useState<DraftValidationV1 | null>(null);
  const [resolveError, setResolveError] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [launching, setLaunching] = useState(false);
  const [launchError, setLaunchError] = useState<ApiErrorV1 | null>(null);
  // ONE idempotency key per review approval: one approval may spawn at most
  // one run, so a double-click and a retry after a failure replay the same
  // key and the server returns the same run_id instead of spawning again.
  const keyRef = useRef<string | null>(null);
  const inFlightRef = useRef(false);

  // A saved draft edit (revision bump) or draft switch makes any resolved
  // preview stale: drop it plus the review approval + key.
  useEffect(() => {
    setResolved(null);
    setValidation(null);
    setResolveError(null);
    setConfirmed(false);
    setLaunchError(null);
    keyRef.current = null;
  }, [draftId, revision]);

  const invalidateReview = () => {
    setConfirmed(false);
    keyRef.current = null;
  };

  const fieldByPath = useMemo(() => {
    const map = new Map<string, ConfigFieldV1>();
    for (const f of fields) map.set(f.path, f);
    return map;
  }, [fields]);

  const goalText = goal !== null && goal.trim() !== '' ? goal : null;

  const resolveAndValidate = async () => {
    if (resolving) return;
    setResolving(true);
    setResolveError(null);
    setResolved(null);
    setValidation(null);
    setLaunchError(null);
    invalidateReview();
    try {
      const p = profile === '' ? undefined : profile;
      const [manifest, verdict] = await Promise.all([
        resolveDraftConfigV1(draftId, p),
        validateRunDraftV1(draftId, p),
      ]);
      setResolved(manifest);
      setValidation(verdict);
    } catch (err) {
      setResolveError(errorText(toApiError(err), t('studio_request_id')));
    } finally {
      setResolving(false);
    }
  };

  // Diff vs defaults: every leaf whose provenance is NOT the bundled default
  // layer. The review shows what this launch changes, derived from the
  // server's provenance map — never from the draft's own override list, which
  // would miss a value a profile or template supplied.
  const changedRows = useMemo(() => {
    if (!resolved) return [];
    const provenance = resolved.provenance ?? {};
    const values = resolved.values ?? {};
    const secrets = resolved.secret_references ?? {};
    return Object.keys(provenance)
      .filter((path) => provenance[path].source !== 'default')
      .sort()
      .map((path) => ({
        path,
        field: fieldByPath.get(path) ?? null,
        effective: values[path],
        provenance: provenance[path],
        secret:
          fieldByPath.get(path)?.sensitivity === 'secret_reference' ||
          Object.prototype.hasOwnProperty.call(secrets, path),
      }));
  }, [resolved, fieldByPath]);

  // ADR-09 review: the RESOLVED mode intents, read off the manifest THIS
  // launch would materialize — never the raw draft selection. The runtime
  // resolver warn-and-falls-back on a mismatched pair, so the resolved leaf
  // is the only honest answer to "what will actually run".
  const modeReview = useMemo(() => {
    if (!resolved) return [];
    const provenance = resolved.provenance ?? {};
    const warnings = [
      ...new Set([...(validation?.warnings ?? []), ...(resolved.warnings ?? [])]),
    ];
    return MODE_INTENT_PAIRS.map((pair) => {
      const resolvedMode = readConfigLeaf(resolved.values, pair.modePath);
      const resolvedEnabled = Boolean(readConfigLeaf(resolved.values, pair.enablePath));
      const rejected = provenance[pair.modePath]?.rejected_override ?? null;
      // Two ways a pair goes unhonored: the mode FELL BACK (the resolver
      // rewrote the leaf and kept the request as rejected_override), or the
      // interlock is set without its master switch (warning only, no rewrite).
      const requested =
        rejected && rejected.reason === 'interlock_mismatch' ? rejected.value : resolvedMode;
      const fellBack = requested !== resolvedMode;
      const orphanInterlock = resolvedEnabled && resolvedMode !== pair.activeMode;
      return {
        pair,
        requested,
        resolvedMode,
        resolvedEnabled,
        honored: !fellBack && !orphanInterlock,
        warnings: warnings.filter(
          (w) => w.includes(pair.modePath) || w.includes(pair.enablePath),
        ),
      };
    });
  }, [resolved, validation]);

  const modeFallbacks = modeReview.filter((m) => !m.honored);

  const validationErrors = useMemo(
    () =>
      (validation?.errors ?? []).map((e) => ({
        path: e.path,
        reason: e.reason,
        message: e.message,
        expected: e.expected,
      })),
    [validation],
  );

  const secrets = secretsQ.data?.secrets ?? [];

  const valid = validation !== null && validation.valid;
  const reviewReady = resolved !== null && validation !== null;
  const launchReady = valid && goalText !== null && confirmed && !launching;

  const setReviewApproval = (checked: boolean) => {
    setConfirmed(checked);
    // Mint exactly one key per approval; unchecking discards it (a fresh
    // approval is a fresh idempotent intent).
    keyRef.current = checked ? crypto.randomUUID() : null;
  };

  const launch = async () => {
    // Ref guard: a double-click in the same frame must not send twice.
    if (inFlightRef.current || !launchReady || keyRef.current === null) return;
    inFlightRef.current = true;
    setLaunching(true);
    setLaunchError(null);
    try {
      const res = await launchRunV1({
        draftId,
        displayName: displayName.trim() === '' ? undefined : displayName.trim(),
        profile: profile === '' ? undefined : profile,
        idempotencyKey: keyRef.current,
      });
      // Canonical redirect, the last step of the launch order: the run_id the
      // server issued in its response — NO mtime/latest-checkpoint polling,
      // which would race a concurrent launch onto the wrong run.
      window.location.hash = `#/overview?run=${encodeURIComponent(res.run_id)}`;
    } catch (err) {
      // The key survives for an idempotent retry of the same approval.
      setLaunchError(toApiError(err));
    } finally {
      inFlightRef.current = false;
      setLaunching(false);
    }
  };

  const steps: Array<{ label: string; done: boolean; active: boolean }> = [
    { label: t('studio_launch_step_goal'), done: goalText !== null, active: !reviewReady },
    { label: t('studio_launch_step_review'), done: valid && confirmed, active: reviewReady },
    { label: t('studio_launch_step_launch'), done: false, active: launchReady },
  ];

  return (
    <section aria-label={t('studio_launch_title')} style={{ marginTop: 20 }}>
      <Card title={`🚀 ${t('studio_launch_title')}`}>
        {/* Stepper: the narrowed draft state machine — the fixed launch
            order made visible, so the user can see which step is
            outstanding rather than a disabled button with no reason. */}
        <ol
          style={{
            display: 'flex',
            gap: 16,
            listStyle: 'none',
            margin: '0 0 12px',
            padding: 0,
            flexWrap: 'wrap',
          }}
        >
          {steps.map((s, i) => (
            <li
              key={s.label}
              aria-current={s.active ? 'step' : undefined}
              style={{ fontWeight: s.active ? 700 : 400, fontSize: '.85rem' }}
            >
              {s.done ? '✓' : `${i + 1}.`} {s.label}
            </li>
          ))}
        </ol>

        {/* Step 1 — goal + launch inputs. */}
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <div style={{ flex: '1 1 260px', minWidth: 0 }}>
            <label style={{ display: 'block', fontSize: '.75rem', color: 'var(--muted)' }}>
              {t('studio_launch_goal_label')}
            </label>
            {goalText !== null ? (
              <p style={{ margin: '2px 0', fontSize: '.85rem', whiteSpace: 'pre-wrap' }}>
                {goalText}
              </p>
            ) : (
              <p role="alert" style={{ margin: '2px 0', fontSize: '.85rem', color: 'var(--status-danger)' }}>
                {t('studio_launch_goal_missing')}
              </p>
            )}
          </div>
          <div>
            <label style={{ display: 'block', fontSize: '.75rem', color: 'var(--muted)' }}>
              {t('studio_launch_display_name')}
            </label>
            <input
              type="text"
              aria-label={t('studio_launch_display_name')}
              value={displayName}
              onChange={(e) => {
                setDisplayName(e.target.value);
                invalidateReview();
              }}
              style={{ width: 220 }}
            />
          </div>
          <div>
            <label style={{ display: 'block', fontSize: '.75rem', color: 'var(--muted)' }}>
              {t('studio_launch_profile')}
            </label>
            <select
              aria-label={t('studio_launch_profile')}
              value={profile}
              onChange={(e) => {
                setProfile(e.target.value as '' | LaunchProfileV1);
                // Profile changes the resolution result itself.
                setResolved(null);
                setValidation(null);
                invalidateReview();
              }}
            >
              <option value="">{t('studio_none_option')}</option>
              {PROFILES.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>
          <Button onClick={() => void resolveAndValidate()} disabled={resolving}>
            {resolving ? t('studio_launch_resolving') : t('studio_launch_resolve')}
          </Button>
          {validation !== null &&
            (valid ? (
              <Badge variant="green">{t('studio_launch_valid')}</Badge>
            ) : (
              <Badge variant="red">{t('studio_launch_invalid')}</Badge>
            ))}
        </div>

        {resolveError && (
          <div role="alert" style={{ color: 'var(--status-danger)', fontSize: '.85rem', marginTop: 8 }}>
            {resolveError}
          </div>
        )}
      </Card>

      {/* Step 2 — resolve/validate results + immutable review. */}
      {reviewReady && resolved !== null && (
        <>
          <ValidationSummary errors={validationErrors} />

          {(validation?.warnings?.length ?? 0) > 0 && (
            <Card title={`⚠️ ${t('studio_launch_warnings_title')}`}>
              <ul style={{ margin: 0, paddingLeft: 20 }}>
                {(validation?.warnings ?? []).map((w, i) => (
                  <li key={i} style={{ fontSize: '.85rem' }}>
                    {w}
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {/* Effective-config diff vs defaults (ConfigBrowser row shape). */}
          <Card title={t('studio_launch_diff_title')}>
            {changedRows.length === 0 ? (
              <p style={{ fontSize: '.85rem', margin: 0, color: 'var(--muted)' }}>
                {t('studio_launch_no_changes')}
              </p>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table>
                  <thead>
                    <tr>
                      <th>{t('config_col_field')}</th>
                      <th>{t('studio_launch_col_default')}</th>
                      <th>{t('studio_launch_col_effective')}</th>
                      <th>{t('config_col_source')}</th>
                      <th>{t('config_col_mutability')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {changedRows.map((row) => (
                      <tr key={row.path}>
                        <td>
                          <code style={{ fontSize: '.8rem' }}>{row.path}</code>
                          {row.field?.applies_when && (
                            <div style={{ color: 'var(--muted)', fontSize: '.72rem' }}>
                              {t('config_applies_when')}: {row.field.applies_when}
                            </div>
                          )}
                        </td>
                        <td>
                          {row.secret ? (
                            <Badge variant="muted">{t('config_secret_reference')}</Badge>
                          ) : (
                            <code style={{ fontSize: '.8rem' }}>
                              {formatValue(row.field?.default)}
                            </code>
                          )}
                        </td>
                        <td>
                          {row.secret ? (
                            // NEVER a value for secret references.
                            <Badge variant="muted">{t('config_secret_reference')}</Badge>
                          ) : (
                            <code style={{ fontSize: '.8rem' }}>
                              {formatValue(row.effective)}
                            </code>
                          )}
                        </td>
                        <td>
                          <Badge
                            variant={NEW_RUN_SOURCE_VARIANT[row.provenance.source] ?? 'muted'}
                          >
                            {row.provenance.source}
                          </Badge>
                          {row.provenance.confidence === 'low' && (
                            <>
                              {' '}
                              <Badge variant="yellow">{t('config_confidence_low')}</Badge>
                            </>
                          )}
                        </td>
                        <td>
                          {row.field ? (
                            <Badge variant={MUTABILITY_VARIANT[row.field.mutability]}>
                              {row.field.mutability}
                            </Badge>
                          ) : (
                            <span style={{ opacity: 0.4 }}>—</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          {/* Secret readiness (existing hook — configured flags, never values). */}
          <Card title={t('studio_launch_secrets_title')}>
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              {secrets.map((s) => (
                <li key={s.name} style={{ fontSize: '.85rem', marginBottom: 2 }}>
                  <code style={{ fontSize: '.8rem' }}>{s.name}</code>{' '}
                  {s.configured ? (
                    <Badge variant="green">
                      {t('studio_secret_configured')}
                      {s.source_class ? ` (${s.source_class})` : ''}
                    </Badge>
                  ) : (
                    <Badge variant="muted">{t('studio_secret_not_configured')}</Badge>
                  )}
                </li>
              ))}
            </ul>
            <p style={{ color: 'var(--muted)', fontSize: '.75rem', margin: '6px 0 0' }}>
              {t('studio_launch_governance_note')}
            </p>
          </Card>

          {/* ADR-09: a requested mode the resolver did NOT honor is the one
              thing a reviewer must not miss — its own alert card above the
              summary, with the resolver's warning verbatim. */}
          {modeFallbacks.length > 0 && (
            <Card title={`⚠️ ${t('studio_launch_mode_fallback_title')}`}>
              <div role="alert">
                <p style={{ fontSize: '.85rem', margin: '0 0 6px' }}>
                  {t('studio_launch_mode_fallback_note')}
                </p>
                <ul style={{ margin: 0, paddingLeft: 20 }}>
                  {modeFallbacks.map((m) => (
                    <li key={m.pair.id} style={{ fontSize: '.85rem', marginBottom: 4 }}>
                      {t(MODE_INTENT_LABEL_KEY[m.pair.id])}:{' '}
                      {t('studio_launch_mode_requested')}{' '}
                      <code style={{ fontSize: '.8rem' }}>{formatValue(m.requested)}</code>
                      {' → '}
                      {t('studio_launch_mode_resolved')}{' '}
                      <code style={{ fontSize: '.8rem' }}>{formatValue(m.resolvedMode)}</code>
                      {m.warnings.map((w, i) => (
                        <div
                          key={i}
                          style={{ color: 'var(--muted)', fontSize: '.78rem' }}
                        >
                          {w}
                        </div>
                      ))}
                    </li>
                  ))}
                </ul>
              </div>
            </Card>
          )}

          {/* Immutable launch summary: a launch is approved explicitly, over
              a read-only rendering of exactly what will be launched — the
              review can never be a live editing surface. */}
          <Card title={t('studio_launch_review_title')}>
            <dl
              style={{
                display: 'grid',
                gridTemplateColumns: 'max-content 1fr',
                gap: '4px 16px',
                margin: 0,
                fontSize: '.85rem',
              }}
            >
              <dt style={{ color: 'var(--muted)' }}>{t('studio_launch_display_name')}</dt>
              <dd style={{ margin: 0 }}>{displayName.trim() === '' ? '—' : displayName.trim()}</dd>
              <dt style={{ color: 'var(--muted)' }}>run_id</dt>
              <dd style={{ margin: 0 }}>{t('studio_launch_run_id_note')}</dd>
              <dt style={{ color: 'var(--muted)' }}>{t('studio_launch_profile')}</dt>
              <dd style={{ margin: 0 }}>{profile === '' ? t('studio_none_option') : profile}</dd>
              {/* RESOLVED mode intents — the manifest's post-interlock values,
                  not the draft's raw selection. */}
              {modeReview.map((m) => (
                <Fragment key={m.pair.id}>
                  <dt style={{ color: 'var(--muted)' }}>
                    {t(MODE_INTENT_LABEL_KEY[m.pair.id])}
                  </dt>
                  <dd style={{ margin: 0 }}>
                    <code style={{ fontSize: '.8rem' }}>{formatValue(m.resolvedMode)}</code>{' '}
                    <span style={{ color: 'var(--muted)', fontSize: '.78rem' }}>
                      ({m.pair.enablePath}={String(m.resolvedEnabled)})
                    </span>{' '}
                    {m.honored ? (
                      <Badge variant="green">{t('studio_launch_mode_effective')}</Badge>
                    ) : (
                      <Badge variant="red">{t('studio_launch_mode_fallback_badge')}</Badge>
                    )}
                  </dd>
                </Fragment>
              ))}
              <dt style={{ color: 'var(--muted)' }}>{t('studio_launch_changed_fields')}</dt>
              <dd style={{ margin: 0 }}>{changedRows.length}</dd>
              <dt style={{ color: 'var(--muted)' }}>{t('studio_launch_digest')}</dt>
              <dd style={{ margin: 0 }}>
                <code style={{ fontSize: '.8rem' }}>{resolved.digest}</code>
              </dd>
            </dl>

            <label
              style={{
                display: 'inline-flex',
                alignItems: 'flex-start',
                gap: 8,
                marginTop: 12,
                fontSize: '.85rem',
              }}
            >
              <input
                type="checkbox"
                aria-label={t('studio_launch_confirm')}
                checked={confirmed}
                disabled={!valid || goalText === null}
                onChange={(e) => setReviewApproval(e.target.checked)}
              />
              <span>{t('studio_launch_confirm')}</span>
            </label>

            {/* Step 3 — the idempotent launch. */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 12 }}>
              <Button onClick={() => void launch()} disabled={!launchReady}>
                {launching ? t('studio_launch_launching') : t('studio_launch_button')}
              </Button>
            </div>

            {launchError && (
              <div role="alert" style={{ marginTop: 8 }}>
                <div style={{ color: 'var(--status-danger)', fontSize: '.85rem' }}>
                  {t('studio_launch_failed_title')}: {errorText(launchError, t('studio_request_id'))}
                </div>
                <ValidationSummary errors={patchErrorsFromDetails(launchError.details)} />
              </div>
            )}
          </Card>
        </>
      )}
    </section>
  );
}
