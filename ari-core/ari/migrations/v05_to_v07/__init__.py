"""v0.5 → v0.7 migration helpers (Phase 5).

Three subsystems live here:

- :mod:`ari.migrations.v05_to_v07.node_reports` — best-effort
  reconstruction of ``node_report.json`` from the legacy tree.json
  dump (used by ``ari migrate node-reports``).
- :mod:`ari.migrations.v05_to_v07.memory` — re-export of the v0.5
  global-memory JSONL → checkpoint-scoped Letta auto-migration.
- :mod:`ari.migrations.v05_to_v07.legacy_axes` — legacy 5-axis fallback
  for evaluator scores written by older runs.

Original public callers continue to import from the canonical module
paths (``ari.orchestrator.node_report``, ``ari.memory.auto_migrate``,
``ari.evaluator.llm_evaluator``); those modules host one-line shims
that delegate to this package.  v1.0 will drop the shims and require
explicit ``ari migrate`` invocations.
"""
