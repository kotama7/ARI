// ARI Dashboard – per-path validation summary for the Configuration Studio
// (gui_refresh task 06 Wave 4d; plan 06 §Validation and review).
//
// Renders the details.errors list of a 400 'invalid_request' PATCH envelope
// (the ari.config.field_registry.validate_patch closed vocabulary:
// unknown_path / secret_reference / read_only / not_project_scope /
// invalid_enum / invalid_type) verbatim — path, reason tag, message.

import { useT } from '../../i18n';
import { Badge, Card } from '../common';

export interface PatchErrorV1 {
  path: string;
  reason: string;
  message: string;
  expected?: unknown;
}

/** Best-effort extraction of details.errors from an ApiErrorV1.details. */
export function patchErrorsFromDetails(details: unknown): PatchErrorV1[] {
  if (typeof details !== 'object' || details === null) return [];
  const errors = (details as { errors?: unknown }).errors;
  if (!Array.isArray(errors)) return [];
  return errors.filter(
    (e): e is PatchErrorV1 =>
      typeof e === 'object' &&
      e !== null &&
      typeof (e as { path?: unknown }).path === 'string' &&
      typeof (e as { message?: unknown }).message === 'string',
  );
}

export function ValidationSummary({ errors }: { errors: PatchErrorV1[] }) {
  const t = useT();
  if (errors.length === 0) return null;
  return (
    <Card title={`⚠️ ${t('studio_validation_title')}`}>
      <ul style={{ margin: 0, paddingLeft: 20 }} role="alert">
        {errors.map((e, i) => (
          <li key={`${e.path}-${i}`} style={{ fontSize: '.85rem', marginBottom: 4 }}>
            <code style={{ fontSize: '.8rem' }}>{e.path}</code>{' '}
            <Badge variant="red">{e.reason}</Badge> {e.message}
          </li>
        ))}
      </ul>
    </Card>
  );
}
