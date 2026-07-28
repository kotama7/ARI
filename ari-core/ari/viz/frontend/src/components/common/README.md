# frontend/src/components/common

Reusable presentational UI primitives shared across pages.

## Contents

- `README.md` — this file.
- `Badge.tsx` — colored variant label span.
- `Button.tsx` — styled button with variant/size props.
- `Card.tsx` — bordered content container.
- `DegradedState.tsx` — canonical PARTIAL-data affordance (warning tokens, `role="status"`, surrounding content stays visible); deliberately distinct from `ErrorState`, which means total failure.
- `EmptyState.tsx` — TODO
- `ErrorState.tsx` — TODO
- `index.ts` — barrel re-exports.
- `LoadingState.tsx` — TODO
- `NavRail.tsx` — vertical slice navigation: a real list with `aria-current` on the selected item, selected/unselected states from the `.nav-rail` tokens; navigation, so deliberately not `Button`.
- `StaleDataBanner.tsx` — freshness notice for live surfaces: keeps the last known snapshot visible and says how fresh it is (`aria-live="polite"`); a dropped stream is never presented as "run stopped".
- `StatBox.tsx` — single value + label stat tile.
- `StatusBadge.tsx` — maps run status to a colored `Badge`.
- `TabStrip.tsx` — the ONE v2 tablist look (`role=tablist/tab`, `aria-selected`/`aria-controls`); the owning page renders the matching `role="tabpanel"` using the `${idPrefix}-tab-<id>` / `${idPrefix}-panel-<id>` id convention.
- `__tests__/` — TODO
  - `asyncStates.test.tsx` — `DegradedState`/`StaleDataBanner` contract: status roles, default translated titles, and the retry/refresh callbacks.
  - `StateComponents.test.tsx` — TODO
