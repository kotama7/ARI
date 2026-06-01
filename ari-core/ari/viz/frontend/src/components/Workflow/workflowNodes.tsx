// ARI Dashboard – Workflow page node/modal layer.
// Extracted verbatim from WorkflowPage.tsx (refactor req 15, follow-up to 03):
// the React Flow custom-node components, the node-type map, and the
// condition/skill/node-edit/skill-detail modals + the skillColor helper and
// SkillMcpEntry type. WorkflowPage.tsx imports the exported symbols from here.

import React, { useState } from 'react';
import { Handle, Position, type NodeTypes, type Edge, type Node } from 'reactflow';

// ── Dynamic skill colour (deterministic hash) ───────

const SKILL_PALETTE = [
  '#3b82f6', '#f59e0b', '#8b5cf6', '#06b6d4', '#10b981',
  '#ef4444', '#f97316', '#64748b', '#a78bfa', '#ec4899',
  '#84cc16', '#f43f5e', '#d946ef', '#0ea5e9', '#14b8a6',
];

export function skillColor(name: string): string {
  let h = 0;
  for (let i = 0; i < name.length; i++) {
    h = ((h << 5) - h + name.charCodeAt(i)) | 0;
  }
  return SKILL_PALETTE[Math.abs(h) % SKILL_PALETTE.length];
}

// ── Custom node components ──────────────────────────

function PhaseNode({ data }: { data: any }) {
  const col = skillColor(data.skill || '');
  const enabled = data.enabled !== false;
  const availableTools: string[] = (data.availableTools || []).map(
    (t: any) => (typeof t === 'string' ? t : t.name),
  );
  const activeTool = data.tool || '';
  const disabledNames: string[] = data.disabledToolNames || [];
  const isOff = (t: string) => disabledNames.includes(t);
  return (
    <div
      style={{
        background: 'var(--card, #1e1e2e)',
        border: `2px solid ${col}`,
        borderRadius: 10,
        padding: '10px 14px',
        minWidth: 180,
        maxWidth: 260,
        opacity: enabled ? 1 : 0.45,
        position: 'relative',
      }}
    >
      <Handle type="target" position={Position.Left} style={{ background: col }} />
      <div style={{ fontWeight: 700, fontSize: '.85rem', color: col }}>{data.label}</div>
      <div style={{ fontSize: '.72rem', color: 'var(--muted, #888)', marginTop: 2 }}>
        {data.skill}
      </div>
      {/* MCP tool badges */}
      {availableTools.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3, marginTop: 4 }}>
          {availableTools.map((t) => {
            const active = t === activeTool;
            const off = isOff(t);
            return (
              <span
                key={t}
                style={{
                  fontSize: '.58rem',
                  padding: '1px 4px',
                  borderRadius: 4,
                  border: `1px solid ${off ? 'var(--border, #333)' : active ? col : 'var(--border, #444)'}`,
                  background: off ? 'transparent' : active ? col + '22' : 'transparent',
                  color: off ? 'var(--muted, #555)' : active ? col : 'var(--muted, #666)',
                  fontWeight: !off && active ? 700 : 400,
                  textDecoration: off ? 'line-through' : 'none',
                  opacity: off ? 0.5 : 1,
                }}
                title={
                  off
                    ? `${t}: disabled in MCP Skill Inventory — stage cannot call this tool`
                    : active
                      ? `${t}: this stage's tool`
                      : t
                }
              >
                {t}
              </span>
            );
          })}
        </div>
      )}
      {!availableTools.length && activeTool && (
        <div style={{ fontSize: '.68rem', color: 'var(--muted, #666)', marginTop: 1 }}>
          {activeTool}
        </div>
      )}
      {data.phase && (
        <span
          style={{
            position: 'absolute',
            top: 4,
            right: 6,
            fontSize: '.6rem',
            padding: '1px 5px',
            borderRadius: 5,
            background: data.phase === 'bfts' ? '#10b98122' : '#8b5cf622',
            color: data.phase === 'bfts' ? '#10b981' : '#8b5cf6',
          }}
        >
          {data.phase}
        </span>
      )}
      {data.onToggle && (
        <label
          style={{
            position: 'absolute',
            bottom: 4,
            right: 6,
            fontSize: '.65rem',
            cursor: 'pointer',
          }}
        >
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => data.onToggle(e.target.checked)}
          />{' '}
          On
        </label>
      )}
      {data.onDelete && (
        <button
          onClick={data.onDelete}
          style={{
            position: 'absolute',
            top: 4,
            right: data.phase ? 48 : 6,
            background: 'none',
            border: 'none',
            color: 'var(--muted, #888)',
            cursor: 'pointer',
            fontSize: '.75rem',
            padding: 0,
          }}
        >
          {'\u2715'}
        </button>
      )}
      <Handle type="source" position={Position.Right} style={{ background: col }} />
      {/* Bottom handles for loop-back edges */}
      <Handle type="source" id="loop-out" position={Position.Bottom} style={{ background: '#f59e0b', left: '70%' }} />
      <Handle type="target" id="loop-in" position={Position.Bottom} style={{ background: '#f59e0b', left: '30%' }} />
    </div>
  );
}

function ConditionNode({ data }: { data: any }) {
  return (
    <div
      style={{
        background: 'var(--card, #1e1e2e)',
        border: '2px solid #f59e0b',
        borderRadius: 0,
        width: 60,
        height: 60,
        transform: 'rotate(45deg)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <Handle type="target" position={Position.Left} style={{ background: '#f59e0b', transform: 'rotate(-45deg)' }} />
      <span style={{ transform: 'rotate(-45deg)', fontSize: '.7rem', fontWeight: 700, color: '#f59e0b' }}>
        {data.label || '?'}
      </span>
      <Handle type="source" position={Position.Right} style={{ background: '#f59e0b', transform: 'rotate(-45deg)' }} />
    </div>
  );
}

function ParallelNode({ data }: { data: any }) {
  return (
    <div
      style={{
        background: 'var(--card, #1e1e2e)',
        border: '2px solid #06b6d4',
        borderRadius: 4,
        padding: '6px 20px',
        minWidth: 200,
        height: 24,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <Handle type="target" position={Position.Left} style={{ background: '#06b6d4' }} />
      <span style={{ fontSize: '.7rem', fontWeight: 700, color: '#06b6d4' }}>
        {data.label || 'Parallel'}
      </span>
      <Handle type="source" position={Position.Right} style={{ background: '#06b6d4' }} />
    </div>
  );
}

export const nodeTypes: NodeTypes = {
  phase: PhaseNode,
  condition: ConditionNode,
  parallel: ParallelNode,
};

// ── Condition builder modal ─────────────────────────

export function ConditionModal({
  edge,
  onSave,
  onClose,
}: {
  edge: Edge;
  onSave: (edgeId: string, condition: string, threshold?: number) => void;
  onClose: () => void;
}) {
  const existing = edge.data?.condition || 'always';
  const existingThreshold = edge.data?.threshold || 0.5;
  const [condType, setCondType] = useState(existing);
  const [threshold, setThreshold] = useState(existingThreshold);

  return (
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
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: 'var(--card, #1e1e2e)',
          border: '1px solid var(--border, #333)',
          borderRadius: 12,
          padding: 20,
          width: 340,
        }}
      >
        <h3 style={{ margin: '0 0 12px' }}>Edge Condition</h3>
        <div style={{ marginBottom: 10 }}>
          <label style={{ fontSize: '.82rem', display: 'block', marginBottom: 4 }}>Type</label>
          <select
            value={condType}
            onChange={(e) => setCondType(e.target.value)}
            style={{
              width: '100%',
              padding: '6px 10px',
              borderRadius: 6,
              border: '1px solid var(--border, #333)',
              background: 'var(--bg, #111)',
              color: 'var(--text, #eee)',
            }}
          >
            <option value="always">Always</option>
            <option value="score_above">Score Above</option>
            <option value="on_success">On Success</option>
            <option value="on_failure">On Failure</option>
            <option value="skip_if_exists">Skip If Exists</option>
          </select>
        </div>
        {condType === 'score_above' && (
          <div style={{ marginBottom: 10 }}>
            <label style={{ fontSize: '.82rem', display: 'block', marginBottom: 4 }}>Threshold</label>
            <input
              type="number"
              step="0.1"
              min="0"
              max="1"
              value={threshold}
              onChange={(e) => setThreshold(parseFloat(e.target.value) || 0.5)}
              style={{
                width: '100%',
                padding: '6px 10px',
                borderRadius: 6,
                border: '1px solid var(--border, #333)',
                background: 'var(--bg, #111)',
                color: 'var(--text, #eee)',
              }}
            />
          </div>
        )}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button
            className="btn btn-outline btn-sm"
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            className="btn btn-primary btn-sm"
            onClick={() => {
              onSave(edge.id, condType, condType === 'score_above' ? threshold : undefined);
              onClose();
            }}
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Skill selector drawer ───────────────────────────

export interface SkillMcpEntry {
  name: string;
  description: string;
  tools: string[];
  version: string;
  dir: string;
  // workflow.yaml can now declare skill phases as either a single string
  // ("bfts" | "paper" | "reproduce" | "all" | "none") or a list of phases
  // (e.g. ["paper", "reproduce"]) — normalize on read/write.
  phase?: string | string[];
  usage?: string;
}

const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '6px 10px',
  borderRadius: 6,
  border: '1px solid var(--border, #333)',
  background: 'var(--bg, #111)',
  color: 'var(--text, #eee)',
};

export function SkillDrawer({
  onAdd,
  onClose,
  skillMcp,
}: {
  onAdd: (name: string, skill: string, tool: string, phase: string) => void;
  onClose: () => void;
  skillMcp: Record<string, SkillMcpEntry>;
}) {
  const [name, setName] = useState('');
  const [skill, setSkill] = useState('');
  const [tool, setTool] = useState('');
  const [phase, setPhase] = useState('paper');

  const skillNames = Object.keys(skillMcp).sort();
  const toolsForSkill = skill && skillMcp[skill] ? skillMcp[skill].tools : [];

  return (
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
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: 'var(--card, #1e1e2e)',
          border: '1px solid var(--border, #333)',
          borderRadius: 12,
          padding: 20,
          width: 380,
        }}
      >
        <h3 style={{ margin: '0 0 12px' }}>Add Phase Node</h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div>
            <label style={{ fontSize: '.82rem', display: 'block', marginBottom: 4 }}>Stage name (snake_case)</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="my_stage"
              style={inputStyle}
            />
          </div>
          <div>
            <label style={{ fontSize: '.82rem', display: 'block', marginBottom: 4 }}>Phase</label>
            <select
              value={phase}
              onChange={(e) => setPhase(e.target.value)}
              style={inputStyle}
            >
              <option value="bfts">bfts (experiment)</option>
              <option value="paper">paper</option>
            </select>
          </div>
          <div>
            <label style={{ fontSize: '.82rem', display: 'block', marginBottom: 4 }}>Skill (MCP server)</label>
            <select
              value={skill}
              onChange={(e) => {
                setSkill(e.target.value);
                setTool('');
              }}
              style={inputStyle}
            >
              <option value="">-- select skill --</option>
              {skillNames.map((s) => (
                <option key={s} value={s}>
                  {s}{skillMcp[s]?.description ? ` — ${skillMcp[s].description}` : ''}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label style={{ fontSize: '.82rem', display: 'block', marginBottom: 4 }}>MCP Tool</label>
            {toolsForSkill.length > 0 ? (
              <select
                value={tool}
                onChange={(e) => setTool(e.target.value)}
                style={inputStyle}
              >
                <option value="">(none — use all tools)</option>
                {toolsForSkill.map((t) => (
                  <option key={typeof t === 'string' ? t : (t as any).name} value={typeof t === 'string' ? t : (t as any).name}>
                    {typeof t === 'string' ? t : (t as any).name}
                  </option>
                ))}
              </select>
            ) : (
              <input
                type="text"
                value={tool}
                onChange={(e) => setTool(e.target.value)}
                placeholder={skill ? '(no tools found — type manually)' : '(select a skill first)'}
                style={inputStyle}
              />
            )}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 14 }}>
          <button className="btn btn-outline btn-sm" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-primary btn-sm"
            disabled={!name}
            onClick={() => {
              if (name) {
                onAdd(name, skill, tool, phase);
                onClose();
              }
            }}
          >
            Add
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Node edit modal (skill/tool per phase) ─────

export function NodeEditModal({
  node,
  skillMcp,
  onSave,
  onClose,
}: {
  node: Node;
  skillMcp: Record<string, SkillMcpEntry>;
  onSave: (nodeId: string, updates: { skill: string; tool: string; phase: string; description: string }) => void;
  onClose: () => void;
}) {
  const [skill, setSkill] = useState(node.data?.skill || '');
  const [tool, setTool] = useState(node.data?.tool || '');
  const [phase, setPhase] = useState(node.data?.phase || 'paper');
  const [description, setDescription] = useState(node.data?.description || '');

  const skillNames = Object.keys(skillMcp).sort();
  const toolsForSkill = skill && skillMcp[skill] ? skillMcp[skill].tools : [];

  // React-driver stages use pre_tool/post_tool plus a `react:` block instead of
  // a single tool. The modal cannot safely round-trip the full block (system
  // prompts, sandbox path, max_steps, …), so we show a read-only summary and
  // only allow editing `skill` / `description` / `phase` here.
  const preTool: string = (node.data as any)?.pre_tool || '';
  const postTool: string = (node.data as any)?.post_tool || '';
  const reactBlock = (node.data as any)?.react;
  const isReactStage = Boolean(preTool || postTool || reactBlock);

  return (
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
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: 'var(--card, #1e1e2e)',
          border: '1px solid var(--border, #333)',
          borderRadius: 12,
          padding: 20,
          width: 420,
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <h3 style={{ margin: 0 }}>Edit: {node.id}</h3>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', color: 'var(--muted)', fontSize: '1.2rem', cursor: 'pointer' }}
          >
            {'\u2715'}
          </button>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div>
            <label style={{ fontSize: '.82rem', display: 'block', marginBottom: 4 }}>Phase</label>
            <select
              value={phase}
              onChange={(e) => setPhase(e.target.value)}
              style={inputStyle}
            >
              <option value="bfts">bfts (experiment)</option>
              <option value="paper">paper</option>
            </select>
          </div>
          <div>
            <label style={{ fontSize: '.82rem', display: 'block', marginBottom: 4 }}>Skill (MCP server)</label>
            <select
              value={skill}
              onChange={(e) => {
                setSkill(e.target.value);
                setTool('');
              }}
              style={inputStyle}
            >
              <option value="">-- select skill --</option>
              {skillNames.map((s) => (
                <option key={s} value={s}>
                  {s}{skillMcp[s]?.description ? ` — ${skillMcp[s].description}` : ''}
                </option>
              ))}
            </select>
            {skill && skillMcp[skill] && (
              <div style={{ fontSize: '.7rem', color: 'var(--muted)', marginTop: 4 }}>
                {skillMcp[skill].description}
                {skillMcp[skill].tools.length > 0 && (
                  <span> — {skillMcp[skill].tools.length} tool(s) available</span>
                )}
              </div>
            )}
          </div>
          {isReactStage ? (
            <div
              style={{
                background: 'rgba(245, 158, 11, 0.08)',
                border: '1px solid rgba(245, 158, 11, 0.4)',
                borderRadius: 6,
                padding: 10,
                fontSize: '.72rem',
                lineHeight: 1.4,
              }}
            >
              <div style={{ color: '#f59e0b', fontWeight: 600, marginBottom: 4 }}>
                ReAct-driver stage (tool fields read-only)
              </div>
              <div style={{ color: 'var(--muted)' }}>
                This stage runs under <code>ari.agent.react_driver</code>: it
                calls <code>pre_tool</code>, drives a ReAct loop over the MCP
                skills opted into <code>agent_phase</code>, then calls{' '}
                <code>post_tool</code>. The full <code>react:</code> block
                (prompts, sandbox, max_steps, final_tool) must be edited in{' '}
                <code>config/workflow.yaml</code> directly.
              </div>
              <ul style={{ margin: '8px 0 0', paddingLeft: 16, color: 'var(--text, #ddd)' }}>
                {preTool && (
                  <li>
                    pre_tool: <code>{preTool}</code>
                  </li>
                )}
                {postTool && (
                  <li>
                    post_tool: <code>{postTool}</code>
                  </li>
                )}
                {reactBlock && (reactBlock as any).agent_phase && (
                  <li>
                    agent_phase: <code>{(reactBlock as any).agent_phase}</code>
                  </li>
                )}
                {reactBlock && (reactBlock as any).final_tool && (
                  <li>
                    final_tool: <code>{(reactBlock as any).final_tool}</code>
                  </li>
                )}
                {reactBlock && (reactBlock as any).max_steps && (
                  <li>
                    max_steps: <code>{(reactBlock as any).max_steps}</code>
                  </li>
                )}
                {reactBlock && (reactBlock as any).sandbox && (
                  <li>
                    sandbox: <code>{(reactBlock as any).sandbox}</code>
                  </li>
                )}
              </ul>
            </div>
          ) : (
            <div>
              <label style={{ fontSize: '.82rem', display: 'block', marginBottom: 4 }}>MCP Tool</label>
              {toolsForSkill.length > 0 ? (
                <select
                  value={tool}
                  onChange={(e) => setTool(e.target.value)}
                  style={inputStyle}
                >
                  <option value="">(none — use all tools)</option>
                  {toolsForSkill.map((t) => (
                    <option key={typeof t === 'string' ? t : (t as any).name} value={typeof t === 'string' ? t : (t as any).name}>
                      {typeof t === 'string' ? t : (t as any).name}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  type="text"
                  value={tool}
                  onChange={(e) => setTool(e.target.value)}
                  placeholder={skill ? '(no tools found — type manually)' : '(select a skill first)'}
                  style={inputStyle}
                />
              )}
            </div>
          )}
          <div>
            <label style={{ fontSize: '.82rem', display: 'block', marginBottom: 4 }}>Description</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              style={{ ...inputStyle, resize: 'vertical' }}
            />
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 14 }}>
          <button className="btn btn-outline btn-sm" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-primary btn-sm"
            onClick={() => {
              onSave(node.id, { skill, tool, phase, description });
              onClose();
            }}
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Skill detail modal ──────────────────────────────

export function SkillModal({
  skillModal,
  onClose,
}: {
  skillModal: { name: string; dir: string; files: Record<string, string>; activeFile: string };
  onClose: () => void;
}) {
  const [activeFile, setActiveFile] = useState(skillModal.activeFile);
  return (
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
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: 'var(--card, #1e1e2e)',
          border: '1px solid var(--border, #333)',
          borderRadius: 12,
          padding: 20,
          width: '80%',
          maxWidth: 800,
          maxHeight: '80vh',
          overflow: 'auto',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
          <h3 style={{ margin: 0 }}>{skillModal.name}</h3>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', color: 'var(--muted)', fontSize: '1.2rem', cursor: 'pointer' }}
          >
            {'\u2715'}
          </button>
        </div>
        <div style={{ fontSize: '.78rem', color: 'var(--muted)', marginBottom: 12 }}>{skillModal.dir}</div>
        <div style={{ display: 'flex', gap: 6, marginBottom: 10, flexWrap: 'wrap' }}>
          {Object.keys(skillModal.files).map((fname) => (
            <button
              key={fname}
              onClick={() => setActiveFile(fname)}
              style={{
                background: fname === activeFile ? 'rgba(255,255,255,.07)' : 'none',
                border: '1px solid var(--border)',
                color: fname === activeFile ? 'var(--text)' : 'var(--muted)',
                padding: '4px 10px',
                borderRadius: 6,
                cursor: 'pointer',
                fontSize: '.75rem',
              }}
            >
              {fname}
            </button>
          ))}
        </div>
        <pre
          style={{
            fontSize: '.78rem',
            whiteSpace: 'pre-wrap',
            background: 'var(--bg)',
            border: '1px solid var(--border)',
            borderRadius: 6,
            padding: 12,
            maxHeight: '50vh',
            overflow: 'auto',
          }}
        >
          {skillModal.files[activeFile] || '(no files found)'}
        </pre>
      </div>
    </div>
  );
}
