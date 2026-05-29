# frontend/src/components/PaperBench

PaperBench UI — register external papers, import them, and launch/inspect PaperBench runs.

## Contents

- `README.md` — this file.
- `index.ts` — barrel re-exports.
- `PaperBenchWizard.tsx` — wizard to configure a PaperBench run.
- `PaperImportDialog.tsx` — dialog to import a new paper.
- `PaperRegistryPage.tsx` — lists registered papers (GET /api/paperbench/papers).
- `__tests__/` — component tests for this directory.
  - `README.md` — __tests__ index.
  - `PaperBenchWizard.test.tsx` — tests for `PaperBenchWizard.tsx`.
  - `PaperImportDialog.test.tsx` — tests for `PaperImportDialog.tsx`.
- `results/` — rubric-scored results view.
  - `README.md` — results index.
  - `ResultsView.tsx` — leaf grades + rubric tree + negative-control display.
