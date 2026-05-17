# `execution_profile` reference

The `execution_profile` object sits under `reproduce_contract` in every
PaperBench rubric (`ari-skill-replicate/schemas/replication_rubric.schema.json`,
v3). It captures the parallel-execution properties the paper requires:
SLURM allocation shape, GPU type, memory, NUMA bindings, etc. The
`ari-skill-paper-re` Phase 2 sbatch dispatcher reads it, fills in any
caller args left at the default, and emits the matching SLURM flags.

Omit `execution_profile` entirely for legacy single-CPU papers — every
caller arg defaults to 0/""/False/None and the sbatch invocation reduces
to the pre-v0.7.2 4-flag form.

## Full field list

| Field | Type | SLURM flag | Default | Notes |
|---|---|---|---|---|
| `kind` | enum | (agent prompt only) | — | `cpu_single` \| `gpu_single` \| `gpu_multi` \| `mpi` \| `mpi_gpu` |
| `paper_max_ranks` | int | — | — | Largest rank count the paper reports |
| `paper_max_nodes` | int | — | — | Largest node count the paper reports |
| `min_ranks` | int | `--ntasks=N` | 1 | Smallest rank count acceptable for partial credit |
| `min_nodes` | int | — | 1 | Mirror of `min_ranks` for nodes |
| `result_aggregation` | enum | — | `rank0_csv` | Only `rank0_csv` is supported in v0.7.2 |
| `metric_columns` | list[str] | — | `[]` | Required CSV header (e.g. `["nodes","ranks","runtime_sec","gflops"]`) |
| `accepts_reduced_scale` | bool | — | `true` | Allow smaller-scale runs (true ⇒ the agent emits a `paper_paper_scale_point` CSV column) |
| `requested_nodes` | int | `--nodes=N` | 0 | Hint; caller arg wins when set |
| `ntasks_per_node` | int | `--ntasks-per-node=N` | 0 | 0 ⇒ let SLURM decide |
| `requested_nodelist` | str | `--nodelist=...` | `""` | Pin specific node(s) |
| `exclude_nodes` | str | `--exclude=...` | `""` | Blacklist nodes (e.g. `"badnode01"`) |
| `exclusive` | bool | `--exclusive` | `false` | Essential for faithful performance reproduction |
| `requested_gpus_per_task` | int | `--gpus-per-task=N` | 0 | |
| `requested_gpus_per_node` | int | `--gpus-per-node=N` | 0 | |
| `gpu_type` | str | `--gres=gpu:<type>:N` | `""` | Combined with `requested_gpus_per_task` (or `_per_node`). Auto-dropped when cluster reports no GRES via `sinfo`. |
| `memory_gb_per_node` | int | `--mem=NG` | 0 | |
| `memory_gb_per_cpu` | int | `--mem-per-cpu=NG` | 0 | |
| `constraint` | str | `--constraint=...` | `""` | E.g. `"skylake"`, `"haswell|broadwell"` |
| `cpu_bind` | str | `--cpu-bind=...` | `""` | E.g. `"cores"`, `"sockets"`, `"rank"` |
| `mem_bind` | str | `--mem-bind=...` | `""` | E.g. `"local"`, `"nearest"` |
| `hint` | str | `--hint=...` | `""` | E.g. `"nomultithread"`, `"compute_bound"` |
| `module_loads` | list[str] | (reproduce.sh prelude) | `[]` | Cluster modules the agent should `module load` before running |
| `extra_sbatch_args` | list[str] | (concat) | `[]` | Pass-through escape hatch (e.g. `["--account=projX"]`) |

## Auto-resolve precedence

`ari-skill-paper-re.run_reproduce` resolves each flag as:

```
explicit caller arg  >  rubric execution_profile  >  default (0/""/False/None)
```

This lets the wizard's *Execution profile override* form override the
rubric without forcing the user to edit the rubric JSON. Boolean fields
(`exclusive`) are merged with OR — once any source enables it, the flag
is emitted.

## Full HPC example (MPI + GPU)

Faithful reproduction of TS-SpGEMM scaling (4 nodes × 8 ranks × 1 V100
per task, exclusive, Skylake-only):

```jsonc
"reproduce_contract": {
  "script_path": "reproduce.sh",
  "max_runtime_sec": 7200,
  "expected_artifacts": ["submission/results/scaling.csv"],
  "execution_profile": {
    "kind": "mpi_gpu",
    "paper_max_ranks": 32,
    "paper_max_nodes": 4,
    "min_ranks": 4,
    "result_aggregation": "rank0_csv",
    "metric_columns": ["nodes","ranks","runtime_sec","gflops"],
    "accepts_reduced_scale": true,

    "requested_nodes": 4,
    "ntasks_per_node": 8,
    "exclusive": true,

    "requested_gpus_per_task": 1,
    "gpu_type": "v100",

    "memory_gb_per_node": 256,
    "constraint": "skylake",
    "cpu_bind": "cores",
    "hint": "nomultithread",

    "module_loads": ["cuda/12.4", "openmpi/4.1"],
    "extra_sbatch_args": ["--account=projX"]
  }
}
```

The resulting `sbatch` invocation:

```
sbatch --wait \
  --partition large \
  --nodes 4 --ntasks 32 --ntasks-per-node 8 \
  --exclusive \
  --gpus-per-task 1 --gres=gpu:v100:1 \
  --mem=256G --cpus-per-task 8 \
  --constraint=skylake --cpu-bind=cores --hint=nomultithread \
  --account=projX \
  --time 02:00:00 \
  reproduce.sh
```

## Single-GPU example

```jsonc
"execution_profile": {
  "kind": "gpu_single",
  "paper_max_ranks": 1,
  "metric_columns": ["throughput_GB_s", "PSNR_dB"]
}
```

The agent prompt is told to use CUDA / PyTorch CUDA / cupy; SLURM
allocation falls back to the partition default.

## Single-CPU example

```jsonc
// Omit execution_profile entirely — legacy single-CPU behaviour.
"reproduce_contract": {
  "script_path": "reproduce.sh",
  "max_runtime_sec": 1800,
  "expected_artifacts": ["results.csv"]
}
```

## See also

- [PaperBench quickstart](../howto/paperbench_quickstart.md)
- [Multi-node setup](../howto/multi_node_setup.md)
- [Compute-node safety conventions](../howto/compute_node_safety.md)
- Skill source: `ari-skill-paper-re/src/server.py:run_reproduce`
- Schema: `ari-skill-replicate/schemas/replication_rubric.schema.json`
