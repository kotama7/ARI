// Results render-section barrel.
//
// The six presentational render-fns that used to live inline in this ~1590-line
// god-file were extracted verbatim into sibling files under ./sections/ as part
// of the subtask-064 dashboard state/component-boundary split. This module is
// now a thin re-export barrel: the exported function names, signatures, and
// import path (`from './resultSections'`) are unchanged, so ResultsPage.tsx and
// any other caller keep working with no edit. Rendered DOM is byte-identical —
// this was a pure code move, not a behavior change.
//
//   ./sections/OrsChainSection.tsx    → renderOrsChain (+ ORS-only helpers)
//   ./sections/ReproSection.tsx       → renderLegacyRepro, renderRepro
//   ./sections/ContextSection.tsx     → renderContext
//   ./sections/FiguresSection.tsx     → renderFigures
//   ./sections/ReviewScoresSection.tsx→ renderReviewScores

export { renderOrsChain } from './sections/OrsChainSection';
export { renderLegacyRepro, renderRepro } from './sections/ReproSection';
export { renderContext } from './sections/ContextSection';
export { renderFigures } from './sections/FiguresSection';
export { renderReviewScores } from './sections/ReviewScoresSection';
