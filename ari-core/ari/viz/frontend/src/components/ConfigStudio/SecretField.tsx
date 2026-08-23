// ARI Dashboard – write-only secret control for the Configuration Studio
// (gui_refresh task 06 Wave 4d; ADR-05/ADR-11). Secrets are write-only on
// this surface — the readiness endpoint has no value field at all — and the
// control itself is generated from the field's declared metadata rather than
// hand-placed, so a new secret field needs no frontend change.
//
// A secret_reference field NEVER carries a readable value: this control
// renders readiness only (configured / not configured + source class from
// GET /api/v1/secrets/status) and writes through the canonical
// PUT /api/v1/secrets/{secret_id}. The input is cleared the moment the PUT
// resolves, and the response type (SecretUpdatedV1) has no value field, so
// echoing a secret back into the DOM is structurally impossible.
//
// The target secret NAME is chosen from the server-side allowlist (the
// readiness rows); the default preselection comes from the model catalog's
// per-provider env_key so 'llm.api_key' targets the right variable for the
// currently selected provider without a frontend constant.

import { useEffect, useState } from 'react';
import { useT } from '../../i18n';
import { Badge, Button } from '../common';
import { putSecretV1, toApiError, type SecretV1 } from '../../services/api/v1';

interface SecretFieldProps {
  /** Readiness rows from GET /api/v1/secrets/status (allowlist order). */
  secrets: SecretV1[];
  /** Preselected secret name (e.g. the catalog env_key of the active provider). */
  defaultName?: string;
  /** Called after a successful PUT so the owner can invalidate readiness. */
  onSaved: () => void;
}

export function SecretField({ secrets, defaultName, onSaved }: SecretFieldProps) {
  const t = useT();
  const [name, setName] = useState<string>(defaultName ?? secrets[0]?.name ?? '');
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);
  const [updated, setUpdated] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Adopt a late-arriving default (catalog/readiness load after mount) only
  // while the user has not touched the picker.
  const [touched, setTouched] = useState(false);
  useEffect(() => {
    if (!touched && defaultName) setName(defaultName);
    else if (!touched && name === '' && secrets.length > 0) setName(secrets[0].name);
  }, [defaultName, secrets, touched, name]);

  const selected = secrets.find((s) => s.name === name);

  const submit = async () => {
    if (name === '' || value === '' || busy) return;
    setBusy(true);
    setError(null);
    setUpdated(false);
    try {
      await putSecretV1(name, value);
      // Write-only: drop the plaintext immediately — it never renders again.
      setValue('');
      setUpdated(true);
      onSaved();
    } catch (err) {
      setError(toApiError(err).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <select
          aria-label={t('studio_secret_name_label')}
          value={name}
          onChange={(e) => {
            setTouched(true);
            setName(e.target.value);
            setUpdated(false);
            setError(null);
          }}
        >
          {secrets.map((s) => (
            <option key={s.name} value={s.name}>
              {s.name}
            </option>
          ))}
        </select>
        {selected &&
          (selected.configured ? (
            <Badge variant="green">
              {t('studio_secret_configured')}
              {selected.source_class ? ` (${selected.source_class})` : ''}
            </Badge>
          ) : (
            <Badge variant="yellow">{t('studio_secret_not_configured')}</Badge>
          ))}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <input
          type="password"
          autoComplete="off"
          aria-label={t('studio_secret_placeholder')}
          placeholder={t('studio_secret_placeholder')}
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            setUpdated(false);
          }}
          style={{ flex: '0 1 260px' }}
        />
        <Button onClick={() => void submit()} disabled={busy || value === ''}>
          {t('studio_secret_set')}
        </Button>
        {updated && <Badge variant="green">{t('studio_secret_updated')}</Badge>}
      </div>
      {error && (
        <div role="alert" style={{ color: 'var(--status-danger)', fontSize: '.8rem' }}>
          {error}
        </div>
      )}
      <div style={{ color: 'var(--muted)', fontSize: '.72rem' }}>
        {t('studio_secret_write_only_note')}
      </div>
    </div>
  );
}
