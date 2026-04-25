import type { CSSProperties } from 'react';
import { useCallback, useEffect, useState } from 'react';
import { useI18n } from '../../i18n';
import { useAppContext } from '../../context/AppContext';
import {
  fetchSettings,
  saveSettings as apiSaveSettings,
  fetchSkills,
  fetchPartitions,
  fetchCheckpoints,
  deleteCheckpoint,
  testSSH as apiTestSSH,
  generateConfig,
  fetchContainerInfo,
  restartLetta,
} from '../../services/api';
import type { Checkpoint } from '../../types';
import { Card } from '../common';

// ── provider models (same as dashboard.js) ───────────

const DEFAULT_PROVIDER = 'openai';

const PROVIDER_MODELS: Record<string, string[]> = {
  openai: ['gpt-5.2', 'gpt-4o', 'gpt-4o-mini', 'o3', 'o1-mini'],
  anthropic: ['claude-opus-4-5', 'claude-sonnet-4-5', 'claude-3-5-haiku-latest'],
  gemini: ['gemini/gemini-2.5-pro', 'gemini/gemini-2.0-flash', 'gemini/gemini-1.5-pro'],
  ollama: ['ollama_chat/llama3.3', 'ollama_chat/qwen3:8b', 'ollama_chat/gemma3:9b', 'ollama_chat/mistral'],
};

const PROVIDER_KEY_PLACEHOLDER: Record<string, string> = {
  openai: 'sk-...',
  anthropic: 'sk-ant-...',
  gemini: 'AIza...',
  ollama: '(not required)',
};

// ── Memory (Letta) — provider × model picker ────────
//
// Letta freezes the agent's embedding_config at agent creation. The
// default ``letta/letta-free`` handle routes through the MemGPT-hosted
// embeddings.memgpt.ai endpoint and intermittently returns 522/empty
// body — Letta then surfaces this as a 400 with the misleading
// "Expecting value: line 1 column 1 (char 0)" message. We expose
// per-provider model lists here so the operator can pick a known-good
// combination and warn when letta-free is selected.
//
// Handles are stored on settings.json as ``provider/model`` strings,
// matching what Letta's SDK (and ari_skill_memory.MemoryConfig)
// expects. Some providers use a different prefix for chat models
// (e.g. ``ollama_chat/`` vs ``ollama/``) — kept on each entry.
type LettaModelEntry = { handle: string; label?: string };
type LettaProviderTable = Record<string, LettaModelEntry[]>;

const LETTA_EMBEDDING_BY_PROVIDER: LettaProviderTable = {
  openai: [
    { handle: 'openai/text-embedding-3-small', label: 'text-embedding-3-small (recommended)' },
    { handle: 'openai/text-embedding-3-large', label: 'text-embedding-3-large' },
    { handle: 'openai/text-embedding-ada-002', label: 'text-embedding-ada-002' },
  ],
  gemini: [
    { handle: 'gemini/text-embedding-004', label: 'text-embedding-004' },
  ],
  ollama: [
    { handle: 'ollama/nomic-embed-text', label: 'nomic-embed-text (local)' },
    { handle: 'ollama/mxbai-embed-large', label: 'mxbai-embed-large (local)' },
    { handle: 'ollama/all-minilm', label: 'all-minilm (local)' },
  ],
  letta: [
    { handle: 'letta/letta-free', label: 'letta-free (external; flaky)' },
    { handle: 'letta-default', label: 'letta-default (resolves to letta-free)' },
  ],
};

// The Letta agent's chat LLM is bound to a fixed mock handle
// (letta/letta-free) inside ari-skill-memory because ARI never invokes
// the agent's chat API — only archival_insert / archival_search, which
// use embeddings. So no LLM picker is rendered; only the embedding
// picker below is operator-facing.
const LETTA_EMBED_PROVIDERS = ['openai', 'gemini', 'ollama', 'letta'] as const;

const CUSTOM_HANDLE_VALUE = '__custom__';

function _splitHandle(
  handle: string,
  table: LettaProviderTable,
): { provider: string; model: string } {
  // Find a provider whose entries contain this handle.
  for (const [prov, entries] of Object.entries(table)) {
    if (entries.some((e) => e.handle === handle)) return { provider: prov, model: handle };
  }
  // Try heuristic split on first slash; fall back to "letta" provider.
  if (handle.includes('/')) {
    const prov = handle.split('/')[0];
    if (prov in table) return { provider: prov, model: handle };
  }
  if (handle === 'letta-default') return { provider: 'letta', model: handle };
  return { provider: CUSTOM_HANDLE_VALUE, model: handle };
}

// ── Skill row type ───────────────────────────────────

interface SkillInfo {
  name: string;
  display_name: string;
  description: string;
  requires_env?: string[];
}

// ── Component ────────────────────────────────────────

export default function SettingsPage() {
  const { t, setLanguage, currentLang } = useI18n();
  const { state: appState, refreshCheckpoints } = useAppContext();

  // LLM
  const [provider, setProvider] = useState(DEFAULT_PROVIDER);
  const [modelSelect, setModelSelect] = useState('');
  const [modelCustom, setModelCustom] = useState('');
  const [temperature, setTemperature] = useState(1.0);
  const [apiKey, setApiKey] = useState('');
  const [baseUrl, setBaseUrl] = useState('');

  // Paper
  const [ssKey, setSsKey] = useState('');
  const [retrievalBackend, setRetrievalBackend] = useState('semantic_scholar');

  // SLURM
  const [partitions, setPartitions] = useState<{ name: string; nodes: number; cpus: number }[]>([]);
  const [selectedPartitions, setSelectedPartitions] = useState<string[]>([]);
  const [cpus, setCpus] = useState(8);
  const [memGb, setMemGb] = useState(32);
  const [walltime, setWalltime] = useState('04:00:00');

  // SSH
  const [sshHost, setSshHost] = useState('');
  const [sshPort, setSshPort] = useState(22);
  const [sshUser, setSshUser] = useState('');
  const [sshPath, setSshPath] = useState('');
  const [sshKeyPath, setSshKeyPath] = useState('');
  const [sshStatus, setSshStatus] = useState('');

  // Container
  const [containerMode, setContainerMode] = useState('auto');
  const [containerImage, setContainerImage] = useState('');
  const [containerPull, setContainerPull] = useState('on_start');
  const [containerRuntime, setContainerRuntime] = useState('');
  const [containerVersion, setContainerVersion] = useState('');

  // VLM Review
  const [vlmReviewModel, setVlmReviewModel] = useState('openai/gpt-4o');

  // Memory (Letta)
  const [lettaBaseUrl, setLettaBaseUrl] = useState('http://localhost:8283');
  const [lettaApiKey, setLettaApiKey] = useState('');
  // Two-stage picker: provider, then model. Storage stays as a flat
  // ``provider/model`` handle string in settings.json so the env
  // propagation (LETTA_EMBEDDING_CONFIG / LETTA_LLM_CONFIG) doesn't change.
  const [lettaEmbedProvider, setLettaEmbedProvider] = useState('openai');
  const [lettaEmbedModel, setLettaEmbedModel] = useState(
    'openai/text-embedding-3-small'
  );
  const [lettaEmbedCustom, setLettaEmbedCustom] = useState('');
  // Deployment selector — values match _api_memory_start_local's `path`
  // contract (auto/docker/singularity/pip). "auto" delegates to
  // _detect_deployment(); the other three force a specific path so the
  // user can override the detector when e.g. docker is on PATH but the
  // daemon socket isn't reachable.
  const [lettaDeployment, setLettaDeployment] = useState<
    'auto' | 'docker' | 'singularity' | 'pip'
  >('auto');
  // Restart UX: single-flight state; status text + last result.
  const [lettaRestarting, setLettaRestarting] = useState(false);
  const [lettaRestartMsg, setLettaRestartMsg] = useState('');

  // Skills
  const [skills, setSkills] = useState<SkillInfo[]>([]);

  // Project management
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>([]);

  // Status
  const [statusMsg, setStatusMsg] = useState('');

  // Language (synced with i18n)
  const [lang, setLang] = useState(currentLang);

  // ── Load settings on mount ─────────────

  const loadSettings = useCallback(async () => {
    try {
      const r = await fetchSettings();
      const savedLang = localStorage.getItem('ari_lang') || r.language || 'ja';
      setLang(savedLang);

      const prov = r.llm_backend || r.llm_provider || DEFAULT_PROVIDER;
      setProvider(prov);
      setModelCustom(r.llm_model || '');
      setModelSelect(r.llm_model || '');
      setTemperature(r.temperature || 1.0);
      setApiKey(r.llm_api_key || '');
      setBaseUrl(r.ollama_host || '');
      setSsKey(r.semantic_scholar_key || '');
      setRetrievalBackend(r.retrieval_backend || 'semantic_scholar');
      setSshHost(r.ssh_host || '');
      setSshPort(r.ssh_port || 22);
      setSshUser(r.ssh_user || '');
      setSshPath(r.ssh_path || '');
      setSshKeyPath(r.ssh_key || '');
      setSelectedPartitions(r.slurm_partitions || (r.slurm_partition ? [r.slurm_partition] : []));
      setCpus(r.slurm_cpus || 8);
      setMemGb(r.slurm_memory_gb || 32);
      setWalltime(r.slurm_walltime || '04:00:00');
      setContainerMode(r.container_mode || 'auto');
      setContainerImage(r.container_image || '');
      setContainerPull(r.container_pull || 'on_start');
      setVlmReviewModel(r.vlm_review_model || 'openai/gpt-4o');
      // Memory (Letta): split the saved flat handle back into a
      // (provider, model) pair so the two-stage picker shows what's
      // currently in effect. Unknown handles drop to "custom" so the
      // operator can keep / edit them without losing the value.
      setLettaBaseUrl(r.letta_base_url || 'http://localhost:8283');
      setLettaApiKey(r.letta_api_key || '');
      const savedEmb = r.letta_embedding_config || 'openai/text-embedding-3-small';
      const embSplit = _splitHandle(savedEmb, LETTA_EMBEDDING_BY_PROVIDER);
      setLettaEmbedProvider(embSplit.provider);
      setLettaEmbedModel(embSplit.model);
      setLettaEmbedCustom(savedEmb);
    } catch {
      // ignore
    }
  }, []);

  const loadSkills = useCallback(async () => {
    try {
      const s = await fetchSkills();
      setSkills(s || []);
    } catch {
      setSkills([]);
    }
  }, []);

  const loadProjects = useCallback(async () => {
    try {
      const ckpts = await fetchCheckpoints();
      setCheckpoints(ckpts || []);
    } catch {
      setCheckpoints([]);
    }
  }, []);

  useEffect(() => {
    loadSettings();
    loadSkills();
    loadProjects();
  }, [loadSettings, loadSkills, loadProjects]);

  // ── Provider change ────────────────────

  function handleProviderChange(newProv: string) {
    setProvider(newProv);
    const models = PROVIDER_MODELS[newProv] || PROVIDER_MODELS[DEFAULT_PROVIDER];
    if (models.length) {
      setModelSelect(models[0]);
      setModelCustom(models[0]);
    }
  }

  // ── model from select ──────────────────

  function handleModelSelectChange(val: string) {
    setModelSelect(val);
    if (val !== '__custom__') {
      setModelCustom(val);
    }
  }

  // ── Available models for current provider
  const currentModels = PROVIDER_MODELS[provider] || PROVIDER_MODELS[DEFAULT_PROVIDER];

  // ── Partition detection ────────────────

  async function handleDetectPartitions() {
    try {
      const r = await fetchPartitions();
      if (r && r.length) {
        setPartitions(r as any);
      } else {
        setPartitions([]);
      }
    } catch {
      setPartitions([]);
    }
  }

  // ── Save ───────────────────────────────

  async function handleSave() {
    const model =
      modelSelect && modelSelect !== '__custom__' ? modelSelect : modelCustom || '';

    const lettaEmbedding =
      lettaEmbedProvider === CUSTOM_HANDLE_VALUE
        ? lettaEmbedCustom.trim()
        : lettaEmbedModel;

    const data: Record<string, unknown> = {
      llm_model: model,
      llm_backend: provider,
      llm_base_url: baseUrl,
      temperature,
      llm_api_key: apiKey,
      semantic_scholar_key: ssKey,
      retrieval_backend: retrievalBackend,
      ssh_host: sshHost,
      ssh_port: sshPort,
      ssh_user: sshUser,
      ssh_path: sshPath,
      ssh_key: sshKeyPath,
      slurm_partitions: selectedPartitions,
      slurm_partition: selectedPartitions[0] || '',
      slurm_cpus: cpus,
      slurm_memory_gb: memGb,
      slurm_walltime: walltime,
      container_mode: containerMode,
      container_image: containerImage,
      container_pull: containerPull,
      vlm_review_model: vlmReviewModel,
      letta_base_url: lettaBaseUrl.trim(),
      letta_api_key: lettaApiKey,
      letta_embedding_config: lettaEmbedding,
    };

    try {
      const r = await apiSaveSettings(data as any);
      setStatusMsg(r.ok ? '✓ Saved' : r.error || 'Save failed');
    } catch (e) {
      setStatusMsg(String(e));
    }
    setTimeout(() => setStatusMsg(''), 3000);
  }

  // ── Test LLM ───────────────────────────

  async function handleTestLLM() {
    setStatusMsg('⏳ Testing...');
    try {
      const r = await generateConfig('ping');
      setStatusMsg(r.error ? '✗ ' + r.error : '✓ LLM reachable');
    } catch (e) {
      setStatusMsg('✗ ' + String(e));
    }
    setTimeout(() => setStatusMsg(''), 5000);
  }

  // ── Test SSH ───────────────────────────

  async function handleTestSSH() {
    setSshStatus('⏳ Connecting...');
    try {
      const r = await apiTestSSH({ ssh_host: sshHost, ssh_port: sshPort, ssh_user: sshUser, ssh_path: sshPath, ssh_key: sshKeyPath });
      setSshStatus(r.ok ? '✓ Connected — ' + r.info : '✗ ' + (r.error || 'Failed'));
    } catch (e) {
      setSshStatus('✗ ' + String(e));
    }
  }

  // ── Delete project ─────────────────────

  async function handleDeleteProject(id: string, path: string) {
    if (!confirm(`Delete project "${id}"? This cannot be undone.`)) return;
    try {
      const r = await deleteCheckpoint(id, path);
      if (r.ok) {
        loadProjects();
        refreshCheckpoints();
      } else {
        alert('Delete failed: ' + (r.error || 'unknown error'));
      }
    } catch (e) {
      alert('Delete failed: ' + String(e));
    }
  }

  // ── Detect container runtime ────────────

  async function handleDetectRuntime() {
    try {
      const r = await fetchContainerInfo();
      setContainerRuntime(r.runtime || 'none');
      setContainerVersion(r.version || '');
    } catch {
      setContainerRuntime('none');
      setContainerVersion('');
    }
  }

  // ── Language change ────────────────────

  function handleLangChange(newLang: string) {
    setLang(newLang);
    setLanguage(newLang);
  }

  const activeId = appState?.checkpoint_id || '';

  // ── Shared input style ─────────────────

  const inputStyle: CSSProperties = {
    padding: '6px 10px',
    borderRadius: '6px',
    border: '1px solid var(--border)',
    background: 'var(--card)',
    color: 'var(--text)',
    fontSize: '.85rem',
    width: '100%',
  };

  const labelStyle: CSSProperties = {
    fontSize: '.82rem',
    color: 'var(--muted)',
    marginBottom: '4px',
    display: 'block',
  };

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>{t('settings_title')}</h2>

      {/* Status */}
      {statusMsg && (
        <div style={{ marginBottom: '12px' }}>
          <span className={statusMsg.startsWith('✓') ? 'badge badge-green' : ''} style={statusMsg.startsWith('✗') ? { color: 'var(--red)' } : undefined}>
            {statusMsg}
          </span>
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        {/* ── Language ──────────────────────── */}
        <Card title={t('settings_lang_section')}>
          <label style={labelStyle}>{t('settings_lang')}</label>
          <select
            value={lang}
            onChange={(e) => handleLangChange(e.target.value)}
            style={inputStyle}
          >
            <option value="en">English</option>
            <option value="ja">{'日本語'}</option>
            <option value="zh">{'中文'}</option>
          </select>
        </Card>

        {/* ── LLM Backend ──────────────────── */}
        <Card title={t('settings_llm')}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
            {/* Provider */}
            <div>
              <label style={labelStyle}>{t('s_provider')}</label>
              <select
                value={provider}
                onChange={(e) => handleProviderChange(e.target.value)}
                style={inputStyle}
              >
                <option value="openai">openai</option>
                <option value="anthropic">anthropic</option>
                <option value="gemini">gemini</option>
                <option value="ollama">ollama</option>
              </select>
            </div>

            {/* Model dropdown */}
            <div>
              <label style={labelStyle}>{t('s_model')}</label>
              <select
                value={modelSelect}
                onChange={(e) => handleModelSelectChange(e.target.value)}
                style={inputStyle}
              >
                {currentModels.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
                <option value="__custom__">{t('custom_entry')}</option>
              </select>
            </div>

            {/* Custom model input */}
            <div>
              <label style={labelStyle}>{t('settings_default_model')}</label>
              <input
                type="text"
                value={modelCustom}
                onChange={(e) => setModelCustom(e.target.value)}
                placeholder={t('model_custom_placeholder')}
                style={inputStyle}
              />
            </div>

            {/* Temperature */}
            <div>
              <label style={labelStyle}>{t('s_temperature')}</label>
              <input
                type="number"
                step="0.1"
                min="0"
                max="2"
                value={temperature}
                onChange={(e) => setTemperature(parseFloat(e.target.value) || 1.0)}
                style={inputStyle}
              />
            </div>

            {/* API Key (hidden for ollama) */}
            {provider !== 'ollama' && (
              <div>
                <label style={labelStyle}>API Key</label>
                <input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder={PROVIDER_KEY_PLACEHOLDER[provider] || 'api key'}
                  style={inputStyle}
                />
              </div>
            )}

            {/* Base URL (ollama only) */}
            {provider === 'ollama' && (
              <div>
                <label style={labelStyle}>Base URL (Ollama)</label>
                <input
                  type="text"
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  placeholder="http://localhost:11434"
                  style={inputStyle}
                />
              </div>
            )}
          </div>
        </Card>

        {/* ── Paper Retrieval ──────────────── */}
        <Card title={t('settings_paper')}>
          <label style={labelStyle}>Paper Retrieval Backend</label>
          <div style={{ display: 'flex', gap: '16px', marginBottom: '12px' }}>
            {([
              ['semantic_scholar', 'Semantic Scholar'],
              ['alphaxiv', 'AlphaXiv'],
              ['both', 'Both (parallel)'],
            ] as const).map(([val, label]) => (
              <label key={val} style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '.85rem', cursor: 'pointer' }}>
                <input
                  type="radio"
                  name="retrieval_backend"
                  value={val}
                  checked={retrievalBackend === val}
                  onChange={() => setRetrievalBackend(val)}
                />
                {label}
              </label>
            ))}
          </div>
          <label style={labelStyle}>Semantic Scholar API Key</label>
          <input
            type="password"
            value={ssKey}
            onChange={(e) => setSsKey(e.target.value)}
            placeholder="(optional)"
            style={inputStyle}
          />
        </Card>

        {/* ── VLM Figure Review ─────────────── */}
        <Card title="VLM Figure Review">
          <label style={labelStyle}>VLM Model</label>
          <select
            value={vlmReviewModel}
            onChange={(e) => setVlmReviewModel(e.target.value)}
            style={inputStyle}
          >
            {(PROVIDER_MODELS[provider] || PROVIDER_MODELS[DEFAULT_PROVIDER]).map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </Card>

        {/* ── Memory (Letta) ─────────────────── */}
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
                setLettaDeployment(
                  e.target.value as 'auto' | 'docker' | 'singularity' | 'pip',
                )
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

        {/* ── SLURM / HPC ─────────────────── */}
        <Card title={t('settings_slurm')}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
            {/* Partition multi-select */}
            <div style={{ gridColumn: '1 / -1' }}>
              <label style={labelStyle}>
                {t('s_partition')}
                <button
                  className="btn btn-outline btn-sm"
                  style={{ marginLeft: '8px' }}
                  onClick={handleDetectPartitions}
                >
                  Detect
                </button>
              </label>
              {partitions.length > 0 ? (
                <select
                  multiple
                  value={selectedPartitions}
                  onChange={(e) => {
                    const opts = Array.from(e.target.selectedOptions).map((o) => o.value);
                    setSelectedPartitions(opts);
                  }}
                  style={{ ...inputStyle, height: '100px' }}
                >
                  {partitions.map((p) => (
                    <option key={p.name} value={p.name}>
                      {p.name} ({p.nodes} nodes, {p.cpus} cpus)
                    </option>
                  ))}
                </select>
              ) : (
                <div style={{ fontSize: '.78rem', color: 'var(--muted)' }}>
                  {selectedPartitions.length > 0
                    ? selectedPartitions.join(', ')
                    : 'Click Detect to discover partitions'}
                </div>
              )}
            </div>

            {/* CPUs */}
            <div>
              <label style={labelStyle}>{t('s_cpus')}</label>
              <input
                type="number"
                value={cpus}
                onChange={(e) => setCpus(parseInt(e.target.value) || 8)}
                style={inputStyle}
              />
            </div>

            {/* Memory */}
            <div>
              <label style={labelStyle}>Memory (GB)</label>
              <input
                type="number"
                value={memGb}
                onChange={(e) => setMemGb(parseInt(e.target.value) || 32)}
                style={inputStyle}
              />
            </div>

            {/* Walltime */}
            <div>
              <label style={labelStyle}>{t('s_walltime')}</label>
              <input
                type="text"
                value={walltime}
                onChange={(e) => setWalltime(e.target.value)}
                style={inputStyle}
              />
            </div>
          </div>
        </Card>

        {/* ── Container ────────────────────── */}
        <Card title="Container">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
            <div>
              <label style={labelStyle}>Mode</label>
              <select
                value={containerMode}
                onChange={(e) => setContainerMode(e.target.value)}
                style={inputStyle}
              >
                <option value="auto">Auto</option>
                <option value="docker">Docker</option>
                <option value="singularity">Singularity</option>
                <option value="apptainer">Apptainer</option>
                <option value="none">None</option>
              </select>
            </div>
            <div>
              <label style={labelStyle}>Pull Policy</label>
              <select
                value={containerPull}
                onChange={(e) => setContainerPull(e.target.value)}
                style={inputStyle}
              >
                <option value="always">Always</option>
                <option value="on_start">On Start</option>
                <option value="never">Never</option>
              </select>
            </div>
            <div style={{ gridColumn: '1 / -1' }}>
              <label style={labelStyle}>Image</label>
              <input
                type="text"
                value={containerImage}
                onChange={(e) => setContainerImage(e.target.value)}
                placeholder="ghcr.io/kotama7/ari:latest"
                style={inputStyle}
              />
            </div>
            <div style={{ display: 'flex', alignItems: 'flex-end', gap: '8px' }}>
              <button className="btn btn-outline btn-sm" onClick={handleDetectRuntime}>
                Detect Runtime
              </button>
              {containerRuntime && (
                <span
                  className={containerRuntime !== 'none' ? 'badge badge-green' : 'badge'}
                  style={{ fontSize: '.75rem' }}
                >
                  {containerRuntime}
                  {containerRuntime !== 'none' ? ' \u2713' : ''}
                  {containerVersion ? ` (${containerVersion})` : ''}
                </span>
              )}
            </div>
          </div>
        </Card>

        {/* ── Available Skills ─────────────── */}
        <Card title={t('settings_skills')}>
          {skills.length > 0 ? (
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={{ textAlign: 'left', padding: '6px 8px', borderBottom: '1px solid var(--border)', fontSize: '.82rem' }}>
                    {t('skill_label')}
                  </th>
                  <th style={{ textAlign: 'left', padding: '6px 8px', borderBottom: '1px solid var(--border)', fontSize: '.82rem' }}>
                    {t('skill_display_name')}
                  </th>
                  <th style={{ textAlign: 'left', padding: '6px 8px', borderBottom: '1px solid var(--border)', fontSize: '.82rem' }}>
                    Description
                  </th>
                  <th style={{ textAlign: 'left', padding: '6px 8px', borderBottom: '1px solid var(--border)', fontSize: '.82rem' }}>
                    Env
                  </th>
                </tr>
              </thead>
              <tbody>
                {skills.map((s) => (
                  <tr key={s.name}>
                    <td style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)' }}>
                      <code style={{ fontSize: '.78rem' }}>{s.name}</code>
                    </td>
                    <td style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)', fontSize: '.85rem' }}>
                      {s.display_name}
                    </td>
                    <td style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)', fontSize: '.8rem', color: 'var(--muted)' }}>
                      {s.description}
                    </td>
                    <td style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)' }}>
                      {s.requires_env && s.requires_env.length ? (
                        s.requires_env.join(', ')
                      ) : (
                        <span className="badge badge-green" style={{ fontSize: '.7rem' }}>
                          any
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div style={{ color: 'var(--muted)', fontSize: '.85rem' }}>No skill.yaml found</div>
          )}
        </Card>

        {/* ── SSH Remote Host ──────────────── */}
        <Card title={t('settings_ssh')}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
            <div>
              <label style={labelStyle}>Host</label>
              <input
                type="text"
                value={sshHost}
                onChange={(e) => setSshHost(e.target.value)}
                style={inputStyle}
              />
            </div>
            <div>
              <label style={labelStyle}>Port</label>
              <input
                type="number"
                value={sshPort}
                onChange={(e) => setSshPort(parseInt(e.target.value) || 22)}
                style={inputStyle}
              />
            </div>
            <div>
              <label style={labelStyle}>{t('ssh_username')}</label>
              <input
                type="text"
                value={sshUser}
                onChange={(e) => setSshUser(e.target.value)}
                style={inputStyle}
              />
            </div>
            <div>
              <label style={labelStyle}>Remote ARI Path</label>
              <input
                type="text"
                value={sshPath}
                onChange={(e) => setSshPath(e.target.value)}
                style={inputStyle}
              />
            </div>
            <div>
              <label style={labelStyle}>SSH Key Path</label>
              <input
                type="text"
                value={sshKeyPath}
                onChange={(e) => setSshKeyPath(e.target.value)}
                style={inputStyle}
              />
            </div>
            <div style={{ display: 'flex', alignItems: 'flex-end' }}>
              <button className="btn btn-outline btn-sm" onClick={handleTestSSH}>
                Test SSH
              </button>
            </div>
          </div>
          {sshStatus && (
            <div style={{ marginTop: '8px', fontSize: '.82rem' }}>
              <span
                className={sshStatus.startsWith('✓') ? 'badge badge-green' : ''}
                style={sshStatus.startsWith('✗') ? { color: 'var(--red)' } : undefined}
              >
                {sshStatus}
              </span>
            </div>
          )}
        </Card>

        {/* ── Project Management ───────────── */}
        <Card title="Project Management">
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {checkpoints.length > 0 ? (
              checkpoints.map((c) => {
                const isActive = c.id === activeId;
                const isRunning = c.status === 'running';
                const borderColor = isActive ? 'var(--primary)' : 'var(--border)';
                return (
                  <div
                    key={c.id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '12px',
                      padding: '10px 14px',
                      background: 'var(--card)',
                      border: `1px solid ${borderColor}`,
                      borderRadius: '8px',
                    }}
                  >
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div
                        title={c.id}
                        style={{
                          fontSize: '.85rem',
                          fontWeight: 600,
                          color: 'var(--text)',
                          whiteSpace: 'nowrap',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          maxWidth: '360px',
                        }}
                      >
                        {c.id}
                      </div>
                      <div style={{ fontSize: '.75rem', color: 'var(--muted)', marginTop: '2px' }}>
                        {c.node_count} nodes {'·'}{' '}
                        {new Date(c.mtime * 1000).toLocaleString()}
                      </div>
                      <div style={{ marginTop: '4px', display: 'flex', gap: '6px' }}>
                        {isRunning && (
                          <span
                            style={{
                              background: 'rgba(16,185,129,.2)',
                              color: '#10b981',
                              borderRadius: '12px',
                              padding: '2px 8px',
                              fontSize: '.72rem',
                              fontWeight: 700,
                            }}
                          >
                            {'●'} Running
                          </span>
                        )}
                        {isActive && (
                          <span
                            style={{
                              background: 'rgba(59,130,246,.2)',
                              color: '#3b82f6',
                              borderRadius: '12px',
                              padding: '2px 8px',
                              fontSize: '.72rem',
                              fontWeight: 700,
                            }}
                          >
                            Active
                          </span>
                        )}
                      </div>
                    </div>
                    <button
                      className="btn btn-sm"
                      style={{
                        background: 'rgba(239,68,68,.15)',
                        color: '#ef4444',
                        border: '1px solid rgba(239,68,68,.3)',
                        whiteSpace: 'nowrap',
                      }}
                      onClick={() => handleDeleteProject(c.id, c.path)}
                    >
                      {'🗑'} Delete
                    </button>
                  </div>
                );
              })
            ) : (
              <span style={{ color: 'var(--muted)' }}>No projects found.</span>
            )}
          </div>
        </Card>

        {/* ── Action buttons ───────────────── */}
        <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
          <button className="btn btn-primary" onClick={handleSave}>
            {t('btn_save')}
          </button>
          <button className="btn btn-outline" onClick={handleTestLLM}>
            {t('btn_test_llm')}
          </button>
        </div>
      </div>
    </div>
  );
}
