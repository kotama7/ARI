# ari.cli

CLI entry point — a thin wrapper with zero domain knowledge; all
construction logic is delegated to `ari.core`.

## Contents

- `README.md` — this file.
- `__init__.py` — Typer app entry point.
- `__main__.py` — `python -m ari.cli` entry.
- `bfts_loop.py` — BFTS run-loop driver + checkpoint persistence.
- `commands.py` — misc top-level commands + `_safe_backup`.
- `lineage.py` — end-of-phase lineage-decision helpers.
- `migrate.py` — `ari migrate` sub-app.
- `Plan.md` — G5 copy / G7 sterile / G12 timeout・overflow の実装計画（handoff study）.
- `projects.py` — `ari paper` / `status` / `projects` / `show` commands.
- `run.py` — `ari run` / `ari resume` commands.

## See also

- **Command surface** → `docs/reference/cli_reference.md`.
- **Per-command details** → the `__init__.py` module docstring + each `*.py` here.
