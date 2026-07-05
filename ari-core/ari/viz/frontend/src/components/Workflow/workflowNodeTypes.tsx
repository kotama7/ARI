// ARI Dashboard – Workflow React Flow custom node renderers.
// Extracted verbatim from workflowNodes.tsx (subtask-064 god-component split):
// the React Flow custom-node components (phase/condition/parallel), the
// node-type map, and the deterministic skillColor helper. Bodies are unchanged;
// workflowNodes.tsx re-exports skillColor + nodeTypes from here, so WorkflowPage
// keeps importing them from './workflowNodes' with no edit.

import { Handle, Position, type NodeTypes } from 'reactflow';

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
          {'✕'}
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
