import { useState, useEffect, useCallback } from 'react';
import { useI18n } from '../../i18n';

interface ScopeValues {
  maxDepth: number;
  maxNodes: number;
  workers: number;
  maxReact: number;
  timeout: number;
  maxRecursionDepth: number;
}

interface ScopePreset {
  depth: number;
  nodes: number;
  react: number;
  workers: number;
  timeout: number;
  maxRecursionDepth: number;
  est: string;
}

const SCOPE_PRESETS: ScopePreset[] = [
  { depth: 3, nodes: 10, react: 20, workers: 2, timeout: 30, maxRecursionDepth: 0, est: '~30 min' },
  { depth: 5, nodes: 30, react: 80, workers: 4, timeout: 120, maxRecursionDepth: 0, est: '~1-2 h' },
  { depth: 9, nodes: 60, react: 150, workers: 8, timeout: 300, maxRecursionDepth: 1, est: '~3-5 h' },
  { depth: 12, nodes: 100, react: 300, workers: 12, timeout: 480, maxRecursionDepth: 2, est: '~5-8 h' },
  { depth: 15, nodes: 120, react: 500, workers: 16, timeout: 720, maxRecursionDepth: 3, est: '~8-12 h' },
];

const PRESET_LABELS = ['Quick', 'Standard', 'Thorough', 'Deep', 'Exhaustive'];

interface StepScopeProps {
  scopeVal: number;
  setScopeVal: (v: number) => void;
  scope: ScopeValues;
  setScope: (s: ScopeValues) => void;
  onBack: () => void;
  onNext: () => void;
}

export function StepScope({
  scopeVal,
  setScopeVal,
  scope,
  setScope,
  onBack,
  onNext,
}: StepScopeProps) {
  const { t } = useI18n();
  const [isManual, setIsManual] = useState(false);

  const applyScopePreset = useCallback(
    (n: number) => {
      setIsManual(false);
      setScopeVal(n);
      const c = SCOPE_PRESETS[n - 1] || SCOPE_PRESETS[1];
      setScope({
        maxDepth: c.depth,
        maxNodes: c.nodes,
        maxReact: c.react,
        workers: c.workers,
        timeout: c.timeout,
        maxRecursionDepth: c.maxRecursionDepth,
      });
    },
    [setScopeVal, setScope],
  );

  // Initialize with Standard preset if values are default
  useEffect(() => {
    if (scope.maxDepth === 5 && scope.maxNodes === 30 && scopeVal === 2) {
      applyScopePreset(2);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleFieldChange = (field: keyof ScopeValues, value: number) => {
    setIsManual(true);
    setScope({ ...scope, [field]: value });
  };

  const currentPreset = !isManual ? SCOPE_PRESETS[scopeVal - 1] : null;

  const summaryHtml = `Depth: <b>${scope.maxDepth}</b>&nbsp;&nbsp; Nodes: <b>${scope.maxNodes}</b>&nbsp;&nbsp; React: <b>${scope.maxReact}</b>&nbsp;&nbsp; Workers: <b>${scope.workers}</b>&nbsp;&nbsp; Timeout: <b>${scope.timeout}m</b>${currentPreset ? '&nbsp;&nbsp;⏱ ' + currentPreset.est : ''}`;

  return (
    <div>
      <div className="card">
        <div className="card-title">{t('wiz_scope_title')}</div>

        {/* Scope summary */}
        <div
          className="card"
          style={{
            background: 'rgba(59,130,246,.07)',
            borderColor: 'rgba(59,130,246,.2)',
            fontSize: '.875rem',
            lineHeight: 1.7,
          }}
          dangerouslySetInnerHTML={{ __html: summaryHtml }}
        />

        {/* Form fields */}
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginTop: 16 }}>
          <div className="form-row" style={{ flex: 1, minWidth: 140 }}>
            <label>
              Max Depth{' '}
              <span style={{ color: 'var(--muted)', fontSize: '.78rem' }}>(2-20)</span>
            </label>
            <input
              type="number"
              value={scope.maxDepth}
              min={2}
              max={20}
              style={{ width: '100%' }}
              onChange={(e) =>
                handleFieldChange('maxDepth', parseInt(e.target.value) || 5)
              }
            />
          </div>
          <div className="form-row" style={{ flex: 1, minWidth: 140 }}>
            <label>
              Max Nodes{' '}
              <span style={{ color: 'var(--muted)', fontSize: '.78rem' }}>(5-500)</span>
            </label>
            <input
              type="number"
              value={scope.maxNodes}
              min={5}
              max={500}
              style={{ width: '100%' }}
              onChange={(e) =>
                handleFieldChange('maxNodes', parseInt(e.target.value) || 30)
              }
            />
          </div>
          <div className="form-row" style={{ flex: 1, minWidth: 140 }}>
            <label>
              Workers{' '}
              <span style={{ color: 'var(--muted)', fontSize: '.78rem' }}>(1-64)</span>
            </label>
            <input
              type="number"
              value={scope.workers}
              min={1}
              max={64}
              style={{ width: '100%' }}
              onChange={(e) =>
                handleFieldChange('workers', parseInt(e.target.value) || 4)
              }
            />
          </div>
          <div className="form-row" style={{ flex: 1, minWidth: 140 }}>
            <label>Max ReAct Steps</label>
            <input
              type="number"
              value={scope.maxReact}
              min={10}
              max={500}
              style={{ width: '100%' }}
              onChange={(e) =>
                handleFieldChange('maxReact', parseInt(e.target.value) || 80)
              }
            />
          </div>
          <div className="form-row" style={{ flex: 1, minWidth: 140 }}>
            <label>Timeout (min)</label>
            <input
              type="number"
              value={scope.timeout}
              min={10}
              max={1440}
              style={{ width: '100%' }}
              onChange={(e) =>
                handleFieldChange('timeout', parseInt(e.target.value) || 120)
              }
            />
          </div>
          <div className="form-row" style={{ flex: 1, minWidth: 140 }}>
            <label>
              Max Recursion Depth{' '}
              <span style={{ color: 'var(--muted)', fontSize: '.78rem' }}>(0-5)</span>
            </label>
            <input
              type="number"
              value={scope.maxRecursionDepth}
              min={0}
              max={5}
              style={{ width: '100%' }}
              onChange={(e) =>
                handleFieldChange(
                  'maxRecursionDepth',
                  e.target.value === '' ? 0 : parseInt(e.target.value),
                )
              }
            />
          </div>
        </div>

        {/* Preset buttons */}
        <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
          {PRESET_LABELS.map((label, i) => (
            <button
              key={i}
              className={`btn btn-outline btn-sm${!isManual && scopeVal === i + 1 ? ' active' : ''}`}
              onClick={() => applyScopePreset(i + 1)}
            >
              {label}
            </button>
          ))}
        </div>
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
