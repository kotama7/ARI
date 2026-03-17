# ari-skill-hpc Requirements

## Overview

MCP Server for HPC environment operations (SLURM / Singularity).
Provides tools for ARI agents to submit jobs, monitor status, and manage containers.

## Design

- **Deterministic**: All tools are pure functions with no LLM calls
- **Partition validation**: Rejects invalid SLURM partitions
- **Account stripping**: `--account` / `-A` headers silently ignored (cluster-specific; check your scheduler)
- **Empty job_id guard**: Returns ERROR immediately for empty job IDs

## Tech Stack

- Python 3.11+
- FastMCP
- subprocess (SLURM CLI: sbatch, squeue, sacct)

## Tool Specifications

### slurm_submit(script: str, partition: str = "", account: str = "") -> dict
Submits a SLURM batch script. Returns `{"job_id": "12345"}` on success.

### job_status(job_id: str) -> dict
Returns `{"status": "COMPLETED", "stdout": "..."}` when done.

### run_bash(command: str) -> dict
Executes a read-only bash command (e.g., `cat output.txt`).

### singularity_run(image: str, command: str, gpu: bool = False) -> dict
Runs a Singularity container. Adds `--nv` flag when `gpu=True`.
