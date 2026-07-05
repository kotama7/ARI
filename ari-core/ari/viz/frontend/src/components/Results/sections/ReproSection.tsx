import React from 'react';
import { Button } from '../../common/Button';
import { Badge } from '../../common/Badge';
import { Card } from '../../common/Card';
import type { CheckpointSummary } from '../../../types';
import { tryParseJson } from '../resultHelpers';
import { renderOrsChain } from './OrsChainSection';

// ─── Legacy renderer (pre-§4.1 reproducibility_report shape) ───────────

export function renderLegacyRepro({ repro, t }: { repro: any; t: (key: string) => string }): React.ReactNode {
  const reproObj = (typeof repro === 'string' ? tryParseJson(repro) : repro);

  if (!reproObj || typeof reproObj !== 'object') {
    return <div style={{ fontSize: '.85rem', color: 'var(--muted)' }}>{String(repro)}</div>;
  }

  const reproRecord = reproObj as Record<string, any>;

  // Skill-not-found error
  if (
    reproRecord.error &&
    (String(reproRecord.error).indexOf('not found') >= 0 ||
      String(reproRecord.error).indexOf('Tool') >= 0 ||
      String(reproRecord.error).indexOf('Available: []') >= 0)
  ) {
    return (
      <>
        <div style={{ color: 'var(--yellow)', fontSize: '.85rem', padding: 8 }}>
          {t('repro_skill_unavail')}
        </div>
        <details>
          <summary
            style={{ fontSize: '.75rem', color: 'var(--muted)', cursor: 'pointer' }}
          >
            {t('details')}
          </summary>
          <pre style={{ fontSize: '.72rem', color: 'var(--muted)', marginTop: 4 }}>
            {reproRecord.error}
          </pre>
        </details>
      </>
    );
  }

  const verdict = reproRecord.verdict || reproRecord.status || reproRecord.result || 'unknown';
  const badgeVariant =
    verdict === 'REPRODUCED' || verdict === 'PASS' || verdict === 'pass'
      ? 'green'
      : verdict === 'FAILED' || verdict === 'FAIL' || verdict === 'fail' || verdict === 'NOT_REPRODUCED'
        ? 'red'
        : 'yellow';

  const skip = new Set(['verdict', 'status', 'result', 'summary']);

  return (
    <>
      <div style={{ fontSize: '1.1rem', marginBottom: 8 }}>
        <Badge variant={badgeVariant}>{verdict}</Badge>
      </div>
      {reproRecord.summary && (
        <div style={{ fontSize: '.85rem', color: 'var(--muted)', marginBottom: 8 }}>
          {reproRecord.summary}
        </div>
      )}
      {Object.keys(reproRecord)
        .filter((k) => !skip.has(k))
        .slice(0, 8)
        .map((k) => (
          <div key={k} style={{ fontSize: '.8rem', marginTop: 4 }}>
            <span style={{ color: 'var(--muted)' }}>{k}:</span>{' '}
            {JSON.stringify(reproRecord[k])}
          </div>
        ))}
    </>
  );
}

// ─── Reproducibility section (extracted from ResultsPage renderRepro) ─────
// Medium-risk seam: renders the rich ORS chain (renderOrsChain) or the legacy
// reproducibility panel (renderLegacyRepro), plus the repro-log toolbar/panel.
// The repro-log state + its setter/loader are container-owned and threaded in
// as props; the body (incl. handleToggleReproLog/handleRefreshReproLog) is
// verbatim from the container, with the closed-over identifiers now params.
export function renderRepro({
  summary,
  selectedId,
  reproLogOpen,
  reproLogContent,
  reproLogPath,
  reproLogLoading,
  setReproLogOpen,
  loadReproLog,
  t,
}: {
  summary: CheckpointSummary | null;
  selectedId: string;
  reproLogOpen: boolean;
  reproLogContent: string | null;
  reproLogPath: string | null;
  reproLogLoading: boolean;
  setReproLogOpen: (v: boolean) => void;
  loadReproLog: (id: string) => void;
  t: (key: string) => string;
}): React.ReactNode {
  if (!summary) return null;

  const repro = summary.reproducibility_report || summary.repro;
  const orsRubric = (summary as any).ors_rubric as Record<string, any> | undefined;
  const orsGrade = (summary as any).ors_grade as Record<string, any> | undefined;
  const orsPhase1 = (summary as any).ors_phase1 as Record<string, any> | undefined;
  const orsReplicator = (summary as any).ors_replicator as Record<string, any> | undefined;
  const orsSeed = (summary as any).ors_seed as Record<string, any> | undefined;
  const orsRubricMeta = (summary as any).ors_rubric_meta as Record<string, any> | undefined;
  const richMode = !!(orsRubric || orsGrade || orsPhase1 || orsReplicator || orsSeed || orsRubricMeta);

  const handleToggleReproLog = () => {
    if (reproLogOpen) { setReproLogOpen(false); return; }
    setReproLogOpen(true);
    if (selectedId) loadReproLog(selectedId);
  };
  const handleRefreshReproLog = () => {
    if (selectedId) loadReproLog(selectedId);
  };

  const reproLogPanel = reproLogOpen && (
    <div
      style={{
        border: '1px solid var(--border)',
        borderRadius: 4,
        marginBottom: 8,
        maxHeight: 320,
        overflow: 'auto',
        background: 'var(--bg)',
      }}
    >
      {reproLogPath && (
        <div
          style={{
            fontSize: '.7rem',
            color: 'var(--muted)',
            padding: '4px 8px',
            borderBottom: '1px solid var(--border)',
            fontFamily: 'monospace',
          }}
        >
          {reproLogPath}
        </div>
      )}
      {reproLogLoading ? (
        <div style={{ padding: 8, fontSize: '.8rem', color: 'var(--muted)' }}>
          {t('repro_log_loading')}
        </div>
      ) : reproLogContent ? (
        <pre
          style={{
            margin: 0, padding: '6px 10px',
            fontSize: '.72rem', lineHeight: 1.45,
            fontFamily: 'monospace',
            whiteSpace: 'pre-wrap', wordBreak: 'break-all',
            color: 'var(--text)',
          }}
        >
          {reproLogContent}
        </pre>
      ) : (
        <div style={{ padding: 8, fontSize: '.8rem', color: 'var(--muted)' }}>
          {t('repro_log_empty')}
        </div>
      )}
    </div>
  );

  const toolbar = (
    <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
      <Button
        onClick={handleToggleReproLog}
        style={{ fontSize: '.75rem', padding: '3px 10px' }}
      >
        {reproLogOpen ? t('repro_log_hide') : t('repro_log_show')}
      </Button>
      {reproLogOpen && (
        <Button
          onClick={handleRefreshReproLog}
          style={{ fontSize: '.75rem', padding: '3px 8px' }}
          disabled={reproLogLoading}
          title={t('repro_log_refresh')}
        >
          {t('repro_log_refresh')}
        </Button>
      )}
    </div>
  );

  if (richMode) {
    return (
      <Card style={{ marginBottom: 16 }}>
        <div className="card-title">{t('verify_title')}</div>
        {renderOrsChain({
          repro,
          orsRubric, orsGrade, orsPhase1, orsReplicator, orsSeed, orsRubricMeta,
          ckptId: selectedId || '',
          reproLog: {
            open: reproLogOpen,
            loading: reproLogLoading,
            content: reproLogContent,
            path: reproLogPath,
          },
          onToggleLog: handleToggleReproLog,
          onRefreshLog: handleRefreshReproLog,
          t,
        })}
      </Card>
    );
  }

  // ── Legacy renderer (pre-§4.1 reproducibility_report shape) ─────────
  return (
    <Card style={{ marginBottom: 16 }}>
      <div className="card-title">{t('verify_title')}</div>
      {toolbar}
      {reproLogPanel}
      {repro ? (
        renderLegacyRepro({ repro, t })
      ) : (
        <div style={{ color: 'var(--muted)', fontSize: '.85rem' }}>
          {t('no_repro')}
        </div>
      )}
    </Card>
  );
}
