import { useState, useCallback, useMemo, useEffect, useRef } from 'react';
import { useI18n } from '../../i18n';
import * as api from '../../services/api';
import { StepGoal } from './StepGoal';
import { StepScope } from './StepScope';
import { StepResources, PROVIDER_MODELS } from './StepResources';
import { StepLaunch } from './StepLaunch';

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

interface UploadedFile {
  name: string;
  path: string;
  type: string;
}

interface ScopeValues {
  maxDepth: number;
  maxNodes: number;
  workers: number;
  maxReact: number;
  timeout: number;
  maxRecursionDepth: number;
}

const STEP_KEYS = ['wiz_step1', 'wiz_step2', 'wiz_step3', 'wiz_step4'] as const;

export function WizardPage() {
  const { t } = useI18n();

  // ---- wizard navigation state ----
  const [step, setStep] = useState(1);

  // ---- Step 1: Goal state ----
  const [wizMode, setWizMode] = useState<'chat' | 'md'>('chat');
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const [chatGeneratedMd, setChatGeneratedMd] = useState('');
  const [goalText, setGoalText] = useState('');
  const [generatedMd, setGeneratedMd] = useState('');
  const [uploadedFiles, setUploadedFiles] = useState<UploadedFile[]>([]);
  const [savePath, setSavePath] = useState('experiment.md');

  // ---- Step 2: Scope state ----
  const [scopeVal, setScopeVal] = useState(2);
  const [scope, setScope] = useState<ScopeValues>({
    maxDepth: 5,
    maxNodes: 30,
    workers: 4,
    maxReact: 80,
    timeout: 120,
    maxRecursionDepth: 0,
  });

  // ---- Step 3: Resources state ----
  const [mode, setMode] = useState('laptop');
  const [llm, setLlm] = useState('openai');
  const [model, setModel] = useState('gpt-5.2');
  const [customModel, setCustomModel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [baseUrl, setBaseUrl] = useState('http://localhost:11434');
  const [ollamaGpu, setOllamaGpu] = useState('');
  const [partition, setPartition] = useState('');
  const [hpcCpus, setHpcCpus] = useState('');
  const [hpcMem, setHpcMem] = useState('');
  const [hpcWall, setHpcWall] = useState('');
  const [hpcGpus, setHpcGpus] = useState('');
  const [phaseModels, setPhaseModels] = useState<Record<string, string>>({});
  const [containerImage, setContainerImage] = useState('');
  const [containerMode, setContainerMode] = useState('auto');

  // ---- VLM Review state ----
  const [vlmReviewModel, setVlmReviewModel] = useState('openai/gpt-4o');

  // ---- Paper Review (rubric-driven) state ----
  const [rubricId, setRubricId] = useState('neurips');
  const [fewshotMode, setFewshotMode] = useState<'static' | 'dynamic'>('static');
  const [numReviewsEnsemble, setNumReviewsEnsemble] = useState(1);
  const [numReflections, setNumReflections] = useState(5);

  // ---- Step 4: Launch state ----
  const [profile, setProfile] = useState('laptop');
  const [paperFormat, setPaperFormat] = useState('arxiv');
  const [language, setLanguage] = useState('en');

  // Compute final MD and goal summary when entering step 4
  const finalMd = useMemo(() => {
    let expContent = '';
    if (wizMode === 'chat') {
      expContent = chatGeneratedMd;
    }
    if (!expContent) expContent = generatedMd;
    if (!expContent) expContent = goalText;
    return expContent;
  }, [wizMode, chatGeneratedMd, generatedMd, goalText]);

  const goalSummary = useMemo(() => {
    const md = finalMd;
    return md;
  }, [finalMd]);

  // Compute effective model
  const effectiveModel = useMemo(() => {
    if ((llm === 'ollama' || llm === 'custom') && customModel) return customModel;
    return model;
  }, [llm, customModel, model]);

  // ── One-time settings load ─────────────────────────────────────────────
  // Pre-populate llm/model/customModel/baseUrl/HPC fields from `settings.json`.
  // Lives in WizardPage (not StepResources) on purpose: StepResources is
  // unmounted when the user navigates away from step 3, and re-running the
  // load on every remount would clobber the user's manual model selection.
  // The ref guard ensures the fetch fires exactly once per WizardPage mount.
  const settingsLoadedRef = useRef(false);
  useEffect(() => {
    if (settingsLoadedRef.current) return;
    settingsLoadedRef.current = true;
    api
      .fetchSettings()
      .then((s: any) => {
        const prov = s.llm_provider || s.llm_backend || 'openai';
        setLlm(prov);
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
  }, []);

  const goToStep = useCallback(
    (s: number) => {
      if (s === 4) {
        // Sync profile with mode
        setProfile(mode === 'hpc' ? 'hpc' : 'laptop');
      }
      setStep(s);
    },
    [mode],
  );

  const handleLaunched = useCallback(() => {
    // Navigate to monitor page
    // Use hash-based navigation compatible with the dashboard
    window.location.hash = '#/monitor';
  }, []);

  return (
    <div>
      <h1>{t('new_title')}</h1>
      <p className="subtitle">{t('new_subtitle')}</p>

      {/* Step pills */}
      <div className="wizard-steps">
        {STEP_KEYS.map((key, i) => {
          const n = i + 1;
          let cls = 'step-pill';
          if (n === step) cls += ' active';
          else if (n < step) cls += ' done';
          return (
            <div
              key={key}
              className={cls}
              onClick={() => goToStep(n)}
              style={{ cursor: 'pointer' }}
            >
              {t(key)}
            </div>
          );
        })}
      </div>

      {/* Step content */}
      {step === 1 && (
        <StepGoal
          wizMode={wizMode}
          setWizMode={setWizMode}
          chatHistory={chatHistory}
          setChatHistory={setChatHistory}
          chatGeneratedMd={chatGeneratedMd}
          setChatGeneratedMd={setChatGeneratedMd}
          goalText={goalText}
          setGoalText={setGoalText}
          generatedMd={generatedMd}
          setGeneratedMd={setGeneratedMd}
          uploadedFiles={uploadedFiles}
          setUploadedFiles={setUploadedFiles}
          savePath={savePath}
          setSavePath={setSavePath}
          onNext={() => goToStep(2)}
        />
      )}

      {step === 2 && (
        <StepScope
          scopeVal={scopeVal}
          setScopeVal={setScopeVal}
          scope={scope}
          setScope={setScope}
          onBack={() => goToStep(1)}
          onNext={() => goToStep(3)}
        />
      )}

      {step === 3 && (
        <StepResources
          mode={mode}
          setMode={setMode}
          llm={llm}
          setLlm={setLlm}
          model={model}
          setModel={setModel}
          customModel={customModel}
          setCustomModel={setCustomModel}
          apiKey={apiKey}
          setApiKey={setApiKey}
          baseUrl={baseUrl}
          setBaseUrl={setBaseUrl}
          ollamaGpu={ollamaGpu}
          setOllamaGpu={setOllamaGpu}
          partition={partition}
          setPartition={setPartition}
          hpcCpus={hpcCpus}
          setHpcCpus={setHpcCpus}
          hpcMem={hpcMem}
          setHpcMem={setHpcMem}
          hpcWall={hpcWall}
          setHpcWall={setHpcWall}
          hpcGpus={hpcGpus}
          setHpcGpus={setHpcGpus}
          phaseModels={phaseModels}
          setPhaseModels={setPhaseModels}
          containerImage={containerImage}
          setContainerImage={setContainerImage}
          containerMode={containerMode}
          setContainerMode={setContainerMode}
          vlmReviewModel={vlmReviewModel}
          setVlmReviewModel={setVlmReviewModel}
          rubricId={rubricId}
          setRubricId={setRubricId}
          fewshotMode={fewshotMode}
          setFewshotMode={setFewshotMode}
          numReviewsEnsemble={numReviewsEnsemble}
          setNumReviewsEnsemble={setNumReviewsEnsemble}
          numReflections={numReflections}
          setNumReflections={setNumReflections}
          onBack={() => goToStep(2)}
          onNext={() => goToStep(4)}
        />
      )}

      {step === 4 && (
        <StepLaunch
          profile={profile}
          setProfile={setProfile}
          paperFormat={paperFormat}
          setPaperFormat={setPaperFormat}
          language={language}
          setLanguage={setLanguage}
          goalSummary={goalSummary}
          finalMd={finalMd}
          maxNodes={scope.maxNodes}
          maxDepth={scope.maxDepth}
          maxReact={scope.maxReact}
          timeout={scope.timeout}
          workers={scope.workers}
          maxRecursionDepth={scope.maxRecursionDepth}
          llmModel={effectiveModel}
          llmProvider={llm}
          hpcCpus={hpcCpus}
          hpcMem={hpcMem}
          hpcGpus={hpcGpus}
          hpcWall={hpcWall}
          partition={partition}
          phaseModels={phaseModels}
          savePath={savePath}
          containerImage={containerImage}
          containerMode={containerMode}
          vlmReviewModel={vlmReviewModel}
          rubricId={rubricId}
          fewshotMode={fewshotMode}
          numReviewsEnsemble={numReviewsEnsemble}
          numReflections={numReflections}
          onBack={() => goToStep(3)}
          onLaunched={handleLaunched}
        />
      )}
    </div>
  );
}
