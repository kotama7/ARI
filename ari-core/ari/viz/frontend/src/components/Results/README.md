# frontend/src/components/Results

Results page — final run results and rubric scoring.

## Contents

- `README.md` — this file.
- `EarSection.tsx` — Experiment Artifact Repository section (curate/publish/publish.yaml editor); extracted from ResultsPage renderEAR in req 15.
- `index.ts` — barrel re-export.
- `PaperWorkspace.tsx` — Overleaf-like paper editor (file tree + PDF/editor views + compile log); extracted from ResultsPage renderPaper in req 15.
- `PdfPreview.tsx` — app-owned PDF.js canvas preview (page nav, zoom, loading/error states) so managed or Chromium browsers without an embedded viewer still show the compiled paper.
- `PublishYamlEditor.tsx` — per-checkpoint publish.yaml (EAR allowlist) editor; extracted from ResultsPage in req 03.
- `resultHelpers.ts` — pure helpers + string formatters (tryParseJson, buildGradeMap, aggregateScore, format*Stage, etc.); extracted from resultSections in req 15.
- `resultSections.tsx` — presentational subcomponents and pure helpers for the results page; extracted from ResultsPage in req 03.
- `ResultsPage.tsx` — results page container (state, data loading, layout).
- `resultTypes.ts` — Results-page shared types (OrsRenderInput, RubricNode, LeafGrade, StageState); extracted from resultSections in req 15.
- `RubricTreeVisualization.tsx` — D3 rubric tree with aggregated leaf scores.
- `useEAR.ts` — hook owning EarSection's curate/publish/publish.yaml-editor action state; extracted from ResultsPage in req 15.
- `__tests__/` — unit tests for this directory.
  - `ResultsPageRoute.test.ts` — `runFromResultsHash` route parsing: `#/results?run=<id>` yields the URL-decoded run id, a bare `#/results` yields an empty selection.
- `sections/` — the pure `render*` section functions split out of the ResultsPage container: context, figures, ORS chain, reproducibility, review scores.
  - `ContextSection.tsx` — `renderContext` — experiment-context card over `summary.science_data.experiment_context`, values over 500 chars collapsed into `<details>`; null when absent.
  - `FiguresSection.tsx` — `renderFigures` — figures grid normalizing `figures_manifest`'s dict and legacy-list shapes, with captions extracted from the stored LaTeX snippets.
  - `OrsChainSection.tsx` — `renderOrsChain` — PaperBench-aware ORS chain: headline verdict plus per-stage status for `ors_rubric_meta` / `ors_replicator` / `ors_seed` / `ors_phase1` / `ors_grade` and the rubric tree.
  - `ReproSection.tsx` — `renderRepro` — reproducibility section dispatching to the ORS chain or the legacy panel plus the repro-log toolbar; `renderLegacyRepro` handles the pre-§4.1 `reproducibility_report` shape.
  - `ReviewScoresSection.tsx` — `renderReviewScores` — `summary.review_report` card mapping decision to badge variant and rendering rubric-driven or legacy dimensional scores.
