# frontend/src/components/ConfigStudio/__tests__

Unit/component tests for the parent `ConfigStudio/` directory.

## Contents

- `README.md` — this file.
- `ConfigStudioExecutionMode.test.tsx` — tests for `ExecutionSection.tsx` + the ADR-09 launch-review wiring (mode selection accepted 2026-07-27): one control writes BOTH pair keys in a single PATCH, the two intents are orthogonal, all four combinations render and round-trip, re-selecting the stored value writes nothing (default path byte-identical), an inconsistent stored pair is flagged, the `rqgm.*` tree renders values with no editable control, the launch review shows the RESOLVED mode (requested→resolved + resolver warning on a fallback), and `mode_interlock_mismatch` blocks the launch with its typed message.
- `ConfigStudioLaunch.test.tsx` — tests for the `LaunchPanel.tsx` launch flow (gui_refresh task 06 Wave 4e, plan 06 §Launch protocol / backend MN-10): resolve→validate→review→launch happy path with the canonical `#/overview?run=<run_id>` redirect from the server-issued run_id, validation failure (`mode_locked`) blocking the POST, double-click single-POST + same-idempotency-key retry, typed error envelope rendering (request_id + per-path `details.errors`).
- `ConfigStudioPage.test.tsx` — tests for `ConfigStudioPage.tsx` (gui_refresh task 06 Wave 4d): schema-driven control generation, If-Match PATCH + 409 reload banner + per-path 400 ValidationSummary, write-only secret flow, the ADR-09 Execution section refused in PROJECT scope.
