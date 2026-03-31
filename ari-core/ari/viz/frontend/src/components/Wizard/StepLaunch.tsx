import type { ReactNode } from 'react';
import { useState } from 'react';
import { useI18n } from '../../i18n';
import * as api from '../../services/api';

interface StepLaunchProps {
  profile: string;
  setProfile: (p: string) => void;
  paperFormat: string;
  setPaperFormat: (f: string) => void;
  language: string;
  setLanguage: (l: string) => void;
  goalSummary: string;
  finalMd: string;
  // Scope values for launch payload
  maxNodes: number;
  maxDepth: number;
  maxReact: number;
  timeout: number;
  workers: number;
  // LLM values for launch payload
  llmModel: string;
  llmProvider: string;
  // HPC values
  hpcCpus: string;
  hpcMem: string;
  hpcGpus: string;
  hpcWall: string;
  partition: string;
  phaseModels: Record<string, string>;
  savePath: string;
  // Navigation
  onBack: () => void;
  onLaunched: () => void;
}

export function StepLaunch({
  profile,
  setProfile,
  paperFormat,
  setPaperFormat,
  language,
  setLanguage,
  goalSummary,
  finalMd,
  maxNodes,
  maxDepth,
  maxReact,
  timeout,
  workers,
  llmModel,
  llmProvider,
  hpcCpus,
  hpcMem,
  hpcGpus,
  hpcWall,
  partition,
  phaseModels,
  savePath,
  onBack,
  onLaunched,
}: StepLaunchProps) {
  const { t } = useI18n();
  const [launchStatus, setLaunchStatus] = useState<ReactNode>(null);
  const [launching, setLaunching] = useState(false);

  const handleLaunch = async () => {
    if (launching) return;
    setLaunching(true);
    setLaunchStatus(
      <span>
        <span className="spinner" /> Launching...
      </span>,
    );

    try {
      const r = await api.launchExperiment({
        config_path: savePath || 'experiment.md',
        profile,
        experiment_md: finalMd,
        max_nodes: maxNodes || null,
        max_depth: maxDepth || null,
        max_react: maxReact || null,
        timeout_min: timeout || null,
        workers: workers || null,
        llm_model: llmModel,
        llm_provider: llmProvider || 'openai',
        hpc_cpus: parseInt(hpcCpus) || null,
        hpc_memory_gb: parseInt(hpcMem) || null,
        hpc_gpus: parseInt(hpcGpus) || null,
        hpc_walltime: hpcWall || null,
        partition: partition || '',
        paper_format: paperFormat || '',
        language: language || 'en',
        phase_models: phaseModels,
      });

      if (r.ok) {
        setLaunchStatus(
          <span className="badge badge-green">
            {'✓'} Launched (PID {r.pid})
          </span>,
        );
        // Navigate to monitor after short delay
        setTimeout(() => {
          onLaunched();
        }, 800);

        // Poll for new checkpoint in background
        pollNewCheckpoint(20);
      } else {
        setLaunchStatus(
          <span style={{ color: 'var(--red)' }}>{r.error}</span>,
        );
        setLaunching(false);
      }
    } catch (e: any) {
      setLaunchStatus(
        <span style={{ color: 'var(--red)' }}>
          {e.message || 'Launch failed'}
        </span>,
      );
      setLaunching(false);
    }
  };

  const pollNewCheckpoint = (attempts: number) => {
    if (attempts <= 0) return;
    setTimeout(async () => {
      try {
        const ck = await api.fetchCheckpoints();
        const all = Array.isArray(ck) ? ck : [];
        const sorted = all.sort((a, b) => (b.mtime || 0) - (a.mtime || 0));
        const newest = sorted[0];
        if (newest && newest.id) {
          await api.switchCheckpoint(newest.path);
          return;
        }
        pollNewCheckpoint(attempts - 1);
      } catch {
        pollNewCheckpoint(attempts - 1);
      }
    }, 3000);
  };

  return (
    <div>
      <div className="card">
        <div className="card-title">{'🚀'} Review &amp; Launch</div>

        {/* Profile */}
        <div className="form-row">
          <label>{t('wiz_profile_label')}</label>
          <select value={profile} onChange={(e) => setProfile(e.target.value)}>
            <option value="laptop">laptop</option>
            <option value="hpc">hpc</option>
            <option value="cloud">cloud</option>
          </select>
        </div>

        {/* Paper Format */}
        <div className="form-row">
          <label>Paper Format / Venue</label>
          <select
            value={paperFormat}
            onChange={(e) => setPaperFormat(e.target.value)}
          >
            <option value="arxiv">arXiv (PDF)</option>
            <option value="neurips">NeurIPS</option>
            <option value="icml">ICML</option>
            <option value="iclr">ICLR</option>
            <option value="acl">ACL</option>
            <option value="custom">Custom</option>
          </select>
        </div>

        {/* Language */}
        <div className="form-row">
          <label>Language</label>
          <select value={language} onChange={(e) => setLanguage(e.target.value)}>
            <option value="en">English</option>
            <option value="ja">{'日本語'}</option>
            <option value="zh">{'中文'}</option>
          </select>
        </div>

        {/* Research Goal Summary */}
        <div className="form-row" style={{ marginTop: 8 }}>
          <label>Research Goal Summary</label>
          <div
            style={{
              fontSize: '.82rem',
              color: 'var(--text)',
              background: 'var(--bg)',
              border: '1px solid var(--border)',
              borderRadius: 6,
              padding: 8,
              maxHeight: 120,
              overflowY: 'auto',
              lineHeight: 1.5,
            }}
          >
            {goalSummary || '—'}
          </div>
        </div>

        {/* Hidden final MD */}
        <textarea
          value={finalMd}
          readOnly
          style={{ display: 'none' }}
        />
      </div>

      {/* Navigation */}
      <div
        style={{
          marginTop: 16,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <button className="btn btn-outline" onClick={onBack} disabled={launching}>
          {'←'} Back
        </button>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <span>{launchStatus}</span>
          <button
            className="btn btn-primary"
            onClick={handleLaunch}
            disabled={launching}
          >
            {'🚀'} Launch Experiment
          </button>
        </div>
      </div>
    </div>
  );
}
