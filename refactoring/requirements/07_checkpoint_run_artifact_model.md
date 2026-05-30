# Requirement: Checkpoint / Run / Artifact Model

## 1. Purpose

- Clarify the concepts: project, run, checkpoint, node, artifact, log, file,
  and result.
- Align these concepts across CLI, core, viz backend, and frontend.
- Preserve existing checkpoint compatibility.

## 2. Current Problem

Checkpoint/run/node/artifact concepts are handled in several places
(`checkpoint.py`, `paths.py`, the viz `checkpoint_*` modules, `file_api.py`,
`node_work_api.py`, `orchestrator/node*`, and frontend types) with ad-hoc
filesystem assumptions. The shared mutable `ari.viz.state` ties the "active
checkpoint" to global state (`_checkpoint_dir`, `_settings_path` rebind via
`set_active_checkpoint`), which spreads the model implicitly.

## 3. Scope

### In Scope

- Documenting the current data model and its filesystem layout assumptions.
- Identifying ad-hoc filesystem assumptions duplicated across modules.
- Introducing compatibility-safe model helpers **only if justified**.

### Out of Scope

- Migrating or rewriting existing checkpoint files (requires a separate
  migration plan — see `GLOBAL_RULES.md`).
- Changing checkpoint on-disk format.
- Expanding `ari.viz.state`.

## 4. Files to Inspect First

```text
ari-core/ari/checkpoint.py
ari-core/ari/paths.py
ari-core/ari/pidfile.py
ari-core/ari/viz/checkpoint_api.py
ari-core/ari/viz/checkpoint_finder.py
ari-core/ari/viz/checkpoint_lifecycle.py
ari-core/ari/viz/file_api.py
ari-core/ari/viz/node_work_api.py
ari-core/ari/orchestrator/node.py
ari-core/ari/orchestrator/node_report/
ari-core/ari/viz/frontend/src/types/index.ts
```

`ari.paths.PathManager` (used by `state.set_active_checkpoint` →
`project_settings_path`) is the existing path-resolution authority — treat it
as the canonical layout source. `orchestrator/node_report/` contains
`builder.py` and `legacy_reconstruct.py`, indicating an existing legacy-format
concern to respect.

## 5. Expected Changes

- Document the current data model (a concept glossary + how each concept maps to
  the filesystem and to API/types).
- Identify ad-hoc filesystem assumptions.
- Introduce compatibility-safe model helpers only if justified (e.g. a single
  place that resolves checkpoint/run/artifact paths, wrapping `PathManager`).
- Do **not** migrate existing checkpoint files without a separate migration plan.

## 6. Step-by-Step Execution Plan

1. Build a glossary: define project, run, checkpoint, node, artifact, log,
   file, result, and how they relate.
2. For each viz module touching the filesystem, record the path assumptions it
   encodes.
3. Compare with `paths.py` / `PathManager`; flag duplicated or divergent
   assumptions.
4. Align frontend `types/index.ts` naming with the glossary (additive,
   non-breaking).
5. If duplication is significant and low-risk to fix, introduce a single helper
   used by the duplicators — behind the existing format, no on-disk change.
6. Run section 8 checks.

## 7. Compatibility Requirements

- Existing checkpoint files load and render unchanged.
- Legacy reconstruction (`node_report/legacy_reconstruct.py`) keeps working.
- No on-disk format change; helpers must read the same layout as today.

## 8. Tests and Smoke Checks

```bash
pytest ari-core/tests -q
```

If checkpoint fixtures exist, run the tests that load real/legacy checkpoints.
On a real environment, confirm an existing checkpoint still opens in the
dashboard (`ari viz` / `./start.sh gui`). Document unavailable dependencies.

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

- The model is partly encoded in on-disk layout; any helper must match it
  exactly, including legacy variants. Verify against real checkpoints, not just
  unit fixtures.
- The "active checkpoint" lives in global mutable state; documenting it is safe,
  but refactoring it is high-risk and may belong in a dedicated requirement.

## 12. Follow-up Candidates

- A dedicated, separately planned checkpoint migration (if format ever changes).
- Reducing `ari.viz.state` global coupling for the active checkpoint.
