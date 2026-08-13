# frontend/src/components/Wizard

Run-launch wizard — multi-step form to configure and start a new run.

## Contents

- `README.md` — this file.
- `index.ts` — barrel re-export.
- `StepGoal.tsx` — research goal / chat step.
- `StepLaunch.tsx` — final review + launch step.
- `StepResources.tsx` — provider/model and container-image step.
- `stepResourcesSections.tsx` — ORS model tables + OrsModelPicker/FewshotManager (extracted from StepResources in req 15).
- `StepScope.tsx` — search scope (max depth/nodes) step.
- `WizardPage.tsx` — wizard container/step orchestration.
- `__tests__/` — Unit/component tests for the parent `Wizard/` directory
  - `README.md` — __tests__ index.
  - `StepResourcesCatalog.test.tsx` — step 3 renders the served model catalog (`GET /api/v1/config/catalogs/models`): providers, per-provider model lists and the provider→API-key-env mapping all come from the server, the endpoint-unavailable path invents nothing, and a source-level guard pins that no frontend copy of the catalog returns.
