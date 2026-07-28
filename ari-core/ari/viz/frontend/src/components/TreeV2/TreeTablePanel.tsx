// ARI Dashboard – TreeV2 virtualized side table (gui_refresh task 07 tail;
// plan 07 §Tree workspace: provide keyboard navigation and an equivalent
// tabular hierarchy / "virtualized side table").
//
// Renders the SAME visible set as the D3 canvas (the page computes it once
// via computeVisibleRows and hands the flat DFS rows here) as a
// depth-indented ARIA tree with:
//
//   - simple scrollTop-based windowing (no new dependency): a spacer div
//     carries the full height, and only the rows inside the viewport
//     (plus overscan) exist in the DOM — ~40 rows for a 10k-node tree;
//   - roving tabindex + ArrowUp/ArrowDown (move focus), ArrowLeft /
//     ArrowRight (collapse / expand the subtree — per-node overrides in
//     the page), Enter (select → ?node= in the URL, which opens the
//     inspector; the hash stays the single source of truth);
//   - aria semantics: role=tree on the scroll container, role=group on
//     the windowed slice, role=treeitem rows with aria-level /
//     aria-expanded / aria-selected.
//
// Selection is NOT owned here: clicking a row or pressing Enter calls
// onSelect(id), which writes ?node= to the hash exactly like a canvas
// click does — both views re-render from the same URL state.

import { useEffect, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { useT } from '../../i18n';
import type { VisibleRow } from './treeLod';

export const TREE_TABLE_ROW_HEIGHT = 28;
/** Rows rendered beyond the viewport on each side. */
const OVERSCAN = 6;
/** Viewport height fallback (jsdom / pre-measure first paint). */
const VIEWPORT_FALLBACK = 600;

interface TreeTablePanelProps {
  rows: VisibleRow[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** Per-node expand/collapse override (true = expand). */
  onToggle: (id: string, expand: boolean) => void;
}

export function TreeTablePanel({
  rows,
  selectedId,
  onSelect,
  onToggle,
}: TreeTablePanelProps) {
  const t = useT();
  const containerRef = useRef<HTMLDivElement>(null);
  const rowRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const pendingFocusRef = useRef(false);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportH, setViewportH] = useState(0);
  // Roving-tabindex anchor, tracked by node id so expand/collapse cannot
  // silently move the focus to a different node.
  const [activeId, setActiveId] = useState<string | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (el && el.clientHeight > 0) setViewportH(el.clientHeight);
  }, []);

  const vh = viewportH > 0 ? viewportH : VIEWPORT_FALLBACK;
  const rowH = TREE_TABLE_ROW_HEIGHT;

  // Effective active row: explicit anchor if still visible, else the
  // selection, else the first row.
  let activeIndex = activeId === null ? -1 : rows.findIndex((r) => r.node.id === activeId);
  if (activeIndex === -1 && selectedId !== null) {
    activeIndex = rows.findIndex((r) => r.node.id === selectedId);
  }
  if (activeIndex === -1 && rows.length > 0) activeIndex = 0;

  // Windowed slice [start, end).
  const start = Math.max(0, Math.floor(scrollTop / rowH) - OVERSCAN);
  const end = Math.min(rows.length, Math.ceil((scrollTop + vh) / rowH) + OVERSCAN);
  const slice = rows.slice(start, end);

  // The tab stop must exist in the DOM: if the active row is scrolled out
  // of the window, the first rendered row carries tabIndex=0 instead.
  const activeInSlice = activeIndex >= start && activeIndex < end;
  const tabStopId = activeInSlice
    ? rows[activeIndex].node.id
    : (slice[0]?.node.id ?? null);

  /** Move the roving focus to rows[index], scrolling it into the window. */
  const moveActive = (index: number): void => {
    if (index < 0 || index >= rows.length) return;
    setActiveId(rows[index].node.id);
    let st = scrollTop;
    if (index * rowH < st) st = index * rowH;
    else if ((index + 1) * rowH > st + vh) st = (index + 1) * rowH - vh;
    if (st !== scrollTop) {
      setScrollTop(st);
      if (containerRef.current) containerRef.current.scrollTop = st;
    }
    pendingFocusRef.current = true;
  };

  // Focus the active row after keyboard-driven re-renders (never on
  // ordinary renders — that would steal focus from the rest of the page).
  useEffect(() => {
    if (!pendingFocusRef.current) return;
    pendingFocusRef.current = false;
    const id = activeId ?? tabStopId;
    if (id !== null) rowRefs.current.get(id)?.focus();
  });

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>): void => {
    if (activeIndex < 0) return;
    const row = rows[activeIndex];
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        moveActive(activeIndex + 1);
        break;
      case 'ArrowUp':
        e.preventDefault();
        moveActive(activeIndex - 1);
        break;
      case 'ArrowRight':
        e.preventDefault();
        if (row.hasChildren && !row.expanded) {
          onToggle(row.node.id, true);
          pendingFocusRef.current = true;
        }
        break;
      case 'ArrowLeft':
        e.preventDefault();
        if (row.hasChildren && row.expanded) {
          onToggle(row.node.id, false);
          pendingFocusRef.current = true;
        }
        break;
      case 'Enter':
        e.preventDefault();
        setActiveId(row.node.id);
        onSelect(row.node.id);
        break;
      default:
        break;
    }
  };

  return (
    <div
      ref={containerRef}
      data-testid="tree2-tree-table"
      role="tree"
      aria-label={t('tree2_table_label')}
      onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
      onKeyDown={onKeyDown}
      style={{
        width: 300,
        minWidth: 220,
        marginLeft: 12,
        overflowY: 'auto',
        overflowX: 'hidden',
        border: '1px solid var(--border)',
        borderRadius: 8,
        position: 'relative',
      }}
    >
      {/* Spacer: the full scrollable height of ALL rows. */}
      <div aria-hidden="true" style={{ height: rows.length * rowH, width: 1 }} />
      <div
        role="group"
        style={{
          position: 'absolute',
          top: start * rowH,
          left: 0,
          right: 0,
        }}
      >
        {slice.map((row) => {
          const id = row.node.id;
          const isSelected = id === selectedId;
          return (
            <div
              key={id}
              ref={(el) => {
                if (el) rowRefs.current.set(id, el);
                else rowRefs.current.delete(id);
              }}
              role="treeitem"
              data-node-id={id}
              aria-level={row.level + 1}
              aria-expanded={row.hasChildren ? row.expanded : undefined}
              aria-selected={isSelected}
              tabIndex={id === tabStopId ? 0 : -1}
              title={id}
              onClick={() => {
                setActiveId(id);
                onSelect(id);
              }}
              style={{
                height: rowH,
                lineHeight: `${rowH}px`,
                paddingLeft: 8 + row.level * 14,
                paddingRight: 8,
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                cursor: 'pointer',
                fontSize: '.78rem',
                background: isSelected ? 'rgba(59,130,246,.18)' : 'transparent',
              }}
            >
              <span
                aria-hidden="true"
                onClick={(e) => {
                  e.stopPropagation();
                  if (row.hasChildren) onToggle(id, !row.expanded);
                }}
                style={{
                  display: 'inline-block',
                  width: 14,
                  color: 'var(--text-muted)',
                  visibility: row.hasChildren ? 'visible' : 'hidden',
                }}
              >
                {row.expanded ? '▾' : '▸'}
              </span>
              <code style={{ fontSize: '.76rem' }}>{id}</code>{' '}
              <span style={{ color: 'var(--text-muted)', fontSize: '.7rem' }}>
                {row.node.status}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
