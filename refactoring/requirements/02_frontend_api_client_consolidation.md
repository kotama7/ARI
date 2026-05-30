# Requirement: Frontend API Client Consolidation

## 1. Purpose

- Consolidate frontend REST calls into the **existing** `services/api.ts`.
- Do **not** create a new API client from scratch.
- Reduce direct `fetch` usage inside components.
- Preserve upload/streaming exceptions only where genuinely justified.
- Improve weakly typed `any` payloads where low-risk.

This is the **first implementation requirement** after planning: the boundary
already exists, the work is localized, and it reduces GUI/API coupling without
backend redesign.

## 2. Current Problem

`services/api.ts` already exists (~764 lines) and is the intended API boundary,
but several components still issue raw `fetch` calls. Confirmed occurrences
(counts are direct `fetch(` matches, excluding `services/api.ts`):

```text
components/PaperBench/results/ResultsView.tsx     4
components/PaperBench/PaperImportDialog.tsx       3
components/PaperBench/PaperBenchWizard.tsx        3
components/Tree/FileExplorer.tsx                  2
components/PaperBench/PaperRegistryPage.tsx       2
components/Results/ResultsPage.tsx                1
components/Monitor/MonitorPage.tsx                1
```

This couples components to endpoint URLs and response shapes, duplicates
error handling, and bypasses the typed boundary.

## 3. Scope

### In Scope

- Moving component-level raw REST calls into `services/api.ts`.
- Adding explicit request/response types to the moved functions where reasonable.
- Documenting any remaining direct `fetch` as a justified exception.

### Out of Scope

- Any backend endpoint change (paths, methods, payloads stay identical).
- Visual redesign or styling changes.
- Component decomposition (that is `03`).
- Reworking `websocket.ts` streaming (only document streaming exceptions here).

## 4. Files to Inspect First

```text
ari-core/ari/viz/frontend/src/services/api.ts
ari-core/ari/viz/frontend/src/services/websocket.ts
ari-core/ari/viz/frontend/src/hooks/useApi.ts
ari-core/ari/viz/frontend/src/hooks/useWebSocket.ts
ari-core/ari/viz/frontend/src/context/AppContext.tsx
ari-core/ari/viz/frontend/src/components/
```

Known direct-fetch areas to audit (from the grep above and the original plan):

```text
ari-core/ari/viz/frontend/src/components/Monitor/MonitorPage.tsx
ari-core/ari/viz/frontend/src/components/PaperBench/PaperBenchWizard.tsx
ari-core/ari/viz/frontend/src/components/PaperBench/PaperImportDialog.tsx
ari-core/ari/viz/frontend/src/components/PaperBench/PaperRegistryPage.tsx
ari-core/ari/viz/frontend/src/components/PaperBench/results/ResultsView.tsx
ari-core/ari/viz/frontend/src/components/Results/ResultsPage.tsx
ari-core/ari/viz/frontend/src/components/Tree/FileExplorer.tsx
```

## 5. Expected Changes

- Component-level raw REST calls are moved to `services/api.ts`.
- Remaining direct `fetch` calls are documented as justified exceptions
  (e.g. multipart upload, server-sent streaming, blob download).
- API functions have explicit request/response types where reasonable; reduce
  `any` where low-risk.
- No visual redesign.
- No backend endpoint changes.

## 6. Step-by-Step Execution Plan

1. Inventory every `fetch(` outside `services/api.ts` (re-run the grep — the
   set may have changed).
2. For each call, identify the endpoint, method, request body, and the shape
   the component expects back.
3. Add or reuse a function in `services/api.ts` with explicit types.
4. Replace the component's raw `fetch` with the typed function; keep the
   component's existing loading/error behavior identical.
5. For upload/streaming cases that cannot reasonably move, leave them but add a
   short code comment marking them as justified exceptions, and list them in
   the PR.
6. Run the checks in section 8.

## 7. Compatibility Requirements

- Endpoint paths, methods, and payloads are unchanged.
- Component-visible behavior (loading states, error messages, rendered data)
  is unchanged.
- `services/api.ts` keeps its existing exports; add, don't rename/remove.

## 8. Tests and Smoke Checks

```bash
cd ari-core/ari/viz/frontend
npm run typecheck
npm run build
npm test -- --run
```

If dependencies are unavailable, document the attempted commands and the
failure reason in the PR and `COMPLETED.md`. Do not mark complete on skipped
checks.

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

- A moved call may subtly change error handling (e.g. `services/api.ts` may
  throw on non-2xx while the component previously read the raw response).
  Match the existing behavior exactly.
- Tightening `any` types can surface latent type errors at call sites; scope
  type improvements to low-risk payloads only.

## 12. Follow-up Candidates

- Stronger typing for endpoints left as `any` (route to `06`).
- Streaming/upload helper standardization in `websocket.ts` / a dedicated
  upload helper.
