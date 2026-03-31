import { useCallback, useEffect, useRef, useState } from 'react';
import { useI18n } from '../../i18n';
import {
  fetchWorkflow,
  saveWorkflow as apiSaveWorkflow,
  fetchSkillDetail,
} from '../../services/api';
import type { WorkflowData, WorkflowStage } from '../../types';
import { Card } from '../common';

// ── Dynamic skill colour (deterministic hash) ───────

const SKILL_PALETTE = [
  '#3b82f6', '#f59e0b', '#8b5cf6', '#06b6d4', '#10b981',
  '#ef4444', '#f97316', '#64748b', '#a78bfa', '#ec4899',
  '#84cc16', '#f43f5e', '#d946ef', '#0ea5e9', '#14b8a6',
];

function skillColor(name: string): string {
  let h = 0;
  for (let i = 0; i < name.length; i++) {
    h = ((h << 5) - h + name.charCodeAt(i)) | 0;
  }
  return SKILL_PALETTE[Math.abs(h) % SKILL_PALETTE.length];
}

// ── DAG layout helper ────────────────────────────────

interface DagPos {
  x: number;
  y: number;
}

function buildDagSvg(pipeline: WorkflowStage[]): string {
  const depMap: Record<string, string[]> = {};
  pipeline.forEach((s) => {
    depMap[s.stage] = s.depends_on || [];
  });

  const levels: Record<string, number> = {};
  function getLevel(stage: string): number {
    if (levels[stage] !== undefined) return levels[stage];
    const deps = depMap[stage] || [];
    levels[stage] =
      deps.length === 0 ? 0 : Math.max(...deps.map((d) => getLevel(d) + 1));
    return levels[stage];
  }
  pipeline.forEach((s) => getLevel(s.stage));

  const colW = 155,
    nodeH = 50,
    padX = 12,
    padY = 12,
    colGap = 32;
  const maxLevel = Math.max(0, ...Object.values(levels));

  const colRow: Record<number, number> = {};
  const posMap: Record<string, DagPos> = {};
  pipeline.forEach((s) => {
    const lv = levels[s.stage];
    if (colRow[lv] === undefined) colRow[lv] = 0;
    posMap[s.stage] = { x: padX + lv * (colW + colGap), y: padY + colRow[lv] * (nodeH + 10) };
    colRow[lv]++;
  });

  const maxRows = Math.max(1, ...Object.values(colRow));
  const svgW = padX * 2 + (maxLevel + 1) * (colW + colGap);
  const svgH = padY * 2 + maxRows * (nodeH + 10);

  let svg =
    `<svg width="${svgW}" height="${svgH}" style="font-family:var(--font);display:block">` +
    '<defs><marker id="warr" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">' +
    '<path d="M0,0 L7,3.5 L0,7 Z" fill="rgba(255,255,255,.3)"/></marker></defs>';

  // Dependency edges (bezier)
  pipeline.forEach((s) => {
    (s.depends_on || []).forEach((dep) => {
      if (!posMap[dep] || !posMap[s.stage]) return;
      const x1 = posMap[dep].x + colW,
        y1 = posMap[dep].y + nodeH / 2;
      const x2 = posMap[s.stage].x,
        y2 = posMap[s.stage].y + nodeH / 2;
      const mx = (x1 + x2) / 2;
      svg += `<path d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}" fill="none" stroke="rgba(255,255,255,.2)" stroke-width="1.5" marker-end="url(#warr)"/>`;
    });
  });

  // Nodes
  pipeline.forEach((s) => {
    const pos = posMap[s.stage];
    const col = skillColor(s.skill);
    const enabled = s.enabled !== false;
    const sname = s.stage.replace(/_/g, ' ');

    svg +=
      `<g opacity="${enabled ? 1 : 0.4}" style="cursor:pointer">` +
      `<rect x="${pos.x}" y="${pos.y}" width="${colW}" height="${nodeH}" rx="7" fill="${col}" fill-opacity=".12" stroke="${col}" stroke-width="1.5"/>` +
      `<text x="${pos.x + 8}" y="${pos.y + 16}" fill="${col}" font-size="10" font-weight="700">${sname}</text>` +
      `<text x="${pos.x + 8}" y="${pos.y + 28}" fill="rgba(255,255,255,.45)" font-size="9">${s.skill || ''}</text>` +
      `<text x="${pos.x + 8}" y="${pos.y + 40}" fill="rgba(255,255,255,.3)" font-size="8">${s.tool || ''}</text>` +
      '</g>';

    // Conditional badge
    if (s.skip_if_exists) {
      svg +=
        `<rect x="${pos.x + colW - 44}" y="${pos.y + 2}" width="42" height="13" rx="4" fill="#f59e0b" fill-opacity=".3"/>` +
        `<text x="${pos.x + colW - 42}" y="${pos.y + 11}" fill="#f59e0b" font-size="8">skip_if</text>`;
    }
  });

  // Loop-back arrows for BFTS cycle
  pipeline.forEach((s) => {
    if (s.loop_back_to && posMap[s.stage] && posMap[s.loop_back_to]) {
      const from = posMap[s.stage],
        to = posMap[s.loop_back_to];
      const x1 = from.x + colW / 2,
        y1 = from.y + nodeH;
      const x2 = to.x + colW / 2,
        y2 = to.y + nodeH;
      svg +=
        `<path d="M${x1},${y1} C${x1},${y1 + 30} ${x2},${y2 + 30} ${x2},${y2}" fill="none" stroke="rgba(251,191,36,.4)" stroke-width="1.5" stroke-dasharray="5,3" marker-end="url(#warr)"/>` +
        `<text x="${(x1 + x2) / 2}" y="${y1 + 22}" fill="rgba(251,191,36,.7)" font-size="8" text-anchor="middle">loop</text>`;
    }
  });

  svg += '</svg>';
  return svg;
}

// ── Main component ───────────────────────────────────

export default function WorkflowPage() {
  const { t } = useI18n();
  const [wfData, setWfData] = useState<WorkflowData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<'full' | 'bfts' | 'paper'>('full');
  const [showMcp, setShowMcp] = useState(true);
  const [selectedStage, setSelectedStage] = useState<string | null>(null);
  const [saveMsg, setSaveMsg] = useState('');
  const [condType, setCondType] = useState('skip_if_exists');
  const [condValue, setCondValue] = useState('');

  // Skill modal
  const [skillModal, setSkillModal] = useState<{
    name: string;
    dir: string;
    files: Record<string, string>;
    activeFile: string;
  } | null>(null);

  // Drag state ref
  const dragRef = useRef<{ from: number } | null>(null);

  // ── data loading ─────────────────────────
  const load = useCallback(() => {
    fetchWorkflow()
      .then((d) => {
        if (!d.ok) {
          setError(d.error || 'Failed to load workflow');
          return;
        }
        setWfData(d);
        setError(null);
      })
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // ── pipeline for current view ────────────
  const getViewPipeline = useCallback(
    (mode: 'full' | 'bfts' | 'paper'): WorkflowStage[] => {
      if (!wfData) return [];
      if (mode === 'bfts') return wfData.bfts_pipeline || [];
      if (mode === 'paper') return wfData.paper_pipeline || wfData.workflow.pipeline || [];
      return wfData.full_pipeline || wfData.workflow.pipeline || [];
    },
    [wfData],
  );

  const dagPipeline = getViewPipeline(viewMode);
  const editPipeline = wfData ? wfData.paper_pipeline || wfData.workflow.pipeline || [] : [];
  const skillMcp = wfData?.skill_mcp || {};

  // ── handlers ─────────────────────────────

  function handleSave() {
    if (!wfData) return;
    setSaveMsg(t('saving'));
    apiSaveWorkflow(wfData.path, wfData.workflow.pipeline)
      .then((d) => {
        setSaveMsg(d.ok ? t('save_done') : '❌ ' + d.error);
        setTimeout(() => setSaveMsg(''), 3000);
      })
      .catch((e) => {
        setSaveMsg('❌ ' + String(e));
        setTimeout(() => setSaveMsg(''), 3000);
      });
  }

  function handleReload() {
    load();
  }

  function handleAddStage() {
    if (!wfData) return;
    const name = prompt('Stage name (snake_case):');
    if (!name) return;
    const skill = prompt('Skill name:') || '';
    const tool = prompt('MCP tool:') || '';
    const newStage: WorkflowStage = {
      stage: name,
      skill,
      tool,
      depends_on: [],
      enabled: true,
      description: '',
      inputs: {},
      outputs: {},
      load_inputs: [],
      phase: '',
      skip_if_exists: null,
      loop_back_to: null,
    };
    const updated = { ...wfData };
    updated.workflow = { ...updated.workflow, pipeline: [...updated.workflow.pipeline, newStage] };
    setWfData(updated as WorkflowData);
  }

  function handleToggleStage(idx: number, enabled: boolean) {
    if (!wfData) return;
    const pipe = [...wfData.workflow.pipeline];
    pipe[idx] = { ...pipe[idx], enabled };
    setWfData({ ...wfData, workflow: { ...wfData.workflow, pipeline: pipe } } as WorkflowData);
  }

  function handleRemoveStage(idx: number) {
    if (!wfData) return;
    if (!confirm(`Remove "${wfData.workflow.pipeline[idx].stage}"?`)) return;
    const pipe = [...wfData.workflow.pipeline];
    pipe.splice(idx, 1);
    setWfData({ ...wfData, workflow: { ...wfData.workflow, pipeline: pipe } } as WorkflowData);
  }

  function handleApplyCondition() {
    if (!selectedStage || !wfData) {
      alert('Click a stage in the DAG or list first');
      return;
    }
    if (!condType || !condValue) {
      alert('Select condition type and enter value');
      return;
    }
    const pipe = wfData.workflow.pipeline.map((s) => {
      if (s.stage !== selectedStage) return s;
      return { ...s, [condType]: condValue };
    });
    setWfData({ ...wfData, workflow: { ...wfData.workflow, pipeline: pipe } } as WorkflowData);
    setSaveMsg('✅ Applied to ' + selectedStage);
    setTimeout(() => setSaveMsg(''), 2500);
  }

  function handleDrop(toIdx: number) {
    if (!dragRef.current || !wfData) return;
    const fromIdx = dragRef.current.from;
    if (fromIdx === toIdx) return;
    const pipe = [...wfData.workflow.pipeline];
    const [moved] = pipe.splice(fromIdx, 1);
    pipe.splice(toIdx, 0, moved);
    setWfData({ ...wfData, workflow: { ...wfData.workflow, pipeline: pipe } } as WorkflowData);
    dragRef.current = null;
  }

  function openSkillModal(skillName: string) {
    fetchSkillDetail(skillName)
      .then((d: any) => {
        if (!d.ok) return;
        const files = d.files as Record<string, string>;
        const firstFile = Object.keys(files)[0] || '';
        setSkillModal({ name: skillName, dir: d.dir, files, activeFile: firstFile });
      })
      .catch(() => {});
  }

  // ── render ───────────────────────────────

  if (error) {
    return (
      <div>
        <h2>Workflow Editor</h2>
        <p style={{ color: 'var(--danger)' }}>{error}</p>
      </div>
    );
  }

  if (!wfData) {
    return <p style={{ color: 'var(--muted)' }}>{t('loading')}</p>;
  }

  const skills = wfData.workflow.skills || [];
  // Build unified skill list
  const allSkills: Record<string, { name: string; description: string; _mcp?: any }> = {};
  skills.forEach((s: any) => {
    allSkills[s.name] = s;
  });
  Object.values(skillMcp as Record<string, any>).forEach((m: any) => {
    if (!allSkills[m.name]) allSkills[m.name] = { name: m.name, description: m.description };
    allSkills[m.name]._mcp = m;
  });

  return (
    <div>
      {/* Title + actions */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          marginBottom: '14px',
          flexWrap: 'wrap',
        }}
      >
        <h2 style={{ margin: 0 }}>Workflow Editor</h2>
        <button className="btn btn-primary btn-sm" onClick={handleSave}>
          {'💾'} Save
        </button>
        <button className="btn btn-outline btn-sm" onClick={handleReload}>
          {'🔄'} Reload
        </button>
        <button className="btn btn-outline btn-sm" onClick={handleAddStage}>
          + Add Stage
        </button>
        <label style={{ fontSize: '.78rem', cursor: 'pointer', marginLeft: '8px' }}>
          <input
            type="checkbox"
            checked={showMcp}
            onChange={(e) => setShowMcp(e.target.checked)}
          />{' '}
          Show MCP tools
        </label>
        <span style={{ fontSize: '.78rem', color: 'var(--muted)' }}>{saveMsg}</span>
      </div>

      {/* DAG visualization */}
      <Card>
        {/* View tabs */}
        <div style={{ display: 'flex', gap: '6px', marginBottom: '10px' }}>
          {(['full', 'bfts', 'paper'] as const).map((mode) => (
            <button
              key={mode}
              onClick={() => setViewMode(mode)}
              style={{
                padding: '4px 12px',
                borderRadius: '6px',
                border: '1px solid var(--border)',
                background: mode === viewMode ? 'rgba(255,255,255,.15)' : 'none',
                color: 'var(--text)',
                cursor: 'pointer',
                fontSize: '.78rem',
              }}
            >
              {mode === 'full'
                ? 'Full Pipeline'
                : mode === 'bfts'
                  ? 'BFTS Loop'
                  : 'Paper Pipeline'}
            </button>
          ))}
        </div>

        <div
          style={{ overflowX: 'auto' }}
          dangerouslySetInnerHTML={{ __html: buildDagSvg(dagPipeline) }}
        />
      </Card>

      {/* Two-column: stage list + skills/conditional */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: '16px',
          marginTop: '16px',
        }}
      >
        {/* Stage list (left) */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {editPipeline.map((s, idx) => {
            const col = skillColor(s.skill);
            const enabled = s.enabled !== false;
            const mcpTools = ((skillMcp as Record<string, any>)[s.skill]?.tools as string[]) || [];

            return (
              <div
                key={s.stage + idx}
                className="card wf-stage-card"
                data-stage={s.stage}
                draggable
                onClick={() => setSelectedStage(s.stage)}
                onDragStart={() => {
                  dragRef.current = { from: idx };
                }}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  handleDrop(idx);
                }}
                style={{
                  borderLeft: `3px solid ${col}`,
                  opacity: enabled ? 1 : 0.55,
                  cursor: 'grab',
                  padding: '8px 10px',
                  outline: selectedStage === s.stage ? '2px solid var(--blue)' : 'none',
                }}
              >
                <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-start' }}>
                  <span style={{ fontSize: '.9rem' }}>{'⠇'}</span>
                  <div style={{ flex: 1, minWidth: 0, overflow: 'hidden' }}>
                    <div
                      style={{
                        display: 'flex',
                        gap: '5px',
                        alignItems: 'center',
                        flexWrap: 'wrap',
                        marginBottom: '2px',
                      }}
                    >
                      <strong style={{ color: col, fontSize: '.82rem' }}>{s.stage}</strong>
                      {s.phase && (
                        <span
                          style={{
                            fontSize: '.65rem',
                            padding: '1px 5px',
                            borderRadius: '5px',
                            background: s.phase === 'bfts' ? '#10b98122' : '#8b5cf622',
                            color: s.phase === 'bfts' ? '#10b981' : '#8b5cf6',
                          }}
                        >
                          {s.phase}
                        </span>
                      )}
                      <span
                        style={{
                          fontSize: '.7rem',
                          background: `${col}22`,
                          color: col,
                          padding: '1px 6px',
                          borderRadius: '6px',
                        }}
                      >
                        {s.skill}
                      </span>
                      {s.skip_if_exists && (
                        <span
                          style={{
                            background: '#f59e0b22',
                            color: '#f59e0b',
                            fontSize: '.7rem',
                            padding: '1px 5px',
                            borderRadius: '6px',
                          }}
                        >
                          skip_if_exists
                        </span>
                      )}
                    </div>
                    <div style={{ fontSize: '.72rem', color: 'var(--muted)' }}>
                      {'🔧'} {s.tool}
                    </div>
                    {/* Dependency pills */}
                    {(s.depends_on || []).length > 0 && (
                      <div style={{ marginTop: '3px' }}>
                        {(s.depends_on || []).map((d) => (
                          <span
                            key={d}
                            style={{
                              fontSize: '.68rem',
                              color: 'var(--muted)',
                              background: 'rgba(255,255,255,.05)',
                              padding: '1px 5px',
                              borderRadius: '5px',
                              marginRight: '4px',
                            }}
                          >
                            {'←'}{d}
                          </span>
                        ))}
                      </div>
                    )}
                    {/* MCP tool pills */}
                    {showMcp && mcpTools.length > 0 && (
                      <div
                        style={{
                          display: 'flex',
                          flexWrap: 'wrap',
                          gap: '3px',
                          marginTop: '5px',
                        }}
                      >
                        {mcpTools.map((toolName) => {
                          const active = toolName === s.tool;
                          return (
                            <span
                              key={toolName}
                              style={{
                                fontSize: '.68rem',
                                padding: '1px 6px',
                                borderRadius: '6px',
                                background: active ? `${col}33` : 'rgba(255,255,255,.05)',
                                color: active ? col : 'var(--muted)',
                                border: `1px solid ${active ? col : 'transparent'}`,
                              }}
                            >
                              {toolName}
                              {active ? ' ✓' : ''}
                            </span>
                          );
                        })}
                      </div>
                    )}
                  </div>
                  <div
                    style={{
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '3px',
                      alignItems: 'flex-end',
                    }}
                  >
                    <label
                      style={{ cursor: 'pointer', fontSize: '.72rem', whiteSpace: 'nowrap' }}
                    >
                      <input
                        type="checkbox"
                        checked={enabled}
                        onChange={(e) => handleToggleStage(idx, e.target.checked)}
                      />{' '}
                      On
                    </label>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleRemoveStage(idx);
                      }}
                      style={{
                        fontSize: '.68rem',
                        background: 'none',
                        border: '1px solid var(--border)',
                        color: 'var(--muted)',
                        borderRadius: '4px',
                        padding: '1px 5px',
                        cursor: 'pointer',
                      }}
                    >
                      {'✕'}
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {/* Right: MCP skills palette + Conditional config */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* MCP Skills palette */}
          <Card title="MCP Skills">
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {Object.values(allSkills).map((s) => {
                const col = skillColor(s.name);
                const mcp = s._mcp || {};
                const tools: string[] = mcp.tools || [];
                return (
                  <div
                    key={s.name}
                    className="card"
                    style={{
                      borderLeft: `3px solid ${col}`,
                      padding: '7px 9px',
                      cursor: 'pointer',
                    }}
                    onClick={() => openSkillModal(s.name)}
                  >
                    <div
                      style={{
                        fontWeight: 700,
                        color: col,
                        fontSize: '.78rem',
                        marginBottom: '2px',
                      }}
                    >
                      {s.name}
                    </div>
                    <div
                      style={{ fontSize: '.7rem', color: 'var(--muted)', marginBottom: '4px' }}
                    >
                      {s.description}
                    </div>
                    {tools.length > 0 ? (
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '2px' }}>
                        {tools.map((toolName) => (
                          <span
                            key={toolName}
                            style={{
                              fontSize: '.65rem',
                              padding: '1px 5px',
                              borderRadius: '5px',
                              background: `${col}22`,
                              color: col,
                            }}
                          >
                            {toolName}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <span style={{ fontSize: '.68rem', color: 'var(--muted)' }}>no tools</span>
                    )}
                  </div>
                );
              })}
            </div>
          </Card>

          {/* Conditional config */}
          <Card title="Conditional Configuration">
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div style={{ fontSize: '.78rem', color: 'var(--muted)' }}>
                Selected stage:{' '}
                <strong style={{ color: 'var(--text)' }}>{selectedStage || '(none)'}</strong>
              </div>
              <select
                value={condType}
                onChange={(e) => setCondType(e.target.value)}
                style={{
                  padding: '6px 10px',
                  borderRadius: '6px',
                  border: '1px solid var(--border)',
                  background: 'var(--card)',
                  color: 'var(--text)',
                  fontSize: '.82rem',
                }}
              >
                <option value="skip_if_exists">skip_if_exists</option>
              </select>
              <input
                type="text"
                value={condValue}
                onChange={(e) => setCondValue(e.target.value)}
                placeholder="Value..."
                style={{
                  padding: '6px 10px',
                  borderRadius: '6px',
                  border: '1px solid var(--border)',
                  background: 'var(--card)',
                  color: 'var(--text)',
                  fontSize: '.82rem',
                }}
              />
              <button className="btn btn-primary btn-sm" onClick={handleApplyCondition}>
                Apply
              </button>
            </div>
          </Card>
        </div>
      </div>

      {/* Skill Modal */}
      {skillModal && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: 'rgba(0,0,0,.6)',
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            zIndex: 1000,
          }}
          onClick={() => setSkillModal(null)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: 'var(--card)',
              border: '1px solid var(--border)',
              borderRadius: '12px',
              padding: '20px',
              width: '80%',
              maxWidth: '800px',
              maxHeight: '80vh',
              overflow: 'auto',
            }}
          >
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: '10px',
              }}
            >
              <h3 style={{ margin: 0 }}>{skillModal.name}</h3>
              <button
                onClick={() => setSkillModal(null)}
                style={{
                  background: 'none',
                  border: 'none',
                  color: 'var(--muted)',
                  fontSize: '1.2rem',
                  cursor: 'pointer',
                }}
              >
                {'✕'}
              </button>
            </div>
            <div style={{ fontSize: '.78rem', color: 'var(--muted)', marginBottom: '12px' }}>
              {skillModal.dir}
            </div>

            {/* File tabs */}
            <div style={{ display: 'flex', gap: '6px', marginBottom: '10px', flexWrap: 'wrap' }}>
              {Object.keys(skillModal.files).map((fname) => (
                <button
                  key={fname}
                  onClick={() => setSkillModal({ ...skillModal, activeFile: fname })}
                  style={{
                    background:
                      fname === skillModal.activeFile ? 'rgba(255,255,255,.07)' : 'none',
                    border: '1px solid var(--border)',
                    color: fname === skillModal.activeFile ? 'var(--text)' : 'var(--muted)',
                    padding: '4px 10px',
                    borderRadius: '6px',
                    cursor: 'pointer',
                    fontSize: '.75rem',
                  }}
                >
                  {fname}
                </button>
              ))}
            </div>

            {/* File content */}
            <pre
              style={{
                fontSize: '.78rem',
                whiteSpace: 'pre-wrap',
                background: 'var(--bg)',
                border: '1px solid var(--border)',
                borderRadius: '6px',
                padding: '12px',
                maxHeight: '50vh',
                overflow: 'auto',
              }}
            >
              {skillModal.files[skillModal.activeFile] || '(no files found)'}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}
