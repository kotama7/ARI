# Refactoring Reports

This directory holds **generated** quality / measurement reports produced by the
refactoring subtasks — it is intentionally empty in the planning phase.

Planned outputs (created by later implementation sessions, **not** in this phase):

- `complexity_baseline.{md,json}` — empirical LOC / complexity / dependency census
  (subtask `001_measure_complexity_and_dependencies`).
- `reference_graph.{json,md}` and `dead_code_candidates.{json,md}` — reference-graph
  and dead-code analysis (subtasks `053`–`058`).
- `quality_report.{md,json}` — aggregated quality report
  (subtask `031_add_quality_report_generator`).
- `refactoring_progress.md` — progress tracker (subtask `035`).

See `../007_subtask_index.md` for the full subtask list and execution order, and
`../000_master_refactoring_plan.md` for the overall program. Nothing in this phase
modifies runtime code, public APIs, CLI/MCP/dashboard contracts, checkpoint formats,
prompts, GitHub workflows, the frontend, or directory names.
