# Requirement: Viz Routes Service Extraction

## 1. Purpose

- Reduce the complexity of `ari-core/ari/viz/routes.py`.
- Keep HTTP dispatch compatibility (paths, methods, response shapes).
- Extract service functions from route handling where safe.
- Isolate state construction, phase detection, config-summary construction,
  static serving, access logging, and filesystem-heavy logic.

## 2. Current Problem

`routes.py` is the largest backend module (~1344 lines) and mixes request
dispatch, static serving, state construction, filesystem access, phase
detection, and response construction. It also leans on shared mutable
`ari.viz.state`. This concentrates risk and makes handlers hard to test.

## 3. Scope

### In Scope

- Extracting cohesive, side-effect-bounded logic out of route handlers into
  service functions (optionally under a new `ari-core/ari/viz/services/`
  package if justified).
- Making handlers thinner: parse request → call service → format response.

### Out of Scope

- Changing endpoint paths, methods, or response shapes.
- Changing dispatch order (unless a test proves equivalence).
- Expanding shared mutable state in `ari.viz.state`.
- Schema/contract work (that is `06`).
- Introducing top-level `ari-api`.

## 4. Files to Inspect First

```text
ari-core/ari/viz/routes.py
ari-core/ari/viz/server.py
ari-core/ari/viz/state.py
ari-core/ari/viz/state_sync.py
ari-core/ari/viz/api_state.py
ari-core/ari/viz/api_settings.py
ari-core/ari/viz/api_experiment.py
ari-core/ari/viz/api_workflow.py
ari-core/ari/viz/checkpoint_api.py
ari-core/ari/viz/checkpoint_finder.py
ari-core/ari/viz/checkpoint_lifecycle.py
ari-core/ari/viz/file_api.py
ari-core/ari/viz/node_work_api.py
```

Note: many `api_*.py` modules already exist (the dashboard is partly modularized
already — `api_experiment.py` ~882, `api_paperbench.py` ~813, `api_settings.py`
~547, `api_workflow.py` ~462 lines). Prefer routing extracted logic into the
existing `api_*` modules or new `services/` modules consistent with them,
rather than inventing a parallel structure.

## 5. Expected Changes

- Route handlers become thinner.
- Extracted service modules may be placed under `ari-core/ari/viz/services/`
  if justified.
- Endpoint paths and response shapes are preserved.
- Dispatch order is preserved unless a test proves equivalence.
- Shared mutable state is not expanded.

## 6. Step-by-Step Execution Plan

1. Catalog every route in `routes.py`: path, method, and what it does.
2. Group handler logic by concern: static serving, state construction, phase
   detection, config-summary construction, filesystem access, logging.
3. For one concern at a time, extract a pure-ish service function (explicit
   inputs/outputs; isolate side effects) and have the handler call it.
4. Keep the handler responsible only for request parsing and response
   formatting.
5. Where a concern already has a home (`api_*.py`, `checkpoint_*.py`,
   `file_api.py`, `node_work_api.py`), move logic there instead of duplicating.
6. Add/extend tests that pin endpoint behavior **before** moving logic.
7. Run section 8 checks.

## 7. Compatibility Requirements

- Every existing REST and WebSocket endpoint keeps its path, method, status
  codes, and response shape.
- Dispatch precedence (route matching order, fall-through to static serving)
  is preserved unless a test proves equivalence.
- `ari.viz.state` surface is not widened.

## 8. Tests and Smoke Checks

```bash
pytest ari-core/tests -q
python -m ari.viz.server --help
```

Verify the actual server entrypoint before relying on `python -m
ari.viz.server --help` — confirm against `server.py` and how `ari viz` /
`start.sh gui` launch it. If the command differs, document the correct smoke
check. Also confirm `./start.sh status` still reports correctly.

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

- Route dispatch order can carry hidden meaning (first-match wins, static
  fall-through). Reordering can change behavior silently — pin with tests first.
- Logic that reads/writes `ari.viz.state` may have ordering dependencies with
  `state_sync.py` and the WebSocket broadcast path.
- Extracting filesystem logic can change error handling for missing paths.

## 12. Follow-up Candidates

- Reducing reliance on `ari.viz.state` globals (coordinate with `07`).
- A `services/` package layout convention if many extractions accumulate.
