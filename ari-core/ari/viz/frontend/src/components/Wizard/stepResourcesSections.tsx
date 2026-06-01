// ARI Dashboard – Wizard StepResources presentational layer.
// Extracted verbatim from StepResources.tsx (refactor req 15, follow-up to 03):
// the ORS provider model tables + inferOrsProvider helper (used only here), and
// the OrsModelPicker + FewshotManager subcomponents. StepResources.tsx imports
// OrsModelPicker + FewshotManager from here.

import React, { useState, useEffect, useCallback } from 'react';
import { useI18n } from '../../i18n';
import * as api from '../../services/api';

type OrsProvider = 'openai' | 'anthropic' | 'google' | 'ollama' | 'custom';

const ORS_PROVIDER_MODELS: Record<OrsProvider, string[]> = {
  openai: [
    'gpt-5.4',
    'gpt-5.2',
    'gpt-5.4-mini',
    'gpt-4o-2024-11-20',
    'gpt-4o-2024-08-06',
    'gpt-4o',
    'gpt-4o-mini',
    'o3',
    'o1-mini',
  ],
  anthropic: [
    'claude-opus-4-7',
    'claude-opus-4-5',
    'claude-sonnet-4-5',
    'claude-haiku-3-5',
  ],
  google: ['gemini-2.5-pro', 'gemini-2.0-flash', 'gemini-1.5-pro'],
  ollama: ['qwen3:8b', 'qwen3:32b', 'llama3.3', 'gemma3:27b', 'mistral'],
  custom: [],
};

const ORS_PROVIDER_LABELS: Record<OrsProvider, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  google: 'Google',
  ollama: 'Ollama (local)',
  custom: 'Custom',
};

function inferOrsProvider(model: string): OrsProvider {
  if (!model) return 'custom';
  for (const provider of [
    'openai',
    'anthropic',
    'google',
    'ollama',
  ] as const) {
    if (ORS_PROVIDER_MODELS[provider].includes(model)) return provider;
  }
  if (model.startsWith('claude-')) return 'anthropic';
  if (model.startsWith('gpt-') || /^o[1-9]/.test(model)) return 'openai';
  if (model.startsWith('gemini-')) return 'google';
  return 'custom';
}

export function OrsModelPicker({
  label,
  help,
  value,
  onChange,
}: {
  label: string;
  help: string;
  value: string;
  onChange: (v: string) => void;
}) {
  const [provider, setProvider] = useState<OrsProvider>(() =>
    inferOrsProvider(value),
  );
  const list = ORS_PROVIDER_MODELS[provider];
  const inList = list.includes(value);
  const customMode = provider === 'custom' || !inList;

  const handleProviderChange = (p: OrsProvider) => {
    setProvider(p);
    if (p !== 'custom') {
      const models = ORS_PROVIDER_MODELS[p];
      if (models.length > 0) onChange(models[0]);
    }
  };

  const handleModelChange = (m: string) => {
    if (m === '__custom__') {
      onChange('');
    } else {
      onChange(m);
    }
  };

  return (
    <div>
      <label style={{ fontSize: '.75rem', color: 'var(--muted)' }}>
        {label}
      </label>
      <div style={{ fontSize: '.7rem', color: 'var(--muted)' }}>{help}</div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 2fr',
          gap: 6,
          marginTop: 4,
        }}
      >
        <select
          className="input-sm"
          value={provider}
          onChange={(e) => handleProviderChange(e.target.value as OrsProvider)}
        >
          {(
            ['openai', 'anthropic', 'google', 'ollama', 'custom'] as OrsProvider[]
          ).map((p) => (
            <option key={p} value={p}>
              {ORS_PROVIDER_LABELS[p]}
            </option>
          ))}
        </select>
        {customMode ? (
          <input
            className="input-sm"
            type="text"
            value={value}
            placeholder="model name (e.g. local-llama)"
            onChange={(e) => onChange(e.target.value)}
          />
        ) : (
          <select
            className="input-sm"
            value={value}
            onChange={(e) => handleModelChange(e.target.value)}
          >
            {list.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
            <option value="__custom__">{'Custom…'}</option>
          </select>
        )}
      </div>
    </div>
  );
}


// ── Few-shot examples manager (embedded in Step 3) ─────────────────────
export function FewshotManager({ rubricId }: { rubricId: string }) {
  const { t } = useI18n();
  const [listing, setListing] = useState<api.FewshotListing | null>(null);
  const [busy, setBusy] = useState('');
  const [msg, setMsg] = useState('');

  const refresh = useCallback(() => {
    if (!rubricId) return;
    api
      .fetchFewshot(rubricId)
      .then(setListing)
      .catch((e) => setMsg(String(e)));
  }, [rubricId]);

  useEffect(() => {
    refresh();
  }, [rubricId, refresh]);

  const [showUpload, setShowUpload] = useState(false);
  const [uploadId, setUploadId] = useState('');
  const [uploadJson, setUploadJson] = useState('');
  const [uploadTxt, setUploadTxt] = useState('');
  const [uploadPdfB64, setUploadPdfB64] = useState('');

  const handleSync = async () => {
    setBusy('sync');
    setMsg('');
    try {
      const r = await api.syncFewshot(rubricId);
      if (r?.error) setMsg(String(r.error));
      else {
        const base = `${t('wiz_fewshot_sync_ok')} (rc=${r.returncode})`;
        setMsg(r.hint ? `${base} — ${r.hint}` : base);
        refresh();
      }
    } catch (e: any) {
      setMsg(e?.message || String(e));
    } finally {
      setBusy('');
    }
  };

  const handlePdfChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || '');
      const b64 = result.includes(',') ? result.split(',')[1] : result;
      setUploadPdfB64(b64);
    };
    reader.readAsDataURL(f);
  };

  const handleUpload = async () => {
    if (!uploadId.trim() || !uploadJson.trim()) {
      setMsg(t('wiz_fewshot_upload_missing'));
      return;
    }
    setBusy('upload');
    setMsg('');
    try {
      const r = await api.uploadFewshot(rubricId, {
        example_id: uploadId.trim(),
        review_json: uploadJson,
        paper_txt: uploadTxt || undefined,
        paper_pdf: uploadPdfB64 || undefined,
      });
      if (r?.error) setMsg(String(r.error));
      else {
        setMsg(t('wiz_fewshot_upload_ok'));
        setShowUpload(false);
        setUploadId('');
        setUploadJson('');
        setUploadTxt('');
        setUploadPdfB64('');
        refresh();
      }
    } catch (e: any) {
      setMsg(e?.message || String(e));
    } finally {
      setBusy('');
    }
  };

  const handleDelete = async (eid: string) => {
    if (!confirm(`${t('wiz_fewshot_delete_confirm')} ${eid}?`)) return;
    setBusy('delete');
    try {
      await api.deleteFewshot(rubricId, eid);
      refresh();
    } catch (e: any) {
      setMsg(e?.message || String(e));
    } finally {
      setBusy('');
    }
  };

  return (
    <div
      style={{
        marginTop: 14,
        padding: 10,
        border: '1px dashed var(--border, #333)',
        borderRadius: 6,
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 6,
        }}
      >
        <div style={{ fontSize: '.8rem', fontWeight: 700 }}>
          {t('wiz_fewshot_examples')} ({listing?.count ?? '—'})
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          <button
            className="btn btn-sm btn-outline"
            type="button"
            disabled={!!busy}
            onClick={handleSync}
            title={t('wiz_fewshot_sync_title')}
          >
            {busy === 'sync' ? '…' : '↻'} {t('wiz_fewshot_sync')}
          </button>
          <button
            className="btn btn-sm btn-outline"
            type="button"
            disabled={!!busy}
            onClick={() => setShowUpload(!showUpload)}
          >
            {'＋'} {t('wiz_fewshot_upload')}
          </button>
        </div>
      </div>

      {listing?.examples && listing.examples.length > 0 ? (
        <div style={{ display: 'grid', gap: 4, fontSize: '.75rem' }}>
          {listing.examples.map((ex) => (
            <div
              key={ex.id}
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '4px 6px',
                background: 'var(--muted-bg, rgba(255,255,255,0.03))',
                borderRadius: 4,
              }}
            >
              <div>
                <span style={{ fontWeight: 600 }}>{ex.id}</span>
                {ex.overall != null && (
                  <span style={{ color: 'var(--muted)' }}> · overall {ex.overall}</span>
                )}
                {ex.decision && (
                  <span style={{ color: 'var(--muted)' }}> · {ex.decision}</span>
                )}
                <span style={{ color: 'var(--muted)' }}>
                  {' '}
                  · {ex.files.map((f) => f.ext).join(', ')}
                </span>
              </div>
              <button
                className="btn btn-sm btn-outline"
                type="button"
                disabled={!!busy}
                onClick={() => handleDelete(ex.id)}
                title={t('wiz_fewshot_delete')}
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ fontSize: '.75rem', color: 'var(--muted)' }}>
          {t('wiz_fewshot_empty')}
        </div>
      )}

      {showUpload && (
        <div
          style={{
            marginTop: 10,
            padding: 8,
            border: '1px solid var(--border, #333)',
            borderRadius: 4,
            display: 'grid',
            gap: 6,
          }}
        >
          <label style={{ fontSize: '.7rem', color: 'var(--muted)' }}>
            {t('wiz_fewshot_upload_id')}
          </label>
          <input
            className="input-sm"
            value={uploadId}
            onChange={(e) => setUploadId(e.target.value)}
            placeholder="my_paper_2026"
          />
          <label style={{ fontSize: '.7rem', color: 'var(--muted)' }}>
            {t('wiz_fewshot_upload_json')}
          </label>
          <textarea
            className="input-sm"
            value={uploadJson}
            onChange={(e) => setUploadJson(e.target.value)}
            rows={6}
            placeholder='{"soundness": 3, "presentation": 3, "contribution": 3, "overall": 6, "confidence": 4, "strengths": "...", "weaknesses": "...", "questions": "...", "decision": "accept"}'
            style={{ width: '100%', fontFamily: 'monospace', fontSize: '.7rem' }}
          />
          <label style={{ fontSize: '.7rem', color: 'var(--muted)' }}>
            {t('wiz_fewshot_upload_txt')}
          </label>
          <textarea
            className="input-sm"
            value={uploadTxt}
            onChange={(e) => setUploadTxt(e.target.value)}
            rows={3}
            placeholder="Paper excerpt / abstract …"
            style={{ width: '100%', fontSize: '.7rem' }}
          />
          <label style={{ fontSize: '.7rem', color: 'var(--muted)' }}>
            {t('wiz_fewshot_upload_pdf')}
          </label>
          <input type="file" accept="application/pdf" onChange={handlePdfChange} />
          <div style={{ display: 'flex', gap: 6 }}>
            <button
              className="btn btn-sm btn-primary"
              type="button"
              disabled={!!busy}
              onClick={handleUpload}
            >
              {busy === 'upload' ? '…' : t('wiz_fewshot_upload_submit')}
            </button>
            <button
              className="btn btn-sm btn-outline"
              type="button"
              onClick={() => setShowUpload(false)}
            >
              {t('wiz_fewshot_upload_cancel')}
            </button>
          </div>
        </div>
      )}

      {msg && (
        <div style={{ marginTop: 6, fontSize: '.7rem', color: 'var(--muted)' }}>
          {msg}
        </div>
      )}
    </div>
  );
}
