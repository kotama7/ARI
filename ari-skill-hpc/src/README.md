# ari-skill-hpc/src

MCP server package for the HPC skill — deterministic (P2) SLURM and
Singularity operations, in local (direct) or SSH remote-cluster mode.
`__init__.py` is empty; the package is imported as `src`.

## Contents

- `README.md` — this file.
- `__init__.py` — empty package marker.
- `server.py` — MCP entry point (`slurm_submit`, `job_status`, `job_cancel`, `run_bash`, `singularity_build`, `singularity_run`).
- `singularity.py` — Singularity image build + run (dispatched through SLURM).
- `slurm.py` — SLURM submit/status/cancel via local subprocess or remote SSH.

## See also

- The skill root `README.md` and the `server.py` module docstring for the tools & outward interface.
