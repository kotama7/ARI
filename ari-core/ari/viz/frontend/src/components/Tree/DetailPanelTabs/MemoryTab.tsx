// ARI Dashboard – DetailPanel "Memory" tab.
// Extracted verbatim from DetailPanel.tsx (refactor req 15): the memory-tab JSX
// block. The `activeTab === 'memory'` guard stays in the container; this renders
// the own/inherited/global memory cards. `t` is sourced via useI18n internally
// (behavior-identical to the container's closure over the same i18n context).

import { useI18n } from '../../../i18n';
import { LoadingState, ErrorState } from '../../common';
import type { MemoryEntry } from '../../../services/api';
import { MemoryEntryCard } from './MemoryEntryCard';

interface MemoryTabProps {
  memLoading: boolean;
  memError: string | null;
  visibleMemory: MemoryEntry[];
  globalEntries: MemoryEntry[];
  ancestorIds: string[];
  currentNodeId: string;
}

export function MemoryTab({
  memLoading,
  memError,
  visibleMemory,
  globalEntries,
  ancestorIds,
  currentNodeId,
}: MemoryTabProps) {
  const { t } = useI18n();
  return (
    <div>
      {memLoading && (
        <div style={{ fontSize: '.72rem' }}>
          <LoadingState inline />
        </div>
      )}
      {memError && <ErrorState message={memError} inline />}
      {!memLoading &&
        !memError &&
        visibleMemory.length === 0 &&
        globalEntries.length === 0 && (
          <div style={{ fontSize: '.75rem', color: 'var(--muted)' }}>
            {t('memory_empty')}
          </div>
        )}
      {!memLoading && visibleMemory.length > 0 && (
        <div
          style={{
            fontSize: '.72rem',
            color: 'var(--muted)',
            marginBottom: 6,
          }}
        >
          <span className="badge badge-blue" style={{ marginRight: 4 }}>
            {t('memory_own')}
          </span>
          <span className="badge badge-muted">
            {t('memory_inherited')}
          </span>
        </div>
      )}
      {globalEntries.length > 0 && (
        <div style={{ marginBottom: 8 }}>
          <div
            style={{
              fontSize: '.7rem',
              color: 'var(--muted)',
              textTransform: 'uppercase',
              letterSpacing: '.04em',
              margin: '8px 0 4px',
            }}
          >
            {t('memory_global_header')} ({globalEntries.length})
          </div>
          {globalEntries.map((e, i) => (
            <MemoryEntryCard
              key={`g-${i}`}
              entry={e}
              variant="global"
              labels={{
                fromNode: t('memory_from_node'),
                sourceMcp: t('memory_source_mcp'),
                sourceFile: t('memory_source_file'),
                sourceGlobal: t('memory_source_global'),
              }}
            />
          ))}
        </div>
      )}
      {visibleMemory.map((e, i) => {
        const own = e.node_id === currentNodeId;
        const depthIdx = ancestorIds.indexOf(e.node_id);
        return (
          <MemoryEntryCard
            key={i}
            entry={e}
            variant={own ? 'own' : 'inherited'}
            ancestorIndex={depthIdx}
            labels={{
              fromNode: t('memory_from_node'),
              sourceMcp: t('memory_source_mcp'),
              sourceFile: t('memory_source_file'),
              sourceGlobal: t('memory_source_global'),
            }}
          />
        );
      })}
    </div>
  );
}
