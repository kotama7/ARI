// ARI Dashboard – the ONE read-only config row renderer (extracted from
// ConfigBrowserPage; gui_refresh Wave 3b rendering contract unchanged).
//
// Extracted for ADR-09 (2026-07-27): the Configuration Studio's Execution
// section displays the ~96 non-selectable rqgm.* governance/tuning leaves
// READ-ONLY, and it must use exactly these rows — value formatting, secret
// redaction, provenance/mutability badge semantics and the applies_when note
// have a single implementation, so the two config surfaces cannot drift.
// There is deliberately NO second read-only renderer in the codebase.
//
// Nothing here is interactive: the component emits a <table> of <tr>s with no
// input/select/button of any kind (asserted by the Studio's execution-mode
// test — the read-only group must expose no editable control).

import { useT } from '../../i18n';
import { Badge } from '../common';
import type { ConfigFieldV1 } from '../../services/api/v1';

export type BadgeVariant = 'green' | 'red' | 'yellow' | 'blue' | 'muted';

/** Provenance source -> badge color (semantic token families).
 * Exported for reuse by the Configuration Studio (Wave 4d) so the two
 * config surfaces can never drift on badge semantics. */
export const SOURCE_VARIANT: Record<string, BadgeVariant> = {
  default: 'muted',
  workflow: 'blue',
  launch_config: 'green',
  env: 'yellow',
  checkpoint_state: 'blue',
};

/** ConfigFieldV1.mutability -> badge color (exported for the Studio too). */
export const MUTABILITY_VARIANT: Record<ConfigFieldV1['mutability'], BadgeVariant> = {
  draft: 'blue',
  new_run_only: 'yellow',
  resume_mutable: 'green',
  read_only: 'muted',
};

/**
 * Deterministic display form of a config value. Deliberately NOT a raw JSON
 * dump (check_dashboard_ux json_dump inventory): strings render bare,
 * containers as a compact literal.
 */
export function formatConfigValue(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'string') return v === '' ? "''" : v;
  if (typeof v === 'number' || typeof v === 'boolean') return String(v);
  if (Array.isArray(v)) return `[${v.map(formatConfigValue).join(', ')}]`;
  if (typeof v === 'object') {
    const entries = Object.entries(v as Record<string, unknown>);
    return `{${entries.map(([k, val]) => `${k}: ${formatConfigValue(val)}`).join(', ')}}`;
  }
  return String(v);
}

/**
 * Structural provenance view: both the run manifest's ProvenanceEntryV1 and
 * the new-run manifest's NewRunProvenanceV1 satisfy it, and the Studio can
 * synthesize one for a document-scoped value without widening either DTO.
 */
export interface ConfigRowProvenance {
  source: string;
  confidence?: 'high' | 'low';
}

/** One read-only display row: registry metadata plus a resolved overlay. */
export interface ConfigReadOnlyRow {
  path: string;
  field: ConfigFieldV1 | null;
  /** Effective value, or the schema default in schema-only mode. */
  value: unknown;
  hasValue: boolean;
  provenance: ConfigRowProvenance | null;
  secret: boolean;
}

/** Header + body of the shared read-only config table. */
export function ConfigReadOnlyTable({ rows }: { rows: ConfigReadOnlyRow[] }) {
  const t = useT();
  return (
    <table>
      <thead>
        <tr>
          <th>{t('config_col_field')}</th>
          <th>{t('config_col_value')}</th>
          <th>{t('config_col_source')}</th>
          <th>{t('config_col_mutability')}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
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
                // NEVER a value for secret references.
                <Badge variant="muted">{t('config_secret_reference')}</Badge>
              ) : row.hasValue ? (
                <code style={{ fontSize: '.8rem' }}>{formatConfigValue(row.value)}</code>
              ) : (
                <span style={{ opacity: 0.4 }}>—</span>
              )}
            </td>
            <td>
              <Badge variant={SOURCE_VARIANT[row.provenance?.source ?? 'default'] ?? 'muted'}>
                {row.provenance?.source ?? 'default'}
              </Badge>
              {row.provenance?.confidence === 'low' && (
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
  );
}
