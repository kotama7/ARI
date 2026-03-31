import { useState, useEffect, useCallback } from 'react';
import { useI18n } from '../../i18n';
import * as api from '../../services/api';

const PROVIDER_MODELS: Record<string, string[]> = {
  openai: ['gpt-5.2', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-4o', 'gpt-4o-mini', 'o3', 'o1-mini'],
  anthropic: ['claude-opus-4-5', 'claude-sonnet-4-5', 'claude-haiku-3-5'],
  ollama: ['qwen3:8b', 'qwen3:32b', 'llama3.3', 'gemma3:27b', 'mistral'],
  custom: [],
};

const PHASES = ['idea', 'bfts', 'coding', 'eval', 'paper', 'review'] as const;
const PHASE_LABELS: Record<string, string> = {
  idea: '💡 Idea',
  bfts: '🔬 BFTS',
  coding: '💻 Coding',
  eval: '📊 Evaluation',
  paper: '📄 Paper',
  review: '🔍 Review',
};

interface DetectedPartition {
  name: string;
  cpus?: number;
  memory?: number;
}

interface GpuOption {
  index: string;
  name: string;
  memory?: string;
}

interface StepResourcesProps {
  mode: string;
  setMode: (m: string) => void;
  llm: string;
  setLlm: (l: string) => void;
  model: string;
  setModel: (m: string) => void;
  customModel: string;
  setCustomModel: (m: string) => void;
  apiKey: string;
  setApiKey: (k: string) => void;
  baseUrl: string;
  setBaseUrl: (u: string) => void;
  ollamaGpu: string;
  setOllamaGpu: (g: string) => void;
  partition: string;
  setPartition: (p: string) => void;
  hpcCpus: string;
  setHpcCpus: (v: string) => void;
  hpcMem: string;
  setHpcMem: (v: string) => void;
  hpcWall: string;
  setHpcWall: (v: string) => void;
  hpcGpus: string;
  setHpcGpus: (v: string) => void;
  phaseModels: Record<string, string>;
  setPhaseModels: (pm: Record<string, string>) => void;
  onBack: () => void;
  onNext: () => void;
}

export function StepResources({
  mode,
  setMode,
  llm,
  setLlm,
  model,
  setModel,
  customModel,
  setCustomModel,
  apiKey,
  setApiKey,
  baseUrl,
  setBaseUrl,
  ollamaGpu,
  setOllamaGpu,
  partition,
  setPartition,
  hpcCpus,
  setHpcCpus,
  hpcMem,
  setHpcMem,
  hpcWall,
  setHpcWall,
  hpcGpus,
  setHpcGpus,
  phaseModels,
  setPhaseModels,
  onBack,
  onNext,
}: StepResourcesProps) {
  const { t } = useI18n();
  const [schedulerLabel, setSchedulerLabel] = useState('detecting…');
  const [schedulerClass, setSchedulerClass] = useState('badge badge-blue');
  const [partitions, setPartitions] = useState<DetectedPartition[]>([]);
  const [gpuOptions, setGpuOptions] = useState<GpuOption[]>([]);
  const [gpuInfo, setGpuInfo] = useState('');
  const [apiKeyStatus, setApiKeyStatus] = useState('');
  const [apiKeyColor, setApiKeyColor] = useState('var(--muted)');
  const [cpuPlaceholder, setCpuPlaceholder] = useState('auto');
  const [memPlaceholder, setMemPlaceholder] = useState('auto');
  const [initialized, setInitialized] = useState(false);

  const handleSetLlm = useCallback(
    (provider: string) => {
      setLlm(provider);
      const models = PROVIDER_MODELS[provider] || [];
      if (models.length > 0) {
        setModel(models[0]);
      }
    },
    [setLlm, setModel],
  );

  // Initialize: detect scheduler, load settings, auto-read API key
  useEffect(() => {
    if (initialized) return;
    setInitialized(true);

    // Detect scheduler
    api
      .detectScheduler()
      .then((r) => {
        setSchedulerLabel(r.scheduler);
        setSchedulerClass(
          r.scheduler !== 'none' ? 'badge badge-green' : 'badge badge-muted',
        );
        const parts = r.partitions || [];
        setPartitions(parts);
        if (parts.length > 0) {
          const first = parts[0];
          const cpus = parseInt(String(first.cpus)) || 0;
          if (cpus >= 2) setCpuPlaceholder('auto (' + cpus + ' CPUs)');
          const memMb = parseInt(String(first.memory)) || 0;
          const memGb = Math.round(memMb / 1024);
          if (memGb >= 1) setMemPlaceholder('auto (' + memGb + ' GB)');
        }
      })
      .catch(() => {
        setSchedulerLabel('none');
        setSchedulerClass('badge badge-muted');
      });

    // Pre-populate from settings
    api
      .fetchSettings()
      .then((s) => {
        const prov = s.llm_provider || s.llm_backend || 'openai';
        handleSetLlm(prov);

        const mdl = s.llm_model || '';
        if (mdl) {
          const models = PROVIDER_MODELS[prov] || [];
          if (models.includes(mdl)) {
            setModel(mdl);
          } else {
            setCustomModel(mdl);
          }
        }

        if (s.ollama_host) setBaseUrl(s.ollama_host);
        if (s.slurm_cpus) setHpcCpus(String(s.slurm_cpus));
        if (s.slurm_memory_gb) setHpcMem(String(s.slurm_memory_gb));
        if (s.slurm_walltime) setHpcWall(s.slurm_walltime);
      })
      .catch(() => {});

    // Auto-read API key
    autoReadApiKey();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialized]);

  // Load Ollama resources when provider is ollama
  useEffect(() => {
    if (llm === 'ollama') {
      api
        .fetchOllamaResources()
        .then((r) => {
          const gpus = r.gpus || [];
          setGpuOptions(gpus);
          const nGpu = gpus.filter(
            (g: GpuOption) => g.index !== 'auto' && g.index !== 'cpu',
          ).length;
          setGpuInfo(
            nGpu > 0
              ? nGpu + ' GPU(s) detected'
              : 'No CUDA GPU — CPU/Auto available',
          );
        })
        .catch(() => {
          setGpuOptions([]);
          setGpuInfo('');
        });
    }
  }, [llm]);

  const autoReadApiKey = async () => {
    const keyMap: Record<string, string> = {
      openai: 'OPENAI_API_KEY',
      anthropic: 'ANTHROPIC_API_KEY',
      google: 'GOOGLE_API_KEY',
    };
    try {
      const r = await api.fetchEnvKeys();
      const envKey = keyMap[llm];
      const val = envKey ? (r.keys[envKey] || '') : '';
      if (val) {
        setApiKey(val);
        setApiKeyStatus('✓ Loaded from .env (' + (envKey || '') + ')');
        setApiKeyColor('var(--green)');
      } else {
        setApiKeyStatus(
          llm === 'ollama' ? '' : 'Not found in .env — enter manually',
        );
        setApiKeyColor('var(--muted)');
      }
    } catch {
      setApiKeyStatus('');
      setApiKeyColor('var(--muted)');
    }
  };

  const handlePartitionChange = (partName: string) => {
    setPartition(partName);
    if (!partitions.length) return;
    const p = partName
      ? partitions.find((x) => x.name === partName)
      : partitions[0];
    if (!p) return;
    if (!hpcCpus) {
      const cpus = parseInt(String(p.cpus)) || 0;
      setCpuPlaceholder(cpus >= 2 ? 'auto (' + cpus + ' CPUs)' : 'auto');
    }
    if (!hpcMem) {
      const m = Math.round((parseInt(String(p.memory)) || 0) / 1024);
      setMemPlaceholder(m >= 1 ? 'auto (' + m + ' GB)' : 'auto');
    }
  };

  const currentModels = PROVIDER_MODELS[llm] || [];
  const isFreeEntry = llm === 'ollama' || llm === 'custom';

  const handlePhaseModelChange = (phase: string, value: string) => {
    const pm = { ...phaseModels };
    if (value) {
      pm[phase] = value;
    } else {
      delete pm[phase];
    }
    setPhaseModels(pm);
  };

  return (
    <div>
      {/* Environment card */}
      <div className="card">
        <div className="card-title">{t('wiz_env_title')}</div>
        <div className="form-row">
          <label>{t('wiz_mode_label')}</label>
          <div className="toggle-group" style={{ maxWidth: 300 }}>
            <div
              className={`toggle-btn${mode === 'laptop' ? ' active' : ''}`}
              onClick={() => setMode('laptop')}
            >
              {'💻'} Laptop
            </div>
            <div
              className={`toggle-btn${mode === 'hpc' ? ' active' : ''}`}
              onClick={() => setMode('hpc')}
            >
              {'🖥'} HPC / Cluster
            </div>
          </div>
        </div>

        {/* HPC options */}
        {mode === 'hpc' && (
          <div>
            <div className="form-row">
              <label>
                Detected scheduler:{' '}
                <span className={schedulerClass}>{schedulerLabel}</span>
              </label>
            </div>
            <div className="form-row">
              <label>{t('s_partition')}</label>
              <select
                value={partition}
                onChange={(e) => handlePartitionChange(e.target.value)}
              >
                <option value="">auto-detect</option>
                {partitions.map((p) => (
                  <option key={p.name} value={p.name}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>
            <div
              style={{
                display: 'flex',
                gap: 12,
                flexWrap: 'wrap',
                marginTop: 8,
              }}
            >
              <div className="form-row" style={{ flex: 1, minWidth: 110 }}>
                <label>CPUs</label>
                <input
                  type="number"
                  value={hpcCpus}
                  placeholder={cpuPlaceholder}
                  min={1}
                  max={256}
                  style={{ width: '100%' }}
                  onChange={(e) => setHpcCpus(e.target.value)}
                />
              </div>
              <div className="form-row" style={{ flex: 1, minWidth: 110 }}>
                <label>Memory (GB)</label>
                <input
                  type="number"
                  value={hpcMem}
                  placeholder={memPlaceholder}
                  min={1}
                  max={512}
                  style={{ width: '100%' }}
                  onChange={(e) => setHpcMem(e.target.value)}
                />
              </div>
              <div className="form-row" style={{ flex: 1, minWidth: 160 }}>
                <label>Walltime</label>
                <input
                  type="text"
                  value={hpcWall}
                  placeholder="auto"
                  style={{ width: '100%' }}
                  onChange={(e) => setHpcWall(e.target.value)}
                />
              </div>
            </div>
            <div className="form-row" style={{ flex: 1, minWidth: 110 }}>
              <label>GPUs</label>
              <input
                type="number"
                value={hpcGpus}
                placeholder="auto"
                min={0}
                max={16}
                style={{ width: '100%' }}
                onChange={(e) => setHpcGpus(e.target.value)}
              />
            </div>
          </div>
        )}
      </div>

      {/* LLM Configuration card */}
      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-title">{'🤖'} LLM Configuration</div>

        {/* Provider toggle */}
        <div className="form-row">
          <label>Provider</label>
          <div className="toggle-group">
            {['openai', 'anthropic', 'ollama', 'custom'].map((p) => (
              <div
                key={p}
                className={`toggle-btn${llm === p ? ' active' : ''}`}
                onClick={() => handleSetLlm(p)}
              >
                {p === 'openai'
                  ? 'OpenAI'
                  : p === 'anthropic'
                    ? 'Anthropic'
                    : p === 'ollama'
                      ? 'Ollama'
                      : 'Custom'}
              </div>
            ))}
          </div>
        </div>

        {/* Model selection */}
        <div className="form-row">
          <label>Model</label>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, flex: 1 }}>
            <select
              value={model}
              style={{ width: '100%' }}
              onChange={(e) => setModel(e.target.value)}
            >
              {currentModels.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
              {isFreeEntry && (
                <option value="__custom__">{t('custom_entry')}</option>
              )}
            </select>
            {isFreeEntry && (
              <input
                type="text"
                value={customModel}
                placeholder={t('model_custom_placeholder')}
                style={{ width: '100%' }}
                onChange={(e) => setCustomModel(e.target.value)}
              />
            )}
          </div>
        </div>

        {/* API Key (hidden for ollama) */}
        {llm !== 'ollama' && (
          <div className="form-row">
            <label>API Key</label>
            <div style={{ display: 'flex', gap: 6 }}>
              <input
                type="password"
                value={apiKey}
                placeholder="sk-..."
                style={{ flex: 1 }}
                onChange={(e) => setApiKey(e.target.value)}
              />
              <button
                className="btn btn-outline btn-sm"
                type="button"
                onClick={autoReadApiKey}
              >
                {'🔑'} Auto-read
              </button>
            </div>
            <div
              style={{ fontSize: '.75rem', color: apiKeyColor, marginTop: 3 }}
            >
              {apiKeyStatus}
            </div>
          </div>
        )}

        {/* Base URL (ollama / custom) */}
        {(llm === 'ollama' || llm === 'custom') && (
          <div className="form-row">
            <label>Base URL</label>
            <input
              type="text"
              value={baseUrl}
              placeholder="http://localhost:11434"
              onChange={(e) => setBaseUrl(e.target.value)}
            />
          </div>
        )}

        {/* GPU select (ollama) */}
        {llm === 'ollama' && (
          <div className="form-row">
            <label>GPU</label>
            <select
              value={ollamaGpu}
              onChange={(e) => setOllamaGpu(e.target.value)}
            >
              {gpuOptions.length > 0 ? (
                gpuOptions.map((g) => {
                  const lbl =
                    g.index === 'auto'
                      ? 'Auto (let Ollama decide)'
                      : g.index === 'cpu'
                        ? 'CPU only'
                        : 'GPU ' +
                          g.index +
                          ': ' +
                          g.name +
                          (g.memory ? ' (' + g.memory + ')' : '');
                  const val =
                    g.index === 'auto'
                      ? ''
                      : g.index === 'cpu'
                        ? 'cpu'
                        : 'CUDA_VISIBLE_DEVICES=' + g.index;
                  return (
                    <option key={g.index} value={val}>
                      {lbl}
                    </option>
                  );
                })
              ) : (
                <>
                  <option value="">Auto</option>
                  <option value="cpu">CPU only</option>
                </>
              )}
            </select>
            <div
              style={{ fontSize: '.75rem', color: 'var(--muted)', marginTop: 3 }}
            >
              {gpuInfo}
            </div>
          </div>
        )}

        {/* Per-phase model override (Advanced) */}
        <details style={{ marginTop: 12 }}>
          <summary
            style={{
              cursor: 'pointer',
              fontSize: '.8rem',
              color: 'var(--muted)',
              fontWeight: 600,
              userSelect: 'none',
            }}
          >
            {'⚙'} Per-Phase Model Override (Advanced)
          </summary>
          <div
            style={{
              marginTop: 10,
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: 8,
            }}
          >
            {PHASES.map((phase) => (
              <div key={phase}>
                <label style={{ fontSize: '.75rem', color: 'var(--muted)' }}>
                  {PHASE_LABELS[phase]}
                </label>
                <select
                  className="input-sm"
                  style={{ width: '100%' }}
                  value={phaseModels[phase] || ''}
                  onChange={(e) => handlePhaseModelChange(phase, e.target.value)}
                >
                  <option value="">default</option>
                  {currentModels.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </div>
            ))}
          </div>
        </details>
      </div>

      {/* Navigation */}
      <div
        style={{ marginTop: 16, display: 'flex', justifyContent: 'space-between' }}
      >
        <button className="btn btn-outline" onClick={onBack}>
          {'←'} Back
        </button>
        <button className="btn btn-primary" onClick={onNext}>
          Next {'→'}
        </button>
      </div>
    </div>
  );
}
