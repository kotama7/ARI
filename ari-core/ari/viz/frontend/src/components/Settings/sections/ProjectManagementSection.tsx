import { Card } from '../../common';
import type { Checkpoint } from '../../../types';

interface ProjectManagementSectionProps {
  checkpoints: Checkpoint[];
  activeId: string;
  onDelete: (id: string, path: string) => void;
}

export function ProjectManagementSection({
  checkpoints,
  activeId,
  onDelete,
}: ProjectManagementSectionProps) {
  return (
    <Card title="Project Management">
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {checkpoints.length > 0 ? (
          checkpoints.map((c) => {
            const isActive = c.id === activeId;
            const isRunning = c.status === 'running';
            const borderColor = isActive ? 'var(--primary)' : 'var(--border)';
            return (
              <div
                key={c.id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '12px',
                  padding: '10px 14px',
                  background: 'var(--card)',
                  border: `1px solid ${borderColor}`,
                  borderRadius: '8px',
                }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    title={c.id}
                    style={{
                      fontSize: '.85rem',
                      fontWeight: 600,
                      color: 'var(--text)',
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      maxWidth: '360px',
                    }}
                  >
                    {c.id}
                  </div>
                  <div style={{ fontSize: '.75rem', color: 'var(--muted)', marginTop: '2px' }}>
                    {c.node_count} nodes {'·'}{' '}
                    {new Date(c.mtime * 1000).toLocaleString()}
                  </div>
                  <div style={{ marginTop: '4px', display: 'flex', gap: '6px' }}>
                    {isRunning && (
                      <span
                        style={{
                          background: 'rgba(16,185,129,.2)',
                          color: '#10b981',
                          borderRadius: '12px',
                          padding: '2px 8px',
                          fontSize: '.72rem',
                          fontWeight: 700,
                        }}
                      >
                        {'●'} Running
                      </span>
                    )}
                    {isActive && (
                      <span
                        style={{
                          background: 'rgba(59,130,246,.2)',
                          color: '#3b82f6',
                          borderRadius: '12px',
                          padding: '2px 8px',
                          fontSize: '.72rem',
                          fontWeight: 700,
                        }}
                      >
                        Active
                      </span>
                    )}
                  </div>
                </div>
                <button
                  className="btn btn-sm"
                  style={{
                    background: 'rgba(239,68,68,.15)',
                    color: '#ef4444',
                    border: '1px solid rgba(239,68,68,.3)',
                    whiteSpace: 'nowrap',
                  }}
                  onClick={() => onDelete(c.id, c.path)}
                >
                  {'🗑'} Delete
                </button>
              </div>
            );
          })
        ) : (
          <span style={{ color: 'var(--muted)' }}>No projects found.</span>
        )}
      </div>
    </Card>
  );
}
