# ari-skill-hpc/tests

Pytest suite for the HPC skill (SLURM + Singularity).

## Contents

- `README.md` — this file.
- `conftest.py` — shared fixtures.
- `test_capability_probe.py` — deterministic platform-capability probe: `_parse_capability_output` parsing, `probe_platform_capabilities` cache short-circuit, and graceful skip paths (no partition / `srun` absent).
- `test_singularity.py` — Singularity build/run.
- `test_slurm_local.py` — SLURM submit/status/cancel in local mode.
- `test_slurm_remote.py` — SLURM submit/status/cancel in SSH-remote mode.
