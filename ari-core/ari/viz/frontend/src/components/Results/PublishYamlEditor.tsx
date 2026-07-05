import { Button } from '../common/Button';
import { useDevMode } from '../../hooks/useDevMode';
import type { PublishYamlData } from '../../services/api';

// ─── publish.yaml editor (per-checkpoint EAR allowlist) ───
export interface PublishYamlEditorProps {
  runId: string;
  data: PublishYamlData | null;
  text: string;
  exists: boolean;
  mode: 'form' | 'raw';
  saving: boolean;
  msg: string;
  t: (k: string) => string;
  setMode: (m: 'form' | 'raw') => void;
  setData: (d: PublishYamlData) => void;
  setText: (s: string) => void;
  onSaved: (alsoCurate: boolean) => void;
}

export function PublishYamlEditor({
  runId,
  data,
  text,
  exists,
  mode,
  saving,
  msg,
  t,
  setMode,
  setData,
  setText,
  onSaved,
}: PublishYamlEditorProps) {
  const { devMode } = useDevMode();
  if (!runId) return null;
  // Raw-YAML editing is developer-only (071): when Developer Mode is off the
  // Raw toggle is hidden and the panel stays in the guided form view even if a
  // stale `mode === 'raw'` is passed in.
  const rawMode = mode === 'raw' && devMode;
  const d: PublishYamlData = data || {};
  const includeArr: string[] = Array.isArray(d.include) ? d.include : [];
  const excludeArr: string[] = Array.isArray(d.exclude) ? d.exclude : [];
  const update = (patch: Partial<PublishYamlData>) =>
    setData({ ...d, ...patch });

  return (
    <div
      style={{
        marginTop: 10,
        padding: 10,
        border: '1px solid var(--border, #ccc)',
        borderRadius: 6,
        background: 'var(--surface-1, rgba(0,0,0,0.02))',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
        <strong>{t('py_editor_title')}</strong>
        <div style={{ display: 'flex', gap: 6 }}>
          <Button
            size="sm"
            variant={!rawMode ? 'primary' : 'outline'}
            onClick={() => setMode('form')}
          >
            {t('py_editor_form')}
          </Button>
          {devMode && (
            <Button
              size="sm"
              variant={rawMode ? 'primary' : 'outline'}
              onClick={() => setMode('raw')}
            >
              {t('py_editor_raw')}
            </Button>
          )}
        </div>
      </div>
      {!exists && (
        <div style={{ fontSize: '.78rem', color: 'var(--muted)', marginBottom: 8 }}>
          {t('py_editor_new_hint')}
        </div>
      )}
      {!rawMode ? (
        <div style={{ display: 'grid', gap: 8, fontSize: '.82rem' }}>
          <label>
            <div style={{ marginBottom: 2 }}>
              <strong>{t('py_editor_include')}</strong>{' '}
              <span style={{ color: 'var(--muted)' }}>{t('py_editor_glob_hint')}</span>
            </div>
            <textarea
              rows={3}
              value={includeArr.join('\n')}
              onChange={(e) =>
                update({
                  include: e.target.value.split('\n').map((s) => s.trim()).filter(Boolean),
                })
              }
              style={{ width: '100%', fontFamily: 'monospace' }}
            />
          </label>
          <label>
            <div style={{ marginBottom: 2 }}>
              <strong>{t('py_editor_exclude')}</strong>{' '}
              <span style={{ color: 'var(--muted)' }}>{t('py_editor_glob_hint')}</span>
            </div>
            <textarea
              rows={3}
              value={excludeArr.join('\n')}
              onChange={(e) =>
                update({
                  exclude: e.target.value.split('\n').map((s) => s.trim()).filter(Boolean),
                })
              }
              style={{ width: '100%', fontFamily: 'monospace' }}
            />
          </label>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            <label>
              <div><strong>{t('py_editor_license')}</strong></div>
              <input
                type="text"
                value={d.license || ''}
                placeholder="MIT"
                onChange={(e) => update({ license: e.target.value })}
                style={{ width: 140 }}
              />
            </label>
            <label>
              <div><strong>{t('py_editor_visibility')}</strong></div>
              <select
                value={d.visibility || 'staged'}
                onChange={(e) => update({ visibility: e.target.value })}
              >
                <option value="staged">staged</option>
                <option value="public">public</option>
                <option value="embargoed">embargoed</option>
              </select>
            </label>
            <label>
              <div><strong>{t('py_editor_max_file_mb')}</strong></div>
              <input
                type="number"
                min={1}
                value={d.max_file_mb ?? 100}
                onChange={(e) => update({ max_file_mb: Number(e.target.value) || 0 })}
                style={{ width: 80 }}
              />
            </label>
          </div>
        </div>
      ) : (
        <textarea
          rows={14}
          value={text}
          onChange={(e) => setText(e.target.value)}
          style={{ width: '100%', fontFamily: 'monospace', fontSize: '.78rem' }}
        />
      )}
      <div style={{ display: 'flex', gap: 6, marginTop: 8, alignItems: 'center' }}>
        <Button size="sm" disabled={saving} onClick={() => onSaved(false)}>
          {saving ? '…' : t('py_editor_save')}
        </Button>
        <Button size="sm" variant="outline" disabled={saving} onClick={() => onSaved(true)}>
          {saving ? '…' : t('py_editor_save_and_curate')}
        </Button>
        {msg && <span style={{ marginLeft: 6, fontFamily: 'monospace' }}>{msg}</span>}
      </div>
    </div>
  );
}
