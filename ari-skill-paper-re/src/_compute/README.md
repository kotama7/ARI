# ari-skill-paper-re/src/_compute

Concrete `ComputerInterface` implementations that run Phase 1 reproduction on
ari's HPC / local sandbox stack (Slurm / Apptainer / local) instead of
PaperBench upstream's Docker-based `alcatraz`.

## Contents

- `README.md` — this file.
- `__init__.py` — public surface (`LocalComputer`, `ApptainerComputer`, `make_computer`); module docstring is authoritative.
- `computer.py` — the computer implementations.
- `local_pbtask.py` — local PaperBench task wiring.
