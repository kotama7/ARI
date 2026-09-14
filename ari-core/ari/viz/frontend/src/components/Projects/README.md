# frontend/src/components/Projects

Projects workspace — the first gui_refresh v2 vertical slice: a read-only run portfolio built on the typed `/api/v1` react-query hooks, gated on the `gui_v2` capability. Its rows link run-explicitly (`#/results?run=<run_id>`) rather than handing a selection over implicitly, so opening two runs in two tabs cannot make them step on each other; the route itself exists only as an entry in `src/app/routeRegistry.ts`, which is the single place a route is declared.

## Contents

- `README.md` — this file.
- `index.ts` — barrel re-export.
- `ProjectsPage.tsx` — v2 run-portfolio table (projects -> runs of the virtual `default` project).
- `__tests__/` — component tests for this directory.
  - `ProjectsPage.test.tsx` — tests for `ProjectsPage.tsx` (rows, empty state, error envelope, two-run isolation, results handoff).
