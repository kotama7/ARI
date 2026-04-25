import { useCallback, useEffect, useRef, useState } from 'react';
import ReactFlow, {
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  Background,
  Controls,
  MiniMap,
  MarkerType,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
  type NodeTypes,
  Handle,
  Position,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { useI18n } from '../../i18n';
import {
  fetchWorkflowFlow,
  saveWorkflowFlow,
  fetchWorkflowDefault,
  fetchSkillDetail,
  fetchWorkflow,
  saveSkillPhases,
  saveDisabledTools,
} from '../../services/api';

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

const nodeTypes: NodeTypes = {
  phase: PhaseNode,
  condition: ConditionNode,
  parallel: ParallelNode,
};

// ── Condition builder modal ─────────────────────────

function ConditionModal({
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

interface SkillMcpEntry {
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

function SkillDrawer({
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

function NodeEditModal({
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

function SkillModal({
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

// ── Main component ──────────────────────────────────

export default function WorkflowPage() {
  const { t } = useI18n();
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saveMsg, setSaveMsg] = useState('');
  const [wfPath, setWfPath] = useState('');

  // MCP skill metadata (loaded once)
  const [skillMcp, setSkillMcp] = useState<Record<string, SkillMcpEntry>>({});
  // Disabled tools (individual tool-level on/off)
  const [disabledTools, setDisabledTools] = useState<Set<string>>(new Set());

  // Modals
  const [condEdge, setCondEdge] = useState<Edge | null>(null);
  const [showAddNode, setShowAddNode] = useState(false);
  const [editNode, setEditNode] = useState<Node | null>(null);
  const [skillModalData, setSkillModalData] = useState<{
    name: string;
    dir: string;
    files: Record<string, string>;
    activeFile: string;
  } | null>(null);

  // Expanded node in detail list
  const [expandedNode, setExpandedNode] = useState<string | null>(null);

  // Context menu
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; edgeId: string } | null>(null);

  // Auto-save debounce
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Load ──────────────────────────────────

  const load = useCallback(() => {
    // Load both workflow flow and skill MCP metadata in parallel
    Promise.all([fetchWorkflowFlow(), fetchWorkflow()])
      .then(([flowRes, wfRes]: [any, any]) => {
        // Extract skill MCP metadata
        const mcp: Record<string, SkillMcpEntry> = (wfRes.ok && wfRes.skill_mcp) ? wfRes.skill_mcp : {};
        setSkillMcp(mcp);
        // Load disabled tools list
        if (wfRes.ok && wfRes.disabled_tools) {
          setDisabledTools(new Set(wfRes.disabled_tools));
        }

        if (!flowRes.ok) {
          setError(flowRes.error || 'Failed to load workflow');
          return;
        }
        const flow = flowRes.flow || { nodes: [], edges: [] };
        const initialDisabled: string[] = wfRes.ok && wfRes.disabled_tools ? wfRes.disabled_tools : [];
        // Attach callbacks and available MCP tools to node data
        const augNodes = (flow.nodes || []).map((n: Node) => {
          const skillEntry = mcp[n.data?.skill || ''];
          return {
            ...n,
            data: {
              ...n.data,
              availableTools: skillEntry?.tools || [],
              disabledToolNames: initialDisabled,
              onToggle: (enabled: boolean) => {
                setNodes((nds) =>
                  nds.map((nd) =>
                    nd.id === n.id ? { ...nd, data: { ...nd.data, enabled } } : nd,
                  ),
                );
              },
              onDelete: () => {
                if (confirm(`Remove "${n.id}"?`)) {
                  setNodes((nds) => nds.filter((nd) => nd.id !== n.id));
                  setEdges((eds) => eds.filter((e) => e.source !== n.id && e.target !== n.id));
                }
              },
            },
          };
        });
        // Style edges
        const styledEdges = (flow.edges || []).map((e: Edge) => {
          const isLoop = e.data?.condition === 'loop';
          const isBridge = e.data?.auto_bridge;
          return {
            ...e,
            type: isLoop ? 'smoothstep' : 'default',
            markerEnd: { type: MarkerType.ArrowClosed },
            animated: e.animated || false,
            label: isBridge
              ? 'bridge'
              : e.data?.condition && e.data.condition !== 'always'
                ? e.data.condition
                : undefined,
            style: {
              stroke: isLoop ? '#f59e0b' : isBridge ? '#6366f1' : undefined,
              strokeWidth: isLoop ? 2 : undefined,
              strokeDasharray: isBridge ? '6 3' : isLoop ? '8 4' : undefined,
            },
            zIndex: isLoop ? 10 : undefined,
          };
        });
        setNodes(augNodes);
        setEdges(styledEdges);
        setWfPath(flowRes.path || '');
        setError(null);
      })
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Keep PhaseNode badges in sync when the user toggles disabledTools
  // from the MCP Skill Inventory section.
  useEffect(() => {
    const names = [...disabledTools];
    setNodes((nds) =>
      nds.map((n) => ({
        ...n,
        data: { ...n.data, disabledToolNames: names },
      })),
    );
  }, [disabledTools]);

  // ── Auto-save (debounced 2s) ──────────────

  const triggerAutoSave = useCallback(() => {
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      // Read latest from state
      setNodes((currentNodes) => {
        setEdges((currentEdges) => {
          const flow = {
            nodes: currentNodes.map((n) => ({
              id: n.id,
              type: n.type,
              position: n.position,
              data: {
                label: n.data.label,
                skill: n.data.skill,
                enabled: n.data.enabled,
                tool: n.data.tool,
                phase: n.data.phase,
                description: n.data.description,
              },
            })),
            edges: currentEdges.map((e) => ({
              id: e.id,
              source: e.source,
              target: e.target,
              data: e.data,
              animated: e.animated,
            })),
          };
          saveWorkflowFlow({ flow }).catch(() => {});
          return currentEdges;
        });
        return currentNodes;
      });
    }, 2000);
  }, []);

  // ── Handlers ──────────────────────────────

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      setNodes((nds) => applyNodeChanges(changes, nds));
      triggerAutoSave();
    },
    [triggerAutoSave],
  );

  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      setEdges((eds) => applyEdgeChanges(changes, eds));
      triggerAutoSave();
    },
    [triggerAutoSave],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      setEdges((eds) =>
        addEdge(
          {
            ...connection,
            markerEnd: { type: MarkerType.ArrowClosed },
            data: { condition: 'always' },
          },
          eds,
        ),
      );
      triggerAutoSave();
    },
    [triggerAutoSave],
  );

  const onEdgeContextMenu = useCallback(
    (event: React.MouseEvent, edge: Edge) => {
      event.preventDefault();
      setCtxMenu({ x: event.clientX, y: event.clientY, edgeId: edge.id });
    },
    [],
  );

  const handleSave = useCallback(() => {
    setSaveMsg(t('saving'));
    const flow = {
      nodes: nodes.map((n) => ({
        id: n.id,
        type: n.type,
        position: n.position,
        data: {
          label: n.data.label,
          skill: n.data.skill,
          enabled: n.data.enabled,
          tool: n.data.tool,
          phase: n.data.phase,
          description: n.data.description,
        },
      })),
      edges: edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        data: e.data,
        animated: e.animated,
      })),
    };
    saveWorkflowFlow({ flow })
      .then((r) => {
        setSaveMsg(r.ok ? t('save_done') : '\u274c ' + r.error);
        setTimeout(() => setSaveMsg(''), 3000);
      })
      .catch((e) => {
        setSaveMsg('\u274c ' + String(e));
        setTimeout(() => setSaveMsg(''), 3000);
      });
  }, [nodes, edges, t]);

  const handleReset = useCallback(() => {
    fetchWorkflowDefault()
      .then((d) => {
        if (d.ok && d.flow) {
          setNodes(d.flow.nodes || []);
          setEdges(
            (d.flow.edges || []).map((e: Edge) => ({
              ...e,
              markerEnd: { type: MarkerType.ArrowClosed },
            })),
          );
          setSaveMsg('Reset to default');
          setTimeout(() => setSaveMsg(''), 2500);
        }
      })
      .catch(() => {});
  }, []);

  const handleAddNode = useCallback(
    (name: string, skill: string, tool: string, phase: string) => {
      const maxX = nodes.reduce((mx, n) => Math.max(mx, n.position.x), 0);
      const newNode: Node = {
        id: name,
        type: 'phase',
        position: { x: maxX + 240, y: 50 },
        data: {
          label: name.replace(/_/g, ' ').replace(/\b\w/g, (c: string) => c.toUpperCase()),
          skill,
          enabled: true,
          tool,
          phase,
          description: '',
          inputs: {},
          outputs: {},
          load_inputs: [],
          skip_if_exists: null,
          loop_back_to: null,
          availableTools: skillMcp[skill]?.tools || [],
          onToggle: (enabled: boolean) => {
            setNodes((nds) =>
              nds.map((nd) =>
                nd.id === name ? { ...nd, data: { ...nd.data, enabled } } : nd,
              ),
            );
          },
          onDelete: () => {
            if (confirm(`Remove "${name}"?`)) {
              setNodes((nds) => nds.filter((nd) => nd.id !== name));
              setEdges((eds) => eds.filter((e) => e.source !== name && e.target !== name));
            }
          },
        },
      };
      setNodes((nds) => [...nds, newNode]);
      triggerAutoSave();
    },
    [nodes, triggerAutoSave, skillMcp],
  );

  const handleNodeEdit = useCallback(
    (nodeId: string, updates: { skill: string; tool: string; phase: string; description: string }) => {
      setNodes((nds) =>
        nds.map((n) =>
          n.id === nodeId
            ? {
                ...n,
                data: {
                  ...n.data,
                  ...updates,
                  availableTools: skillMcp[updates.skill]?.tools || [],
                },
              }
            : n,
        ),
      );
      triggerAutoSave();
    },
    [triggerAutoSave, skillMcp],
  );

  const handleCondSave = useCallback(
    (edgeId: string, condition: string, threshold?: number) => {
      setEdges((eds) =>
        eds.map((e) =>
          e.id === edgeId
            ? {
                ...e,
                data: { ...e.data, condition, threshold },
                label: condition !== 'always' ? condition + (threshold != null ? ` (${threshold})` : '') : undefined,
              }
            : e,
        ),
      );
      triggerAutoSave();
    },
    [triggerAutoSave],
  );

  function openSkillModal(skillName: string) {
    fetchSkillDetail(skillName)
      .then((d: any) => {
        if (!d.ok) return;
        const files = d.files as Record<string, string>;
        const firstFile = Object.keys(files)[0] || '';
        setSkillModalData({ name: skillName, dir: d.dir, files, activeFile: firstFile });
      })
      .catch(() => {});
  }

  // ── Render ────────────────────────────────

  if (error) {
    return (
      <div>
        <h2>Workflow Editor</h2>
        <p style={{ color: 'var(--danger)' }}>{error}</p>
      </div>
    );
  }

  return (
    <div>
      {/* Title + actions */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          marginBottom: 14,
          flexWrap: 'wrap',
        }}
      >
        <h2 style={{ margin: 0 }}>Workflow Editor</h2>
        <button className="btn btn-primary btn-sm" onClick={handleSave}>
          Save
        </button>
        <button className="btn btn-outline btn-sm" onClick={load}>
          Reload
        </button>
        <button className="btn btn-outline btn-sm" onClick={() => setShowAddNode(true)}>
          + Add Node
        </button>
        <button className="btn btn-outline btn-sm" onClick={handleReset}>
          Reset to default
        </button>
        <span style={{ fontSize: '.78rem', color: 'var(--muted)' }}>{saveMsg}</span>
        {wfPath && <span style={{ fontSize: '.68rem', color: 'var(--muted)' }}>{wfPath}</span>}
      </div>

      {/* React Flow canvas */}
      <div
        style={{
          width: '100%',
          height: 420,
          background: 'var(--bg, #111)',
          border: '1px solid var(--border, #333)',
          borderRadius: 10,
        }}
      >
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onEdgeContextMenu={onEdgeContextMenu}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.15 }}
          onClick={() => setCtxMenu(null)}
        >
          <Background color="rgba(255,255,255,.05)" gap={20} />
          <Controls />
          <MiniMap
            nodeStrokeColor="#333"
            nodeColor={(n) => {
              const col = skillColor(n.data?.skill || '');
              return col;
            }}
            maskColor="rgba(0,0,0,.5)"
          />
        </ReactFlow>
      </div>

      {/* Agent Runtime Tools — skills available during BFTS agent execution but not assigned to a stage */}
      {(() => {
        // Collect skills used as stages in bfts_pipeline
        const bftsStageSkills = new Set(
          nodes
            .filter((n) => n.data?.phase === 'bfts')
            .map((n) => n.data?.skill as string)
            .filter(Boolean),
        );
        // Find skills with usage="active" that are NOT assigned to a bfts stage
        const agentSkills = Object.entries(skillMcp).filter(([name, entry]) => {
          const usage = (entry as any).usage || 'registered';
          if (usage === 'active') return true;
          // Also include skills that have no phase restriction and no stage assignment
          if (!bftsStageSkills.has(name) && !(entry as any).phase) return false;
          return false;
        });
        if (agentSkills.length === 0) return null;
        return (
          <div
            style={{
              marginTop: 16,
              padding: '10px 14px',
              background: 'var(--card, #1e1e2e)',
              border: '1px solid var(--border, #333)',
              borderRadius: 10,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <span style={{
                fontSize: '.72rem', fontWeight: 700, color: '#f59e0b',
              }}>Agent Runtime Tools</span>
              <span style={{
                fontSize: '.6rem', padding: '1px 6px', borderRadius: 5,
                background: '#f59e0b22', color: '#f59e0b',
              }}>available during BFTS execution</span>
            </div>
            <div style={{ fontSize: '.68rem', color: 'var(--muted)', marginBottom: 8 }}>
              These skills are not assigned to a specific pipeline stage but are available to the ReAct agent during experiment execution.
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {agentSkills.map(([name, entry]) => {
                const col = skillColor(name);
                const tools: string[] = (entry.tools || []).map(
                  (t: any) => (typeof t === 'string' ? t : t.name),
                );
                return (
                  <div
                    key={name}
                    style={{
                      borderLeft: `3px solid ${col}`,
                      padding: '6px 10px',
                      minWidth: 180,
                      maxWidth: 280,
                      background: 'var(--bg, #111)',
                      borderRadius: 6,
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <strong style={{ color: col, fontSize: '.75rem' }}>{name}</strong>
                      <span style={{
                        fontSize: '.55rem', padding: '1px 4px', borderRadius: 4,
                        background: '#3b82f622', color: '#3b82f6',
                      }}>active</span>
                    </div>
                    {entry.description && (
                      <div style={{ fontSize: '.65rem', color: 'var(--muted)', marginTop: 2 }}>
                        {entry.description}
                      </div>
                    )}
                    {tools.length > 0 && (
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3, marginTop: 4 }}>
                        {tools.map((t) => {
                          const off = disabledTools.has(t);
                          return (
                            <span
                              key={t}
                              style={{
                                fontSize: '.56rem', padding: '1px 4px', borderRadius: 4,
                                border: '1px solid var(--border, #444)',
                                color: off ? 'var(--muted, #555)' : 'var(--muted, #888)',
                                textDecoration: off ? 'line-through' : 'none',
                                opacity: off ? 0.5 : 1,
                              }}
                              title={off ? `${t}: disabled in MCP Skill Inventory` : t}
                            >{t}</span>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        );
      })()}

      {/* Node detail list with MCP tool selection */}
      <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {nodes.map((n) => {
          const col = skillColor(n.data?.skill || '');
          const availTools: string[] = (n.data?.availableTools || []).map(
            (t: any) => (typeof t === 'string' ? t : t.name),
          );
          const activeTool = n.data?.tool || '';
          const mcpEntry = skillMcp[n.data?.skill || ''];
          const expanded = expandedNode === n.id;
          return (
            <div
              key={n.id}
              className="card"
              style={{
                borderLeft: `3px solid ${col}`,
                padding: '8px 10px',
              }}
            >
              {/* Header row */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div
                  style={{ display: 'flex', gap: 8, alignItems: 'center', flex: 1, cursor: 'pointer' }}
                  onClick={() => setExpandedNode(expanded ? null : n.id)}
                >
                  <span style={{ fontSize: '.7rem', color: 'var(--muted)', transform: expanded ? 'rotate(90deg)' : 'none', transition: 'transform .15s' }}>
                    {'\u25B6'}
                  </span>
                  <strong style={{ color: col, fontSize: '.82rem' }}>{n.id}</strong>
                  {n.data?.phase && (
                    <span
                      style={{
                        fontSize: '.65rem',
                        padding: '1px 5px',
                        borderRadius: 5,
                        background: n.data.phase === 'bfts' ? '#10b98122' : '#8b5cf622',
                        color: n.data.phase === 'bfts' ? '#10b981' : '#8b5cf6',
                      }}
                    >
                      {n.data.phase}
                    </span>
                  )}
                  <span style={{ fontSize: '.7rem', color: 'var(--muted)' }}>{n.data?.skill}</span>
                  {activeTool && (
                    <span style={{ fontSize: '.68rem', color: col, fontWeight: 600 }}>{activeTool}</span>
                  )}
                  {availTools.length > 0 && (
                    <span style={{ fontSize: '.62rem', color: 'var(--muted)', marginLeft: 2 }}>
                      ({availTools.length} tools)
                    </span>
                  )}
                </div>
                <div style={{ display: 'flex', gap: 4 }}>
                  <button
                    className="btn btn-outline btn-sm"
                    style={{ fontSize: '.7rem', padding: '2px 8px' }}
                    onClick={() => n.data?.skill && openSkillModal(n.data.skill)}
                  >
                    Source
                  </button>
                  <button
                    className="btn btn-outline btn-sm"
                    style={{ fontSize: '.7rem', padding: '2px 8px' }}
                    onClick={() => setEditNode(n)}
                  >
                    Edit
                  </button>
                </div>
              </div>
              {/* Expanded: MCP tool details */}
              {expanded && (
                <div style={{ marginTop: 8, paddingLeft: 20 }}>
                  {mcpEntry && (
                    <div style={{ fontSize: '.72rem', color: 'var(--muted)', marginBottom: 6 }}>
                      {mcpEntry.description}
                      {mcpEntry.dir && <span style={{ marginLeft: 6, opacity: .6 }}>({mcpEntry.dir})</span>}
                    </div>
                  )}
                  {availTools.length > 0 ? (
                    <>
                      <div style={{ fontSize: '.72rem', color: 'var(--muted)', marginBottom: 4 }}>
                        MCP Tools — click to set active:
                      </div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                        {availTools.map((t) => {
                          const isActive = t === activeTool;
                          return (
                            <button
                              key={t}
                              onClick={() => {
                                const newTool = isActive ? '' : t;
                                setNodes((nds) =>
                                  nds.map((nd) =>
                                    nd.id === n.id ? { ...nd, data: { ...nd.data, tool: newTool } } : nd,
                                  ),
                                );
                                triggerAutoSave();
                              }}
                              style={{
                                fontSize: '.7rem',
                                padding: '3px 8px',
                                borderRadius: 5,
                                border: `1px solid ${isActive ? col : 'var(--border, #444)'}`,
                                background: isActive ? col + '22' : 'transparent',
                                color: isActive ? col : 'var(--text, #ccc)',
                                fontWeight: isActive ? 700 : 400,
                                cursor: 'pointer',
                              }}
                            >
                              {isActive ? '\u2713 ' : ''}{t}
                            </button>
                          );
                        })}
                      </div>
                    </>
                  ) : (
                    <div style={{ fontSize: '.72rem', color: 'var(--muted)', fontStyle: 'italic' }}>
                      No MCP tools registered for this skill
                    </div>
                  )}
                  {n.data?.description && (
                    <div style={{ fontSize: '.7rem', color: 'var(--muted)', marginTop: 6, fontStyle: 'italic' }}>
                      {n.data.description}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Skill inventory: all skills with phase toggle checkboxes */}
      {(() => {
        // Deduplicate: skip ari-skill-* aliases if a friendly name exists
        const allSkills = Object.entries(skillMcp)
          .filter(([name, entry]) => {
            if (name.startsWith('ari-skill-')) {
              return !Object.entries(skillMcp).some(
                ([other, oe]) => other !== name && !other.startsWith('ari-skill-') && oe.dir === (entry as any).dir,
              );
            }
            return true;
          })
          .sort(([a], [b]) => a.localeCompare(b));

        // Phase values understood by ari.mcp.client._phase_matches. "all"
        // matches every phase; "none" disables the skill. A skill may also
        // declare a list like ["paper", "reproduce"].
        type PhaseName = 'bfts' | 'paper' | 'reproduce';
        const PHASE_LIST: PhaseName[] = ['bfts', 'paper', 'reproduce'];

        const phasesOfEntry = (
          currentPhase: string | string[] | undefined,
        ): Set<PhaseName> => {
          // Legacy value: "pipeline" meant the paper pipeline.
          const toPhases = (v: string): PhaseName[] => {
            const s = v === 'pipeline' ? 'paper' : v;
            if (s === 'all') return [...PHASE_LIST];
            if (s === 'none' || s === '') return [];
            return PHASE_LIST.includes(s as PhaseName) ? [s as PhaseName] : [];
          };
          const acc = new Set<PhaseName>();
          if (Array.isArray(currentPhase)) {
            for (const v of currentPhase) toPhases(String(v)).forEach((p) => acc.add(p));
          } else {
            toPhases(currentPhase || 'all').forEach((p) => acc.add(p));
          }
          return acc;
        };

        const phasesToYaml = (phases: Set<PhaseName>): string | string[] => {
          if (phases.size === 0) return 'none';
          if (phases.size === PHASE_LIST.length) return 'all';
          if (phases.size === 1) return [...phases][0];
          return PHASE_LIST.filter((p) => phases.has(p));
        };

        const handlePhaseToggle = (
          skillName: string,
          currentPhase: string | string[] | undefined,
          toggledPhase: PhaseName,
        ) => {
          const phases = phasesOfEntry(currentPhase);
          if (phases.has(toggledPhase)) phases.delete(toggledPhase);
          else phases.add(toggledPhase);
          const newPhase = phasesToYaml(phases);

          // Update local state
          setSkillMcp((prev) => ({
            ...prev,
            [skillName]: { ...prev[skillName], phase: newPhase },
          }));

          // Persist to workflow.yaml
          saveSkillPhases([{ name: skillName, phase: newPhase }]).catch(() => {});
        };

        return (
          <div style={{ marginTop: 20 }}>
            <h4 style={{ margin: '0 0 10px', fontSize: '.85rem' }}>
              MCP Skill Inventory
            </h4>
            <div style={{ fontSize: '.72rem', color: 'var(--muted)', marginBottom: 10, display: 'flex', gap: 12, flexWrap: 'wrap' }}>
              <span><span style={{ background: '#10b98122', color: '#10b981', padding: '1px 5px', borderRadius: 4, fontSize: '.62rem' }}>stage</span> pipeline stage</span>
              <span><span style={{ background: '#3b82f622', color: '#3b82f6', padding: '1px 5px', borderRadius: 4, fontSize: '.62rem' }}>active</span> called indirectly</span>
              <span><span style={{ background: '#64748b22', color: '#64748b', padding: '1px 5px', borderRadius: 4, fontSize: '.62rem' }}>registered</span> currently unused</span>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {allSkills.map(([name, entry]) => {
                const col = skillColor(name);
                const usage = entry.usage || 'registered';
                const badgeStyles: Record<string, { bg: string; fg: string }> = {
                  stage:      { bg: '#10b98122', fg: '#10b981' },
                  active:     { bg: '#3b82f622', fg: '#3b82f6' },
                  registered: { bg: '#64748b22', fg: '#64748b' },
                };
                const badge = badgeStyles[usage] || badgeStyles.registered;
                const tools: string[] = (entry.tools || []).map(
                  (t: any) => (typeof t === 'string' ? t : t.name),
                );
                const enabledPhases = phasesOfEntry(entry.phase);
                const hasBfts = enabledPhases.has('bfts');
                const hasPaper = enabledPhases.has('paper');
                const hasReproduce = enabledPhases.has('reproduce');
                const isDisabled = enabledPhases.size === 0;
                return (
                  <div
                    key={name}
                    className="card"
                    style={{
                      borderLeft: `3px solid ${col}`,
                      padding: '6px 10px',
                      minWidth: 220,
                      maxWidth: 320,
                      opacity: isDisabled ? 0.4 : (usage === 'registered' ? 0.65 : 1),
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <strong style={{ color: col, fontSize: '.78rem' }}>{name}</strong>
                        <span style={{
                          fontSize: '.58rem', padding: '1px 5px', borderRadius: 4,
                          background: badge.bg, color: badge.fg,
                        }}>{usage}</span>
                      </div>
                      {usage !== 'stage' && (
                        <button
                          className="btn btn-outline btn-sm"
                          style={{ fontSize: '.65rem', padding: '1px 6px' }}
                          onClick={() => {
                            const stageName = name.replace(/-skill$/, '').replace(/-/g, '_');
                            const p = hasBfts ? 'bfts' : 'paper';
                            handleAddNode(stageName, name, '', p);
                          }}
                        >
                          + Stage
                        </button>
                      )}
                    </div>
                    {entry.description && (
                      <div style={{ fontSize: '.68rem', color: 'var(--muted)', marginTop: 2 }}>
                        {entry.description}
                      </div>
                    )}
                    {/* Phase toggle checkboxes */}
                    <div style={{ display: 'flex', gap: 10, marginTop: 5, fontSize: '.68rem' }}>
                      <label style={{ display: 'flex', alignItems: 'center', gap: 3, cursor: 'pointer' }}>
                        <input
                          type="checkbox"
                          checked={hasBfts}
                          onChange={() => handlePhaseToggle(name, entry.phase, 'bfts')}
                          style={{ accentColor: '#10b981' }}
                        />
                        <span style={{ color: '#10b981' }}>BFTS</span>
                      </label>
                      <label style={{ display: 'flex', alignItems: 'center', gap: 3, cursor: 'pointer' }}>
                        <input
                          type="checkbox"
                          checked={hasPaper}
                          onChange={() => handlePhaseToggle(name, entry.phase, 'paper')}
                          style={{ accentColor: '#8b5cf6' }}
                        />
                        <span style={{ color: '#8b5cf6' }}>Paper</span>
                      </label>
                      <label
                        style={{ display: 'flex', alignItems: 'center', gap: 3, cursor: 'pointer' }}
                        title="Expose this skill to the ReAct reproducibility agent (paper-re)."
                      >
                        <input
                          type="checkbox"
                          checked={hasReproduce}
                          onChange={() => handlePhaseToggle(name, entry.phase, 'reproduce')}
                          style={{ accentColor: '#f59e0b' }}
                        />
                        <span style={{ color: '#f59e0b' }}>Reproduce</span>
                      </label>
                    </div>
                    {tools.length > 0 && (
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3, marginTop: 4 }}>
                        {tools.map((t) => {
                          const off = disabledTools.has(t);
                          return (
                            <span
                              key={t}
                              onClick={() => {
                                const next = new Set(disabledTools);
                                if (off) next.delete(t); else next.add(t);
                                setDisabledTools(next);
                                saveDisabledTools([...next]).catch(() => {});
                              }}
                              style={{
                                fontSize: '.58rem', padding: '1px 4px', borderRadius: 4,
                                border: `1px solid ${off ? 'var(--border, #333)' : '#10b981'}`,
                                color: off ? 'var(--muted, #555)' : '#10b981',
                                background: off ? 'transparent' : '#10b98112',
                                textDecoration: off ? 'line-through' : 'none',
                                cursor: 'pointer',
                                userSelect: 'none',
                                opacity: off ? 0.5 : 1,
                              }}
                              title={off ? `${t}: OFF (click to enable)` : `${t}: ON (click to disable)`}
                            >{t}</span>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        );
      })()}

      {/* Context menu for edges */}
      {ctxMenu && (
        <div
          style={{
            position: 'fixed',
            left: ctxMenu.x,
            top: ctxMenu.y,
            background: 'var(--card, #1e1e2e)',
            border: '1px solid var(--border, #333)',
            borderRadius: 8,
            padding: '4px 0',
            zIndex: 1001,
            boxShadow: '0 4px 16px rgba(0,0,0,.4)',
          }}
        >
          <button
            style={{
              display: 'block',
              width: '100%',
              padding: '6px 14px',
              background: 'none',
              border: 'none',
              color: 'var(--text, #eee)',
              cursor: 'pointer',
              textAlign: 'left',
              fontSize: '.82rem',
            }}
            onClick={() => {
              const edge = edges.find((e) => e.id === ctxMenu.edgeId);
              if (edge) setCondEdge(edge);
              setCtxMenu(null);
            }}
          >
            Add Condition
          </button>
        </div>
      )}

      {/* Condition builder modal */}
      {condEdge && (
        <ConditionModal
          edge={condEdge}
          onSave={handleCondSave}
          onClose={() => setCondEdge(null)}
        />
      )}

      {/* Add node drawer */}
      {showAddNode && (
        <SkillDrawer onAdd={handleAddNode} onClose={() => setShowAddNode(false)} skillMcp={skillMcp} />
      )}

      {/* Node edit modal */}
      {editNode && (
        <NodeEditModal
          node={editNode}
          skillMcp={skillMcp}
          onSave={handleNodeEdit}
          onClose={() => setEditNode(null)}
        />
      )}

      {/* Skill detail modal */}
      {skillModalData && (
        <SkillModal skillModal={skillModalData} onClose={() => setSkillModalData(null)} />
      )}
    </div>
  );
}
