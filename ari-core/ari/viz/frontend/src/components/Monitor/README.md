# frontend/src/components/Monitor

Monitor page — live run progress and resource monitoring.

## Contents

- `README.md` — this file.
- `GpuMonitor.tsx` — GPU usage monitor card.
- `index.ts` — barrel re-export.
- `MonitorPage.tsx` — monitor page container.
- `monitorSections.tsx` — metric helper + Experiment-Configuration card (extracted from MonitorPage in req 15).
- `PhaseStepper.tsx` — workflow phase progress bar (idea→bfts→paper→review).
- `__tests__/` — component tests for this directory.
  - `MonitorPage.test.tsx` — RR-D-1 regression: partial `/api/resource-metrics` payload renders placeholders, never a TypeError crash.
