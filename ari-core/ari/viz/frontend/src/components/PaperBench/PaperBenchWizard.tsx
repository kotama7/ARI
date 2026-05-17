import { useEffect, useState } from 'react';
import { useT } from '../../i18n';

interface RubricConfig {
  model: string;
  two_stage: boolean;
  target_leaf_count: number;
  temperature: number;
}
interface ReproduceConfig {
  model: string;
  time_limit_sec: number;
  iterative_agent: boolean;
  sandbox_kind: string;
  partition: string;
  // execution_profile override (mirrors the rubric's execution_profile)
  nodes: number;
  ntasks: number;
  ntasks_per_node: number;
  exclusive: boolean;
  gpus_per_task: number;
  gpu_type: string;
  memory_gb_per_node: number;
  constraint: string;
  cpu_bind: string;
  mem_bind: string;
  hint: string;
  nodelist: string;
  extra_sbatch_args: string;
}
interface JudgeConfig {
  model: string;
  n_runs: number;
  skip_negative_control: boolean;
}

const STEPS = ['paper', 'rubric', 'reproduce', 'judge', 'launch'] as const;
type StepId = (typeof STEPS)[number];

interface PaperEntry {
  paper_id: string;
  title: string;
  license: string;
  license_assessment?: { usable: boolean };
}

/**
 * PaperBenchWizard — 5-step launch flow.
 *
 * Step 3 (Reproduce) is the focal point of v0.7.2 because it exposes the
 * full 16-arg execution_profile override surface that drives the new
 * sbatch flags in ari-skill-paper-re/src/server.py. The other four steps
 * are deliberately minimal placeholders; they collect the configs that
 * POST /api/paperbench/run forwards verbatim to the existing CLI run path.
 */
export function PaperBenchWizard() {
  const t = useT();
  const [step, setStep] = useState<StepId>('paper');
  const [papers, setPapers] = useState<PaperEntry[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [rubric, setRubric] = useState<RubricConfig>({
    model: 'gemini/gemini-2.5-pro',
    two_stage: true,
    target_leaf_count: 0,
    temperature: 0.0,
  });
  const [reproduce, setReproduce] = useState<ReproduceConfig>({
    model: 'gpt-5-mini',
    time_limit_sec: 12 * 3600,
    iterative_agent: false,
    sandbox_kind: 'auto',
    partition: '',
    nodes: 0,
    ntasks: 0,
    ntasks_per_node: 0,
    exclusive: false,
    gpus_per_task: 0,
    gpu_type: '',
    memory_gb_per_node: 0,
    constraint: '',
    cpu_bind: '',
    mem_bind: '',
    hint: '',
    nodelist: '',
    extra_sbatch_args: '',
  });
  const [judge, setJudge] = useState<JudgeConfig>({
    model: 'gpt-5-mini',
    n_runs: 1,
    skip_negative_control: false,
  });
  const [costEstimate, setCostEstimate] = useState<{
    wall_time_sec: number;
    llm_cost_usd: number;
  } | null>(null);
  const [launchResult, setLaunchResult] = useState<{ job_ids?: string[]; error?: string } | null>(
    null,
  );

  useEffect(() => {
    void fetch('/api/paperbench/papers')
      .then((r) => r.json())
      .then((d) => setPapers(d.papers || []));
  }, []);

  // Live cost estimate refresh whenever any config changes.
  useEffect(() => {
    void fetch('/api/paperbench/cost-estimate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        rubric_config: rubric,
        reproduce_config: reproduce,
        judge_config: judge,
      }),
    })
      .then((r) => r.json())
      .then(setCostEstimate)
      .catch(() => setCostEstimate(null));
  }, [rubric, reproduce, judge]);

  const launch = async (dryRun: boolean) => {
    const body = {
      paper_ids: Array.from(selectedIds),
      rubric_config: rubric,
      reproduce_config: {
        ...reproduce,
        extra_sbatch_args: reproduce.extra_sbatch_args
          .split(/\s+/)
          .filter(Boolean),
      },
      judge_config: judge,
      dry_run: dryRun,
    };
    const r = await fetch('/api/paperbench/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    setLaunchResult(await r.json());
  };

  const stepIdx = STEPS.indexOf(step);

  return (
    <div style={{ padding: 28, maxWidth: 900 }}>
      <h2>{t('pb_wizard_title')}</h2>
      <div style={{ display: 'flex', gap: 8, marginBottom: 18 }}>
        {STEPS.map((s, i) => (
          <span
            key={s}
            style={{
              padding: '4px 10px',
              borderRadius: 4,
              background: i === stepIdx ? '#36c' : i < stepIdx ? '#bdb' : '#ddd',
              color: i === stepIdx ? '#fff' : '#333',
              fontSize: 13,
            }}
          >
            {i + 1}. {t(`pb_step_${s}` as const)}
          </span>
        ))}
      </div>

      {step === 'paper' && (
        <div>
          <h3>{t('pb_step1_title')}</h3>
          {papers.map((p) => (
            <label key={p.paper_id} style={{ display: 'block', padding: 4 }}>
              <input
                type="checkbox"
                checked={selectedIds.has(p.paper_id)}
                onChange={() => {
                  const next = new Set(selectedIds);
                  next.has(p.paper_id) ? next.delete(p.paper_id) : next.add(p.paper_id);
                  setSelectedIds(next);
                }}
              />{' '}
              <code>{p.paper_id}</code> {p.title}{' '}
              {p.license_assessment?.usable ? '✅' : '⚠'}
            </label>
          ))}
        </div>
      )}

      {step === 'rubric' && (
        <div>
          <h3>{t('pb_step2_title')}</h3>
          <label>
            {t('pb_model')}
            <input value={rubric.model} onChange={(e) => setRubric({ ...rubric, model: e.target.value })} />
          </label>{' '}
          <label>
            <input
              type="checkbox"
              checked={rubric.two_stage}
              onChange={(e) => setRubric({ ...rubric, two_stage: e.target.checked })}
            />{' '}
            {t('pb_two_stage')}
          </label>{' '}
          <label>
            {t('pb_target_leaves')}
            <input
              type="number"
              value={rubric.target_leaf_count}
              onChange={(e) => setRubric({ ...rubric, target_leaf_count: parseInt(e.target.value || '0', 10) })}
              style={{ width: 80 }}
            />
          </label>
        </div>
      )}

      {step === 'reproduce' && (
        <div>
          <h3>{t('pb_step3_title')}</h3>
          <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap' }}>
            <label>
              {t('pb_model')}
              <input
                value={reproduce.model}
                onChange={(e) => setReproduce({ ...reproduce, model: e.target.value })}
              />
            </label>
            <label>
              {t('pb_time_limit')}
              <input
                type="number"
                value={reproduce.time_limit_sec}
                onChange={(e) =>
                  setReproduce({ ...reproduce, time_limit_sec: parseInt(e.target.value || '0', 10) })
                }
                style={{ width: 100 }}
              />
            </label>
            <label>
              {t('pb_sandbox')}
              <select
                value={reproduce.sandbox_kind}
                onChange={(e) => setReproduce({ ...reproduce, sandbox_kind: e.target.value })}
              >
                <option value="auto">auto</option>
                <option value="slurm">slurm</option>
                <option value="local">local</option>
                <option value="apptainer">apptainer</option>
                <option value="docker">docker</option>
              </select>
            </label>
            <label>
              {t('pb_partition')}
              <input
                value={reproduce.partition}
                onChange={(e) => setReproduce({ ...reproduce, partition: e.target.value })}
              />
            </label>
          </div>

          <fieldset style={{ marginTop: 14, padding: 12, border: '1px solid #ccc' }}>
            <legend>{t('pb_execution_profile_override')}</legend>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
              {[
                ['nodes', 'nodes'],
                ['ntasks', 'ntasks'],
                ['ntasks_per_node', 'ntasks_per_node'],
                ['gpus_per_task', 'gpus_per_task'],
                ['memory_gb_per_node', 'memory_gb_per_node'],
              ].map(([key]) => (
                <label key={key}>
                  {key}
                  <input
                    type="number"
                    value={(reproduce as unknown as Record<string, number>)[key]}
                    onChange={(e) =>
                      setReproduce({
                        ...reproduce,
                        [key]: parseInt(e.target.value || '0', 10),
                      } as ReproduceConfig)
                    }
                    style={{ width: '100%' }}
                  />
                </label>
              ))}
              <label>
                <input
                  type="checkbox"
                  checked={reproduce.exclusive}
                  onChange={(e) => setReproduce({ ...reproduce, exclusive: e.target.checked })}
                />{' '}
                exclusive
              </label>
              {[
                ['gpu_type', 'gpu_type (e.g. v100)'],
                ['constraint', 'constraint (skylake)'],
                ['cpu_bind', 'cpu_bind (cores)'],
                ['mem_bind', 'mem_bind (local)'],
                ['hint', 'hint (nomultithread)'],
                ['nodelist', 'nodelist'],
              ].map(([key, label]) => (
                <label key={key}>
                  {label}
                  <input
                    value={(reproduce as unknown as Record<string, string>)[key]}
                    onChange={(e) =>
                      setReproduce({ ...reproduce, [key]: e.target.value } as ReproduceConfig)
                    }
                    style={{ width: '100%' }}
                  />
                </label>
              ))}
              <label style={{ gridColumn: 'span 4' }}>
                extra_sbatch_args ({t('pb_space_sep')})
                <input
                  value={reproduce.extra_sbatch_args}
                  onChange={(e) =>
                    setReproduce({ ...reproduce, extra_sbatch_args: e.target.value })
                  }
                  style={{ width: '100%' }}
                  placeholder="--account=projX --reservation=res1"
                />
              </label>
            </div>
          </fieldset>
        </div>
      )}

      {step === 'judge' && (
        <div>
          <h3>{t('pb_step4_title')}</h3>
          <label>
            {t('pb_model')}
            <input value={judge.model} onChange={(e) => setJudge({ ...judge, model: e.target.value })} />
          </label>{' '}
          <label>
            n_runs
            <input
              type="number"
              value={judge.n_runs}
              onChange={(e) => setJudge({ ...judge, n_runs: parseInt(e.target.value || '1', 10) })}
              style={{ width: 60 }}
            />
          </label>{' '}
          <label>
            <input
              type="checkbox"
              checked={judge.skip_negative_control}
              onChange={(e) => setJudge({ ...judge, skip_negative_control: e.target.checked })}
            />{' '}
            {t('pb_skip_negative_control')}
          </label>
        </div>
      )}

      {step === 'launch' && (
        <div>
          <h3>{t('pb_step5_title')}</h3>
          <ul>
            <li>
              {t('pb_summary_papers')}: {selectedIds.size}
            </li>
            <li>
              {t('pb_summary_rubric')}: {rubric.model} two_stage={String(rubric.two_stage)}
            </li>
            <li>
              {t('pb_summary_reproduce')}: {reproduce.model}, sandbox={reproduce.sandbox_kind}
              {reproduce.exclusive ? ', --exclusive' : ''}
              {reproduce.gpu_type ? `, --gres=gpu:${reproduce.gpu_type}:${reproduce.gpus_per_task || 1}` : ''}
              {reproduce.memory_gb_per_node ? `, --mem=${reproduce.memory_gb_per_node}G` : ''}
            </li>
            <li>
              {t('pb_summary_judge')}: {judge.model}, n_runs={judge.n_runs}
            </li>
          </ul>
          {costEstimate && (
            <div style={{ padding: 10, background: '#f5f5f5', marginTop: 8 }}>
              <strong>{t('pb_estimated')}:</strong>{' '}
              wall_time ≈ {Math.round(costEstimate.wall_time_sec / 60)} min × {selectedIds.size}{' '}
              {t('pb_papers')},{' '}
              cost ≈ ${(costEstimate.llm_cost_usd * selectedIds.size).toFixed(2)}
            </div>
          )}
          <div style={{ marginTop: 16, display: 'flex', gap: 12 }}>
            <button onClick={() => void launch(true)}>{t('pb_dry_run')}</button>
            <button onClick={() => void launch(false)} disabled={selectedIds.size === 0}>
              🚀 {t('pb_launch_all')}
            </button>
          </div>
          {launchResult && (
            <div style={{ marginTop: 12, padding: 10, background: launchResult.error ? '#fee' : '#efe' }}>
              {launchResult.error || `✓ ${t('pb_jobs_queued')}: ${launchResult.job_ids?.join(', ')}`}
            </div>
          )}
        </div>
      )}

      <div style={{ marginTop: 24, display: 'flex', gap: 12 }}>
        <button
          onClick={() => setStep(STEPS[Math.max(0, stepIdx - 1)])}
          disabled={stepIdx === 0}
        >
          ← {t('pb_back')}
        </button>
        <button
          onClick={() => setStep(STEPS[Math.min(STEPS.length - 1, stepIdx + 1)])}
          disabled={stepIdx === STEPS.length - 1 || (step === 'paper' && selectedIds.size === 0)}
        >
          {t('pb_next')} →
        </button>
      </div>
    </div>
  );
}
