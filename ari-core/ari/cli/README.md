# ari.cli

CLI entry point — a thin wrapper with zero domain knowledge; all
construction logic is delegated to `ari.core`.

## Contents

- `README.md` — this file.
- `__init__.py` — Typer app entry point.
- `__main__.py` — `python -m ari.cli` entry.
- `bfts_loop.py` — BFTS run-loop driver + checkpoint persistence.
- `commands.py` — misc top-level commands + `_safe_backup`.
- `doctor.py` — TODO
- `harness.py` — TODO
- `kca.py` — command handlers for knowledge, capability, and assurance inspection and registration.
- `lineage.py` — end-of-phase lineage-decision helpers.
- `manuscript.py` — Manuscript Complete preparation, evaluation, publication, and repair commands.
- `manuscript_repair_runtime.py` — transactional auto-repair runtime used by the manuscript CLI.
- `migrate.py` — `ari migrate` sub-app.
- `paper_dispatch.py` — shared paper-axis dispatch behind `ari paper`/`run`/`resume`; resolves linear vs rqgm_archive, builds the agent-as-judge score fn, and runs the RQGM paper-candidate pre-flight (the exploration-axis escalation that can rewrite `_scientific_score`).
- `projects.py` — `ari paper` / `status` / `projects` / `show` commands.
- `run.py` — `ari run` / `ari resume` commands.

## See also

- **Command surface** → `docs/reference/cli_reference.md`.
- **Per-command details** → the `__init__.py` module docstring + each `*.py` here.
- `harness.py` — `ari harness list` prints what each registered harness declares it is for, including what it is blind to and whether its resolution band was ever measured; `ari harness select` ranks the pool against a requirement and exits 2 when nothing qualifies, because "no harness can answer this" is a result and running the closest one anyway produces a number rather than an answer.
