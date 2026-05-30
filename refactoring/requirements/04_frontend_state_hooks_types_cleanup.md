# Requirement: Frontend State, Hooks, and Types Cleanup

## 1. Purpose

- Clarify frontend global state, hooks, and type boundaries.
- Audit `AppContext.tsx`.
- Reduce over-broad global state.
- Move server-state fetching to hooks/services where appropriate.
- Improve `types/index.ts` without breaking call sites.

## 2. Current Problem

Global UI state and server state may be mixed in `context/AppContext.tsx`, and
loading/error patterns may be duplicated across components. `types/index.ts`
(~199 lines) is shared widely, so type changes are risky and tend to be avoided,
encouraging `any`.

## 3. Scope

### In Scope

- Auditing `AppContext.tsx` and separating UI state from server state.
- Consolidating duplicated loading/error patterns into hooks.
- Safe improvements to shared types.

### Out of Scope

- Backend changes (unless separately justified).
- API consolidation (`02`) and component decomposition (`03`) — those should be
  done first so this requirement works on a cleaner base.
- Introducing a new state-management library.

## 4. Files to Inspect First

```text
ari-core/ari/viz/frontend/src/context/AppContext.tsx
ari-core/ari/viz/frontend/src/hooks/
ari-core/ari/viz/frontend/src/services/
ari-core/ari/viz/frontend/src/types/index.ts
ari-core/ari/viz/frontend/src/components/
```

Existing hooks include `useApi.ts` and `useWebSocket.ts`; reuse and extend
these rather than adding parallel mechanisms.

## 5. Expected Changes

- Clearer separation between UI state and server state.
- Fewer component-local duplicated loading/error patterns.
- Safer shared types.
- No backend changes unless separately justified.

## 6. Step-by-Step Execution Plan

1. Map what `AppContext.tsx` currently holds; classify each field as UI state
   (selection, view mode, theme, language) vs. server state (fetched data).
2. Move server-state fetching into hooks backed by `services/api.ts`.
3. Identify duplicated `loading`/`error`/`data` triples across components and
   extract a shared hook pattern (extend `useApi.ts` if suitable).
4. Tighten `types/index.ts` incrementally; for each change, update all call
   sites in the same PR and keep them compiling.
5. Run section 8 checks.

## 7. Compatibility Requirements

- User-visible behavior unchanged.
- Context consumers keep working (add fields/hooks rather than removing widely
  used ones in a single step; use deprecation comments if a field must go).
- No endpoint changes.

## 8. Tests and Smoke Checks

```bash
cd ari-core/ari/viz/frontend
npm run typecheck
npm run build
npm test -- --run
```

Document failures if dependencies are unavailable.

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

- `AppContext.tsx` is consumed broadly; moving fields can cause cascading
  re-renders or break consumers. Change in small steps.
- Server state moved into hooks can change fetch timing/caching; preserve the
  observable behavior.

## 12. Follow-up Candidates

- Consider a lightweight server-state cache (e.g. a query hook) only if a
  separate requirement justifies the dependency.
- Type alignment with backend schemas (coordinate with `06`).
