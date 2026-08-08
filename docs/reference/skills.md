---
sources:
  - path: ari-skill-hpc/ari_skill_hpc/server.py
    role: implementation
  - path: ari-skill-hpc/ari_skill_hpc/contracts.py
    role: implementation
  - path: ari-skill-hpc/ari_skill_hpc/scheduler.py
    role: implementation
  - path: ari-skill-hpc/ari_skill_hpc/slurm.py
    role: implementation
  - path: ari-skill-hpc/ari_skill_hpc/counters.py
    role: implementation
  - path: ari-skill-hpc/mcp.json
    role: config
  - path: ari-skill-hpc/skill.yaml
    role: config
  - path: ari-skill-hpc/tests/test_server.py
    role: test
  - path: ari-skill-coding/src/server.py
    role: implementation
  - path: ari-skill-coding/mcp.json
    role: config
  - path: ari-skill-paper-re/src/server.py
    role: implementation
  - path: ari-skill-paper-re/mcp.json
    role: config
  - path: ari-skill-idea/src/server.py
    role: implementation
last_verified: 2026-08-08
---

# Capability Provider Packages (`ari-skill-*` compatibility names)

The packages historically called “Skills” are executable **Capability
Providers** connected through MCP. They are not Knowledge Skills. MCP is the
transport/discovery protocol; each listed tool is an atomic Provider
operation. Tools are deterministic where possible, and LLM-using operations
are explicitly annotated. The on-disk `skill.yaml`, `SkillManifestV1`, and
`SKILLS.lock` names remain compatibility names for the Provider manifest and
run snapshot; there is no parallel `provider.yaml` or `PROVIDERS.lock`.

Non-executable Knowledge Skills and independent Harnesses are documented in
[Knowledge, Capability, and Scientific Assurance](knowledge_capability_assurance.md).
The default-off `ari-skill-knowledge` and `ari-skill-harness` packages expose
only read/query and non-authoritative request operations; neither grants
catalog administration or fixed resolution authority. Those two and
`ari-skill-tool-registry` have no narrative section here — their tools are
catalogued in [mcp_tools.md](mcp_tools.md), and the registry's catalog
identity and provider adapters in [tool_registry.md](tool_registry.md).

## ari-skill-hpc

Typed SLURM lifecycle, strict SSH transport, capability probes, and
digest-pinned containers. **LLM: No** (fully deterministic).

Ten tools in three groups: two typed submitters (`job_submit`,
`container_submit`) plus the retained batch-script bridge (`slurm_submit`); four
lifecycle operations that share one handle selector (`job_status`, `job_result`,
`job_logs`, `job_cancel`); and three probes (`probe_platform_capabilities`,
`counter_support`, `measure_counters`). Containers are declared by the
digest-pinned `ContainerRequestV1` carried on the request, not by the choice of
tool: `container_submit` is the same submission with that field made mandatory,
and `job_submit` — which declares the identical input schema — accepts a request
that carries a container and runs it through exactly the same path, it simply
does not require one. The package exposes no image build, pull or run commands.

### Tools

#### `job_submit(request)`

Submit an immutable `JobRequestV1` and immediately return an idempotent
`JobHandleV1`. The tool takes exactly one argument, `request` — the
`JobSubmitArgumentsV1` wrapper exists to keep every JSON Schema `$ref` at the
root of the input schema. Commands are `argv` arrays; the login-node shell is
never used. The core agent's batch-script workflow stays on the `slurm_submit`
bridge below; new programmatic callers should prefer `job_submit`.

`JobRequestV1` requires `request_id`, `job_name`, `work_dir` (an existing,
non-symlink absolute directory), `argv` and `resources`. `environment`,
`container`, `accelerator_allocation`, `inputs`, `outputs` and `metadata` are
optional.

`resources` (`ResourceRequestV1`) declares the same `partition` / `nodes=1` /
`tasks=1` / `tasks_per_node=None` / `cpus_per_task=1` / `walltime="01:00:00"` /
`launcher="auto"` shape as `slurm_submit`, and adds `memory_mb_per_node`,
`memory_mb_per_cpu`, `gpus_per_node`, `gpus_per_task`, `gpu_type`, `nodelist`,
`exclude_nodes`, `exclusive`, `constraint`, `hint`, `account`, `qos` and
`reservation`.

`environment` (`EnvironmentPolicyV1`) fixes `export_mode` to `NIL`: the job sees
only the reviewed non-secret literals and `modules` declared here, and a
variable whose name looks like a credential (`*_TOKEN`, `*_PASSWORD`,
`*_API_KEY`, …) is refused rather than embedded in the request.

Submission is always `sbatch --parsable --export=NIL`. The request is identified
by `request_digest`, the sha256 of its canonical JSON, and that digest is
claimed in a durable ledger *before* `sbatch` runs — so resubmitting the same
request returns the existing handle instead of a second job, and a transport
that dies with the outcome unknown leaves the claim standing rather than letting
a retry duplicate the job.

Every `inputs` pin must match its declared sha256 and size at submission time,
and is checked again on the node before the payload starts; declared `outputs`
must stay below `work_dir`, and symlinks are refused. Per-job artifacts live
under `{work_dir}/.ari-hpc/{request_digest without its sha256: prefix}/`, which
is the handle's `artifact_scope`.

```python
result = job_submit(request={
    "request_id": "bench_001",
    "job_name": "bench_test",
    "work_dir": "/abs/path/to/workdir",
    "argv": ["./bench", "--threads", "32"],
    "resources": {"partition": "your_partition", "cpus_per_task": 32},
})
# Returns: {"schema_version": "ari.hpc.job-handle/v1", "handle_id": "hpc-...",
#           "request_digest": "sha256:...", "job_id": "12345",
#           "state": "submitted", ...}
```

#### `container_submit(request)`

The same lifecycle and the same argument schema as `job_submit`, except that
`request.container` must be there: without it the call is refused as a
validation error.

`ContainerRequestV1` takes `runtime` (`apptainer` by default, or `singularity`),
`image` (an `ArtifactPinV1` — absolute path, `sha256:…` digest and byte size),
`binds` (read-only by default, targets must be unique), `gpu` (default `false`),
`network` (`host` by default, or `none`), `contain_all` (default `true`) and
`clean_environment` (default `true`). The image is pinned by digest, so an image
whose bytes changed is refused before the job runs and again on the node. With a
container declared, each `inputs` pin must also sit below `work_dir` or one of
the declared binds; `work_dir` itself is bind-mounted read-write unless the
request already declared it.

#### `slurm_submit(script, job_name, partition, nodes=1, tasks=1, tasks_per_node=None, cpus_per_task=1, launcher="auto", walltime="01:00:00", work_dir, modules=[])`

Submit a SLURM batch job.

**Allocating more than one node does not, by itself, use more than one node.**
The batch body runs on the first node; the rest sit idle unless something
launches a parallel step. `launcher` decides who does that:

| `launcher` | The script is started as | Use when |
|---|---|---|
| `auto` (default) | exactly as written | your script calls `srun` / `mpirun` itself, or is serial |
| `srun` | `srun` with the declared `nodes` / `tasks` / `cpus_per_task` (and `--ntasks-per-node` when declared), wrapping `bash -c <script>` | the script IS the parallel program (MPI / SPMD) |
| `none` | exactly as written | the payload must see the batch step untouched |

`auto` and `none` therefore reach the node identically here: the bridge body is
a script, and only `srun` wraps it. The CPU binding `auto` performs is on the
typed `job_submit` / `container_submit` path, where the payload is an `argv`
and a one-task, one-node request is started as `srun --ntasks=1
--cpus-per-task=N`. That binding exists because a batch step inherits the whole
node's affinity mask — a threaded payload otherwise spreads across the machine
and can lose to its own serial baseline, which reads as a slow kernel rather
than an unbound allocation.

Do **not** combine `launcher="srun"` with your own launcher: `srun --ntasks=8
mpirun -np 8 ./x` is sixty-four ranks, and nothing downstream can tell that
from a correct run. That is why the choice is explicit rather than inferred
from `tasks > 1` — the two kinds of multi-task request are indistinguishable
to the scheduler.

The launch mode and the allocation shape are both part of the request digest,
so the same script submitted under a different shape or launcher is a
different job rather than a cache hit on the first one.

```python
result = slurm_submit(
    script="""
#!/bin/bash
gcc -O3 -fopenmp -o ./bench ./bench.c
OMP_NUM_THREADS=32 ./bench
""",
    job_name="bench_test",
    partition="your_partition",
    cpus_per_task=32,
    work_dir="/abs/path/to/workdir"
)
# Returns: {"schema_version": "ari.hpc.job-handle/v1", "handle_id": "hpc-...",
#           "job_id": "12345", "state": "submitted", "status": "submitted",
#           "message": "Job 12345 submitted successfully",
#           "request_digest": "sha256:...", "submission_digest": "sha256:..."}
```

**Notes:**
- `#SBATCH` directives written inside `script` have no effect. The generated
  header is followed immediately by executable lines, so `sbatch` stops reading
  directives before the body — declare the shape through the arguments
  (`nodes`, `tasks`, `cpus_per_task`, `walltime`) instead
- A refused submission comes back as `{"job_id": "", "status": "error",
  "message": ..., "partition": ...}` rather than raising
- The body runs under `set -euo pipefail` with `PATH=/usr/local/bin:/usr/bin:/bin`,
  `LANG`/`LC_ALL=C.UTF-8`, and `BASH_ENV ENV CDPATH GLOBIGNORE PYTHONHOME
  PYTHONPATH VIRTUAL_ENV` unset: nothing is inherited from the submitting shell,
  so use absolute paths and reach the toolchain through `modules`

#### `job_status(handle_id)`

Return a provider-neutral `JobStatusV1` for an ARI handle or a raw SLURM ID.

`job_status`, `job_result`, `job_logs` and `job_cancel` share one selector
schema: exactly one of `handle_id` (the `JobHandleV1` handle ID, preferred) or
`job_id` (raw SLURM job ID, legacy compatibility). It is a `oneOf`, so passing
both or neither is refused, and the implementation reads `handle_id` first. A
selector that is neither a known handle nor a bare numeric SLURM ID is a
validation error.

State comes from `sacct -j <id> --noheader --parsable2 --allocations
--format=JobID,State,ExitCode,Start,End,Reason`, falling back to
`squeue -j <id> --noheader --format=%T|%R` when accounting has no record yet.

```python
result = job_status(handle_id="hpc-...")
# Returns: {"schema_version": "ari.hpc.job-status/v1", "handle_id": "hpc-...",
#           "job_id": "12345", "state": "succeeded",
#           "scheduler_state": "COMPLETED", "exit_code": 0,
#           "start_time": ..., "end_time": ..., "reason": None}
```

`state` is the normalised, provider-neutral value — one of `submitted`,
`running`, `succeeded`, `failed`, `cancelled`, `unknown` — while
`scheduler_state` keeps SLURM's own word. `PENDING` / `CONFIGURING` /
`REQUEUED` / `RESIZING` / `SPECIAL_EXIT` normalise to `submitted`; `RUNNING` /
`COMPLETING` / `SUSPENDED` / `STAGE_OUT` to `running`; `COMPLETED` to
`succeeded`; `CANCELLED` (either spelling) / `DEADLINE` / `REVOKED` to
`cancelled`; `BOOT_FAIL` / `FAILED` / `NODE_FAIL` / `OUT_OF_MEMORY` /
`PREEMPTED` / `TIMEOUT` to `failed`. A job the scheduler will not answer for
reads `state: "unknown"`, `scheduler_state: "UNKNOWN"` — a recorded absence of
evidence, not an error.

There is no `ERROR` state. A call that fails returns the error envelope
`{"error": {"kind": ..., "message": ..., "retryable": ...}}`, where `kind` is
`validation`, `transport`, `scheduler` or `unknown`; the message is scrubbed of
credential-shaped text before it leaves the tool.

#### `job_result(handle_id)`

Collect a terminal `JobResultV1`, rehashing declared inputs, outputs and logs.
Same selector as `job_status`.

The job must have been submitted through ARI (there has to be a ledger record
and a handle) and must carry a typed request: a `slurm_submit` bridge job
exposes status and logs but not a typed `JobResultV1`. Calling before the job
reaches a terminal state (`succeeded`, `failed`, `cancelled`) is a validation
error.

Each declared input is re-verified against its pin, each declared output is
re-hashed from the file on disk into an `ArtifactPinV1`, and the logs are
attached alongside provenance pins — the submission record, the
execution-environment snapshot, the module list, the container runtime version,
the exit code, and the exclusive-allocation and accelerator-inventory witnesses
when the request declared one. A missing `required: true` output is not an
exception: it lands in the result as `error.kind = "artifact"`. A job that ended
in any non-`succeeded` terminal state gets `error.kind = "execution"`, marked
`retryable` for `NODE_FAIL`, `PREEMPTED` and `REQUEUED`.

The returned record carries `request_digest`, `environment_digest` and
`module_digest`, plus `module_snapshot_digest`, `container_digest`,
`accelerator_allocation_digest` and `accelerator_inventory_digest` where they
apply, sealed by a `result_digest` taken over the rest of the record. The same
record is written atomically to `{artifact_scope}/result-v1.json`.

#### `job_logs(handle_id)`

Read bounded, digest-bound stdout/stderr for an ARI job handle. Same selector as
`job_status`, and likewise only for jobs submitted through ARI.

```python
result = job_logs(handle_id="hpc-...")
# Returns: {"schema_version": "ari.hpc.job-logs/v1", "logs": [...]}
```

Each entry gives `stream` (`stdout` or `stderr`), `path`, `digest`,
`size_bytes`, `text` and `truncated`. `text` stops at 1 MiB (1,048,576 bytes)
and sets `truncated: true` when it does — truncation is visible rather than
passing as complete output. `digest` and `size_bytes` cover the whole file when
the log is read directly on a shared filesystem; when the scheduler is reached
over a non-shared transport the log comes back through that transport, and
`digest` and `size_bytes` then describe the same 1 MiB-bounded text.
Logs are read from `slurm-{job_id}.out` / `.err` in the handle's
`artifact_scope`; a stream with no file is simply left out, and a log that is
not a regular non-symlink file is refused.

#### `job_cancel(handle_id)`

Request cancellation of an ARI or SLURM job. Same selector as `job_status`.

```python
result = job_cancel(handle_id="hpc-...")
# Returns: {"schema_version": "ari.hpc.job-cancel/v1", "handle_id": "hpc-...",
#           "job_id": "12345", "status": "cancel_requested"}
```

The name is exact: this returns the fact that `scancel` accepted the request,
not that the job has stopped. Poll `job_status` for the scheduler's own account
of it — a cancelled job reads `state: "cancelled"`. If `scancel` itself is
rejected, the call returns the error envelope with `kind: "scheduler"`.

#### `probe_platform_capabilities(checkpoint_dir, partition="", tools="")`

Probe tool availability (`command -v`) **on the compute partition** and cache
the result to `{checkpoint_dir}/platform_capabilities.json`. `tools` is a
comma-separated list, defaulting to `ARI_PROBE_TOOLS` and then to
`perf,numactl,papi_avail,likwid-perfctr,valgrind`; an empty `partition` falls
back to `ARI_SLURM_PARTITION`.

A probe that ran returns `{"status": "probed", "partition": ..., "arch": ...,
"available": {"perf": true, ...}}` — `available` maps each probed name to a
boolean. The same record comes back as `{"status": "unsaved", "reason": ...,
...}` when the probe ran but the cache could not be written, and as
`{"status": "cached", ...}` when a valid cache is already there and nothing is
re-probed. Best-effort by design: any failure (no partition, `srun` missing,
queue wait beyond the timeout) returns `{"status": "skipped", "reason": ...}`
and writes nothing. The claims extractor reads the cached note so it never
declares evidence that depends on tools the platform verifiably lacks.

#### `counter_support()`

Report whether this node grants hardware counters, established by opening one
rather than by looking for a profiler binary. Takes no arguments.

A profiler binary proves nothing: `perf` is absent from some nodes that permit
counters and present on some that deny them, and vendor profilers live at
site-dependent paths. Calling `perf_event_open` observes the kernel policy that
will actually apply, inside whatever container the node runs in.

```python
result = counter_support()
# Returns: {"schema_version": "ari.hpc.counter-support/v1", "architecture": "...",
#           "perf_event_paranoid": ..., "reviewed_events": [...],
#           "status": "ready", "detail": None}
```

`status` is `ready`; `denied` when the self-probe is refused with `EACCES` or
`EPERM`; `unsupported` when the architecture has no reviewed `perf_event_open`
syscall number, or the self-probe failed for any other reason; `unavailable` on
a non-Linux host.

#### `measure_counters(pid, window_ms=1000, events=["cycles", "instructions"])`

Count reviewed hardware events on an existing process over a bounded window.
This profiles rather than executes: it creates no process, writes nothing, and
asks for no credential.

- `pid` is required and must name a running process
- `window_ms` runs from 1 to 60000 (`MAX_WINDOW_MS`), default 1000
- `events` is drawn from the reviewed set — `branch-instructions`,
  `branch-misses`, `cache-misses`, `cache-references`, `cycles`,
  `instructions` — defaulting to `["cycles", "instructions"]`. A name outside
  that set is refused rather than passed through, so a caller cannot reach an
  arbitrary raw event encoding

Counters are opened with the least-privileged request there is
(`exclude_kernel`, `exclude_hv`), so a denial reflects policy rather than an
over-broad ask; the returned `excluded: ["kernel", "hypervisor"]` records that.

```python
result = measure_counters(pid=12345, window_ms=2000)
# Returns: {"schema_version": "ari.hpc.counter-measurement/v1", "status": "measured",
#           "support": {...}, "pid": 12345, "window_seconds": 2.000123,
#           "counters": {"cycles": ..., "instructions": ...},
#           "excluded": ["kernel", "hypervisor"]}
```

When `counter_support()` is not `ready`, or a counter cannot be opened against
the target pid, `counters` comes back empty and `status` carries `denied`,
`unavailable` or `unsupported` with the `support` record attached.

This is the one HPC tool that declares `context_requirement: node` in
`skill.yaml`, so its input schema declares an `ari_context` object property. The
transport injects the authorised node context under that name for any tool with
a context requirement, and the schema is `additionalProperties: false` — a
schema that did not declare it would refuse every authorised call. The proxy
strips the property out of `tools/list` and overwrites it on `tools/call`, so it
is never an argument the agent supplies.

---

## ari-skill-idea

Literature survey and idea generation. **LLM: Yes** (generate_ideas uses VirSci multi-agent deliberation).

### Tools

#### `survey(topic, max_papers=8, mode="record", snapshot_path="survey_snapshot_v1.json", provider="semantic-scholar")`

Prior-work survey. Deterministic (no LLM). The provider is **pinned, not
chained**: `provider` accepts only `semantic-scholar` or `virsci-snapshot`
and anything else raises, so a `record` / `live` call never switches
backends mid-outage and never silently becomes a different corpus. A
`virsci-snapshot` call (or `mode="frozen"`) raises `FileNotFoundError` when
the frozen corpus is absent instead of degrading to the network; a
Semantic Scholar call raises on an HTTP error instead of degrading to
another provider. There is no arXiv fallback. `mode` is `record`, `live`,
`replay` or `frozen`; `replay` performs no network access and fails when
the checkpoint artifact named by `snapshot_path` is missing or its digest
does not validate. The Semantic Scholar path enriches the first three hits
with up to three citing papers each (one bounded citation hop), keeping
only the edges between retained records. Returns `papers` (the legacy
projection), `survey_snapshot` (`SurveySnapshotV1`),
`survey_snapshot_digest` and `execution_mode`.

```python
result = survey("OpenMP compiler optimization HPC benchmarks")
# Returns: {"papers": [{"title": "...", "abstract": "...", "url": "..."}]}
```

Set `S2_API_KEY` for higher Semantic Scholar rate limits. `max_papers` is
capped at 15.

`survey` and `generate_ideas` are the skill's **only** registered MCP tools;
`_load_virsci_snapshot_papers` is a plain helper `survey` calls directly and
must never be agent-visible. `tests/test_server.py` pins both facts through
`mcp.list_tools()` (a lost/misplaced `@mcp.tool()` decorator has shipped
before).

#### `generate_ideas(topic, papers, experiment_context="", n_ideas=3, n_agents=4, max_discussion_rounds=2, max_recursion_depth=0, survey_snapshot=None, survey_snapshot_ref="", seed=None, generation_mode="auto")`

Generate research hypotheses using VirSci multi-agent LLM deliberation. Multiple AI personas (researcher, critic, expert, synthesizer) debate the research question. In the default `simple_bfts` mode it is called **once** before BFTS starts (pre-BFTS only). In the opt-in `ari_rqgm` mode with `proposal_router.generators.virsci.enabled: true`, the core-side `VirSciAdapter` additionally calls `survey` + `generate_ideas` through the ProposalRouter's event-triggered, budget-capped dispatch — see [VirSci Integration](../guides/virsci_integration.md).

Model: `ARI_LLM_MODEL` env > `LLM_MODEL` env > `ollama_chat/qwen3:32b`.

The literature input is frozen before the first model call. Pass either the
exact `SurveySnapshotV1` object `survey` returned (`survey_snapshot`), the
checkpoint-relative reference to a verified one (`survey_snapshot_ref`, which
requires `ARI_CHECKPOINT_DIR` and cannot be combined with inline literature),
or the legacy inline `papers` list; with all three empty the tool performs one
pinned Semantic Scholar record operation rather than falling back to another
provider. `seed` is recorded in the generation lock. `generation_mode` is
`auto`, `default` or `virsci` — anything else raises, and explicit `virsci`
fails closed instead of degrading to the re-impl loop. `n_ideas` is clamped to
1–5, `n_agents` to 2–4, `max_discussion_rounds` to 0–3, and
`max_recursion_depth` is reserved for recursive orchestration (currently
unused).

#### VirSci-live (vendor-wrap) — opt-in real engine

`generate_ideas` has two interchangeable engines behind the same idea contract.
The default (**reimpl**, behaviour unchanged) runs the lightweight re-implemented
discussion loop. The opt-in (**real_wrap**) instead runs VirSci's *actual*
mechanism — `Platform.select_coauthors` (freshness team formation) +
`Team.generate_idea` (multi-agent deliberation) from the vendored, **unedited**
`vendor/virsci` — grounded on a **live** Semantic Scholar snapshot (corpus +
SPECTER2 cosine retrieval index + author profiles + co-author graph).

- **Default OFF** = behaviour byte-identical to before. Enable with env
  `ARI_IDEA_VIRSCI_REAL=1`, the CLI flag `--virsci-live`, or the GUI experiment
  wizard "VirSci live" toggle (Scope/Resources step; persisted to
  `launch_config.json`).
- **Degrades safely.** On missing deps (`virsci` pip extra absent) or any runtime
  error, the skill falls back to the reimpl loop. The `idea.json` contract is
  identical either way. Beyond that, the live-snapshot build now **fails loud on an
  empty / 0-paper S2 fetch** (a 429 rate-limit, network failure, or no search hits):
  rather than silently writing a "successful" 0-paper manifest with placeholder
  authors — which would run VirSci fully ungrounded yet record it as a `real_wrap`
  success — it raises so `generate_ideas` degrades **visibly** to the reimpl loop. A
  cached manifest with `n_papers == 0` is treated as a poisoned cache and never reused
  (it is rebuilt). When the topic `/paper/search` is throttled (S2 429) but the survey
  already vetted paper ids, the build recovers by fetching a seed corpus through
  `/paper/batch` (keyed by id, so more targeted and less likely to be throttled),
  recorded as `seed_fallback` in `virsci_snapshot/snapshot_manifest.json`.
- **Path reporting.** `idea.json` carries `virsci_integration_status`:
  `"real_wrap"` when the vendor engine ran, or `"reimpl: …"` (with the reason)
  when the reimpl loop was used.
- **LLM:** deliberation follows the per-phase Idea model (`ARI_MODEL_IDEA`);
  engine calls route through litellm so ARI's cost tracker captures them.
- **Scope:** a single live snapshot — no era-split / no paper-parity (those are
  VirSci's retrospective-benchmark artifacts, out of scope). freshness/diversity
  come from the S2 author profiles + co-author graph.
- **Deps:** the `virsci` pip extra (faiss-cpu, transformers, torch, loguru,
  sqlalchemy); SPECTER2 weights are fetched at runtime; needs
  `SEMANTIC_SCHOLAR_API_KEY` / `S2_API_KEY` (for `embedding.specter_v2`) and an
  OpenAI-compatible LLM endpoint (the ARI CLI shim).

Env knobs (only the toggle is required; the rest are tunable — see
[Environment Variables](environment_variables.md)):

| Variable | Default | Purpose |
|---|---|---|
| `ARI_IDEA_VIRSCI_REAL` | unset (off) | toggle the real vendor-wrap path |
| `ARI_IDEA_VIRSCI_K` | `7` | discussion turns (vendor `group_max_discuss_iteration`) |
| `ARI_IDEA_VIRSCI_TEAM_SIZE` | `3` | max team members (vendor `max_teammember`) |
| `ARI_IDEA_VIRSCI_N_AUTHORS` | `16` | author pool for `select_coauthors` |
| `ARI_IDEA_VIRSCI_N_PAPERS` | `800` | SPECTER2 retrieval corpus size |
| `ARI_IDEA_VIRSCI_MAX_TEAMS` | `n_ideas` | cap on teams driven through `generate_idea` |
| `ARI_IDEA_VIRSCI_SPECTER2_MODEL` | `allenai/specter2_base` | local query embedder |

CLI flags on `ari run`: `--virsci-live` / `--no-virsci-live`, `--virsci-k`,
`--virsci-team-size`, `--virsci-n-authors`, `--virsci-n-papers`.

---

## ari-skill-evaluator

Metric contracts, deterministic claim gates, and evidence-grounded semantic
review. **LLM: Split** — the two contract tools are separated so that the one
which *decides* is deterministic and the one which *guesses* cannot admit its
own guess.

### Tools

#### `make_metric_spec(experiment_text, checkpoint_dir="", proposal_json=None, reviewer="")`

Materialize one frozen metric contract. **Deterministic, no LLM.** The
experiment Markdown is always parsed for `metric_keyword` /
`min_expected_metric` and friends, but that parser output is *evidence*, not a
contract. What gets frozen depends on what exists:

- an idea-owned `ari.research-contract/v1` at the checkpoint whose
  `admission_status` is `admitted` → its `metric_gate_projection` is used (a
  contract still awaiting human review is refused, not silently accepted);
- otherwise a `proposal_json` **plus** a non-empty `reviewer` → the proposal is
  admitted under that reviewer's name and an admission decision is recorded;
- otherwise an already-persisted `metric_contract.json` → read back, migrating
  the legacy shape through a reader that does not rewrite the file;
- otherwise the parser result alone, returned with `contract_frozen: false`,
  `admission_status: "human-review-required"` and
  `proposal_tool: "propose_metric_contract"`.

Persisting is mint-once: writing a projection whose `projection_digest` differs
from the one already at `{checkpoint}/metric_contract.json` raises rather than
overwrites.

```python
result = make_metric_spec(
    open("experiment.md").read(),
    checkpoint_dir="/path/to/checkpoint",
)
# Frozen: {
#   "metric_keyword": "GFLOP_per_s",          # the contract's metric name
#   "metric_unit": "GFLOP/s", "metric_direction": "higher",
#   "expected_metrics": ["GFLOP_per_s", ...], # name + required_evidence
#   "expected_params": [],
#   "min_expected_metric": 50000.0,
#   "scoring_guide": "...",
#   "metric_contract": {...}, "metric_contract_digest": "...",
#   "projection_digest": "...", "contract_frozen": True,
#   "contract_source": "idea.research-contract/v1",
#   "admission_status": "admitted"
# }
# Not frozen: the parser fields plus
#   {"metric_contract": None, "contract_frozen": False,
#    "admission_status": "human-review-required",
#    "proposal_tool": "propose_metric_contract"}
```

`parser_result` is always carried alongside, so a reader can tell what the text
said from what the contract admitted. `expected_metrics` on the frozen path is
the contract's own `name` plus its `required_evidence`, deduplicated —
not a second extraction. `expected_params` is `[]` on every path; the typed
`params` / `measurements` split reaching `transform-skill::nodes_to_science_data`
comes from `coding-skill::emit_results` (D contract).

The frozen contract is **idea-owned** — built from the idea's `primary_metric`,
its structured `falsifiable_claims`, and the `correctness_required` /
`ceiling_must_be_measured` requirement flags — so an agent cannot drop a claim
or requirement to dodge the check. It is read back by
`transform-skill::nodes_to_science_data` (grafted onto
`science_data.metric_contract`) and enforced by the deterministic hard gate.

#### `propose_metric_contract(idea_json=None, checkpoint_dir="", model="", model_revision="")`

The explicit LLM proposal step, for the case where no typed contract exists
yet. **LLM: Yes**. Reads the idea from `idea_json` (an object, a path, or a
JSON string; bare text is accepted as `idea_text`) or falls back to
`{checkpoint_dir}/idea.json`, and emits a `MetricContractProposalV1` recording
the source idea digest, evidence digest, model, model revision, prompt digest,
the proposed contract and the model's own `confidence`. Written to
`{checkpoint}/metric_contract_proposal.json`.

Two refusals define it. It raises on an idea that already carries
`typed_schema_version: "ari.research-contract/v1"` — a typed idea already owns
its contract and an LLM does not get to restate it. And `requires_human_review`
is always `true`: the output is inert until a human passes it back through
`make_metric_spec` with a `reviewer`. Nothing here writes
`metric_contract.json`.

Model: `model` arg > `ARI_MODEL_METRIC_PROPOSAL` env > `ARI_LLM_MODEL` env >
`gpt-4o-mini`, called at `temperature=0.0`.

#### `claim_evidence_hard_gate(checkpoint_dir, paper_path, science_data_json="", paper_claim_links_path="", figures_manifest_json="", policy=None, phase="draft")`

Deterministic claim/evidence hard gate (execution data fidelity). **No LLM**. Verifies that science_data claims reference executed nodes, re-computes `numeric_assertions` from `results.json` and checks the paper-reported numbers within tolerance, detects uncovered result numbers per section policy, and checks figure existence. Thin MCP wrapper over ari-core's `run_hard_gate` (`ari.public.claim_gate`). In strict mode the `final` phase returns `{"error": ...}` when blocking errors exist so the stage runner raises and `finalize_paper` is skipped; the `draft` phase and warn/off mode never block. Writes `evaluation/claim_evidence_hard_gate_{phase}.json`.

#### `evidence_grounded_semantic_review(checkpoint_dir, paper_path, science_data_json="", hard_gate_path="", paper_claim_links_path="", phase="initial", model="", model_revision="")`

Non-blocking, evidence-grounded semantic review. **LLM: Yes**. The LLM detects over-claiming / interpretation issues / unregistered strong claims grounded in the hard-gate evidence, WITHOUT touching the independent text reviewer; it does not re-check numbers. Emits `suggested_revisions` consumed by `paper_refine` plus scores. Writes `evaluation/evidence_grounded_semantic_review.json`. Never blocks. Only `checkpoint_dir` and `paper_path` are required. `model` pins the reviewing model for this call (otherwise `ARI_MODEL_SEMANTIC_REVIEW` > `ARI_LLM_MODEL` > `gpt-4o-mini`) and `model_revision` records which revision of it ran; both are written into the report alongside the prompt, evidence and hard-gate digests, so a review is attributable to an exact model identity.

---

## ari-skill-paper

LaTeX paper generation, compilation, and review (post-BFTS only). **LLM: Yes**.

### Tools

#### `list_venues()`

Returns available venue configurations.

Supported venues: `neurips` (9 pages), `icpp` (10 pages), `sc` (12 pages), `isc` (12 pages), `arxiv` (unlimited), `acm` (10 pages).

#### `get_template(venue)`

Returns the LaTeX template for a venue.

#### `compile_paper(tex_dir, main_file="main.tex", figures_manifest_path="")`

Run pdflatex compilation. Returns `success`, `pdf_path`, `log` and the typed
`compile` record. A missing directory or main file comes back as
`success: False` with the reason in `log` rather than raising.

#### `check_format(venue, pdf_path)`

Validate paper format against venue requirements (page count, etc.). An
unknown `venue` raises with the valid list attached.

#### `write_paper_iterative(workspace_root, science_data_path, figures_manifest_path, references_path, ear_manifest_path, rubric_id, experiment_summary="", context="", verified_context_path="", venue="arxiv", max_revision_rounds=2, author_name="", writer_prompt_override="", decode_seed=0)`

Full paper generation, and the primary pipeline tool. **LLM: Yes**. There is no
per-section drafting, review or revision tool: the loop lives inside this call.
It fills the venue template in one LLM call — every `FILL_*_START … FILL_*_END`
block at once — then runs `max(1, max_revision_rounds)` reflection rounds over
the *same* message history, each round feeding back compile errors, BibTeX
status, figures available but unreferenced, figure references that match no
file, and chktex output, until the model answers `I am done`. There is always
at least one reflection round; `max_revision_rounds=0` does not skip it.

Every input arrives as a path resolved inside the closed `workspace_root`
(`science_data_path`, `figures_manifest_path`, `references_path`,
`ear_manifest_path`, optional `verified_context_path`) rather than as inline
JSON. Two contracts are enforced against each reflection: a revision that
changes or drops a `% CLAIM:Cx:NCx` comment is rejected, and so is one that
edits, adds or removes a renderer-owned figure block.

`writer_prompt_override` and `decode_seed` are additive seams, and their
defaults are a frozen compatibility contract rather than a recommended
configuration: `""` and `0` must reproduce the pre-parameter tool byte for
byte. `paper_refine` takes the same pair with the same defaults.

`writer_prompt_override=""` loads the bundled `paper_writer.md`; a non-empty
value **replaces** it as the reflection system prompt. The initial
template-fill call keeps its own `fill_in_writer` prompt either way, so the
override reaches the reflection loop only. It is a plain instruction string,
not governance — `tests/test_writer_prompt_override.py` asserts the default
reflection prompt is exactly the loaded `paper_writer.md` plus the language
directive, that a non-empty override leaves no `paper_writer.md` body in that
call, and that importing the skill drags in no `ari.rqgm` module.

`decode_seed=0` keeps the linear, unseeded behaviour — no `seed` key in the
payload at all. A non-zero value is passed to litellm on both the initial
authoring call and every reflection call, so callers generating a *population*
of drafts get distinct samples instead of K copies; litellm's `seed` is
best-effort and provider-dependent, so it buys diversity, not bit-exact replay.
The parameter exists because of the opposite failure, recorded in the
regression note on `tests/test_server.py::test_a_non_zero_decode_seed_reaches_the_payload`:
a caller that recorded a per-draft seed the request payload never carried is
"what made 8 seeds collapse to 1 draft". A recorded seed is only meaningful if
it reached the payload. No skill test covers this tool's seed plumbing; the
payload assertions live on `paper_refine` (below).

Returns `latex`, `sections`, `reviews`, `revision_counts`, `bib`, `key_list`
and the draft `paper_build`.

#### `review_compiled_paper(rubric_id, tex_path="", pdf_path="", figures_manifest_json="", experiment_summary="", vlm_findings_json="", num_reflections=None, num_fs_examples=None, num_reviews_ensemble=None)`

Rubric-driven paper review compatible with the **AI Scientist v1/v2** pipeline
(Nature / arXiv:2408.06292 Appendix A.4). Loads a YAML rubric from
`ari-core/config/reviewer_rubrics/<rubric_id>.yaml`, renders prompts from the
rubric's `score_dimensions` / `text_sections` / `decision` schema, injects VLM
per-figure findings as reviewer notes, optionally prepends few-shot example
reviews, runs a self-reflection loop, then normalises the output to a
rubric-stable JSON schema.

Bundled rubrics (23 YAMLs in `ari-core/config/reviewer_rubrics/`):

| Family | Rubric IDs |
|---|---|
| ML conferences | `neurips` (default, v2-compatible), `iclr`, `icml`, `cvpr`, `acl` |
| Systems / HPC | `sc`, `osdi`, `usenix_security` |
| Theory / graphics | `stoc`, `siggraph` |
| HCI / robotics | `chi`, `icra` |
| Economics / humanities journals | `aer`, `qje`, `econometrica`, `apsr`, `ahr`, `pmla`, `philreview` |
| Journals / generic | `nature`, `journal_generic`, `workshop`, `generic_conference` |

Add a new venue by dropping `<id>.yaml` into `reviewer_rubrics/` — no code
changes required. Each rubric declares `score_dimensions`, `text_sections`,
`decision` rules, execution parameters, and a SHA256 hash for P2 determinism.

Rubric resolution is explicit and has no fallback chain. `rubric_id` is the
first, required argument; `resolve_rubric` refuses an empty one outright
("migrate legacy ARI_RUBRIC/default config to an explicit workflow input")
rather than reaching for an environment variable, a `neurips` default, or a
built-in `legacy` schema. Which rubric graded a paper is therefore always
recorded in the call that made it.

Old launch or workflow documents that relied on that chain are converted
offline: `src/rubric_migration.py::migrate_legacy_rubric_selection` walks
`paper_rubric` → `rubric_id` → `ARI_RUBRIC` → the `neurips` pre-v1 default,
validates the result, and returns an explicit `paper_rubric` field plus a
record naming which `source` supplied it. It is a one-off migration helper, not
a runtime fallback.

#### Symmetric author / reviewer venue conditioning (unreleased)

`prompt_overrides` carries two parallel fields:

- `system_hint` — injected into peer-review prompts by `review_engine`
  (existing behaviour).
- `author_hint` — appended to `write_paper_iterative`'s drafting system
  prompt as a dedicated `VENUE RUBRIC AUTHOR GUIDANCE` block. Tells the
  drafter what reviewers will look for, so the paper is written to make
  those signals easy to surface.

Empty `author_hint` adds no block at all, leaving the drafting prompt's
bare `Target venue: X.` line as the only venue signal. SC and NeurIPS
ship calibrated `author_hint` blocks; remaining venues are empty and can
be filled in incrementally without touching code.

Nature Ablation defaults (best-config rationale):

- `num_reflections: 5` — +2% balanced accuracy
- `num_fs_examples: 1` — +2% balanced accuracy (1-shot from ICLR reviewer guidelines)
- `num_reviews_ensemble: 1` — ensemble does not improve accuracy, only variance
- `temperature: 0.75`

Model: `ARI_LLM_MODEL` env > `LLM_MODEL` env > `ollama_chat/qwen3:32b`.

**Ensemble + Area Chair meta-review (built in):** `review_compiled_paper` runs
N independent reviewer agents via the ensemble path (temperature jitter, AI
Scientist v1 best-config style). When N>1, it also runs the Area Chair
meta-review internally and attaches `ensemble_reviews: [...]` and
`meta_review: {...}` to the output. N resolves as: explicit arg >
`ARI_NUM_REVIEWS_ENSEMBLE` env > `rubric.params.num_reviews_ensemble`
(defaults to 1). N=1 is equivalent to a single reviewer.

#### `list_rubrics()`

Returns the list of available rubrics (id, venue, domain, version, SHA256
hash, path). Used by the viz API `/api/rubrics` and the New Experiment wizard
dropdown.

#### `inject_code_availability(tex_path, ref="", sha256="", doi="", license_id="", checkpoint_dir="")` — v0.7.0

Runs as the `finalize_paper` stage. Auto-loads the curated bundle's
`ref` / `bundle_sha256` / `doi` from `ear_published/manifest.lock` +
`publish_record.json` and injects machine-readable `\codeavailability{}`,
`\codedigest{}`, `\coderef{}` macros plus a human-readable Code
Availability section into `full_paper.tex`. The macros let downstream
tools (`ari clone`, third-party readers) recover the bundle without
trusting the registry — the digest is the trust anchor. Skips silently
when no curated bundle exists (so v0.6.0 checkpoints keep building).

#### `merge_reviews(review_report_path, vlm_review_path="", hard_gate_path="", semantic_review_path="")` — v0.7.0

Post-hoc structural merge of `review_report.json` (text reviewer) and
`vlm_review.json` (VLM figure review). Purely deterministic — no LLM.
Attaches `vlm_figure_review` and `_review_composition` metadata so the
GUI / CLI can show both outputs with clear source attribution. The
upstream stages stay independent (matching AI Scientist v2's
`perform_review` contract) and are reconciled here.

Only `review_report_path` is required; the other three are optional and the
two-argument v0.6.0 call still works. The text and VLM reviews stay under
`independent_reviews` and are never modified. `hard_gate_path`
(`claim_evidence_hard_gate`) and `semantic_review_path`
(`evidence_grounded_semantic_review`) are reported separately under
`evidence_grounded_reviews`, and the two together produce the unified
`suggested_revisions` list `paper_refine` consumes — omit them and that list
has nothing to carry.

#### `link_paper_claims(tex_path="", science_data_json="", figures_manifest_json="", output_path="")` — v0.9.0

Reconciles `% CLAIM:Cx:NCx` anchors against science_data claims and builds
`paper_claim_links.json` (anchors / writer_assertions / numeric_mentions /
figure_refs / unresolved_anchors / uncovered_numeric_candidates) consumed by
the claim hard gate. **Deterministic, no LLM**. The transform-stage
`science_data.json` is never mutated; figure binding is recorded here. Run after
`write_paper` (draft) and again after `paper_refine` (final). Degrades to a
valid empty result on failure (never error-only) so it cannot cascade-skip the
finalize chain.

#### `paper_refine(tex_path="", suggested_revisions_json="", merged_review_path="", semantic_review_path="", venue="arxiv", writer_prompt_override="", decode_seed=0)` — v0.9.0

Anchor-preserving revision pass that applies `suggested_revisions` (from
`evidence_grounded_semantic_review` / the merged review). **LLM: Yes**. Explicit
`replace "X" with "Y"` substitutions are applied deterministically first, then a
bounded multi-pass LLM find/replace handles the remainder; every `% CLAIM`
anchor present in the draft must survive (anchor-dropping edits are rejected and
on net anchor loss the original paper is kept). Math-safe underscore escaping
skips `\( … \)` / `\[ … \]` and math environments. The refined LaTeX is returned
under `latex` (the draft is preserved as `full_paper.draft.tex`). `refine_passes`
reports how many LLM passes ran (at most 3), and any explicit substitution whose
old span still occurs comes back under `unaddressed_substitutions`.

Two additive arguments leave the default path byte-identical when unset, and
the defaults are a frozen compatibility contract rather than a tuning knob.
`writer_prompt_override` is a plain instruction string that, when non-empty, is
**prepended** to the bundled `global_coherence.md` prompt so the supplied
paper-writer text leads the refine — note the asymmetry: the same argument name
*replaces* the bundled prompt in `write_paper_iterative` but only prefixes it
here. `decode_seed` stays out of the payload at `0`, and a non-zero value
samples the refine under its draft's seed so a refine inherits its parent's
decode identity.

These are the two seams the skill suite actually pins.
`tests/test_server.py` covers the payload half in both directions: at `0` no
captured `litellm.acompletion` call carries a `seed` key and the messages are
identical to omitting the argument entirely, and at a non-zero value every
captured call carries exactly that seed — the assertion that stops a recorded
seed from being a seed the model never saw.
`tests/test_writer_prompt_override.py` covers the prompt half, asserting the
default system prompt is exactly `global_coherence.md` plus the language
directive with no prefix, and that a non-empty override produces
`override + "\n\n" + global_coherence + directive`.

#### `finalize_paper_build(workspace_root, draft_build_path, tex_path, bib_path, pdf_path, compile_record_path, figures_manifest_path, claim_links_path, hard_gate_path, text_review_path, visual_review_path, semantic_review_path, refinement_call_path="", visual_passing_score=0.7, output_path="paper_build.json")`

The last stage of the paper phase: turn the draft `PaperBuildV1` that
`write_paper_iterative` returned into the immutable final record.
**Deterministic, no LLM**. Every path resolves inside the closed
`workspace_root`, and every artifact the draft declared — its inputs, each
recorded revision's TeX and bibliography, each recorded model call — is
re-verified against its digest before anything new is read. It then hashes the
final tex / bib / PDF, parses the compile record, and requires the claim links
document to be `ari.paper-claim-links/v1` from the `link_paper_claims` stage.

Finalization is a judgement, not a formality. `blocking_reasons` accumulates
each failure — a final revision that dropped a canonical figure ID or changed
mathematical content, a hard gate that was disabled or reported blocking
findings, unresolved claim anchors, uncovered numeric result mentions, a
compile that did not complete, a PDF whose digest differs from the compile
record's, a visual review with failed targets or a score below
`visual_passing_score`. Any reason at all makes the status `blocked` (or
`compile-error` when a compile reason is among them) instead of `finalized`,
and the MCP tool then raises with the reasons joined into the message. The
record is written either way, so a blocked build is auditable rather than lost.

##### Few-shot corpus management

The files under `ari-core/config/reviewer_rubrics/fewshot_examples/<rubric>/`
can be managed from the **New Experiment Wizard → Paper Review → Few-shot
Examples** sub-panel (GUI) or with `scripts/fewshot/sync.py` (CLI).

GUI actions:

- **Auto-sync** — server-side runs `scripts/fewshot/sync.py --venue <rubric>`
  which pulls entries declared in `scripts/fewshot/manifest.yaml`. By default
  this includes the three AI Scientist v2 fewshot papers
  (`132_automated_relational`, `2_carpe_diem`, `attention`) downloaded from
  the Apache-2.0 `SakanaAI/AI-Scientist-v2` repo.
- **Upload** — accepts a rubric-shaped JSON review form plus an optional
  `.txt` excerpt and optional PDF (base64). The JSON is stamped with
  `_source: "GUI upload (rubric=<id>)"` for provenance.
- **Delete** — removes every sibling file of an example.

Backing REST endpoints:

- `GET  /api/fewshot/<rubric>`              list examples
- `POST /api/fewshot/<rubric>/sync`          sync from manifest
- `POST /api/fewshot/<rubric>/upload`        upload one example
- `POST /api/fewshot/<rubric>/<example>/delete` delete

All endpoints refuse any rubric not present in `reviewer_rubrics/` and strip
`../` sequences / slashes from both rubric and example ids.

---

## ari-skill-paper-re

Reproducibility grading via PaperBench (arXiv:2504.01848) **SimpleJudge**.
**LLM: Yes** (the judge is an LLM call inside the upstream
`SimpleJudge`; ARI itself adds no extra LLM calls in this skill).

v0.7.0 replaces the v0.6.0 LLM-driven verdict path
(`extract_repro_config` → `react_driver` → `build_repro_report`) with a
deterministic chain whose grading core is taken from PaperBench:

```
ors_generate_rubric  (replicate-skill)    → ors_rubric.json + ors_rubric.meta.json
ors_audit_rubric     (replicate-skill)    → a separate audit document; ors_rubric.json is never mutated
ear_publish          (transform-skill)    → bundle.tar.gz + publish_record.json (local-tarball default)
ors_seed_sandbox     (paper-re-skill)     → repro_sandbox/{reproduce.sh, code/...}
                                              (deterministic; fetch_code_bundle ← publish_record.json)
ors_build_reproduce  (paper-re-skill)     → repro_sandbox/{reproduce.sh, source files}
                                              (LLM fallback; skipped if seed populated reproduce.sh)
ors_run_reproduce    (paper-re-skill)     → ors_phase1.json   (Phase 1: sandbox-execute reproduce.sh)
ors_grade            (paper-re-skill)     → ors_grade.json    (Phase 2: SimpleJudge over the rubric leaves)
```

`ors_audit_rubric` checks the rubric everything downstream is graded
against: it flags each leaf `vague_qualifier` / `no_paper_evidence` /
`duplicate` (deterministic) and `unverifiable` (one LLM call per leaf),
and reports `regen_recommended` when >20% of leaves are flagged. The frozen
rubric is **not** rewritten — the findings land in a separate
`ari.replication-rubric-audit/v2` document (default path:
`<rubric_path>.audit.json`), which binds the rubric and paper digests so the
two cannot drift apart. It is a signal, not a gate — grading proceeds either
way. Point it at a different model than the generator with
`ARI_MODEL_RUBRIC_AUDIT`.

EAR-on runs flow through `ors_seed_sandbox` (deterministic seed); the
LLM `ors_build_reproduce` skips when reproduce.sh is already present,
so it only fires on EAR-off runs (paper-only reproduction).

**v0.7.2 HPC additions.** Both `build_reproduce_sh` and `run_reproduce`
consume the optional `reproduce_contract.execution_profile` block
([reference](execution_profile.md)):

- The agent prompt receives an `EXECUTION PROFILE` JSON block + a live
  `CLUSTER SHAPE` snapshot from `SLURM_JOB_NUM_NODES` / `SLURM_NTASKS`
  / `nvidia-smi`, plus a `COMPUTE-NODE EXECUTION CONVENTIONS` footer
  (shared FS, srun-first, conda activation, multi-node fan-out,
  timeout wrapping). The full appendix lives in
  `ari-skill-paper-re/src/_replicator_agent.py::_format_hpc_appendix`.
- For `kind ∈ {mpi, mpi_gpu}` an MPI aggregation skeleton
  (`prompts/mpi_aggregate_skel.py`) is auto-copied into
  `submission/mpi_aggregate.py`.
- `run_reproduce` takes the allocation shape as typed arguments rather
  than raw flags — `nodes`, `ntasks`, `ntasks_per_node`, `nodelist`,
  `exclude_nodes`, `exclusive`, `gpus_per_task`, `gpus_per_node`,
  `gpu_type`, `memory_gb_per_node`, `memory_gb_per_cpu`, `constraint`,
  `hint`, `account`, `qos`, `reservation`, `module_loads` — each of which
  auto-resolves from `execution_profile` when left at its default.
  `cpu_bind` / `mem_bind` are refused with the instruction to place those
  srun job-step settings in `reproduce.sh`. The former `extra_sbatch_args`
  escape hatch is deprecated down to four translatable prefixes
  (`--account=`, `--qos=`, `--reservation=`, `--hint=`); anything else
  raises, pointing at the typed field.

PaperBench is vendored as a git submodule under
`ari-skill-paper-re/vendor/paperbench`; the bridge module
`_paperbench_bridge.py` adapts the upstream `TaskNode` /
`SimpleJudge` API to ARI's rubric envelope. The main per-leaf grading
completer routes through LiteLLM (`_litellm_completer.py`) so any
provider works (`gpt-5-mini`, `anthropic/claude-...`, `gemini/...`,
`ollama/...`); the two structured score-parsing completers are built from
the same `judge_model`, differing only in their `response_format`
(`ParsedJudgeResponseInt` / `ParsedJudgeResponseFloat`).

### Tools

#### `fetch_code_bundle(ref="", sha256="", dest="", checkpoint_dir="", overwrite=False)`

Pre-populates the reproducibility sandbox with a curated EAR bundle
via `ari.clone` — deterministic, no LLM. Two ways to point at the
bundle:

- **Direct ref**: `ref="file:///path/to/bundle.tar.gz"` /
  `ref="ari://0ccabb16…"` / `ref="gh:owner/repo"` / `ref="https://…"`.
- **Auto-load from publish_record.json** (v0.7.0+): pass
  `checkpoint_dir={checkpoint}`; ref + sha256 are read from
  `{checkpoint_dir}/publish_record.json` (the file `ari ear publish`
  writes). Mirrors the convention `inject_code_availability` uses.

Skips with `populated=False, skipped_reason=...` when `dest/reproduce.sh`
already exists (composes after `ear` seed / a prior bundle); refuses to
clobber a non-empty dest unless `overwrite=True`.

```python
# Workflow stage: auto-load from the local-tarball backend's record.
result = fetch_code_bundle(
    checkpoint_dir="/path/to/checkpoint",
    dest="/path/to/checkpoint/repro_sandbox",
)
# Returns: {"populated": True, "dest": ..., "bundle_sha256": ..., "files": ...}
```

#### `build_reproduce_sh(paper_path="", paper_text="", rubric_path="", output_dir="", model="", time_limit_sec=43200, iterative_agent=False, max_steps=0, sandbox_kind="auto", container_image="", overwrite=False)`

**LLM-driven replicator** (v0.7.0+). Sibling of `fetch_code_bundle`:
both target `repro_sandbox/`. Reads the paper (and the rubric's
`reproduce_contract.expected_artifacts` when `rubric_path` is given)
and writes a self-contained `reproduce.sh` + supporting source files
into `output_dir`.

Routes through LiteLLM, so any provider works. Model resolves
`model` arg > `ARI_MODEL_REPLICATOR` env > `ARI_LLM_MODEL` env >
`gpt-5-mini`. Output JSON is sanity-checked (every file path is
filesystem-safe ASCII, no `..`, `reproduce.sh` is shebanged + has
`set -euo pipefail`, total content < 200 KB).

Skips with `populated=False, skipped_reason=...` when `output_dir/reproduce.sh`
is already present, so it composes cleanly after `fetch_code_bundle` /
EAR pre-populate. The workflow's `ors_build_reproduce` stage sets this
ordering — when `include_ear=true`, the EAR-seeded reproduce.sh wins;
when off, the LLM falls through.

`sandbox_kind` is `auto` / `local` / `apptainer` / `slurm` and selects where
the agent rollout itself runs. `container_image` is honoured only by the
`apptainer` rollout, where it is an immutable local SIF or a digest-pinned
remote URI (`ARI_PHASE1_APPTAINER_IMAGE` supplies it when the argument is
empty); `local` and `slurm` ignore it. There is no legacy `apptainer_image`
argument: the name was deleted from the signature and occurs nowhere in the
skill, so `container_image` is the only way to name an image here.

```python
result = build_reproduce_sh(
    paper_path="full_paper.tex",
    rubric_path="ors_rubric.json",
    output_dir="repro_sandbox",
)
# Returns: {populated, output_dir, files, expected_artifacts,
#           max_runtime_sec, language, model, prompt_sha256, notes, warnings}
```

#### `run_reproduce(rubric_path, repo_dir, sandbox_kind="", container_image="", timeout_global_sec=0, network_policy="deny", network_isolation_attested=False, partition="", cpus=0, walltime="", …SLURM flags)`

**Phase 1**. Executes `repo_dir/reproduce.sh` in a sandbox; captures
`reproduce.log` and lists artefacts; reports any
`expected_artifacts` (from the rubric envelope) that did not appear.

Sandbox priority (`auto`, the default): `slurm` (when sbatch is on
PATH AND `ARI_SLURM_PARTITION` is set — the same partition BFTS used)
→ `docker` (when daemon usable and not on HPC) → `apptainer` →
`singularity` → `local`. Override with the `sandbox_kind` argument
or `ARI_PHASE1_SANDBOX`. There is no default image: a container sandbox
requires an immutable, digest-pinned one — `container_image`, else
`ARI_PHASE1_DOCKER_IMAGE` for `docker` and `ARI_PHASE1_APPTAINER_IMAGE` for
`apptainer` / `singularity`. A docker reference must be a full
`sha256:<image-id>` or be pinned with `@sha256:<digest>`; an apptainer
reference must be a local immutable SIF or be pinned the same way. An empty
one is refused rather than defaulted.

**Network** is denied by default: `network_policy` is `deny` unless the call
explicitly admits an unisolated substrate with `network_policy="inherit"`, and
`network_isolation_attested` records that the substrate's isolation was
attested rather than assumed. The source tree is snapshotted read-only and the
run happens in a private attempt tree, so an identical successful plan replays
idempotently and a failed plan gains a linked retry attempt.

**SLURM dispatch** is a handoff to the typed scheduler lifecycle rather than a
private `sbatch` of its own: the execution request becomes a `JobRequestV1`
with a `ResourceRequestV1` built from the resolved arguments, is submitted
through the same `SlurmScheduler` `ari-skill-hpc` uses (its own ledger at
`{repo_dir}/../.ari-hpc/paper-re-jobs-v1.json`), and is polled to a terminal
state; the verified scheduler logs are then materialised into `reproduce.log`.
The result carries `handle_id`, `job_id`, `request_digest`, `handoff_digest`,
`execution_identity` and `unmapped_policies`, and a job that outlives the
timeout is cancelled and reported with `timed_out: true`. Partition resolves
arg > `ARI_SLURM_PARTITION` > `{checkpoint_dir}/launch_config.json`; `cpus`
resolves arg > `ARI_SLURM_CPUS` (default `8`); `walltime` resolves arg >
`ARI_SLURM_WALLTIME` > an `HH:MM:SS` string derived from the timeout.

```python
result = run_reproduce(
    rubric_path="ors_rubric.json",
    repo_dir="repro_sandbox",
)
# Returns: {executed, exit_code, log_path, artifacts, missing,
#           elapsed_sec, sandbox_kind, [partition, cpus, walltime, timed_out]}
```

#### `grade_with_simplejudge(rubric_path, repo_dir, paper_path="", paper_text="", judge_model="", n_runs=0, skip_negative_control=False, code_only=False)`

**Phase 2**. Runs PaperBench `SimpleJudge` over the (post-Phase-1)
repo + reproduce.log + paper. `n_runs` iterations (the argument, else
`ARI_JUDGE_N_RUNS`, else 1; 1–100) are
averaged using PaperBench's weighted leaf aggregation; a one-off
**negative control** (empty repo + trivial `reproduce.sh`) verifies
the rubric does not reward absence of work — both controls must
score under 5% (`passed=true`).

```python
result = grade_with_simplejudge(
    rubric_path="ors_rubric.json",
    repo_dir="repro_sandbox",
    paper_path="full_paper.tex",
)
# Returns: {ors_score, raw_score, leaf_grades, judge_model, n_runs,
#           rubric_sha256, elapsed_sec, negative_control: {empty, boilerplate, passed}}
```

Model: `judge_model` arg > `ARI_MODEL_JUDGE` > `ARI_LLM_MODEL` > `gpt-5-mini`.

The main per-leaf grading completer routes through LiteLLM
(`_litellm_completer.py`), so any provider LiteLLM understands works
(`gpt-5-mini`, `anthropic/claude-opus-4-7`, `gemini/gemini-2.5-pro`,
`ollama/llama3.1`, etc.) — PaperBench's hand-maintained
`CONTEXT_WINDOW_LENGTHS` registry no longer constrains the choice.
The structured int/float score-parsing completers use that same
`judge_model` through the same LiteLLM path — they differ from the main
completer only in carrying a `response_format`
(`ParsedJudgeResponseInt` / `ParsedJudgeResponseFloat`).

---

## ari-skill-replicate

PaperBench-format **auto-rubric generator and auditor** introduced in
v0.7.0. Reads a paper and emits a frozen rubric (`replication_rubric.schema.json`,
a PaperBench `TaskNode` tree wrapped with provenance metadata: paper
sha256, generator model, prompt sha256, optional audit metadata).
**LLM: Yes**.

The rubric is consumed by `ari-skill-paper-re.grade_with_simplejudge`;
together they form the ORS reproducibility flow that replaced the
v0.6.0 `react_driver`-based check.

### Tools

#### `generate_rubric(paper_path="", paper_text="", output_path="", target_leaf_count=0, model="", temperature=0.0, seed=0, paperbench_rubric_id="", max_model_calls=64, subtree_concurrency=4, provider="", model_revision="")`

Produces a PaperBench-compatible rubric. When `target_leaf_count=0`,
the leaf count is auto-computed from paper length (~1 leaf / 75 words,
clamped to [50, 400]).

Generation is always hierarchical: the single-call path is gone, and the frozen
envelope records `strategy: "hierarchical-v2"` / `quality_profile: "calibrated"`
unconditionally. A **skeleton pass** (`prompts/skeleton.md`) defines the root +
direct children (one node per major contribution / experiment) with a per-child
leaf budget, then **parallel subtree passes** (`prompts/subtree.md`,
`subtree_concurrency` at a time) recursively populate each direct child's
subtree. A merge step joins the populated subtrees back into the skeleton;
leaves whose `quote` or `requirements` violate the schema's `minLength=10` are
dropped (a handful per run is normal), as are leaves that cannot be bound to an
exact paper span or a declared external prerequisite. `max_model_calls` bounds
the whole run, and every prompt/response pair is retained under `.ari-rubric/`
and listed in `generator.calls`.

`paperbench_rubric_id` (unreleased) selects a venue-conditioned template
from `ari-core/config/paperbench_rubrics/<id>.yaml`. Empty string =
bundled prompt verbatim (back-compat). Non-empty values load the YAML
and inject `prompt_overrides.system_hint` / `prompt_overrides.leaf_style`
into the skeleton + subtree prompts via `{VENUE_HINT}` placeholders.
This mirrors the `reviewer_rubrics/` venue pattern already used by
`ari-skill-paper` for peer review, so the same `venue → YAML → prompt`
flow is now available for the rubric generator. Shipped templates:
`generic` (back-compat), `sc` (HPC paper-audit, 6 axes), `neurips`
(ML reproducibility, 6 axes), `nature` (wet-lab, 5 axes). See
[`docs/reference/rubric_schema.md`](rubric_schema.md#venue-conditioned-templates)
for the YAML schema.

#### `audit_rubric(rubric_path, paper_path="", paper_text="", auditor_model="", output_path="", max_model_calls=400)`

Independent auditor pass. Flags problematic leaves:
- `vague_qualifier` (e.g. "should improve", "is reasonable")
- `no_paper_evidence` (claim not anchored to paper text)
- `duplicate` (semantically equivalent to a sibling)
- `unverifiable` (no decidable test)

The frozen rubric is never mutated: the findings go into a separate
`ari.replication-rubric-audit/v2` document, written to `output_path` or, when
that is empty, beside the rubric as `<rubric_path>.audit.json`. The rubric's own
digest, its `paper_sha256` against the supplied paper text, and its generator
provenance artifacts are all re-verified before the audit runs. The report
records `independence_status: "not-independent"` when the auditor's
model/provider/revision identity equals the generator's, and recommends
regeneration when more than 20% of leaves are flagged.

#### `suggest_target_leaf_count(paper_path="", paper_text="")`

Returns the auto-computed target and the paper's word count. Useful for
the GUI Wizard to pre-fill the "Target leaves" field.

### v0.7.2 — `reproduce_contract.execution_profile`

The skeleton + subtree prompts now instruct the generator to populate
`reproduce_contract.execution_profile` when the paper specifies parallel
execution properties (MPI rank counts, GPU type, exclusivity, memory,
NUMA bindings). Schema:
[`docs/reference/execution_profile.md`](execution_profile.md).
The field is optional and backward-compatible — single-CPU papers leave
it absent.

### Environment

| Variable | Default | Purpose |
|---|---|---|
| `ARI_MODEL_RUBRIC_GEN` | `gemini/gemini-2.5-pro` | Generator LLM |
| `ARI_MODEL_RUBRIC_AUDIT` | `anthropic/claude-opus-4-7` | Auditor LLM (independent of generator) |
| `ARI_RUBRIC_GEN_TARGET_LEAVES` | (unset) | Override target leaf count (`0`/unset = auto). GUI Wizard "Target leaves" field. |
| `ARI_RUBRIC_GEN_TEMPERATURE` | (unset) | Override generator temperature. GUI Wizard "Temperature" field. |

Env vars are resolved in `server.py` before the generator runs and win
over the kwarg defaults when the workflow stage doesn't pass an
explicit value (the bundled `ors_generate_rubric` stage does not, so
the GUI Wizard always controls these two knobs at runtime).

---

## ari-skill-memory

Ancestor-scoped node memory, backed by [Letta](https://docs.letta.com)
in v0.6.0. Prevents cross-branch contamination and stores a separate
ReAct-trace collection for the agent loop. **LLM: △** (embedding-based
retrieval; see PHILOSOPHY.md for the P2/P5 relaxation note).

### Tools

#### `add_memory(node_id, text, metadata=None)`

Store an entry tagged with `node_id`. **Copy-on-Write**: rejects writes
whose `node_id` ≠ the node carried in the signed call context, so a child
cannot mutate an ancestor's entries.

#### `search_memory(query, ancestor_ids, limit=5)`

Return entries whose `node_id` is in `ancestor_ids`, **ranked by
semantic similarity to `query`** via Letta's embedding-based
`passages.search` route. Siblings and children are never returned.

Implementation note (verified against Letta 0.16.7, 2026-05-04): the
skill deliberately does NOT use `passages.list(search=q)` — that SDK
call hits `GET /archival-memory?search=q`, which is server-side **SQL
substring matching** (`WHERE LOWER(text) LIKE LOWER(%q%)`), not
semantic search. Long natural-language queries never substring-match
structured passages like `RESULT SUMMARY metrics=[...]`, so every
search would silently return 0 — exactly what was observed in
production runs with 84 valid passages. Instead the skill calls
`passages.search` (`GET /archival-memory/search`, `embed_query=True`)
with `top_k = max(letta_overfetch, limit*40)` to ensure the ancestor-
relevant entries land inside the ranked window, then post-filters
locally by `ancestor_ids`, `ari_checkpoint`, and
`kind == "node_scope"`. The embedding cost paid on every `add_memory`
insert is now actually consumed by retrieval. Order is the embedding
rank order itself — children see entries most relevant to their
`eval_summary` query first.

#### `get_node_memory(node_id)`

All entries for a specific node (chronological, no scoring).

There is no per-node clear, debug-only or otherwise. Nothing in the skill's
thirteen tools removes an entry: writes are append-only and CoW-guarded, and
`tests/test_cow.py::test_destructive_clear_is_not_publicly_exposed` asserts the
absence directly (`assert not hasattr(server, "clear_node_memory")`). The way
to shrink a node's footprint is to add a consolidated typed entry with
`consolidate_node_memory`, not to delete the originals.

#### `get_experiment_context()`

Stable experiment facts read from Letta core memory — `experiment_goal`,
`primary_metric`, `hardware_spec`, etc. Seeded once after the first
node's `generate_ideas` completes (the moment `primary_metric` is
determined); safe to call repeatedly (60 s in-process cache). Returns
`{}` until that seed runs.

#### Typed verifiable-research-memory tools

Typed entries (Phase 1) carry structured provenance so the paper / figure
stages can ground claims on reproducible artifacts. Callers are loop/pipeline
hooks, not LLM pulls. Every write tool is **Copy-on-Write guarded**: `node_id`
must equal the node in the signed call context that ari-core's MCPClient
injects into the call, so a child cannot mutate an ancestor's entries.

#### `add_experiment_result(node_id, text, metric_ptr=None, artifact_refs=None, node_report_ref=None)`

Record a typed `experiment_result` (CoW: self node only).

#### `add_failure_case(node_id, text, artifact_refs=None, node_report_ref=None)`

Record a typed `failure_case` (CoW: self node only).

#### `add_procedure_memory(node_id, text, node_report_ref=None)`

Record a reusable procedure (CoW: self node only).

#### `add_reflection(node_id, text, confidence=None, node_report_ref=None)`

Record a reflection (CoW: self node only). Not usable for paper claims.

#### `add_reproducibility_event(node_id, target_memory_id, status, artifact_refs=None, text=None)`

Append an append-only reproducibility status event against an existing entry
(CoW: self node only).

#### `search_research_memory(query, ancestor_ids, kinds=None, require_artifacts=False, limit=5)`

Ancestor-scoped typed search, filtered by `kind` / artifact presence. Siblings
and children are never returned.

#### `get_verified_context(ancestor_ids, purpose="paper", limit=None)`

Artifact-grounded, reproducibility-aware context for paper / figure use.

#### `audit_memory(experiments_root, run_id=None)`

Verify recorded provenance (sha256) against disk for a checkpoint. Returns
`{summary, results}`.

#### `consolidate_node_memory(node_id, node_report, work_dir, run_id=None)`

Derive and write typed memory (`experiment_result` / `failure_case` /
`reflection`) from a `node_report` at node end via the typed writer (CoW: self
node only). Caller is the ari-core node-end hook.

Storage: per-checkpoint Letta agent with two archival collections
(`ari_node_*`, `ari_react_*`). A snapshot at
`{ARI_CHECKPOINT_DIR}/memory_backup.v1.json.gz` keeps checkpoints
portable. The v0.5.x JSONL stores were removed in v0.6.0
(checkpoint-scoped `memory_store.jsonl` and the legacy global JSONL that
once lived under `$HOME/.ari/`); use `ari memory migrate` to import
legacy data. Cross-experiment "global memory" is no longer a feature —
stable lessons belong in `experiment.md`, code, or prior papers.

---

## ari-skill-orchestrator

Expose ARI as an MCP server for external agents and IDEs. Supports recursive sub-experiments. **LLM: No** (delegates to ARI CLI).

Dual transport: **stdio** (the default, for Claude Desktop / other MCP clients)
and **MCP Streamable HTTP** (`--transport streamable-http`, port from
`ARI_ORCHESTRATOR_HTTP_PORT`, default 9890). The HTTP transport refuses to
start without `ARI_ORCHESTRATOR_HTTP_TOKENS_FILE` — over the network,
authentication is required rather than optional.

Every tool is authorized against the calling principal, so the twelve below are
one submit / one cancel and ten reads, not a general remote-control surface.

### Tools

#### `run_experiment(experiment_md, idempotency_key, parent_run_id="", max_recursion_depth=None, max_nodes=10, max_total_nodes=100, max_descendant_runs=32, estimated_cost_usd=0.0, max_cost_usd=100.0, cpus=1, timeout_minutes=60, model="", llm_backend="", executor="", retrieval_backend="")`

Idempotently submit one quota-bound ARI run and return its durable handle.
`idempotency_key` is required, not optional: it is what makes a retried submit
return the existing run instead of starting a second one.

The quota block is part of the request, and recursion is bounded on three axes
at once — `max_nodes` for this run, `max_total_nodes` across the tree, and
`max_descendant_runs` for how many child runs the subtree may spawn — with
`max_cost_usd` over the top. `parent_run_id` and `max_recursion_depth` fall
back to the inherited `ARI_PARENT_RUN_ID` / `ARI_MAX_RECURSION_DEPTH` (depth
defaulting to 3) so a child run cannot escape its parent's budget merely by
omitting the arguments. `model` / `llm_backend` / `executor` /
`retrieval_backend` likewise fall back to `ARI_MODEL` / `ARI_BACKEND` /
`ARI_EXECUTOR` / `ARI_RETRIEVAL_BACKEND`. There is no credential argument: the
tool takes neither an API key nor a base URL.

#### `get_status(run_id)`

Return the exact durable state and bounded scientific progress for a run.

#### `get_result(run_id)`

Return terminal metadata and digest-addressed artifacts for a run.

#### `stop_experiment(run_id)`

Cancel a run, propagate termination to its descendants, and settle exactly one
terminal state.

#### `list_runs()`

List only runs owned by the authenticated principal; an admin principal may
list all.

#### `list_children(parent_run_id)`

Return the authorized direct descendants of one exact parent run ID (for
recursive sub-experiment tracking).

#### `list_artifacts(run_id)`

List the allowlisted, digest-verified artifacts of a run. Filesystem paths are
not exposed — an artifact is named by its identity, not its location.

#### `read_artifact(run_id, artifact_id)`

Read one bounded admitted artifact by its exact SHA-256 identity.

#### `get_paper(run_id)`

Return paper artifact references for an authorized run.

#### `get_ear(run_id)`

Return verified EAR and evidence artifact references for an authorized run.

#### `list_skills(run_id)`

Return the sanitized, immutable `SKILLS.lock` view for one run — which
Providers that run was actually locked to.

#### `get_workflow(run_id)`

Return the locked phase / tool membership for a run, without the raw workflow
document or any secret config.

Workspace: `ARI_WORKSPACE` env, defaulting to the resolved ARI repository root. Parent-child relationships persisted in `meta.json` per checkpoint.

---

## ari-skill-transform

Converts BFTS internal representation to publication-ready scientific data format. Strips all internal fields (`node_id`, `label`, `depth`, `parent_id`) and exposes only scientific content (`configurations`, `experiment_context`). **LLM: Yes**.

### Tools

#### `nodes_to_science_data(nodes_json_path, llm_model="", llm_base_url="", primary_metric="", higher_is_better="true")`

LLM analyzes the full BFTS tree, extracting hardware specs, methodology, key findings, and comparisons. The pipeline passes `primary_metric` and `higher_is_better` from `evaluation_criteria.json` (resolved via `tpl_vars` — see `ari-core/ari/pipeline.py`) so direction-aware reductions can be performed without the consumer re-deriving them.

Returns:

```text
configurations[*]:
  rank, label, eval_summary
  parameters / measurements / predictions / scores  ← typed split (when populated)
  metrics                                           ← back-compat flat union
  _typed_source: "results.json" | "llm_evaluator" | (absent)
  _typed_schema_version
  _provenance                                       ← union of emit_results
                                                       _provenance across the
                                                       node's results*.json
                                                       variants (when present)
per_key_summary:                                    ← input-param keys & "_…" keys
                                                       are excluded
summary_stats:
  count
  primary_metric, direction, primary_metric_best, primary_metric_n  (when set)
  typed_split_coverage: {results.json, llm_evaluator, none}         ← adoption tracking
experiment_context:                                 ← LLM-extracted methodology /
                                                       hardware / findings
implementation_overview (optional):                 ← LLM-extracted architecture /
                                                       key_algorithms / optimizations
report_driven                                       ← true when node_report.json was
                                                       used as the LLM input substrate
```

**Source priority for the typed split** (D > C > legacy):

1. `experiments/{run_id}/{node_id}/results.json` — written by `coding-skill::emit_results` (D contract). Authoritative because the experiment script declared its own contract.
2. `node.metrics::_params_dict` and `_measurements_dict` — emitted by the LLM evaluator from artifact text when `MetricSpec.expected_params` is set (C contract).
3. Legacy: `parameters: {}` and the flat `metrics` dict carries everything as a single ambiguous bag.

It also reads back `{checkpoint}/metric_contract.json` (written by `evaluator-skill::make_metric_spec`, next to `tree.json`) and grafts it onto `science_data.metric_contract` so the deterministic hard gate enforces the declared contract (claims / correctness / `required_measured` / declared invariants) — without this graft the declared contract is inert and only the universal invariant registry reaches the gate.

**Robustness**: the LLM response parser strips `<think>…</think>` blocks and `` ```json `` fences, then walks balanced braces from each candidate `{` (handles `{...} prose {...}` shapes that the legacy greedy `\{.*\}` regex would have collapsed). On any parse failure the raw response is saved to `{checkpoint_dir}/science_data.debug.txt` for post-hoc audit.

Model: `llm_model` arg > `ARI_MODEL_TRANSFORM` env > `ARI_LLM_MODEL` env >
`LLM_MODEL` env > a backend-matched default (`claude-cli` when
`ARI_BACKEND=cli-shim`, otherwise `gpt-4o-mini`).

**Why it exists:** Ensures BFTS-internal terminology never leaks into generated papers or figures, and that input-size descriptors (`nnz`, `M`, `K`) cannot be confused with measured outputs (`GFlops_per_s`, accuracy) when computing best-of statistics.

#### `generate_ear(checkpoint_dir, llm_model="", llm_base_url="")`

Builds a structured **Experiment Artifact Repository (EAR)** under `<checkpoint>/ear/` for reproducibility. The layout is *node_report-driven* and shaped like a typical paper-companion code repo:

- `README.md` — deterministic, with optional `Architecture` section sourced from `science_data.json::implementation_overview.architecture`
- `reproduce.sh` — best node's literal `build_command` + `run_command` (from its `node_report.json`)
- `environment.json` — captured runtime environment (Python, platform, pip packages, hardware)
- `code/` — verbatim union of contributing chain nodes' `files_changed.added` ∪ `modified` (no per-node subdirs)
- `data/` — `checkpoint/uploads/` mirror (input data only; absent if uploads/ is empty). **Experiment outputs (CSV etc.) are NOT included** — `reproduce.sh` regenerates them
- `figures/` — top-level `*.{pdf,png,svg,jpg,jpeg}` from the checkpoint
- `LICENSE` — generated from `publish.yaml::license` (MIT / Apache-2.0 / BSD-3-Clause / GPL-3.0 / CC-BY-4.0)

Two ARI audit logs are kept at `<checkpoint>/` (outside `ear/`, so they are *not* bundled into the published artifact):

- `EVOLUTION.md` — per-step search trajectory with deltas and concerns; uses Step / Label only, never raw `node_id`
- `_provenance.json` — origin metadata (`from_node_id`, `introduced_by`, `excluded_nodes`); paths inside are checkpoint-relative (`ear/code/...`)

Other internal ARI metadata (`tree.json`, `science_data.json`, `raw_metrics.json`, `eval_scores.json`, `commands.md`) also stays at checkpoint root and never appears under `ear/`. `run_config.json` lives at `checkpoint/run_config.json`.

Returns: `{ear_dir, code_layout, verbatim_files, rendered_files, data_count, figure_count, top_node_id, best_chain_depth, excluded_count, has_readme, has_evolution, has_reproduce_sh, has_license, has_environment, ...}`.

#### `curate_ear(checkpoint_dir)` — v0.7.0

Curates `{checkpoint}/ear/` into `{checkpoint}/ear_published/` using
the author-supplied `ear/publish.yaml` allowlist + a built-in deny
list (`.env*`, `secrets/**`, `*.pem`, `*.key`, `id_rsa`,
`id_ed25519`). Writes `manifest.lock` with the canonical
`bundle_sha256` (sha256 of a sorted `{path, sha256, size}` JSON
payload) — this is the digest baked into the paper's
`\codedigest{...}` macro. **Deterministic, no LLM**. Skips silently
when `publish.yaml` is absent (back-compat for v0.6.0 checkpoints).

#### `publish_ear(checkpoint_dir, backend="ari-registry", visibility="staged", dry_run=False)` — v0.7.0

Thin MCP wrapper around `ari.publish.publish`. Builds a reproducible
tarball from `ear_published/` (sorted entries, normalised mtime/uid/gid),
hands it to the backend (`ari-registry` / `gh` / `zenodo` /
`local-tarball`), records `publish_record.json` at the checkpoint
root. Always starts at `visibility=staged` regardless of the argument
(FR-P5); `auto_promote=true` in `publish.yaml` plus a passing
reproducibility check is required to promote to `public`.

`ARI_PUBLISH_DRYRUN=1` forces dry-run mode for CI safety.

#### `promote_ear(checkpoint_dir, target="public")` — v0.7.0

Promotes a previously-published EAR artefact to a wider visibility tier.
Thin MCP wrapper around `ari.publish.promote`. **Deterministic, no LLM**.
Returns `{ref, visibility, promoted_at, promote_failed_at}` (or
`{error, kind}` on a `PublishError`).

#### License templates — v0.7.0

When `publish.yaml::license` is set and `ear/LICENSE` does not already
exist, `generate_ear` emits one of: **MIT**, **Apache-2.0**,
**BSD-3-Clause**, **GPL-3.0**, **CC-BY-4.0** (templates under
`ari-skill-transform/src/licenses/`).

---

## ari-skill-web

Web search and academic literature retrieval under one record/replay contract. **LLM: Partial** (only `rerank_retrieval_records` uses LLM).

### The retrieval contract

There is no tool per provider and no tool that mutates provider state. The four
retrieval tools — `web_search`, `fetch_url`, `search_papers` and
`walk_citations` — instead share the same two arguments, `mode` and
`snapshot_ref`:

| `mode` | Behaviour |
|---|---|
| `record` (default) | Fetch, then write a `SurveySnapshotV1` under the checkpoint. Requires `ARI_CHECKPOINT_DIR`; without it the call is refused up front |
| `live` | Fetch without snapshotting |
| `replay` | **No network access at all.** Replays the snapshot named by the checkpoint-relative `snapshot_ref` an earlier record returned |

Each of the four returns the same `ari.retrieval-result/v1` document —
`provider`, `query`, `count`, normalised `records` (`RetrievalRecordV1`),
`alias_groups`, the embedded `survey_snapshot` with its
`survey_snapshot_digest`, the `snapshot_ref` to replay it, and the
`execution_mode` that produced it. A cited paper is therefore always traceable
to the exact retrieval that found it. The remaining three tools —
`rerank_retrieval_records`, `list_uploaded_files`, `read_uploaded_file` — take
no `mode`: they consume records that were already retrieved, or read the
checkpoint's own `uploads/`.

### Tools

#### `web_search(query, n=5, mode="record", snapshot_ref="")`

DuckDuckGo web search. No API key required. `n` is clamped to 10. Result
snippets are carried with `use_restriction: "untrusted search-result snippet"`
— they are data, never instructions.

#### `fetch_url(url, max_chars=8000, mode="record", snapshot_ref="", max_bytes=2097152)`

Fetch and extract readable text from a URL, through pinned-IP SSRF and redirect
controls. `max_chars` is clamped to 100,000 and `max_bytes` may not exceed 2
MiB; a non-2xx status is a `NetworkPolicyError`, not an empty result. HTML is
reduced with BeautifulSoup after `script` / `style` / `nav` / `footer` /
`header` are dropped.

#### `search_papers(query, max_results=10, provider=None, mode="record", snapshot_ref="")`

Search **one pinned academic provider**. The provider comes from the `provider`
argument, else from `ARI_RETRIEVAL_BACKEND`, and must be `semantic-scholar`
(the default), `arxiv` or `alphaxiv` — AlphaXiv is reached over MCP JSON-RPC at
`ARI_ALPHAXIV_ENDPOINT`. `max_results` is clamped to 50.

`provider="both"` is **refused**, with the instruction to issue two pinned
calls and merge them by aliases. A composite search has no single provider
identity, so its snapshot could not say what was actually queried; `record`
and `live` never silently switch provider either. Underscores are accepted in
provider names (`semantic_scholar` normalises to `semantic-scholar`).

#### `walk_citations(seed_ids, direction="references", max_depth=2, max_nodes=50, request_budget=20, mode="record", snapshot_ref="")`

Bounded Semantic Scholar citation-graph walk with cycle detection —
breadth-first from up to 20 deduplicated seed IDs (an `s2:` prefix is
stripped), following `references` or `citations`. Every bound is clamped:
`max_depth` to 5, `max_nodes` to 500, `request_budget` to 500.

Exhaustion is reported, not hidden. The result carries `citation_edges`,
`requests_used`, and `partial` — set when the budget ran out or a provider call
failed, with the reason recorded — so a truncated graph cannot be mistaken for
a complete one.

#### `rerank_retrieval_records(research_question, records, max_results=10)`

Reorder already-retrieved `RetrievalRecordV1` rows by relevance to a research
question. **LLM: Yes**, and deliberately a separate tool: the deterministic
retrieval path never calls it, so the stochastic step is opt-in and visible.
The model may only permute supplied indices — it never introduces a record —
and a response with no valid index is an error rather than a silent passthrough.

The returned `provenance` block records the model, the API base identity
(scheme, host and port only — no credentials), the temperature, and the prompt,
input and output digests, so the ordering can be audited later. Record text is
passed to the model as data with an explicit instruction to ignore any
instructions inside it.

Model: `ARI_LLM_MODEL` env > `LLM_MODEL` env > `ollama_chat/qwen3:32b`.

#### `list_uploaded_files()`

Lists user-uploaded files in the checkpoint directory. Deterministic.

#### `read_uploaded_file(filename, max_chars=50000)`

Reads text file content from uploaded files with binary detection. Deterministic.

---

## ari-skill-coding

Code generation, execution, and file reading. **LLM: No** (deterministic).

### Tools

#### `write_code(filename, code, work_dir="/workspace")`

Write a source file to the work directory.

#### `edit_code(filename, old_string, new_string, replace_all=False, work_dir="/workspace")`

Replace an exact snippet inside an existing file, leaving the rest untouched. Prefer this over `write_code` when the file already exists: re-emitting a whole kernel to change a few lines costs tokens and risks dropping code that was working. `old_string` must appear **exactly once** unless `replace_all` is set, so an ambiguous edit fails instead of silently changing the wrong place.

#### `run_code(filename, work_dir="/workspace", timeout=600)`

Execute a source file using an interpreter selected by its extension (`.py` →
`python3`, `.sh` → `bash`, `.js` → `node`, `.rb` → `ruby`, `.pl` → `perl`,
`.lua` → `lua`); it does **not** compile, so C/C++/Fortran/Rust/Go go through
`run_bash`. The inline `stdout`/`stderr` are bounded previews (4,000 and 2,000
characters) whose truncation marker states the omitted character count and says
the full log is an artifact; the complete streams are always written as
content-addressed artifacts with SHA-256 digests.

#### `run_bash(command, work_dir="/workspace", timeout=600)`

Run a bash command in the work directory. Same bounded previews and
content-addressed full logs as `run_code`, with a `truncated` boolean flag in
the result.

#### `read_file(path, offset=0, limit=8000, work_dir="/workspace")`

Read a text file with paginated access for large files. `offset` and `limit` are
**character** offsets, not lines. Returns content, `next_offset` for
continuation (`null` at the end), and the total character count.

```python
result = read_file("results.csv", offset=0, limit=100)
# Returns: {"path": "...", "content": "...", "offset": 0, "returned_chars": 100,
#           "total_chars": 5000, "truncated": True, "next_offset": 100}
```

#### `describe_environment()`

Report this cluster's environment catalog so the agent does not have to discover the toolchain by trial and error. Per node it lists arch, CPU, GPUs, compilers on PATH, the raw `module avail` catalog, and the NAMES of set toolchain env vars (values are never dumped — the agent echoes the ones it needs). On a **login** node it reports the login node itself plus one entry per configured compute partition; on a **compute** node, only that node.

Work directory: `ARI_WORK_DIR` (default `/tmp/ari_work`) fixes the workspace
root. A `work_dir` argument does not replace that root — it selects a directory
*beneath* it, created on demand, and a path that resolves outside it is refused
rather than rewritten. The agent is shown the root as the fixed container path
`/workspace`, which the filesystem tools map back to the real directory in the
`filename`, `command` and `path` arguments before touching it, and scrub out of
every result. The `work_dir` argument itself is **not** mapped back — it is
resolved against the real root as given, so a literal `/workspace` there is
refused as escaping that root even though it is the argument's declared schema
default. Leave `work_dir` unset (it then resolves to the root), or let
`ari.agent.tool_manager` pin the node's real path (below).

Inside a BFTS run the `work_dir` argument is not left to the model: `ari.agent.tool_manager` pins the node's real `work_dir` on every filesystem tool. The env fallback cannot serve that role because the MCP server snapshots `ARI_WORK_DIR` at fork time, so per-node updates never reach it — an unpinned call would land in a shared scratch dir the evaluator never reads, and the node would be scored on inherited code.

#### `emit_results(params, measurements, cases={}, predictions={}, scores={}, provenance={}, units={}, execution=None, file="results.json", work_dir="/workspace")`

Write a typed `results.json` separating input parameters from measured outputs. Call this once at the **end** of an experiment run so downstream stages (`transform → science_data`, paper writing, summary stats) can tell apart "what we measured" from "what we ran on" — a best-of reduction never accidentally picks an input size (e.g. `nnz`, `M`, `K`, `threads`) over a real metric (e.g. `GFlops_per_s`).

```python
emit_results(
    params={"M": 120000, "K": 120000, "nnz": 3840000, "threads": 8},
    measurements={"GFlops_per_s": 26.864, "GB_per_s": 63.802},
    predictions={"peak_gflops_model": 686.45},
    scores={"parallel_efficiency": 0.81},
)
```

The file is `{"schema_version": "1.0", "typed_schema_version": "ari.measurement-set/v1", "measurement_set": {...}}` — only the canonical `MeasurementSetV1` object, with no flat projection beside it (see [Execution and measurement contracts](execution_contract.md)). It is overwritten on repeat calls; pass a different `file` name to keep multiple result variants. `params` and `measurements` must be disjoint — do NOT include input parameters in `measurements` and do NOT include measured outputs in `params`. Every group must be finite JSON: a non-serializable value (e.g. `pathlib.Path`), a `NaN`/`Infinity`, or a non-numeric measurement is refused with an `error` rather than coerced. `file` is written through the closed workspace, so a path escaping `work_dir` is refused.

The optional `units` arg is a `{measurement: unit}` map; a measurement with no declared unit is recorded as `unit_status: "missing"` and units are never inferred. The optional `execution` arg is the `measurement_execution` block copied verbatim from a prior `run_code`/`run_bash` response (execution identity/attempt, status, exit code, artifact digests, and the server-issued receipt); without it the measurements are marked `execution_status: "unreported"` and are not scientifically admissible. A `units` or `provenance` key naming something that is not in `measurements` is refused.

The `cases` arg is declared in the tool's input schema — an optional `{case_name: {"params": {...}, "measurements": {...}}}` map for a run that measured more than one problem size or shape — but the current server does not forward it: the `emit_results` branch of `call_tool` passes only `params`, `measurements`, `predictions`, `scores`, `provenance`, `units`, `execution`, `file` and `work_dir`, and the writer takes no `cases` parameter. Anything sent under `cases` is therefore accepted and dropped, so a multi-shape run must not be reported through it alone; emit one `results.json` per case with a distinct `file` name instead.

The optional `provenance` arg is an `{operand: source}` map recorded on the corresponding canonical measurement record and consumed by the claim/metric-correctness gate. Tag an operand `"microbench"` or `"benchmark"` when its value is an empirically **MEASURED** ceiling/peak (so a normalized metric is not flagged as resting on a placeholder), and `"correctness"` or `"reference"` when it is a residual computed against an **independent** reference (so the output is not flagged as unverified). Best-effort; omitted entirely when empty.

The downstream `transform-skill::nodes_to_science_data` populates `configurations[*].parameters` from this file when present (D contract). The older C-contract path — the LLM evaluator's typed split, driven by `MetricSpec.expected_params` — is still wired through `ari-core/ari/agent/loop.py`, but `evaluator-skill::make_metric_spec` now returns `expected_params: []` on every path, so nothing feeds it. Call `emit_results`: it is the only route by which a node's input parameters reach `science_data`.

---

## ari-skill-benchmark

Typed deterministic summaries, statistical tests, and provenance-aware run
comparison. **LLM: No** (deterministic). Figures are not this skill's job —
`ari-skill-plot` renders them.

All three tools take exactly one `request` object and return one
`AnalysisResultV1` carrying `kind`, an `input_digest` over the fully resolved
inputs, the caller's `analysis_plan_digest`, and the `library_versions`
(python / numpy / scipy) the numbers were produced under. An optional
`artifact_target` additionally writes the result and a CSV table into a closed
workspace as digest-bound `AnalysisArtifactV1` entries.

Samples arrive as `MetricSampleSetV1`: a `metric_id`, an explicit non-empty
`unit`, and either inline `observations` or an `AnalysisDataSourceV1` naming a
digest-bound numeric column (`auto` / `csv` / `json` / `npy`) inside a closed
workspace. `missing_policy` is `error` by default — a missing value is refused
rather than quietly dropped — and the resolved `missing_count` is reported
either way.

### Tools

#### `analyze_results(request)`

Summarize one or more datasets. Per metric: `count`, `missing_count`, `mean`,
`std`, `variance`, `minimum`, `q25`, `median`, `q75`, `maximum`, the
`mean_confidence_interval` at the request's `confidence_level` (0.95 by
default), a `constant_data` flag, an `independence_status` of `verified` /
`declared` / `not-established`, and the `source_digest` the values came from.
Duplicate `metric_id` values in one request are refused.

#### `statistical_test(request)`

Run a **pre-declared** family of comparisons. Each `StatisticalComparisonV1`
names its own `comparison_id`, two sample sets, a `test_family` (`auto`,
`welch_t`, `student_t`, `paired_t`, `mann_whitney`, `wilcoxon`), a `pairing`
(`unpaired`, `ordered`, `pair_id`), an `alternative` and its `alpha`.

Multiplicity is not optional: a request with more than one comparison and
`correction: "none"` is rejected outright, so `bonferroni`, `holm` or
`benjamini_hochberg` must be chosen before the tests are run rather than after
the p-values are seen.

#### `compare_runs(request)`

Rank at least two scalar `RunRecordV1` runs in the declared `direction`
(`higher` or `lower`) against `baseline_run_id` (the first run when unset),
reporting each run's `delta` and `relative_delta`.

The caveats are the point. Runs are grouped by `(backend_id,
environment_digest)`; when more than one group is present,
`environment_compatible` is false and — because `require_compatible_environment`
defaults to true — the call **raises**, telling the caller to set it false to
obtain an explicitly caveated cross-environment ranking. Each group is marked
`shared_substrate` and `independence_inference: "not-permitted"`: sharing a
substrate is never read as independent replication. `independence_status` is
`declared` only when every run carries a distinct `replicate_id`, otherwise
`not-established` with no replicate count at all. `provenance_differences`
lists what changed relative to the baseline.

---

## ari-skill-plot

Source-bound declarative figure planning over a **fixed** renderer. **LLM:
Mixed** (deterministic + P2-exception) — but the exception is narrow: the LLM
may only *plan* a figure, never draw one. There is one renderer, it takes a
canonical `FigureSpecV1`, and no caller-supplied code, SVG or artifact bytes
reach it on any path.

### Tools

#### `render_figure(request)`

Render one canonical `FigureSpecV1` and return its manifest. The request must
be exactly `{spec, workspace, relative_directory}` — any other key set is
refused before anything is read — and a rendering failure comes back as a
`ValueError` describing the rejection rather than a partial figure. This is the
primitive the two generators below both call; nothing else can draw.

#### `generate_figures(science_data_path, output_dir, n_figures=3, revision=0)`

Derive deterministic default specs from a native `ScienceDataV1` (loaded with
its artifact digest) and render them into `output_dir`, returning the
`FigureBatchV1`. `revision` must be `0`: the deterministic path has no feedback
round, and a non-zero revision is refused rather than treated as a re-render.

#### `generate_figures_llm(science_data_path, output_dir, experiment_summary="", n_figures=3, vlm_feedback="", revision=0, previous_batch_path="")`

The LLM picks admitted fields only — `metric_id`, `chart_type`, `x_mode` —
after which the same fixed renderer produces the figure. Numeric values, units,
captions, paths, code, SVG and artifact bytes are all selected or produced
deterministically from the verified science record, so a hallucinated number
cannot reach a figure. P2 exception.

Revisions are bound rather than free-form. `revision=0` refuses any
`vlm_feedback`; `revision > 0` requires both a feedback document **and** the
`previous_batch_path` whose `revision` is exactly its parent. The feedback must
bind that manifest's digest, the metric set is carried over from the previous
batch, and a revision that changes a stable `figure_id` is refused — so a
review round cannot quietly become a different figure.

### Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `ARI_MODEL_PLOT` | Planner LLM for `generate_figures_llm` | (none) |
| `ARI_MODEL_PLOT_REVISION` | Model revision recorded into the figure manifest | (none) |
| `ARI_LLM_MODEL` | Planner fallback | (none) |
| `LLM_MODEL` | Cross-skill fallback | (none) |
| `ARI_LLM_API_BASE` | LiteLLM API base override (then `LLM_API_BASE`) | LiteLLM default |
| `OPENAI_API_KEY` | Required for an OpenAI-hosted planner | (none) |

Planning is called at `temperature=0.0`, and with none of the three model
variables set `generate_figures_llm` raises rather than silently picking a
model. Figure *review* is `ari-skill-vlm`'s job, not this skill's — there is no
caption VLM here.

### ari-core boundary

`src/server.py` reaches ari-core only through the public surface
(`from ari.public import cost_tracker`, then `bootstrap_skill("plot")`).

---

## ari-skill-vlm

Artifact-bound, criteria-versioned visual review of scientific figures and
tables. **LLM: Yes** (VLM).

Two things make a review citable rather than an opinion. The target is bound:
a figure is selected out of a verified `FigureBatchV1`, a table is named by
content-addressed artifact reference inside a closed workspace — never a loose
path the reviewer could be pointed away from. And the criteria are versioned:
each `VisualReviewV1` records `criteria_profile_id` **and**
`criteria_profile_digest` alongside the model, model revision, provider,
prompt digest and `sampling` (`temperature: 0.0`), so a score cannot be
compared across silently-edited criteria.

Bundled profiles: `figure-publication/v1` (source integrity, units/labels,
readability, comparability, accessibility; passing 0.7),
`figure-domain-integrity/v1` (source integrity, uncertainty, domain semantics,
readability; passing 0.75) and `table-publication/v1` (source integrity,
units/labels, precision, readability; passing 0.7). An unknown profile ID, or
one whose `target_kind` does not match the call, is refused.

### Tools

#### `review_figure(figures_manifest_path, figure_id, context="", criteria_profile_id="figure-publication/v1", max_output_tokens=2048)`

Review one figure selected by `figure_id` from a verified `FigureBatchV1`. A
`figure_id` the batch does not carry is refused rather than resolved to
something nearby.

#### `review_figures_all(figures_manifest_path, context="", criteria_profile_id="figure-publication/v1", budget=None)`

Review every figure in one batch, bounded by a `ReviewBudgetV1`:
`max_figures` (default 20, ≤100), `max_total_bytes` (default 100 MiB, ≤512
MiB), `max_concurrency` (default 2, ≤4), `max_model_calls` (default 20, ≤100)
and `max_output_tokens` (default 2,048, 128–8,192). Individual failures are
preserved as failed reviews with their raw evidence instead of collapsing the
batch, and figures past the budget are recorded as such rather than dropped
silently. This is the tool the pipeline's figure-review stage runs.

#### `review_table(request)`

Review one content-addressed table artifact. The request schema is exact —
`workspace`, `target_id`, `artifact`, `context`, `criteria_profile_id`,
`iteration` (0–2) and `max_output_tokens`, no more and no less. An unsupported
artifact media type comes back as a recorded `artifact-error` review rather
than an exception, so the failure is still evidence.

Model: `ARI_VLM_MODEL` env > `VLM_MODEL` env — there is no default. With
neither set the review raises rather than quietly picking a model. Provider and
revision are recorded from `ARI_MODEL_VLM_PROVIDER` / `ARI_MODEL_VLM_REVISION`,
the provider defaulting to the model string's own prefix.

---

## Writing a New Skill

1. Create `ari-skill-yourskill/src/server.py`:

```python
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("your-skill")

@mcp.tool()
def your_tool(param: str) -> dict:
    """Tool description."""
    # NO LLM calls here
    return {"result": process(param)}

if __name__ == "__main__":
    mcp.run()
```

2. Register in `ari-core/config/workflow.yaml`. `phase` scopes which
   pipeline-phase ReAct agents see the skill (string for one phase,
   list for several):

```yaml
skills:
  - name: your-skill
    path: '{{ari_root}}/ari-skill-yourskill'
    phase: [paper, reproduce]
```

   Valid phase values: `bfts`, `paper`, `reproduce`, `all`, `none`.

3. Reference the tool name in `experiment.md`'s `## Required Workflow`.
