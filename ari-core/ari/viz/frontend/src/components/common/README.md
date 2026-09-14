# frontend/src/components/common

Reusable presentational UI primitives shared across pages.

## Contents

- `README.md` — this file.
- `Badge.tsx` — colored variant label span.
- `Button.tsx` — styled button with variant/size props.
- `Card.tsx` — bordered content container.
- `DegradedState.tsx` — canonical PARTIAL-data affordance (warning tokens, `role="status"`, surrounding content stays visible); deliberately distinct from `ErrorState`, which means total failure.
- `EmptyState.tsx` — canonical "no data yet" block on the `.empty-state`/`.empty-icon` CSS; caller passes an already-translated `message` plus optional emoji `icon` and `hint`.
- `ErrorState.tsx` — canonical total-failure affordance: `var(--red)` message plus optional Retry button, rendering a plain string from either api error regime (thrown message or `{error}` body).
- `index.ts` — barrel re-exports.
- `LoadingState.tsx` — canonical spinner + translated label replacing the ad-hoc `<span className="spinner" /> {t('loading')}` patterns; `inline` renders a row instead of a centered block.
- `NavRail.tsx` — vertical slice navigation: a real list with `aria-current` on the selected item, selected/unselected states from the `.nav-rail` tokens; navigation, so deliberately not `Button`.
- `StaleDataBanner.tsx` — freshness notice for live surfaces: keeps the last known snapshot visible and says how fresh it is (`aria-live="polite"`); a dropped stream is never presented as "run stopped".
- `StatBox.tsx` — single value + label stat tile.
- `StatusBadge.tsx` — maps run status to a colored `Badge`.
- `TabStrip.tsx` — the ONE v2 tablist look (`role=tablist/tab`, `aria-selected`/`aria-controls`); the owning page renders the matching `role="tabpanel"` using the `${idPrefix}-tab-<id>` / `${idPrefix}-panel-<id>` id convention.
- `__tests__/` — unit tests for the primitives in this directory.
  - `asyncStates.test.tsx` — `DegradedState`/`StaleDataBanner` contract: status roles, default translated titles, and the retry/refresh callbacks.
  - `StateComponents.test.tsx` — `LoadingState`/`EmptyState`/`ErrorState` kit contract: default vs overridden labels, icon/hint rendering, and the retry button existing only when `onRetry` is passed.
