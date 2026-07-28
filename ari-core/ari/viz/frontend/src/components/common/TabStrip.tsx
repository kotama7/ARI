// ARI Dashboard – shared tab strip primitive (gui_refresh plan 02: a v2
// workspace is composed from semantic tokens + shared primitives only).
//
// ONE tablist look for every v2 workspace. The Governance workspace shipped
// the pattern first (role=tablist/tab + aria-selected/aria-controls over the
// `.tab-strip` tokens); extracting it here is what keeps a second workspace
// (the Configuration Studio scope bar) from inventing a third look.
//
// Tabs are NAVIGATION, not actions, so this is deliberately NOT the shared
// <Button> (an action affordance): a tab carries role="tab"/aria-selected and
// never the .btn treatment.
//
// The owning page keeps the panel: ids follow `${idPrefix}-tab-<id>` and
// `${idPrefix}-panel-<id>`, so the page's role="tabpanel" pairs up with the
// tab's aria-controls via aria-labelledby.

import type { ReactNode } from 'react';

export interface TabStripItem<T extends string = string> {
  /** Stable tab key — also the `${idPrefix}-tab-<id>` DOM id suffix. */
  id: T;
  label: ReactNode;
  /** Native disabled button (an unreachable tab states why via `title`). */
  disabled?: boolean;
  title?: string;
}

interface TabStripProps<T extends string> {
  items: readonly TabStripItem<T>[];
  /** Selected tab id; a value outside `items` selects nothing. */
  activeId: string;
  onSelect: (id: T) => void;
  /** Accessible name of the tablist. */
  ariaLabel: string;
  /** DOM id namespace shared with the page's tabpanel. */
  idPrefix: string;
}

export function TabStrip<T extends string>({
  items,
  activeId,
  onSelect,
  ariaLabel,
  idPrefix,
}: TabStripProps<T>) {
  return (
    <div className="tab-strip" role="tablist" aria-label={ariaLabel}>
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          role="tab"
          id={`${idPrefix}-tab-${item.id}`}
          className="tab-strip-tab"
          aria-selected={activeId === item.id}
          aria-controls={`${idPrefix}-panel-${item.id}`}
          disabled={item.disabled}
          title={item.title}
          onClick={() => onSelect(item.id)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
