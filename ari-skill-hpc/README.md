# ari-skill-hpc

Deterministic MCP skill for reproducible scheduler jobs. It exposes a common
`JobRequestV1` / `JobHandleV1` / `JobStatusV1` / `JobResultV1` lifecycle, with
SLURM as the first backend and Apptainer/Singularity as digest-pinned execution
profiles. The outer MCP call returns immediately after scheduler submission;
long-running work is polled or cancelled through its handle.

`ari_skill_hpc.execution_adapter.handoff_execution_to_slurm` maps the common
`ExecutionRequestV1` identity, structured argv, clean environment, and immutable
input snapshots into a `JobRequestV1`. Its signed `ExecutionHandoffV1` record
lists every mapped field and every POSIX policy SLURM does not preserve; it
deliberately reports `policy_equivalent: false` instead of claiming substrate
parity.

## Canonical tools

| Tool | Contract |
|---|---|
| `job_submit` | Submit one immutable `JobRequestV1`; retries use the durable request digest and do not create a second job. |
| `container_submit` | The same lifecycle, requiring a pinned `ContainerRequestV1`. |
| `job_status` | Normalize SLURM states to `submitted`, `running`, `succeeded`, `failed`, `cancelled`, or `unknown`. |
| `job_result` | Rehash declared inputs, outputs, logs, and provenance into `JobResultV1`. |
| `job_logs` | Return bounded, digest-bound stdout and stderr. |
| `job_cancel` | Request cancellation with an inert handle or numeric SLURM ID. |
| `probe_platform_capabilities` | Probe a validated tool list on one compute partition and atomically cache the result. |
| `counter_support` | Report whether this node grants hardware counters, established by opening one rather than by looking for a profiler binary. |
| `measure_counters` | Count reviewed hardware events on an existing process over a bounded window. It creates no process and writes nothing. |

The five container-specific aliases were removed after the P6 deprecation and
caller-count gate. `slurm_submit` remains a scoped bridge for the core agent's
batch-script workflow; new programmatic integrations use `job_submit`.
`run_bash` is not an HPC tool; short interactive execution belongs to
`ari-skill-coding`.

`ResourceRequestV1` also says how the payload is started inside the allocation.
`launcher` is `auto` (the default), `srun`, or `none`: `auto` binds a
single-task, single-node payload with `srun --ntasks=1` so it gets the CPUs it
asked for instead of the whole node, and starts any larger shape directly,
leaving the parallel launch to the payload; `srun` starts the payload itself
with the declared `nodes` / `tasks` / `cpus_per_task`, which is what an MPI or
SPMD binary needs; `none` never wraps. It is declared rather than inferred from
`tasks > 1`, because the two readings of a multi-task request are
indistinguishable here and guessing wrong is silent — a payload that launches
its own ranks, started under `srun --ntasks=N`, runs N times too many. The
launcher is part of the request digest, so the same script under a different
launch mode is a different job rather than an idempotent retry.

`measure_counters` declares `context_requirement: node`, so its input schema
declares an `ari_context` object property. The transport injects the authorized
node context under that name for any tool with a context requirement, and a
schema that sets `additionalProperties: false` without declaring it refuses
every authorized call. The proxy strips the property back out of `tools/list`,
so it is never an argument a caller supplies.

Checked-in JSON Schemas live under [`schemas/`](schemas/). Regenerate or verify
them with:

```bash
python scripts/sync_contracts.py --write
python scripts/sync_contracts.py
```

## Security and reproducibility boundary

- Local scheduler commands use `asyncio.create_subprocess_exec`; no request is
  interpolated into a login-node shell. Remote commands are POSIX-quoted argv
  atoms and batch scripts are transferred through `sbatch` standard input.
- Jobs use `sbatch --export=NIL`. Unlike `NONE`, SLURM documents that `NIL`
  does not implicitly reconstruct a user login environment. The generated
  script adds only a fixed PATH, locale, SLURM variables, reviewed non-secret
  literals, and explicitly named modules. It never sources `.env` or shell rc
  files.
- Remote mode requires an absolute `SLURM_SSH_KNOWN_HOSTS` file and an explicit
  key or password scope. Paramiko `RejectPolicy`, `allow_agent=False`, and
  `look_for_keys=False` make missing or mismatched host keys fail closed.
- Input files and SIF images are regular, non-symlink files with exact SHA-256
  and size pins. Declared outputs must remain below `work_dir` and are rehashed
  only after terminal completion.
- A durable ledger records a claim before `sbatch`. A transport failure with an
  uncertain submit outcome leaves that claim in place, preventing an accidental
  duplicate on retry.

These choices follow the current primary documentation for
[SLURM `sbatch`](https://slurm.schedmd.com/sbatch.html),
[SLURM job states](https://slurm.schedmd.com/job_state_codes.html), and
[Paramiko host-key policy](https://docs.paramiko.org/en/4.0/api/client.html).

## Local mode

`SLURM_MODE=local` is the default. Configure a stable ledger path in production:

```bash
export ARI_HPC_LEDGER_PATH=/shared/project/checkpoints/hpc-jobs-v1.json
export ARI_SCHEDULER_PATH=/usr/local/bin:/usr/bin:/bin
```

If no ledger path is configured, the skill uses `ARI_CHECKPOINT_DIR`, then
`ARI_WORK_DIR`, and finally a per-user temporary state directory.

## Strict remote mode

```bash
export SLURM_MODE=remote
export SLURM_SSH_HOST=cluster.example.org
export SLURM_SSH_USER=researcher
export SLURM_SSH_KNOWN_HOSTS=/etc/ari/cluster_known_hosts
export SLURM_SSH_KEY=/run/secrets/ari_cluster_key
export SLURM_SHARED_FILESYSTEM=true
ari-skill-hpc
```

Typed output collection currently requires a shared filesystem visible at the
same absolute paths on the MCP host and compute nodes. Set
`SLURM_SHARED_FILESYSTEM=false` only for status/cancel/log use; a future artifact
transport backend can extend this without changing the job contracts.

## Containers

Canonical callers put an `ArtifactPinV1` image in `request.container.image`,
declare each bind as a typed source/target/mode tuple, and request GPU access in
both the container and scheduler resource records. `--cleanenv`, `--containall`,
and an explicit writable work-directory bind are generated by the adapter.
`container.network: none` additionally emits an isolated container network;
`host` remains the compatibility default and must not be used by offline
scientific profiles such as OpenROAD.

## Verification

```bash
ruff check src tests scripts
pytest -q
python scripts/sync_contracts.py
python ../scripts/check_skill_manifests.py
```

See [`docs/guides/hpc_setup.md`](../docs/guides/hpc_setup.md) for operator setup
and [`docs/reference/execution_contract.md`](../docs/reference/execution_contract.md)
for the shared execution contract.
