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
