# ari-skill-hpc

MCP skill for SLURM and Singularity HPC operations.
Provides tools for ARI agents to submit, monitor, and manage HPC jobs.

**Design Principle P2 compliant: No LLM calls. Fully deterministic.**

## Tools

| Tool | Description |
|---|---|
| `slurm_submit` | Submit a SLURM batch script and return job_id |
| `job_status` | Poll job status (PENDING / RUNNING / COMPLETED / FAILED) |
| `run_bash` | Read SLURM output file or run a short bash command |
| `singularity_run` | Run a Singularity container with optional GPU access |

## Tests

```bash
pytest tests/ -q
# 27 passed
```
