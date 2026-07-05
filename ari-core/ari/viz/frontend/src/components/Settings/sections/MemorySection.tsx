import { Card } from '../../common';
import { restartLetta } from '../../../services/api';
import { inputStyle, labelStyle } from '../settingsStyles';
import {
  LETTA_EMBEDDING_BY_PROVIDER,
  LETTA_EMBED_PROVIDERS,
  CUSTOM_HANDLE_VALUE,
} from '../settingsConstants';
import type { TFn, LettaDeployment } from '../settingsTypes';

interface MemorySectionProps {
  t: TFn;
  lettaBaseUrl: string;
  setLettaBaseUrl: (v: string) => void;
  lettaApiKey: string;
  setLettaApiKey: (v: string) => void;
  lettaEmbedProvider: string;
  setLettaEmbedProvider: (v: string) => void;
  lettaEmbedModel: string;
  setLettaEmbedModel: (v: string) => void;
  lettaEmbedCustom: string;
  setLettaEmbedCustom: (v: string) => void;
  lettaDeployment: LettaDeployment;
  setLettaDeployment: (v: LettaDeployment) => void;
  lettaRestarting: boolean;
  setLettaRestarting: (v: boolean) => void;
  lettaRestartMsg: string;
  setLettaRestartMsg: (v: string) => void;
}

export function MemorySection({
  t,
  lettaBaseUrl,
  setLettaBaseUrl,
  lettaApiKey,
  setLettaApiKey,
  lettaEmbedProvider,
  setLettaEmbedProvider,
  lettaEmbedModel,
  setLettaEmbedModel,
  lettaEmbedCustom,
  setLettaEmbedCustom,
  lettaDeployment,
  setLettaDeployment,
  lettaRestarting,
  setLettaRestarting,
  lettaRestartMsg,
  setLettaRestartMsg,
}: MemorySectionProps) {
  return (
    <Card title={t('settings_memory')}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
        <div>
          <label style={labelStyle}>{t('settings_memory_base_url')}</label>
          <input
            type="text"
            value={lettaBaseUrl}
            onChange={(e) => setLettaBaseUrl(e.target.value)}
            placeholder="http://localhost:8283"
            style={inputStyle}
          />
        </div>
        <div>
          <label style={labelStyle}>{t('settings_memory_api_key')}</label>
          <input
            type="password"
            value={lettaApiKey}
            onChange={(e) => setLettaApiKey(e.target.value)}
            placeholder="(optional)"
            style={inputStyle}
          />
        </div>

        {/* Embedding — provider + model two-stage picker */}
        <div>
          <label style={labelStyle}>
            {t('settings_memory_embedding_provider')}
          </label>
          <select
            value={lettaEmbedProvider}
            onChange={(e) => {
              const p = e.target.value;
              setLettaEmbedProvider(p);
              if (p !== CUSTOM_HANDLE_VALUE) {
                const first = LETTA_EMBEDDING_BY_PROVIDER[p]?.[0];
                if (first) setLettaEmbedModel(first.handle);
              }
            }}
            style={inputStyle}
          >
            {LETTA_EMBED_PROVIDERS.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
            <option value={CUSTOM_HANDLE_VALUE}>{t('custom_entry')}</option>
          </select>
        </div>
        <div>
          <label style={labelStyle}>
            {t('settings_memory_embedding_model')}
          </label>
          {lettaEmbedProvider !== CUSTOM_HANDLE_VALUE ? (
            <select
              value={lettaEmbedModel}
              onChange={(e) => setLettaEmbedModel(e.target.value)}
              style={inputStyle}
            >
              {(LETTA_EMBEDDING_BY_PROVIDER[lettaEmbedProvider] || []).map((m) => (
                <option key={m.handle} value={m.handle}>
                  {m.label || m.handle}
                </option>
              ))}
            </select>
          ) : (
            <input
              type="text"
              value={lettaEmbedCustom}
              onChange={(e) => setLettaEmbedCustom(e.target.value)}
              placeholder="provider/model"
              style={inputStyle}
            />
          )}
        </div>

      </div>

      {/* Letta-free warning (now keyed off the new provider state) */}
      {lettaEmbedProvider === 'letta' && (
        <div
          style={{
            marginTop: '10px',
            fontSize: '.78rem',
            color: 'var(--red)',
            background: 'rgba(239,68,68,.08)',
            border: '1px solid rgba(239,68,68,.3)',
            padding: '8px 10px',
            borderRadius: '6px',
          }}
        >
          {t('settings_memory_letta_free_warning')}
        </div>
      )}

      {/* Restart Letta — long-lived daemon doesn't reload env, so
          changes to provider keys / handles need a server restart
          to take effect. The button calls /api/memory/restart which
          runs stop_local + start_local. */}
      <div
        style={{
          marginTop: '12px',
          display: 'flex',
          gap: '8px',
          alignItems: 'center',
          flexWrap: 'wrap',
        }}
      >
        <label style={{ fontSize: '.8rem', color: 'var(--muted)' }}>
          {t('settings_memory_deployment')}
        </label>
        <select
          value={lettaDeployment}
          onChange={(e) =>
            setLettaDeployment(e.target.value as LettaDeployment)
          }
          disabled={lettaRestarting}
          style={{ ...inputStyle, width: 'auto', minWidth: '160px' }}
        >
          <option value="auto">{t('settings_memory_deployment_auto')}</option>
          <option value="docker">Docker</option>
          <option value="singularity">Singularity</option>
          <option value="pip">{t('settings_memory_deployment_pip')}</option>
        </select>
        <button
          className="btn btn-outline btn-sm"
          disabled={lettaRestarting}
          onClick={async () => {
            if (!confirm(t('settings_memory_restart_confirm'))) return;
            setLettaRestarting(true);
            setLettaRestartMsg(t('settings_memory_restart_running'));
            try {
              const r = await restartLetta(lettaDeployment);
              setLettaRestartMsg(
                r.ok
                  ? `✓ ${t('settings_memory_restart_ok')}${
                      r.start?.path ? ` (${r.start.path})` : ''
                    }`
                  : `✗ ${r.start?.error || r.error || 'failed'}`
              );
            } catch (e) {
              setLettaRestartMsg(`✗ ${String(e)}`);
            } finally {
              setLettaRestarting(false);
            }
            setTimeout(() => setLettaRestartMsg(''), 8000);
          }}
        >
          {lettaRestarting ? t('settings_memory_restart_running') : t('settings_memory_restart')}
        </button>
        {lettaRestartMsg && (
          <span
            className={lettaRestartMsg.startsWith('✓') ? 'badge badge-green' : ''}
            style={
              lettaRestartMsg.startsWith('✗')
                ? { color: 'var(--red)', fontSize: '.8rem' }
                : { fontSize: '.8rem' }
            }
          >
            {lettaRestartMsg}
          </span>
        )}
      </div>

      <div style={{ marginTop: '8px', fontSize: '.78rem', color: 'var(--muted)' }}>
        {t('settings_memory_note')}
      </div>
      <div style={{ marginTop: '4px', fontSize: '.78rem', color: 'var(--muted)' }}>
        {t('settings_memory_key_note')}
      </div>
    </Card>
  );
}
