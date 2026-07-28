# frontend/src/components/ConfigBrowser

Read-only effective-config browser — gui_refresh Wave 3b (plans 05 §Purpose / §Resolved manifest, 06 §Effective configuration): the canonical config-field registry (`GET /api/v1/config/schema`) grouped by category, overlaid with a run's resolved manifest (`GET /api/v1/runs/{run_id}/resolved-config`) when the hash carries `?run=<run_id>`. Gated on the `gui_v2` capability. Studio editing is Wave 4 — nothing here mutates anything.

## Contents

- `README.md` — this file.
- `ConfigBrowserPage.tsx` — schema/effective-config browser (category groups, search, provenance/mutability badges, secret-reference redaction, resolver warnings).
- `ConfigReadOnlyTable.tsx` — the ONE read-only config row/table renderer (value formatting, secret redaction, `SOURCE_VARIANT`/`MUTABILITY_VARIANT` badge maps); shared with the Configuration Studio's ADR-09 Execution section so the two config surfaces cannot drift.
- `index.ts` — barrel re-export.
- `__tests__/` — component tests for this directory.
  - `ConfigBrowserPage.test.tsx` — tests for `ConfigBrowserPage.tsx` (144-field schema mode + search, run-mode provenance/warnings/secret redaction, error envelope with request_id).
