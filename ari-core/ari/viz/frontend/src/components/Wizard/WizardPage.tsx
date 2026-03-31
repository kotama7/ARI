import { useState, useCallback, useMemo } from 'react';
import { useI18n } from '../../i18n';
import { StepGoal } from './StepGoal';
import { StepScope } from './StepScope';
import { StepResources } from './StepResources';
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
          llmModel={effectiveModel}
          llmProvider={llm}
          hpcCpus={hpcCpus}
          hpcMem={hpcMem}
          hpcGpus={hpcGpus}
          hpcWall={hpcWall}
          partition={partition}
          phaseModels={phaseModels}
          savePath={savePath}
          onBack={() => goToStep(3)}
          onLaunched={handleLaunched}
        />
      )}
    </div>
  );
}
