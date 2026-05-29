---
sources:
  - path: ari-skill-paper-re/src/prompts/replicator.md
    role: prompt
  - path: ari-skill-paper-re/src/_replicator_agent.py
    role: implementation
last_verified: 2026-05-25
---

# Compute-node safety conventions (L1–L7)

`reproduce.sh` runs on a fresh compute node inside the SLURM allocation,
not on the login node where the agent generated it. The following
conventions (L1–L7) ensure the script can actually complete there.

The PaperBench replicator agent is prompted with these conventions via
`ari-skill-paper-re/src/prompts/replicator.md` (look for the
`COMPUTE-NODE EXECUTION CONVENTIONS` block). They are reproduced here so
you can audit a generated `reproduce.sh` by hand.

## L1 — Shared filesystem

All paths in `reproduce.sh` must resolve on **every** allocated node.

- ✅ `$HOME`, `/work/...`, `/scratch/...`, `/lustre/...`, `/nfs/...`
- ❌ `/tmp`, `/var/tmp`, `/local`, container-local mount-only paths

ARI warns when the checkpoint dir is on a node-local FS, but it does
not refuse to run — your job will silently fail on multi-node when
ranks 1+ cannot see ranks 0's files.

## L2 — MPI invocation: prefer `srun` over `mpirun`

```bash
# Preferred (uses SLURM's PMI/PMIx integration; works without OpenMPI
# being separately installed):
srun -n $SLURM_NTASKS ./my_program

# Acceptable fallback (only when OpenMPI/MPICH is loaded as a module):
mpirun -np $SLURM_NTASKS ./my_program

# Last-resort Python fallback (when neither srun nor mpirun is on PATH):
pip install --user mpi4py
python -c "from mpi4py import MPI; ..."
```

Test with `which srun mpirun` first. The agent prompt instructs the
replicator to emit this check.

## L3 — GRES probe

When the rubric's `execution_profile.gpu_type` is set, ARI checks
`sinfo -o '%G'` before adding `--gres=gpu:<type>:N` to `sbatch`. If
GRES is unconfigured ("(null)"), the flag is dropped and a warning is
logged — `--gpus-per-task` survives.

You can verify the probe interactively:

```python
from ari_skill_paper_re.server import _slurm_has_gres
_slurm_has_gres()    # True / False
```

## L4 — Conda / virtualenv activation

`#!/usr/bin/env bash` does **not** activate any Python environment. If
your `reproduce.sh` needs a specific env, prepend:

```bash
# Option A: source ~/.bashrc (cluster default Python env)
source ~/.bashrc

# Option B: explicit conda activate
source ~/miniconda3/etc/profile.d/conda.sh
conda activate ari-repro

# Option C: rely on /usr/bin/python3 + user-site installs
pip install --user numpy matplotlib mpi4py
```

The agent prompt nudges the replicator to pick one of these.

## L5 — Module loads

Site-specific modules (CUDA, OpenMPI, compilers, mathlibs) must be
loaded inside `reproduce.sh`, not just on the login node. Use the
rubric's `execution_profile.module_loads` to specify them:

```jsonc
"module_loads": ["cuda/12.4", "openmpi/4.1", "gcc/11.3"]
```

The agent then emits:

```bash
module load cuda/12.4 openmpi/4.1 gcc/11.3
```

at the top of `reproduce.sh`. ARI does not validate the module names —
your cluster's `module avail` is authoritative.

## L6 — Multi-node fan-out

`reproduce.sh` starts as **one rank on the first allocated node**. To
use every allocated node, the script must fan out:

```bash
srun -N $SLURM_JOB_NUM_NODES -n $SLURM_NTASKS ./my_program
```

Without this, your script uses 1 node regardless of allocation size,
even if `sbatch --nodes=4` was successful. The agent prompt includes a
dedicated "MULTI-NODE FAN-OUT" section to remind the replicator.

## L7 — Timeout wrapping

SLURM `--time` enforces a hard wallclock and SIGTERMs jobs at the
limit. For partial-result safety, wrap long stages in `timeout`:

```bash
timeout 1800 python long_step.py    # 30-min per-step ceiling
timeout 600  ./bench                # 10-min benchmark cap
```

This ensures one slow step does not eat the entire allocation. The
agent prompt encourages but does not enforce this.

## Verifying a generated reproduce.sh

A quick checklist before launching:

```bash
# 1. No node-local paths
grep -E '/(tmp|var/tmp|local)/' repro_sandbox/reproduce.sh && echo BAD

# 2. srun OR mpirun (not bare ./program)
grep -E 'srun|mpirun' repro_sandbox/reproduce.sh || echo MISSING_FANOUT

# 3. Module loads when execution_profile demanded them
grep -E '^module load' repro_sandbox/reproduce.sh

# 4. Timeout wrappers around long steps
grep -E 'timeout' repro_sandbox/reproduce.sh
```

## See also

- [Multi-node setup](multi_node_setup.md)
- [Execution profile reference](../../reference/execution_profile.md)
- [Troubleshooting](paperbench_troubleshooting.md)
