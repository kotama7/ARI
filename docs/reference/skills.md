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
last_verified: 2026-08-06
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
catalog administration or fixed resolution authority.

## ari-skill-hpc

Typed SLURM lifecycle, strict SSH transport, capability probes, and
digest-pinned containers. **LLM: No** (fully deterministic).

Ten tools in three groups: two typed submitters (`job_submit`,
`container_submit`) plus the retained batch-script bridge (`slurm_submit`); four
lifecycle operations that share one handle selector (`job_status`, `job_result`,
`job_logs`, `job_cancel`); and three probes (`probe_platform_capabilities`,
`counter_support`, `measure_counters`). Containers are reached only through
`container_submit` and the digest-pinned `ContainerRequestV1` it carries — the
package exposes no image build, pull or run commands.

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
| `auto` (default) | bound to its CPUs when the shape is one task on one node, otherwise started directly | your script calls `srun` / `mpirun` itself, or is serial |
| `srun` | `srun` with the declared `nodes` / `tasks` / `cpus_per_task` | the script IS the parallel program (MPI / SPMD) |
| `none` | exactly as written | the payload must see the batch step untouched |

`auto` binds the single-task case because a batch step inherits the whole
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

#### `survey(topic, max_papers=8)`

Prior-work survey. Deterministic (no LLM). Sources are tried in order:
the frozen `virsci_snapshot` corpus the idea stage already built for this
run's topic, then a live Semantic Scholar query (HTTP, then the
`semanticscholar` client as a retry), then an **arXiv fallback** — so a
keyless or rate-limited S2 does not silently erase prior-art grounding.
The top results are then enriched with their citing papers (2-hop). Every
degradation, including a final 0-paper result, is reported on stderr.

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

#### `generate_ideas(topic, papers, experiment_context="", n_ideas=3, n_agents=4, max_discussion_rounds=2, max_recursion_depth=0)`

Generate research hypotheses using VirSci multi-agent LLM deliberation. Multiple AI personas (researcher, critic, expert, synthesizer) debate the research question. In the default `simple_bfts` mode it is called **once** before BFTS starts (pre-BFTS only). In the opt-in `ari_rqgm` mode with `proposal_router.generators.virsci.enabled: true`, the core-side `VirSciAdapter` additionally calls `survey` + `generate_ideas` through the ProposalRouter's event-triggered, budget-capped dispatch — see [VirSci Integration](../guides/virsci_integration.md).

Model: `ARI_LLM_MODEL` env > `LLM_MODEL` env > `ollama_chat/qwen3:32b`.

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

Metric spec extraction from experiment files. **LLM: Conditional** (fallback only when metric_keyword not found in text).

### Tools

#### `make_metric_spec(experiment_text)`

Parse experiment Markdown to extract evaluation criteria. Deterministic when `metric_keyword` and `min_expected_metric` are present in the text; falls back to LLM if not found.

```python
result = make_metric_spec(open("experiment.md").read())
# Returns: {
#   "metric_keyword": "GFLOP_per_s",
#   "expected_metrics": ["GFLOP_per_s", "GB_per_s"],   # MEASURED outputs
#   "expected_params":  ["M", "K", "nnz", "threads"],  # INPUT knobs
#   "min_expected_metric": 50000.0,
#   "scoring_guide": "..."
# }
```

`expected_metrics` and `expected_params` are strictly disjoint by contract — a name appears in one or the other, never both. The LLM-fallback path is the only one that fills `expected_params` (the regex path covers the experiment.md-format quick path, which has no consistent "## Parameters" header to mine). `loop.py` threads `expected_params` into `MetricSpec` so the LLM evaluator emits a typed `params` / `measurements` split on each node, which `transform-skill::nodes_to_science_data` then propagates to `configurations[*].parameters` (C contract — see also the D contract via `coding-skill::emit_results`).

`make_metric_spec` also builds an **idea-owned run-level `metric_contract`** from the idea's `primary_metric`, its structured `falsifiable_claims`, and the `correctness_required` / `ceiling_must_be_measured` requirement flags. It persists this to `{checkpoint}/metric_contract.json` (next to `idea.json` / `tree.json`). The contract is idea-owned so an agent cannot drop a claim or requirement to dodge the check; it is read back by `transform-skill::nodes_to_science_data` (grafted onto `science_data.metric_contract`) and enforced by the deterministic hard gate.

Model (fallback): `ARI_MODEL` env > `gpt-4o-mini`.

#### `claim_evidence_hard_gate(checkpoint_dir, paper_path, science_data_json="", paper_claim_links_path="", figures_manifest_json="", policy=None, phase="draft")`

Deterministic claim/evidence hard gate (execution data fidelity). **No LLM**. Verifies that science_data claims reference executed nodes, re-computes `numeric_assertions` from `results.json` and checks the paper-reported numbers within tolerance, detects uncovered result numbers per section policy, and checks figure existence. Thin MCP wrapper over ari-core's `run_hard_gate` (`ari.public.claim_gate`). In strict mode the `final` phase returns `{"error": ...}` when blocking errors exist so the stage runner raises and `finalize_paper` is skipped; the `draft` phase and warn/off mode never block. Writes `evaluation/claim_evidence_hard_gate_{phase}.json`.

#### `evidence_grounded_semantic_review(checkpoint_dir, paper_path, science_data_json="", hard_gate_path="", paper_claim_links_path="", phase="initial")`

Non-blocking, evidence-grounded semantic review. **LLM: Yes**. The LLM detects over-claiming / interpretation issues / unregistered strong claims grounded in the hard-gate evidence, WITHOUT touching the independent text reviewer; it does not re-check numbers. Emits `suggested_revisions` consumed by `paper_refine` plus scores. Writes `evaluation/evidence_grounded_semantic_review.json`. Never blocks.

---

## ari-skill-paper

LaTeX paper generation, compilation, and review (post-BFTS only). **LLM: Yes**.

### Tools

#### `list_venues()`

Returns available venue configurations.

Supported venues: `neurips` (9 pages), `icpp` (10 pages), `sc` (12 pages), `isc` (12 pages), `arxiv` (unlimited), `acm` (10 pages).

#### `get_template(venue)`

Returns the LaTeX template for a venue.

#### `generate_section(section, context, venue="arxiv", nodes_json_path="", refs_json="")`

Generate a LaTeX section using LLM. Section types: `introduction`, `related_work`, `method`, `experiment`, `conclusion`.

#### `compile_paper(tex_dir, main_file="main.tex")`

Run pdflatex compilation. Returns success status and error messages.

#### `check_format(venue, pdf_path)`

Validate paper format against venue requirements (page count, etc.).

#### `review_section(latex, context, venue="arxiv")`

Review a LaTeX section. Returns strengths, weaknesses, and suggestions.

#### `revise_section(section, latex, feedback, context, venue="arxiv")`

Revise a LaTeX section based on review feedback.

#### `write_paper_iterative(experiment_summary="", context="", nodes_json_path="", refs_json="", figures_manifest_json="", science_data_json="", venue="arxiv", max_revision_rounds=2, author_name="")`

Full paper generation with iterative draft → review → revise loop. Primary pipeline tool.

#### `review_compiled_paper(tex_path, pdf_path, figures_manifest_json, experiment_summary, rubric_id="", vlm_findings_json="", num_reflections=None, num_fs_examples=None, num_reviews_ensemble=None)`

Rubric-driven paper review compatible with the **AI Scientist v1/v2** pipeline
(Nature / arXiv:2408.06292 Appendix A.4). Loads a YAML rubric from
`ari-core/config/reviewer_rubrics/<rubric_id>.yaml`, renders prompts from the
rubric's `score_dimensions` / `text_sections` / `decision` schema, injects VLM
per-figure findings as reviewer notes, optionally prepends few-shot example
reviews, runs a self-reflection loop, then normalises the output to a
rubric-stable JSON schema.

Bundled rubrics (16 YAMLs in `ari-core/config/reviewer_rubrics/`):

| Family | Rubric IDs |
|---|---|
| ML conferences | `neurips` (default, v2-compatible), `iclr`, `icml`, `cvpr`, `acl` |
| Systems / HPC | `sc`, `osdi`, `usenix_security` |
| Theory / graphics | `stoc`, `siggraph` |
| HCI / robotics | `chi`, `icra` |
| Journals / generic | `nature`, `journal_generic`, `workshop`, `generic_conference` |

Add a new venue by dropping `<id>.yaml` into `reviewer_rubrics/` — no code
changes required. Each rubric declares `score_dimensions`, `text_sections`,
`decision` rules, execution parameters, and a SHA256 hash for P2 determinism.

Rubric resolution order: explicit `rubric_id` arg → `ARI_RUBRIC` env →
`neurips` → built-in `legacy` fallback (v0.5 schema, used when neither
`rubric_id` nor any matching YAML resolves).

#### Symmetric author / reviewer venue conditioning (unreleased)

`prompt_overrides` carries two parallel fields:

- `system_hint` — injected into peer-review prompts by `review_engine`
  (existing behaviour).
- `author_hint` — injected into paper-drafting prompts by
  `generate_section` as a dedicated `══ VENUE-SPECIFIC AUTHOR
  GUIDANCE ══` block. Tells the drafter what reviewers will look for,
  so the paper is written to make those signals easy to surface.

Empty `author_hint` preserves the legacy weak append (just `Target
venue: X. Page limit: N pages.`). SC and NeurIPS ship calibrated
`author_hint` blocks; remaining venues are empty and can be filled in
incrementally without touching code.

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

#### `merge_reviews(review_report_path, vlm_review_path="")` — v0.7.0

Post-hoc structural merge of `review_report.json` (text reviewer) and
`vlm_review.json` (VLM figure review). Purely deterministic — no LLM.
Attaches `vlm_figure_review` and `_review_composition` metadata so the
GUI / CLI can show both outputs with clear source attribution. The
upstream stages stay independent (matching AI Scientist v2's
`perform_review` contract) and are reconciled here.

#### `link_paper_claims(tex_path="", science_data_json="", figures_manifest_json="", output_path="")` — v0.9.0

Reconciles `% CLAIM:Cx:NCx` anchors against science_data claims and builds
`paper_claim_links.json` (anchors / writer_assertions / numeric_mentions /
figure_refs / unresolved_anchors / uncovered_numeric_candidates) consumed by
the claim hard gate. **Deterministic, no LLM**. The transform-stage
`science_data.json` is never mutated; figure binding is recorded here. Run after
`write_paper` (draft) and again after `paper_refine` (final). Degrades to a
valid empty result on failure (never error-only) so it cannot cascade-skip the
finalize chain.

#### `paper_refine(tex_path="", suggested_revisions_json="", merged_review_path="", semantic_review_path="", venue="arxiv")` — v0.9.0

Anchor-preserving revision pass that applies `suggested_revisions` (from
`evidence_grounded_semantic_review` / the merged review). **LLM: Yes**. Explicit
`replace "X" with "Y"` substitutions are applied deterministically first, then a
bounded multi-pass LLM find/replace handles the remainder; every `% CLAIM`
anchor present in the draft must survive (anchor-dropping edits are rejected and
on net anchor loss the original paper is kept). Math-safe underscore escaping
skips `\( … \)` / `\[ … \]` and math environments. The refined LaTeX is returned
under `latex` (the draft is preserved as `full_paper.draft.tex`).

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
- `run_reproduce` exposes 15 new SLURM flags (`--nodes`, `--ntasks`,
  `--ntasks-per-node`, `--nodelist`, `--exclude`, `--exclusive`,
  `--gpus-per-task`, `--gpus-per-node`, `--gres=gpu:<type>:N`, `--mem`,
  `--mem-per-cpu`, `--constraint`, `--cpu-bind`, `--mem-bind`,
  `--hint`) plus an `extra_sbatch_args` escape hatch. Each caller arg
  auto-resolves from `execution_profile` when left at its default.
- Runtime probes: `_is_shared_fs(repo_dir)` warns on node-local paths,
  `_slurm_has_gres()` silently drops `--gres` when the cluster has no
  GRES configured (keeping `--gpus-per-task`) so the submission is not
  rejected.

PaperBench is vendored as a git submodule under
`ari-skill-paper-re/vendor/paperbench`; the bridge module
`_paperbench_bridge.py` adapts the upstream `TaskNode` /
`SimpleJudge` API to ARI's rubric envelope. The main per-leaf grading
completer routes through LiteLLM (`_litellm_completer.py`) so any
provider works (`gpt-5-mini`, `anthropic/claude-...`, `gemini/...`,
`ollama/...`); the score-parsing structured completer stays on
`gpt-4o-2024-08-06` (within PaperBench's allow-list).

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

#### `build_reproduce_sh(paper_path="", paper_text="", rubric_path="", output_dir="", model="", time_limit_sec=43200, iterative_agent=False, max_steps=0, sandbox_kind="auto", container_image="", apptainer_image="", overwrite=False)`

**LLM-driven replicator** (v0.7.0+). Sibling of `fetch_code_bundle`:
both target `repro_sandbox/`. Reads the paper (and the rubric's
`reproduce_contract.expected_artifacts` when `rubric_path` is given)
and writes a self-contained `reproduce.sh` + supporting source files
into `output_dir`.

Routes through LiteLLM, so any provider works. Model resolves
`model` arg > `ARI_MODEL_REPLICATE` env > `ARI_LLM_MODEL` env >
`claude-opus-4-7`. Output JSON is sanity-checked (every file path is
filesystem-safe ASCII, no `..`, `reproduce.sh` is shebanged + has
`set -euo pipefail`, total content < 200 KB).

Skips with `populated=False, skipped_reason=...` when `output_dir/reproduce.sh`
is already present, so it composes cleanly after `fetch_code_bundle` /
EAR pre-populate. The workflow's `ors_build_reproduce` stage sets this
ordering — when `include_ear=true`, the EAR-seeded reproduce.sh wins;
when off, the LLM falls through.

```python
result = build_reproduce_sh(
    paper_path="full_paper.tex",
    rubric_path="ors_rubric.json",
    output_dir="repro_sandbox",
)
# Returns: {populated, output_dir, files, expected_artifacts,
#           max_runtime_sec, language, model, prompt_sha256, notes, warnings}
```

#### `run_reproduce(rubric_path, repo_dir, sandbox_kind="", container_image="", timeout_global_sec=0, partition="", cpus=0, walltime="", …SLURM flags)`

**Phase 1**. Executes `repo_dir/reproduce.sh` in a sandbox; captures
`reproduce.log` and lists artefacts; reports any
`expected_artifacts` (from the rubric envelope) that did not appear.

Sandbox priority (`auto`, the default): `slurm` (when sbatch is on
PATH AND `ARI_SLURM_PARTITION` is set — the same partition BFTS used)
→ `docker` (when daemon usable and not on HPC) → `apptainer` →
`singularity` → `local`. Override with the `sandbox_kind` argument
or `ARI_PHASE1_SANDBOX`. The container image is `docker://ubuntu:24.04`
by default (`ARI_PHASE1_DOCKER_IMAGE` / `ARI_PHASE1_APPTAINER_IMAGE` /
`ARI_PHASE1_SINGULARITY_IMAGE` to customise).

**SLURM dispatch** (v0.7.0, restored from v0.5.0): submits via
`sbatch --wait` so the call blocks until the job finishes and
inherits the job's exit code. partition / cpus / walltime resolve
arg > env (`ARI_SLURM_PARTITION` / `ARI_SLURM_CPUS` /
`ARI_SLURM_WALLTIME`) > `{checkpoint_dir}/launch_config.json`. A tiny
wrapper script (`{repo_dir}/.slurm_wrap.sh`) is generated to bypass
sbatch's spool-relocation: it `exec bash`'s the user reproduce.sh by
absolute path so `$0`-relative `cd "$(dirname "$0")/code"` still works
inside the spooled job.

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
repo + reproduce.log + paper. `n_runs` (default 3) iterations are
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
The structured int/float score-parsing completer remains on
`gpt-4o-2024-08-06` (within the registry) since its task is small
and the upstream pydantic-schema integration is OpenAI-shaped.

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

#### `suggest_target_leaf_count(paper_path, paper_text)`

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
| `ARI_RUBRIC_GEN_TWO_STAGE` | (unset) | Force two-stage on/off (`1`/`true`/`on` vs `0`/`false`/`off`). GUI Wizard "Two-stage generation" toggle. |

Env vars are resolved in `server.py` before the generator runs and win
over the kwarg defaults when the workflow stage doesn't pass an
explicit value (the bundled `ors_generate_rubric` stage does not, so
the GUI Wizard always controls these three knobs at runtime).

---

## ari-skill-memory

Ancestor-scoped node memory, backed by [Letta](https://docs.letta.com)
in v0.6.0. Prevents cross-branch contamination and stores a separate
ReAct-trace collection for the agent loop. **LLM: △** (embedding-based
retrieval; see PHILOSOPHY.md for the P2/P5 relaxation note).

### Tools

#### `add_memory(node_id, text, metadata=None)`

Store an entry tagged with `node_id`. **Copy-on-Write**: rejects writes
whose `node_id` ≠ `$ARI_CURRENT_NODE_ID` so a child cannot mutate an
ancestor's entries.

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

#### `clear_node_memory(node_id)`

Debug-only per-node clear. Same CoW rule as `add_memory`.

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
must equal `$ARI_CURRENT_NODE_ID` (the ari-core MCPClient routes the write
through the `_set_current_node` bridge), so a child cannot mutate an ancestor's
entries.

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
`{ARI_CHECKPOINT_DIR}/memory_backup.jsonl.gz` keeps checkpoints
portable. The v0.5.x JSONL stores were removed in v0.5.0
(checkpoint-scoped `memory_store.jsonl` and the legacy global JSONL that
once lived under `$HOME/.ari/`); use `ari memory migrate` to import
legacy data. Cross-experiment "global memory" is no longer a feature —
stable lessons belong in `experiment.md`, code, or prior papers.

---

## ari-skill-orchestrator

Expose ARI as an MCP server for external agents and IDEs. Supports recursive sub-experiments. **LLM: No** (delegates to ARI CLI).

Dual transport: **stdio** (MCP for Claude Desktop / other MCP clients) + **HTTP** (REST + SSE on `ARI_ORCHESTRATOR_PORT`, default 9890).

### Tools

#### `run_experiment(experiment_md, max_nodes=10, model="", max_recursion_depth=3, parent_run_id="", llm_backend="", llm_api_key="", llm_base_url="", executor="", cpus=0, timeout_minutes=0, retrieval_backend="")`

Launch an ARI experiment asynchronously. Returns `run_id`. When `parent_run_id` is set, the experiment is tracked as a child of the parent (for recursive sub-experiment workflows).

#### `get_status(run_id)`

Return progress, current best metrics, and recursion metadata for a run.

#### `list_runs()`

List all past experiment runs.

#### `list_children(run_id)`

Return child runs of a parent experiment (for recursive sub-experiment tracking).

#### `get_paper(run_id)`

Return the generated paper (LaTeX).

Workspace: `ARI_WORKSPACE` env (default: `~/ARI`). Parent-child relationships persisted in `meta.json` per checkpoint.

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

Model: `llm_model` arg > `LLM_MODEL` env > `gpt-4o-mini`.

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

Web search and academic literature retrieval with pluggable backends. **LLM: Partial** (only `collect_references_iterative` uses LLM).

### Tools

#### `web_search(query, n=5)`

DuckDuckGo web search. No API key required. Deterministic.

#### `fetch_url(url, max_chars=8000)`

Fetch and extract text from a URL via BeautifulSoup. Deterministic.

#### `search_arxiv(query, max_results=5)`

arXiv paper search. Deterministic.

#### `search_semantic_scholar(query, limit=8, extra_queries=None)`

Semantic Scholar API with fallback to arXiv. Deterministic.

#### `search_papers(query, max_results=10)`

Dispatches to the configured retrieval backend (`ARI_RETRIEVAL_BACKEND`):
- `"semantic_scholar"` (default) — Semantic Scholar API
- `"alphaxiv"` — AlphaXiv via MCP JSON-RPC over HTTP
- `"both"` — parallel execution with deduplication

#### `set_retrieval_backend(backend)`

Dynamically switch the retrieval backend at runtime. Valid values: `"semantic_scholar"`, `"alphaxiv"`, `"both"`.

#### `collect_references_iterative(experiment_summary, keywords, max_rounds=20, min_papers=10)`

AI Scientist v2-style iterative citation collection. LLM generates search queries and selects relevant papers across multiple rounds.

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
`/workspace`, which the filesystem tools map back to the real directory before
touching it and scrub out of every result.

Inside a BFTS run the `work_dir` argument is not left to the model: `ari.agent.tool_manager` pins the node's real `work_dir` on every filesystem tool. The env fallback cannot serve that role because the MCP server snapshots `ARI_WORK_DIR` at fork time, so per-node updates never reach it — an unpinned call would land in a shared scratch dir the evaluator never reads, and the node would be scored on inherited code.

#### `emit_results(params, measurements, predictions={}, scores={}, provenance={}, units={}, execution=None, file="results.json", work_dir="/workspace")`

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

The optional `provenance` arg is an `{operand: source}` map recorded on the corresponding canonical measurement record and consumed by the claim/metric-correctness gate. Tag an operand `"microbench"` or `"benchmark"` when its value is an empirically **MEASURED** ceiling/peak (so a normalized metric is not flagged as resting on a placeholder), and `"correctness"` or `"reference"` when it is a residual computed against an **independent** reference (so the output is not flagged as unverified). Best-effort; omitted entirely when empty.

The downstream `transform-skill::nodes_to_science_data` populates `configurations[*].parameters` from this file when present (D contract). When `emit_results` is not called, the LLM evaluator's typed split (C contract — see `ari-skill-evaluator::make_metric_spec` below) supplies the same information from artifact analysis.

---

## ari-skill-benchmark

Performance analysis, plotting, and statistical testing. **LLM: No** (deterministic).

### Tools

#### `analyze_results(result_path, metrics)`

Load and analyze CSV, JSON, or NPY result files. Returns summary statistics.

#### `plot(data, plot_type, output_path, title="", xlabel="", ylabel="")`

Generate matplotlib figures. Plot types: `bar`, `line`, `scatter`, `heatmap`.

#### `statistical_test(data_a, data_b, test)`

Run scipy statistical tests: `ttest`, `mannwhitney`, `wilcoxon`.

---

## ari-skill-plot

Scientific figure generator. Two modes: **deterministic** (`generate_figures`, P2-safe matplotlib over a fixed schema) and **LLM-driven** (`generate_figures_llm`, an AI-Scientist-v2-style code-write-and-run path with optional VLM caption pass). **LLM: Mixed** (deterministic + P2-exception).

### Tools

#### `generate_figures(nodes_json_path, output_dir, figures=None, science_data_path="", vlm_captions=True, experiment_context="")`

Render canonical comparison figures from `nodes_tree.json` into `output_dir`.  Returns a manifest of every emitted figure with its caption and source node ids.  Byte-deterministic for a given matplotlib version.

#### `generate_figures_llm(nodes_json_path, output_dir, experiment_summary="", context="", n_figures=3, science_data_path="", vlm_feedback="")`

LLM examines the data shape + natural-language `intent`, writes matplotlib code, runs it in the same `_run_plot_code` sandbox, and (optionally) calls a VLM to caption the result.  P2 exception.

The `kind="plot"` system prompt now enforces a **LAYOUT** rule (call `fig.tight_layout()` and save with `bbox_inches='tight'`, put the legend outside the axes, rotate long tick labels; a figure with overlapping or truncated text is **REJECTED**) and a **COMPARABILITY** rule (do not juxtapose values measured on different scales/regimes without a clear axis or annotation). These are prompt-level guidance to the figure-writing LLM — no new mechanical gate is added.

### Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `VLM_MODEL` | Vision LLM for caption pass | `openai/gpt-4o` |
| `ARI_LLM_MODEL` | LLM that writes matplotlib code in `_llm` mode | (none — required for `_llm`) |
| `LLM_MODEL` | Cross-skill fallback | (none) |
| `ARI_LLM_API_BASE` | LiteLLM API base override | LiteLLM default |
| `OPENAI_API_KEY` | Required for OpenAI-hosted LLM/VLM | (none) |

### ari-core boundary

`src/server.py` imports `from ari import cost_tracker`; Phase 4 of the master refactor migrates this to `ari.public.cost_tracker`.

---

## ari-skill-vlm

Vision-Language model for figure and table quality review. **LLM: Yes** (VLM).

### Tools

#### `review_figure(image_path, context="", criteria=None)`

VLM reviews an experiment figure. Returns score (0-1), issues, suggestions.

#### `review_table(latex_or_path, context="")`

VLM reviews a table (LaTeX source or rendered image). Returns score, issues, suggestions.

Model: `VLM_MODEL` env > `openai/gpt-4o`.

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
