# ari-skill-hpc

MCP skill for SLURM and Singularity HPC operations.  Provides tools
for ARI agents to submit, monitor, and manage HPC jobs.  Local
(direct) and SSH-based remote-cluster modes are both supported.

**Design Principle P2 compliant: no LLM calls; fully deterministic.**

## Tools

| Tool | Description |
|---|---|
| `slurm_submit` | Submit a SLURM batch script and return `job_id` |
| `job_status` | Poll job status (`PENDING` / `RUNNING` / `COMPLETED` / `FAILED`) |
| `job_cancel` | `scancel` a running job |
| `run_bash` | Read SLURM output file or run a short bash command |
| `singularity_build` | Build a SIF from a definition file |
| `singularity_run` | Run a SIF with optional GPU access |
| `singularity_pull` | Pull a SIF from a remote URI |
| `singularity_build_fakeroot` | Fakeroot build (no privileged daemon) |
| `singularity_run_gpu` | GPU variant with `--gres=gpu:N` and bind paths |

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `SLURM_MODE` | `local` (direct) / `ssh` (remote cluster) | `local` |
| `SLURM_SSH_HOST` | SSH host for remote SLURM mode | (none — required for `ssh` mode) |
| `SLURM_SSH_USER` | SSH user | current user |
| `SLURM_SSH_PORT` | SSH port | `22` |
| `SLURM_SSH_KEY` | SSH private key path | `~/.ssh/id_rsa` |

(`SLURM_DEFAULT_PARTITION`, `ARI_SLURM_*` etc. are honoured by the
 ARI core; see `docs/reference/environment_variables.md` for the
 full list.)

## Remote (SSH) mode example

```bash
export SLURM_MODE=ssh
export SLURM_SSH_HOST=cluster.example.org
export SLURM_SSH_USER=research
python -m ari_skill_hpc.server
```

## Dependencies

- `mcp >= 1.0`
- `pydantic >= 2.0`
- `paramiko >= 3.0` (only when `SLURM_MODE=ssh`)

## Tests

```bash
pytest tests/ -q                          # all
pytest tests/test_slurm_local.py          # local only (no SLURM cluster needed)
pytest tests/test_slurm_remote.py         # SSH-required
```

## See also

- [`docs/hpc_setup.md`](../docs/hpc_setup.md) — full cluster setup
- [`ari-skill-coding`](../ari-skill-coding/README.md) — host-side
  Singularity wrapping for user code
- `docs/reference/mcp_tools.md` — argument signatures.
