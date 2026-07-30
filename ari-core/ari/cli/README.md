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
- `paper_dispatch.py` — shared paper-axis dispatch behind `ari paper`/`run`/`resume`; resolves linear vs rqgm_archive, builds the agent-as-judge score fn, and runs the RQGM paper-candidate pre-flight (the exploration-axis escalation that can rewrite `_scientific_score`).
- `projects.py` — `ari paper` / `status` / `projects` / `show` commands.
- `run.py` — `ari run` / `ari resume` commands.

## See also

- **Command surface** → `docs/reference/cli_reference.md`.
- **Per-command details** → the `__init__.py` module docstring + each `*.py` here.
