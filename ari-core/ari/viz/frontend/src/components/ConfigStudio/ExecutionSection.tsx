// ARI Dashboard – Configuration Studio "Execution" section (ADR-09, accepted
// by the program 2026-07-27; supersedes the "no CLI flag / no GUI toggle"
// statement in docs/guides/execution_modes.md for the NEW-RUN case only).
//
// Exactly TWO user-facing controls, one per orthogonal intent:
//
//   Execution mode  ari.mode   {simple_bfts (default), ari_rqgm}
//                   + rqgm.enabled
//   Paper mode      paper.mode {linear (default), rqgm_archive}
//                   + rqgm.paper.enabled
//
// Each control writes BOTH leaves of its pair into the edit buffer in one
// step, so a single Save issues ONE PATCH carrying both keys — the GUI can
// never produce the half-set document the backend rejects with
// `mode_interlock_mismatch`. The two axes are independent: all four
// combinations are valid.
//
// HARD CONSTRAINTS honored here:
//   - NEW-RUN ONLY. Both leaves are `mutability: new_run_only`; the copy says
//     so explicitly. Nothing on this surface can retarget an existing run —
//     resume keeps taking its mode from the persisted {ckpt}/rqgm_state.json
//     (ari.cli.run reconcile_resume_mode, downgrade-only).
//   - PROJECT scope stays refused. The four leaves are `scope: run`, so the
//     project document rejects them (`not_project_scope`); in that scope the
//     selects are disabled with the reason instead of pretending to work.
//   - Selecting a mode is NOT governance mutation. The remaining ~96 `rqgm.*`
//     tuning leaves stay READ-ONLY (collapsed by default) and are rendered by
//     the SHARED ConfigBrowser read-only table — this file contains no second
//     row renderer and emits no editable control inside that group. The GUI's
//     RQGM registry/transition surfaces remain read-only as before.
//   - DEFAULT PATH UNCHANGED. Leaving simple_bfts + linear writes nothing:
//     re-selecting the value the document already has clears the pending edit
//     rather than materializing a redundant key.

import { useT } from '../../i18n';
import { Badge, Card } from '../common';
import {
  ConfigReadOnlyTable,
  MUTABILITY_VARIANT,
  type ConfigReadOnlyRow,
} from '../ConfigBrowser/ConfigReadOnlyTable';
import type { ConfigFieldV1 } from '../../services/api/v1';
import {
  MODE_INTENT_LABEL_KEY,
  MODE_INTENT_PAIRS,
  MODE_SELECTION_PATHS,
  pairSelection,
  type ModeIntentPair,
} from './modeIntents';

/** Human descriptor per mode value (i18n key; values themselves are shown
 * verbatim because they ARE the config values a workflow.yaml would carry). */
const MODE_VALUE_DESC: Record<string, string> = {
  simple_bfts: 'studio_exec_opt_simple_bfts',
  ari_rqgm: 'studio_exec_opt_ari_rqgm',
  linear: 'studio_paper_opt_linear',
  rqgm_archive: 'studio_paper_opt_rqgm_archive',
};

const PAIR_HELP: Record<ModeIntentPair['id'], string> = {
  execution: 'studio_exec_mode_help',
  paper: 'studio_paper_mode_help',
};

export interface ExecutionSectionProps {
  /** Every registry leaf of this section (the 4 mode leaves + `rqgm.*`). */
  fields: ConfigFieldV1[];
  /** Editing scope of the active document. */
  scope: 'project' | 'template' | 'draft';
  /** Effective form value: pending edit > saved document > registry default. */
  valueOf: (path: string) => unknown;
  /** True when the path carries an unsaved edit. */
  isPending: (path: string) => boolean;
  /** True when the path is stored in the active document. */
  isSaved: (path: string) => boolean;
  /** Write BOTH leaves of one intent pair (or clear both back to saved). */
  onSelectPair: (pair: ModeIntentPair, mode: string) => void;
}

export function ExecutionSection({
  fields,
  scope,
  valueOf,
  isPending,
  isSaved,
  onSelectPair,
}: ExecutionSectionProps) {
  const t = useT();
  // Mode selection is a RUN-scoped intent: the project document rejects it
  // server-side (`not_project_scope`), so the controls are disabled there.
  const selectable = scope !== 'project';

  const byPath = new Map(fields.map((f) => [f.path, f]));

  const readOnlyRows: ConfigReadOnlyRow[] = fields
    .filter((f) => !MODE_SELECTION_PATHS.has(f.path))
    .map((f) => {
      const value = valueOf(f.path);
      return {
        path: f.path,
        field: f,
        value,
        hasValue: value !== null && value !== undefined,
        provenance: isSaved(f.path) ? { source: scope, confidence: 'high' } : null,
        secret: f.sensitivity === 'secret_reference',
      };
    });

  return (
    <>
      <Card title={`⚙️ ${t('studio_exec_section_title')}`}>
        <p style={{ fontSize: '.85rem', margin: '0 0 6px' }}>
          {t('studio_exec_section_intro')}
        </p>
        <p style={{ fontSize: '.85rem', margin: '0 0 6px' }}>
          {t('studio_exec_orthogonal')}
        </p>
        <p role="note" style={{ fontSize: '.85rem', margin: 0, color: 'var(--muted)' }}>
          ⚠️ {t('studio_exec_new_run_only')}
        </p>
        {!selectable && (
          <p role="note" style={{ fontSize: '.85rem', margin: '6px 0 0' }}>
            {t('studio_exec_scope_note')}
          </p>
        )}
      </Card>

      {/* Schema-driven: a pair is offered only when the canonical registry
          still declares its mode leaf — this file invents no field. */}
      {MODE_INTENT_PAIRS.filter((pair) => byPath.has(pair.modePath)).map((pair) => {
        const modeField = byPath.get(pair.modePath);
        const options =
          modeField?.enum && modeField.enum.length > 0
            ? modeField.enum.map((v) => String(v))
            : [pair.fallbackMode, pair.activeMode];
        const modeValue = valueOf(pair.modePath);
        const enabledValue = valueOf(pair.enablePath);
        const consistent = pairSelection(pair, modeValue, enabledValue) !== null;
        const edited = isPending(pair.modePath) || isPending(pair.enablePath);
        return (
          <Card key={pair.id} title={t(MODE_INTENT_LABEL_KEY[pair.id])}>
            <p style={{ fontSize: '.85rem', margin: '0 0 8px' }}>{t(PAIR_HELP[pair.id])}</p>
            <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
              <select
                aria-label={t(MODE_INTENT_LABEL_KEY[pair.id])}
                disabled={!selectable}
                value={typeof modeValue === 'string' ? modeValue : pair.fallbackMode}
                onChange={(e) => onSelectPair(pair, e.target.value)}
              >
                {options.map((v) => (
                  <option key={v} value={v}>
                    {MODE_VALUE_DESC[v] ? `${v} — ${t(MODE_VALUE_DESC[v])}` : v}
                  </option>
                ))}
              </select>
              {edited && <Badge variant="yellow">{t('studio_edited_badge')}</Badge>}
              {/* Mutability comes from the registry, never a literal here. */}
              {modeField && (
                <Badge variant={MUTABILITY_VARIANT[modeField.mutability]}>
                  {modeField.mutability}
                </Badge>
              )}
            </div>
            <p style={{ color: 'var(--muted)', fontSize: '.75rem', margin: '6px 0 0' }}>
              {t('studio_exec_pair_paths')}{' '}
              <code style={{ fontSize: '.75rem' }}>{pair.modePath}</code>
              {' + '}
              <code style={{ fontSize: '.75rem' }}>{pair.enablePath}</code>
              {' = '}
              <code style={{ fontSize: '.75rem' }}>
                {String(Boolean(enabledValue))}
              </code>
            </p>
            <p style={{ color: 'var(--muted)', fontSize: '.75rem', margin: '2px 0 0' }}>
              {t('studio_exec_new_run_only')}
            </p>
            {!consistent && (
              <p
                role="alert"
                style={{ color: 'var(--status-danger)', fontSize: '.8rem', margin: '6px 0 0' }}
              >
                {t('studio_exec_pair_mismatch')}
              </p>
            )}
          </Card>
        );
      })}

      {/* The remaining rqgm.* tuning tree: visible, effective values, but not
          editable in this release — rendered by the SHARED read-only table. */}
      <details>
        <summary style={{ cursor: 'pointer', padding: '6px 0' }}>
          <strong>{t('studio_exec_readonly_title')}</strong>{' '}
          <span style={{ color: 'var(--muted)', fontSize: '.8rem' }}>
            ({readOnlyRows.length})
          </span>
        </summary>
        <Card>
          <p style={{ fontSize: '.8rem', margin: '0 0 8px', color: 'var(--muted)' }}>
            {t('studio_exec_readonly_note')}
          </p>
          <div style={{ overflowX: 'auto' }}>
            <ConfigReadOnlyTable rows={readOnlyRows} />
          </div>
        </Card>
      </details>
    </>
  );
}
