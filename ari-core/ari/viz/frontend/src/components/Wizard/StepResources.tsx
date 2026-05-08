import React, { useState, useEffect, useCallback } from 'react';
import { useI18n } from '../../i18n';
import * as api from '../../services/api';
import type { ContainerImage } from '../../services/api';

export const PROVIDER_MODELS: Record<string, string[]> = {
  openai: ['gpt-5.2', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-4o', 'gpt-4o-2024-08-06', 'gpt-4o-mini', 'o3', 'o1-mini'],
  anthropic: ['claude-opus-4-5', 'claude-sonnet-4-5', 'claude-haiku-3-5'],
  ollama: ['qwen3:8b', 'qwen3:32b', 'llama3.3', 'gemma3:27b', 'mistral'],
  custom: [],
};

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

export interface OrsSettings {
  replicator_model: string;
  rubric_gen_model: string;
  rubric_audit_model: string;
  judge_model: string;
  rubric_gen_temperature: number;
  rubric_gen_target_leaves: number;     // 0 = auto
  rubric_gen_two_stage: boolean;        // skeleton + parallel subtrees
  judge_n_runs: number;                 // PaperBench paper §4.1: single-pass; ari default >1 is independent variance reduction
  phase1_max_runtime_sec: number;       // ARI's reproduce.sh wall cap (ors_run_reproduce)
  phase1_sandbox_kind: 'auto' | 'docker' | 'apptainer' | 'singularity' | 'local';
  // v0.7+ replicator-agent fields. The vendored PaperBench solver
  // (BasicAgent / IterativeAgent) is driven against repro_sandbox/.
  replicator_time_limit_sec: number;    // Agent rollout wall budget (PaperBench §5.2: 12h)
  iterative_agent: boolean;             // PaperBench §5.3: removes early-end, prompts step-by-step
  replicator_max_steps: number;         // 0 = unlimited (only time_limit_sec constrains)
}

export const ORS_DEFAULTS: OrsSettings = {
  replicator_model: 'claude-opus-4-7',
  rubric_gen_model: 'gemini-2.5-pro',
  rubric_audit_model: 'claude-opus-4-7',
  judge_model: 'gpt-4o-2024-11-20',
  rubric_gen_temperature: 0.0,
  rubric_gen_target_leaves: 0,
  rubric_gen_two_stage: true,
  judge_n_runs: 1,                      // PaperBench parity (paper §4.1 single-pass)
  phase1_max_runtime_sec: 43200,        // 12 h, matches paper §2.2 reproduce.sh cap
  phase1_sandbox_kind: 'auto',
  replicator_time_limit_sec: 43200,     // 12 h, matches paper §5.2
  iterative_agent: false,               // BasicAgent default; flip on for IterativeAgent
  replicator_max_steps: 0,              // unbounded; rely on time_limit_sec
};

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
  containerImage: string;
  setContainerImage: (v: string) => void;
  containerMode: string;
  setContainerMode: (v: string) => void;
  vlmReviewModel: string;
  setVlmReviewModel: (v: string) => void;
  rubricId: string;
  setRubricId: (v: string) => void;
  fewshotMode: 'static' | 'dynamic';
  setFewshotMode: (v: 'static' | 'dynamic') => void;
  numReviewsEnsemble: number;
  setNumReviewsEnsemble: (v: number) => void;
  numReflections: number;
  setNumReflections: (v: number) => void;
  ors: OrsSettings;
  setOrs: (o: OrsSettings) => void;
  onBack: () => void;
  onNext: () => void;
}

const RUBRIC_OPTIONS: Array<{ id: string; label: string }> = [
  { id: 'neurips', label: 'NeurIPS (ML/AI, v2-compatible)' },
  { id: 'iclr', label: 'ICLR (ML/AI)' },
  { id: 'icml', label: 'ICML (ML/AI)' },
  { id: 'cvpr', label: 'CVPR / ICCV / ECCV (Computer Vision)' },
  { id: 'acl', label: 'ACL / EMNLP (NLP)' },
  { id: 'sc', label: 'SC (HPC / Systems)' },
  { id: 'chi', label: 'CHI (HCI)' },
  { id: 'usenix_security', label: 'USENIX Security / S&P / CCS (Security)' },
  { id: 'osdi', label: 'OSDI / SOSP / VLDB (Systems & Databases)' },
  { id: 'stoc', label: 'STOC / FOCS / SODA (Theory)' },
  { id: 'icra', label: 'ICRA / IROS / RSS (Robotics)' },
  { id: 'siggraph', label: 'SIGGRAPH / SIGGRAPH Asia (Graphics)' },
  { id: 'nature', label: 'Nature / Science (Natural & Life Sciences)' },
  { id: 'journal_generic', label: 'Generic Journal (revision-cycle)' },
  { id: 'workshop', label: 'Workshop / Short Paper' },
  { id: 'generic_conference', label: 'Generic Conference' },
];

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
  containerImage,
  setContainerImage,
  containerMode,
  setContainerMode,
  vlmReviewModel,
  setVlmReviewModel,
  rubricId,
  setRubricId,
  fewshotMode,
  setFewshotMode,
  numReviewsEnsemble,
  setNumReviewsEnsemble,
  numReflections,
  setNumReflections,
  ors,
  setOrs,
  onBack,
  onNext,
}: StepResourcesProps) {
  const [rubricsFromApi, setRubricsFromApi] = useState<
    Array<{ id: string; label: string }>
  >([]);
  const [closedReviewRubrics, setClosedReviewRubrics] = useState<Set<string>>(
    new Set(),
  );
  useEffect(() => {
    api
      .fetchRubrics()
      .then((rs) => {
        if (Array.isArray(rs) && rs.length > 0) {
          setRubricsFromApi(
            rs.map((r) => ({
              id: r.id,
              label: `${r.id} — ${r.venue}${r.domain ? ` (${r.domain})` : ''}`,
            })),
          );
          setClosedReviewRubrics(
            new Set(rs.filter((r) => r.closed_review).map((r) => r.id)),
          );
        }
      })
      .catch(() => {});
  }, []);
  const isClosedReview = closedReviewRubrics.has(rubricId);
  useEffect(() => {
    if (isClosedReview && fewshotMode === 'dynamic') {
      setFewshotMode('static');
    }
  }, [isClosedReview, fewshotMode, setFewshotMode]);
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
  const [containerImages, setContainerImages] = useState<ContainerImage[]>([]);
  const [containerRuntime, setContainerRuntime] = useState('none');
  const [pullStatus, setPullStatus] = useState('');
  const [pulling, setPulling] = useState(false);
  const [pullImageName, setPullImageName] = useState('');

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

    // NOTE: Settings are loaded ONCE in WizardPage.tsx (`useEffect` with
    // `settingsLoadedRef`) so that user selections survive step navigation.
    // Re-loading them here would clobber the user's manual model selection
    // every time StepResources remounts (e.g. when navigating Launch ↔ Resources).

    // Auto-read API key
    autoReadApiKey();

    // Load container info & images
    api.fetchContainerInfo().then((info) => {
      setContainerRuntime(info.runtime);
    }).catch(() => {});
    loadContainerImages();
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

  const loadContainerImages = async () => {
    try {
      const r = await api.fetchContainerImages();
      setContainerImages(r.images || []);
    } catch {
      setContainerImages([]);
    }
  };

  const handlePull = async () => {
    if (!pullImageName.trim()) return;
    setPulling(true);
    setPullStatus('Pulling…');
    try {
      const r = await api.pullContainerImage(pullImageName.trim(), containerMode);
      if (r.ok) {
        setPullStatus('Pull complete');
        await loadContainerImages();
        setContainerImage(pullImageName.trim());
        setPullImageName('');
      } else {
        setPullStatus('Pull failed: ' + (r.error || 'unknown error'));
      }
    } catch (e: any) {
      setPullStatus('Pull failed: ' + (e.message || 'unknown error'));
    } finally {
      setPulling(false);
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

      {/* Container card */}
      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-title">
          Container
          <span
            className={containerRuntime !== 'none' ? 'badge badge-green' : 'badge badge-muted'}
            style={{ marginLeft: 8, fontSize: '.7rem' }}
          >
            {containerRuntime}
          </span>
        </div>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          <div className="form-row" style={{ flex: 2, minWidth: 200 }}>
            <label>Image</label>
            <select
              value={containerImage}
              style={{ width: '100%' }}
              onChange={(e) => setContainerImage(e.target.value)}
            >
              <option value="">(no container)</option>
              {containerImages.map((img) => (
                <option key={img.name} value={img.name}>
                  {img.name}{img.size ? ` (${img.size})` : ''}
                </option>
              ))}
            </select>
          </div>
          <div className="form-row" style={{ flex: 1, minWidth: 140 }}>
            <label>Mode</label>
            <select
              value={containerMode}
              style={{ width: '100%' }}
              onChange={(e) => setContainerMode(e.target.value)}
            >
              <option value="auto">Auto</option>
              <option value="docker">Docker</option>
              <option value="singularity">Singularity</option>
              <option value="apptainer">Apptainer</option>
              <option value="none">None</option>
            </select>
          </div>
        </div>
        {/* Pull image */}
        <div style={{ marginTop: 10 }}>
          <label style={{ fontSize: '.8rem', color: 'var(--muted)', fontWeight: 600 }}>
            Pull new image
          </label>
          <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
            <input
              type="text"
              value={pullImageName}
              placeholder="e.g. ghcr.io/kotama7/ari:latest"
              style={{ flex: 1 }}
              onChange={(e) => setPullImageName(e.target.value)}
              disabled={pulling}
            />
            <button
              className="btn btn-outline btn-sm"
              type="button"
              onClick={handlePull}
              disabled={pulling || !pullImageName.trim()}
            >
              {pulling ? 'Pulling…' : 'Pull'}
            </button>
          </div>
          {pullStatus && (
            <div style={{
              fontSize: '.75rem',
              marginTop: 3,
              color: pullStatus.startsWith('Pull complete') ? 'var(--green)' : pullStatus.startsWith('Pull failed') ? 'var(--red, #e74c3c)' : 'var(--muted)',
            }}>
              {pullStatus}
            </div>
          )}
        </div>
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

        {/* Advanced LLM Settings */}
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
            {'⚙'} Advanced
          </summary>
          <div style={{ marginTop: 10 }}>
            {/* Per-phase model override */}
            <div style={{ fontSize: '.78rem', fontWeight: 600, color: 'var(--muted)', marginBottom: 6 }}>
              Per-Phase Model Override
            </div>
            <div
              style={{
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

            {/* VLM Figure Review model */}
            <div style={{ borderTop: '1px solid var(--border, #333)', marginTop: 14, paddingTop: 12 }}>
              <div key="vlm">
                <label style={{ fontSize: '.75rem', color: 'var(--muted)' }}>
                  {'🖼'} VLM Figure Review
                </label>
                <select
                  className="input-sm"
                  style={{ width: '100%' }}
                  value={vlmReviewModel}
                  onChange={(e) => setVlmReviewModel(e.target.value)}
                >
                  <option value="">default (gpt-4o)</option>
                  {currentModels.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </div>
            </div>

          </div>
        </details>
      </div>

      {/* ORS Reproducibility Evaluation (PaperBench-format auto rubric) */}
      <div className="card" style={{ marginTop: 16 }}>
        <details open>
          <summary style={{ cursor: 'pointer', fontWeight: 600 }}>
            {'🧪'} {t('ors_section_title')}
          </summary>
          <div style={{ marginTop: 12, display: 'grid', gap: 10 }}>
            <OrsModelPicker
              label={t('ors_replicator_model')}
              help={t('ors_replicator_help')}
              value={ors.replicator_model}
              onChange={(v) => setOrs({ ...ors, replicator_model: v })}
            />

            <div>
              <OrsModelPicker
                label={t('ors_rubric_gen_model')}
                help={t('ors_rubric_gen_help')}
                value={ors.rubric_gen_model}
                onChange={(v) => setOrs({ ...ors, rubric_gen_model: v })}
              />
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 6 }}>
                <div>
                  <label style={{ fontSize: '.7rem', color: 'var(--muted)' }}>
                    Temperature
                  </label>
                  <input
                    className="input-sm"
                    type="number"
                    step="0.1"
                    min={0}
                    max={2}
                    style={{ width: '100%' }}
                    value={ors.rubric_gen_temperature}
                    onChange={(e) =>
                      setOrs({
                        ...ors,
                        rubric_gen_temperature:
                          parseFloat(e.target.value) || 0,
                      })
                    }
                  />
                </div>
                <div>
                  <label style={{ fontSize: '.7rem', color: 'var(--muted)' }}>
                    Target leaves (0 = auto)
                  </label>
                  <input
                    className="input-sm"
                    type="number"
                    min={0}
                    max={400}
                    style={{ width: '100%' }}
                    value={ors.rubric_gen_target_leaves}
                    onChange={(e) =>
                      setOrs({
                        ...ors,
                        rubric_gen_target_leaves:
                          Math.max(0, Math.min(400, parseInt(e.target.value) || 0)),
                      })
                    }
                  />
                </div>
              </div>
              <div style={{ marginTop: 8, display: 'flex', alignItems: 'flex-start', gap: 6 }}>
                <input
                  id="ors-rubric-two-stage"
                  type="checkbox"
                  checked={ors.rubric_gen_two_stage}
                  onChange={(e) =>
                    setOrs({ ...ors, rubric_gen_two_stage: e.target.checked })
                  }
                  style={{ marginTop: 3 }}
                />
                <label htmlFor="ors-rubric-two-stage" style={{ fontSize: '.75rem', lineHeight: 1.4 }}>
                  <div style={{ fontWeight: 500 }}>{t('ors_rubric_two_stage')}</div>
                  <div style={{ color: 'var(--muted)', fontSize: '.7rem', marginTop: 2 }}>
                    {t('ors_rubric_two_stage_help')}
                  </div>
                </label>
              </div>
            </div>

            <OrsModelPicker
              label={t('ors_rubric_audit_model')}
              help={t('ors_rubric_audit_help')}
              value={ors.rubric_audit_model}
              onChange={(v) => setOrs({ ...ors, rubric_audit_model: v })}
            />

            <div>
              <OrsModelPicker
                label={t('ors_judge_model')}
                help={t('ors_judge_help')}
                value={ors.judge_model}
                onChange={(v) => setOrs({ ...ors, judge_model: v })}
              />
              <div style={{ marginTop: 6 }}>
                <label style={{ fontSize: '.7rem', color: 'var(--muted)' }}>
                  {t('ors_judge_n_runs')}
                </label>
                <input
                  className="input-sm"
                  type="number"
                  min={1}
                  max={10}
                  style={{ width: '100%' }}
                  value={ors.judge_n_runs}
                  onChange={(e) =>
                    setOrs({
                      ...ors,
                      judge_n_runs: Math.max(1, Math.min(10, parseInt(e.target.value) || 1)),
                    })
                  }
                />
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              <div>
                <label style={{ fontSize: '.75rem', color: 'var(--muted)' }}>
                  {t('ors_phase1_max_runtime')}
                </label>
                <input
                  className="input-sm"
                  type="number"
                  min={0.1}
                  max={12}
                  step="0.5"
                  style={{ width: '100%' }}
                  value={(ors.phase1_max_runtime_sec / 3600).toFixed(2)}
                  onChange={(e) => {
                    const hours = Math.max(0.1, Math.min(12, parseFloat(e.target.value) || 6));
                    setOrs({ ...ors, phase1_max_runtime_sec: Math.round(hours * 3600) });
                  }}
                />
              </div>
              <div>
                <label style={{ fontSize: '.75rem', color: 'var(--muted)' }}>
                  Phase 1 Sandbox
                </label>
                <select
                  className="input-sm"
                  style={{ width: '100%' }}
                  value={ors.phase1_sandbox_kind}
                  onChange={(e) =>
                    setOrs({
                      ...ors,
                      phase1_sandbox_kind: e.target.value as
                        | 'auto'
                        | 'docker'
                        | 'apptainer'
                        | 'singularity'
                        | 'local',
                    })
                  }
                >
                  <option value="auto">auto (docker → apptainer → singularity → local)</option>
                  <option value="docker">docker</option>
                  <option value="apptainer">apptainer</option>
                  <option value="singularity">singularity</option>
                  <option value="local">local</option>
                </select>
              </div>
            </div>

            {/* Replicator Agent (v0.7+) — PaperBench BasicAgent / IterativeAgent */}
            <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--border)' }}>
              <div style={{ fontSize: '.85rem', fontWeight: 600, marginBottom: 8 }}>
                {t('ors_replicator_agent') || 'Replicator Agent'}
                <span style={{ fontSize: '.7rem', color: 'var(--muted)', fontWeight: 400, marginLeft: 8 }}>
                  ({t('ors_replicator_agent_help') || 'PaperBench BasicAgent / IterativeAgent driven against repro_sandbox/'})
                </span>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                <div>
                  <label style={{ fontSize: '.75rem', color: 'var(--muted)' }}>
                    {t('ors_replicator_mode') || 'Agent variant'}
                  </label>
                  <select
                    className="input-sm"
                    style={{ width: '100%' }}
                    value={ors.iterative_agent ? 'iterative' : 'basic'}
                    onChange={(e) =>
                      setOrs({ ...ors, iterative_agent: e.target.value === 'iterative' })
                    }
                  >
                    <option value="basic">BasicAgent (paper §5.2)</option>
                    <option value="iterative">IterativeAgent (paper §5.3 — step-by-step, no early end)</option>
                  </select>
                </div>
                <div>
                  <label style={{ fontSize: '.75rem', color: 'var(--muted)' }}>
                    {t('ors_replicator_time_limit') || 'Agent time limit (h)'}
                  </label>
                  <input
                    className="input-sm"
                    type="number"
                    min={0.5}
                    max={36}
                    step="0.5"
                    style={{ width: '100%' }}
                    value={(ors.replicator_time_limit_sec / 3600).toFixed(2)}
                    onChange={(e) => {
                      const hours = Math.max(0.5, Math.min(36, parseFloat(e.target.value) || 12));
                      setOrs({ ...ors, replicator_time_limit_sec: Math.round(hours * 3600) });
                    }}
                  />
                </div>
              </div>

              <div style={{ marginTop: 8 }}>
                <label style={{ fontSize: '.75rem', color: 'var(--muted)' }}>
                  {t('ors_replicator_max_steps') || 'Agent max steps (0 = unlimited)'}
                </label>
                <input
                  className="input-sm"
                  type="number"
                  min={0}
                  max={10000}
                  style={{ width: '100%' }}
                  value={ors.replicator_max_steps}
                  onChange={(e) =>
                    setOrs({ ...ors, replicator_max_steps: Math.max(0, parseInt(e.target.value) || 0) })
                  }
                />
              </div>
            </div>
          </div>
        </details>
      </div>

      {/* Paper Review card (rubric-driven) */}
      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-title">
          {'📝'} {t('wiz_paper_review_section')}
        </div>

        <div className="form-row">
          <label>{t('wiz_rubric')}</label>
          <select
            value={rubricId}
            style={{ width: '100%' }}
            onChange={(e) => setRubricId(e.target.value)}
          >
            {(rubricsFromApi.length > 0 ? rubricsFromApi : RUBRIC_OPTIONS).map(
              (r) => (
                <option key={r.id} value={r.id}>
                  {r.label}
                </option>
              ),
            )}
          </select>
        </div>

        <div className="form-row">
          <label>{t('wiz_fewshot_mode')}</label>
          <div style={{ display: 'flex', gap: 6 }}>
            <button
              type="button"
              className={`btn btn-sm ${fewshotMode === 'static' ? 'btn-primary' : 'btn-outline'}`}
              onClick={() => setFewshotMode('static')}
            >
              {t('wiz_fewshot_static')}
            </button>
            <button
              type="button"
              className={`btn btn-sm ${fewshotMode === 'dynamic' ? 'btn-primary' : 'btn-outline'}`}
              onClick={() => setFewshotMode('dynamic')}
              disabled={isClosedReview}
              title={
                isClosedReview
                  ? t('wiz_fewshot_dynamic_unsupported')
                  : undefined
              }
            >
              {t('wiz_fewshot_dynamic')}
            </button>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          <div>
            <label style={{ fontSize: '.75rem', color: 'var(--muted)' }}>
              {t('wiz_num_reviews_ensemble')}
            </label>
            <input
              className="input-sm"
              type="number"
              min={1}
              max={10}
              value={numReviewsEnsemble}
              onChange={(e) =>
                setNumReviewsEnsemble(
                  Math.max(1, Math.min(10, parseInt(e.target.value) || 1)),
                )
              }
              style={{ width: '100%' }}
            />
          </div>
          <div>
            <label style={{ fontSize: '.75rem', color: 'var(--muted)' }}>
              {t('wiz_num_reflections')}
            </label>
            <input
              className="input-sm"
              type="number"
              min={0}
              max={10}
              value={numReflections}
              onChange={(e) =>
                setNumReflections(
                  Math.max(0, Math.min(10, parseInt(e.target.value) || 0)),
                )
              }
              style={{ width: '100%' }}
            />
          </div>
        </div>
        <FewshotManager rubricId={rubricId} />
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


function OrsModelPicker({
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
function FewshotManager({ rubricId }: { rubricId: string }) {
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
