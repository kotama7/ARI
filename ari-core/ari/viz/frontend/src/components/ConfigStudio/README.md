# ConfigStudio — schema-driven Configuration Studio (gui_refresh task 06 Waves 4d/4e)

The EDITING extension of the read-only ConfigBrowser (Wave 3b), served at
`#/studio` (v2-only route, `guiV2` gated; the legacy `#/settings` page stays
untouched and fully functional in parallel).

Sources of truth (plans 05/06):

- `GET /api/v1/config/schema` — the canonical field registry drives every
  control; nothing here hardcodes a field list.
- `GET/PATCH /api/v1/projects/default/config` — PROJECT scope, If-Match
  optimistic concurrency (409 → reload banner; 400 → ValidationSummary with
  the server's per-path `details.errors`).
- `GET/POST/PATCH /api/v1/run-templates[...]` and `/api/v1/run-drafts[...]`
  — TEMPLATE / DRAFT scope via `#/studio?template=<id>` / `#/studio?draft=<id>`.
- `GET /api/v1/secrets/status` + `PUT /api/v1/secrets/{secret_id}` —
  `SecretField.tsx`: readiness display + write-only assignment (ADR-05);
  a secret value can never be rendered (the response DTO has no value field).
- `GET /api/v1/config/catalogs/models` — server-side provider/model catalog
  (no frontend model constants; also supplies the per-provider env-key the
  SecretField preselects).

Control generation from metadata (plan 06 §Schema-driven rendering):
enum → select, bool → switch, int/float → number input, str → text input,
secret_reference → SecretField, composite types → disabled with a reason.

Launch flow (Wave 4e — `LaunchPanel.tsx`, plan 06 §Launch protocol, backend
MN-10), DRAFT scope only:

- drafts carry an optional create-time `goal` (materialized as
  `{ckpt}/experiment.md` by the launch);
- `POST /run-drafts/{id}/resolve-config` + `/validate` → effective-config
  diff vs defaults (ConfigBrowser badge maps/table shape), draft validation
  errors (shared ValidationSummary), resolver warnings, secret readiness
  rows (status hook — never values), locked-governance note;
- immutable review summary (display name, server-issued run_id note,
  profile, RESOLVED execution/paper mode, changed-fields count, digest)
  behind an explicit confirm checkbox — checking it mints ONE idempotency
  key per approval;
- `POST /api/v1/runs` with that key (double-click/retry replay the same
  key → one spawn), then the canonical `#/overview?run=<run_id>` redirect
  from the SERVER-issued run_id — never mtime/latest-checkpoint polling;
- failures render the typed envelope (message + request_id + per-path
  `details.errors`, incl. `missing_goal` / `mode_locked` /
  `mode_interlock_mismatch`).

Mode selection (ADR-09, accepted by the program 2026-07-27 — supersedes the
"no CLI flag / no GUI toggle" statement in `docs/guides/execution_modes.md`
for the NEW-RUN case). `ExecutionSection.tsx` replaces the former locked
governance group with exactly TWO controls, one per orthogonal intent:

- **Execution mode** — `ari.mode` ∈ {`simple_bfts` (default), `ari_rqgm`}
  written together with its interlock `rqgm.enabled`;
- **Paper mode** — `paper.mode` ∈ {`linear` (default), `rqgm_archive`}
  written together with its interlock `rqgm.paper.enabled`.

Invariants this surface must keep:

- ONE control writes BOTH keys of its pair, and the Studio save carries them
  in a SINGLE PATCH — the GUI can never produce the half-set document the
  backend rejects (`mode_interlock_mismatch`). The pair constants live in
  `modeIntents.ts`, the mirror of `field_registry.MODE_INTERLOCK_PAIRS`.
- NEW-RUN ONLY; resume is unaffected (the persisted
  `{ckpt}/rqgm_state.json` mode continues to win, downgrade-only).
- PROJECT scope still refuses the run-scoped mode paths
  (`not_project_scope`): the controls are disabled there with the reason.
- Re-selecting the stored value clears the pending pair, so the DEFAULT
  selection (`simple_bfts` + `linear`) writes nothing and the launched run
  stays byte-identical to today.
- The other ~96 `rqgm.*` tuning leaves stay READ-ONLY (collapsed group,
  effective values visible) and are rendered by the SHARED
  `ConfigBrowser/ConfigReadOnlyTable.tsx` — no second row renderer, no
  editable control inside that group. Selecting a mode is not governance
  mutation: the GUI's RQGM registry/transition surfaces remain read-only.
- The launch review displays the RESOLVED mode from the resolve-config
  manifest, never the raw selection; a resolver fallback renders
  `requested → resolved` plus the warning verbatim, and a paired-intent
  validation error blocks the launch with its typed message.

## Contents

- `README.md` — this file.
- `ConfigStudioPage.tsx` — schema-driven form over project/template/draft scopes.
- `ExecutionSection.tsx` — ADR-09 execution/paper mode selection + the read-only `rqgm.*` tree.
- `index.ts` — barrel re-exports.
- `LaunchPanel.tsx` — draft launch flow (resolve/validate → immutable review → idempotent launch).
- `modeIntents.ts` — the two ADR-09 mode intent pairs (frontend mirror of `field_registry.MODE_INTERLOCK_PAIRS`) + leaf readers.
- `SecretField.tsx` — write-only secret assignment + readiness display.
- `StudioPickers.tsx` — template select/create + draft create (incl. goal) controls.
- `ValidationSummary.tsx` — per-path `details.errors` renderer.
- `__tests__/` — component tests for this directory.
  - `README.md` — __tests__ index.
  - `ConfigStudioExecutionMode.test.tsx` — tests for `ExecutionSection.tsx` + the ADR-09 launch-review wiring (mode selection accepted 2026-07-27): one control writes BOTH pair keys in a single PATCH, the two intents are orthogonal, all four combinations render and round-trip, re-selecting the stored value writes nothing (default path byte-identical), an inconsistent stored pair is flagged, the `rqgm.*` tree renders values with no editable control, the launch review shows the RESOLVED mode (requested→resolved + resolver warning on a fallback), and `mode_interlock_mismatch` blocks the launch with its typed message.
  - `ConfigStudioLaunch.test.tsx` — tests for the `LaunchPanel.tsx` launch flow (gui_refresh task 06 Wave 4e, plan 06 §Launch protocol / backend MN-10): resolve→validate→review→launch happy path with the canonical `#/overview?run=<run_id>` redirect from the server-issued run_id, validation failure (`mode_locked`) blocking the POST, double-click single-POST + same-idempotency-key retry, typed error envelope rendering (request_id + per-path `details.errors`).
  - `ConfigStudioPage.test.tsx` — tests for `ConfigStudioPage.tsx` (gui_refresh task 06 Wave 4d): schema-driven control generation, If-Match PATCH + 409 reload banner + per-path 400 ValidationSummary, write-only secret flow, the ADR-09 Execution section refused in PROJECT scope.
