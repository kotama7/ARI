---
sources:
  - path: ari-skill-paper-re/src/server.py
    role: implementation
last_verified: 2026-05-25
---

# Multi-node setup for PaperBench

ARI ships single-node sandbox dispatch out of the box (local /
apptainer / docker). Multi-node MPI reproduction adds three site
prerequisites:

1. **SLURM with `sbatch` on PATH.**
2. **GRES (generic resources) configured** when the rubric requests a
   `gpu_type`. Verify with `sinfo -o '%G'`; "(null)" means no GRES.
3. **Shared filesystem** (NFS / Lustre / GPFS) mounted at the same path
   on every allocated node. ARI warns when `repo_dir` looks node-local.

## Verifying your site

```bash
# 1. sbatch present?
which sbatch && echo OK

# 2. GRES configured?
sinfo -h -o '%G' | head    # expect: gpu:v100:4 or similar; "(null)" = no GRES

# 3. Shared FS — does $HOME live on a real share?
df -hT $HOME               # look for nfs / lustre / nfs4 / fuse.lustre

# 4. MPI available?
which srun mpirun          # srun is preferred (PMI/PMIx integration)
module avail openmpi 2>&1 | head
```

ARI's safety probes:
- `_is_shared_fs()` warns if the checkpoint directory is under
  `/tmp`, `/var/tmp`, or any other non-shared root.
- `_slurm_has_gres()` silently drops `--gres=gpu:<type>:N` when `sinfo`
  reports no GRES, keeping `--gpus-per-task` so the submission is not
  rejected outright.

## Picking the right partition

The `ari-skill-paper-re` server resolves the SLURM partition in this
order: explicit caller arg → `ARI_SLURM_PARTITION` env → checkpoint
`launch_config.json`. Leaving any of these set switches the wizard's
default partition.

```bash
export ARI_SLURM_PARTITION=large
```

## Example: sx40 (single-node, 4×V100)

`sx40` is a CRA partition exposing `4× V100-SXM2-16GB` per node without
GRES configured. Use:

```jsonc
"execution_profile": {
  "kind": "gpu_single",
  "paper_max_ranks": 1,
  "requested_gpus_per_task": 1
  // gpu_type omitted — GRES-less; sinfo probe is enforced
}
```

## Example: R-CCS Cloud (Web UI, manual)

R-CCS Cloud Jupyter exposes a SLURM allocation through a web
notebook. ARI runs cannot `sbatch` directly from inside the notebook —
instead:

1. From the notebook, `python -m ari.viz.server --host 0.0.0.0`.
2. From a separate terminal session (inside the same allocation), run
   `ari run experiment.md`. Hand the experiment a checkpoint dir on
   shared `/work/...`.
3. The wizard's *Reproduce* step should set
   `sandbox_kind=slurm` and `nodes=<allocation>`.

## Module loads

When the rubric carries `module_loads: ["cuda/12.4","openmpi/4.1"]`,
the agent is instructed to emit a `module load cuda/12.4 openmpi/4.1`
line at the top of `reproduce.sh`. ARI does not validate the module
names — your cluster's `module avail` is authoritative.

## Failure modes & recovery

| Symptom | Cause | Fix |
|---|---|---|
| `sbatch: error: Invalid GRES gpu:v100:1` | no GRES configured | leave `gpu_type` empty; rely on `--gpus-per-task` only |
| `mpirun: command not found` on compute node | OpenMPI not loaded | add `"openmpi/4.1"` (or your cluster's name) to `module_loads`, OR rely on `srun` (the agent prompt prefers it) |
| All ranks land on node 1 | reproduce.sh ran without `srun` | the agent prompt's "MULTI-NODE FAN-OUT" block instructs `srun -N $SLURM_JOB_NUM_NODES -n $SLURM_NTASKS`; verify it landed in the generated reproduce.sh |
| `Permission denied` opening files on rank > 0 | `repo_dir` was on `/tmp` | move the checkpoint to `$HOME` or `/work/...`; see the shared-FS warning in the run log |

## See also

- [Execution profile reference](../../reference/execution_profile.md)
- [Compute-node safety conventions](compute_node_safety.md)
- [`hpc_setup.md`](../hpc_setup.md) for the underlying ARI HPC
  configuration.
