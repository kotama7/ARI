# frontend/src/components/Tree

BFTS tree page — renders the search tree, a per-node detail panel, and a file browser.

## Contents

- `README.md` — this file.
- `DetailPanel.tsx` — selected-node detail panel (tabs: memory, report, etc.).
- `detailPanelHelpers.ts` — pure ancestor-chain helper (`computeAncestorIds`) extracted from DetailPanel in req 15.
- `FileExplorer.tsx` — checkpoint/node file tree browser.
- `index.ts` — barrel re-export.
- `TreePage.tsx` — tree page container.
- `TreeVisualization.tsx` — D3 search-tree canvas.
- `useDetailPanelData.ts` — hook owning DetailPanel's memory/access-log/node-report fetch effects; extracted from DetailPanel in req 15.
- `DetailPanelTabs/` — extracted detail-panel subcomponents.
  - `README.md` — DetailPanelTabs index.
  - `MemoryEntryCard.tsx` — renders one memory record (own/inherited/global) as a card.
