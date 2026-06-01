import React, { useState } from 'react';
import { Button } from '../common/Button';
import { Badge } from '../common/Badge';
import { Card } from '../common/Card';
import { fetchCheckpointFilecontent } from '../../services/api';
import type { CheckpointSummary } from '../../types';
import { RubricTreeVisualization } from './RubricTreeVisualization';
import type { OrsRenderInput, RubricNode, LeafGrade, StageState } from './resultTypes';
import {
  tryParseJson, buildGradeMap, aggregateScore, truncSha, fileCount, asFileList,
  formatFiles, formatRubricStage, replicatorState, formatReplicatorStage,
  phase1State, formatPhase1Stage, phase2State, formatPhase2Stage,
} from './resultHelpers';

// ─── ORS chain (PaperBench-aware) renderer ──────────────────────────────
//
// Surface the per-stage status produced by the new ORS workflow:
//   ors_rubric_meta   ← generator metadata (model, leaves, expected_artifacts)
//   ors_replicator    ← LLM-driven replicator (paper → reproduce.sh)
//   ors_seed          ← fetch_code_bundle (EAR → repro_sandbox)
//   ors_phase1        ← run_reproduce (executed/exit_code/missing/sandbox)
//   ors_grade         ← SimpleJudge result (ors_score, leaf_grades[])
// Plus the synthesized ``reproducibility_report`` for the headline verdict.

export function renderOrsChain(input: OrsRenderInput): React.ReactNode {
  const {
    repro,
    orsRubric, orsGrade, orsPhase1, orsReplicator, orsSeed, orsRubricMeta,
    ckptId, reproLog, onToggleLog, onRefreshLog,
    t,
  } = input;

  // Headline verdict + score bar pulled from the synthesized report.
  const reproObj = (typeof repro === 'string' ? tryParseJson(repro) : repro) || {};
  const verdict = (reproObj.verdict || reproObj.status || reproObj.result || '').toString();
  const summaryText: string | undefined = reproObj.summary;

  const orsScore: number | undefined = typeof orsGrade?.ors_score === 'number'
    ? orsGrade.ors_score : undefined;
  const rawScore: number | undefined = typeof orsGrade?.raw_score === 'number'
    ? orsGrade.raw_score : undefined;
  const leafGrades: any[] = Array.isArray(orsGrade?.leaf_grades) ? orsGrade!.leaf_grades : [];
  const passed = leafGrades.filter((lg) => (lg.passed_runs ?? 0) > 0).length;
  const total = leafGrades.length;

  const badgeVariant =
    verdict === 'REPRODUCED' || verdict === 'PASS'
      ? 'green'
      : verdict === 'FAILED' || verdict === 'NOT_REPRODUCED'
        ? 'red'
        : 'yellow';

  return (
    <div>
      {/* Headline */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
        {verdict && <Badge variant={badgeVariant}>{verdict}</Badge>}
        {orsScore !== undefined && (
          <div style={{ fontSize: '.95rem', fontWeight: 600 }}>
            {(orsScore * 100).toFixed(1)}%
          </div>
        )}
        {total > 0 && (
          <div style={{ fontSize: '.78rem', color: 'var(--muted)' }}>
            {passed} / {total} {t('ors_leaves_passed_unit')}
          </div>
        )}
      </div>
      {orsScore !== undefined && (
        <ScoreBar weighted={orsScore} raw={rawScore} />
      )}
      {summaryText && (
        <div style={{ fontSize: '.85rem', color: 'var(--muted)', marginBottom: 10 }}>
          {summaryText}
        </div>
      )}

      {/* Chain stages */}
      <div style={{
        marginBottom: 12, marginTop: 12,
        fontSize: '.7rem', fontWeight: 700, color: 'var(--blue-light)',
        textTransform: 'uppercase', letterSpacing: '.04em',
      }}>
        {t('ors_chain_title')}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 12 }}>
        <ChainStage
          label={t('ors_stage_rubric')}
          state={orsRubricMeta ? 'ok' : 'pending'}
          detail={orsRubricMeta ? formatRubricStage(orsRubricMeta) : '—'}
        />
        <ChainStage
          label={t('ors_stage_replicator')}
          state={replicatorState(orsReplicator, orsSeed)}
          detail={formatReplicatorStage(orsReplicator, orsSeed)}
        />
        <ChainStage
          label={t('ors_stage_phase1')}
          state={phase1State(orsPhase1)}
          detail={formatPhase1Stage(orsPhase1)}
        />
        <ChainStage
          label={t('ors_stage_phase2')}
          state={phase2State(orsGrade)}
          detail={formatPhase2Stage(orsGrade)}
        />
      </div>

      {/* Grading tree (rebuilt from rubric tree + per-leaf grades) */}
      {orsRubric?.rubric && total > 0 && (
        <GradingTreeSection
          rubric={orsRubric.rubric as RubricNode}
          leafGrades={leafGrades}
          passed={passed}
          total={total}
          t={t}
        />
      )}
      {/* Fallback: flat per-leaf list when rubric tree is unavailable. */}
      {!orsRubric?.rubric && total > 0 && (
        <details style={{ marginBottom: 8 }}>
          <summary style={{
            cursor: 'pointer', fontSize: '.78rem', color: 'var(--muted)',
            userSelect: 'none', padding: '4px 0',
          }}>
            ▸ {t('ors_leaves_header')} ({passed} ✓ / {total - passed} ✗)
          </summary>
          <div style={{
            marginTop: 6, maxHeight: 360, overflowY: 'auto',
            border: '1px solid var(--border)', borderRadius: 4,
          }}>
            {leafGrades.map((lg, i) => (
              <LeafGradeRow key={lg.id || i} grade={lg}
                noExplanationLabel={t('ors_no_explanation')} />
            ))}
          </div>
        </details>
      )}

      {/* Generation Logs (per-stage view) */}
      <GenerationLogs
        ckptId={ckptId}
        orsRubricMeta={orsRubricMeta}
        orsRubric={orsRubric}
        orsReplicator={orsReplicator}
        orsSeed={orsSeed}
        orsPhase1={orsPhase1}
        reproLog={reproLog}
        onToggleLog={onToggleLog}
        onRefreshLog={onRefreshLog}
        t={t}
      />

      {/* Provenance footer */}
      <Provenance
        orsGrade={orsGrade}
        orsPhase1={orsPhase1}
        orsReplicator={orsReplicator}
        orsRubricMeta={orsRubricMeta}
      />
    </div>
  );
}

// ─── Grading tree section (list/tree view toggle) ────────────────────────

function GradingTreeSection({
  rubric, leafGrades, passed, total, t,
}: {
  rubric: RubricNode;
  leafGrades: any[];
  passed: number;
  total: number;
  t: (key: string) => string;
}): React.ReactNode {
  const [view, setView] = useState<'list' | 'tree'>('list');
  const gradesById = React.useMemo(() => buildGradeMap(leafGrades), [leafGrades]);
  const toggleBtn = (mode: 'list' | 'tree', label: string) => (
    <button
      type="button"
      onClick={() => setView(mode)}
      style={{
        padding: '2px 10px', fontSize: '.7rem', fontWeight: 600,
        cursor: 'pointer', border: '1px solid var(--border)',
        background: view === mode ? 'var(--blue-light, #60a5fa)' : 'transparent',
        color: view === mode ? '#0b1220' : 'var(--muted)',
        borderRadius: 4,
      }}
    >
      {label}
    </button>
  );
  return (
    <details open style={{ marginBottom: 8 }}>
      <summary
        style={{
          cursor: 'pointer', fontSize: '.78rem', color: 'var(--muted)',
          userSelect: 'none', padding: '4px 0',
        }}
      >
        ▸ {t('ors_tree_header')} ({passed} ✓ / {total - passed} ✗)
      </summary>
      <div style={{
        display: 'flex', gap: 4, marginTop: 4, marginBottom: 4,
      }}>
        {toggleBtn('list', t('ors_view_list'))}
        {toggleBtn('tree', t('ors_view_tree'))}
      </div>
      {view === 'list' ? (
        <div
          style={{
            marginTop: 6, maxHeight: 460, overflowY: 'auto',
            border: '1px solid var(--border)', borderRadius: 4,
            padding: '4px 0',
          }}
        >
          <RubricTreeNode
            node={rubric}
            gradesById={gradesById}
            depth={0}
            noExplanationLabel={t('ors_no_explanation')}
          />
        </div>
      ) : (
        <div
          style={{
            marginTop: 6,
            border: '1px solid var(--border)', borderRadius: 4,
            overflow: 'hidden',
          }}
        >
          <RubricTreeVisualization
            node={rubric}
            gradesById={gradesById}
            noExplanationLabel={t('ors_no_explanation')}
          />
        </div>
      )}
    </details>
  );
}

// ─── Rubric grading tree (recursive PaperBench TaskNode renderer) ────────

function RubricTreeNode({
  node, gradesById, depth, noExplanationLabel,
}: {
  node: RubricNode;
  gradesById: Map<string, LeafGrade>;
  depth: number;
  noExplanationLabel: string;
}): React.ReactNode {
  const children = node.sub_tasks || [];
  const isLeaf = children.length === 0;
  const agg = aggregateScore(node, gradesById);
  const score = agg.score;
  const isPassed = score !== null && score >= 0.5;
  const indent = depth * 16;
  const grade = isLeaf && node.id ? gradesById.get(String(node.id)) : undefined;
  const explanation: string = String(grade?.explanation || '');

  // Color cue: green if pass, red if fail, yellow if partial
  const dotColor =
    score === null ? 'var(--muted)' :
    score >= 0.7 ? 'var(--green)' :
    score >= 0.3 ? 'var(--yellow)' :
    'var(--red)';

  const summaryRow = (
    <div
      style={{
        display: 'flex', gap: 6, alignItems: 'flex-start',
        padding: '4px 8px', paddingLeft: 8 + indent,
        fontSize: '.75rem',
        listStyle: 'none', userSelect: 'none',
      }}
    >
      <span
        style={{
          width: 10, height: 10, borderRadius: '50%',
          background: dotColor, flexShrink: 0,
          marginTop: 4,
        }}
        title={score !== null ? `score=${score.toFixed(3)}` : 'pending'}
      />
      {isLeaf && (
        <span style={{
          color: isPassed ? 'var(--green)' : 'var(--red)',
          fontWeight: 700, minWidth: 12,
        }}>
          {isPassed ? '✓' : '✗'}
        </span>
      )}
      {node.task_category && isLeaf && (
        <span style={{
          fontSize: '.62rem', color: 'var(--muted)',
          minWidth: 100, padding: '1px 4px',
          background: 'var(--surface-2, rgba(0,0,0,0.05))',
          borderRadius: 3, textAlign: 'center',
          alignSelf: 'flex-start',
        }}>
          {node.task_category}
        </span>
      )}
      <span style={{
        flex: 1, color: 'var(--text)', wordBreak: 'break-word',
        fontWeight: !isLeaf && depth === 0 ? 600 : 400,
      }}>
        {node.requirements || '(unnamed)'}
      </span>
      {!isLeaf && (
        <span style={{ fontSize: '.7rem', color: 'var(--muted)', whiteSpace: 'nowrap' }}>
          {agg.passed}/{agg.total}
          {score !== null && ` · ${(score * 100).toFixed(0)}%`}
        </span>
      )}
      {node.weight !== undefined && (
        <span style={{ fontSize: '.7rem', color: 'var(--muted)' }}>
          w={node.weight}
        </span>
      )}
    </div>
  );

  if (isLeaf) {
    return (
      <details style={{ borderBottom: '1px solid var(--border)' }}>
        <summary style={{ cursor: 'pointer', listStyle: 'none' }}>
          {summaryRow}
        </summary>
        <div style={{
          padding: `4px 8px 8px ${30 + indent}px`,
          fontSize: '.7rem', color: 'var(--muted)',
          whiteSpace: 'pre-wrap', wordBreak: 'break-word',
        }}>
          {explanation || noExplanationLabel}
        </div>
      </details>
    );
  }
  return (
    <details open={depth < 1} style={{ borderBottom: '1px solid var(--border)' }}>
      <summary style={{ cursor: 'pointer', listStyle: 'none' }}>
        {summaryRow}
      </summary>
      <div>
        {children.map((c, i) => (
          <RubricTreeNode
            key={c.id || i}
            node={c}
            gradesById={gradesById}
            depth={depth + 1}
            noExplanationLabel={noExplanationLabel}
          />
        ))}
      </div>
    </details>
  );
}

// ─── Stage-by-stage Generation Logs ───────────────────────────────────

function GenerationLogs(
  { ckptId, orsRubricMeta, orsRubric, orsReplicator, orsSeed, orsPhase1, reproLog, onToggleLog, onRefreshLog, t }:
  {
    ckptId: string;
    orsRubricMeta?: Record<string, any>;
    orsRubric?: Record<string, any>;
    orsReplicator?: Record<string, any>;
    orsSeed?: Record<string, any>;
    orsPhase1?: Record<string, any>;
    reproLog: { open: boolean; loading: boolean; content: string | null; path: string | null };
    onToggleLog: () => void;
    onRefreshLog: () => void;
    t: (key: string) => string;
  },
): React.ReactNode {
  return (
    <details style={{ marginTop: 12, marginBottom: 8 }}>
      <summary style={{
        cursor: 'pointer', fontSize: '.78rem',
        color: 'var(--blue-light)', fontWeight: 700,
        textTransform: 'uppercase', letterSpacing: '.04em',
        userSelect: 'none', padding: '4px 0',
      }}>
        📜 {t('ors_logs_title')}
      </summary>
      <div style={{
        marginTop: 4, display: 'flex', flexDirection: 'column', gap: 6,
      }}>
        {/* ① Rubric generation */}
        <LogStage
          label={t('ors_stage_rubric')}
          summary={
            orsRubricMeta
              ? `${orsRubricMeta.model || '?'} · ${orsRubricMeta.leaves_count ?? '?'} leaves`
              + (orsRubricMeta.target_leaf_count
                  ? ` · target=${orsRubricMeta.target_leaf_count}` : '')
              : '—'
          }
          warnings={(orsRubricMeta?.warnings as string[]) || []}
        >
          {orsRubricMeta && (
            <KvList
              items={[
                ['model', orsRubricMeta.model],
                ['leaves_count', orsRubricMeta.leaves_count],
                ['depth', orsRubricMeta.depth],
                ['target_leaf_count', orsRubricMeta.target_leaf_count],
                ['auto_computed_target', orsRubricMeta.auto_computed_target],
                ['paper_sha256', truncSha(orsRubricMeta.paper_sha256)],
                ['rubric_sha256', truncSha(orsRubricMeta.rubric_sha256)],
                ['prompt_sha256', truncSha(orsRubricMeta.prompt_sha256)],
              ]}
            />
          )}
          {orsRubricMeta?.category_breakdown && (
            <KvList items={
              Object.entries(orsRubricMeta.category_breakdown as Record<string, any>)
                .map(([k, v]) => [`category::${k}`, v])
            } />
          )}
          {orsRubric?.reproduce_contract && (
            <KvList items={[
              ['expected_artifacts',
                JSON.stringify(orsRubric.reproduce_contract.expected_artifacts || [])],
              ['max_runtime_sec', orsRubric.reproduce_contract.max_runtime_sec],
            ]} />
          )}
        </LogStage>

        {/* ② Replicator (or EAR seed) */}
        <LogStage
          label={t('ors_stage_replicator')}
          summary={(() => {
            if (orsSeed?.populated) {
              return `EAR-seeded · ${fileCount(orsSeed.files)} files`;
            }
            if (orsReplicator?.populated) {
              return `LLM (${orsReplicator.model || '?'}) · ${fileCount(orsReplicator.files)} files`;
            }
            return '—';
          })()}
          warnings={(orsReplicator?.warnings as string[]) || []}
        >
          {orsSeed?.populated && (
            <KvList items={[
              ['mode', 'EAR / curated bundle'],
              ['files', formatFiles(orsSeed.files)],
              ['bundle_sha256', truncSha(orsSeed.bundle_sha256)],
              ['dest', orsSeed.dest],
            ]} />
          )}
          {orsReplicator?.populated && (
            <>
              <KvList items={[
                ['mode', 'LLM (paper → reproduce.sh)'],
                ['model', orsReplicator.model],
                ['language', orsReplicator.language],
                ['max_runtime_sec', orsReplicator.max_runtime_sec],
                ['files', formatFiles(orsReplicator.files)],
                ['expected_artifacts',
                  JSON.stringify(orsReplicator.expected_artifacts || [])],
                ['prompt_sha256', truncSha(orsReplicator.prompt_sha256)],
              ]} />
              {orsReplicator.notes && (
                <CollapsibleText label="notes" content={String(orsReplicator.notes)} />
              )}
            </>
          )}
          {orsReplicator?.error && (
            <KvList items={[['error', String(orsReplicator.error)]]} />
          )}
          {/* File viewers — fetch reproduce.sh and any source on demand. */}
          {(orsReplicator?.populated || orsSeed?.populated) && ckptId && (
            <FileViewers
              ckptId={ckptId}
              files={asFileList(orsReplicator?.files ?? orsSeed?.files)}
              prefix="repro_sandbox"
            />
          )}
        </LogStage>

        {/* ③ Phase 1 (build/run) — folds the existing reproduce.log toggle */}
        <LogStage
          label={t('ors_stage_phase1')}
          summary={(() => {
            if (!orsPhase1) return '—';
            if (!orsPhase1.executed) return orsPhase1.skipped_reason || 'skipped';
            const sb = orsPhase1.sandbox_kind || '?';
            const part = orsPhase1.partition ? `:${orsPhase1.partition}` : '';
            return `${sb}${part} · exit ${orsPhase1.exit_code} `
              + `· ${typeof orsPhase1.elapsed_sec === 'number' ? orsPhase1.elapsed_sec.toFixed(1) : '?'}s`;
          })()}
        >
          {orsPhase1 && (
            <KvList items={[
              ['executed', orsPhase1.executed],
              ['exit_code', orsPhase1.exit_code],
              ['sandbox_kind', orsPhase1.sandbox_kind],
              ['partition', orsPhase1.partition],
              ['cpus', orsPhase1.cpus],
              ['walltime', orsPhase1.walltime],
              ['elapsed_sec', orsPhase1.elapsed_sec],
              ['missing', JSON.stringify(orsPhase1.missing || [])],
              ['artifacts', `${(orsPhase1.artifacts || []).length} files`],
            ]} />
          )}
          <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
            <Button onClick={onToggleLog} style={{ fontSize: '.7rem', padding: '2px 8px' }}>
              {reproLog.open ? t('repro_log_hide') : t('repro_log_show')}
            </Button>
            {reproLog.open && (
              <Button
                onClick={onRefreshLog}
                style={{ fontSize: '.7rem', padding: '2px 8px' }}
                disabled={reproLog.loading}
                title={t('repro_log_refresh')}
              >
                {t('repro_log_refresh')}
              </Button>
            )}
          </div>
          {reproLog.open && (
            <div style={{
              border: '1px solid var(--border)', borderRadius: 4,
              marginTop: 6, maxHeight: 320, overflow: 'auto',
              background: 'var(--bg)',
            }}>
              {reproLog.path && (
                <div style={{
                  fontSize: '.66rem', color: 'var(--muted)',
                  padding: '4px 8px', borderBottom: '1px solid var(--border)',
                  fontFamily: 'monospace',
                }}>
                  {reproLog.path}
                </div>
              )}
              {reproLog.loading ? (
                <div style={{ padding: 8, fontSize: '.72rem', color: 'var(--muted)' }}>
                  {t('repro_log_loading')}
                </div>
              ) : reproLog.content ? (
                <pre style={{
                  margin: 0, padding: '6px 10px',
                  fontSize: '.68rem', lineHeight: 1.45,
                  fontFamily: 'monospace',
                  whiteSpace: 'pre-wrap', wordBreak: 'break-all',
                  color: 'var(--text)',
                }}>
                  {reproLog.content}
                </pre>
              ) : (
                <div style={{ padding: 8, fontSize: '.72rem', color: 'var(--muted)' }}>
                  {t('repro_log_empty')}
                </div>
              )}
            </div>
          )}
        </LogStage>
      </div>
    </details>
  );
}

function LogStage(
  { label, summary, warnings, children }: {
    label: string;
    summary: string;
    warnings?: string[];
    children?: React.ReactNode;
  },
): React.ReactNode {
  return (
    <details style={{
      border: '1px solid var(--border)', borderRadius: 4,
      background: 'var(--surface-2, rgba(0,0,0,0.02))',
    }}>
      <summary style={{
        cursor: 'pointer', padding: '6px 10px',
        fontSize: '.75rem', userSelect: 'none',
        display: 'flex', gap: 8, alignItems: 'baseline',
      }}>
        <span style={{ fontWeight: 600, minWidth: 160 }}>{label}</span>
        <span style={{ flex: 1, color: 'var(--muted)' }}>{summary}</span>
        {warnings && warnings.length > 0 && (
          <span style={{ fontSize: '.7rem', color: 'var(--yellow)' }}>
            ⚠ {warnings.length}
          </span>
        )}
      </summary>
      <div style={{ padding: '4px 12px 8px 24px' }}>
        {children}
        {warnings && warnings.length > 0 && (
          <CollapsibleText
            label="warnings"
            content={warnings.map((w) => `• ${w}`).join('\n')}
          />
        )}
      </div>
    </details>
  );
}

function KvList({ items }: { items: Array<[string, any]> }): React.ReactNode {
  const visible = items.filter(([_, v]) => v !== undefined && v !== null && v !== '');
  if (visible.length === 0) return null;
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: 'auto 1fr',
      columnGap: 8, rowGap: 2, fontSize: '.7rem',
      fontFamily: 'monospace', marginTop: 4,
    }}>
      {visible.map(([k, v]) => (
        <React.Fragment key={k}>
          <span style={{ color: 'var(--muted)' }}>{k}:</span>
          <span style={{ wordBreak: 'break-all', color: 'var(--text)' }}>{String(v)}</span>
        </React.Fragment>
      ))}
    </div>
  );
}

function CollapsibleText({ label, content }: { label: string; content: string }): React.ReactNode {
  return (
    <details style={{ marginTop: 6 }}>
      <summary style={{
        cursor: 'pointer', fontSize: '.7rem', color: 'var(--muted)',
        userSelect: 'none',
      }}>
        ▸ {label}
      </summary>
      <pre style={{
        margin: '4px 0 0 0', padding: '6px 8px',
        fontSize: '.68rem', lineHeight: 1.45,
        fontFamily: 'monospace',
        whiteSpace: 'pre-wrap', wordBreak: 'break-word',
        background: 'var(--bg)',
        border: '1px solid var(--border)', borderRadius: 4,
        maxHeight: 240, overflow: 'auto',
      }}>
        {content}
      </pre>
    </details>
  );
}

function FileViewers(
  { ckptId, files, prefix }: { ckptId: string; files: string[]; prefix?: string },
): React.ReactNode {
  // Show a "Show <file>" button per file; lazily fetch + cache content.
  const codeFiles = files.filter((f) =>
    /\.(sh|py|cpp|c|h|hpp|js|ts|rs|go|java|R|jl|m|tex|md|txt|json|yaml|yml|toml)$/i.test(f)
  );
  if (codeFiles.length === 0) return null;
  return (
    <div style={{ marginTop: 6 }}>
      {codeFiles.map((f) => (
        <FileViewer
          key={f}
          ckptId={ckptId}
          path={prefix ? `${prefix}/${f}` : f}
          label={f}
        />
      ))}
    </div>
  );
}

function FileViewer(
  { ckptId, path, label }: { ckptId: string; path: string; label: string },
): React.ReactNode {
  const [open, setOpen] = useState(false);
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleToggle = async () => {
    if (open) { setOpen(false); return; }
    setOpen(true);
    if (content !== null) return;
    setLoading(true);
    setError(null);
    try {
      const j = await fetchCheckpointFilecontent(ckptId, path);
      setContent(typeof j.content === 'string' ? j.content : JSON.stringify(j, null, 2));
    } catch (e: any) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ marginTop: 4 }}>
      <Button
        onClick={handleToggle}
        style={{ fontSize: '.7rem', padding: '2px 8px' }}
      >
        {open ? `▾ ${label}` : `▸ ${label}`}
      </Button>
      {open && (
        <div style={{
          marginTop: 4,
          border: '1px solid var(--border)', borderRadius: 4,
          maxHeight: 320, overflow: 'auto',
          background: 'var(--bg)',
        }}>
          {loading ? (
            <div style={{ padding: 8, fontSize: '.7rem', color: 'var(--muted)' }}>
              loading…
            </div>
          ) : error ? (
            <div style={{ padding: 8, fontSize: '.7rem', color: 'var(--red)' }}>
              {error}
            </div>
          ) : (
            <pre style={{
              margin: 0, padding: '6px 10px',
              fontSize: '.66rem', lineHeight: 1.4,
              fontFamily: 'monospace',
              whiteSpace: 'pre', overflow: 'auto',
              color: 'var(--text)',
            }}>
              {content}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

function ScoreBar({ weighted, raw }: { weighted: number; raw?: number }): React.ReactNode {
  const wpct = Math.max(0, Math.min(1, weighted)) * 100;
  const rpct = raw !== undefined ? Math.max(0, Math.min(1, raw)) * 100 : null;
  const fillColor = wpct >= 70 ? 'var(--green)' : wpct >= 30 ? 'var(--yellow)' : 'var(--red)';
  return (
    <div style={{ marginBottom: 10 }}>
      <div
        style={{
          width: '100%', height: 8, background: 'var(--bg)',
          border: '1px solid var(--border)', borderRadius: 4, overflow: 'hidden',
          position: 'relative',
        }}
      >
        <div
          style={{
            width: `${wpct}%`, height: '100%',
            background: fillColor, transition: 'width 0.3s ease',
          }}
        />
        {rpct !== null && (
          <div
            style={{
              position: 'absolute', top: 0, left: `${rpct}%`,
              width: 2, height: '100%', background: 'var(--text)', opacity: 0.5,
            }}
            title={`raw=${(rpct).toFixed(1)}%`}
          />
        )}
      </div>
      <div style={{ fontSize: '.7rem', color: 'var(--muted)', marginTop: 2 }}>
        weighted {weighted.toFixed(3)}
        {raw !== undefined && ` · raw ${raw.toFixed(3)}`}
      </div>
    </div>
  );
}

function ChainStage(
  { label, state, detail }: { label: string; state: StageState; detail: React.ReactNode },
): React.ReactNode {
  const icon = state === 'ok' ? '✓' : state === 'fail' ? '✗' : state === 'partial' ? '◐' : '·';
  const color =
    state === 'ok' ? 'var(--green)' :
    state === 'fail' ? 'var(--red)' :
    state === 'partial' ? 'var(--yellow)' :
    'var(--muted)';
  return (
    <div
      style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '4px 8px',
        background: 'var(--surface-2, rgba(0,0,0,0.04))',
        borderRadius: 4,
      }}
    >
      <span
        style={{
          width: 18, height: 18, lineHeight: '18px',
          textAlign: 'center', borderRadius: '50%',
          background: color, color: 'var(--bg)',
          fontSize: '.7rem', fontWeight: 700, flexShrink: 0,
        }}
      >
        {icon}
      </span>
      <span style={{ fontSize: '.78rem', fontWeight: 600, minWidth: 160 }}>
        {label}
      </span>
      <span style={{ fontSize: '.75rem', color: 'var(--muted)', flex: 1, wordBreak: 'break-word' }}>
        {detail}
      </span>
    </div>
  );
}

function LeafGradeRow({ grade, noExplanationLabel }: {
  grade: Record<string, any>;
  noExplanationLabel?: string;
}): React.ReactNode {
  const passed = (grade.passed_runs ?? 0) > 0;
  const cat = grade.task_category || '—';
  const explanation: string = String(grade.explanation || '');
  return (
    <details style={{ borderBottom: '1px solid var(--border)' }}>
      <summary
        style={{
          cursor: 'pointer', padding: '6px 8px', display: 'flex',
          gap: 8, alignItems: 'flex-start', fontSize: '.75rem',
          listStyle: 'none', userSelect: 'none',
        }}
      >
        <span style={{
          color: passed ? 'var(--green)' : 'var(--red)',
          fontWeight: 700, minWidth: 14,
        }}>
          {passed ? '✓' : '✗'}
        </span>
        <span style={{
          fontSize: '.65rem', color: 'var(--muted)',
          minWidth: 110, padding: '1px 4px',
          background: 'var(--surface-2, rgba(0,0,0,0.05))',
          borderRadius: 3, textAlign: 'center',
          alignSelf: 'flex-start',
        }}>
          {cat}
        </span>
        <span style={{ flex: 1, color: 'var(--text)', wordBreak: 'break-word' }}>
          {grade.requirements}
        </span>
        {grade.weight !== undefined && (
          <span style={{ fontSize: '.7rem', color: 'var(--muted)' }}>
            w={grade.weight}
          </span>
        )}
      </summary>
      <div
        style={{
          padding: '4px 8px 8px 30px',
          fontSize: '.72rem', color: 'var(--muted)',
          whiteSpace: 'pre-wrap', wordBreak: 'break-word',
        }}
      >
        {explanation || noExplanationLabel || '(no explanation)'}
      </div>
    </details>
  );
}

function Provenance(
  { orsGrade, orsPhase1, orsReplicator, orsRubricMeta }:
  {
    orsGrade?: Record<string, any>;
    orsPhase1?: Record<string, any>;
    orsReplicator?: Record<string, any>;
    orsRubricMeta?: Record<string, any>;
  },
): React.ReactNode {
  const items: [string, string][] = [];
  if (orsGrade?.rubric_sha256) {
    items.push(['rubric_sha256', String(orsGrade.rubric_sha256).slice(0, 16) + '…']);
  }
  if (orsRubricMeta?.prompt_sha256) {
    items.push(['rubric_prompt_sha256', String(orsRubricMeta.prompt_sha256).slice(0, 16) + '…']);
  }
  if (orsReplicator?.prompt_sha256) {
    items.push(['replicator_prompt_sha256', String(orsReplicator.prompt_sha256).slice(0, 16) + '…']);
  }
  if (orsPhase1?.partition) {
    items.push(['partition', String(orsPhase1.partition)]);
  }
  if (orsPhase1?.cpus) {
    items.push(['cpus', String(orsPhase1.cpus)]);
  }
  if (orsPhase1?.walltime) {
    items.push(['walltime', String(orsPhase1.walltime)]);
  }
  if (!items.length) return null;
  return (
    <div
      style={{
        marginTop: 10, paddingTop: 8,
        borderTop: '1px solid var(--border)',
        fontSize: '.7rem', color: 'var(--muted)',
        fontFamily: 'monospace', display: 'grid',
        gridTemplateColumns: 'auto 1fr', columnGap: 8, rowGap: 2,
      }}
    >
      {items.map(([k, v]) => (
        <React.Fragment key={k}>
          <span>{k}:</span>
          <span style={{ wordBreak: 'break-all' }}>{v}</span>
        </React.Fragment>
      ))}
    </div>
  );
}

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

// ─── Experiment-context card (extracted from ResultsPage renderContext) ───
// Pure render of summary.science_data.experiment_context. Returns null when
// absent. Body verbatim from the container.
export function renderContext({
  summary,
  t,
}: {
  summary: CheckpointSummary | null;
  t: (key: string) => string;
}): React.ReactNode {
  if (!summary) return null;
  const sd = summary.science_data;
  if (!sd || !(sd as any).experiment_context) return null;

  const ctx = (sd as any).experiment_context as Record<string, unknown>;

  return (
    <Card style={{ marginBottom: 16 }}>
      <div className="card-title">{t('exp_context')}</div>
      <div>
        {Object.entries(ctx).map(([k, v]) => {
          const text = String(
            typeof v === 'object'
              ? JSON.stringify(v, null, 2)
              : v,
          );
          return (
            <div key={k} style={{ marginBottom: 12 }}>
              <div style={{ color: 'var(--muted)', fontSize: '.75rem', marginBottom: 2, fontWeight: 600 }}>
                {k}
              </div>
              {text.length <= 500 ? (
                <div style={{ fontSize: '.8rem', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                  {text}
                </div>
              ) : (
                <details>
                  <summary style={{ cursor: 'pointer', color: 'var(--blue-light)', fontSize: '.75rem', listStyle: 'none', userSelect: 'none' }}>
                    {'▶ Show detail'}
                  </summary>
                  <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: '4px 0 0', fontSize: '.78rem', overflow: 'auto', maxHeight: 480 }}>
                    {text}
                  </pre>
                </details>
              )}
            </div>
          );
        })}
      </div>
    </Card>
  );
}

// ─── Figures grid (extracted from ResultsPage renderFigures) ──────────────
// Pure render of summary.figures_manifest (dict or legacy-list shape). Returns
// null when absent/empty. Body verbatim from the container.
export function renderFigures({
  summary,
}: {
  summary: CheckpointSummary | null;
}): React.ReactNode {
  if (!summary) return null;
  const fm = summary.figures_manifest as any;
  if (!fm || !fm.figures) return null;

  // plot-skill writes `figures` as a dict {name: path}; older runs may
  // have stored a list [{path, caption, ...}]. Normalize to a list here
  // so the grid works with both shapes.
  const kinds = (fm.figure_kinds || {}) as Record<string, string>;
  const snippets = (fm.latex_snippets || {}) as Record<string, string>;
  const extractCaption = (snip: string): string => {
    const m = snip.match(/\\caption\{([^}]+)\}/);
    return m ? m[1] : '';
  };
  const figs: Array<{ name: string; path: string; caption: string; kind: string }> =
    Array.isArray(fm.figures)
      ? fm.figures.map((fig: any, idx: number) => ({
          name: fig.name || `fig_${idx + 1}`,
          path: fig.path || fig,
          caption: fig.caption || '',
          kind: fig.kind || fig.figure_kind || '',
        }))
      : Object.entries(fm.figures as Record<string, string>).map(([name, path]) => ({
          name,
          path: String(path),
          caption: extractCaption(snippets[name] || ''),
          kind: kinds[name] || '',
        }));

  if (!figs.length) return null;

  return (
    <Card style={{ marginBottom: 16 }}>
      <div className="card-title">{'📈'} Figures</div>
      <div className="grid-2">
        {figs.map((fig, idx) => {
          const { path, caption, kind } = fig;
          const kindBadge: Record<string, string> = {
            plot: 'Plot',
            svg: 'Diagram',
          };
          return (
            <div key={idx}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                {kind && kindBadge[kind] && (
                  <Badge variant="blue">{kindBadge[kind]}</Badge>
                )}
                {caption && (
                  <span style={{ fontSize: '.8rem', color: 'var(--muted)' }}>
                    {caption}
                  </span>
                )}
              </div>
              <img
                className="figure-img"
                src={`/codefile?path=${encodeURIComponent(path)}`}
                alt="figure"
                onError={(e) => {
                  (e.target as HTMLImageElement).style.display = 'none';
                }}
              />
            </div>
          );
        })}
      </div>
    </Card>
  );
}

// ─── Review-scores card (extracted from ResultsPage renderReviewScores) ───
// Pure render of summary.review_report (rubric-driven or legacy schema). The
// decisionVariant/decisionLabel/renderDimension helpers were container-local
// and used only here, so they are nested verbatim (decisionLabel/renderDimension
// close over the t param exactly as they did the container's t). Returns null
// when no review_report. Body verbatim from the container.
export function renderReviewScores({
  summary,
  t,
}: {
  summary: CheckpointSummary | null;
  t: (key: string) => string;
}): React.ReactNode {
  // Decision → badge variant mapping
  const decisionVariant = (
    d?: string,
  ): 'green' | 'red' | 'yellow' | 'muted' => {
    if (!d) return 'muted';
    if (d === 'accept' || d === 'weak_accept') return 'green';
    if (d === 'reject' || d === 'weak_reject') return 'red';
    if (d === 'borderline') return 'yellow';
    return 'muted';
  };

  const decisionLabel = (d?: string): string => {
    if (!d) return '—';
    const key = `review_${d}`;
    const localized = t(key);
    return localized === key ? d : localized;
  };

  // Render one dimensional score (rubric-driven)
  const renderDimension = (
    name: string,
    value: number | null | undefined,
    scale: [number, number] | undefined,
  ) => {
    const [lo, hi] = scale ?? [0, 10];
    const range = hi - lo || 1;
    const pct =
      value != null ? Math.max(0, Math.min(100, ((value - lo) / range) * 100)) : 0;
    return (
      <div key={name}>
        <div
          style={{
            fontSize: '.8rem',
            color: 'var(--muted)',
            marginBottom: 4,
            textTransform: 'capitalize',
          }}
        >
          {name.replace(/_/g, ' ')}
        </div>
        <div style={{ fontSize: '1.4rem', fontWeight: 800 }}>
          {value != null ? value : '—'}{' '}
          <span style={{ fontSize: '.9rem', color: 'var(--muted)' }}>
            /{hi}
          </span>
        </div>
        {value != null && (
          <div className="score-bar">
            <div className="score-fill" style={{ width: `${pct}%` }} />
          </div>
        )}
      </div>
    );
  };

  const rr = summary?.review_report;
  if (!rr) return null;

  // Rubric-driven path: new schema with score_dimensions
  const hasRubric =
    !!rr.rubric_id || (rr.score_dimensions && rr.score_dimensions.length > 0);

  const legacyScores: [string, number | null][] = [
    [t('abstract'), rr.abstract_score ?? rr.scores?.abstract ?? null],
    [t('body'), rr.body_score ?? rr.scores?.body ?? null],
    [t('overall'), rr.overall_score ?? rr.score ?? null],
  ];

  const textSections: Array<{ key: string; label: string; body?: string }> = [
    { key: 'strengths', label: t('review_strengths'), body: rr.strengths },
    { key: 'weaknesses', label: t('review_weaknesses'), body: rr.weaknesses },
    { key: 'questions', label: t('review_questions'), body: rr.questions },
    {
      key: 'limitations',
      label: t('review_limitations'),
      body: rr.limitations,
    },
  ].filter((s) => s.body && s.body.trim().length > 0);

  return (
    <Card style={{ marginBottom: 16 }}>
      <div
        className="card-title"
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 8,
          flexWrap: 'wrap',
        }}
      >
        <span>{t('review_scores')}</span>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {rr.rubric_id && (
            <Badge variant="muted">
              {t('review_rubric')}: {rr.rubric_id}
              {rr.rubric_version ? ` @${rr.rubric_version}` : ''}
            </Badge>
          )}
          {rr.venue && <Badge variant="muted">{rr.venue}</Badge>}
          {rr.decision && (
            <Badge variant={decisionVariant(rr.decision)}>
              {t('review_decision')}: {decisionLabel(rr.decision)}
            </Badge>
          )}
        </div>
      </div>

      {hasRubric && rr.score_dimensions && rr.score_dimensions.length > 0 ? (
        <div
          className="grid-3"
          style={{
            gridTemplateColumns: `repeat(${Math.min(
              rr.score_dimensions.length,
              5,
            )}, minmax(0, 1fr))`,
          }}
        >
          {rr.score_dimensions.map((d) =>
            renderDimension(d.name, d.value, d.scale),
          )}
        </div>
      ) : (
        <div className="grid-3">
          {legacyScores.map(([label, value]) => (
            <div key={label}>
              <div
                style={{
                  fontSize: '.8rem',
                  color: 'var(--muted)',
                  marginBottom: 4,
                }}
              >
                {label}
              </div>
              <div style={{ fontSize: '1.4rem', fontWeight: 800 }}>
                {value != null ? value : '—'}{' '}
                <span style={{ fontSize: '.9rem', color: 'var(--muted)' }}>
                  /10
                </span>
              </div>
              {value != null && (
                <div className="score-bar">
                  <div
                    className="score-fill"
                    style={{ width: `${(value as number) * 10}%` }}
                  />
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {rr.confidence != null && (
        <div style={{ marginTop: 12, fontSize: '.9rem' }}>
          {t('review_confidence')}:{' '}
          <strong>{rr.confidence}</strong>
        </div>
      )}

      {textSections.length > 0 && (
        <div style={{ marginTop: 16, display: 'grid', gap: 12 }}>
          {textSections.map((s) => (
            <div key={s.key}>
              <div
                style={{
                  fontSize: '.85rem',
                  fontWeight: 700,
                  marginBottom: 4,
                }}
              >
                {s.label}
              </div>
              <div
                style={{
                  whiteSpace: 'pre-wrap',
                  fontSize: '.85rem',
                  lineHeight: 1.5,
                  color: 'var(--muted)',
                }}
              >
                {s.body}
              </div>
            </div>
          ))}
        </div>
      )}

      {rr.issues && rr.issues.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: '.85rem', fontWeight: 700, marginBottom: 4 }}>
            {t('review_issues')}
          </div>
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: '.85rem' }}>
            {rr.issues.map((x, i) => (
              <li key={i}>{x}</li>
            ))}
          </ul>
        </div>
      )}

      {rr.recommendations && rr.recommendations.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: '.85rem', fontWeight: 700, marginBottom: 4 }}>
            {t('review_recommendations')}
          </div>
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: '.85rem' }}>
            {rr.recommendations.map((x, i) => (
              <li key={i}>{x}</li>
            ))}
          </ul>
        </div>
      )}

      {rr.figure_caption_issues && rr.figure_caption_issues.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: '.85rem', fontWeight: 700, marginBottom: 4 }}>
            {t('review_figure_caption_issues')}
          </div>
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: '.85rem' }}>
            {rr.figure_caption_issues.map((x, i) => (
              <li key={i}>{x}</li>
            ))}
          </ul>
        </div>
      )}

      {rr.ensemble_reviews && rr.ensemble_reviews.length > 1 && (
        <div style={{ marginTop: 16 }}>
          <div style={{ fontSize: '.85rem', fontWeight: 700, marginBottom: 6 }}>
            {t('review_ensemble')} ({rr.ensemble_reviews.length})
          </div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {rr.ensemble_reviews.map((er, i) => (
              <Badge key={i} variant={decisionVariant(er.decision)}>
                #{i + 1}:{' '}
                {er.overall_score ?? er.score ?? '—'}{' '}
                {er.decision ? `(${decisionLabel(er.decision)})` : ''}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {rr.meta_review && (
        <div style={{ marginTop: 12, padding: 10, border: '1px solid var(--border)', borderRadius: 6 }}>
          <div style={{ fontSize: '.85rem', fontWeight: 700, marginBottom: 4 }}>
            {t('review_meta')}
          </div>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            {rr.meta_review.decision && (
              <Badge variant={decisionVariant(rr.meta_review.decision)}>
                {decisionLabel(rr.meta_review.decision)}
              </Badge>
            )}
            <span style={{ fontSize: '.9rem' }}>
              {t('overall')}:{' '}
              <strong>
                {rr.meta_review.overall_score ?? rr.meta_review.score ?? '—'}
              </strong>
            </span>
          </div>
        </div>
      )}

      {rr.fewshot_sources && rr.fewshot_sources.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: '.85rem', fontWeight: 700, marginBottom: 4 }}>
            {t('review_fewshot_sources')}
          </div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {rr.fewshot_sources.map((fs, i) => (
              <Badge key={i} variant="muted">
                {fs.title ?? fs.id}
                {fs.score != null ? ` (${fs.score.toFixed(2)})` : ''}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {rr.citation_ok != null && (
        <div style={{ marginTop: 12 }}>
          {t('citations')}:{' '}
          {rr.citation_ok ? (
            <Badge variant="green">{'✓'} {t('ok_label')}</Badge>
          ) : (
            <Badge variant="red">{'✗'} {t('issues_label')}</Badge>
          )}
        </div>
      )}
    </Card>
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
