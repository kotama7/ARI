# frontend/src/components/Results

Results page — final run results and rubric scoring.

## Contents

- `README.md` — this file.
- `EarSection.tsx` — Experiment Artifact Repository section (curate/publish/publish.yaml editor); extracted from ResultsPage renderEAR in req 15.
- `index.ts` — barrel re-export.
- `PublishYamlEditor.tsx` — per-checkpoint publish.yaml (EAR allowlist) editor; extracted from ResultsPage in req 03.
- `resultHelpers.ts` — pure helpers + string formatters (tryParseJson, buildGradeMap, aggregateScore, format*Stage, etc.); extracted from resultSections in req 15.
- `resultSections.tsx` — presentational subcomponents and pure helpers for the results page; extracted from ResultsPage in req 03.
- `ResultsPage.tsx` — results page container (state, data loading, layout).
- `resultTypes.ts` — Results-page shared types (OrsRenderInput, RubricNode, LeafGrade, StageState); extracted from resultSections in req 15.
- `RubricTreeVisualization.tsx` — D3 rubric tree with aggregated leaf scores.
- `useEAR.ts` — hook owning EarSection's curate/publish/publish.yaml-editor action state; extracted from ResultsPage in req 15.
