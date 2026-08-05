# ari.cli

CLI entry point — a thin wrapper with zero domain knowledge; all
construction logic is delegated to `ari.core`.

## Contents

- `README.md` — this file.
- `__init__.py` — Typer app entry point.
- `__main__.py` — `python -m ari.cli` entry.
- `bfts_loop.py` — BFTS run-loop driver + checkpoint persistence.
- `commands.py` — misc top-level commands + `_safe_backup`.
- `doctor.py` — `ari doctor` sub-app: environment health checks (`ari doctor claude-code [--live]`).
- `harness.py` — TODO
- `lineage.py` — end-of-phase lineage-decision helpers.
- `migrate.py` — `ari migrate` sub-app.
- `projects.py` — `ari paper` / `status` / `projects` / `show` commands.
- `run.py` — `ari run` / `ari resume` commands.

## See also

- **Command surface** → `docs/reference/cli_reference.md`.
- **Per-command details** → the `__init__.py` module docstring + each `*.py` here.
- `harness.py` — `ari harness list` prints what each registered harness declares it is for, including what it is blind to and whether its resolution band was ever measured; `ari harness select` ranks the pool against a requirement and exits 2 when nothing qualifies, because "no harness can answer this" is a result and running the closest one anyway produces a number rather than an answer.
