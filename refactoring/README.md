# ARI Refactoring Task-Control System

This directory is a **temporary refactoring task-control system** for the
`kotama7/ARI` repository. It is **not** final architecture documentation.

The files here exist to drive a sequence of small, reviewable refactoring PRs.
Once a requirement is fully implemented, tested, recorded, and reviewed, its
requirement file is **deleted**. The presence of a file under
`requirements/` therefore means the work it describes is **not yet done**.

## What this directory is (and is not)

- It **is** a set of task-control documents: each `requirements/NN_*.md` file
  describes one bounded refactoring step, its scope, its checks, and its
  completion criteria.
- It **is not** the system's architecture reference. Long-lived design docs
  live under `docs/` and per-directory `README.md` files. When a refactor
  produces durable architecture knowledge, fold that knowledge into `docs/`
  or the relevant `README.md`, **not** into this directory.
- It **is not** a place for partial credit. A requirement file stays until the
  whole requirement is finished.

## Why the initial planning PR must not change production code

The first PR (the one that creates this directory) **only** adds planning and
requirement documents. It does **not**:

- refactor production code,
- move source files,
- rename modules,
- change package configuration,
- change launch scripts (`start.sh`, `shutdown.sh`, `setup.sh`).

Reasons:

1. The plan must be reviewable on its own. Mixing a large plan with code
   changes makes both harder to review.
2. The assessment requirements (`00`, `01`, `13`) must be executed against the
   repository **as it is today**, before anything moves, so the baseline is
   trustworthy.
3. ARI has live, behavior-sensitive surfaces (CLI, dashboard REST/WebSocket,
   checkpoints, workflows, skills). Locking the plan and the guard tests first
   reduces the risk of silent behavior drift.

## How to execute requirement files, one by one

1. Pick the next file according to the **Recommended execution order** below.
2. Read it fully, including `## 4. Files to Inspect First`.
3. Re-confirm the facts in the file against the current repository — the
   repository may have moved since the file was written.
4. Implement **only** that requirement's `In Scope` items. Do not opportunistically
   fix things that belong to another requirement; move them to that file's
   `## 12. Follow-up Candidates` instead.
5. Run the requirement's `## 8. Tests and Smoke Checks`.
6. If checks pass and the change is reviewed, follow `## 10. Deletion Rule`:
   record completion in `COMPLETED.md` and delete the requirement file **in the
   same PR**.
7. If checks cannot run (missing deps, no compute node, etc.), record the
   attempted commands and the failure reason in the PR and in `COMPLETED.md`;
   do **not** mark the requirement complete on a skipped check.

Keep each PR small. Do not mix unrelated requirements in one PR. Do not mix
pure file movement with behavior changes unless explicitly justified in the
requirement.

## Recommended execution order

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

`00`, `01`, and `13` are **assessment / guard** requirements: they primarily
produce notes and tests, and unblock everything after them. `14` is the
migration-policy requirement and is finished last.

The first **implementation** requirement after planning is
`02_frontend_api_client_consolidation.md`, because:

- `services/api.ts` already exists, so the boundary is already there to
  consolidate into,
- the work is localized to the frontend,
- it reduces GUI/API coupling,
- it requires no backend redesign,
- it prepares the ground for later component decomposition (`03`).

## How completion is recorded

Completion is recorded in [`COMPLETED.md`](./COMPLETED.md) using the template
in that file. Every completed requirement gets one entry summarizing what was
done, the PR/commit, the checks that ran, any follow-up moved elsewhere, and
the timestamp.

## When a requirement file may be deleted

A requirement file under `requirements/` may be deleted **only** when all of
the following are true (see `GLOBAL_RULES.md` and each file's section 9):

1. The requirement is fully implemented (no partial credit).
2. Existing behavior is preserved.
3. Required tests or smoke checks pass.
4. The implementation has been reviewed.
5. Any follow-up work has been moved into a new or existing requirement file.
6. Completion is recorded in `COMPLETED.md`.
7. The file is deleted in the **same PR** that records the completion.

## How remaining files represent incomplete work

The set of files under `requirements/` is the live to-do list. As long as a
file is present, its requirement is unfinished. When `requirements/` is empty,
the planned refactoring sequence is complete and this directory can itself be
removed in a final cleanup PR (recorded in `COMPLETED.md`).
