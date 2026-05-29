# ari.migrations

Migration shims that keep checkpoints from older releases readable, so new
feature code stays free of v0.5/v0.6 branching. Sub-packages host the
branching; canonical modules ship thin re-export shims.

## Contents

- `README.md` — this file.
- `__init__.py` — rationale + layout.
- `v05_to_v07/` — v0.5 → v0.7 migration helpers.
  - `README.md` — v05_to_v07 index.
  - `__init__.py` — subsystem map + deprecation plan.
  - `legacy_axes.py` — legacy 5-axis evaluator-score fallback.
  - `memory.py` — v0.5 JSONL → v0.6 Letta migration shim.
  - `node_reports.py` — `node_report.json` reconstruction from legacy `tree.json`.

## See also

- **Rationale & layout** → the `__init__.py` module docstring (authoritative).
- **Upgrade guide** → `docs/guides/migration.md`.
