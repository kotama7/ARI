# ari-skill-hpc/tests

Pytest suite for the HPC skill (SLURM + Singularity).

## Contents

- `README.md` — this file.
- `conftest.py` — shared fixtures.
- `test_singularity.py` — Singularity build/run.
- `test_slurm_local.py` — SLURM submit/status/cancel in local mode.
- `test_slurm_remote.py` — SLURM submit/status/cancel in SSH-remote mode.
