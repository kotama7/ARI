---
sources:
  - path: ari-skill-replicate/schemas/replication_rubric.schema.json
    role: schema
  - path: ari-skill-paper-re/src/server.py
    role: implementation
  - path: ari-skill-paper-re/src/rubric_contract.py
    role: implementation
  - path: ari-skill-paper-re/src/_replicator_agent.py
    role: implementation
  - path: ari-skill-hpc/ari_skill_hpc/contracts.py
    role: implementation
  - path: ari-skill-hpc/ari_skill_hpc/scheduler.py
    role: implementation
last_verified: 2026-08-16
---

# `execution_profile` reference

The `execution_profile` object sits under `reproduce_contract` in every
PaperBench rubric (`ari-skill-replicate/schemas/replication_rubric.schema.json`
— `schema_version: ari.replication-rubric/v2`, `version: "3"`). It captures the
parallel-execution properties the paper requires:
SLURM allocation shape, GPU type, memory, job-step bindings, etc.
`ari-skill-paper-re` reads it and compiles the allocation fields into
`ari.hpc.job-request/v1`; the replicator agent receives the whole object
verbatim in its prompt while writing `reproduce.sh`.

Omit `execution_profile` entirely for single-CPU papers. The scheduler always
uses the same typed request, clean environment, digest, and handle lifecycle.

> **Who actually validates this.** JSON-schema validation lives in
> `ari-skill-replicate` (`generator.py` / `auditor.py`), which runs when the
> rubric is produced or audited. `ari-skill-paper-re`'s `load_rubric` checks the
> envelope — version negotiation, `rubric_sha256`, `paper_sha256`, TaskNode
> shape — and does **not** run the schema over `execution_profile`, nor inject
> the schema's `default:` values. Every reader is
> `exec_profile.get(field, 0) or 0` (or `... or ""`), so an omitted field
> behaves as `0` / `""` / `False` at runtime no matter what the Default column
> below says. The one place this bites: `accepts_reduced_scale` is documented as
> defaulting to `true`, but if you leave it out the agent never sees the
> reduced-scale instruction. The second gate is the typed
> `ResourceRequestV1`, which rejects a malformed *compiled* shape.

## Full field list

| Field | Type | SLURM flag | Default | Notes |
|---|---|---|---|---|
| `kind` | enum | (agent prompt only) | — | `cpu_single` \| `gpu_single` \| `gpu_multi` \| `mpi` \| `mpi_gpu` |
| `paper_max_ranks` | int | — | — | Largest rank count the paper reports |
| `paper_max_nodes` | int | — | — | Largest node count the paper reports |
| `min_ranks` | int | `--ntasks=N` | 1 | Smallest rank count acceptable for partial credit. When set it *is* the requested `--ntasks`, so `ntasks_per_node` must not exceed it — the typed request rejects `tasks_per_node cannot exceed total tasks`. |
| `min_nodes` | int | (agent prompt only) | 1 | Mirror of `min_ranks` for nodes. No resolution code reads it — `--nodes` comes from `requested_nodes` |
| `result_aggregation` | enum | (agent prompt only) | `rank0_csv` | `rank0_csv` is the schema's only enum member |
| `metric_columns` | list[str] | — | `[]` | Required CSV header (e.g. `["nodes","ranks","runtime_sec","gflops"]`) |
| `accepts_reduced_scale` | bool | — | `true` | Allow smaller-scale runs (true ⇒ the agent emits a `paper_paper_scale_point` CSV column) |
| `requested_nodes` | int | `--nodes=N` | 0 (absent) | Hint; caller arg wins when set. The schema requires `minimum: 1`, so omit the key rather than writing `0`; an absent value compiles to `--nodes=1` |
| `ntasks_per_node` | int | `--ntasks-per-node=N` | 0 | 0 ⇒ the directive is omitted entirely. When `ntasks` is not given, total tasks is derived as `ntasks_per_node × nodes` (else 1) |
| `requested_nodelist` | str | `--nodelist=...` | `""` | Pin specific node(s) |
| `exclude_nodes` | str | `--exclude=...` | `""` | Blacklist nodes (e.g. `"badnode01"`) |
| `exclusive` | bool | `--exclusive` | `false` | Essential for faithful performance reproduction |
| `requested_gpus_per_task` | int | `--gpus-per-task=[<type>:]N` | 0 | Mutually exclusive with `requested_gpus_per_node` (schema `allOf` and `ResourceRequestV1`) |
| `requested_gpus_per_node` | int | `--gres=gpu:[<type>:]N` | 0 | Emitted as `--gres`, not `--gpus-per-node`, and only when `requested_gpus_per_task` is 0 |
| `gpu_type` | str | typed GPU selector | `""` | Combined with exactly one GPU-count field; requests are never silently dropped — `gpu_type` alone is promoted to `requested_gpus_per_node=1` rather than discarded. |
| `memory_gb_per_node` | int | `--mem=<GB×1024>M` | 0 | Mutually exclusive with `memory_gb_per_cpu` |
| `memory_gb_per_cpu` | int | `--mem-per-cpu=<GB×1024>M` | 0 | Mutually exclusive with `memory_gb_per_node` |
| `constraint` | str | `--constraint=...` | `""` | E.g. `"skylake"`, `"haswell|broadwell"` |
| `cpu_bind` | str | `srun --cpu-bind=...` in `reproduce.sh` | `""` | Job-step setting, not an `sbatch` directive — and `run_reproduce` never forwards the rubric's value: it only passes its own `cpu_bind` argument, which the SLURM path then rejects outright (`cpu_bind and mem_bind are srun job-step settings; place them explicitly in reproduce.sh`). The rubric value reaches the agent only as part of the EXECUTION PROFILE dump. |
| `mem_bind` | str | `srun --mem-bind=...` in `reproduce.sh` | `""` | Same handling as `cpu_bind`. |
| `hint` | enum | `--hint=...` | `""` | `""` \| `compute_bound` \| `memory_bound` \| `multithread` \| `nomultithread` |
| `module_loads` | list[str] | generated clean job prelude | `[]` | Loaded explicitly and included in provenance. |
| `account` | str | `--account=...` | `""` | Typed project/account selector. |
| `qos` | str | `--qos=...` | `""` | Typed QoS selector. |
| `reservation` | str | `--reservation=...` | `""` | Typed reservation selector. |
| `extra_sbatch_args` | list[str] | deprecated reader only | `[]` | New producers must not emit it; the reader only translates account/QoS/reservation/hint. |

## Auto-resolve precedence

`ari-skill-paper-re.run_reproduce` resolves each flag as:

```
explicit caller arg  >  rubric execution_profile  >  default (0/""/False/None)
```

This lets the wizard's *Execution profile override* form override the
rubric without forcing the user to edit the rubric JSON. Boolean fields
(`exclusive`) are merged with OR — once any source enables it, the flag
is emitted.

Two exceptions to the chain:

- `cpu_bind` / `mem_bind` are **caller-only**. `run_reproduce` never consults
  `execution_profile` for them.
- `account` / `qos` / `reservation` / `hint` gain a fourth, lowest tier: values
  parsed out of the deprecated `extra_sbatch_args` list.

`partition` is not part of `execution_profile` at all; it is resolved separately
(caller arg → `$ARI_SLURM_PARTITION` → `$SLURM_PARTITION` →
`{checkpoint_dir}/launch_config.json`'s `partition`), and a `slurm` sandbox with
no resolvable partition is a hard error rather than a fallback.

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
    "min_ranks": 32,
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
    "account": "projX"
  }
}
```

The scheduler invokes only `sbatch --parsable --export=NIL` and sends a
generated script on stdin. Its relevant directives are:

```
#SBATCH --partition=large
#SBATCH --nodes=4
#SBATCH --ntasks=32
#SBATCH --ntasks-per-node=8
#SBATCH --exclusive
#SBATCH --gpus-per-task=v100:1
#SBATCH --mem=262144M
#SBATCH --cpus-per-task=8
#SBATCH --constraint=skylake
#SBATCH --hint=nomultithread
#SBATCH --account=projX
#SBATCH --export=NIL
```

That is the subset this profile controls. The generator always also emits
`--job-name`, `--time`, `--chdir`, `--output` and `--error`, and `--export=NIL`
is unconditional.

`launcher` defaults to `auto`, which wraps only a single-task single-node
payload in `srun`. A 32-rank request like the one above is started **directly**,
so `reproduce.sh` itself must do the parallel launch (`srun -n $SLURM_NTASKS`
or `mpirun -np $SLURM_NTASKS`) — which is exactly what the agent is instructed
to write for the `mpi` / `mpi_gpu` kinds.

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

- [PaperBench quickstart](../guides/paperbench/paperbench_quickstart.md)
- [Multi-node setup](../guides/paperbench/multi_node_setup.md)
- [Compute-node safety conventions](../guides/paperbench/compute_node_safety.md)
- Skill source: `ari-skill-paper-re/src/server.py:run_reproduce`
- Schema: `ari-skill-replicate/schemas/replication_rubric.schema.json`
