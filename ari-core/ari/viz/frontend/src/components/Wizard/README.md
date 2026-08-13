# frontend/src/components/Wizard

Run-launch wizard — multi-step form to configure and start a new run.

## Contents

- `README.md` — this file.
- `index.ts` — barrel re-export.
- `StepGoal.tsx` — research goal / chat step.
- `StepLaunch.tsx` — final review + launch step.
- `StepResources.tsx` — provider/model and container-image step.
- `stepResourcesSections.tsx` — OrsModelPicker/FewshotManager (extracted from StepResources in req 15). The ORS model table is gone; the picker maps its own provider labels (`google`, `custom`) onto catalog ids and takes models from `useModelCatalog`.
- `StepScope.tsx` — search scope (max depth/nodes) step.
- `WizardPage.tsx` — wizard container/step orchestration.
