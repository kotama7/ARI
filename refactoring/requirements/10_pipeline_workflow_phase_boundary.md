# Requirement: Pipeline / Workflow / Phase Boundary

## 1. Purpose

- Clarify the BFTS, ReAct, post-BFTS pipeline, paper generation, review,
  reproduction, PaperBench, and workflow phases.
- Avoid mixing orchestration with concrete side effects.
- Preserve existing workflow behavior.

## 2. Current Problem

Orchestration logic spans `pipeline/`, `agent/`, and `orchestrator/`, and is
surfaced through `viz/api_workflow.py` and the Workflow frontend. Phase
transitions, stage running, and concrete side effects (LLM calls, filesystem,
subprocess) may be interleaved, making phases hard to reason about and test.

## 3. Scope

### In Scope

- Documenting the current phase model and the boundaries between phases.
- Identifying where orchestration mixes with concrete side effects.
- Proposing interface improvements (phase/stage/plugin seams).

### Out of Scope

- A large pipeline rewrite.
- Changing workflow YAML semantics or phase outcomes.
- Changing skill behavior invoked by phases.

## 4. Files to Inspect First

```text
ari-core/ari/pipeline/
ari-core/ari/agent/react_driver.py
ari-core/ari/agent/tool_manager.py
ari-core/ari/orchestrator/bfts.py
ari-core/ari/viz/api_workflow.py
ari-core/ari/viz/frontend/src/components/Workflow/
ari-skill-paper/
ari-skill-replicate/
ari-skill-evaluator/
ari-skill-paper-re/
ari-skill-benchmark/
```

Confirmed structure: `pipeline/` has `orchestrator.py`, `stage_runner.py`,
`stage_control.py`, `context_builder.py`, `experiment_md.py`, `yaml_loader.py`;
`orchestrator/` has `bfts.py`, `node.py`, `node_selection.py`,
`lineage_decision.py`, `root_idea_selector.py`, `node_report/`; `agent/` has
`react_driver.py`, `tool_manager.py`, `loop.py`, `workflow.py`, `run_env.py`,
`shims/`. `WorkflowPage.tsx` (~1720 lines) is also a `03` decomposition target.

## 5. Expected Changes

- Document the current phase model.
- Identify phase/plugin boundaries.
- Propose interface improvements.
- Avoid a large pipeline rewrite.

## 6. Step-by-Step Execution Plan

1. Map the phase lifecycle from `pipeline/orchestrator.py` and
   `pipeline/stage_runner.py` / `stage_control.py`.
2. Identify where BFTS (`orchestrator/bfts.py`) and ReAct
   (`agent/react_driver.py`) plug into the pipeline.
3. Note where concrete side effects (LLM, subprocess, filesystem) are invoked
   directly inside orchestration vs. behind an interface.
4. Document how `viz/api_workflow.py` and the Workflow frontend observe/drive
   phases.
5. Propose seams (e.g. a phase interface, a stage-runner contract) that would
   let side effects be injected — without changing behavior yet.
6. Run section 8 checks.

## 7. Compatibility Requirements

- Workflow YAML semantics and phase ordering unchanged.
- BFTS concurrency behavior preserved — note: the PaperBench/BFTS loop commits
  concurrently in the same worktree, so any staging/commit-related code must
  keep finalizing stages promptly.
- `api_workflow.py` endpoints and the Workflow UI behavior unchanged.

## 8. Tests and Smoke Checks

```bash
pytest ari-core/tests -q
bash scripts/run_all_tests.sh
```

Workflow/pipeline behavior is environment-sensitive; verify representative
phase transitions on a real environment, not only with fakes. Document
unavailable dependencies.

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

- Phase transitions carry implicit state and ordering; refactoring seams can
  change timing in ways tests miss.
- Concurrent committers in the BFTS loop make worktree-touching changes
  especially risky.

## 12. Follow-up Candidates

- Implementing any proposed phase/stage interface (separate requirement).
- Coordinated decomposition of `WorkflowPage.tsx` with `03`.
