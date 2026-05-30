# ResultsPage.tsx Decomposition (requirement 03)

Task-control note from `03_frontend_large_component_decomposition.md`.
Captured 2026-05-30. Source-of-truth analysis from a 4-agent mapping workflow +
direct verification.

## What was done (this PR)

`components/Results/ResultsPage.tsx` (3177 lines) → split into:

| File | lines | contents |
|------|-------|----------|
| `ResultsPage.tsx` | ~1857 | the container `export function ResultsPage()` (byte-identical body) + imports |
| `resultSections.tsx` | ~1161 | all module-scope presentational subcomponents + pure helpers + types that lived below the container |
| `PublishYamlEditor.tsx` | ~162 | the `PublishYamlEditor` component + its props interface |

Method: exact `sed`/script slices (code moved **verbatim**); only `export`
keywords and minimal import headers added. Verified byte-for-byte: the container
body, the PublishYamlEditor block, and the sections block each equal the original
modulo added `export`/`import` lines. **Zero logic change.**

Exports added to `resultSections.tsx`: `tryParseJson`, `renderOrsChain`,
`FileViewers`, `renderLegacyRepro` (container imports only `renderOrsChain` and
`renderLegacyRepro`; the other two are referenced only within the file).
`PublishYamlEditor.tsx` exports `PublishYamlEditor`.

Checks: `npm run typecheck` 0 non-test errors (only the 11 pre-existing
`__tests__` jest-dom errors); `npm run build` ✓; `npm test -- --run` 4 passed / 2
failed (pre-existing brittle PaperBench `getByDisplayValue` tests). No regression.

## Why React behavior is preserved

The moved components are still single module-scope definitions imported by
reference, so component identity is stable across renders (no remount). The
render helpers `renderOrsChain`/`renderLegacyRepro` are plain functions called as
`renderOrsChain({...})` inside the container's JSX (not `<X/>`), so their returned
element trees are created each render exactly as before. `tryParseJson` preserves
its existing implementation verbatim.

## Module-scope dependency DAG (for the finer follow-up split, req 15)

```
resultTypes (RubricNode, LeafGrade, StageState, OrsRenderInput)
   ▲
resultHelpers (tryParseJson, buildGradeMap, aggregateScore, truncSha, fileCount,
   asFileList, formatFiles, formatRubricStage, replicatorState,
   formatReplicatorStage, phase1State, formatPhase1Stage, phase2State,
   formatPhase2Stage)   [note: format*Stage return React.ReactNode → .tsx]
   ▲
resultPrimitives (KvList, CollapsibleText, FileViewer, FileViewers, ScoreBar,
   ChainStage)   ← services/api(fetchCheckpointFilecontent), common/Button
   ▲
sections (GradingTreeSection, RubricTreeNode, LeafGradeRow, GenerationLogs,
   LogStage, Provenance, renderOrsChain, renderLegacyRepro)
   ← RubricTreeVisualization, common/Badge/Button
   ▲
ResultsPage (container)
```
No cycles. `Provenance` (used only by `renderOrsChain`) → keep with orsChain.
`leafComponents` (safest first to extract): KvList, CollapsibleText, ScoreBar,
LeafGradeRow, Provenance.

## Container-internal seams (deferred to req 15)

From the container analysis (line numbers are pre-split, original file):

| Seam | orig lines | risk | note |
|------|-----------|------|------|
| `renderReviewScores` → `<ReviewScoresCard report t/>` | 567-807 (+512,522,530) | low | pure fn of `summary.review_report`; no local state — best first extraction |
| `renderFigures` → `<FiguresGrid manifest/>` | 1855-1922 | low | pure fn of `summary.figures_manifest` |
| `renderContext` → `<ExperimentContextCard ctx/>` | 1414-1456 | low | pure fn of experiment_context |
| `renderRepro` + `reproLog*` → `<ReproSection>` | 1284-1411 | medium | prop contract shared by legacy panel AND renderOrsChain→GenerationLogs |
| `useCheckpointResults(checkpointId)` hook | 240-313,348-354,474-509 | medium | data spine: selectedId/summary/loading/error/ear/ckptFiles + 2 effects + sessionStorage handoff + prevHasRepro/prevHasReview ref-diff |
| `renderPaper` → `<PaperWorkspace>` | 996-1272 (+810-993 helpers) | high | most state-coupled: ~12 state vars, 5 handlers, uploadRef, Ctrl+S keydown, activeAbsPath ordering quirk |
| `renderEAR` + `useEAR` hook | 1459-1852 | high | 13 state vars; **duplicated curate-EAR block at ~1524 and ~1648** — a `useEAR` hook would dedupe |

Known smell (do NOT "fix" under a refactor): the container declares
`activeAbsPath` state mid-body (~orig L974) far from the other state, and calls
its setter (~L503) before the declaration (works via hoisting). Pin/relocate only
under a behavior-verified change.

## Follow-up (moved to req 15)

- Finer split of `resultSections.tsx` per the DAG above.
- Container seams above.
- The other 5 large components (Workflow, StepResources, Settings, DetailPanel,
  Monitor).
