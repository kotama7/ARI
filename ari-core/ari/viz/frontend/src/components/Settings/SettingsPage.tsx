import { useCallback, useEffect, useState } from 'react';
import { useI18n } from '../../i18n';
import { useDevMode } from '../../hooks/useDevMode';
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
} from '../../services/api';
import type { Checkpoint } from '../../types';
import {
  DEFAULT_PROVIDER,
  PROVIDER_MODELS,
  LETTA_EMBEDDING_BY_PROVIDER,
  CUSTOM_HANDLE_VALUE,
  _splitHandle,
} from './settingsConstants';
import type { SkillInfo, LettaDeployment } from './settingsTypes';
import { SettingsGroup } from './SettingsGroup';
import { LanguageSection } from './sections/LanguageSection';
import { LlmBackendSection } from './sections/LlmBackendSection';
import { PaperRetrievalSection } from './sections/PaperRetrievalSection';
import { VlmReviewSection } from './sections/VlmReviewSection';
import { MemorySection } from './sections/MemorySection';
import { SlurmSection } from './sections/SlurmSection';
import { ContainerSection } from './sections/ContainerSection';
import { SkillsSection } from './sections/SkillsSection';
import { SshSection } from './sections/SshSection';
import { ProjectManagementSection } from './sections/ProjectManagementSection';

// ── Orchestrator ─────────────────────────────────────
//
// This container owns ALL load/save orchestration and every piece of local
// state; the `sections/*` components are presentational (props-lifting design,
// subtask 070 §7/§17) so the save payload cannot drift. Progressive disclosure
// (069) is applied by grouping the ten <Card> sections into sensitivity tiers
// via <SettingsGroup>, which collapses tiers with CSS only — it never unmounts
// a card — so the frozen SettingsContract (TEN cards + the 24-key POST) holds.
//
// NOTE: the per-phase model fields (model_idea/bfts/coding/eval/paper/review)
// and vlm_review_enabled/max_iter/threshold declared on the `Settings` type are
// INTENTIONALLY not edited here — they live in Wizard/StepResources.tsx. Do not
// add them to this panel or to handleSave's 24-key object.

export default function SettingsPage() {
  const { t, setLanguage, currentLang } = useI18n();
  const { devMode, setDevMode } = useDevMode();
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
  const [lettaDeployment, setLettaDeployment] = useState<LettaDeployment>('auto');
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
      setBaseUrl(prov === 'cli-shim' ? (r.llm_base_url || '') : (r.ollama_host || ''));
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
        {/* ── Tier 1: Essentials (Primary — always open) ── */}
        <SettingsGroup title={t('settings_group_essentials')} defaultOpen>
          <LanguageSection t={t} lang={lang} onLangChange={handleLangChange} />
          {/* Developer Mode toggle (071). Client-only; persisted in
              localStorage['ari_dev_mode'] via useDevMode — NOT part of the
              24-key /api/settings POST. Rendered as a plain row (no .card-title
              / .settings-group-header) so the SettingsContract (10 cards) and
              SettingsDisclosure (4 groups) invariants are untouched. */}
          <div
            className="dev-mode-toggle"
            style={{ padding: '4px 2px', display: 'flex', flexDirection: 'column', gap: 2 }}
          >
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
              <input
                type="checkbox"
                role="switch"
                aria-checked={devMode}
                checked={devMode}
                onChange={(e) => setDevMode(e.target.checked)}
              />
              <span style={{ fontWeight: 600 }}>{t('settings_devmode_label')}</span>
              <span className="badge badge-muted" style={{ fontSize: '.68rem' }}>
                {t('dev_only_badge')}
              </span>
            </label>
            <div style={{ fontSize: '.75rem', color: 'var(--muted)' }}>
              {t('settings_devmode_help')}
            </div>
          </div>
          <LlmBackendSection
            t={t}
            provider={provider}
            onProviderChange={handleProviderChange}
            modelSelect={modelSelect}
            onModelSelectChange={handleModelSelectChange}
            modelCustom={modelCustom}
            setModelCustom={setModelCustom}
            temperature={temperature}
            setTemperature={setTemperature}
            apiKey={apiKey}
            setApiKey={setApiKey}
            baseUrl={baseUrl}
            setBaseUrl={setBaseUrl}
            currentModels={currentModels}
          />
        </SettingsGroup>

        {/* ── Tier 2: Project (Secondary) ── */}
        <SettingsGroup title={t('settings_group_project')} defaultOpen>
          <PaperRetrievalSection
            t={t}
            retrievalBackend={retrievalBackend}
            setRetrievalBackend={setRetrievalBackend}
            ssKey={ssKey}
            setSsKey={setSsKey}
          />
          <VlmReviewSection
            provider={provider}
            vlmReviewModel={vlmReviewModel}
            setVlmReviewModel={setVlmReviewModel}
          />
        </SettingsGroup>

        {/* ── Tier 3: Infrastructure (Advanced — collapsed by default) ── */}
        <SettingsGroup title={t('settings_group_infrastructure')} defaultOpen={false}>
          <MemorySection
            t={t}
            lettaBaseUrl={lettaBaseUrl}
            setLettaBaseUrl={setLettaBaseUrl}
            lettaApiKey={lettaApiKey}
            setLettaApiKey={setLettaApiKey}
            lettaEmbedProvider={lettaEmbedProvider}
            setLettaEmbedProvider={setLettaEmbedProvider}
            lettaEmbedModel={lettaEmbedModel}
            setLettaEmbedModel={setLettaEmbedModel}
            lettaEmbedCustom={lettaEmbedCustom}
            setLettaEmbedCustom={setLettaEmbedCustom}
            lettaDeployment={lettaDeployment}
            setLettaDeployment={setLettaDeployment}
            lettaRestarting={lettaRestarting}
            setLettaRestarting={setLettaRestarting}
            lettaRestartMsg={lettaRestartMsg}
            setLettaRestartMsg={setLettaRestartMsg}
          />
          <SlurmSection
            t={t}
            partitions={partitions}
            selectedPartitions={selectedPartitions}
            setSelectedPartitions={setSelectedPartitions}
            onDetect={handleDetectPartitions}
            cpus={cpus}
            setCpus={setCpus}
            memGb={memGb}
            setMemGb={setMemGb}
            walltime={walltime}
            setWalltime={setWalltime}
          />
          <ContainerSection
            containerMode={containerMode}
            setContainerMode={setContainerMode}
            containerPull={containerPull}
            setContainerPull={setContainerPull}
            containerImage={containerImage}
            setContainerImage={setContainerImage}
            containerRuntime={containerRuntime}
            containerVersion={containerVersion}
            onDetectRuntime={handleDetectRuntime}
          />
          <SshSection
            t={t}
            sshHost={sshHost}
            setSshHost={setSshHost}
            sshPort={sshPort}
            setSshPort={setSshPort}
            sshUser={sshUser}
            setSshUser={setSshUser}
            sshPath={sshPath}
            setSshPath={setSshPath}
            sshKeyPath={sshKeyPath}
            setSshKeyPath={setSshKeyPath}
            sshStatus={sshStatus}
            onTestSSH={handleTestSSH}
          />
        </SettingsGroup>

        {/* ── Tier 4: Diagnostics & Danger Zone (collapsed; visually distinct) ── */}
        <SettingsGroup title={t('settings_group_diagnostics')} defaultOpen={false} danger>
          <SkillsSection t={t} skills={skills} />
          <ProjectManagementSection
            checkpoints={checkpoints}
            activeId={activeId}
            onDelete={handleDeleteProject}
          />
        </SettingsGroup>

        {/* ── Action buttons (always visible) ── */}
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
