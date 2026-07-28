# frontend/src/components/Projects

Projects workspace — the first gui_refresh v2 vertical slice (plans 01 §Route model, 07 §Projects and run portfolio): a read-only run portfolio built on the typed `/api/v1` react-query hooks, gated on the `gui_v2` capability.

## Contents

- `README.md` — this file.
- `index.ts` — barrel re-export.
- `ProjectsPage.tsx` — v2 run-portfolio table (projects -> runs of the virtual `default` project).
- `__tests__/` — component tests for this directory.
  - `ProjectsPage.test.tsx` — tests for `ProjectsPage.tsx` (rows, empty state, error envelope, two-run isolation, results handoff).
