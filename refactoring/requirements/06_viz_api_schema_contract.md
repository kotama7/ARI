# Requirement: Viz API Schema Contract

## 1. Purpose

- Make dashboard API request/response contracts explicit.
- Align backend responses and frontend TypeScript types.
- Reduce ad-hoc dict/object drift between backend and frontend.
- Avoid breaking existing endpoints.

## 2. Current Problem

Backend handlers return ad-hoc dicts, and the frontend mirrors them with
hand-written types (and some `any`). There is no enforced contract, so the two
sides drift. `docs/reference/rest_api.md` documents endpoints but is not a
machine-checked schema.

## 3. Scope

### In Scope

- Documenting/defining schemas for **stable** endpoints.
- Improving frontend types for common responses.
- Keeping old response fields during migration.

### Out of Scope

- A large schema-framework migration (e.g. full pydantic/OpenAPI rollout)
  unless separately justified.
- Endpoint path/behavior changes.
- Backend route extraction (that is `05`).

## 4. Files to Inspect First

```text
ari-core/ari/viz/api_*.py
ari-core/ari/viz/checkpoint_*.py
ari-core/ari/viz/file_api.py
ari-core/ari/viz/node_work_api.py
ari-core/ari/viz/frontend/src/types/index.ts
ari-core/ari/viz/frontend/src/services/api.ts
docs/reference/rest_api.md
```

`docs/reference/rest_api.md` carries front-matter listing `routes.py`,
`api_paperbench.py`, and `api_experiment.py` as implementation sources and a
`last_verified` date — keep it in sync when contracts are formalized.

## 5. Expected Changes

- Define or document schemas for stable endpoints.
- Improve frontend types for common responses.
- Avoid a large schema framework migration unless separately justified.
- Preserve old response fields during migration.

## 6. Step-by-Step Execution Plan

1. Pick the highest-traffic, most stable endpoints first (state, settings,
   experiment, checkpoint listing).
2. For each, capture the actual response shape from the backend code.
3. Write/strengthen the matching TypeScript type in `types/index.ts` and use it
   in `services/api.ts`.
4. Decide the backend documentation form: docstring + `rest_api.md` entry, or a
   lightweight typed dict / dataclass — without changing the wire format.
5. When adding new fields, keep old fields present (additive only).
6. Update `docs/reference/rest_api.md` and its `last_verified` date.
7. Run section 8 checks.

## 7. Compatibility Requirements

- Wire format stays additive: existing fields remain; new fields are optional
  from the consumer's perspective during migration.
- No endpoint path/method/status changes.
- Frontend type changes must keep all call sites compiling.

## 8. Tests and Smoke Checks

```bash
pytest ari-core/tests -q
cd ari-core/ari/viz/frontend && npm run typecheck
cd ari-core/ari/viz/frontend && npm run build
```

If a contract test harness exists or is added, run it. Document unavailable
dependencies.

## 9. Completion Criteria

The requirement is complete only when:

- all scoped changes are implemented
- existing behavior is preserved
- tests or smoke checks pass
- risks are documented
- follow-up work is moved to another requirement file
- completion is recorded in `refactoring/COMPLETED.md`
- this requirement file is deleted in the same PR

## 10. Deletion Rule

This file must remain in `refactoring/requirements/` while the requirement is
incomplete.

When all completion criteria are satisfied, record the completion in
`refactoring/COMPLETED.md`, then delete this file in the same PR.

Do not delete this file for partial completion.

## 11. Risks

- Formalizing a schema can accidentally tighten it (e.g. forbidding extra
  fields), breaking compatibility. Keep contracts permissive during migration.
- Frontend types that were loose (`any`) may have hidden mismatches with the
  real backend shape; reconcile to the backend's actual output, not the
  assumed one.

## 12. Follow-up Candidates

- A future, separately justified move to generated types / OpenAPI.
- Endpoints intentionally left undocumented because they are unstable —
  record them as such.
