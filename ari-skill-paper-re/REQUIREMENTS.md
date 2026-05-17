# ari-skill-paper-re Requirements

## Overview

MCP server that runs **PaperBench-style reproducibility evaluation** against
ari-generated papers. Composed of two stages:

1. **Replicator (`build_reproduce_sh`)** — drives PaperBench's
   `BasicAgent` / `IterativeAgent` solver (vendored, unmodified) against
   ari's HPC sandbox via `_compute.LocalComputer` /
   `_compute.ApptainerComputer`. The agent reads the paper and writes
   `reproduce.sh` plus all source files needed to reproduce the paper's
   main experiment, by repeatedly calling bash / python / file-read tools
   until the time budget is exhausted or the `submit` tool is invoked.

2. **Grader (`grade_with_simplejudge`)** — wraps PaperBench's `SimpleJudge`
   (vendored, unmodified) to score the post-reproduce submission against a
   rubric of per-leaf claim criteria.

## PaperBench parity status

| Methodology axis (PaperBench paper) | ari implementation | Notes |
|---|---|---|
| Agent rollout: ReAct loop, max_steps + time_limit, periodic reminders, sonnet limits, context pruning | `BasicAgentSolver` from vendor, unmodified | identical |
| Tools: bash / python / read-file / search-file / submit | vendor `BashTool`, `PythonTool`, `ReadFileChunk`, `SearchFile`, `SubmitTool` | identical |
| Time budget: 12 h default (paper §5.2); 24 h / 36 h IterativeAgent extended | `replicator_time_limit_sec` (default 43200) | configurable |
| BasicAgent / IterativeAgent split (paper §5.3) | `iterative_agent` flag | identical |
| Reproduction phase: fresh container, reproduce.sh executed (paper §2.2) | `ors_run_reproduce` stage in ari workflow | container substrate differs (Slurm/Apptainer instead of Docker — see "Substrate footnote") |
| Reproduction time cap: 12 h (paper §2.2) | `phase1_max_runtime_sec` (default 43200) | identical |
| SimpleJudge per-leaf grading (paper §4.1) | `_paperbench_bridge.SimpleJudge` | identical |
| Single-pass judging (paper §4.1) | `judge_n_runs` (default 1) | identical at default; ari's >1 is independent variance reduction |
| Weighted leaf → root score aggregation (paper §2.3) | `_paperbench_bridge.aggregate_graded_tree` | identical |
| Negative control: blacklist URL monitor (paper §2.5) | **not implemented** | ari papers have no per-paper blacklist by design |

## Substrate footnote

PaperBench upstream runs Agent Rollout in an Ubuntu 24.04 Docker container
with single-A10 GPU access (paper §5.1) and Reproduction in a fresh VM with
the same image and GPU (§2.2). ari runs both phases on the host's existing
sandbox stack:

* **Local mode**: plain subprocess on the login node (development / smoke).
* **Apptainer / Singularity**: `apptainer exec --bind <work_dir> <image> bash -lc <cmd>`.
* **Slurm**: ari is expected to be running inside an `sbatch` allocation;
  per-tool-call `sbatch` is *not* used because the queueing overhead would
  be fatal at agent-step cadence.
* **GPU**: depends on the partition / image; not enforced by the framework.

PaperBench's `disable_internet()` is a no-op under ari's substrate; outbound
restrictions are expected to come from the cluster network policy. The paper
§2.5 blacklist monitor is post-hoc and not load-bearing for the methodology.

## Tech Stack

* Python 3.13+
* FastMCP (`mcp>=1.0`)
* PaperBench upstream packages, vendored at `vendor/paperbench/`:
  - `paperbench` (solver, judge, monitor, rubric)
  - `nanoeval` (`ComputerTask` / `ComputerInterface` abstractions)
  - `preparedness_turn_completer` (`TurnCompleter` interface)
* Third-party from PyPI / GitHub:
  - `chz` (OpenAI's config framework, github.com/openai/chz)
  - `litellm`, `openai`, `pydantic`, `tiktoken`, `tenacity`, `blobfile`, `structlog`
* `docker` Python SDK is a *transitive* import target (alcatraz module
  loading), but the **Docker daemon is NOT required** — alcatraz's runtime
  is never actually instantiated.

The vendored packages are loaded via `sys.path` injection in `_vendor_path.py`,
not via editable pip installs, to keep the `vendor/` git submodule
unmodified.

## Tool Specifications

### `build_reproduce_sh(...)`
Drive a PaperBench-style ReAct agent against the workspace.
* **Inputs**: `paper_path` / `paper_text`, `rubric_path`, `output_dir`,
  `model`, `time_limit_sec`, `iterative_agent`, `max_steps`,
  `sandbox_kind`, `apptainer_image`, `overwrite`.
* **Output dict**: `populated`, `output_dir`, `files`, `expected_artifacts`,
  `max_runtime_sec`, `model`, `iterative_agent`, `agent_runtime_sec`,
  `notes`, `warnings`, or `skipped_reason` / `error` on the non-success
  paths.

### `run_reproduce(...)`
Execute the rollout's `reproduce.sh` in a fresh sandbox (paper §2.2).
Honors `ARI_PHASE1_SANDBOX` (`auto`/`docker`/`apptainer`/`singularity`/
`slurm`/`local`).

### MPI / multi-node — **Supported via rubric.execution_profile** (v0.7.2+)

(Replaces the pre-v0.7.2 status "Pending Phase 4 wrapping".)

Under `sandbox_kind="slurm"` (v0.7.2+), full SLURM control: `--nodes`,
`--ntasks`, `--ntasks-per-node`, `--nodelist`, `--exclude`, `--exclusive`,
`--gpus-per-task`, `--gpus-per-node`, `--gres=gpu:<type>:N`, `--mem`,
`--mem-per-cpu`, `--constraint`, `--cpu-bind`, `--mem-bind`, `--hint`, and
an `extra_sbatch_args` pass-through for any remaining flag. All args
default to 0 / "" / False / None so legacy single-node call sites stay
byte-identical. When `rubric_path` carries
`reproduce_contract.execution_profile`, every caller arg left at its
default is auto-resolved from the matching profile field (explicit caller
args always win — **supports MPI / multi-node reproduction via rubric.
execution_profile**). See `docs/reference/execution_profile.md` for the
full 21-field schema and example rubrics.

Runtime safety probes (`_is_shared_fs`, `_slurm_has_gres`): repo_dir is
warned about when node-local; `--gres=gpu:<type>:N` is silently dropped
when `sinfo` reports no GRES so the submission is not rejected.

### `grade_with_simplejudge(...)`
Run `SimpleJudge` against the reproduced submission. `n_runs=1` matches
PaperBench paper §4.1; higher values average for variance reduction.

### `fetch_code_bundle(...)`
Materialize an EAR-published code bundle into the workspace. When the
upstream `include_ear=False` toggle is honoured (since v0.6.x), this stage
is disabled and the agent generates the workspace from scratch.

### `generate_rubric(...)`
Produce a TaskNode-format rubric from the paper text + experiment notes.

## Architecture invariants

1. The vendor tree under `vendor/paperbench/` is treated as read-only.
   All ari-specific behaviour lives in `src/`; reach into vendor only via:
   - subclassing (`AriPBSolver`, `LocalPBTask`)
   - context-managed monkey-patching (`_bypass_docker_sanity_check`)
   - `sys.path` injection (`_vendor_path.py`)
   Modifying `vendor/` is *not* allowed by these requirements.

2. The single-shot LLM Replicator that existed up to v0.6.x is removed
   (deleted in v0.7). Replication is exclusively agent-driven.

3. The grader continues to use upstream `SimpleJudge` faithfully — score
   aggregation matches paper §2.3 (weight × passed / Σweight).

4. Per-checkpoint workflow.yaml is authoritative (since v0.6.x cli/core
   fixes); launch-time rewrites (e.g. `include_ear=False`) actually drive
   the paper pipeline.
