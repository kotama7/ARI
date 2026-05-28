# ari.migrations.v05_to_v07

v0.5 → v0.7 migration helpers: node-report reconstruction from legacy
`tree.json`, v0.5 memory JSONL import, and legacy 5-axis evaluator
fallback. Canonical modules delegate here via one-line shims.

## Contents

- `README.md` — this file.
- `__init__.py` — subsystem map + deprecation plan.
- `legacy_axes.py` — legacy 5-axis evaluator-score fallback.
- `memory.py` — v0.5 JSONL → v0.6 Letta migration shim.
- `node_reports.py` — `node_report.json` reconstruction from legacy `tree.json`.

## See also

- **Subsystems & deprecation plan** → the `__init__.py` module docstring (authoritative).
- **`ari migrate` usage** → `docs/guides/migration.md`.
