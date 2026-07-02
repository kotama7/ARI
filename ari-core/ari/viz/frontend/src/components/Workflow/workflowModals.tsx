// ARI Dashboard – Workflow editor modals.
// Extracted verbatim from workflowNodes.tsx (subtask-064 god-component split):
// the condition / skill-add / node-edit / skill-detail modals, the shared
// inputStyle, and the SkillMcpEntry type. Bodies are unchanged; workflowNodes.tsx
// re-exports these from here, so WorkflowPage keeps importing them from
// './workflowNodes' with no edit.

import React, { useState } from 'react';
import { type Edge, type Node } from 'reactflow';

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
            {'✕'}
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
            {'✕'}
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
