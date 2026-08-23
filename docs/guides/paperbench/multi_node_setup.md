---
sources:
  - path: ari-skill-paper-re/src/server.py
    role: implementation
  - path: ari-skill-paper-re/src/prompts/replicator.md
    role: implementation
  - path: ari-skill-hpc/ari_skill_hpc/scheduler.py
    role: implementation
  - path: ari-core/ari/viz/server.py
    role: implementation
last_verified: 2026-08-16
---

# Multi-node setup for PaperBench

ARI ships single-node sandbox dispatch out of the box (local /
apptainer / docker). Multi-node MPI reproduction adds three site
prerequisites:

1. **SLURM with `sbatch` on PATH.**
2. **GRES (generic resources) configured** when the rubric requests a
   `gpu_type`. Verify with `sinfo -o '%G'`; "(null)" means no GRES.
3. **Shared filesystem** (NFS / Lustre / GPFS) mounted at the same path
   on every allocated node. Nothing in ARI checks this — there is no
   node-local warning for `repo_dir`. The only guard is advisory: the
   replicator prompt tells the agent that every path in `reproduce.sh`
   must resolve on every allocated node and to never use `/tmp` or
   `/var/tmp`.

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

ARI validates paths and typed resource syntax but cannot prove that a mount is
shared or that a partition can satisfy a request. Keep the workspace on a
compute-node-visible filesystem and inspect `sinfo` before launch. Resources
are submitted exactly and never silently dropped.

## Picking the right partition

The `ari-skill-paper-re` server resolves the SLURM partition in this
order: explicit caller arg → `ARI_SLURM_PARTITION` env →
`SLURM_PARTITION` env → `launch_config.json` (looked for beside
`repo_dir`, i.e. `{repo_dir}/../launch_config.json` then
`{repo_dir}/launch_config.json`). Leaving any of these set switches the
wizard's default partition. If none resolves, a `sandbox_kind=slurm`
reproduction fails with *"no partition could be resolved"* rather than
falling back.

`ARI_SLURM_PARTITION` does double duty: `sandbox_kind=auto` only
resolves to `slurm` when `sbatch` is on PATH **and**
`ARI_SLURM_PARTITION` is set. `SLURM_PARTITION` and `launch_config.json`
do not enable the `auto` path.

```bash
export ARI_SLURM_PARTITION=<your-partition>
```

## Example: anonymous no-GRES GPU partition

If a site exposes physical GPUs without configuring scheduler GRES, SLURM
cannot reserve them reliably. Select a GRES-enabled partition or ask the site
administrator to configure it; do not convert the request to CPU implicitly.

```jsonc
"execution_profile": {
  "kind": "gpu_single",
  "paper_max_ranks": 1,
  "requested_gpus_per_task": 1,
  "gpu_type": "v100"
}
```

`run_reproduce` reads `requested_gpus_per_task`, `requested_gpus_per_node`
and `gpu_type` from this block, but takes `--ntasks` from `min_ranks`,
not `paper_max_ranks` — the latter is a rubric-side scale statement the
agent reads, not a scheduler field. `gpu_type` with no count at all
becomes `--gres=gpu:<type>:1`.

## Example: notebook-fronted allocation (Web UI, manual)

Some sites expose a SLURM allocation through a hosted Jupyter notebook
rather than a login shell. ARI runs cannot `sbatch` directly from inside
the notebook — instead:

1. From the notebook, `ARI_GUI_BIND=0.0.0.0 python -m ari.viz.server`.
   There is no `--host` flag — the server takes only `--checkpoint` and
   `--port` (default `8765`) and binds loopback (`127.0.0.1` + `::1`)
   unless `ARI_GUI_BIND` says otherwise (`::` for a dual-stack
   wildcard).
2. From a separate terminal session (inside the same allocation), run
   `ari run experiment.md`. Hand the experiment a checkpoint dir on
   shared `/work/...`.
3. The wizard's *Reproduce* step should set the **Sandbox** select to
   `slurm` and `nodes` to the allocation's node count.

## Module loads

When the rubric carries `module_loads: ["cuda/12.4","openmpi/4.1"]`,
two independent things happen:

- The agent is instructed to emit a `module load cuda/12.4 openmpi/4.1`
  line at the top of `reproduce.sh`.
- For `sandbox_kind=slurm`, the list is also declared on the
  `JobRequestV1`, and the generated batch script sources the module
  init, runs **`module --force purge`**, then `module load`s each entry
  in order before the payload. The purge is the surprise: whatever the
  node (or your sbatch wrapper) had loaded is discarded first, so the
  declared list must be complete. A node with no module system at all
  exits `86` rather than running unmoduled.

ARI does not validate the module names — your cluster's `module avail`
is authoritative.

## Failure modes & recovery

| Symptom | Cause | Fix |
|---|---|---|
| `sbatch: error: Invalid GRES gpu:v100:1` | no GRES configured | leave `gpu_type` empty; rely on `--gpus-per-task` only |
| `mpirun: command not found` on compute node | OpenMPI not loaded | add `"openmpi/4.1"` (or your cluster's name) to `module_loads`, OR rely on `srun` (the agent prompt prefers it) |
| All ranks land on node 1 | reproduce.sh ran without `srun` | the replicator prompt's "Multi-node fan-out" block instructs `srun -N $SLURM_JOB_NUM_NODES -n $SLURM_NTASKS`; verify it landed in the generated reproduce.sh |
| `Permission denied` opening files on rank > 0 | `repo_dir` was on `/tmp` | move the checkpoint to `$HOME` or `/work/...`. Nothing logs a shared-FS warning; the rank-0-only failure is the first signal you get |
| `exit 86` with "requested environment modules are unavailable" | rubric declared `module_loads` but the compute node has no module system | drop `module_loads`, or target a partition whose nodes have Lmod / Environment Modules |
| `cpu_bind and mem_bind are srun job-step settings` | those fields were set for `sandbox_kind=slurm` | clear them in the wizard and put the binding into `reproduce.sh` instead |

## See also

- [Execution profile reference](../../reference/execution_profile.md)
- [Compute-node safety conventions](compute_node_safety.md)
- [`hpc_setup.md`](../hpc_setup.md) for the underlying ARI HPC
  configuration.
