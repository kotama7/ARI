// ARI Dashboard – Governance workspace shared primitives (gui_refresh task
// 08 Wave 4a). Registry lifecycle status and node score state are different
// state machines and must never be mixed in one field or one legend; absence
// is rendered as absence, never as clean or as zero. Both rules are enforced
// by the API and restated here for the render side — see
// docs/reference/rqgm_gui_read_models.md, "Two vocabularies, two state
// machines" and "Presentation truth rules the API enforces".
//
// Two SEPARATE state-machine vocabularies, kept apart structurally:
//   - registry lifecycle (the closed 10-value STATUS_VALUES implementation
//     vocabulary) renders via RegistryStatusBadge → `.reg-badge--*` classes
//     backed by the `--reg-*` tokens;
//   - node score state (computed/recomputed/stale/invalidated/removed)
//     renders via NodeStateBadge → `.nodestate-badge--*` classes backed by
//     the `--state-*` tokens.
// The class families and token families are disjoint, so one vocabulary can
// never borrow the other's color: a registry status and a node score state
// are different state machines, so neither may appear in the other's field
// or legend. Badge text is the
// verbatim implementation token (glossary: lifecycle states are shown as
// the auditable exact value); the translated label rides on `title`.

import { useT } from '../../i18n';
import type { ApiErrorV1 } from '../../services/api/v1';

/** Registry lifecycle vocabulary — verbatim `ari.rqgm.events.STATUS_VALUES`
 * (mirrors `RegistryStatusV1`; pinned against the generated DTO enum by the
 * page test's exhaustive-render case). */
export const REGISTRY_STATUS_VALUES = [
  'candidate',
  'validated',
  'shadow',
  'probationary_active',
  'active',
  'warning',
  'probation',
  'quarantine',
  'retired',
  'banned',
] as const;

/** Node score-state vocabulary (mirrors `NodeScoreStateV1`) — a DIFFERENT
 * state machine from the registry lifecycle above. */
export const NODE_SCORE_STATES = [
  'computed',
  'recomputed',
  'stale',
  'invalidated',
  'removed',
] as const;

export function RegistryStatusBadge({ status }: { status: string }) {
  const t = useT();
  const known = (REGISTRY_STATUS_VALUES as readonly string[]).includes(status);
  return (
    <span
      className={known ? `reg-badge reg-badge--${status}` : 'reg-badge'}
      title={known ? t(`gov_status_${status}`) : status}
      data-testid={`reg-status-${status}`}
    >
      {status}
    </span>
  );
}

export function NodeStateBadge({ state }: { state: string | null }) {
  const t = useT();
  if (state === null || state === '') {
    // A missing state is shown as unknown — never guessed: a missing source
    // is never displayed as clean, because "we verified nothing bad happened"
    // and "we have no record" are different claims.
    return <span style={{ opacity: 0.55 }}>{t('gov_unknown')}</span>;
  }
  const known = (NODE_SCORE_STATES as readonly string[]).includes(state);
  return (
    <span
      className={
        known ? `nodestate-badge nodestate-badge--${state}` : 'nodestate-badge'
      }
      title={known ? t(`gov_state_${state}`) : state}
      data-testid={`node-state-${state}`}
    >
      {state}
    </span>
  );
}

/** Glossary display form: score/policy identity is always `Policy <hash12>`
 * — a hash-less policy is `unknown`, never blank. A score is never shown
 * without its policy identity, so the identity slot always renders. */
export function PolicyHashLabel({ hash }: { hash: string | null | undefined }) {
  const t = useT();
  if (!hash) {
    return <span style={{ opacity: 0.55 }}>{t('gov_unknown')}</span>;
  }
  return <code style={{ fontSize: '.78rem' }}>{hash}</code>;
}

/** err.message plus the envelope's request_id: every /api/v1 failure carries
 * a `req-<12 hex>` id minted per dispatch, and the UI quotes it so a bug
 * report names one server-side dispatch. */
export function errorText(err: ApiErrorV1, requestIdLabel: string): string {
  const rid = err.request_id ? ` (${requestIdLabel}: ${err.request_id})` : '';
  return `${err.message}${rid}`;
}

/** Numeric score cell: numbers verbatim, anything else shown as unknown —
 * a missing score is NEVER rendered as 0. Counts and scores stay absent when
 * their artifact is missing; zero is a measurement, absence is not. */
export function ScoreValue({ value }: { value: unknown }) {
  const t = useT();
  if (typeof value === 'number' && Number.isFinite(value)) {
    return <code style={{ fontSize: '.8rem' }}>{String(value)}</code>;
  }
  return <span style={{ opacity: 0.55 }}>{t('gov_unknown')}</span>;
}
