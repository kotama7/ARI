# ARI viz dashboard (frontend)

React + Vite + TypeScript. Served by `ari viz` / `python -m ari.viz.server`
which bundles the production build via `vite build`.

## Develop

```bash
npm install
npm run dev          # hot-reload dev server at http://localhost:5173
npm run typecheck    # tsc --noEmit
npm run build        # emit dist/ for production
```

## Test (v0.7.2+)

The PaperBench surface
(`src/components/PaperBench/{PaperImportDialog,PaperBenchWizard,results/ResultsView}.tsx`)
ships with [Vitest](https://vitest.dev) + React Testing Library
component tests.

```bash
npm install          # installs vitest, @testing-library/*, jsdom
npm test             # single pass
npm run test:watch   # interactive
```

Tests live under `src/**/__tests__/*.test.tsx`. The jsdom setup
(`vitest.setup.ts`) stubs `EventSource` so SSE-using components can be
rendered without a real network. Each test that calls `fetch` should
`vi.stubGlobal('fetch', ...)` with a mock returning the expected JSON.

Frontend tests are **not** run by the `refactor-guards` CI workflow yet
(no Node setup in that job). Add a separate `frontend-test` workflow
or invoke `npm test` from a pre-merge hook when you want the green-bar
guarantee.

## Layout

```
src/
├── App.tsx                       hash-router → PAGE_MAP lookup
├── components/
│   ├── Layout/                   sidebar + main shell
│   ├── PaperBench/               v0.7.2 paper registry + run wizard
│   │   ├── PaperRegistryPage.tsx
│   │   ├── PaperImportDialog.tsx
│   │   ├── PaperBenchWizard.tsx
│   │   ├── results/
│   │   │   └── ResultsView.tsx
│   │   └── __tests__/            Vitest component tests
│   ├── Experiments/              existing experiment list
│   ├── Wizard/                   existing 4-step launch wizard
│   ├── Results/                  existing results page
│   └── …
├── context/                      AppContext (shared state)
├── hooks/
├── i18n/                         en.ts / ja.ts / zh.ts dictionaries
├── services/                     fetch helpers
└── styles/                       dashboard.css
```
