// ARI Dashboard – shared vertical navigation rail. A v2 workspace is composed
// from semantic tokens and shared primitives only: no screen defines its own
// look for something another screen already has, which is why this lives here
// rather than in the workspace that needed it first.
//
// A rail selects WHICH slice of a workspace is shown — navigation, not an
// action — so it is deliberately NOT the shared <Button> (an action
// affordance) and not the tab strip (a horizontal composite): it renders a
// real list, one item per slice, with `aria-current` on the selected one and
// the selected/unselected states coming from the `.nav-rail` semantic tokens.
//
// An item may carry a trailing accessory (e.g. the Configuration Studio's
// per-category pending-edit Badge); the accessory lives INSIDE the item's
// control so it is part of that item's accessible name.

import type { ReactNode } from 'react';

export interface NavRailItem<T extends string = string> {
  id: T;
  label: ReactNode;
  /** Trailing accessory rendered inside the item (e.g. a count Badge). */
  accessory?: ReactNode;
}

interface NavRailProps<T extends string> {
  items: readonly NavRailItem<T>[];
  /** Selected item id; a value outside `items` selects nothing. */
  activeId: string;
  onSelect: (id: T) => void;
  /** Accessible name of the navigation landmark. */
  ariaLabel: string;
}

export function NavRail<T extends string>({
  items,
  activeId,
  onSelect,
  ariaLabel,
}: NavRailProps<T>) {
  return (
    <nav className="nav-rail" aria-label={ariaLabel}>
      <ul className="nav-rail-list">
        {items.map((item) => (
          <li key={item.id}>
            <button
              type="button"
              className="nav-rail-item"
              aria-current={activeId === item.id ? true : undefined}
              onClick={() => onSelect(item.id)}
            >
              <span className="nav-rail-item-label">{item.label}</span>
              {item.accessory}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}
