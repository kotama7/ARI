# Requirement: Migration and Requirement Deletion

## 1. Purpose

- Define the execution order for the refactoring sequence.
- Define the requirement-file deletion policy.
- Define the compatibility-wrapper removal policy.
- Define when larger package movement (e.g. top-level `ari-gui` / `ari-api`)
  may be considered.

This requirement is finished **last**; it governs the lifecycle of all the
others.

## 2. Current Problem

Without a written migration and deletion policy, requirement files could be
deleted prematurely, compatibility wrappers could be removed too early, or a
large directory move could happen before its risk is assessed.

## 3. Scope

### In Scope

- Recording the execution order, deletion policy, wrapper-removal policy, and
  package-move policy as the authoritative reference.
- Confirming the policies are consistent with `README.md` and `GLOBAL_RULES.md`.

### Out of Scope

- Performing any package move.
- Deleting other requirement files (each is deleted by its own completion PR).

## 4. Files to Inspect First

```text
refactoring/README.md
refactoring/GLOBAL_RULES.md
refactoring/COMPLETED.md
refactoring/requirements/
```

## 5. Expected Changes

This requirement specifies policy (and is itself deleted when the policy is
settled and recorded). It must specify:

- requirement files are temporary task-control files
- completed requirements are recorded in `refactoring/COMPLETED.md`
- the completed requirement file is deleted in the **same PR** that records it
- partial completion must **not** delete the file
- large directory moves require prior assessment (`00`, `01`)
- `ari-core/ari/viz` and `ari-core/ari/viz/frontend` are refactored **in place**
  first
- top-level `ari-gui` or `ari-api` are **not** introduced until a later
  migration requirement proves the benefit and low risk

## 6. Step-by-Step Execution Plan

1. Confirm the recommended execution order (below) matches `README.md`.
2. Confirm the deletion policy matches `GLOBAL_RULES.md` and each requirement's
   section 9/10.
3. Define the compatibility-wrapper removal policy (see section 7).
4. Define the package-move gate (see section 7).
5. When the sequence completes (`requirements/` empty), record final cleanup of
   this directory in `COMPLETED.md`.

### Recommended execution order

```text
1.  00_repository_architecture_assessment.md
2.  01_dependency_and_boundary_graph.md
3.  13_testing_smoke_guards.md
4.  02_frontend_api_client_consolidation.md
5.  03_frontend_large_component_decomposition.md
6.  04_frontend_state_hooks_types_cleanup.md
7.  05_viz_routes_service_extraction.md
8.  06_viz_api_schema_contract.md
9.  07_checkpoint_run_artifact_model.md
10. 08_config_settings_workflow_unification.md
11. 09_core_skill_public_contract.md
12. 10_pipeline_workflow_phase_boundary.md
13. 11_llm_backend_boundary.md
14. 12_hpc_container_subprocess_boundary.md
15. 14_migration_and_requirement_deletion.md
```

## 7. Compatibility Requirements

**Compatibility-wrapper removal policy.** When a refactor introduces a
compatibility wrapper (re-export, shim, alias) to preserve an old import path or
endpoint:

- the wrapper stays until all known call sites are migrated;
- removing a wrapper is itself a behavior-sensitive change and requires its own
  requirement file (or an explicit, justified section in a later requirement),
  with its own checks;
- wrappers are never removed in the same PR that introduces them.

**Package-move gate.** A move such as `ari-core/ari/viz` →
top-level `ari-gui`/`ari-api`:

- is forbidden in early refactoring;
- may be proposed only after `00` and `01` are complete and the in-place
  refactors (`02`–`12`) have reduced the relevant coupling;
- requires a new, dedicated migration requirement that proves the move is
  low-risk and worth the compatibility cost, including a wrapper plan for old
  import paths and launch behavior (`start.sh`, `ari viz`).

## 8. Tests and Smoke Checks

- No production-code change here. Sanity check: the order/policy in this file
  matches `README.md` and `GLOBAL_RULES.md`, and every other requirement's
  section 9/10 is consistent with the deletion policy.

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

- Premature deletion of a requirement file loses task state; enforce the
  "same-PR record + delete" rule in review.
- Premature wrapper removal or package move can break import paths, launch
  scripts, or skill packages.

## 12. Follow-up Candidates

- A dedicated `ari-gui` / `ari-api` migration requirement (only if justified
  after the in-place refactors).
- Final cleanup PR that removes the `refactoring/` directory once
  `requirements/` is empty.
