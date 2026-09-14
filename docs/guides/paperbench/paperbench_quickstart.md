---
sources:
  - path: scripts/sc_paper_dogfood.py
    role: doc
  - path: scripts/build_pb_images.sh
    role: doc
  - path: ari-skill-paper-re
    role: implementation
  - path: ari-skill-replicate
    role: implementation
  - path: ari-core/ari/viz/api_paperbench.py
    role: implementation
  - path: ari-core/ari/viz/api_paperbench_worker.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/PaperBench
    role: implementation
  - path: ari-core/config/paperbench_rubrics
    role: config
  - path: report/Makefile
    role: config
last_verified: 2026-08-16
---

# PaperBench quickstart

A 5-minute walkthrough from importing an external paper to viewing its
PaperBench audit score.

## Prerequisites

- ARI installed (`pip install -e ari-core/`).
- The viz server running (`ari viz` or `python -m ari.viz.server`).
- An LLM provider configured in `.env` (e.g. `OPENAI_API_KEY` or
  `GEMINI_API_KEY`).
- For SLURM dispatch: `sbatch` on PATH plus
  [`docs/guides/paperbench/multi_node_setup.md`](multi_node_setup.md).

## 1. Import a paper

Open the dashboard, click the **📚 PaperBench** sidebar entry, then
**📥 Import paper**. Fill in the form (arXiv ID / DOI / upload / local),
then **Save to registry**. The badge under the license input is an
optimistic client-side guess (green only for `MIT` / `Apache*` / `BSD*`
/ `arXiv*` / a bare `CC BY`), so `CC0` and `CC BY-SA` show ⚠ there even
though the server classifies them as usable. The registry row shows the
server's real verdict.

Equivalent CLI:

```bash
curl -X POST http://localhost:8765/api/paperbench/papers/import \
  -H 'Content-Type: application/json' \
  -d '{
    "source_type": "arxiv",
    "source": "2404.14193",
    "title": "LLAMP: assessing latency tolerance",
    "license": "CC BY 4.0",
    "authors": ["Alice", "Bob"]
  }'
```

## 2. Launch the PaperBench wizard

From the registry page, tick one or more papers and click
**🚀 Run PaperBench**. The 5-step wizard walks through:

1. **Papers** — verify your selection.
2. **Rubric** — pick the generator model (default
   `gemini/gemini-2.5-pro`, calibrated `hierarchical-v2` strategy —
   the strategy is not selectable).
   See [Rubric schema](../../reference/execution_profile.md).
3. **Reproduce** — choose the replicator model + time budget +
   sandbox kind (`auto` / `local` / `apptainer` / `docker` / `slurm`) +
   `container_image` (a local non-symlink SIF, full Docker
   `sha256:<image-id>`, or registry URI pinned with `@sha256:<digest>`).
   Expand *Execution profile override*
   to override SLURM allocation flags (`--nodes`, `--ntasks`,
   `--ntasks-per-node`, `--gpus-per-task`, `gpu_type`,
   `memory_gb_per_node`, `--exclusive`, `--constraint`, `--hint`,
   `--nodelist`). `account` / `qos` / `reservation` have no field of
   their own: the grid's free-text `extra_sbatch_args` box accepts only
   `--account=`, `--qos=`, `--reservation=` and `--hint=` entries, which
   the skill translates into the typed fields — any other flag is
   rejected. The wizard fields always start at `0` / `""`; a rubric's
   `execution_profile` is merged server-side in `run_reproduce`, and a
   non-zero wizard field wins over the rubric hint.
4. **Judge** — set the SimpleJudge model + `n_runs` (default 1 — see
   PaperBench paper §4.1). A digest-verified successful Stage 2 record is
   mandatory. `code_only` is an explicit scope choice, never an implicit
   substitute for a missing reproduction.
5. **Launch** — review the cost estimate, then click *Dry run* to verify
   or *Launch all* to enqueue the jobs.

> **Fail-loud preconditions.** Wizard requests sandbox/GPU resources
> the host cannot satisfy fail rather than silently downgrading to host CPU.
> The legacy local fallback has been removed.
> GPU/resource requests have no silent-drop override: correct the cluster
> configuration or select a compatible partition. What the caller sees is
> not a raised exception — `run_reproduce` records the failed attempt and
> returns `{"executed": false, "error": …, "failure_kind": …}` with
> `failure_kind` `"sandbox-unavailable"` (missing container runtime) or
> `"scheduler-failure"` (no `sbatch`, no resolvable partition).
>
> Network denial defaults ON; unisolated local/SLURM execution requires an
> administrator attestation or an explicit `network_policy=inherit` choice.
> The wizard sends neither, so a GUI-launched `local`/`slurm` reproduction
> is rejected at plan time with *"sandbox_kind=… cannot prove network
> denial"*. Reach those two arguments through the `run_reproduce` MCP tool
> or the `_paperbench_bridge.reproduce_submission` entry point instead.

## 3. Wait

The wizard returns one job ID per paper. Open
`#/paperbench/results?job=<job_id>`: the Results page reads
`GET /api/paperbench/run/<job_id>` once for status, then follows the
job over Server-Sent Events on
`GET /api/paperbench/run/<job_id>/logs` until it reaches `completed`,
`failed` or `interrupted`. Typical wall-time: ~30 min for a CPU-only
smoke, several hours for a faithful GPU reproduction.

> A job whose worker died with a viz-server restart is reported with the
> status `interrupted` and is never respawned — relaunch it from the
> wizard.

## 4. Read the score

When status flips to `completed`, the Results page renders the rubric
tree with per-leaf pass/fail colouring and the aggregate ORS score. The
underlying JSON is available at
`GET /api/paperbench/run/<job_id>/results`.

## 5. Generate the audit report (optional)

For a human-readable write-up. `AUDIT_FORMATS` defaults to `pdf` alone,
so ask for HTML explicitly if you want it; `AUDIT_LANGS` defaults to
`en` and `AUDIT_OUTPUT` to `audit/$(PAPER_ID)`:

```bash
make -C report audit-report \
  CHECKPOINT=/var/tmp/ari/.../<checkpoint-id> \
  PAPER_ID=<paper_id> \
  AUDIT_LANGS="en ja zh" \
  AUDIT_FORMATS="pdf html"
```

The same renderer is reachable from the GUI as
`POST /api/paperbench/run/<job_id>/report`, which defaults to
`["pdf", "html", "md"]` and writes under
`{registry_root}/reports/<job_id>/`.

See [`report/scripts/paperbench_report.py`](../../../report/scripts/paperbench_report.py)
for the Python API.

## 6. (Advanced) Switch rubric framing by venue

`generate_rubric` defaults to the original PaperBench framing — direct
children decompose the paper by contribution, leaves grade submission
output. For **paper-audit** research (does the paper itself describe
enough to reproduce?) select a venue-conditioned template via
`paperbench_rubric_id`. Shipped IDs:

- `generic` — back-compat default
- `sc` — six HPC axes (env / data / execution / figures / scaling / conclusion)
- `neurips` — NeurIPS Reproducibility Checklist axes
- `nature` — wet-lab Reporting Summary axes

CLI dogfood (no GUI, no SLURM — calls `generate_rubric_async` directly
through `scripts/sc_paper_dogfood.py`):

```bash
python scripts/sc_paper_dogfood.py \
    --pdf /path/to/sc24_paper.pdf \
    --rubric-template sc \
    --rubric-model gpt-5-mini \
    --target-leaves 30
```

The output `rubric.json` should have exactly six direct children
matching `sc.yaml`'s `top_level_axes`, with leaves phrased as
`"X is identifiable in the paper or AD Appendix"` instead of `"the
implementation does X"`. Both are enforced by prompt instruction only
(`build_skeleton_venue_hint` emits a normative "DO NOT ADD, REMOVE,
RENAME, OR REORDER" block); no validator rejects a rubric whose direct
children drifted, so check `[rubric.summary] direct_children=` in the
script's output. Adding a new venue is a YAML-only change —
see [`rubric_schema.md`](../../reference/rubric_schema.md#venue-conditioned-templates).

## 7. (Advanced) Full 3-stage protocol via CLI

The dogfood script also drives PaperBench's full Stage 1 → Stage 2 →
Stage 3 protocol via the bridge surface
(`ari-skill-paper-re/src/_paperbench_bridge.py`). Stage 1
(`rollout_submission`) runs a vendor BasicAgent / IterativeAgent that
writes `reproduce.sh`. Stage 2 (`reproduce_submission`) executes it in
the chosen sandbox and captures `reproduce.log` + an
`submission_executed_<UTC>.tar.gz` provenance snapshot. Stage 3
(`judge_submission`) grades the executed submission.

```bash
python scripts/sc_paper_dogfood.py \
    --pdf /path/to/paper.pdf \
    --rubric-model gpt-5-mini \
    --with-rollout \
        --rollout-model gpt-5-mini \
        --rollout-time-limit-sec 14400 \
        --rollout-sandbox local \
    --with-reproduction \
        --reproduce-sandbox slurm \
        --reproduce-partition <PARTITION> \
        --reproduce-gpus-per-task 1 \
        --reproduce-time-limit-sec 7200 \
    --judge-dryrun --judge-model gpt-5-mini \
    --out $HOME/.ari_pb_<run_id>
```

Mutually exclusive with `--paper-audit-mode` (and with `paper_audit`
rubric templates such as `sc.yaml` — these grade the paper itself,
not an executed submission). `scripts/build_pb_images.sh` prints the immutable
Docker image IDs. For an Apptainer rollout, first convert the local tag to a
SIF (`apptainer pull pb-env.sif docker-daemon://pb-env:latest`) and pass its
absolute path. Never pass the mutable `pb-env` / `pb-reproducer` tag itself.

## HPC cluster sbatch wrapper (illustrative)

The ARI bridge does NOT auto-load cluster modules — that is the user's
responsibility, following standard HPC practice (NERSC / OLCF / LLNL
all recommend putting `module load` at the TOP of your sbatch script).
The bridge probes `module spider` and `module avail` (read-only, never
`module load`) at rollout start and surfaces the cluster catalog to the
agent as DATA; the agent decides which module
to load. If you want a complete catalog, pre-load
the modules in your sbatch wrapper BEFORE invoking ARI — this is the
canonical HPC pattern.

Example (a two-step-entry Env Modules site — **adjust the module /
partition / GPU spec for YOUR cluster**):

```bash
#!/bin/bash
#SBATCH --partition=<partition>
#SBATCH --gres=gpu:L40S-44GB:1
#SBATCH --cpus-per-task=8
#SBATCH --time=08:00:00
#SBATCH --output=workspace/checkpoints/<ts>_<slug>/sbatch.log
#SBATCH --export=ALL
set -eu

# Pre-load the toolchain modules your paper needs. The names below are
# site specific — replace with your cluster's equivalents (use
# `module avail` on a login node to discover the catalog).
module load <site-entry-module>       # cluster-specific entry module
module load nvhpc                  # if the paper needs CUDA / nvcc
# module load openmpi              # if the paper needs MPI
# module load fftw                 # if the paper needs FFTW

cd /path/to/ARI
python scripts/sc_paper_dogfood.py \
    --pdf /path/to/paper.pdf \
    --rubric-model gpt-5-mini \
    --with-rollout --rollout-model gpt-5-mini \
        --rollout-time-limit-sec 14400 --rollout-sandbox local \
    --with-reproduction --reproduce-sandbox local \
        --reproduce-time-limit-sec 7200 \
    --judge-dryrun --judge-model gpt-5-mini \
    --out workspace/checkpoints/<ts>_<slug>
```

What this gives you:

- The python process inherits the loaded env (PATH includes nvcc, etc).
- The bridge's module probes (`_probe_module_avail`, `_detect_runtime_env`)
  are plain `subprocess.run` calls that inherit that env, so the catalog
  and the `nvcc_path` / `module_path` facts the agent is shown reflect
  what you pre-loaded.

What this does **not** give you — the environment does NOT reach the
agent or the graded script:

- Stage 1's agent shell is scrubbed, not inherited.
  `_compute/computer.py:_agent_environment` builds a fixed dict
  (`PATH=/usr/local/bin:/usr/bin:/bin`, `HOME=<work_dir>/.ari_home`) and
  `LocalComputer.send_shell_command` runs `bash --noprofile --norc -c`.
  The agent therefore does not see your pre-loaded nvcc on PATH, and
  `module` is not even a defined command in its shell unless the agent
  sources the module init itself.
- Stage 2's `reproduce.sh` is scrubbed too.
  `execute_local_attempt` runs it under
  `ari.execution.build_minimal_environment()`: `PATH` reset to
  `/usr/local/bin:/usr/bin:/bin`, `HOME=/nonexistent`, and only
  `LANG`, `LC_ALL`, `SSL_CERT_DIR`, `SSL_CERT_FILE` carried over from
  the parent. The SLURM path submits with `#SBATCH --export=NIL`, which
  is the same story. A `reproduce.sh` without its own `module load`
  chain fails at grade time regardless of what your wrapper loaded.

What this does NOT replace:

- The agent MUST put `module load <NAME>` at the top of
  `submission/reproduce.sh` so the script is portable to grading
  environments (vendor PaperBench eval runs in Docker with no module).
  The bridge's env-truth notes + paper-kind addendum explicitly
  instruct the agent to do this in STEP 2.

If you DO NOT pre-load (Pattern A: minimal sbatch with no module load):

- The bridge still works.
- The agent self-discovers via the `module spider` / `module avail`
  catalog in the env-truth notes and the paper-kind addendum's runbook
  STEP 1.
- Less deterministic — the catalog is whatever the un-extended
  `MODULEPATH` exposes, so on a two-step-entry site the tier-2 modules
  are only visible through the bridge's read-only `module show`
  expansion, and the agent may still fail to load them in its own shell
  and produce a Python proxy of a CUDA paper.
- Use Pattern A for ML / pure-Python papers where toolchain
  pre-loading is unnecessary.

## Next steps

- [Rubric schema + venue templates](../../reference/rubric_schema.md)
- [Execution profile reference](../../reference/execution_profile.md)
- [Multi-node setup](multi_node_setup.md)
- [Compute-node safety conventions](compute_node_safety.md)
- [Troubleshooting](paperbench_troubleshooting.md)
- [PaperBench bridge API](../../reference/api_paperbench.md)
- [Environment variables](../../reference/environment_variables.md)
